from fastapi import FastAPI
from contextlib import asynccontextmanager
from routers import webhook, user
from services.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="卡管家 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook.router)
app.include_router(user.router, prefix="/users")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "card-genie"}