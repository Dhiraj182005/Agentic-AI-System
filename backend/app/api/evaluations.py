import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.evaluation import (
    ArgumentEvaluationResponse,
    EvaluationListResponse,
)
from app.services import argument_analysis_service, debate_service
from app.services.argument_evaluation import ArgumentEvaluationError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evaluations"])


def _evaluation_response(evaluation, agent_name: str) -> ArgumentEvaluationResponse:
    return ArgumentEvaluationResponse(
        id=evaluation.id,
        debate_id=evaluation.debate_id,
        message_id=evaluation.message_id,
        agent_id=evaluation.agent_id,
        agent_name=agent_name,
        logical_soundness=evaluation.logical_soundness,
        evidence_score=evaluation.evidence_score,
        relevance_score=evaluation.relevance_score,
        effectiveness_score=evaluation.effectiveness_score,
        overall_score=evaluation.overall_score,
        explanation=evaluation.explanation,
        created_at=evaluation.created_at,
    )


@router.post(
    "/messages/{message_id}/evaluation",
    response_model=ArgumentEvaluationResponse,
)
async def evaluate_message(
    message_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        evaluation, agent_name = await argument_analysis_service.evaluate_argument(
            db, current_user, message_id
        )
    except argument_analysis_service.MessageNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        )
    except ArgumentEvaluationError as exc:
        logger.error("Argument evaluation failed for message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Argument evaluation failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Argument evaluation failed because of an internal error",
        )
    return _evaluation_response(evaluation, agent_name)


@router.get(
    "/debates/{debate_id}/evaluations",
    response_model=EvaluationListResponse,
)
async def list_evaluations(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read stored evaluations from the database. Never calls the LLM."""
    try:
        rows = await argument_analysis_service.list_evaluations(
            db, current_user, debate_id
        )
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    return EvaluationListResponse(
        debate_id=debate_id,
        evaluations=[
            _evaluation_response(evaluation, name) for evaluation, name in rows
        ],
    )
