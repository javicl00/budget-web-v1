from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, SessionLocal
from . import models, schemas, crud
from datetime import date
import csv, io, hashlib

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Budget Web API", version="0.6.0")
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
    planned = payload.planned if payload.planned is not None else False
    if planned and tx_date <= today:
        planned = False
    tx = models.Transaction(user_id=user.id, planned=planned, **{k: v for k, v in payload.model_dump().items() if k != 'planned'})
    tx.planned = planned
    db.add(tx); db.commit(); db.refresh(tx)
    crud.log(db, user.id, "tx_create", f"{'[PLAN] ' if planned else ''}{tx.description} {tx.amount}", "transaction", tx.id)
    return tx

@app.patch("/api/transactions/{tx_id}/category")
def update_tx_category(tx_id: int, payload: schemas.TxCategoryUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    tx = db.query(models.Transaction).filter_by(id=tx_id, user_id=user.id).first()
    if not tx: raise HTTPException(404, "Not found")
    tx.category_id = payload.category_id
    db.commit()
    crud.log(db, user.id, "tx_category_update", f"Tx {tx_id} -> cat {payload.category_id}", "transaction", tx_id)
    return {"ok": True}

@app.post("/api/transactions/confirm-planned")
def confirm_planned(db: Session = Depends(get_db), user=Depends(get_current_user)):
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

# ── PLANNER (50/30/20 + historical weights) ──────────────────
@app.post("/api/planner")
def plan_month(payload: schemas.PlannerRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    Estrategia 50/30/20:
      50% necesidades · 30% deseos · 20% ahorro
    Los gastos fijos manuales se muestran con su importe EXACTO y se descuentan
    del bloque de necesidades. El resto del bloque se distribuye por historial.
    """
    from datetime import date as dt

    income = payload.expected_income
    savings_goal = payload.savings_goal if payload.savings_goal > 0 else round(income * 0.20, 2)

    # Bloques 50/30/20
    needs_budget  = round(income * 0.50, 2)
    wants_budget  = round(income * 0.30, 2)
    # Si el ahorro definido > 20%, comprimir wants primero
    actual_savings_pct = savings_goal / income
    if actual_savings_pct > 0.20:
        excess = savings_goal - round(income * 0.20, 2)
        wants_budget = max(0, wants_budget - excess)

    # ── Gastos fijos manuales (importe EXACTO, bloque needs) ──
    fixed_items = []
    fixed_total = 0.0
    for fc in payload.fixed_expenses:
        fixed_items.append({
            "category": fc.category,
            "suggested": round(fc.amount, 2),
            "block": "needs",
            "block_label": "Necesidades (50%)",
            "source": "manual",
            "pct_of_income": round(fc.amount / income * 100, 1)
        })
        fixed_total += fc.amount

    # Presupuesto needs que queda tras gastos fijos manuales
    needs_remaining = max(0, needs_budget - fixed_total)

    # ── Historial últimos 3 meses ─────────────────────────────
    today = dt.today()
    months_back = []
    for i in range(1, 4):
        m = today.month - i; y = today.year
        while m <= 0: m += 12; y -= 1
        months_back.append(f"{y}-{m:02d}")

    NEEDS_KW = {"alquiler","hipoteca","suministros","agua","luz","gas","internet",
                "telefono","teléfono","transporte","alimentacion","alimentación",
                "supermercado","seguros","seguro","salud","farmacia","medico",
                "médico","educacion","educación","comunidad","ibi"}
    WANTS_KW = {"ocio","restaurante","restaurantes","ropa","viaje","viajes",
                "suscripcion","suscripción","deporte","gym","gimnasio","cine",
                "musica","música","juegos","vacaciones","bar","cafeteria",
                "cafetería","regalo","regalos","belleza","estetica","estética"}

    hist_needs: dict[str,float] = {}
    hist_wants: dict[str,float] = {}
    fixed_cat_names = {fc.category.strip().lower() for fc in payload.fixed_expenses}

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
            cat_obj = db.query(models.Category).filter_by(id=t.category_id).first()
            name = (cat_obj.name if cat_obj else "Sin categoría").strip()
            name_l = name.lower()
            # Saltar las que ya están como fijos manuales
            if name_l in fixed_cat_names:
                continue
            amt = float(t.amount)
            if any(k in name_l for k in NEEDS_KW):
                hist_needs[name] = hist_needs.get(name, 0) + amt
            else:
                hist_wants[name] = hist_wants.get(name, 0) + amt

    avg_needs = {k: round(v / len(months_back), 2) for k, v in hist_needs.items()}
    avg_wants = {k: round(v / len(months_back), 2) for k, v in hist_wants.items()}

    # ── Distribuir necesidades históricas dentro de needs_remaining ──
    def distribute(budget: float, hist: dict[str,float], extra: list[str]) -> list[dict]:
        all_cats = list(hist.keys()) + [c for c in extra if c not in hist]
        if not all_cats or budget <= 0:
            return []
        min_w = (sum(hist.values()) / len(hist) * 0.5) if hist else 1.0
        weights = {c: hist.get(c, min_w) for c in all_cats}
        total_w = sum(weights.values()) or 1
        return [
            {"category": c, "suggested": round(budget * weights[c] / total_w, 2),
             "pct": round(weights[c] / total_w * 100, 1)}
            for c in sorted(all_cats, key=lambda x: -weights[x])
        ]

    extra_needs = [c for c in (payload.variable_categories or []) if c.strip().lower() not in {k.lower() for k in avg_wants}]
    extra_wants = [c for c in (payload.variable_categories or []) if c.strip().lower() not in {k.lower() for k in avg_needs}]

    needs_hist_items = distribute(needs_remaining, avg_needs, extra_needs)
    wants_items      = distribute(wants_budget, avg_wants, extra_wants)

    result_items = list(fixed_items)
    for it in needs_hist_items:
        result_items.append({**it, "block": "needs", "block_label": "Necesidades (50%)",
                              "source": "histórico",
                              "pct_of_income": round(it["suggested"] / income * 100, 1)})
    for it in wants_items:
        result_items.append({**it, "block": "wants", "block_label": "Deseos (30%)",
                              "source": "histórico",
                              "pct_of_income": round(it["suggested"] / income * 100, 1)})

    total_needs_real = sum(i["suggested"] for i in result_items if i["block"] == "needs")
    total_wants_real = sum(i["suggested"] for i in result_items if i["block"] == "wants")

    return {
        "expected_income": income,
        "savings_goal": savings_goal,
        "savings_pct": round(savings_goal / income * 100, 1),
        "needs_budget": needs_budget,
        "wants_budget": wants_budget,
        "needs_pct": round(needs_budget / income * 100, 1),
        "wants_pct": round(wants_budget / income * 100, 1),
        "total_needs_suggested": round(total_needs_real, 2),
        "total_wants_suggested": round(total_wants_real, 2),
        "has_history": bool(hist_needs or hist_wants),
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
