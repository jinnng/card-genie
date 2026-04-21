from __future__ import annotations

import json
import logging
import os
from datetime import date

import httpx
from playwright.async_api import async_playwright

from services.db import get_client

logger = logging.getLogger(__name__)

# 各銀行卡片的優惠頁面設定
# card_name 需對應 cards 表的 name 欄位
SCRAPE_TARGETS = [
    {
        "card_name": "CUBE 卡",
        "bank": "國泰世華",
        "url": "https://www.cathay-cube.com.tw/cathaybk/personal/product/credit-card/cards/cube",
    },
]


async def fetch_page_text(url: str) -> str | None:
    """
    用 Playwright 抓取頁面純文字內容
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="zh-TW",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            content = await page.inner_text("body")
            await browser.close()
            return content
    except Exception as e:
        logger.error(f"Playwright fetch failed for {url}: {e}")
        return None


async def parse_promotions_with_claude(card_name: str, bank: str, page_text: str) -> list[dict]:
    """
    把頁面文字交給 Claude，解析成結構化的優惠清單
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set")
        return []

    prompt = f"""以下是 {bank} {card_name} 信用卡頁面的文字內容。
請找出所有「有時間限制的優惠活動」，排除常態性的回饋說明（例如「一般消費 0.3%」這類永久性條款）。

頁面內容：
{page_text[:4000]}

請回傳 JSON 陣列（只回傳 JSON，不要其他文字）：
[
  {{
    "title": "優惠活動標題（簡短）",
    "detail": "優惠內容說明（一到兩句話）",
    "valid_until": "YYYY-MM-DD（找不到則為 null）"
  }}
]

如果找不到任何有時間限制的優惠，回傳空陣列 []。"""

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
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            raw = resp.json()["content"][0]["text"]
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(clean)
    except Exception as e:
        logger.error(f"Claude parse failed: {e}")
        return []


async def get_card_id(card_name: str, bank: str) -> int | None:
    """
    從 cards 表取得 card_id
    """
    client = await get_client()
    result = await client.table("cards") \
        .select("id") \
        .eq("name", card_name) \
        .eq("bank", bank) \
        .limit(1) \
        .execute()
    if result.data:
        return result.data[0]["id"]
    return None


async def upsert_promotions(card_id: int, promotions: list[dict], source_url: str) -> int:
    """
    把解析出的優惠存入 promotions 表
    已過期的優惠自動跳過，重複的標題更新內容
    回傳實際寫入筆數
    """
    client = await get_client()
    today = date.today()
    saved = 0

    for promo in promotions:
        # 過濾已過期
        valid_until = promo.get("valid_until")
        if valid_until:
            try:
                if date.fromisoformat(valid_until) < today:
                    logger.info(f"Skipping expired promotion: {promo['title']}")
                    continue
            except ValueError:
                valid_until = None

        # 檢查是否已存在相同標題
        existing = await client.table("promotions") \
            .select("id") \
            .eq("card_id", card_id) \
            .eq("title", promo["title"]) \
            .execute()

        record = {
            "card_id": card_id,
            "title": promo["title"],
            "detail": promo.get("detail", ""),
            "valid_until": valid_until,
            "source_url": source_url,
        }

        if existing.data:
            await client.table("promotions") \
                .update(record) \
                .eq("id", existing.data[0]["id"]) \
                .execute()
        else:
            await client.table("promotions") \
                .insert(record) \
                .execute()

        saved += 1

    return saved


async def scrape_card(target: dict) -> None:
    """
    爬取單一卡片的優惠頁面，解析後存入資料庫
    """
    card_name = target["card_name"]
    bank = target["bank"]
    url = target["url"]

    logger.info(f"Scraping {bank} {card_name}...")

    # 抓頁面
    page_text = await fetch_page_text(url)
    if not page_text:
        logger.error(f"Failed to fetch page for {bank} {card_name}")
        return

    # Claude 解析
    promotions = await parse_promotions_with_claude(card_name, bank, page_text)
    logger.info(f"Claude found {len(promotions)} promotions for {bank} {card_name}")

    if not promotions:
        return

    # 存入資料庫
    card_id = await get_card_id(card_name, bank)
    if not card_id:
        logger.error(f"Card not found in DB: {bank} {card_name}")
        return

    saved = await upsert_promotions(card_id, promotions, url)
    logger.info(f"Saved {saved} promotions for {bank} {card_name}")


async def run_all_scrapers() -> None:
    """
    執行所有設定的爬蟲目標
    """
    logger.info(f"Starting scraper for {len(SCRAPE_TARGETS)} cards")
    for target in SCRAPE_TARGETS:
        try:
            await scrape_card(target)
        except Exception as e:
            logger.error(f"Scraper error for {target['card_name']}: {e}")
    logger.info("Scraper finished")