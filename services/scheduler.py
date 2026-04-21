from __future__ import annotations

import logging
import os

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from services.db import get_client
from services.transaction_service import get_weekly_summary

logger = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

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


async def push_message(line_user_id: str, text: str) -> None:
    """用 Push API 主動推播訊息給用戶"""
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": line_user_id,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(LINE_PUSH_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error(f"Push failed for {line_user_id}: {resp.status_code} {resp.text}")


async def build_weekly_summary_text(user_id: int) -> str | None:
    summary = await get_weekly_summary(user_id)
    if not summary:
        return None

    total = sum(summary.values())
    lines = ["📊 本週消費摘要\n"]
    for cat, amount in sorted(summary.items(), key=lambda x: -x[1]):
        emoji = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"{emoji} {cat}　NT${amount:,.0f}")
    lines.append(f"\n💰 合計　NT${total:,.0f}")
    lines.append("\n輸入「本週」可隨時查看明細。")
    return "\n".join(lines)


async def send_weekly_reports() -> None:
    """每週一 9:00 推播消費摘要"""
    logger.info("Weekly report job started")
    client = await get_client()
    result = await client.table("users").select("id, line_user_id").execute()
    users = result.data
    success = 0
    skipped = 0
    for user in users:
        try:
            text = await build_weekly_summary_text(user["id"])
            if text is None:
                skipped += 1
                continue
            await push_message(user["line_user_id"], text)
            success += 1
        except Exception as e:
            logger.error(f"Failed to send report to {user['line_user_id']}: {e}")
    logger.info(f"Weekly report done: {success} sent, {skipped} skipped")


async def run_daily_scraper() -> None:
    """每天凌晨 2:00 執行爬蟲，更新優惠資料"""
    logger.info("Daily scraper job started")
    try:
        from services.scraper import run_all_scrapers
        await run_all_scrapers()
    except Exception as e:
        logger.error(f"Daily scraper failed: {e}")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")

    # 每週一 09:00 推播週報
    scheduler.add_job(
        send_weekly_reports,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_report",
        name="每週消費摘要推播",
        replace_existing=True,
    )

    # 每月 1 號凌晨 02:00 更新優惠資料
    scheduler.add_job(
        run_daily_scraper,
        trigger=CronTrigger(day=1, hour=2, minute=0),
        id="monthly_scraper",
        name="每月優惠爬蟲",
        replace_existing=True,
    )

    return scheduler