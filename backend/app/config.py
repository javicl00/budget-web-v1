from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://budget:budget@localhost:5432/budgetdb"
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:8000", "http://localhost"]

    class Config:
        env_file = ".env"

settings = Settings()
