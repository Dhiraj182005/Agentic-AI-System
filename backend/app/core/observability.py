"""Request correlation and LLM-call context.

Every HTTP request gets a request id (taken from a valid ``X-Request-ID``
header or generated) that is echoed in the response and attached to log
records. The debate engine sets the debate/round/agent context, so a single
LLM call log line tells a developer where it happened without logging any
prompt content or credentials.
"""

from __future__ import annotations

import contextvars
import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
llm_context_var: contextvars.ContextVar[dict] = contextvars.ContextVar("llm_context", default={})

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class RequestIdFilter(logging.Filter):
    """Adds ``request_id`` to every record (for format strings and tools)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def set_llm_context(**values) -> contextvars.Token:
    """Set debate/round/agent context for LLM calls made in this task."""
    merged = {**llm_context_var.get(), **{k: v for k, v in values.items() if v is not None}}
    return llm_context_var.set(merged)


def reset_llm_context(token: contextvars.Token) -> None:
    llm_context_var.reset(token)


def llm_context_fields() -> str:
    context = llm_context_var.get()
    return " ".join(f"{key}={context[key]}" for key in sorted(context))
