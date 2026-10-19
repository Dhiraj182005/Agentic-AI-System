from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    SECRET_KEY: str = "change-me-in-production"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/aidebate"
    REDIS_URL: str = "redis://redis:6379/0"

    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: int = 60

    EVIDENCE_PROVIDER: str = "tavily"
    TAVILY_API_KEY: str = ""
    SERPAPI_API_KEY: str = ""
    GOOGLE_FACT_CHECK_API_KEY: str = ""

    # Minimum gap between the top two final agent scores required to declare
    # a winner; closer scores produce a tie (Module 11 judge).
    JUDGE_MIN_SCORE_GAP: float = 0.5

    FRONTEND_URL: str = "http://localhost:5173"

    JWT_SECRET_KEY: str = "change-me-in-development"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
