from fastapi import APIRouter
from services.db import get_client

router = APIRouter()


@router.get("/")
async def list_users():
    """暫時用於 debug，正式上線前移除"""
    client = await get_client()
    result = await client.table("users").select("*").execute()
    return result.data