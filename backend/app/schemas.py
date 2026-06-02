from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional

class UserCreate(BaseModel): email: EmailStr; password: str
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; email: EmailStr; is_active: bool

class CategoryBase(BaseModel): name: str; type: str
class CategoryCreate(CategoryBase): pass
class CategoryOut(CategoryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int

class TxBase(BaseModel):
    tx_date: date; description: str; amount: float; type: str
    category_id: Optional[int] = None; note: Optional[str] = None
    source: str = "manual"; planned: Optional[bool] = False
class TxCreate(TxBase): pass
class TxOut(TxBase):
    model_config = ConfigDict(from_attributes=True)
    id: int; user_id: int; imported: bool; planned: bool
    created_at: Optional[datetime] = None

class RuleCreate(BaseModel): text: str; category_name: str; tx_type: str; priority: int = 50
class BudgetCreate(BaseModel): month: str; goal_savings: float = 0; monthly_limit: float = 0
class ReminderCreate(BaseModel): text: str; reminder_date: date; repeat: str = "none"; priority: int = 3
class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; action: str; detail: str; created_at: Optional[datetime] = None

class FixedExpense(BaseModel): category: str; amount: float
class PlannerRequest(BaseModel):
    expected_income: float
    savings_goal: float = 0
    fixed_expenses: list[FixedExpense] = []
    variable_categories: list[str] = []
