import asyncio
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.redis import redis_client
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.ai import router as ai_router
from app.api.agents import router as agents_router

settings = get_settings()
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Debate Arena backend...")
    yield
    logger.info("Shutting down...")
    await redis_client.aclose()


app = FastAPI(
    title="AI Debate Arena",
    description="Multi-Agent LLM Based Argument Verification and Evidence-Based Decisions",
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth", "description": "Authentication endpoints"},
        {"name": "ai", "description": "AI agent endpoints"},
        {"name": "agents", "description": "Role-based AI agent endpoints"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "AI Debate Arena API", "docs": "/docs"}
