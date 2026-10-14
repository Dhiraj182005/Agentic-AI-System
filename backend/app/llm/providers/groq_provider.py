import logging

from groq import AsyncGroq
from groq import APIConnectionError, APITimeoutError, APIError

from app.core.config import get_settings
from app.llm.base import (
    BaseLLMProvider,
    LLMConfigurationError,
    LLMMessage,
    LLMProviderAPIError,
    LLMProviderError,
    LLMResponse,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


class GroqProvider(BaseLLMProvider):
    """LLM provider backed by the Groq API."""

    provider_name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.model_name = model if model is not None else settings.GROQ_MODEL
        self.timeout = timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS

        if not self.api_key:
            raise LLMConfigurationError("GROQ_API_KEY is not configured.")
        if not self.model_name:
            raise LLMConfigurationError("GROQ_MODEL is not configured.")

        # Retry transient failures (including 429 rate limits) with the
        # SDK's exponential backoff, so a short-lived token bucket refill
        # does not fail a whole request immediately.
        self._client = AsyncGroq(
            api_key=self.api_key, timeout=self.timeout, max_retries=4
        )

    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not messages:
            raise LLMProviderError("Cannot generate a response from an empty message list.")

        groq_messages = [{"role": message.role, "content": message.content} for message in messages]

        try:
            completion = await self._client.chat.completions.create(
                model=self.model_name,
                messages=groq_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except APITimeoutError as exc:
            logger.warning("Groq request timed out after %ss", self.timeout)
            raise LLMTimeoutError("The LLM request timed out.") from exc
        except (APIConnectionError, APIError) as exc:
            # Log the original exception message (status codes, rate-limit
            # details, payload errors) so the terminal shows the root cause.
            logger.warning(
                "Groq API request failed: %s: %s",
                type(exc).__name__,
                str(exc)[:300],
            )
            raise LLMProviderAPIError("The LLM provider request failed.") from exc

        try:
            choice = completion.choices[0]
            content = choice.message.content
        except (AttributeError, IndexError) as exc:
            logger.error(
                "Groq returned an unreadable response: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise LLMProviderError("The LLM provider returned an unreadable response.") from exc

        if not content:
            usage = getattr(completion, "usage", None)
            details = getattr(usage, "completion_tokens_details", None)
            logger.error(
                "Groq returned empty content (finish_reason=%s, "
                "completion_tokens=%s, reasoning_tokens=%s, max_tokens=%s): "
                "reasoning tokens count against max_tokens and can exhaust "
                "the budget before any content is produced",
                getattr(choice, "finish_reason", None),
                getattr(usage, "completion_tokens", None) if usage else None,
                getattr(details, "reasoning_tokens", None) if details else None,
                max_tokens,
            )
            raise LLMProviderError("The LLM provider returned an empty response.")

        return LLMResponse(
            content=content,
            provider=self.provider_name,
            model=self.model_name,
        )