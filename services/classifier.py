from __future__ import annotations

import json
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

CATEGORIES = ["飲食", "超市", "交通", "網購", "娛樂", "醫療", "服飾", "其他"]

SUPERMARKET_KEYWORDS = ["家樂福", "全聯", "大潤發", "愛買", "costco", "好市多", "頂好", "rt-mart"]

FOOD_KEYWORDS = ["早餐", "午餐", "晚餐", "宵夜", "咖啡", "飲料", "便當", "麵", "飯", "滷味",
                 "麥當勞", "肯德基", "漢堡王", "摩斯", "subway", "7-11", "全家", "萊爾富",
                 "吃", "餐", "食"]

TRANSPORT_KEYWORDS = ["uber", "計程車", "捷運", "公車", "停車", "加油", "高鐵", "台鐵", "油資", "油費"]

SHOPPING_KEYWORDS = ["momo", "蝦皮", "pchome", "博客來", "amazon", "網購", "shopee"]

ENTERTAINMENT_KEYWORDS = ["netflix", "spotify", "youtube", "電影", "ktv", "遊戲", "steam"]

MEDICAL_KEYWORDS = ["藥局", "診所", "醫院", "掛號", "藥", "健保"]

CLOTHING_KEYWORDS = ["衣服", "褲子", "裙子", "鞋子", "包包", "外套", "上衣", "內衣", "襪子",
                     "gu", "zara", "uniqlo", "h&m", "nike", "adidas", "服飾", "穿搭"]

SIMPLE_PATTERN = re.compile(
    r"^(?P<note>.+?)\s+(?P<amount>\d+(?:\.\d+)?)$|^(?P<amount2>\d+(?:\.\d+)?)\s+(?P<note2>.+)$"
)


def _regex_classify(note: str) -> str | None:
    """
    關鍵字比對，找不到明確類別時回傳 None，交給 Claude 判斷
    """
    note_lower = note.lower()

    for kw in SUPERMARKET_KEYWORDS:
        if kw in note_lower:
            return "超市"
    for kw in CLOTHING_KEYWORDS:
        if kw in note_lower:
            return "服飾"
    for kw in FOOD_KEYWORDS:
        if kw in note_lower:
            return "飲食"
    for kw in TRANSPORT_KEYWORDS:
        if kw in note_lower:
            return "交通"
    for kw in SHOPPING_KEYWORDS:
        if kw in note_lower:
            return "網購"
    for kw in ENTERTAINMENT_KEYWORDS:
        if kw in note_lower:
            return "娛樂"
    for kw in MEDICAL_KEYWORDS:
        if kw in note_lower:
            return "醫療"

    return None


async def claude_classify(note: str, amount: float) -> str:
    """
    只問 Claude 類別，金額已由 Regex 取得，省 token
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "其他"

    prompt = f"""請判斷以下消費屬於哪個類別。

消費描述：「{note}」
金額：{amount}

只能從以下類別選一個回答，只回傳類別名稱，不要其他文字：
飲食、超市、交通、網購、娛樂、醫療、服飾、其他"""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 20,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            category = resp.json()["content"][0]["text"].strip()
            if category in CATEGORIES:
                return category
            return "其他"
    except Exception as e:
        logger.error(f"Claude classify error: {e}")
        return "其他"


async def claude_parse(text: str) -> dict | None:
    """
    完整解析：金額和類別都交給 Claude（用於完全無法用 Regex 解析的輸入）
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    prompt = f"""你是一個記帳助理，請從以下訊息中萃取消費資訊。
金額可能是數字（800）或中文（八百、一千兩百），請統一轉換成數字。

訊息：「{text}」

請回傳 JSON（只回傳 JSON，不要其他文字）：
{{
  "amount": 數字（金額，中文數字請轉成阿拉伯數字，找不到則為 0）,
  "category": 類別（只能是：飲食、超市、交通、網購、娛樂、醫療、服飾、其他）,
  "note": "原始輸入",
  "is_expense": true 或 false（這是消費記錄嗎？）
}}"""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            data = resp.json()
            raw = data["content"][0]["text"]
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(clean)

            if not parsed.get("is_expense") or parsed.get("amount", 0) <= 0:
                return None

            return {
                "amount": float(parsed["amount"]),
                "category": parsed.get("category", "其他"),
                "note": text.strip(),
            }
    except Exception as e:
        logger.error(f"Claude parse error: {e}")
        return None


async def parse_expense(text: str) -> dict | None:
    """
    主入口，三層處理：
    1. Regex 取得金額 + 關鍵字命中類別 → 直接回傳，不呼叫 API
    2. Regex 取得金額，但類別不確定 → 只問 Claude 類別（省 token）
    3. Regex 完全無法解析 → 整串交給 Claude 完整判斷
    """
    m = SIMPLE_PATTERN.match(text.strip())

    if m:
        if m.group("note"):
            note = m.group("note").strip()
            amount = float(m.group("amount"))
        else:
            note = m.group("note2").strip()
            amount = float(m.group("amount2"))

        category = _regex_classify(note)

        if category:
            logger.info(f"Regex classified: {note} → {category} NT${amount}")
            return {"amount": amount, "category": category, "note": text.strip()}

        logger.info(f"Regex got amount, asking Claude for category: {note}")
        category = await claude_classify(note, amount)
        return {"amount": amount, "category": category, "note": text.strip()}

    logger.info(f"Regex failed, full Claude parse: {text}")
    return await claude_parse(text)