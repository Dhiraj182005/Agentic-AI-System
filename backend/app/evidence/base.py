from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

ClaimType = Literal["factual", "opinion", "prediction", "definition", "other"]

MAX_QUERY_LENGTH = 300


class SearchResult(BaseModel):
    """Normalized search result shared by every evidence provider."""

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    snippet: str = ""
    source_name: str = Field(min_length=1)
    relevance_score: float | None = None


class EvidenceProviderError(Exception):
    """Base class for all evidence provider failures."""


class EvidenceConfigurationError(EvidenceProviderError):
    """Raised when the evidence provider is missing configuration."""


class EvidenceProviderAPIError(EvidenceProviderError):
    """Raised when the underlying search API returns an error."""


class EvidenceTimeoutError(EvidenceProviderError):
    """Raised when a search request exceeds the configured timeout."""


class EvidenceProviderResponseError(EvidenceProviderError):
    """Raised when the provider returns a malformed/unexpected payload."""


class EvidenceProvider(ABC):
    """Common interface every evidence/search provider must implement."""

    provider_name: str = "base"

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Run a search and return normalized results."""
        raise NotImplementedError
