from __future__ import annotations

import logging

from services.db import get_client

logger = logging.getLogger(__name__)


async def get_or_create_user(line_user_id: str) -> int:
    """
    用 LINE user_id 取得或建立用戶，回傳 user.id
    """
    client = await get_client()

    result = await client.table("users") \
        .select("id") \
        .eq("line_user_id", line_user_id) \
        .limit(1) \
        .execute()

    if result.data:
        return result.data[0]["id"]

    insert = await client.table("users") \
        .insert({"line_user_id": line_user_id}) \
        .execute()

    return insert.data[0]["id"]


async def save_transaction(
    user_id: int,
    amount: float,
    category: str,
    note: str,
    card_used: str | None = None,
) -> dict:
    """
    寫入一筆消費記錄，回傳完整紀錄
    """
    client = await get_client()
    result = await client.table("transactions").insert({
        "user_id": user_id,
        "amount": amount,
        "category": category,
        "note": note,
        "card_used": card_used,
    }).execute()
    return result.data[0]


async def get_weekly_summary(user_id: int) -> dict:
    from datetime import datetime, timedelta, timezone

    client = await get_client()
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    result = await client.table("transactions") \
        .select("amount, category") \
        .eq("user_id", user_id) \
        .gte("created_at", seven_days_ago) \
        .execute()

    summary: dict[str, float] = {}
    for row in result.data:
        cat = row["category"]
        summary[cat] = summary.get(cat, 0) + float(row["amount"])

    return summary
    """
    取得本週消費摘要（依類別加總）
    """
    client = await get_client()
    result = await client.table("transactions") \
        .select("amount, category") \
        .eq("user_id", user_id) \
        .gte("created_at", "now() - interval '7 days'") \
        .execute()

    summary: dict[str, float] = {}
    for row in result.data:
        cat = row["category"]
        summary[cat] = summary.get(cat, 0) + float(row["amount"])

    return summary