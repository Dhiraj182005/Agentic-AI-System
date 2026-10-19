"""Analytics endpoints for the results dashboard (Module 12).

Every route requires authentication and only aggregates the authenticated
user's own debates and analysis records.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.analytics import (
    AgentPerformanceResponse,
    ArgumentQualityResponse,
    ClaimVerificationResponse,
    DebateActivityResponse,
    RecentDebatesResponse,
    SummaryResponse,
)
from app.services import analytics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=SummaryResponse)
async def analytics_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Key performance indicators from stored records (owner only)."""
    return SummaryResponse(**await analytics_service.summary(db, current_user.id))


@router.get("/debate-activity", response_model=DebateActivityResponse)
async def analytics_debate_activity(
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Debate creation counts per UTC day over the selected range."""
    return DebateActivityResponse(
        **await analytics_service.debate_activity(db, current_user.id, days)
    )


@router.get("/claim-verification", response_model=ClaimVerificationResponse)
async def analytics_claim_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stored verdict and confidence distributions (owner only)."""
    return ClaimVerificationResponse(
        **await analytics_service.claim_verification(db, current_user.id)
    )


@router.get("/agent-performance", response_model=AgentPerformanceResponse)
async def analytics_agent_performance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate Module 11 judgment scores per agent (owner only)."""
    return AgentPerformanceResponse(
        **await analytics_service.agent_performance(db, current_user.id)
    )


@router.get("/argument-quality", response_model=ArgumentQualityResponse)
async def analytics_argument_quality(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stored Module 10 fallacy and evaluation aggregates (owner only)."""
    return ArgumentQualityResponse(
        **await analytics_service.argument_quality(db, current_user.id)
    )


@router.get("/recent-debates", response_model=RecentDebatesResponse)
async def analytics_recent_debates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated recent debates with lightweight summary fields."""
    return RecentDebatesResponse(
        **await analytics_service.recent_debates(
            db, current_user.id, page, page_size
        )
    )
