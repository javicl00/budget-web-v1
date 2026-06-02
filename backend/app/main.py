from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, SessionLocal
from . import models, schemas, crud
from datetime import date
import csv, io, hashlib

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Budget Web API", version="0.3.0")
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
def health():
    return {"status": "ok"}

@app.get("/api/categories", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(models.Category).order_by(models.Category.type, models.Category.name).all()

@app.post("/api/categories", response_model=schemas.CategoryOut)
def create_category(payload: schemas.CategoryCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    cat = models.Category(name=payload.name.strip(), type=payload.type)
    db.add(cat); db.commit(); db.refresh(cat)
    crud.log(db, user.id, "category_create", f"{cat.name} ({cat.type})", "category", cat.id)
    return cat

@app.get("/api/transactions", response_model=list[schemas.TxOut])
def list_transactions(month: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        q = q.filter(models.Transaction.tx_date >= start, models.Transaction.tx_date < end)
    return q.order_by(models.Transaction.tx_date.desc(), models.Transaction.id.desc()).all()

@app.post("/api/transactions", response_model=schemas.TxOut)
def create_transaction(payload: schemas.TxCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    tx = models.Transaction(user_id=user.id, **payload.model_dump())
    db.add(tx); db.commit(); db.refresh(tx)
    crud.log(db, user.id, "tx_create", f"{tx.description} {tx.amount}", "transaction", tx.id)
    return tx

@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    tx = db.query(models.Transaction).filter_by(id=tx_id, user_id=user.id).first()
    if not tx: raise HTTPException(404, "Not found")
    db.delete(tx); db.commit()
    crud.log(db, user.id, "tx_delete", f"Transaction {tx_id}")
    return {"deleted": True}

@app.get("/api/rules")
def list_rules(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(models.Rule).filter_by(user_id=user.id).order_by(models.Rule.priority.desc(), models.Rule.id.desc()).all()

@app.post("/api/rules")
def create_rule(payload: schemas.RuleCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rule = models.Rule(user_id=user.id, **payload.model_dump())
    db.add(rule); db.commit(); db.refresh(rule)
    crud.log(db, user.id, "rule_create", rule.text, "rule", rule.id)
    return {"id": rule.id}

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
    txs = db.query(models.Transaction).filter(models.Transaction.user_id == user.id, models.Transaction.tx_date >= start, models.Transaction.tx_date < end, models.Transaction.type == "expense").all()
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

@app.get("/api/dashboard")
def dashboard(month: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1); end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        q = q.filter(models.Transaction.tx_date >= start, models.Transaction.tx_date < end)
    txs = q.all()
    income = sum(float(t.amount) for t in txs if t.type == "income")
    expense = sum(float(t.amount) for t in txs if t.type == "expense")
    by_cat: dict = {}
    for t in txs:
        if t.type == "expense" and t.category_id:
            cat = db.query(models.Category).filter_by(id=t.category_id).first()
            name = cat.name if cat else "Sin categoría"
            by_cat[name] = by_cat.get(name, 0) + float(t.amount)
    return {"income": income, "expense": expense, "balance": income - expense, "count": len(txs), "by_category": by_cat}

@app.get("/api/audit-log")
def audit_log(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(models.AuditLog).filter_by(user_id=user.id).order_by(models.AuditLog.id.desc()).limit(200).all()

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
            tx = models.Transaction(user_id=user.id, tx_date=date.fromisoformat(d[:10]), description=desc[:255], amount=abs(amt_val), type=typ, source="csv", imported=True, note=n["note"] or None)
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

@app.post("/api/auth/demo")
def auth_demo(db: Session = Depends(get_db), user=Depends(get_current_user)):
    crud.log(db, user.id, "auth_demo", "Sesión demo solicitada")
    return {"user_id": user.id, "email": user.email}
