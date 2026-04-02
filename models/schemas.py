from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class UserCreate(BaseModel):
    line_user_id: str


class User(BaseModel):
    id: int
    line_user_id: str
    state: Optional[str] = None
    created_at: datetime


class TransactionCreate(BaseModel):
    user_id: int
    amount: float
    category: str
    note: Optional[str] = None
    card_used: Optional[str] = None


class Transaction(TransactionCreate):
    id: int
    created_at: datetime