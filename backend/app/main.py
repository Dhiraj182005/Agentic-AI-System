import asyncio
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import install_redaction, setup_logging
from app.db.redis import redis_client
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.ai import router as ai_router
from app.api.agents import router as agents_router
from app.api.debates import router as debates_router
from app.api.claims import router as claims_router
from app.api.fallacies import router as fallacies_router
from app.api.evaluations import router as evaluations_router
from app.api.judge import router as judge_router
from app.api.analytics import router as analytics_router
from app.api.websocket import router as websocket_router

settings = get_settings()
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-attach once uvicorn has configured its own loggers, so access-log
    # lines that contain a query string are scrubbed too.
    install_redaction()
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
        {"name": "debates", "description": "Debate creation and agent selection endpoints"},
        {"name": "claims", "description": "Claim extraction and evidence retrieval endpoints"},
        {"name": "fallacies", "description": "Fallacy detection endpoints"},
        {"name": "evaluations", "description": "Argument quality evaluation endpoints"},
        {"name": "judge", "description": "Debate judge and overall scoring endpoints"},
        {"name": "analytics", "description": "Analytics dashboard endpoints"},
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
app.include_router(debates_router, prefix="/api/v1")
app.include_router(claims_router, prefix="/api/v1")
app.include_router(fallacies_router, prefix="/api/v1")
app.include_router(evaluations_router, prefix="/api/v1")
app.include_router(judge_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
# WebSocket routes carry their own /ws path and need no /api/v1 prefix.
app.include_router(websocket_router)


@app.get("/")
async def root():
    return {"message": "AI Debate Arena API", "docs": "/docs"}
