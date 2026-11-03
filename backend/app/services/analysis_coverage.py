"""Current persisted coverage, independent of historical judge limitations."""
from sqlalchemy import select
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence, SOURCE_WEB
from app.models.fallacy import Fallacy
from app.models.verdict import DebateVerdict
from app.services.judge_rubric import rubric_snapshot
from app.core.config import get_settings


async def coverage_payload(db, debate):
    async def rows(model):
        return list((await db.execute(select(model).where(model.debate_id == debate.id))).scalars())
    messages, rounds, claims, checks, evaluations = [await rows(model) for model in
        (DebateMessage, DebateRound, Claim, Fallacy, ArgumentEvaluation)]
    ids = [c.id for c in claims]
    evidence = list((await db.execute(select(Evidence).where(Evidence.claim_id.in_(ids)))).scalars()) if ids else []
    verifications = list((await db.execute(select(ClaimVerification).where(ClaimVerification.claim_id.in_(ids)))).scalars()) if ids else []
    factual_ids = {c.id for c in claims if c.claim_type == "factual"}
    verified = [v for v in verifications if v.claim_id in factual_ids]
    eligible = [m for m in messages if m.content.strip()]
    failures = (debate.analysis_status or {}).get("failures", [])
    google = (debate.analysis_status or {}).get("fact_check") or {}
    verdict = (await db.execute(select(DebateVerdict).where(DebateVerdict.debate_id == debate.id))).scalar_one_or_none()
    def stage(done, total, name):
        if total == 0:
            return "not_run"
        if done >= total:
            return "completed"
        failed = any(f.get("stage") == name for f in failures)
        if failed:
            return "partial" if done else "failed"
        return "partial" if done else "pending" if (debate.analysis_status or {}).get("state") == "running" else "not_run"
    fallacy_count = len({f.message_id for f in checks})
    agents = []
    for agent in debate.agents:
        scores = [e for e in evaluations if e.agent_id == agent.id]
        agents.append({"agent_id": str(agent.id), "agent_name": agent.name,
            "messages": sum(m.agent_id == agent.id for m in eligible), "evaluations": len(scores),
            "average_score": round(sum(e.overall_score for e in scores) / len(scores), 2) if scores else None})
    extracted_messages = sum(m.claims_extracted_at is not None for m in eligible)
    google_pending = sum(c.id in factual_ids and c.fact_check_status is None for c in claims)
    pending = (max(0, len(eligible) - fallacy_count) + max(0, len(eligible) - len(evaluations))
               + len(factual_ids) - len(verified) + len(eligible) - extracted_messages + google_pending)
    return {"agents": len(debate.agents), "rounds": len(rounds), "messages": len(eligible),
        "messages_analyzed": len({f.message_id for f in checks} | {e.message_id for e in evaluations}),
        "fallacy_analyses": fallacy_count, "fallacies_detected": sum(f.fallacy_type != "no_fallacy" for f in checks),
        "quality_evaluations": len(evaluations), "claims": len(claims), "unique_claims": len({c.canonical_claim_id or c.id for c in claims}), "factual_claims": len(factual_ids),
        "claims_verified": len(verified), "insufficient_evidence": sum(v.verdict == "insufficient_evidence" for v in verified),
        "google_fact_checks": sum(e.source_type == "google_fact_check" for e in evidence),
        "tavily_sources": sum(e.source_type == SOURCE_WEB for e in evidence),
        "failed_operations": len(failures) + google.get("failed", 0), "pending_operations": pending,
        "google_search_status": google.get("status", "not_run"),
        "fallacy_status": stage(fallacy_count, len(eligible), "fallacy"),
        "quality_status": stage(len(evaluations), len(eligible), "evaluation"),
        "verification_status": stage(len(verified), len(factual_ids), "verification"),
        "extraction_status": stage(sum(m.claims_extracted_at is not None for m in eligible), len(eligible), "extraction"),
        "verdict_status": "stored" if verdict else (debate.analysis_status or {}).get("verdict", "not_run"),
        "agent_comparisons": agents, "rubric": rubric_snapshot(get_settings().JUDGE_MIN_SCORE_GAP)}
