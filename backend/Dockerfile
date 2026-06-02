FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
CMD ["bash", "-c", "alembic stamp base 2>/dev/null; alembic upgrade 0001 && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
