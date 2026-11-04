from pydantic_settings import BaseSettings
from functools import lru_cache
from pydantic import model_validator
from urllib.parse import urlparse


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
    # Comma-separated Groq models used, in order, when the current model's
    # DAILY quota (tokens or requests per day) is exhausted. Same provider and
    # key; each model has its own quota. Empty = no fallback.
    GROQ_FALLBACK_MODELS: str = ""
    LLM_TIMEOUT_SECONDS: int = 60
    # Retries for transient provider failures (rate limits, 5xx, timeouts,
    # connection errors): exponential backoff with jitter, Retry-After honored.
    # A provider wait longer than LLM_RETRY_MAX_DELAY_SECONDS fails fast.
    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_BASE_DELAY_SECONDS: float = 1.0
    # Per-minute token limits (e.g. Groq on-demand TPM) reset within 60 s.
    LLM_RETRY_MAX_DELAY_SECONDS: float = 60.0
    # Reasoning models (e.g. openai/gpt-oss-*) spend output tokens on hidden
    # reasoning. When an answer comes back empty because the budget ran out,
    # the request is retried with a doubled budget up to this ceiling.
    LLM_MAX_OUTPUT_TOKENS_CEILING: int = 8192
    # Output token budget for one debate turn (reasoning + visible answer).
    DEBATE_MAX_RESPONSE_TOKENS: int = 2048
    # Word limits per turn type (all structured fields together).
    DEBATE_OPENING_WORD_LIMIT: int = 200
    DEBATE_REBUTTAL_WORD_LIMIT: int = 180
    DEBATE_CLOSING_WORD_LIMIT: int = 160
    # Panel and budget limits. Turns = agents x rounds; the token estimate is
    # turns x (prompt estimate + DEBATE_MAX_RESPONSE_TOKENS).
    DEBATE_MAX_AGENTS: int = 6
    DEBATE_MAX_SPECIALISTS: int = 3
    DEBATE_MAX_TURNS: int = 40
    DEBATE_TOKEN_BUDGET: int = 250000
    # Post-debate analysis: extract claims, search evidence (Tavily) and verify
    # up to ANALYSIS_MAX_VERIFIED_CLAIMS factual claims, then generate the
    # verdict. Runs automatically after a debate when it was created with
    # "verify evidence"; Regenerate verdict runs any missing stages.
    AUTO_ANALYSIS_AFTER_DEBATE: bool = True
    ANALYSIS_MAX_VERIFIED_CLAIMS: int = 0  # zero = all factual claims
    ANALYSIS_MESSAGE_CONCURRENCY: int = 1
    # A run still marked "running" after this long is treated as abandoned.
    ANALYSIS_STALE_SECONDS: int = 1200
    # Identical topic analyses are served from Redis for this long, so
    # re-requests (typing, refreshes) do not repeat the LLM call.
    RECOMMENDATION_CACHE_TTL_SECONDS: int = 900
    # A running debate refreshes a Redis heartbeat with this TTL. A 'running'
    # debate whose heartbeat expired (and that saw no database update for
    # one more TTL) is marked failed as interrupted and can be resumed.
    DEBATE_HEARTBEAT_TTL_SECONDS: int = 90
    # Fallback when Redis is unavailable: no update for this long = stale.
    DEBATE_STALE_AFTER_SECONDS: int = 1800

    EVIDENCE_PROVIDER: str = "tavily"
    TAVILY_API_KEY: str = ""
    SERPAPI_API_KEY: str = ""
    # Google Fact Check Tools API (published fact-checks; complements Tavily).
    # Without a key the fact-check stage is skipped and analysis continues.
    GOOGLE_FACT_CHECK_API_KEY: str = ""
    GOOGLE_FACT_CHECK_LANGUAGE: str = "en"
    GOOGLE_FACT_CHECK_TIMEOUT_SECONDS: float = 10.0
    GOOGLE_FACT_CHECK_MAX_RESULTS: int = 5
    # Parallel fact-check searches per analysis run.
    GOOGLE_FACT_CHECK_CONCURRENCY: int = 3

    # Minimum gap between the top two final agent scores required to declare
    # a winner; closer scores produce a tie (Module 11 judge).
    JUDGE_MIN_SCORE_GAP: float = 0.5

    # Optional demo account for presentations (see app/services/demo_account).
    # Off by default; never point these at a real or administrator account.
    DEMO_ACCOUNT_ENABLED: bool = False
    DEMO_ACCOUNT_EMAIL: str = ""
    DEMO_ACCOUNT_PASSWORD: str = ""

    FRONTEND_URL: str = "http://localhost:5173"

    JWT_SECRET_KEY: str = "change-me-in-development"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    @model_validator(mode="after")
    def validate_production(self):
        if self.APP_ENV.lower() not in ("production", "prod"):
            return self
        if len(self.JWT_SECRET_KEY) < 32 or self.JWT_SECRET_KEY.lower().startswith(("change-me", "changeme")):
            raise ValueError("Production requires a unique JWT_SECRET_KEY of at least 32 characters")
        origin = urlparse(self.FRONTEND_URL)
        if origin.scheme != "https" or not origin.netloc or origin.path not in ("", "/") or origin.query or origin.fragment or origin.username or '*' in self.FRONTEND_URL:
            raise ValueError("Production FRONTEND_URL must be one explicit HTTPS origin")
        database = urlparse(self.DATABASE_URL)
        if database.scheme != "postgresql+asyncpg" or not database.hostname or not database.password or database.password in ("postgres", "PASSWORD", "password"):
            raise ValueError("Production requires an async PostgreSQL URL with non-default credentials")
        redis = urlparse(self.REDIS_URL)
        if redis.scheme not in ("redis", "rediss") or not redis.hostname or not redis.password or redis.password in ("PASSWORD", "password"):
            raise ValueError("Production requires an authenticated Redis URL")
        if self.DEMO_ACCOUNT_ENABLED:
            raise ValueError("Disable the public shared demo account in production")
        if self.JWT_ALGORITHM not in ("HS256", "HS384", "HS512") or self.ACCESS_TOKEN_EXPIRE_MINUTES <= 0:
            raise ValueError("Invalid production JWT configuration")
        return self

    model_config = {"env_file": ".env", "extra": "ignore", "hide_input_in_errors": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()
