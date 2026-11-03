import asyncio
import logging
import random
import re
import time

from groq import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from app.core.config import get_settings
from app.core.observability import llm_context_fields
from app.llm.base import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMContextLengthError,
    LLMEmptyResponseError,
    LLMMessage,
    LLMModelNotFoundError,
    LLMProviderAPIError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMServerError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

# Empty answers caused by an exhausted output budget are retried with a
# doubled budget at most this many times (bounded by the token ceiling).
MAX_BUDGET_ESCALATIONS = 2
TRANSIENT_STATUS_CODES = (408, 409, 425)


def _error_code(exc: APIStatusError) -> str:
    """Provider error code from the response body, e.g. 'model_not_found'."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            return str(error.get("code") or error.get("type") or "")
    return ""


_LIMIT_RE = re.compile(
    r"on (tokens|requests) per (minute|day|hour)[^:]*:\s*Limit (\d+), Used (\d+), Requested (\d+)",
    re.IGNORECASE,
)
_LIMIT_KINDS = {
    ("tokens", "minute"): "TPM", ("tokens", "day"): "TPD", ("tokens", "hour"): "TPH",
    ("requests", "minute"): "RPM", ("requests", "day"): "RPD", ("requests", "hour"): "RPH",
}


def _rate_limit_details(exc: APIStatusError) -> dict:
    """Which Groq limit was hit, from the error body (numbers only; the
    organisation id and free text are never kept)."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    message = str(error.get("message", "")) if isinstance(error, dict) else ""
    match = _LIMIT_RE.search(message)
    if not match:
        return {}
    unit, window, limit, used, requested = match.groups()
    return {
        "limit_kind": _LIMIT_KINDS.get((unit.lower(), window.lower())),
        "limit": int(limit),
        "used": int(used),
        "requested": int(requested),
    }


def _rate_limit_error(exc: APIStatusError) -> LLMRateLimitError:
    return LLMRateLimitError(
        "The LLM provider rate limit was reached.",
        retry_after=_retry_after_seconds(exc),
        **_rate_limit_details(exc),
    )


def _limit_headers(exc) -> str:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    keys = ("x-ratelimit-remaining-tokens", "x-ratelimit-remaining-requests",
            "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests")
    return " ".join(f"{k[12:]}={headers.get(k)}" for k in keys if headers.get(k) is not None)


def _retry_after_seconds(exc: APIStatusError) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            return max(float(raw) * scale, 0.0)
        except (TypeError, ValueError):
            continue
    return None


def classify_error(exc: Exception) -> tuple[LLMProviderError, bool]:
    """Map an SDK exception to (normalized error, is_transient).

    Only the exception type/status/code is used; provider payloads, keys and
    request bodies never reach the normalized message.
    """
    if isinstance(exc, APITimeoutError):
        return LLMTimeoutError("The LLM request timed out."), True
    if isinstance(exc, APIConnectionError):
        return LLMConnectionError("Could not connect to the LLM provider."), True
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return LLMAuthenticationError("The LLM provider rejected the credentials."), False
    if isinstance(exc, NotFoundError):
        return LLMModelNotFoundError("The configured LLM model was not found."), False
    if isinstance(exc, RateLimitError):
        return _rate_limit_error(exc), True
    if isinstance(exc, BadRequestError):
        code = _error_code(exc)
        if code in ("model_not_found", "model_decommissioned"):
            return LLMModelNotFoundError("The configured LLM model is unavailable."), False
        if code == "context_length_exceeded":
            return LLMContextLengthError("The request exceeded the model context."), False
        return LLMBadRequestError("The LLM provider rejected the request."), False
    if isinstance(exc, InternalServerError):
        return LLMServerError("The LLM provider had a server error."), True
    if isinstance(exc, APIStatusError) and _error_code(exc) == "rate_limit_exceeded":
        # Groq answers 413 "rate_limit_exceeded" when a request does not fit
        # the remaining per-minute token window; the same request succeeds
        # once the window refills, so it is transient like a 429.
        return _rate_limit_error(exc), True
    if isinstance(exc, APIStatusError):
        if exc.status_code in TRANSIENT_STATUS_CODES:
            return LLMServerError("The LLM provider asked to retry."), True
        return LLMProviderAPIError("The LLM provider request failed."), False
    return LLMProviderAPIError("The LLM provider request failed."), False


# model -> monotonic time until which its daily quota is known to be spent.
# Shared by every provider instance in this process, so exhausted models are
# skipped instead of being called (and refused) again for each request.
_EXHAUSTED_UNTIL: dict[str, float] = {}
_DEFAULT_EXHAUSTION_SECONDS = 1800.0


def _mark_exhausted(model: str, retry_after: float | None) -> None:
    _EXHAUSTED_UNTIL[model] = time.monotonic() + (retry_after or _DEFAULT_EXHAUSTION_SECONDS)


def _is_exhausted(model: str) -> bool:
    until = _EXHAUSTED_UNTIL.get(model)
    if until is None:
        return False
    if time.monotonic() >= until:
        _EXHAUSTED_UNTIL.pop(model, None)
        return False
    return True


def reset_exhausted_models() -> None:
    """Forget quota state (tests)."""
    _EXHAUSTED_UNTIL.clear()


class GroqProvider(BaseLLMProvider):
    """LLM provider backed by the Groq API.

    Retries are handled here (the SDK's own retries are disabled so the two
    never multiply): transient failures get bounded exponential backoff with
    jitter and honor Retry-After; permanent failures (bad key, unknown model,
    invalid request, context too long) fail immediately. A generation is a
    pure read from the provider's point of view - callers persist the result
    only after it succeeds - so retrying never duplicates stored messages.
    """

    provider_name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        retry_base_delay: float | None = None,
        retry_max_delay: float | None = None,
        max_output_tokens_ceiling: int | None = None,
        fallback_models: list[str] | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.model_name = model if model is not None else settings.GROQ_MODEL
        self.timeout = timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS
        self.max_retries = max(
            0, max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
        )
        self.retry_base_delay = (
            retry_base_delay
            if retry_base_delay is not None
            else settings.LLM_RETRY_BASE_DELAY_SECONDS
        )
        self.retry_max_delay = (
            retry_max_delay
            if retry_max_delay is not None
            else settings.LLM_RETRY_MAX_DELAY_SECONDS
        )
        self.max_output_tokens_ceiling = (
            max_output_tokens_ceiling
            if max_output_tokens_ceiling is not None
            else settings.LLM_MAX_OUTPUT_TOKENS_CEILING
        )

        if not self.api_key:
            raise LLMConfigurationError("GROQ_API_KEY is not configured.")
        if not self.model_name:
            raise LLMConfigurationError("GROQ_MODEL is not configured.")

        self._client = AsyncGroq(
            api_key=self.api_key, timeout=self.timeout, max_retries=0
        )
        # Injectable for tests so backoff never really sleeps there.
        self._sleep = asyncio.sleep
        self._attempts = 0
        self._escalations = 0
        self._json_mode = False
        self._active_model = self.model_name
        self.fallback_models = (
            list(fallback_models)
            if fallback_models is not None
            else [m.strip() for m in (settings.GROQ_FALLBACK_MODELS or "").split(",") if m.strip()]
        )

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after + random.uniform(0, 0.25)
        exponential = self.retry_base_delay * (2 ** attempt)
        return min(self.retry_max_delay, exponential) * random.uniform(0.5, 1.0)

    async def _create(self, groq_messages, temperature, max_tokens):
        """One chat completion with transient-failure retries."""
        attempt = 0
        extra = {"response_format": {"type": "json_object"}} if self._json_mode else {}
        while True:
            self._attempts += 1
            try:
                return await self._client.chat.completions.create(
                    model=self._active_model,
                    messages=groq_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra,
                )
            except (APIConnectionError, APIError) as exc:
                error, transient = classify_error(exc)
                status = getattr(exc, "status_code", None)
                details = ""
                if isinstance(error, LLMRateLimitError):
                    details = (
                        f" limit={error.limit_kind or 'unknown'}"
                        + (
                            f" used={error.used} of={error.limit} requested={error.requested}"
                            if error.limit is not None
                            else ""
                        )
                        + f" retry_after={error.retry_after}"
                        + (f" {_limit_headers(exc)}" if _limit_headers(exc) else "")
                    )
                logger.warning(
                    "Groq request failed (attempt %d/%d, model=%s): %s status=%s code=%s%s",
                    attempt + 1,
                    self.max_retries + 1,
                    self._active_model,
                    type(exc).__name__,
                    status,
                    _error_code(exc) if isinstance(exc, APIStatusError) else "",
                    details,
                )
                if not transient or attempt >= self.max_retries:
                    raise error from exc
                retry_after = getattr(error, "retry_after", None)
                if getattr(error, "limit_kind", None) in ("TPD", "RPD"):
                    # A daily quota is not refilled by a short retry.
                    raise error from exc
                if retry_after is not None and retry_after > self.retry_max_delay:
                    logger.warning(
                        "Groq asked to wait %.1fs (> %.1fs limit); not retrying",
                        retry_after,
                        self.retry_max_delay,
                    )
                    raise error from exc
                delay = self._backoff_delay(attempt, retry_after)
                logger.info("Retrying Groq request in %.2fs", delay)
                await self._sleep(delay)
                attempt += 1

    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        if not messages:
            raise LLMProviderError("Cannot generate a response from an empty message list.")

        groq_messages = [{"role": message.role, "content": message.content} for message in messages]

        self._json_mode = json_mode
        chain = self.model_chain()
        last_error: LLMProviderError | None = None
        for model in chain:
            if model != chain[0] and _is_exhausted(model):
                continue
            if model == chain[0] and len(chain) > 1 and _is_exhausted(model):
                continue
            self._active_model = model
            started = time.monotonic()
            self._attempts = 0
            self._escalations = 0
            try:
                response = await self._generate(groq_messages, temperature, max_tokens)
            except LLMRateLimitError as exc:
                self._log_call(started, outcome="error", category=type(exc).__name__)
                last_error = exc
                if exc.limit_kind in ("TPD", "RPD") and len(chain) > 1:
                    # Daily quota of this model is spent: remember it (shared
                    # by all provider instances) and use the next model.
                    _mark_exhausted(model, exc.retry_after)
                    logger.warning(
                        "Model %s daily %s quota exhausted; trying fallback model",
                        model,
                        "token" if exc.limit_kind == "TPD" else "request",
                    )
                    continue
                raise
            except LLMProviderError as exc:
                self._log_call(started, outcome="error", category=type(exc).__name__)
                raise
            self._log_call(started, outcome="ok")
            return response
        if last_error is not None:
            last_error.user_message = (
                "The daily quota of every configured language model is used up "
                f"({', '.join(chain)}). Try again later or raise the account tier."
            )
            raise last_error
        raise LLMRateLimitError(
            "All configured models are temporarily exhausted.",
            limit_kind="TPD",
        )

    def model_chain(self) -> list[str]:
        """Primary model first, then GROQ_FALLBACK_MODELS (deduplicated)."""
        chain = [self.model_name]
        for model in self.fallback_models:
            if model and model not in chain:
                chain.append(model)
        return chain

    def _log_call(self, started: float, *, outcome: str, category: str | None = None) -> None:
        """One line per generation: no prompt text, no credentials."""
        logger.info(
            "llm_call provider=%s model=%s outcome=%s%s duration_ms=%d attempts=%d escalations=%d %s",
            self.provider_name,
            self._active_model,
            outcome,
            f" category={category}" if category else "",
            (time.monotonic() - started) * 1000,
            self._attempts,
            self._escalations,
            llm_context_fields(),
        )

    async def _generate(self, groq_messages, temperature, max_tokens) -> LLMResponse:
        budget = max_tokens
        escalations = 0
        while True:
            completion = await self._create(groq_messages, temperature, budget)

            try:
                choice = completion.choices[0]
                content = choice.message.content
            except (AttributeError, IndexError) as exc:
                logger.error(
                    "Groq returned an unreadable response: %s", type(exc).__name__
                )
                raise LLMProviderError(
                    "The LLM provider returned an unreadable response."
                ) from exc

            finish_reason = getattr(choice, "finish_reason", None)
            if content:
                if finish_reason == "length":
                    logger.warning(
                        "Groq answer was cut off at max_tokens=%s (model=%s)",
                        budget,
                        self._active_model,
                    )
                return LLMResponse(
                    content=content,
                    provider=self.provider_name,
                    model=self._active_model,
                )

            usage = getattr(completion, "usage", None)
            details = getattr(usage, "completion_tokens_details", None)
            logger.error(
                "Groq returned empty content (model=%s, finish_reason=%s, "
                "completion_tokens=%s, reasoning_tokens=%s, max_tokens=%s)",
                self._active_model,
                finish_reason,
                getattr(usage, "completion_tokens", None) if usage else None,
                getattr(details, "reasoning_tokens", None) if details else None,
                budget,
            )
            # Reasoning models can spend the whole budget before writing any
            # visible text. Retry the same request with a larger budget.
            if (
                finish_reason == "length"
                and budget is not None
                and escalations < MAX_BUDGET_ESCALATIONS
                and budget < self.max_output_tokens_ceiling
            ):
                budget = min(budget * 2, self.max_output_tokens_ceiling)
                escalations += 1
                self._escalations = escalations
                logger.info("Retrying with max_tokens=%s", budget)
                continue
            raise LLMEmptyResponseError("The LLM provider returned an empty response.")
