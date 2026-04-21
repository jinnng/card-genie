"""
爬蟲測試腳本 v2 - 國泰世華 CUBE 卡優惠頁面
執行方式：python3 test_scraper.py
"""
import asyncio
from playwright.async_api import async_playwright

TARGET_URL = "https://www.cathay-cube.com.tw/cathaybk/personal/product/credit-card/cards/cube"


async def test_scrape():
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

        print(f"正在抓取：{TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)

        # 等待動態內容載入
        await page.wait_for_timeout(3000)

        print(f"頁面標題：{await page.title()}\n")

        # 嘗試找優惠相關的區塊
        # 常見的優惠 selector 關鍵字
        selectors_to_try = [
            "section",
            "article",
            "[class*='promo']",
            "[class*='offer']",
            "[class*='benefit']",
            "[class*='privilege']",
            "[class*='reward']",
            "[class*='discount']",
            "[class*='優惠']",
            "[class*='cardInfo']",
            "[class*='card-info']",
            "[class*='feature']",
        ]

        print("--- 找到的區塊 ---")
        for selector in selectors_to_try:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    print(f"selector '{selector}': 找到 {len(elements)} 個元素")
            except Exception:
                pass

        # 抓取完整頁面純文字
        print("\n--- 頁面完整文字（前 2000 字）---")
        content = await page.inner_text("body")
        print(content[:2000])

        # 儲存完整 HTML 供分析
        html = await page.content()
        with open("cube_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n完整 HTML 已儲存至 cube_page.html（{len(html)} 字元）")

        await browser.close()
        print("\n✅ 測試完成")


if __name__ == "__main__":
    asyncio.run(test_scrape())