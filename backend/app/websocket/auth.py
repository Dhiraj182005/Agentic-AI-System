from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.models.debate import Debate
from app.models.user import User

# Application close codes (4000-4999 range) so clients can tell auth failures
# apart from ordinary disconnects.
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


class WebSocketAuthError(Exception):
    """Raised when a WebSocket subscription must be refused."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def authenticate_debate_websocket(
    db: AsyncSession, token: str | None, debate_id: UUID
) -> Debate:
    """Validate the existing Module 2 JWT and the debate ownership.

    The same token format and secret are used as for HTTP requests; no second
    authentication system is introduced. The token itself is never logged.
    """
    if not token:
        raise WebSocketAuthError(CLOSE_UNAUTHORIZED, "Authentication required")

    subject = decode_access_token(token)
    if subject is None:
        raise WebSocketAuthError(CLOSE_UNAUTHORIZED, "Invalid or expired token")

    try:
        user_id = UUID(subject)
    except ValueError:
        raise WebSocketAuthError(CLOSE_UNAUTHORIZED, "Invalid or expired token")

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise WebSocketAuthError(CLOSE_UNAUTHORIZED, "Invalid or expired token")

    debate = (
        await db.execute(select(Debate).where(Debate.id == debate_id))
    ).scalar_one_or_none()
    if debate is None:
        raise WebSocketAuthError(CLOSE_NOT_FOUND, "Debate not found")

    if debate.user_id != user.id:
        raise WebSocketAuthError(
            CLOSE_FORBIDDEN, "You cannot watch this debate"
        )

    return debate
