from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, SessionLocal
from . import models, schemas, crud
from datetime import date
import csv, io, hashlib

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Budget Web API", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(x_demo_user: str | None = Header(default=None), db: Session = Depends(get_db)):
    email = x_demo_user or "demo@local"
    user = db.query(models.User).filter_by(email=email).first()
    if not user:
        user = models.User(email=email, password_hash="demo")
        db.add(user); db.commit(); db.refresh(user)
        crud.create_default_categories(db, user.id)
        crud.log(db, user.id, "bootstrap", f"Usuario creado: {email}")
    return user

@app.get("/health")
def health(): return {"status": "ok"}

# ── CATEGORIES ──────────────────────────────────────────────
@app.get("/api/categories", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(models.Category).order_by(models.Category.type, models.Category.name).all()

@app.post("/api/categories", response_model=schemas.CategoryOut)
def create_category(payload: schemas.CategoryCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    existing = db.query(models.Category).filter_by(name=payload.name.strip()).first()
    if existing: raise HTTPException(400, "Categoría ya existe")
    cat = models.Category(name=payload.name.strip(), type=payload.type)
    db.add(cat); db.commit(); db.refresh(cat)
    crud.log(db, user.id, "category_create", f"{cat.name} ({cat.type})", "category", cat.id)
    return cat

@app.put("/api/categories/{cat_id}", response_model=schemas.CategoryOut)
def update_category(cat_id: int, payload: schemas.CategoryCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    cat = db.query(models.Category).filter_by(id=cat_id).first()
    if not cat: raise HTTPException(404, "Not found")
    cat.name = payload.name.strip(); cat.type = payload.type
    db.commit(); db.refresh(cat)
    crud.log(db, user.id, "category_update", f"{cat.name}", "category", cat.id)
    return cat

@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    cat = db.query(models.Category).filter_by(id=cat_id).first()
    if not cat: raise HTTPException(404, "Not found")
    db.query(models.Transaction).filter_by(category_id=cat_id).update({"category_id": None})
    db.delete(cat); db.commit()
    crud.log(db, user.id, "category_delete", f"Cat {cat_id}")
    return {"deleted": True}

# ── TRANSACTIONS ─────────────────────────────────────────────
@app.get("/api/transactions", response_model=list[schemas.TxOut])
def list_transactions(month: str | None = None, include_planned: bool = True, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        q = q.filter(models.Transaction.tx_date >= start, models.Transaction.tx_date < end)
    if not include_planned:
        q = q.filter(models.Transaction.planned == False)
    return q.order_by(models.Transaction.tx_date.desc(), models.Transaction.id.desc()).all()

@app.post("/api/transactions", response_model=schemas.TxOut)
def create_transaction(payload: schemas.TxCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    today = date.today()
    tx_date = payload.tx_date if isinstance(payload.tx_date, date) else date.fromisoformat(str(payload.tx_date))
    # Si es planificado y la fecha ya llegó, se hace efectivo automáticamente
    planned = payload.planned if payload.planned is not None else False
    if planned and tx_date <= today:
        planned = False
    tx = models.Transaction(user_id=user.id, planned=planned, **{k: v for k, v in payload.model_dump().items() if k != 'planned'})
    tx.planned = planned
    db.add(tx); db.commit(); db.refresh(tx)
    crud.log(db, user.id, "tx_create", f"{'[PLAN] ' if planned else ''}{tx.description} {tx.amount}", "transaction", tx.id)
    return tx

@app.post("/api/transactions/confirm-planned")
def confirm_planned(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Hace efectivos todos los movimientos planificados cuya fecha ya llegó."""
    today = date.today()
    pending = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.planned == True,
        models.Transaction.tx_date <= today
    ).all()
    for tx in pending:
        tx.planned = False
    db.commit()
    crud.log(db, user.id, "planned_confirm", f"{len(pending)} movimientos confirmados")
    return {"confirmed": len(pending)}

@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    tx = db.query(models.Transaction).filter_by(id=tx_id, user_id=user.id).first()
    if not tx: raise HTTPException(404, "Not found")
    db.delete(tx); db.commit()
    crud.log(db, user.id, "tx_delete", f"Transaction {tx_id}")
    return {"deleted": True}

# ── RULES ────────────────────────────────────────────────────
@app.get("/api/rules")
def list_rules(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(models.Rule).filter_by(user_id=user.id).order_by(models.Rule.priority.desc(), models.Rule.id.desc()).all()

@app.post("/api/rules")
def create_rule(payload: schemas.RuleCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rule = models.Rule(user_id=user.id, **payload.model_dump())
    db.add(rule); db.commit(); db.refresh(rule)
    crud.log(db, user.id, "rule_create", rule.text, "rule", rule.id)
    return {"id": rule.id}

@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rule = db.query(models.Rule).filter_by(id=rule_id, user_id=user.id).first()
    if not rule: raise HTTPException(404, "Not found")
    db.delete(rule); db.commit()
    return {"deleted": True}

@app.post("/api/rules/apply")
def apply_rules(month: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1); end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        q = q.filter(models.Transaction.tx_date >= start, models.Transaction.tx_date < end)
    txs = q.all()
    rules = db.query(models.Rule).filter_by(user_id=user.id).order_by(models.Rule.priority.desc()).all()
    updated = 0
    for tx in txs:
        for rule in rules:
            if rule.tx_type == tx.type and rule.text.lower() in tx.description.lower():
                cat = db.query(models.Category).filter_by(name=rule.category_name).first()
                if not cat:
                    cat = models.Category(name=rule.category_name, type=rule.tx_type)
                    db.add(cat); db.flush()
                tx.category_id = cat.id; updated += 1; break
    db.commit(); crud.log(db, user.id, "rules_apply", f"Aplicadas: {updated}")
    return {"updated": updated}

# ── BUDGETS ──────────────────────────────────────────────────
@app.get("/api/budgets")
def list_budgets(month: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Budget).filter_by(user_id=user.id)
    if month: q = q.filter_by(month=month)
    return q.order_by(models.Budget.month.desc()).all()

@app.post("/api/budgets")
def create_budget(payload: schemas.BudgetCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    budget = db.query(models.Budget).filter_by(user_id=user.id, month=payload.month).first()
    if not budget:
        budget = models.Budget(user_id=user.id, month=payload.month, goal_savings=payload.goal_savings, monthly_limit=payload.monthly_limit)
        db.add(budget)
    else:
        budget.goal_savings = payload.goal_savings; budget.monthly_limit = payload.monthly_limit
    db.commit(); db.refresh(budget)
    crud.log(db, user.id, "budget_upsert", payload.month)
    return budget

@app.get("/api/budgets/breakdown")
def budget_breakdown(month: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    y, m = map(int, month.split("-"))
    start = date(y, m, 1); end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    txs = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.tx_date >= start,
        models.Transaction.tx_date < end,
        models.Transaction.type == "expense",
        models.Transaction.planned == False
    ).all()
    spent_map: dict = {}
    for t in txs:
        cat = db.query(models.Category).filter_by(id=t.category_id).first()
        name = cat.name if cat else "Sin categoría"
        spent_map[name] = spent_map.get(name, 0) + float(t.amount)
    budget = db.query(models.Budget).filter_by(user_id=user.id, month=month).first()
    items = []
    if budget:
        rows = db.query(models.BudgetItem).filter_by(budget_id=budget.id).all()
        for it in rows:
            items.append({"category": it.category_name, "budget": float(it.amount), "spent": float(spent_map.get(it.category_name, 0)), "delta": float(it.amount) - float(spent_map.get(it.category_name, 0))})
    return {"month": month, "items": items}

# ── PLANNER ──────────────────────────────────────────────────
@app.post("/api/planner")
def plan_month(payload: schemas.PlannerRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    Dado un ingreso esperado y los gastos fijos del mes anterior (o definidos),
    calcula cuánto puede destinarse a cada categoría variable.
    """
    # Gastos fijos: media de los últimos 3 meses por categoría (solo movimientos efectivos)
    from datetime import date as dt, timedelta
    today = dt.today()
    # Últimos 3 meses de historial
    months_back = []
    for i in range(1, 4):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12; y -= 1
        months_back.append(f"{y}-{m:02d}")

    fixed_categories: dict[str, float] = {}
    for mon in months_back:
        y2, m2 = map(int, mon.split("-"))
        s = dt(y2, m2, 1)
        e = dt(y2 + (m2 == 12), 1 if m2 == 12 else m2 + 1, 1)
        txs = db.query(models.Transaction).filter(
            models.Transaction.user_id == user.id,
            models.Transaction.type == "expense",
            models.Transaction.planned == False,
            models.Transaction.tx_date >= s,
            models.Transaction.tx_date < e
        ).all()
        for t in txs:
            cat = db.query(models.Category).filter_by(id=t.category_id).first()
            name = cat.name if cat else "Sin categoría"
            fixed_categories[name] = fixed_categories.get(name, 0) + float(t.amount)

    # Media mensual por categoría
    avg_by_cat = {k: round(v / len(months_back), 2) for k, v in fixed_categories.items()}

    # Añadir gastos fijos manuales del payload
    for fc in payload.fixed_expenses:
        avg_by_cat[fc.category] = avg_by_cat.get(fc.category, 0) + fc.amount

    total_fixed = sum(avg_by_cat.values())
    available = payload.expected_income - total_fixed - payload.savings_goal
    available = max(available, 0)

    # Distribuir el disponible entre categorías variables según pesos históricos
    variable_cats = payload.variable_categories if payload.variable_categories else []
    if not variable_cats:
        # Si no especifica, sugerir categorías de gasto que no sean fijas
        all_cats = db.query(models.Category).filter_by(type="expense").all()
        variable_cats = [c.name for c in all_cats if c.name not in avg_by_cat]

    per_variable = round(available / len(variable_cats), 2) if variable_cats else 0

    result_items = []
    for cat, amt in sorted(avg_by_cat.items(), key=lambda x: -x[1]):
        result_items.append({"category": cat, "suggested": amt, "type": "fixed", "source": "histórico"})
    for cat in variable_cats:
        result_items.append({"category": cat, "suggested": per_variable, "type": "variable", "source": "distribuido"})

    return {
        "expected_income": payload.expected_income,
        "savings_goal": payload.savings_goal,
        "total_fixed": round(total_fixed, 2),
        "available_for_variable": round(available, 2),
        "items": result_items
    }

# ── DASHBOARD ────────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard(month: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1); end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        q = q.filter(models.Transaction.tx_date >= start, models.Transaction.tx_date < end)
    txs = q.all()
    effective = [t for t in txs if not t.planned]
    planned = [t for t in txs if t.planned]
    income = sum(float(t.amount) for t in effective if t.type == "income")
    expense = sum(float(t.amount) for t in effective if t.type == "expense")
    planned_expense = sum(float(t.amount) for t in planned if t.type == "expense")
    by_cat: dict = {}
    for t in effective:
        if t.type == "expense" and t.category_id:
            cat = db.query(models.Category).filter_by(id=t.category_id).first()
            name = cat.name if cat else "Sin categoría"
            by_cat[name] = by_cat.get(name, 0) + float(t.amount)
    return {"income": income, "expense": expense, "balance": income - expense, "count": len(effective), "planned_count": len(planned), "planned_expense": planned_expense, "by_category": by_cat}

# ── AUDIT ─────────────────────────────────────────────────────
@app.get("/api/audit-log")
def audit_log(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(models.AuditLog).filter_by(user_id=user.id).order_by(models.AuditLog.id.desc()).limit(200).all()

# ── IMPORTS ──────────────────────────────────────────────────
def normalize_columns(row: dict, mapping: dict | None = None):
    mapping = mapping or {}
    normalized = {k.lower().strip(): v for k, v in row.items()}
    def pick(*keys, default=""):
        for k in keys:
            mk = mapping.get(k, k).lower().strip()
            if mk in normalized and str(normalized[mk]).strip():
                return str(normalized[mk]).strip()
        return default
    return {"date": pick("date","fecha","transaction_date"), "description": pick("description","descripcion","concepto","detalle"), "amount": pick("amount","importe","monto",default="0"), "type": pick("type","tipo"), "category": pick("category","categoria"), "note": pick("note","nota")}

@app.post("/api/imports/csv")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    content = (await file.read()).decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    rows_total = rows_inserted = rows_skipped = 0
    digest = hashlib.sha256(content.encode()).hexdigest()
    if db.query(models.ImportBatch).filter_by(user_id=user.id, hash=digest).first():
        return {"status": "skipped_duplicate_file"}
    seen: set = set()
    for row in reader:
        rows_total += 1
        n = normalize_columns(row)
        d = n["date"]; desc = n["description"]; amt_raw = n["amount"]
        if not d or not desc: rows_skipped += 1; continue
        try:
            amt_val = float(str(amt_raw).replace(".","").replace(",",".")) if "," in str(amt_raw) else float(str(amt_raw))
        except Exception: rows_skipped += 1; continue
        typ = n["type"] or ("income" if amt_val > 0 else "expense")
        fp = f"{d[:10]}|{desc.lower().strip()}|{abs(amt_val):.2f}|{typ}"
        if fp in seen: rows_skipped += 1; continue
        seen.add(fp)
        try:
            tx = models.Transaction(user_id=user.id, tx_date=date.fromisoformat(d[:10]), description=desc[:255], amount=abs(amt_val), type=typ, source="csv", imported=True, note=n["note"] or None, planned=False)
            db.add(tx); rows_inserted += 1
        except Exception: rows_skipped += 1
    batch = models.ImportBatch(user_id=user.id, filename=file.filename or "upload.csv", rows_total=rows_total, rows_inserted=rows_inserted, rows_skipped=rows_skipped, hash=digest)
    db.add(batch); crud.log(db, user.id, "csv_import", f"{file.filename}: {rows_inserted}/{rows_total}")
    db.commit()
    applied = apply_rules(month=None, db=db, user=user)["updated"]
    return {"rows_total": rows_total, "rows_inserted": rows_inserted, "rows_skipped": rows_skipped, "rules_applied": applied}

@app.post("/api/imports/csv/apply-rules")
def import_csv_apply_rules(month: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Transaction).filter_by(user_id=user.id, imported=True)
    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1); end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        q = q.filter(models.Transaction.tx_date >= start, models.Transaction.tx_date < end)
    txs = q.all()
    rules = db.query(models.Rule).filter_by(user_id=user.id).order_by(models.Rule.priority.desc()).all()
    applied = 0
    for tx in txs:
        for rule in rules:
            if rule.tx_type == tx.type and rule.text.lower() in tx.description.lower():
                cat = db.query(models.Category).filter_by(name=rule.category_name).first()
                if not cat:
                    cat = models.Category(name=rule.category_name, type=rule.tx_type)
                    db.add(cat); db.flush()
                tx.category_id = cat.id; applied += 1; break
    db.commit(); crud.log(db, user.id, "import_rules_apply", f"Aplicadas {applied} reglas a importados")
    return {"applied": applied}

@app.post("/api/imports/preview")
async def preview_csv(file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    content = (await file.read()).decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    headers = list(reader.fieldnames or [])
    for i, row in enumerate(reader):
        if i >= 5: break
        rows.append(dict(row))
    return {"headers": headers, "rows": rows}
