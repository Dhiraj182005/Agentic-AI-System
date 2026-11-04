from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
import logging

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def log_connection_failure(exc: Exception, *, operation: str) -> None:
    """Allowlisted diagnostics only: driver text/tracebacks can embed credentials."""
    cause = getattr(exc, "orig", None) or exc
    name = type(cause).__name__
    messages = {
        "InvalidPasswordError": "PostgreSQL authentication failed.",
        "InvalidAuthorizationSpecificationError": "PostgreSQL authorization failed.",
        "InvalidCatalogNameError": "The requested PostgreSQL database is unavailable.",
        "CannotConnectNowError": "PostgreSQL is not accepting connections now.",
        "TooManyConnectionsError": "PostgreSQL connection capacity was reached.",
        "ConnectionRefusedError": "The database connection was refused.",
        "gaierror": "Database hostname resolution failed.",
        "TimeoutError": "The database connection timed out.",
        "SSLCertVerificationError": "Database TLS certificate verification failed.",
        "SSLError": "Database TLS negotiation failed.",
    }
    message = messages.get(name, "PostgreSQL connection check failed; driver details withheld to protect credentials.")
    logger.error(
        "postgresql_connection_failed operation=%s exception_type=%s error_message=%s",
        operation, name, message,
        extra={"event": "postgresql_connection_failed", "operation": operation,
               "exception_type": name, "error_message": message},
    )

# SQL parameter logging can expose user content and authentication hashes.
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
