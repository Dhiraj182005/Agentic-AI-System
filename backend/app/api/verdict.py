import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.verdict import VerdictResponse
from fastapi import status as status_codes

from app.services import analysis_pipeline
from app.services.debate_service import DebateNotFoundError
from app.services.verdict_service import (
    VerdictDataUnavailableError,
    VerdictLLMError,
    VerdictNotCompletedError,
    VerdictNotFoundError,
    VerdictService,
    verdict_response_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debates", tags=["verdict"])


@router.post("/{debate_id}/verdict", response_model=VerdictResponse)
async def generate_verdict(
    debate_id: UUID,
    regenerate: bool = Query(
        False, description="Replace the stored verdict (e.g. after verifying more claims)"
    ),
    run_missing_analysis: bool = Query(
        False,
        description=(
            "First run any missing analysis stages (claim extraction, evidence "
            "search, verification) and then (re)generate the verdict"
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate (or return the stored) final verdict on the debate question."""
    if run_missing_analysis:
        try:
            analysis_state = await analysis_pipeline.run_analysis(
                db, current_user, debate_id, trigger="verdict",
                regenerate_verdict=regenerate,
            )
        except VerdictNotFoundError:
            raise HTTPException(status_code=status_codes.HTTP_404_NOT_FOUND, detail="Debate not found")
        except DebateNotFoundError:
            raise HTTPException(status_code=status_codes.HTTP_404_NOT_FOUND, detail="Debate not found")
        except analysis_pipeline.AnalysisInProgressError as exc:
            from app.models.debate import Debate
            current = await db.get(Debate, debate_id)
            await db.refresh(current)
            return JSONResponse(status_code=202, content={**analysis_pipeline.status_payload(current),
                "joined": True, "message": "Analysis already in progress — showing live progress."})
        except analysis_pipeline.AnalysisNotReadyError as exc:
            raise HTTPException(status_code=status_codes.HTTP_400_BAD_REQUEST, detail=str(exc))
        verdict = await VerdictService().get_verdict(db, current_user, debate_id)
        if verdict is None or analysis_state.get("verdict") == "failed":
            failure = next(
                (f["error"] for f in analysis_state.get("failures", []) if f.get("stage") == "verdict"),
                "The verdict could not be generated",
            )
            raise HTTPException(status_code=status_codes.HTTP_502_BAD_GATEWAY, detail=failure)
        return await verdict_response_payload(db, verdict)
    try:
        verdict = await VerdictService().generate_verdict(
            db, current_user, debate_id, regenerate=regenerate
        )
    except VerdictNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found")
    except (VerdictNotCompletedError, VerdictDataUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except VerdictLLMError as exc:
        logger.error("Verdict failed for debate %s: %s", debate_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Verdict failed for debate %s", debate_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate the verdict",
        )
    return await verdict_response_payload(db, verdict)


@router.get("/{debate_id}/analysis")
async def get_analysis_status(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """State of the post-debate analysis (never calls the LLM)."""
    from app.services.debate_service import get_debate

    try:
        debate = await get_debate(db, current_user, debate_id)
    except DebateNotFoundError:
        raise HTTPException(status_code=status_codes.HTTP_404_NOT_FOUND, detail="Debate not found")
    from app.services.analysis_coverage import coverage_payload
    return {**analysis_pipeline.status_payload(debate), "coverage": await coverage_payload(db, debate)}


@router.post("/{debate_id}/analysis", status_code=status_codes.HTTP_202_ACCEPTED)
async def start_analysis(
    debate_id: UUID,
    regenerate: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start the missing analysis stages in the background."""
    try:
        return await analysis_pipeline.ensure_analysis(db, current_user, debate_id, regenerate=regenerate)
    except DebateNotFoundError:
        raise HTTPException(status_code=status_codes.HTTP_404_NOT_FOUND, detail="Debate not found")
    except analysis_pipeline.AnalysisNotReadyError as exc:
        raise HTTPException(
            status_code=status_codes.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get("/{debate_id}/verdict", response_model=VerdictResponse)
async def get_verdict(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the stored verdict only - never calls the LLM."""
    try:
        verdict = await VerdictService().get_verdict(db, current_user, debate_id)
    except VerdictNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found")
    if verdict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verdict not found")
    return await verdict_response_payload(db, verdict)
