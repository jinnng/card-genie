from __future__ import annotations

import json
import logging
import os

import httpx

from services.card_service import (
    add_user_card,
    get_banks,
    get_user_cards,
    get_user_promotions,
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

HELP_TEXT = """Card Genie 使用說明

請使用底部選單操作：

✏️  記帳 → 輸入消費內容
📊 本週摘要 → 查看本週消費
💳 卡片設定 → 管理持有的信用卡
📈 消費分析 → 分析消費輪廓（即將推出）

其他指令：
  我的優惠 → 查看持卡限時優惠
  說明 → 顯示此說明"""

ACCOUNTING_GUIDE = """請輸入消費內容，例如：

• 家樂福 2340
• 麥當勞85
• Uber 150"""


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
    """回覆訊息並附上 Quick Reply 按鈕"""
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


async def reply_payment_flex(
    reply_token: str,
    category: str,
    amount: float,
    note: str,
    user_cards: list[dict],
) -> None:
    """回覆 Flex Message 付款方式選擇"""
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    emoji = CATEGORY_EMOJI.get(category, "📝")
    amount_str = f"NT${amount:,.0f}"

    # 建立付款方式按鈕
    payment_buttons = []

    # 現金
    payment_buttons.append({
        "type": "button",
        "action": {
            "type": "message",
            "label": "💵 現金",
            "text": f"付款:現金",
        },
        "style": "secondary",
        "height": "sm",
    })

    # 簽帳金融卡
    payment_buttons.append({
        "type": "button",
        "action": {
            "type": "message",
            "label": "🏧 簽帳金融卡",
            "text": f"付款:簽帳金融卡",
        },
        "style": "secondary",
        "height": "sm",
    })

    # 用戶持有的信用卡
    for card in user_cards[:8]:  # 最多 8 張避免過長
        card_label = f"{card['bank']} {card['name']}"
        payment_buttons.append({
            "type": "button",
            "action": {
                "type": "message",
                "label": card_label[:20],
                "text": f"付款:{card_label}",
            },
            "style": "primary",
            "height": "sm",
        })

    # 取消按鈕
    payment_buttons.append({
        "type": "button",
        "action": {
            "type": "message",
            "label": "取消",
            "text": "取消記帳",
        },
        "style": "secondary",
        "height": "sm",
        "color": "#aaaaaa",
    })

    flex_message = {
        "type": "flex",
        "altText": f"{emoji} {category} {amount_str} — 請選擇付款方式",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{emoji} {category}",
                        "weight": "bold",
                        "size": "lg",
                        "color": "#ffffff",
                    },
                    {
                        "type": "text",
                        "text": amount_str,
                        "size": "xxl",
                        "weight": "bold",
                        "color": "#ffffff",
                    },
                    {
                        "type": "text",
                        "text": note,
                        "size": "sm",
                        "color": "#ffffff99",
                        "wrap": True,
                    },
                ],
                "backgroundColor": "#3b82f6",
                "paddingAll": "16px",
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "請選擇付款方式",
                        "weight": "bold",
                        "size": "sm",
                        "color": "#666666",
                        "margin": "none",
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": payment_buttons,
                        "spacing": "sm",
                        "margin": "md",
                    },
                ],
                "paddingAll": "16px",
            },
        },
    }

    payload = {
        "replyToken": reply_token,
        "messages": [flex_message],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(LINE_REPLY_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error(f"LINE flex reply failed: {resp.status_code} {resp.text}")


async def handle_event(event: dict) -> None:
    event_type = event.get("type")

    if event_type == "follow":
        await reply_message(
            event["replyToken"],
            "👋 歡迎使用 Card Genie！\n\n請使用底部選單開始記帳，或輸入「說明」查看所有功能。",
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
    state = await get_user_state(user_id)

    # 持卡設定流程
    if state == "setting_cards":
        await handle_card_setting(reply_token, user_id, text)
        return

    # 等待付款方式選擇
    if state and state.startswith("awaiting_payment:"):
        await handle_payment_selection(reply_token, user_id, text, state)
        return

    # 等待記帳輸入
    if state == "awaiting_expense":
        if text == "取消記帳":
            await set_user_state(user_id, None)
            await reply_message(reply_token, "已取消記帳。")
            return
        await handle_expense_input(reply_token, user_id, text)
        return

    # Rich Menu 按鈕
    if text == "記帳":
        await set_user_state(user_id, "awaiting_expense")
        await reply_message(reply_token, ACCOUNTING_GUIDE)
        return

    if text in ("本週摘要", "本週", "本周", "這週", "這周"):
        await handle_weekly_summary(reply_token, user_id)
        return

    if text in ("卡片設定", "我的卡片", "信用卡"):
        await handle_show_cards(reply_token, user_id)
        return

    if text == "消費分析":
        await reply_message(
            reply_token,
            "📈 消費分析功能即將推出！\n\n將根據你的消費輪廓推薦最適合的卡片組合，敬請期待。"
        )
        return

    if text in ("我的優惠", "優惠"):
        await handle_my_promotions(reply_token, user_id)
        return

    if text in ("說明", "help"):
        await reply_message(reply_token, HELP_TEXT)
        return

    if text == "取消記帳":
        await set_user_state(user_id, None)
        await reply_message(reply_token, "已取消記帳。")
        return

    # 非狀態下的任意輸入，嘗試解析為記帳
    result = await parse_expense(text)
    if result:
        await show_payment_selection(reply_token, user_id, result)
        return

    await reply_message(
        reply_token,
        "請使用底部選單操作，或輸入「說明」查看功能列表。"
    )


async def handle_expense_input(reply_token: str, user_id: str, text: str) -> None:
    """在 awaiting_expense 狀態下處理記帳輸入"""

    # 如果用戶在記帳流程中又點了其他功能，重置狀態並處理對應指令
    if text == "記帳":
        await reply_message(reply_token, ACCOUNTING_GUIDE)
        return

    if text in ("本週摘要", "本週", "本周"):
        await set_user_state(user_id, None)
        await handle_weekly_summary(reply_token, user_id)
        return

    if text in ("卡片設定", "我的卡片"):
        await set_user_state(user_id, None)
        await handle_show_cards(reply_token, user_id)
        return

    if text == "消費分析":
        await set_user_state(user_id, None)
        await reply_message(reply_token, "📈 消費分析功能即將推出！")
        return

    if text in ("說明", "help"):
        await set_user_state(user_id, None)
        await reply_message(reply_token, HELP_TEXT)
        return
    result = await parse_expense(text)

    if not result:
        await reply_message(
            reply_token,
            "無法解析消費內容，請重新輸入，例如：\n家樂福 2340\n麥當勞85"
        )
        return

    await show_payment_selection(reply_token, user_id, result)


async def show_payment_selection(reply_token: str, user_id: str, result: dict) -> None:
    """顯示付款方式 Flex Message，並儲存待確認的記帳資料到 state"""
    db_user_id = await get_or_create_user(user_id)
    user_cards = await get_user_cards(db_user_id)

    # 把記帳資料暫存到 state
    state_data = json.dumps({
        "amount": result["amount"],
        "category": result["category"],
        "note": result["note"],
    }, ensure_ascii=False)
    await set_user_state(user_id, f"awaiting_payment:{state_data}")

    await reply_payment_flex(
        reply_token,
        category=result["category"],
        amount=result["amount"],
        note=result["note"],
        user_cards=user_cards,
    )


async def handle_payment_selection(reply_token: str, user_id: str, text: str, state: str) -> None:
    """處理付款方式選擇，寫入資料庫"""

    if text == "取消記帳":
        await set_user_state(user_id, None)
        await reply_message(reply_token, "已取消記帳。")
        return

    if not text.startswith("付款:"):
        # 非付款選擇的輸入，忽略並提示
        await reply_message(reply_token, "請點選上方的付款方式按鈕。")
        return

    payment = text.replace("付款:", "").strip()

    # 解析暫存的記帳資料
    try:
        state_data = state.replace("awaiting_payment:", "", 1)
        expense = json.loads(state_data)
    except Exception:
        await set_user_state(user_id, None)
        await reply_message(reply_token, "記帳資料遺失，請重新記帳。")
        return

    # 清除狀態
    await set_user_state(user_id, None)

    # 寫入資料庫
    db_user_id = await get_or_create_user(user_id)
    await save_transaction(
        user_id=db_user_id,
        amount=expense["amount"],
        category=expense["category"],
        note=expense["note"],
        card_used=payment,
    )

    emoji = CATEGORY_EMOJI.get(expense["category"], "📝")
    amount_str = f"NT${expense['amount']:,.0f}"
    await reply_message(
        reply_token,
        f"✅ {expense['category']} {amount_str}，已記錄 {emoji}\n💳 付款方式：{payment}"
    )


async def handle_my_promotions(reply_token: str, user_id: str) -> None:
    """查詢用戶所有持卡的有效優惠"""
    db_user_id = await get_or_create_user(user_id)
    cards_with_promos = await get_user_promotions(db_user_id)

    if not cards_with_promos:
        cards = await get_user_cards(db_user_id)
        if not cards:
            await reply_message(
                reply_token,
                "你還沒有設定持有的信用卡。\n請使用底部選單「卡片設定」開始設定。"
            )
        else:
            await reply_message(
                reply_token,
                "目前你的卡片沒有進行中的限時優惠。\n每月初會自動更新最新優惠資訊。"
            )
        return

    lines = ["🎁 你的卡片限時優惠\n"]
    for card_data in cards_with_promos:
        lines.append(f"💳 {card_data['bank']} {card_data['card_name']}")
        for promo in card_data["promotions"]:
            valid_str = f"（至 {promo['valid_until']}）" if promo.get("valid_until") else ""
            lines.append(f"  • {promo['title']}{valid_str}")
            if promo.get("detail"):
                lines.append(f"    {promo['detail']}")
        lines.append("")

    await reply_message(reply_token, "\n".join(lines).strip())


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
    """持卡設定流程"""
    if text in ("完成", "結束", "done"):
        await set_user_state(user_id, None)
        db_user_id = await get_or_create_user(user_id)
        cards = await get_user_cards(db_user_id)
        if cards:
            card_list = "\n".join(f"• {c['bank']} {c['name']}" for c in cards)
            await reply_message(
                reply_token,
                f"✅ 設定完成！\n\n你的卡片：\n{card_list}\n\n記帳時會自動顯示你的卡片供選擇。"
            )
        else:
            await reply_message(reply_token, "設定完成，目前沒有持卡紀錄。")
        return

    db_user_id = await get_or_create_user(user_id)
    banks = await get_banks()

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
        from services.card_service import remove_user_card
        await remove_user_card(db_user_id, card["id"])
        await reply_with_quick_reply(
            reply_token,
            f"✅ 已移除 {card['bank']} {card['name']}",
            banks + ["完成"]
        )
        return

    if text == "換銀行":
        await reply_with_quick_reply(reply_token, "請選擇發卡銀行：", banks + ["完成"])
        return

    if text in banks:
        results = await search_cards(text)
        card_names = [c["name"] for c in results]
        await reply_with_quick_reply(
            reply_token,
            f"請選擇 {text} 的卡片：",
            card_names + ["換銀行", "完成"]
        )
        return

    results = await search_cards(text)
    if not results:
        await reply_with_quick_reply(
            reply_token,
            f"找不到「{text}」，請重新選擇",
            banks + ["完成"]
        )
        return

    card = results[0]
    from services.card_service import add_user_card
    added = await add_user_card(db_user_id, card["id"])

    if added:
        await reply_with_quick_reply(
            reply_token,
            f"✅ 已新增 {card['bank']} {card['name']}\n\n繼續選擇銀行或點「完成」結束",
            banks + ["完成"]
        )
    else:
        await reply_with_quick_reply(
            reply_token,
            f"「{card['bank']} {card['name']}」已在清單中\n\n繼續選擇銀行或點「完成」結束",
            banks + ["完成"]
        )


async def handle_weekly_summary(reply_token: str, user_id: str) -> None:
    """本週消費摘要"""
    from services.transaction_service import get_weekly_summary

    db_user_id = await get_or_create_user(user_id)
    summary = await get_weekly_summary(db_user_id)

    if not summary:
        await reply_message(reply_token, "本週還沒有消費記錄，點底部選單「記帳」開始記錄吧！")
        return

    total = sum(summary.values())
    lines = ["📊 本週消費摘要\n"]
    for cat, amount in sorted(summary.items(), key=lambda x: -x[1]):
        emoji = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"{emoji} {cat}　NT${amount:,.0f}")
    lines.append(f"\n💰 合計　NT${total:,.0f}")

    await reply_message(reply_token, "\n".join(lines))