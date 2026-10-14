import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks WebSocket connections per debate.

    The manager is process-local (in-memory), which is correct for this
    single-backend MVP. A multi-instance deployment would need shared
    infrastructure (e.g. Redis Pub/Sub) to fan events out across processes.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set] = {}

    def register(self, websocket, debate_id: str) -> None:
        """Associate a socket with a debate."""
        self._connections.setdefault(str(debate_id), set()).add(websocket)

    def unregister(self, websocket, debate_id: str) -> None:
        """Remove a socket; forgotten debates are cleaned up."""
        key = str(debate_id)
        sockets = self._connections.get(key)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(key, None)

    def sockets_for(self, debate_id: str) -> set:
        return set(self._connections.get(str(debate_id), set()))

    def connection_count(self, debate_id: str | None = None) -> int:
        if debate_id is None:
            return sum(len(sockets) for sockets in self._connections.values())
        return len(self._connections.get(str(debate_id), set()))

    def is_watched(self, debate_id: str) -> bool:
        return self.connection_count(debate_id) > 0

    async def broadcast(self, debate_id: str, event: dict) -> int:
        """Send an event to every client watching the debate.

        A failing socket is dropped and never breaks the broadcast for the
        remaining clients.
        """
        delivered = 0
        for websocket in self.sockets_for(debate_id):
            try:
                await websocket.send_json(event)
                delivered += 1
            except Exception:
                logger.warning(
                    "Removing WebSocket that failed to receive an event for debate %s",
                    debate_id,
                )
                self.unregister(websocket, debate_id)
        return delivered

    def drop_all(self) -> None:
        self._connections.clear()


# Process-local singleton: the backend runs a single worker process.
connection_manager = ConnectionManager()
