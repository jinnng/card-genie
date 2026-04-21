from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from routers import webhook, user
from services.db import init_db
from services.scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Card Genie API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook.router)
app.include_router(user.router, prefix="/users")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "card-genie"}


@app.post("/admin/send-weekly-report")
async def trigger_weekly_report():
    """手動觸發週報推播（測試用）"""
    from services.scheduler import send_weekly_reports
    await send_weekly_reports()
    return {"status": "ok", "message": "週報推播完成"}


@app.post("/admin/run-scraper")
async def trigger_scraper():
    """手動觸發爬蟲（測試用）"""
    from services.scraper import run_all_scrapers
    await run_all_scrapers()
    return {"status": "ok", "message": "爬蟲執行完成"}