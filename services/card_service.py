from __future__ import annotations

import logging

from services.db import get_client

logger = logging.getLogger(__name__)


async def search_cards(query: str) -> list[dict]:
    """
    用關鍵字搜尋信用卡（銀行名稱或卡片名稱）
    """
    client = await get_client()
    result = await client.table("cards") \
        .select("id, name, bank, rewards") \
        .or_(f"name.ilike.%{query}%,bank.ilike.%{query}%") \
        .execute()
    return result.data


async def get_all_cards() -> list[dict]:
    """
    取得所有信用卡清單
    """
    client = await get_client()
    result = await client.table("cards") \
        .select("id, name, bank") \
        .order("bank") \
        .execute()
    return result.data


async def get_user_cards(user_id: int) -> list[dict]:
    """
    取得用戶持有的信用卡
    """
    client = await get_client()
    result = await client.table("user_cards") \
        .select("card_id, cards(id, name, bank, rewards)") \
        .eq("user_id", user_id) \
        .execute()
    return [row["cards"] for row in result.data]


async def add_user_card(user_id: int, card_id: int) -> bool:
    """
    新增用戶持卡，已存在則忽略，回傳是否新增成功
    """
    client = await get_client()
    existing = await client.table("user_cards") \
        .select("card_id") \
        .eq("user_id", user_id) \
        .eq("card_id", card_id) \
        .execute()

    if existing.data:
        return False

    await client.table("user_cards") \
        .insert({"user_id": user_id, "card_id": card_id}) \
        .execute()
    return True

async def get_banks() -> list[str]:
    """取得所有不重複的發卡銀行"""
    client = await get_client()
    result = await client.table("cards") \
        .select("bank") \
        .execute()
    banks = list({row["bank"] for row in result.data})
    return sorted(banks)


async def remove_user_card(user_id: int, card_id: int) -> None:
    """
    移除用戶持卡
    """
    client = await get_client()
    await client.table("user_cards") \
        .delete() \
        .eq("user_id", user_id) \
        .eq("card_id", card_id) \
        .execute()


async def get_best_card(user_id: int, category: str) -> dict | None:
    """
    根據消費類別，從用戶持有的卡中找出回饋最高的那張
    回傳 {"name": str, "bank": str, "rate": float}
    """
    cards = await get_user_cards(user_id)
    if not cards:
        return None

    best = None
    best_rate = 0.0

    for card in cards:
        rewards = card.get("rewards", {})
        rate = rewards.get(category) or rewards.get("其他") or 1.0
        if rate > best_rate:
            best_rate = rate
            best = {"name": card["name"], "bank": card["bank"], "rate": rate}

    if best and best_rate > 1.0:
        return best
    return None


async def set_user_state(line_user_id: str, state: str | None) -> None:
    """
    更新用戶對話狀態
    """
    client = await get_client()
    await client.table("users") \
        .update({"state": state}) \
        .eq("line_user_id", line_user_id) \
        .execute()


async def get_user_state(line_user_id: str) -> str | None:
    """
    取得用戶對話狀態
    """
    client = await get_client()
    result = await client.table("users") \
        .select("state") \
        .eq("line_user_id", line_user_id) \
        .limit(1) \
        .execute()

    if result.data:
        return result.data[0].get("state")
    return None