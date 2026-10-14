import logging
from datetime import datetime, timezone

from app.websocket.manager import ConnectionManager, connection_manager

logger = logging.getLogger(__name__)

DEBATE_STARTED = "debate_started"
ROUND_STARTED = "round_started"
AGENT_TURN_STARTED = "agent_turn_started"
AGENT_MESSAGE = "agent_message"
AGENT_TURN_COMPLETED = "agent_turn_completed"
ROUND_COMPLETED = "round_completed"
DEBATE_COMPLETED = "debate_completed"
DEBATE_FAILED = "debate_failed"
ERROR = "error"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class DebateEventManager:
    """Builds debate event payloads and publishes them to the connection manager.

    Only the DebateEngine talks to this object; agents never see WebSockets.
    """

    def __init__(self, manager: ConnectionManager | None = None) -> None:
        self.manager = manager if manager is not None else connection_manager

    async def emit(self, debate_id, event_type: str, data: dict | None = None) -> dict:
        event = {
            "type": event_type,
            "debate_id": str(debate_id),
            "timestamp": _timestamp(),
            "data": data or {},
        }
        await self.manager.broadcast(str(debate_id), event)
        return event

    async def debate_started(self, debate_id, status: str = "running") -> dict:
        return await self.emit(debate_id, DEBATE_STARTED, {"status": status})

    async def round_started(self, debate_id, round_number: int) -> dict:
        return await self.emit(
            debate_id, ROUND_STARTED, {"round_number": round_number}
        )

    async def agent_turn_started(
        self, debate_id, round_number: int, turn_number: int, agent
    ) -> dict:
        return await self.emit(
            debate_id,
            AGENT_TURN_STARTED,
            {
                "round_number": round_number,
                "turn_number": turn_number,
                "agent": _agent_payload(agent),
            },
        )

    async def agent_message(
        self,
        debate_id,
        round_number: int,
        turn_number: int,
        message_type: str,
        message_id,
        agent,
        content: str,
    ) -> dict:
        return await self.emit(
            debate_id,
            AGENT_MESSAGE,
            {
                "round_number": round_number,
                "turn_number": turn_number,
                "message_type": message_type,
                "message_id": str(message_id),
                "agent": _agent_payload(agent),
                "content": content,
            },
        )

    async def agent_turn_completed(
        self, debate_id, round_number: int, turn_number: int, agent
    ) -> dict:
        return await self.emit(
            debate_id,
            AGENT_TURN_COMPLETED,
            {
                "round_number": round_number,
                "turn_number": turn_number,
                "agent": _agent_payload(agent),
            },
        )

    async def round_completed(self, debate_id, round_number: int) -> dict:
        return await self.emit(
            debate_id, ROUND_COMPLETED, {"round_number": round_number}
        )

    async def debate_completed(self, debate_id, status: str = "completed") -> dict:
        return await self.emit(debate_id, DEBATE_COMPLETED, {"status": status})

    async def debate_failed(self, debate_id, message: str) -> dict:
        return await self.emit(
            debate_id, DEBATE_FAILED, {"status": "failed", "message": message}
        )

    async def error(self, debate_id, message: str) -> dict:
        return await self.emit(debate_id, ERROR, {"message": message})


def _agent_payload(agent) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "role": agent.role,
    }
