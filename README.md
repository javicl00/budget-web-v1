# budget-web-v1

Budget Web App – FastAPI + PostgreSQL + Alembic + Vanilla JS frontend.

## Stack
- **Backend**: FastAPI, SQLAlchemy, Alembic, PostgreSQL
- **Frontend**: Vanilla JS SPA (`frontend/index.html`)
- **Infra**: Docker Compose

## Levantar el proyecto

```bash
docker compose up --build
```

- API: http://localhost:8000
- Health: http://localhost:8000/health
- Docs: http://localhost:8000/docs
- Frontend: abre `frontend/index.html` en el navegador

## Variables de entorno

Ver `docker-compose.yml`. La URL de la base de datos es:
```
DATABASE_URL=postgresql+psycopg://budget:budget@db:5432/budgetdb
```
