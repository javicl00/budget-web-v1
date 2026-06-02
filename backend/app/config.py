from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://budget:budget@localhost:5432/budgetdb"
    cors_origins_raw: str = "http://localhost:5173,http://localhost:8000,http://localhost"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        env_prefix = ""

settings = Settings()
