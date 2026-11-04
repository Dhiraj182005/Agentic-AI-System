from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
import logging
import re

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def log_connection_failure(exc: Exception, *, operation: str) -> None:
    """Allowlisted diagnostics only: driver text/tracebacks can embed credentials."""
    cause = exc
    chain = []
    seen = set()
    while id(cause) not in seen:
        seen.add(id(cause))
        chain.append(type(cause).__name__)
        nested = getattr(cause, "orig", None)
        if not isinstance(nested, BaseException):
            nested = cause.__cause__
        if not isinstance(nested, BaseException) and not cause.__suppress_context__:
            nested = cause.__context__
        if not isinstance(nested, BaseException) or id(nested) in seen:
            break
        cause = nested
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
    if isinstance(cause, TypeError):
        # Preserve useful connect() diagnostics without copying arbitrary
        # driver payloads, URLs, quoted credentials or SQL parameters.
        match = re.search(r"unexpected keyword argument ['\"]([a-z_]+)['\"]", str(cause))
        safe_options = {"sslmode", "channel_binding", "ssl", "application_name", "target_session_attrs"}
        if match and match.group(1) in safe_options:
            message = f"Database driver received unsupported connection keyword '{match.group(1)}'."
        else:
            message = "Database driver raised TypeError while preparing or executing the connection check; argument values withheld."
    logger.error(
        "postgresql_connection_failed operation=%s exception_type=%s exception_chain=%s error_message=%s",
        operation, name, " -> ".join(chain), message,
        extra={"event": "postgresql_connection_failed", "operation": operation,
               "exception_type": name, "exception_chain": chain, "error_message": message},
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
