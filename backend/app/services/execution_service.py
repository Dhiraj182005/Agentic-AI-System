"""One persisted source of truth for Overview and the verdict workspace."""
from sqlalchemy import select
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.execution_event import ExecutionEvent
from app.models.verdict import DebateVerdict
from app.services.debate_service import get_debate


async def execution_snapshot(db, user, debate_id):
    debate = await get_debate(db, user, debate_id)
    rounds = list((await db.execute(select(DebateRound).where(DebateRound.debate_id == debate_id)
                                   .order_by(DebateRound.round_number))).scalars())
    messages = list((await db.execute(select(DebateMessage, DebateRound.round_number).join(DebateRound)
                                     .where(DebateMessage.debate_id == debate_id))).all())
    events = list(reversed((await db.execute(select(ExecutionEvent).where(ExecutionEvent.debate_id == debate_id)
                                             .order_by(ExecutionEvent.id.desc()).limit(100))).scalars().all()))
    from app.services.analysis_pipeline import status_payload
    verdict = (await db.execute(select(DebateVerdict.id).where(DebateVerdict.debate_id == debate_id))).scalar_one_or_none()
    await db.refresh(debate, ["status", "execution_state", "analysis_status"])
    analysis = status_payload(debate)
    from app.services.analysis_coverage import coverage_payload
    analysis["coverage"] = await coverage_payload(db, debate)
    phase = debate.execution_state
    if debate.status in ("failed", "cancelled"):
        phase = debate.status
    elif debate.status == "pending":
        phase = "created"
    elif debate.status == "running":
        phase = "starting" if phase == "starting" else "running"
    elif analysis.get("state") == "running":
        phase = "generating_verdict" if analysis.get("current_stage") in ("verdict", "publishing") else "analyzing"
    elif analysis.get("state") in ("failed", "partial") and analysis.get("verdict") not in ("generated", "up_to_date"):
        phase = "failed"
    elif verdict:
        phase = "completed"
    else:
        phase = "analyzing"  # transcript finished, analysis is ready/pending, not falsely complete
    active_round = next((r.round_number for r in rounds if r.status == "running"), None)
    if phase == "starting" and active_round is not None:
        phase = "running"
    latest_turn = next((e for e in reversed(events) if e.event_type in (
        "agent_turn_started", "agent_turn_completed", "debate_completed", "debate_failed")), None)
    active = latest_turn.data.get("agent") if latest_turn and latest_turn.event_type == "agent_turn_started" and debate.status == "running" else None
    agents = []
    for agent in debate.agents:
        completed = [number for message, number in messages if message.agent_id == agent.id]
        speaking = active and active.get("id") == str(agent.id)
        failed = debate.status == "failed" and latest_turn and latest_turn.event_type == "debate_failed"
        # Only identify a failed speaker if a recorded start exists for that agent.
        last_start = next((e for e in reversed(events) if e.event_type == "agent_turn_started"), None)
        failed = bool(failed and last_start and last_start.data.get("agent", {}).get("id") == str(agent.id))
        status = "failed" if failed else "generating_rebuttal" if speaking and (active_round or 1) > 1 else "generating_argument" if speaking else "completed" if len(completed) >= debate.total_rounds else "waiting"
        agents.append({"id": str(agent.id), "name": agent.name, "role": agent.role, "status": status,
                       "latest_completed_round": max(completed, default=0), "current_round": active_round if speaking else None,
                       "completed_turns": len(completed)})
    expected = len(debate.agents) * debate.total_rounds
    return {"debate_id": str(debate.id), "execution_state": phase, "transcript_status": debate.status,
        "sequence": events[-1].id if events else 0, "current_round": active_round or max((r.round_number for r in rounds), default=0),
        "total_rounds": debate.total_rounds, "completed_rounds": sum(r.status == "completed" for r in rounds),
        "completed_turns": len(messages), "total_turns": expected,
        "debate_progress": round(min(len(messages) / expected, 1) * 100, 1) if expected else 0,
        "current_agent": active, "agents": agents,
        "rounds": [{"number": r.round_number, "status": r.status, "started_at": r.started_at,
                    "completed_at": r.completed_at} for r in rounds],
        "analysis": analysis, "verdict_available": verdict is not None,
        "events": [{"id": str(e.id), "sequence": e.id, "type": e.event_type,
                    "timestamp": e.created_at.isoformat(), "debate_id": str(e.debate_id), "data": e.data} for e in events]}
