import logging
import re
import sys

# Uvicorn's access logger writes the full request target, so a WebSocket
# upgrade line would contain `/ws/debates/{id}?token=<JWT>`. The JWT (and any
# provider key or bearer token that might ever reach a log line) must never be
# logged, so every log record is scrubbed before it is written.
_PATTERNS = [
    (re.compile(r"(token=)[^&\s\"']+"), r"\1<redacted>"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"), r"\1<redacted>"),
    (re.compile(r"\bgsk_[A-Za-z0-9]+"), "<redacted>"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
        "<redacted-jwt>",
    ),
]


class RedactSecretsFilter(logging.Filter):
    """Scrubs secrets from log records in place (idempotent)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for pattern, replacement in _PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install_redaction() -> None:
    """Attach the redaction filter to the app and uvicorn loggers/handlers.

    Called both at import time and from the FastAPI lifespan, so it works
    whichever order uvicorn configures its loggers in. Safe to call twice.
    """
    names = ("", "uvicorn", "uvicorn.access", "uvicorn.error")
    for name in names:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactSecretsFilter) for f in logger.filters):
            logger.addFilter(RedactSecretsFilter())
        for handler in logger.handlers:
            if not any(isinstance(f, RedactSecretsFilter) for f in handler.filters):
                handler.addFilter(RedactSecretsFilter())


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    install_redaction()
