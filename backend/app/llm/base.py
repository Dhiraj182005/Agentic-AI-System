from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant"]


class LLMMessage(BaseModel):
    """Provider-independent chat message."""

    role: MessageRole
    content: str = Field(min_length=1)


class LLMResponse(BaseModel):
    """Normalized LLM generation result shared across providers."""

    content: str
    provider: str
    model: str


class LLMProviderError(Exception):
    """Base class for all LLM provider failures.

    ``user_message`` is safe to show to end users (no provider payloads,
    keys or internals); details belong in the server logs only.
    """

    user_message = "The language model provider request failed."


class LLMConfigurationError(LLMProviderError):
    """Raised when LLM configuration is missing or invalid."""

    user_message = "The language model provider is not configured correctly."


class LLMProviderAPIError(LLMProviderError):
    """Raised when the underlying LLM API returns an error."""


class LLMTimeoutError(LLMProviderError):
    """Raised when an LLM request exceeds the configured timeout."""

    user_message = "The language model provider did not respond in time."


# Transient API failures (retried with backoff by the provider).


class LLMConnectionError(LLMProviderAPIError):
    user_message = "The language model provider could not be reached."


def _wait_text(seconds: float | None) -> str:
    if seconds is None:
        return "later"
    if seconds < 90:
        return f"in about {max(1, round(seconds))} seconds"
    return f"in about {round(seconds / 60)} minutes"


class LLMRateLimitError(LLMProviderAPIError):
    """A provider rate limit or quota. ``limit_kind`` tells which one:
    TPM / RPM (per minute, short waits), TPD / RPD (daily quota, long waits)
    or None when the provider did not say."""

    user_message = (
        "The language model provider's rate limit or quota was reached. "
        "Wait a moment and try again."
    )

    def __init__(
        self,
        message: str = "",
        retry_after: float | None = None,
        limit_kind: str | None = None,
        limit: int | None = None,
        used: int | None = None,
        requested: int | None = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit_kind = limit_kind
        self.limit = limit
        self.used = used
        self.requested = requested
        wait = _wait_text(retry_after)
        if limit_kind == "TPD":
            usage = f" ({used:,} of {limit:,} tokens used)" if used is not None and limit else ""
            self.user_message = (
                f"The language model account's daily token quota is used up{usage}. "
                f"Groq accepts this request again {wait}; a full debate needs far "
                "more tokens than that frees, so try later or raise the account tier."
            )
        elif limit_kind == "RPD":
            self.user_message = (
                "The language model account's daily request quota is used up. "
                f"Try again {wait} or raise the account tier."
            )
        elif limit_kind in ("TPM", "RPM"):
            unit = "token" if limit_kind == "TPM" else "request"
            self.user_message = (
                f"The language model's per-minute {unit} limit was reached. "
                f"Try again {wait}."
            )


class LLMServerError(LLMProviderAPIError):
    user_message = "The language model provider had a temporary server error."


# Permanent API failures (never retried).


class LLMAuthenticationError(LLMProviderAPIError):
    user_message = (
        "The language model provider rejected the API key. Check GROQ_API_KEY."
    )


class LLMModelNotFoundError(LLMProviderAPIError):
    user_message = (
        "The configured language model is not available. Check GROQ_MODEL."
    )


class LLMBadRequestError(LLMProviderAPIError):
    user_message = "The language model provider rejected the request."


class LLMContextLengthError(LLMBadRequestError):
    user_message = "The debate context is too long for the configured model."


class LLMEmptyResponseError(LLMProviderError):
    """The provider answered but produced no text."""

    user_message = (
        "The language model returned an empty answer (its response budget "
        "was used up by internal reasoning)."
    )


class BaseLLMProvider(ABC):
    """Common interface every LLM provider must implement."""

    provider_name: str = "base"
    model_name: str = ""

    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a completion from a list of messages.

        ``json_mode`` asks the provider to guarantee a syntactically valid
        JSON object (when it supports that); callers still validate it.
        """
        raise NotImplementedError