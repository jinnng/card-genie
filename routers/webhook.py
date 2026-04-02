import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request
from services.line_service import handle_event

logger = logging.getLogger(__name__)
router = APIRouter()


def verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE Webhook 簽名"""
    channel_secret = os.environ["LINE_CHANNEL_SECRET"]
    hash_value = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    import base64
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(...),
):
    body = await request.body()

    if not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(body)
    logger.info(f"Webhook received: {len(payload.get('events', []))} events")

    for event in payload.get("events", []):
        await handle_event(event)

    return {"status": "ok"}