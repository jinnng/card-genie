from __future__ import annotations

import logging
import os

import httpx

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
    "其他": "📝",
}

HELP_TEXT = """卡管家使用說明

記帳：直接傳消費內容
  早餐 85
  家樂福 2340
  計程車 230

查詢：
  本週 → 查看本週消費摘要
  說明 → 顯示此說明"""


async def reply_message(reply_token: str, text: str) -> None:
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
    # 指令處理
    if text in ("說明", "help", "Help"):
        await reply_message(reply_token, HELP_TEXT)
        return

    if text in ("本週", "本周", "這週", "這周"):
        await handle_weekly_summary(reply_token, user_id)
        return

    # 記帳解析
    result = await parse_expense(text)

    if not result:
        await reply_message(
            reply_token,
            "請用「品項 金額」的格式記帳\n例如：早餐 85、家樂福 2340",
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

    # 回覆確認
    emoji = CATEGORY_EMOJI.get(result["category"], "📝")
    amount_str = f"NT${result['amount']:,.0f}"
    reply = f"✅ {result['category']} {amount_str}，已記錄 {emoji}"

    await reply_message(reply_token, reply)


async def handle_weekly_summary(reply_token: str, user_id: str) -> None:
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