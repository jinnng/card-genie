-- 卡管家 初始化 Schema v1.0
-- 在 Supabase SQL Editor 執行此檔案

-- 1. 用戶表
create table if not exists users (
  id           bigserial primary key,
  line_user_id text unique not null,
  state        text,                    -- 對話狀態機，例如 'awaiting_card_input'
  created_at   timestamptz default now()
);

-- 2. 消費記錄表
create table if not exists transactions (
  id          bigserial primary key,
  user_id     bigint references users(id) on delete cascade,
  amount      numeric(10, 2) not null,
  category    text not null,            -- 飲食/超市/交通/網購/娛樂/醫療/其他
  note        text,                     -- 原始輸入文字，例如「家樂福 2340」
  card_used   text,                     -- 使用的卡片名稱
  created_at  timestamptz default now()
);

-- 3. 信用卡資料表
create table if not exists cards (
  id          bigserial primary key,
  name        text not null,            -- 例如「國泰世華 CUBE 卡」
  bank        text not null,            -- 例如「國泰世華」
  rewards     jsonb not null default '{}',  -- 彈性 JSON，各銀行結構不同
  updated_at  timestamptz default now()
);

-- 4. 用戶持卡關聯表
create table if not exists user_cards (
  user_id  bigint references users(id) on delete cascade,
  card_id  bigint references cards(id) on delete cascade,
  primary key (user_id, card_id)
);

-- 5. 優惠活動表
create table if not exists promotions (
  id          bigserial primary key,
  card_id     bigint references cards(id) on delete cascade,
  title       text not null,
  detail      text,
  valid_until date,
  source_url  text,
  created_at  timestamptz default now()
);

-- 索引：加速常見查詢
create index if not exists idx_transactions_user_id on transactions(user_id);
create index if not exists idx_transactions_created_at on transactions(created_at);
create index if not exists idx_promotions_card_id on promotions(card_id);
create index if not exists idx_promotions_valid_until on promotions(valid_until);

-- 啟用 Row Level Security（之後視需求設定 policy）
alter table users enable row level security;
alter table transactions enable row level security;
alter table cards enable row level security;
alter table user_cards enable row level security;
alter table promotions enable row level security;