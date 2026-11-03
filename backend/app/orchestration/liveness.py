"""Liveness heartbeat for running debates.

Debates execute inside the HTTP request that started them. If the server
stops mid-debate (restart, crash, redeploy) nothing would ever move the
debate out of 'running'. While a debate executes, the worker keeps a short-TTL
Redis key alive; a 'running' debate without that key - and with no database
update for a grace period - is reliably interrupted, across restarts and
multiple workers. If Redis is unreachable, callers fall back to an elapsed
time threshold instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets

from app.core.config import get_settings
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


def heartbeat_key(debate_id) -> str:
    return f"maves:debate:{debate_id}:heartbeat"


async def is_alive(debate_id) -> bool | None:
    """True/False from the heartbeat, or None when Redis is unavailable."""
    try:
        return bool(await redis_client.exists(heartbeat_key(debate_id)))
    except Exception:
        logger.warning("Redis unavailable for debate liveness check", exc_info=True)
        return None


class DebateHeartbeat:
    """Async context manager that keeps the heartbeat key alive while the
    debate executes and removes it afterwards (only if it is still ours)."""

    def __init__(self, debate_id, ttl: int | None = None):
        self.key = heartbeat_key(debate_id)
        self.ttl = max(int(ttl or get_settings().DEBATE_HEARTBEAT_TTL_SECONDS), 3)
        self.token = secrets.token_hex(8)
        self._task: asyncio.Task | None = None

    async def _beat(self) -> None:
        try:
            await redis_client.set(self.key, self.token, ex=self.ttl)
        except Exception:
            logger.warning("Could not write debate heartbeat", exc_info=True)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.ttl / 3)
            await self._beat()

    async def __aenter__(self) -> "DebateHeartbeat":
        await self._beat()
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        try:
            if await redis_client.get(self.key) == self.token:
                await redis_client.delete(self.key)
        except Exception:
            logger.warning("Could not clear debate heartbeat", exc_info=True)
