from __future__ import annotations

import json
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

CATEGORIES = ["飲食", "超市", "交通", "網購", "娛樂", "醫療", "其他"]

# 超市關鍵字對照
SUPERMARKET_KEYWORDS = ["家樂福", "全聯", "大潤發", "愛買", "costco", "好市多", "頂好", "rt-mart"]

# Regex：「任意文字 數字」或「數字 任意文字」
SIMPLE_PATTERN = re.compile(
    r"^(?P<note>.+?)\s+(?P<amount>\d+(?:\.\d+)?)$|^(?P<amount2>\d+(?:\.\d+)?)\s+(?P<note2>.+)$"
)

FOOD_KEYWORDS = ["早餐", "午餐", "晚餐", "宵夜", "咖啡", "飲料", "便當", "麵", "飯", "滷味",
                 "麥當勞", "肯德基", "漢堡王", "摩斯", "subway", "7-11", "全家", "萊爾富"]

TRANSPORT_KEYWORDS = ["uber", "計程車", "捷運", "公車", "停車", "加油", "高鐵", "台鐵", "油資"]

SHOPPING_KEYWORDS = ["momo", "蝦皮", "pchome", "博客來", "amazon", "網購", "shopee"]

ENTERTAINMENT_KEYWORDS = ["netflix", "spotify", "youtube", "電影", "ktv", "遊戲", "steam"]

MEDICAL_KEYWORDS = ["藥局", "診所", "醫院", "掛號", "藥", "健保"]


def _regex_classify(note: str) -> str:
    note_lower = note.lower()
    for kw in SUPERMARKET_KEYWORDS:
        if kw in note_lower:
            return "超市"
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
    return "飲食"  # 預設：單純數字+文字最常見是飲食


def try_regex_parse(text: str) -> dict | None:
    """
    第一層：Regex 快速解析
    成功回傳 {"amount": float, "category": str, "note": str}
    失敗回傳 None
    """
    m = SIMPLE_PATTERN.match(text.strip())
    if not m:
        return None

    if m.group("note"):
        note = m.group("note").strip()
        amount = float(m.group("amount"))
    else:
        note = m.group("note2").strip()
        amount = float(m.group("amount2"))

    category = _regex_classify(note)
    return {"amount": amount, "category": category, "note": text.strip()}


async def claude_parse(text: str) -> dict | None:
    """
    第二層：Claude API 解析模糊輸入
    成功回傳 {"amount": float, "category": str, "note": str}
    失敗回傳 None
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping Claude parse")
        return None

    prompt = f"""你是一個記帳助理，請從以下訊息中萃取消費資訊。

訊息：「{text}」

請回傳 JSON（只回傳 JSON，不要其他文字）：
{{
  "amount": 數字（金額，找不到則為 0）,
  "category": 類別（只能是：飲食、超市、交通、網購、娛樂、醫療、其他），
  "note": "原始輸入的簡短摘要",
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
            parsed = json.loads(raw)

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
    主入口：先 Regex，失敗再 Claude API
    """
    result = try_regex_parse(text)
    if result:
        logger.info(f"Regex classified: {result}")
        return result

    result = await claude_parse(text)
    if result:
        logger.info(f"Claude classified: {result}")
    return result