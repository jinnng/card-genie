from __future__ import annotations

import logging
import os

import httpx

from services.card_service import (
    add_user_card,
    get_banks,
    get_best_card,
    get_user_cards,
    get_user_state,
    remove_user_card,
    search_cards,
    set_user_state,
)
from services.classifier import parse_expense
from services.transaction_service import get_or_create_user, save_transaction

logger = logging.getLogger(__name__)

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

CATEGORY_EMOJI = {
    "飲食": "🍱",
    "超市": "🛒",
    "交通": "🚌",
    "網購": "📦",
    "娛樂": "🎬",
    "醫療": "💊",
    "服飾": "👕",
    "其他": "📝",
}

HELP_TEXT = """卡管家使用說明

📝 記帳
  早餐 85
  家樂福 2340
  GU 790

📊 查詢
  本週 → 本週消費摘要

💳 信用卡
  我的卡片 → 查看 / 設定持有的卡

❓ 其他
  說明 → 顯示此說明"""


async def reply_message(reply_token: str, text: str) -> None:
    """回覆純文字訊息"""
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(LINE_REPLY_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error(f"LINE reply failed: {resp.status_code} {resp.text}")


async def reply_with_quick_reply(reply_token: str, text: str, options: list[str]) -> None:
    """回覆訊息並附上 Quick Reply 按鈕（LINE 最多 13 個）"""
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{
            "type": "text",
            "text": text,
            "quickReply": {
                "items": [
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": opt[:20],
                            "text": opt,
                        }
                    }
                    for opt in options[:13]
                ]
            }
        }]
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(LINE_REPLY_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error(f"LINE reply failed: {resp.status_code} {resp.text}")


async def handle_event(event: dict) -> None:
    event_type = event.get("type")

    if event_type == "follow":
        await reply_message(
            event["replyToken"],
            "👋 歡迎使用卡管家！\n\n直接傳送消費就能記帳：\n「早餐 85」\n「家樂福 2340」\n\n輸入「說明」查看所有功能。",
        )

    elif event_type == "message":
        message = event.get("message", {})
        if message.get("type") == "text":
            await handle_text_message(
                reply_token=event["replyToken"],
                user_id=event["source"]["userId"],
                text=message["text"].strip(),
            )


async def handle_text_message(reply_token: str, user_id: str, text: str) -> None:
    # 取得用戶狀態，判斷是否在持卡設定流程中
    state = await get_user_state(user_id)

    if state == "setting_cards":
        await handle_card_setting(reply_token, user_id, text)
        return

    # 一般指令
    if text in ("說明", "help"):
        await reply_message(reply_token, HELP_TEXT)
        return

    if text in ("本週", "本周", "這週", "這周"):
        await handle_weekly_summary(reply_token, user_id)
        return

    if text in ("我的卡片", "卡片設定", "信用卡"):
        await handle_show_cards(reply_token, user_id)
        return

    # 記帳解析
    result = await parse_expense(text)

    if not result:
        await reply_message(
            reply_token,
            "請用「品項 金額」的格式記帳\n例如：早餐 85、家樂福 2340\n\n輸入「說明」查看所有功能",
        )
        return

    # 寫入資料庫
    db_user_id = await get_or_create_user(user_id)
    await save_transaction(
        user_id=db_user_id,
        amount=result["amount"],
        category=result["category"],
        note=result["note"],
    )

    # 組合回覆：確認訊息 + 用卡建議
    emoji = CATEGORY_EMOJI.get(result["category"], "📝")
    amount_str = f"NT${result['amount']:,.0f}"
    reply = f"✅ {result['category']} {amount_str}，已記錄 {emoji}"

    best_card = await get_best_card(db_user_id, result["category"])
    if best_card:
        reply += f"\n\n💳 提醒：{best_card['bank']} {best_card['name']} 本類別回饋 {best_card['rate']}%，記得用"

    await reply_message(reply_token, reply)


async def handle_show_cards(reply_token: str, user_id: str) -> None:
    """顯示用戶持卡清單，進入選單式設定模式"""
    db_user_id = await get_or_create_user(user_id)
    cards = await get_user_cards(db_user_id)
    banks = await get_banks()

    if cards:
        card_list = "\n".join(f"• {c['bank']} {c['name']}" for c in cards)
        msg = f"💳 你目前持有的卡片：\n{card_list}\n\n請選擇要新增的發卡銀行，或點「完成」結束"
    else:
        msg = "💳 請選擇你的發卡銀行："

    await set_user_state(user_id, "setting_cards")
    await reply_with_quick_reply(reply_token, msg, banks + ["完成"])


async def handle_card_setting(reply_token: str, user_id: str, text: str) -> None:
    """持卡設定流程：銀行選單 → 卡片選單 → 新增 / 刪除"""

    # 結束設定
    if text in ("完成", "結束", "done"):
        await set_user_state(user_id, None)
        db_user_id = await get_or_create_user(user_id)
        cards = await get_user_cards(db_user_id)
        if cards:
            card_list = "\n".join(f"• {c['bank']} {c['name']}" for c in cards)
            await reply_message(
                reply_token,
                f"✅ 設定完成！\n\n你的卡片：\n{card_list}\n\n記帳時會自動提醒最佳用卡。"
            )
        else:
            await reply_message(reply_token, "設定完成，目前沒有持卡紀錄。")
        return

    db_user_id = await get_or_create_user(user_id)
    banks = await get_banks()

    # 刪除卡片（輸入「－卡片名稱」）
    if text.startswith("－") or text.startswith("-"):
        query = text.lstrip("－").lstrip("-").strip()
        results = await search_cards(query)
        if not results:
            await reply_with_quick_reply(
                reply_token,
                f"找不到「{query}」，請確認卡片名稱",
                banks + ["完成"]
            )
            return
        card = results[0]
        await remove_user_card(db_user_id, card["id"])
        await reply_with_quick_reply(
            reply_token,
            f"✅ 已移除 {card['bank']} {card['name']}\n\n繼續選擇銀行新增，或點「完成」結束",
            banks + ["完成"]
        )
        return

    # 換銀行
    if text == "換銀行":
        await reply_with_quick_reply(reply_token, "請選擇發卡銀行：", banks + ["完成"])
        return

    # 用戶選了銀行名稱 → 列出該銀行卡片
    if text in banks:
        results = await search_cards(text)
        card_names = [c["name"] for c in results]
        await reply_with_quick_reply(
            reply_token,
            f"請選擇 {text} 的卡片：",
            card_names + ["換銀行", "完成"]
        )
        return

    # 用戶選了卡片名稱 → 新增
    results = await search_cards(text)
    if not results:
        await reply_with_quick_reply(
            reply_token,
            f"找不到「{text}」，請重新選擇",
            banks + ["完成"]
        )
        return

    card = results[0]
    added = await add_user_card(db_user_id, card["id"])

    if added:
        await reply_with_quick_reply(
            reply_token,
            f"✅ 已新增 {card['bank']} {card['name']}\n\n繼續選擇銀行新增其他卡片，或點「完成」結束",
            banks + ["完成"]
        )
    else:
        await reply_with_quick_reply(
            reply_token,
            f"「{card['bank']} {card['name']}」已在你的清單中了\n\n繼續選擇銀行，或點「完成」結束",
            banks + ["完成"]
        )


async def handle_weekly_summary(reply_token: str, user_id: str) -> None:
    """本週消費摘要"""
    from services.transaction_service import get_weekly_summary

    db_user_id = await get_or_create_user(user_id)
    summary = await get_weekly_summary(db_user_id)

    if not summary:
        await reply_message(reply_token, "本週還沒有消費記錄，快來記第一筆吧！")
        return

    total = sum(summary.values())
    lines = ["📊 本週消費摘要\n"]
    for cat, amount in sorted(summary.items(), key=lambda x: -x[1]):
        emoji = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"{emoji} {cat}　NT${amount:,.0f}")
    lines.append(f"\n💰 合計　NT${total:,.0f}")

    await reply_message(reply_token, "\n".join(lines))