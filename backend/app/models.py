from sqlalchemy import String, Date, DateTime, ForeignKey, Numeric, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Timestamped:
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class User(Base, Timestamped):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Category(Base, Timestamped):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(20), index=True)

class Transaction(Base, Timestamped):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    tx_date: Mapped[Date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    type: Mapped[str] = mapped_column(String(20), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    imported: Mapped[bool] = mapped_column(Boolean, default=False)

class Rule(Base, Timestamped):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(String(255), index=True)
    category_name: Mapped[str] = mapped_column(String(120))
    tx_type: Mapped[str] = mapped_column(String(20))
    priority: Mapped[int] = mapped_column(default=50)

class Budget(Base, Timestamped):
    __tablename__ = "budgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    goal_savings: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    monthly_limit: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

class BudgetItem(Base, Timestamped):
    __tablename__ = "budget_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id"), index=True)
    category_name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

class Reminder(Base, Timestamped):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(String(255))
    reminder_date: Mapped[Date] = mapped_column(Date, index=True)
    repeat: Mapped[str] = mapped_column(String(20), default="none")
    priority: Mapped[int] = mapped_column(default=3)

class AuditLog(Base, Timestamped):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    detail: Mapped[str] = mapped_column(String(500))
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(nullable=True)

class ImportBatch(Base, Timestamped):
    __tablename__ = "imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    rows_total: Mapped[int] = mapped_column(default=0)
    rows_inserted: Mapped[int] = mapped_column(default=0)
    rows_skipped: Mapped[int] = mapped_column(default=0)
    hash: Mapped[str] = mapped_column(String(128), index=True)
