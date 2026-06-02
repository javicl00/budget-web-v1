from sqlalchemy.orm import Session
from . import models

DEFAULT_CATEGORIES = [
    ("Alimentación", "expense"), ("Transporte", "expense"), ("Vivienda", "expense"),
    ("Salud", "expense"), ("Ocio", "expense"), ("Ropa", "expense"),
    ("Educación", "expense"), ("Suscripciones", "expense"), ("Otros gastos", "expense"),
    ("Nómina", "income"), ("Freelance", "income"), ("Otros ingresos", "income"),
]

def create_default_categories(db: Session, user_id: int):
    for name, type_ in DEFAULT_CATEGORIES:
        if not db.query(models.Category).filter_by(name=name).first():
            db.add(models.Category(name=name, type=type_))
    db.commit()

def log(db: Session, user_id: int | None, action: str, detail: str, entity_type: str | None = None, entity_id: int | None = None):
    db.add(models.AuditLog(user_id=user_id, action=action, detail=detail, entity_type=entity_type, entity_id=entity_id))
    db.commit()
