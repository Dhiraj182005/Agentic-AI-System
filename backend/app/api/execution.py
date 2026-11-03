from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.debate_service import DebateNotFoundError, DebateConflictError
from app.services.execution_service import execution_snapshot

router = APIRouter(prefix="/debates", tags=["execution"])


@router.get("/{debate_id}/execution")
async def get_execution(debate_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        return await execution_snapshot(db, user, debate_id)
    except DebateNotFoundError:
        raise HTTPException(404, "Debate not found")


@router.post("/{debate_id}/execute", status_code=202)
async def execute(debate_id: UUID, resume: bool = False, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.debate_service import schedule_execution
    try:
        await schedule_execution(db, user, debate_id, resume=resume)
        return await execution_snapshot(db, user, debate_id)
    except DebateNotFoundError:
        raise HTTPException(404, "Debate not found")
    except DebateConflictError as exc:
        raise HTTPException(409, str(exc))
