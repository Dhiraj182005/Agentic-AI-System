import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.orchestration.debate_engine import DebateExecutionError
from app.schemas.debate import (
    DebateCreateRequest,
    DebateListResponse,
    DebateResponse,
    DebateRoundResponse,
    DebateRoundsResponse,
    TranscriptMessageResponse,
    TranscriptResponse,
)
from app.services import debate_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debates", tags=["debates"])


@router.post(
    "",
    response_model=DebateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_debate(
    payload: DebateCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await debate_service.create_debate(db, current_user, payload)
    except debate_service.DebateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Debate creation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the debate",
        )


@router.get("", response_model=DebateListResponse)
async def list_debates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    debates = await debate_service.list_debates(db, current_user)
    return DebateListResponse(items=debates)


@router.get("/{debate_id}", response_model=DebateResponse)
async def get_debate(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await debate_service.get_debate(db, current_user, debate_id)
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )


@router.post("/{debate_id}/start", response_model=DebateResponse)
async def start_debate(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute the debate synchronously and return its final state."""
    try:
        return await debate_service.start_debate(db, current_user, debate_id)
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    except debate_service.DebateConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    except DebateExecutionError as exc:
        if exc.provider:
            logger.error("Debate %s failed: provider error", debate_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The debate failed because the language model provider did not respond",
            )
        logger.error("Debate %s failed: internal error", debate_id, exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The debate failed because of an internal error",
        )
    except Exception:
        logger.exception("Debate %s failed unexpectedly", debate_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The debate failed because of an internal error",
        )


@router.get("/{debate_id}/messages", response_model=TranscriptResponse)
async def get_debate_messages(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await debate_service.get_debate_transcript(db, current_user, debate_id)
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    messages = [
        TranscriptMessageResponse(
            id=message.id,
            round_number=round_number,
            turn_number=message.turn_number,
            agent=message.agent,
            message_type=message.message_type,
            content=message.content,
            created_at=message.created_at,
        )
        for message, round_number in rows
    ]
    return TranscriptResponse(debate_id=debate_id, messages=messages)


@router.get("/{debate_id}/rounds", response_model=DebateRoundsResponse)
async def get_debate_rounds(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rounds = await debate_service.get_debate_rounds(db, current_user, debate_id)
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    return DebateRoundsResponse(
        debate_id=debate_id,
        rounds=[DebateRoundResponse.model_validate(r) for r in rounds],
    )
