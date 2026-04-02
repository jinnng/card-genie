import logging
import os

import httpx

logger = logging.getLogger(__name__)

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


async def reply_message(reply_token: str, text: str) -> None:
    """呼叫 LINE Reply API 回傳訊息"""
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
    """處理單一 LINE event"""
    event_type = event.get("type")

    if event_type == "follow":
        # 用戶加入好友
        reply_token = event["replyToken"]
        await reply_message(
            reply_token,
            "👋 歡迎使用卡管家！\n\n直接傳送消費紀錄就能記帳，例如：\n「早餐 85」\n「家樂福 2340」\n\n輸入「說明」查看所有功能。",
        )

    elif event_type == "message":
        message = event.get("message", {})
        if message.get("type") == "text":
            await handle_text_message(
                reply_token=event["replyToken"],
                user_id=event["source"]["userId"],
                text=message["text"],
            )

    else:
        logger.debug(f"Unhandled event type: {event_type}")


async def handle_text_message(reply_token: str, user_id: str, text: str) -> None:
    """處理文字訊息（第一週：Echo Bot）"""
    # TODO 第 3–4 週替換為記帳解析邏輯
    logger.info(f"Message from {user_id}: {text}")
    await reply_message(reply_token, f"[Echo] {text}")