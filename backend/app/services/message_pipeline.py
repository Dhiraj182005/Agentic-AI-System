"""Resumable per-message analysis. Each worker owns its session and commits independently."""
import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.models.debate_message import DebateMessage
from app.models.user import User
from app.services import argument_analysis_service as arguments


async def run_message_batch(db, user, debate_id: UUID, *, stage: str, force=False, progress=None):
    from app.services.debate_service import get_debate
    debate = await get_debate(db, user, debate_id)
    if debate.status != "completed":
        raise arguments.ArgumentAnalysisValidationError("Complete the debate before batch analysis")
    ids = list((await db.execute(select(DebateMessage.id).where(
        DebateMessage.debate_id == debate_id, DebateMessage.content != ""))).scalars())
    if not ids:
        raise arguments.ArgumentAnalysisValidationError("Debate has no messages to analyze")
    user_id = user.id
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    semaphore = asyncio.Semaphore(max(1, min(get_settings().ANALYSIS_MESSAGE_CONCURRENCY, 4)))
    summary = {"stage": stage, "total": len(ids), "completed": 0, "failed": 0, "failures": []}

    async def worker(message_id):
        async with semaphore, factory() as session:
            owner = await session.get(User, user_id)
            try:
                if stage == "fallacy":
                    await arguments.analyze_message_fallacy(session, owner, message_id, force=force)
                else:
                    await arguments.evaluate_argument(session, owner, message_id, force=force)
                return None
            except Exception:
                await session.rollback()
                # Provider exception text may contain response payloads. Persist a safe category.
                return {"stage": stage, "message_id": str(message_id),
                        "error": "Message analysis failed. Retry to process this message again."}

    tasks = [asyncio.create_task(worker(mid)) for mid in ids]
    try:
        for task in asyncio.as_completed(tasks):
            failure = await task
            if failure:
                summary["failed"] += 1
                summary["failures"].append(failure)
            else:
                summary["completed"] += 1
            if progress:
                await progress(dict(summary))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return summary
