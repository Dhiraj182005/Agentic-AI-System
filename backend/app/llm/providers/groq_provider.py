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

        self._client = AsyncGroq(api_key=self.api_key, timeout=self.timeout)

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
            logger.warning("Groq API request failed: %s", type(exc).__name__)
            raise LLMProviderAPIError("The LLM provider request failed.") from exc

        try:
            content = completion.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise LLMProviderError("The LLM provider returned an unreadable response.") from exc

        if not content:
            raise LLMProviderError("The LLM provider returned an empty response.")

        return LLMResponse(
            content=content,
            provider=self.provider_name,
            model=self.model_name,
        )