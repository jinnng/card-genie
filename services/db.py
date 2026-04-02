import logging
import os

from supabase import AsyncClient, acreate_client

logger = logging.getLogger(__name__)

_client: AsyncClient | None = None


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = await acreate_client(url, key)
    return _client


async def init_db() -> None:
    """應用啟動時驗證資料庫連線"""
    try:
        client = await get_client()
        await client.table("users").select("count").limit(1).execute()
        logger.info("Supabase connected ✓")
    except Exception as e:
        logger.warning(f"Supabase init warning: {e}")