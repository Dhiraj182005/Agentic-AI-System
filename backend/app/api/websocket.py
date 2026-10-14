import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.websocket.auth import WebSocketAuthError, authenticate_debate_websocket
from app.websocket.manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.websocket("/ws/debates/{debate_id}")
async def debate_websocket(
    websocket: WebSocket,
    debate_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Observation channel for a running debate.

    Authentication reuses the Module 2 JWT passed as a query parameter:
    `/ws/debates/{debate_id}?token=<JWT>`. The token is only decoded, never
    logged, stored or broadcast. The socket can only watch a debate owned by
    the authenticated user.
    """
    await websocket.accept()

    try:
        debate = await authenticate_debate_websocket(
            db, websocket.query_params.get("token"), debate_id
        )
    except WebSocketAuthError as exc:
        logger.warning(
            "WebSocket refused for debate %s (close code %s)",
            debate_id,
            exc.code,
        )
        await websocket.close(code=exc.code)
        return

    debate_key = str(debate.id)
    connection_manager.register(websocket, debate_key)
    logger.info("WebSocket connected for debate %s", debate_key)

    try:
        # Reading keeps the connection alive and notices disconnects. The
        # socket never drives the debate: it is an observation channel only.
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            text = message.get("text")
            if not text:
                continue
            try:
                json.loads(text)
            except (TypeError, ValueError):
                await websocket.send_json(
                    {
                        "type": "error",
                        "debate_id": debate_key,
                        "timestamp": _now(),
                        "data": {"message": "Malformed event"},
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("WebSocket connection error for debate %s", debate_key)
    finally:
        connection_manager.unregister(websocket, debate_key)
        logger.info("WebSocket disconnected for debate %s", debate_key)
