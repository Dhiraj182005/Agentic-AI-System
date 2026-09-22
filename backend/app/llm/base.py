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
    """Base class for all LLM provider failures."""


class LLMConfigurationError(LLMProviderError):
    """Raised when LLM configuration is missing or invalid."""


class LLMProviderAPIError(LLMProviderError):
    """Raised when the underlying LLM API returns an error."""


class LLMTimeoutError(LLMProviderError):
    """Raised when an LLM request exceeds the configured timeout."""


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
    ) -> LLMResponse:
        """Generate a completion from a list of messages."""
        raise NotImplementedError