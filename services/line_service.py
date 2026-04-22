from __future__ import annotations

import logging
import os

import httpx

from services.card_service import (
    add_user_card,
    get_banks,
    get_best_card,
    get_relevant_promotion,
    get_user_cards,
    get_user_promotions,
    get_user_state,
    remove_user_card,
    search_cards,
    set_user_state,
)
from services.transaction_service import get_or_create_user, save_transaction

logger = logging.getLogger(__name__)

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

CATEGORIES = ["飲食", "超市", "交通", "網購", "娛樂", "醫療", "服飾", "其他"]

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

✏️  記帳 → 選擇類別並輸入金額
📊 本週摘要 → 查看本週消費
💳 卡片設定 → 管理持有的信用卡
📈 消費分析 → 分析消費輪廓（即將推出）

其他指令：
  我的優惠 → 查看持卡限時優惠
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

    # 等待輸入金額
    if state and state.startswith("awaiting_amount:"):
        category = state.split(":", 1)[1]
        await handle_amount_input(reply_token, user_id, text, category)
        return

    # Rich Menu 按鈕對應
    if text == "記帳":
        await handle_start_accounting(reply_token, user_id)
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

    if text in ("我的優惠", "優惠", "最新優惠"):
        await handle_my_promotions(reply_token, user_id)
        return

    if text in ("說明", "help"):
        await reply_message(reply_token, HELP_TEXT)
        return

    # 類別選擇（記帳流程中）
    clean_text = text.split(" ")[-1] if " " in text else text
    if state == "awaiting_category" and clean_text in CATEGORIES:
        text = clean_text  # 統一用純文字處理
        await set_user_state(user_id, f"awaiting_amount:{text}")
        emoji = CATEGORY_EMOJI.get(text, "📝")
        await reply_message(reply_token, f"{emoji} {text}\n\n請輸入金額：")
        return

    # 無法識別的輸入
    await reply_message(
        reply_token,
        "請使用底部選單操作，或輸入「說明」查看功能列表。"
    )


async def handle_start_accounting(reply_token: str, user_id: str) -> None:
    """開始記帳：顯示類別選單"""
    await set_user_state(user_id, "awaiting_category")
    category_options = [f"{CATEGORY_EMOJI[c]} {c}" for c in CATEGORIES]
    await reply_with_quick_reply(
        reply_token,
        "請選擇消費類別：",
        category_options + ["取消"]
    )


async def handle_amount_input(reply_token: str, user_id: str, text: str, category: str) -> None:
    """處理金額輸入"""

    if text == "取消":
        await set_user_state(user_id, None)
        await reply_message(reply_token, "已取消記帳。")
        return

    # 解析金額
    try:
        amount = float(text.replace(",", "").replace("，", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await reply_message(reply_token, "請輸入有效的金額數字，例如：85 或 2340")
        return

    # 寫入資料庫
    await set_user_state(user_id, None)
    db_user_id = await get_or_create_user(user_id)
    await save_transaction(
        user_id=db_user_id,
        amount=amount,
        category=category,
        note=f"{category} {amount:.0f}",
    )

    # 組合回覆：確認 + 用卡建議 + 相關優惠
    emoji = CATEGORY_EMOJI.get(category, "📝")
    amount_str = f"NT${amount:,.0f}"
    reply = f"✅ {category} {amount_str}，已記錄 {emoji}"

    best_card = await get_best_card(db_user_id, category)
    if best_card:
        reply += f"\n\n💳 提醒：{best_card['bank']} {best_card['name']} 本類別回饋 {best_card['rate']}%，記得用"

        promo = await get_relevant_promotion(db_user_id, category, best_card["name"])
        if promo:
            valid_str = f"，活動至 {promo['valid_until']}" if promo.get("valid_until") else ""
            reply += f"\n🎁 限時優惠：{promo['title']}{valid_str}"

    await reply_message(reply_token, reply)


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
    """持卡設定流程：銀行選單 → 卡片選單 → 新增 / 刪除"""

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
        await reply_message(reply_token, "本週還沒有消費記錄，點底部選單「記帳」開始記錄吧！")
        return

    total = sum(summary.values())
    lines = ["📊 本週消費摘要\n"]
    for cat, amount in sorted(summary.items(), key=lambda x: -x[1]):
        emoji = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"{emoji} {cat}　NT${amount:,.0f}")
    lines.append(f"\n💰 合計　NT${total:,.0f}")

    await reply_message(reply_token, "\n".join(lines))