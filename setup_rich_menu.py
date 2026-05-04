"""
Rich Menu 設定腳本
執行方式：python3 setup_rich_menu.py

會自動完成：
1. 上傳 line_rich_menu.png 圖片
2. 建立 Rich Menu 並設定 4 個按鈕區塊
3. 設為預設 Rich Menu（所有用戶都會看到）
"""
import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

LINE_API = "https://api.line.me/v2/bot"


def get_headers():
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        print("❌ 找不到 LINE_CHANNEL_ACCESS_TOKEN，請確認 .env 設定")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


async def create_rich_menu() -> str:
    """建立 Rich Menu，回傳 richMenuId"""
    payload = {
        "size": {"width": 2500, "height": 843},
        "selected": True,
        "name": "Card Genie 主選單",
        "chatBarText": "功能選單",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 625, "height": 843},
                "action": {"type": "message", "text": "記帳"},
            },
            {
                "bounds": {"x": 625, "y": 0, "width": 625, "height": 843},
                "action": {"type": "message", "text": "本週摘要"},
            },
            {
                "bounds": {"x": 1250, "y": 0, "width": 625, "height": 843},
                "action": {"type": "message", "text": "卡片設定"},
            },
            {
                "bounds": {"x": 1875, "y": 0, "width": 625, "height": 843},
                "action": {"type": "message", "text": "消費分析"},
            },
        ],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API}/richmenu",
            headers={**get_headers(), "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            print(f"❌ 建立 Rich Menu 失敗：{resp.status_code} {resp.text}")
            sys.exit(1)

        rich_menu_id = resp.json()["richMenuId"]
        print(f"✅ Rich Menu 建立成功：{rich_menu_id}")
        return rich_menu_id


async def upload_image(rich_menu_id: str) -> None:
    """上傳 Rich Menu 圖片"""
    image_path = "line_rich_menu.png"
    if not os.path.exists(image_path):
        print(f"❌ 找不到圖片：{image_path}")
        print("   請確認 line_rich_menu.png 在專案根目錄")
        sys.exit(1)

    with open(image_path, "rb") as f:
        image_data = f.read()

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            headers={**get_headers(), "Content-Type": "image/png"},
            content=image_data,
        )
        if resp.status_code != 200:
            print(f"❌ 上傳圖片失敗：{resp.status_code} {resp.text}")
            sys.exit(1)

        print("✅ 圖片上傳成功")


async def set_default_rich_menu(rich_menu_id: str) -> None:
    """設為預設 Rich Menu"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API}/user/all/richmenu/{rich_menu_id}",
            headers=get_headers(),
        )
        if resp.status_code != 200:
            print(f"❌ 設定預設 Rich Menu 失敗：{resp.status_code} {resp.text}")
            sys.exit(1)

        print("✅ 已設為預設 Rich Menu（所有用戶都會看到）")


async def delete_old_rich_menus(keep_id: str) -> None:
    """刪除舊的 Rich Menu，保留剛建立的"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{LINE_API}/richmenu/list",
            headers=get_headers(),
        )
        if resp.status_code != 200:
            return

        menus = resp.json().get("richmenus", [])
        for menu in menus:
            if menu["richMenuId"] != keep_id:
                await client.delete(
                    f"{LINE_API}/richmenu/{menu['richMenuId']}",
                    headers=get_headers(),
                )
                print(f"🗑  已刪除舊 Rich Menu：{menu['richMenuId']}")


async def main():
    print("=== Card Genie Rich Menu 設定 ===\n")

    # 1. 建立 Rich Menu
    rich_menu_id = await create_rich_menu()

    # 2. 上傳圖片
    await upload_image(rich_menu_id)

    # 3. 刪除舊的（避免堆積）
    await delete_old_rich_menus(rich_menu_id)

    # 4. 設為預設
    await set_default_rich_menu(rich_menu_id)

    print(f"\n🎉 完成！Rich Menu ID：{rich_menu_id}")
    print("重新打開 LINE Bot 對話框，底部應該會出現功能選單。")


if __name__ == "__main__":
    asyncio.run(main())