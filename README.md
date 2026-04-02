# 卡管家

LINE Bot 個人財務助理 — 自然語言記帳 + 信用卡使用策略推薦

## 本地開發

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定環境變數
cp .env.example .env
# 填入 LINE_CHANNEL_SECRET、LINE_CHANNEL_ACCESS_TOKEN、SUPABASE_URL、SUPABASE_KEY

# 3. 啟動開發伺服器
uvicorn main:app --reload --port 8000

# 4. 用 ngrok 暴露本地端點（另一個 terminal）
ngrok http 8000
# 把 https://xxxx.ngrok.io/webhook 填進 LINE Developers Console
```

## 專案結構

```
card-genie/
├── main.py              # FastAPI 主程式
├── routers/
│   ├── webhook.py       # LINE Webhook 端點
│   └── user.py          # 用戶相關 API
├── services/
│   ├── line_service.py  # LINE 事件處理 & Reply API
│   └── db.py            # Supabase 連線
├── models/
│   └── schemas.py       # Pydantic 資料模型
├── supabase_init.sql    # 資料庫初始化 SQL
├── Procfile             # Railway 部署設定
└── requirements.txt
```

## 部署（Railway）

1. push 到 GitHub
2. Railway → New Project → Deploy from GitHub repo
3. 設定環境變數（與 .env 相同的四個變數）
4. 部署完成後，把 Railway 的 URL + `/webhook` 填進 LINE Console