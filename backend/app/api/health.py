from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.db.database import get_db, log_connection_failure
from app.db.redis import check_redis_health
from app.schemas.health import HealthResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    db_status = "disconnected"
    redis_status = "disconnected"

    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
        logger.info("postgresql_connection_succeeded operation=health_check",
                    extra={"event": "postgresql_connection_succeeded", "operation": "health_check"})
    except Exception as exc:
        log_connection_failure(exc, operation="health_check")
        db_status = "disconnected"
        # Do not let get_db's final commit retry an aborted health transaction.
        try:
            await db.rollback()
        except Exception as rollback_error:
            log_connection_failure(rollback_error, operation="health_check_rollback")

    if await check_redis_health():
        redis_status = "connected"

    overall = "ok" if db_status == "connected" else "degraded"

    return HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
    )
