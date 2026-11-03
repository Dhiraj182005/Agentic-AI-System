import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.orchestration.debate_engine import DebateExecutionError
from app.db.redis import redis_client
from app.schemas.debate import (
    DebateCreateRequest,
    RecommendedSpecialist,
    RejectedSpecialist,
    TopicAnalysisSummary,
    DebateListResponse,
    DebateResponse,
    DebateRoundResponse,
    DebateRoundsResponse,
    RecommendAgentsRequest,
    RecommendAgentsResponse,
    RecommendedAgent,
    TranscriptMessageResponse,
    TranscriptResponse,
)
from app.services import debate_service, report_service
from app.services.topic_analysis import AnalysisError, TopicAnalysisService
from app.core.config import get_settings
import hashlib
import json
from app.services.agent_selection import (
    AgentSelectionError,
    AgentSelectionService,
    InsufficientAgentsError,
)

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


@router.post("/recommend-agents", response_model=RecommendAgentsResponse)
async def recommend_agents(
    payload: RecommendAgentsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recommend active core agents whose expertise fits the given topic.

    The selection is produced by the shared LLM provider and validated
    against the agents stored in the database; when the provider is
    unavailable the deterministic topic/keyword fallback is used instead
    (``selection_source`` tells the client which path ran).
    """
    if payload.include_specialists:
        analyzed = await _recommend_with_analysis(db, payload)
        if analyzed is not None:
            return analyzed
    try:
        service = AgentSelectionService()
        pairs, source = await service.recommend(db, payload.topic)
    except InsufficientAgentsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except AgentSelectionError as exc:
        logger.warning("Agent recommendation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate agent recommendations right now",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Agent recommendation failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate agent recommendations",
        )
    return RecommendAgentsResponse(
        topic=payload.topic,
        selection_mode="auto",
        selection_source=source,
        agents=[
            RecommendedAgent(id=agent.id, name=agent.name, role=agent.role, reason=reason)
            for agent, reason in pairs
        ],
    )


def _analysis_cache_key(payload: RecommendAgentsRequest) -> str:
    raw = json.dumps(
        [payload.topic.strip().lower(), (payload.context or "").strip().lower(), payload.mode],
        ensure_ascii=False,
    )
    return "maves:topic-analysis:" + hashlib.sha256(raw.encode()).hexdigest()


async def _recommend_with_analysis(
    db: AsyncSession, payload: RecommendAgentsRequest
) -> RecommendAgentsResponse | None:
    """Topic analysis with built-in picks and dynamic AI specialists.

    Served from a short Redis cache when the same topic is requested again
    (typing, refresh). Returns None when the analysis is unavailable so the
    caller falls back to built-in-only recommendation.
    """
    key = _analysis_cache_key(payload)
    try:
        cached = await redis_client.get(key)
    except Exception:
        cached = None
    if cached:
        try:
            response = RecommendAgentsResponse.model_validate_json(cached)
            response.cached = True
            return response
        except Exception:
            pass

    service = AgentSelectionService()
    try:
        builtins = await service.builtin_agents(db)
        analysis = await TopicAnalysisService().analyze(
            payload.topic, builtins, context=payload.context, mode=payload.mode
        )
    except InsufficientAgentsError:
        raise
    except AnalysisError as exc:
        logger.warning("Topic analysis unavailable, using built-in selection: %s", exc)
        return None
    except Exception:
        logger.exception("Topic analysis failed unexpectedly, using built-in selection")
        return None

    response = RecommendAgentsResponse(
        topic=payload.topic,
        selection_mode="auto",
        selection_source="llm",
        agents=[
            RecommendedAgent(id=a.id, name=a.name, role=a.role, reason=reason)
            for a, reason in analysis.builtins
        ],
        analysis=TopicAnalysisSummary(
            main_domain=analysis.main_domain,
            secondary_domains=analysis.secondary_domains,
            key_questions=analysis.key_questions,
            recommended_agent_count=analysis.recommended_agent_count,
            specialists_rationale=analysis.specialists_rationale,
        ),
        specialists=[RecommendedSpecialist(**s.model_dump()) for s in analysis.specialists],
        rejected_specialists=[RejectedSpecialist(**r) for r in analysis.rejected],
    )
    try:
        await redis_client.set(
            key, response.model_dump_json(), ex=get_settings().RECOMMENDATION_CACHE_TTL_SECONDS
        )
    except Exception:
        logger.warning("Could not cache topic analysis", exc_info=True)
    return response


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


def _execution_http_error(debate_id, exc: DebateExecutionError) -> HTTPException:
    """Map an engine failure to a safe HTTP error.

    The engine's message is already user-safe (round/turn/agent plus a
    per-error-class explanation); provider internals stay in the logs.
    """
    if exc.provider:
        logger.error("Debate %s failed: %s", debate_id, exc)
        return HTTPException(
            status_code=(
                status.HTTP_504_GATEWAY_TIMEOUT
                if exc.timeout
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail=str(exc),
        )
    logger.error("Debate %s failed: internal error", debate_id, exc_info=exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="The debate failed because of an internal error",
    )


@router.post("/{debate_id}/resume", response_model=DebateResponse)
async def resume_debate(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Continue a failed debate from the failed turn (no duplicate turns)."""
    try:
        return await debate_service.resume_debate(db, current_user, debate_id)
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    except debate_service.DebateConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except DebateExecutionError as exc:
        raise _execution_http_error(debate_id, exc)
    except Exception:
        logger.exception("Debate %s resume failed unexpectedly", debate_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The debate failed because of an internal error",
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
        raise _execution_http_error(debate_id, exc)
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
            structured=message.structured,
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


@router.get("/{debate_id}/report.pdf")
async def download_debate_report(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a PDF conclusion report assembled from persisted data only.

    The report never calls the LLM or any external service and never runs
    new analysis: missing judgments or analyses are shown as explicit
    unavailable states inside the document.
    """
    try:
        pdf_bytes, filename = await report_service.build_report(
            db, current_user, debate_id
        )
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    except report_service.ReportRenderError:
        logger.exception("Report rendering failed for debate %s", debate_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not render the report",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Report generation failed for debate %s", debate_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate the report",
        )
    return Response(
        content=pdf_bytes,
        media_type=report_service.REPORT_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
