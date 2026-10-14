import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.fallacy import (
    FallacyAnalysisListResponse,
    FallacyListResponse,
    FallacyResponse,
)
from app.services import argument_analysis_service, debate_service
from app.services.argument_analysis_service import FallacyAnalysisResult
from app.services.fallacy_detection import FallacyDetectionError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fallacies"])


def _analysis_response(result: FallacyAnalysisResult) -> FallacyResponse:
    row = result.fallacy
    return FallacyResponse(
        id=row.id if row is not None else None,
        debate_id=result.analysis.debate_id,
        message_id=result.analysis.message_id,
        agent_id=result.analysis.agent_id,
        agent_name=result.analysis.agent_name,
        fallacy_type=result.detected.fallacy_type,
        severity=result.detected.severity,
        confidence=result.detected.confidence,
        explanation=result.detected.explanation,
        evidence_span=result.detected.evidence_span,
        created_at=row.created_at if row is not None else None,
    )


def _stored_response(fallacy, agent_name: str) -> FallacyResponse:
    return FallacyResponse(
        id=fallacy.id,
        debate_id=fallacy.debate_id,
        message_id=fallacy.message_id,
        agent_id=fallacy.agent_id,
        agent_name=agent_name,
        fallacy_type=fallacy.fallacy_type,
        severity=fallacy.severity,
        confidence=fallacy.confidence,
        explanation=fallacy.explanation,
        evidence_span=fallacy.evidence_span,
        created_at=fallacy.created_at,
    )


@router.post(
    "/debates/{debate_id}/fallacies/analyze",
    response_model=FallacyAnalysisListResponse,
)
async def analyze_debate_fallacies(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        results = await argument_analysis_service.analyze_debate_fallacies(
            db, current_user, debate_id
        )
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    except argument_analysis_service.ArgumentAnalysisValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except FallacyDetectionError as exc:
        logger.error("Fallacy analysis failed for debate %s", debate_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Fallacy analysis failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fallacy analysis failed because of an internal error",
        )
    return FallacyAnalysisListResponse(
        debate_id=debate_id,
        analyzed_count=len(results),
        fallacies=[_analysis_response(result) for result in results],
    )


@router.get("/debates/{debate_id}/fallacies", response_model=FallacyListResponse)
async def list_fallacies(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read stored fallacies from the database. Never calls the LLM."""
    try:
        rows = await argument_analysis_service.list_fallacies(
            db, current_user, debate_id
        )
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    return FallacyListResponse(
        debate_id=debate_id,
        fallacies=[_stored_response(fallacy, name) for fallacy, name in rows],
    )


@router.post(
    "/messages/{message_id}/fallacies/analyze",
    response_model=FallacyResponse,
)
async def analyze_message_fallacy(
    message_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await argument_analysis_service.analyze_message_fallacy(
            db, current_user, message_id
        )
    except argument_analysis_service.MessageNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        )
    except FallacyDetectionError as exc:
        logger.error("Fallacy analysis failed for message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Fallacy analysis failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fallacy analysis failed because of an internal error",
        )
    return _analysis_response(result)
