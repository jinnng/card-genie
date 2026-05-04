from __future__ import annotations

import logging
import os

import voyageai

from services.db import get_client

logger = logging.getLogger(__name__)


def get_voyage_client() -> voyageai.AsyncClient:
    api_key = os.environ.get("VOYAGE_API_KEY", "")
    if not api_key:
        raise ValueError("VOYAGE_API_KEY not set")
    return voyageai.AsyncClient(api_key=api_key)


async def embed_text(text: str) -> list[float]:
    """將單一文字向量化"""
    client = get_voyage_client()
    result = await client.embed(
        [text],
        model="voyage-3-lite",
        input_type="document",
    )
    return result.embeddings[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批次向量化多筆文字"""
    client = get_voyage_client()
    result = await client.embed(
        texts,
        model="voyage-3-lite",
        input_type="document",
    )
    return result.embeddings


async def embed_query(query: str) -> list[float]:
    """將查詢文字向量化（用於搜尋）"""
    client = get_voyage_client()
    result = await client.embed(
        [query],
        model="voyage-3-lite",
        input_type="query",
    )
    return result.embeddings[0]


def build_card_document(card: dict) -> str:
    """
    把信用卡資料轉成自然語言文字，供向量化使用
    例如：「國泰世華 CUBE 卡：超市消費回饋 3.0%，飲食消費回饋 1.0%，網購消費回饋 1.0%」
    """
    rewards = card.get("rewards", {})
    reward_parts = []
    for category, rate in rewards.items():
        reward_parts.append(f"{category}消費回饋 {rate}%")

    rewards_text = "、".join(reward_parts) if reward_parts else "一般消費回饋"
    return f"{card['bank']} {card['name']}：{rewards_text}"


async def index_all_cards() -> int:
    """
    把所有信用卡資料向量化，存入 card_documents 表
    回傳成功處理的卡片數量
    """
    db = await get_client()
    result = await db.table("cards").select("id, name, bank, rewards").execute()
    cards = result.data

    if not cards:
        logger.warning("No cards found to index")
        return 0

    # 建立文件文字
    documents = []
    for card in cards:
        doc_text = build_card_document(card)
        documents.append((card["id"], doc_text))

    # 批次向量化
    texts = [doc[1] for doc in documents]
    embeddings = await embed_texts(texts)

    # 寫入資料庫（先清空舊資料再重寫）
    await db.table("card_documents").delete().neq("id", 0).execute()

    records = []
    for (card_id, content), embedding in zip(documents, embeddings):
        records.append({
            "card_id": card_id,
            "content": content,
            "embedding": embedding,
        })

    await db.table("card_documents").insert(records).execute()
    logger.info(f"Indexed {len(records)} card documents")
    return len(records)


async def search_cards_by_query(query: str, top_k: int = 5) -> list[dict]:
    """
    用語意搜尋找出最相關的信用卡
    回傳 [{"card_id": int, "content": str, "similarity": float}]
    """
    query_embedding = await embed_query(query)

    db = await get_client()

    # 使用 pgvector 的餘弦相似度搜尋
    result = await db.rpc(
        "match_card_documents",
        {
            "query_embedding": query_embedding,
            "match_threshold": 0.5,
            "match_count": top_k,
        }
    ).execute()

    return result.data


async def search_cards_by_categories(categories: list[str], top_k: int = 6) -> list[dict]:
    """
    根據多個消費類別搜尋最相關的信用卡
    """
    query = "、".join(categories) + "消費回饋優惠"
    return await search_cards_by_query(query, top_k=top_k)