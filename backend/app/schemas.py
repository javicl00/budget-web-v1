from pydantic import BaseModel
from typing import Optional
from datetime import date

class CategoryCreate(BaseModel):
    name: str
    type: str

class CategoryOut(BaseModel):
    id: int
    name: str
    type: str
    model_config = {"from_attributes": True}

class TxCreate(BaseModel):
    tx_date: date
    description: str
    amount: float
    type: str
    category_id: Optional[int] = None
    note: Optional[str] = None
    source: Optional[str] = "manual"
    planned: Optional[bool] = False

class TxCategoryUpdate(BaseModel):
    category_id: Optional[int] = None

class TxOut(BaseModel):
    id: int
    tx_date: date
    description: str
    amount: float
    type: str
    category_id: Optional[int] = None
    note: Optional[str] = None
    source: Optional[str] = None
    planned: bool = False
    model_config = {"from_attributes": True}

class RuleCreate(BaseModel):
    text: str
    category_name: str
    tx_type: str
    priority: int = 50

class BudgetCreate(BaseModel):
    month: str
    goal_savings: float = 0
    monthly_limit: float = 0

class FixedExpense(BaseModel):
    category: str
    amount: float

class PlannerRequest(BaseModel):
    expected_income: float
    savings_goal: float = 0
    fixed_expenses: list[FixedExpense] = []
    variable_categories: list[str] = []
