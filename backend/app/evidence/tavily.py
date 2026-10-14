import logging
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.evidence.base import (
    MAX_QUERY_LENGTH,
    EvidenceConfigurationError,
    EvidenceProvider,
    EvidenceProviderAPIError,
    EvidenceProviderResponseError,
    EvidenceTimeoutError,
    SearchResult,
)

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_RESULTS_LIMIT = 10


class TavilyEvidenceProvider(EvidenceProvider):
    """Evidence provider backed by the Tavily search API."""

    provider_name = "tavily"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        if api_key is None:
            api_key = get_settings().TAVILY_API_KEY
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self._client = client

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            raise EvidenceConfigurationError(
                "Evidence provider is not configured (missing API key)"
            )

        clean_query = (query or "").strip()
        if not clean_query:
            raise EvidenceProviderAPIError("Search query cannot be empty")

        limit = max(1, min(int(max_results), MAX_RESULTS_LIMIT))
        payload = {
            "api_key": self.api_key,
            "query": clean_query[:MAX_QUERY_LENGTH],
            "max_results": limit,
            "search_depth": "basic",
            "include_answer": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            response = await self._post(payload, headers)
        except httpx.TimeoutException as exc:
            logger.error("Tavily search timed out")
            raise EvidenceTimeoutError("The evidence provider timed out") from exc
        except httpx.HTTPError as exc:
            logger.error("Tavily search failed: %s", type(exc).__name__)
            raise EvidenceProviderAPIError(
                "The evidence provider could not be reached"
            ) from exc

        if response.status_code != 200:
            logger.error("Tavily search returned status %s", response.status_code)
            raise EvidenceProviderAPIError(
                "The evidence provider returned an error"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise EvidenceProviderResponseError(
                "The evidence provider returned a malformed response"
            ) from exc

        return self._normalize(body, limit)

    async def _post(
        self, payload: dict, headers: dict
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                TAVILY_SEARCH_URL, json=payload, headers=headers, timeout=self.timeout
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(
                TAVILY_SEARCH_URL, json=payload, headers=headers, timeout=self.timeout
            )

    @staticmethod
    def _normalize(body: object, limit: int) -> list[SearchResult]:
        if not isinstance(body, dict):
            raise EvidenceProviderResponseError(
                "The evidence provider returned a malformed response"
            )
        raw_results = body.get("results")
        if raw_results is None:
            return []
        if not isinstance(raw_results, list):
            raise EvidenceProviderResponseError(
                "The evidence provider returned a malformed response"
            )

        results: list[SearchResult] = []
        for item in raw_results:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "").strip() or url
            snippet = str(item.get("content") or item.get("snippet") or "").strip()
            source_name = str(item.get("source_name") or "").strip()
            if not source_name:
                source_name = urlparse(url).netloc or "unknown"
            score = item.get("score")
            relevance = float(score) if isinstance(score, (int, float)) else None
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_name=source_name,
                    relevance_score=relevance,
                )
            )
        return results
