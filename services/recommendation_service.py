from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from services.db import get_client
from services.embedding_service import search_cards_by_categories

logger = logging.getLogger(__name__)


async def get_monthly_summary(user_id: int) -> dict[str, float]:
    """取得過去 30 天各類別消費加總"""
    db = await get_client()
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    result = await db.table("transactions") \
        .select("amount, category") \
        .eq("user_id", user_id) \
        .gte("created_at", thirty_days_ago) \
        .execute()

    summary: dict[str, float] = {}
    for row in result.data:
        cat = row["category"]
        summary[cat] = summary.get(cat, 0) + float(row["amount"])

    return summary


async def get_card_details(card_ids: list[int]) -> list[dict]:
    """根據 card_id 清單取得卡片完整資料"""
    db = await get_client()
    result = await db.table("cards") \
        .select("id, name, bank, rewards") \
        .in_("id", card_ids) \
        .execute()
    return result.data


async def generate_recommendation(
    monthly_summary: dict[str, float],
    candidate_cards: list[dict],
    user_owned_card_ids: list[int],
) -> str:
    """
    用 Claude API 根據消費分析和候選卡片生成推薦說明
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "無法生成推薦，請確認 API 設定。"

    # 整理消費摘要
    total = sum(monthly_summary.values())
    summary_text = "\n".join(
        f"- {cat}：NT${amount:,.0f}（{amount/total*100:.0f}%）"
        for cat, amount in sorted(monthly_summary.items(), key=lambda x: -x[1])
    )

    # 整理候選卡片
    cards_text = "\n".join(
        f"- {c['bank']} {c['name']}：{json.dumps(c['rewards'], ensure_ascii=False)}"
        + ("（用戶已持有）" if c["id"] in user_owned_card_ids else "（可申辦）")
        for c in candidate_cards
    )

    prompt = f"""你是一位專業的信用卡顧問，請根據用戶過去 30 天的消費紀錄，推薦最適合的卡片組合策略。

用戶過去 30 天消費：
{summary_text}
總計：NT${total:,.0f}

可推薦的信用卡（rewards 為各類別回饋百分比）：
{cards_text}

請推薦一個「卡組合策略」，包含：
1. 主力卡（日常消費通吃）
2. 加碼卡（特定類別額外回饋，若有明顯需求）
3. 海外卡（若用戶有海外消費需求）

格式要求：
- 用繁體中文回答
- 每張卡說明為什麼適合這位用戶（結合他的消費習慣）
- 已持有的卡優先推薦，未持有的卡說明「建議申辦」
- 語氣簡潔專業，不超過 200 字
- 不要使用 Markdown 格式"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            return resp.json()["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Recommendation generation error: {e}")
        return "推薦生成失敗，請稍後再試。"


async def check_and_update_usage(user_id: int) -> bool:
    """
    檢查用戶本月是否已使用過消費分析（付費功能鎖）
    回傳 True 表示可以使用，False 表示本月已用過
    """
    db = await get_client()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    result = await db.table("users") \
        .select("last_analysis_at") \
        .eq("id", user_id) \
        .limit(1) \
        .execute()

    if not result.data:
        return True

    last_analysis = result.data[0].get("last_analysis_at")
    if last_analysis and last_analysis >= month_start:
        return False

    # 更新使用時間
    await db.table("users") \
        .update({"last_analysis_at": now.isoformat()}) \
        .eq("id", user_id) \
        .execute()

    return True


async def run_analysis(user_id: int, owned_card_ids: list[int]) -> dict:
    """
    執行完整的消費分析流程
    回傳 {"summary": dict, "recommendation": str, "top_categories": list}
    """
    # 取得消費摘要
    monthly_summary = await get_monthly_summary(user_id)

    if not monthly_summary:
        return {"error": "no_data"}

    # 找出前三大消費類別
    top_categories = sorted(monthly_summary.keys(), key=lambda k: -monthly_summary[k])[:3]

    # RAG：用消費類別搜尋最相關的信用卡
    search_results = await search_cards_by_categories(top_categories, top_k=6)

    if not search_results:
        return {"error": "no_cards"}

    # 取得候選卡片完整資料
    candidate_card_ids = [r["card_id"] for r in search_results]
    candidate_cards = await get_card_details(candidate_card_ids)

    # Claude 生成推薦說明
    recommendation = await generate_recommendation(
        monthly_summary,
        candidate_cards,
        owned_card_ids,
    )

    return {
        "summary": monthly_summary,
        "top_categories": top_categories,
        "recommendation": recommendation,
        "candidate_cards": candidate_cards,
    }