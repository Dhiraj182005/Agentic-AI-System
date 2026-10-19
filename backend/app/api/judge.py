import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.debate import Debate
from app.models.judge import DebateJudgment
from app.models.user import User
from app.schemas.judge import JudgmentResponse
from app.services.debate_judge_service import (
    DebateJudgeService,
    JudgeDataUnavailableError,
    JudgeLLMError,
    JudgeNotCompletedError,
    JudgeNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debates", tags=["judge"])


def _to_response(judgment: DebateJudgment, debate: Debate) -> JudgmentResponse:
    winner_name = None
    if judgment.winner_agent_id is not None:
        winner_name = next(
            (agent.name for agent in debate.agents if agent.id == judgment.winner_agent_id),
            None,
        )
    return JudgmentResponse(
        id=judgment.id,
        debate_id=judgment.debate_id,
        status=judgment.status,
        overall_score=judgment.overall_score,
        outcome=judgment.outcome,
        winner_agent_id=judgment.winner_agent_id,
        winner_name=winner_name,
        summary=judgment.summary,
        limitations=judgment.limitations,
        scoring_rubric=judgment.scoring_rubric or {},
        agent_scores=judgment.agent_scores or [],
        created_at=judgment.created_at,
        updated_at=judgment.updated_at,
    )


async def _load_owned_debate(
    db: AsyncSession, user: User, debate_id
) -> Debate:
    debate = (
        await db.execute(select(Debate).where(Debate.id == debate_id))
    ).scalar_one_or_none()
    if debate is None or debate.user_id != user.id:
        raise JudgeNotFoundError("Debate not found")
    return debate


@router.post("/{debate_id}/judge", response_model=JudgmentResponse)
async def judge_debate(
    debate_id,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate (or return the existing) judgment for a completed debate."""
    try:
        judgment = await DebateJudgeService().judge_debate(
            db, current_user, debate_id
        )
        debate = await _load_owned_debate(db, current_user, debate_id)
    except JudgeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    except JudgeNotCompletedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except JudgeDataUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except JudgeLLMError as exc:
        logger.error("Judgment failed for debate %s: %s", debate_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Judgment failed for debate %s", debate_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate the judgment",
        )
    return _to_response(judgment, debate)


@router.get("/{debate_id}/judgment", response_model=JudgmentResponse)
async def get_judgment(
    debate_id,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the stored judgment only - never calls the LLM."""
    try:
        debate = await _load_owned_debate(db, current_user, debate_id)
    except JudgeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    judgment = (
        await db.execute(
            select(DebateJudgment).where(DebateJudgment.debate_id == debate_id)
        )
    ).scalar_one_or_none()
    if judgment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Judgment not found",
        )
    return _to_response(judgment, debate)
