"""Post-debate analysis pipeline.

After a debate completes (when it was created with "verify evidence"), and
whenever the user regenerates the verdict, this pipeline runs the stages
that are still missing - and only those:

1. resumable per-message claim extraction (independently committed batches);
2. published fact-check search (Google Fact Check Tools, best effort) for
   up to ANALYSIS_MAX_VERIFIED_CLAIMS *factual* claims - opinions,
   predictions and definitions are never verified as facts. A missing key
   or an outage is recorded as a warning; the next stages still run;
3. web evidence retrieval with the configured provider (Tavily);
4. claim verification against all stored evidence (existing service).
   Claims that gained new fact-checks are re-verified;
5. fallacy checks and rubric quality evaluations for every eligible message;
6. final verdict, regenerated on changed material or explicit request.

Technical failures are kept apart from evidence findings: a search or LLM
failure is recorded in ``debates.analysis_status["failures"]`` and never
stored as an "insufficient evidence" verdict. "Insufficient evidence" is
only recorded after a search actually ran and found nothing (or the sources
did not settle the claim).

One run per debate at a time: the run is claimed with a conditional UPDATE,
so concurrent requests get AnalysisInProgressError instead of duplicating
claims or LLM calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.evidence.base import EvidenceProviderError
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.evidence import SOURCE_WEB
from app.models.user import User
from app.models.verdict import DebateVerdict
from app.services import claim_service
from app.services.claim_extraction import ClaimExtractionError
from app.services.verification_service import ClaimVerificationError

logger = logging.getLogger(__name__)

VERIFIABLE_TYPES = ("factual",)
_background_tasks: set[asyncio.Task] = set()


class AnalysisError(Exception):
    """Base class for pipeline errors."""


class AnalysisInProgressError(AnalysisError):
    """Another analysis run for this debate is in progress."""


class AnalysisNotReadyError(AnalysisError):
    """The debate is not completed or has no messages."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(exc: Exception) -> str:
    """User-safe failure category (no provider payloads or keys)."""
    if isinstance(exc, EvidenceProviderError):
        return "The evidence search service failed."
    if isinstance(exc, (ClaimVerificationError, ClaimExtractionError)):
        return str(exc) or "The language model step failed."
    return "An unexpected analysis error occurred."


def is_stale(status: dict | None) -> bool:
    if not status or status.get("state") != "running":
        return False
    try:
        started = datetime.fromisoformat(status.get("heartbeat_at") or status["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        return True
    return _now() - started > timedelta(seconds=get_settings().ANALYSIS_STALE_SECONDS)


async def _claim_run(db: AsyncSession, debate_id: UUID, trigger: str) -> dict:
    status = {"state": "running", "run_id": str(uuid4()), "trigger": trigger, "started_at": _now().isoformat()}
    stale_before = (_now() - timedelta(seconds=get_settings().ANALYSIS_STALE_SECONDS)).isoformat()
    observed = (await db.execute(select(Debate.analysis_status).where(Debate.id == debate_id))).scalar_one()
    result = await db.execute(
        text(
            "UPDATE debates SET analysis_status = CAST(:status AS JSON) "
            "WHERE id = :id AND (analysis_status IS NULL "
            "OR (analysis_status->>'state') IS DISTINCT FROM 'running' "
            "OR (CAST(:invalid_stale AS BOOLEAN) AND analysis_status::jsonb=CAST(:observed AS JSONB)) "
            "OR COALESCE(analysis_status->>'heartbeat_at', analysis_status->>'started_at') < :stale_before) RETURNING id"
        ),
        {"status": json.dumps(status), "id": debate_id, "stale_before": stale_before,
         "invalid_stale": is_stale(observed), "observed": json.dumps(observed)},
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise AnalysisInProgressError("An analysis of this debate is already running")
    await db.commit()
    return status


async def _recover(db: AsyncSession, user: User) -> None:
    """Roll back a failed stage and reload the user explicitly (a rollback
    expires ORM objects; implicit reloads are not allowed in async code)."""
    await db.rollback()
    await db.refresh(user)


async def _save_status(db: AsyncSession, debate_id: UUID, status: dict) -> None:
    if status.get("state") == "running":
        status["heartbeat_at"] = _now().isoformat()
    phase = "generating_verdict" if status.get("current_stage") in ("verdict", "publishing") else "analyzing"
    if status["state"] != "running":
        phase = "completed" if status.get("verdict") in ("generated", "up_to_date") else "analyzing" if status.get("verdict") == "skipped" and status["state"] == "completed" else "failed"
    result = await db.execute(text(
        "UPDATE debates SET analysis_status=CAST(:status AS JSON), execution_state=:phase "
        "WHERE id=:id AND analysis_status->>'run_id'=:run_id RETURNING id"),
        {"status": json.dumps(status), "phase": phase, "id": debate_id, "run_id": status["run_id"]})
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise AnalysisInProgressError("This analysis run was superseded by a newer run")
    await db.commit()
    debate = await db.get(Debate, debate_id)
    await db.refresh(debate, ["analysis_status", "execution_state"])
    from app.websocket.events import DebateEventManager
    await DebateEventManager(bind=db.bind).emit(debate_id, "analysis_progress", {
        "run_id": status["run_id"], "state": status["state"], "execution_state": phase,
        "current_stage": status.get("current_stage"), "stages": status.get("stages", {})})


STAGES = ("transcript", "extraction", "fact_check", "retrieval", "verification", "fallacy",
          "evaluation", "performance", "verdict", "publishing")
STAGE_EVENTS = {"extraction": "claim_extraction", "retrieval": "evidence_retrieval",
                "verification": "claim_verification", "fallacy": "fallacy_analysis",
                "evaluation": "argument_evaluation", "verdict": "verdict_generation"}


async def _stage(db, debate_id, status, key, state, summary=None, error=None):
    item = dict(status.setdefault("stages", {}).get(key, {"state": "pending"}))
    item["state"] = state
    if state == "running":
        item.setdefault("started_at", _now().isoformat())
        status["current_stage"] = key
    elif state in ("completed", "failed", "skipped"):
        item["finished_at"] = _now().isoformat()
    if summary is not None:
        item["summary"] = summary
    if error:
        item["error"] = error
    status["stages"][key] = item
    await _save_status(db, debate_id, status)
    from app.websocket.events import DebateEventManager
    suffix = "started" if state == "running" else state if state in ("failed", "skipped") else "completed"
    await DebateEventManager(bind=db.bind).emit(debate_id, f"{STAGE_EVENTS.get(key, key)}_{suffix}",
        {"run_id": status["run_id"], "stage": key, **item})


async def _heartbeat(bind, debate_id, run_id):
    factory = async_sessionmaker(bind, expire_on_commit=False)
    while True:
        await asyncio.sleep(15)
        async with factory() as db:
            await db.execute(text("UPDATE debates SET analysis_status = jsonb_set(analysis_status::jsonb, "
                "'{heartbeat_at}', to_jsonb(CAST(:now AS text)))::json WHERE id=:id "
                "AND analysis_status->>'run_id'=:run_id AND analysis_status->>'state'='running'"),
                {"now": _now().isoformat(), "id": debate_id, "run_id": run_id})
            await db.commit()


def select_claims(claims: list[tuple[Claim, str]], limit: int) -> list[Claim]:
    """Factual claims only, spread across agents round-robin, in debate order."""
    if limit <= 0:
        limit = len(claims)
    by_agent: dict[str, list[Claim]] = {}
    for claim, agent_name in claims:
        if claim.claim_type in VERIFIABLE_TYPES:
            by_agent.setdefault(agent_name, []).append(claim)
    selected: list[Claim] = []
    while len(selected) < limit and any(by_agent.values()):
        for queue in by_agent.values():
            if queue and len(selected) < limit:
                selected.append(queue.pop(0))
    return selected


def _needs_verification(claim: Claim, verification: ClaimVerification | None, web_count: int) -> bool:
    if verification is None:
        return True
    if any(timestamp and timestamp > verification.updated_at for timestamp in
           (claim.evidence_retrieved_at, claim.fact_check_searched_at)):
        return True
    # A verification made without a web search (manual "Verify" before
    # "Retrieve evidence", or a failed search) is not a full evidence
    # finding: redo it properly.
    return web_count == 0 and claim.evidence_retrieved_at is None


async def run_analysis(
    db: AsyncSession,
    user: User,
    debate_id: UUID,
    *,
    trigger: str,
    generate_verdict: bool = True,
    regenerate_verdict: bool = False,
    claimed_status: dict | None = None,
) -> dict:
    """Run the missing analysis stages for a completed debate (see module doc)."""
    from app.services.debate_service import get_debate
    from app.services.verdict_service import VerdictError, VerdictService

    debate = await get_debate(db, user, debate_id)
    if debate.status != "completed":
        raise AnalysisNotReadyError("The debate must be completed before it can be analysed")

    status = claimed_status or await _claim_run(db, debate_id, trigger)
    status["stages"] = {key: {"state": "pending"} for key in STAGES}
    heartbeat = asyncio.create_task(_heartbeat(db.bind, debate_id, status["run_id"]))
    status.update(
        {"extraction": None, "claims_total": 0, "claims_factual": 0, "claims_selected": 0,
         "searched": 0, "no_sources": 0, "verified": 0, "already_verified": 0,
         "fact_check": None, "failures": [], "verdict": "skipped"}
    )
    try:
        from app.websocket.events import DebateEventManager
        await DebateEventManager(bind=db.bind).emit(debate_id, "analysis_started", {"run_id": status["run_id"]})
        await _stage(db, debate_id, status, "transcript", "running")
        from app.models.debate_message import DebateMessage
        message_count = len((await db.execute(select(DebateMessage.id).where(DebateMessage.debate_id == debate_id))).scalars().all())
        await _stage(db, debate_id, status, "transcript", "completed", {"messages": message_count})
        await _stage(db, debate_id, status, "extraction", "running")
        # 1. Resumable extraction with per-message completion.
        claims = await claim_service.list_claims(db, user, debate_id)
        try:
            async def extraction_progress(summary):
                status["claims_total"] = summary["claims"]
                status["stages"]["extraction"]["summary"] = summary
                await _save_status(db, debate_id, status)
            claims = await claim_service.extract_claims(db, user, debate_id, progress=extraction_progress)
            status["extraction"] = "done"
            await _stage(db, debate_id, status, "extraction", "completed", {"claims": len(claims)})
        except (ClaimExtractionError, claim_service.ClaimValidationError) as exc:
            await _recover(db, user)
            status["extraction"] = "failed"
            claims = await claim_service.list_claims(db, user, debate_id)
            await _stage(db, debate_id, status, "extraction", "failed", {"persisted_claims": len(claims)}, _safe_error(exc))
            status["failures"].append({"stage": "extraction", "error": _safe_error(exc)})
            logger.warning("Analysis %s: extraction failed: %s", debate_id, type(exc).__name__)
        status["claims_total"] = len(claims)
        status["claims_factual"] = sum(1 for c, _ in claims if c.claim_type in VERIFIABLE_TYPES)
        selected = select_claims(claims, get_settings().ANALYSIS_MAX_VERIFIED_CLAIMS)
        # Search canonical statements first so repeated message occurrences
        # can reuse their evidence even when round-robin selection interleaves agents.
        selected.sort(key=lambda claim: claim.canonical_claim_id is not None)
        selected_ids = [c.id for c in selected]
        await _save_status(db, debate_id, status)

        # 2. Published fact-checks for the selected claims (never raises for
        # provider problems; recorded as a warning, not a stage failure).
        status["claims_selected"] = len(selected_ids)
        await _stage(db, debate_id, status, "fact_check", "running")
        fact_check = await claim_service.run_fact_check_stage(db, user, selected_ids)
        refreshed = set(fact_check.pop("new_claim_ids"))
        status["fact_check"] = fact_check
        if fact_check["status"] in ("failed", "partial", "unavailable"):
            logger.warning("Analysis %s: fact-check stage %s", debate_id, fact_check["status"])
        await _save_status(db, debate_id, status)

        await _stage(db, debate_id, status, "fact_check",
            "skipped" if not selected_ids or fact_check["status"] == "unavailable" else "failed" if fact_check["status"] in ("failed", "partial") else "completed",
            fact_check, fact_check.get("error"))
        await _stage(db, debate_id, status, "retrieval", "running")
        # 3+4. Web evidence and verification for selected factual claims.
        for claim_id in selected_ids:
            # Reload per claim: a rollback after a failure expires ORM objects.
            claim = await db.get(Claim, claim_id)
            evidence = await claim_service.get_evidence(db, user, claim_id)
            web_count = sum(1 for e in evidence if e.source_type == SOURCE_WEB)
            verification = (
                await db.execute(select(ClaimVerification).where(ClaimVerification.claim_id == claim_id))
            ).scalars().first()
            if claim_id not in refreshed and not _needs_verification(claim, verification, web_count):
                status["already_verified"] += 1
                continue
            try:
                if web_count == 0:
                    evidence = await claim_service.retrieve_evidence(
                        db, user, claim_id, fact_check=False
                    )
                    status["searched"] += 1
                    await DebateEventManager(bind=db.bind).emit(debate_id, "evidence_retrieval_completed",
                        {"run_id": status["run_id"], "claim_id": str(claim_id), "sources": len(evidence)})
                    if not evidence:
                        # Searched and found nothing: commit the attempt time so
                        # the "insufficient evidence" result below is genuine.
                        await db.commit()
                        status["no_sources"] += 1
            except EvidenceProviderError as exc:
                await _recover(db, user)
                status["failures"].append(
                    {"stage": "retrieval", "claim_id": str(claim_id), "error": _safe_error(exc)}
                )
                logger.warning("Analysis %s: retrieval failed for a claim: %s", debate_id, type(exc).__name__)
                await _save_status(db, debate_id, status)
                # Published fact-checks found earlier are still evidence.
                if not await claim_service.get_evidence(db, user, claim_id):
                    continue
            try:
                if status["stages"]["verification"]["state"] == "pending":
                    await _stage(db, debate_id, status, "verification", "running")
                await claim_service.verify_claim(db, user, claim_id)
                status["verified"] += 1
                await DebateEventManager(bind=db.bind).emit(debate_id, "claim_verification_completed",
                    {"run_id": status["run_id"], "claim_id": str(claim_id), "verified": status["verified"]})
            except ClaimVerificationError as exc:
                await _recover(db, user)
                status["failures"].append(
                    {"stage": "verification", "claim_id": str(claim_id), "error": _safe_error(exc)}
                )
                logger.warning("Analysis %s: verification failed for a claim: %s", debate_id, type(exc).__name__)
            await _save_status(db, debate_id, status)

        for key, counter in (("retrieval", "searched"), ("verification", "verified")):
            errors = [f for f in status["failures"] if f["stage"] == key]
            blocked = key == "verification" and status["verified"] + status["already_verified"] < len(selected_ids) and not errors
            await _stage(db, debate_id, status, key, "failed" if errors else "skipped" if blocked or not selected_ids else "completed",
                {"processed": status[counter], "reused": status["already_verified"], "total": len(selected_ids)},
                errors[0]["error"] if errors else "Some claims could not be verified because evidence retrieval failed." if blocked else None)
        # Every participant's message is checked; successful rows survive other failures.
        from app.services.message_pipeline import run_message_batch
        for stage in ("fallacy", "evaluation"):
            await _stage(db, debate_id, status, stage, "running")
            async def progress(summary):
                status[stage] = summary
                status["stages"][stage]["summary"] = summary
                await _save_status(db, debate_id, status)
            summary = await run_message_batch(db, user, debate_id, stage=stage, progress=progress)
            status[stage] = summary
            status["failures"].extend(summary["failures"])
            await _stage(db, debate_id, status, stage, "failed" if summary["failed"] else "completed", summary,
                         "Some messages failed; successful results are saved." if summary["failed"] else None)
        await _stage(db, debate_id, status, "performance", "running")
        try:
            from app.services.debate_judge_service import DebateJudgeService, current_judge_inputs
            service = DebateJudgeService()
            existing_judge = await service.get_existing(db, debate_id)
            current_debate = await db.get(Debate, debate_id)
            changed_inputs = existing_judge is not None and (existing_judge.scoring_rubric or {}).get("inputs") != await current_judge_inputs(db, current_debate)
            judgment = await service.judge_debate(db, user, debate_id, regenerate=changed_inputs)
            await _stage(db, debate_id, status, "performance", "completed", {"agents": len(judgment.agent_scores or [])})
        except Exception:
            await _recover(db, user)
            error = "Agent performance evaluation failed; retry to resume."
            status["failures"].append({"stage": "performance", "error": error})
            await _stage(db, debate_id, status, "performance", "failed", error=error)
        if len(selected_ids) < status["claims_factual"]:
            status["failures"].append({"stage": "verification", "error": "Configured claim limit left factual claims pending."})

        if status["extraction"] == "failed" and not claims:
            status["result_state"] = "failed"
        elif status["failures"] or fact_check["status"] in ("failed", "partial", "unavailable"):
            status["result_state"] = "partial"
        else:
            status["result_state"] = "completed"
        await _save_status(db, debate_id, status)

        # 4. Verdict on the persisted results.
        changed = status["verified"] > 0
        existing_verdict = (
            await db.execute(select(DebateVerdict).where(DebateVerdict.debate_id == debate_id))
        ).scalar_one_or_none()
        # Consistency: the same evidence must not produce a different verdict
        # on every click. "Regenerate" asks the model again only when the
        # evidence changed, the stored verdict is stale, or it predates the
        # bias-aware format - otherwise the stored verdict stands.
        outdated = existing_verdict is None or existing_verdict.assumptions is None
        if existing_verdict is not None and not outdated:
            from app.services.verdict_service import current_evidence_snapshot

            current = await current_evidence_snapshot(db, debate_id)
            stored = existing_verdict.evidence_snapshot or {}
            outdated = {k: stored.get(k) for k in current} != current
        if generate_verdict and (regenerate_verdict or changed or outdated):
            try:
                await _stage(db, debate_id, status, "verdict", "running")
                async def publishing():
                    async with async_sessionmaker(db.bind, expire_on_commit=False)() as progress_db:
                        await _stage(progress_db, debate_id, status, "verdict", "completed")
                        await _stage(progress_db, debate_id, status, "publishing", "running")
                # New evidence makes any earlier verdict stale: replace it.
                await VerdictService().generate_verdict(db, user, debate_id, regenerate=True, on_generated=publishing)
                status["verdict"] = "generated"
                await _stage(db, debate_id, status, "publishing", "completed")
                await DebateEventManager(bind=db.bind).emit(debate_id, "verdict_generated", {"run_id": status["run_id"]})
            except VerdictError as exc:
                await _recover(db, user)
                status["verdict"] = "failed"
                status["failures"].append({"stage": "verdict", "error": str(exc)})
                status["result_state"] = "partial"
                await _stage(db, debate_id, status, "verdict", "failed", error=str(exc))
                await _stage(db, debate_id, status, "publishing", "skipped")
            await _save_status(db, debate_id, status)
        elif generate_verdict:
            status["verdict"] = "up_to_date"
            await _stage(db, debate_id, status, "verdict", "completed", {"reused": True})
            await _stage(db, debate_id, status, "publishing", "skipped", {"reason": "Stored verdict is current"})
            await _save_status(db, debate_id, status)
        status["state"] = status["result_state"]
        status["finished_at"] = _now().isoformat()
        status["current_stage"] = None
        await _save_status(db, debate_id, status)
        await DebateEventManager(bind=db.bind).emit(debate_id, "analysis_completed" if status["state"] == "completed" else "analysis_failed",
            {"run_id": status["run_id"], "state": status["state"]})
        logger.info(
            "Analysis %s (%s): state=%s claims=%d selected=%d verified=%d no_sources=%d failures=%d",
            debate_id, trigger, status["state"], status["claims_total"], status["claims_selected"],
            status["verified"], status["no_sources"], len(status["failures"]),
        )
        return status
    except asyncio.CancelledError:
        await _recover(db, user)
        status["state"] = "failed"
        status["finished_at"] = _now().isoformat()
        status["failures"].append({"stage": status.get("current_stage") or "pipeline", "error": "Analysis was interrupted. Retry to resume saved work."})
        if status.get("current_stage") in status["stages"]:
            status["stages"][status["current_stage"]].update(state="failed", finished_at=_now().isoformat(), error="Analysis was interrupted. Retry to resume.")
        await _save_status(db, debate_id, status)
        raise
    except Exception:
        await _recover(db, user)
        status["state"] = "failed"
        status["finished_at"] = _now().isoformat()
        status["failures"].append({"stage": "pipeline", "error": "An unexpected analysis error occurred."})
        if status.get("current_stage") in status["stages"]:
            status["stages"][status["current_stage"]].update(state="failed", finished_at=_now().isoformat(), error="This operation failed. Saved work can be retried.")
        await _save_status(db, debate_id, status)
        logger.exception("Analysis %s failed unexpectedly", debate_id)
        raise
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


def auto_analysis_enabled() -> bool:
    return get_settings().AUTO_ANALYSIS_AFTER_DEBATE


def schedule_analysis(bind, debate_id: UUID, user_id: UUID, trigger: str = "auto", *, claimed_status=None, regenerate=False) -> asyncio.Task:
    """Run the pipeline in the background on its own session (same engine
    as the request that scheduled it)."""
    session_factory = async_sessionmaker(bind, expire_on_commit=False)

    async def runner():
        async with session_factory() as db:
            user = await db.get(User, user_id)
            if user is None:
                return
            try:
                await run_analysis(db, user, debate_id, trigger=trigger, claimed_status=claimed_status, regenerate_verdict=regenerate)
            except AnalysisInProgressError:
                logger.info("Analysis %s already running; background run skipped", debate_id)
            except Exception:
                logger.exception("Background analysis %s failed", debate_id)

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def ensure_analysis(db, user, debate_id, *, regenerate=False):
    """Reserve a run before responding; repeats attach instead of duplicating work."""
    from app.services.debate_service import get_debate
    debate = await get_debate(db, user, debate_id)
    user_id = user.id
    if debate.status != "completed":
        raise AnalysisNotReadyError("Complete the debate transcript before starting analysis")
    try:
        reserved = await _claim_run(db, debate_id, "manual")
    except AnalysisInProgressError:
        await db.refresh(debate)
        return {**status_payload(debate), "joined": True,
                "message": "Analysis already in progress — showing live progress."}
    schedule_analysis(db.bind, debate_id, user_id, claimed_status=reserved, regenerate=regenerate)
    return {**reserved, "joined": False, "message": "Analysis started — showing live progress."}


async def wait_for_background() -> None:
    """Await scheduled runs (tests and graceful shutdown)."""
    while _background_tasks:
        await asyncio.gather(*list(_background_tasks), return_exceptions=True)


def status_payload(debate: Debate) -> dict:
    status = dict(debate.analysis_status or {"state": "not_started"})
    if is_stale(status):
        status["state"] = "failed"
        status.setdefault("failures", []).append(
            {"stage": "pipeline", "error": "The analysis run was interrupted."}
        )
    return status
