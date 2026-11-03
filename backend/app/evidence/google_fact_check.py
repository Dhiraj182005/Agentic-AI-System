"""Google Fact Check Tools API client (claims:search).

Returns *published fact-checks* whose reviewed claim matches a query. A
publisher's rating is an external opinion about the claim *they* reviewed:
MAVES stores and shows it as evidence, never as its own verdict.

The API key is sent in the ``X-Goog-Api-Key`` header, never in the URL, so
it cannot leak through logged URLs or exception messages.
"""

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from app.evidence.retry import request_with_retry
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.evidence.base import (
    MAX_QUERY_LENGTH,
    EvidenceConfigurationError,
    EvidenceProviderAPIError,
    EvidenceProviderResponseError,
    EvidenceTimeoutError,
)

logger = logging.getLogger(__name__)

FACT_CHECK_SEARCH_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
SOURCE_TYPE = "google_fact_check"
MAX_PAGE_SIZE = 10
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


class FactCheckAuthError(EvidenceProviderAPIError):
    """The API key was rejected or lacks permission for the API."""


class FactCheckQuotaError(EvidenceProviderAPIError):
    """The API quota or rate limit was exceeded."""


class FactCheckResult(BaseModel):
    """One published fact-check (a claimReview) for a matching claim."""

    claim_text: str = ""
    claimant: str | None = None
    publisher_name: str = Field(min_length=1)
    publisher_site: str | None = None
    review_url: str = Field(min_length=1)
    review_title: str = ""
    textual_rating: str = ""
    review_date: datetime | None = None
    language_code: str | None = None


def normalize_query(text: str) -> str:
    """Collapse whitespace, drop wrapping quotes and cap length on a word
    boundary. Returns '' when nothing searchable remains."""
    query = re.sub(r"\s+", " ", text or "").strip().strip("\"'“”‘’").strip()
    if len(query) > MAX_QUERY_LENGTH:
        cut = query[:MAX_QUERY_LENGTH]
        query = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return query


def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_claims_response(body: object, limit: int) -> list[FactCheckResult]:
    """Flatten ``claims[].claimReview[]`` into results, skipping incomplete
    entries (no review URL) and duplicate review URLs."""
    if not isinstance(body, dict):
        raise EvidenceProviderResponseError("The fact-check service returned a malformed response")
    if "error" in body:
        raise EvidenceProviderResponseError("The fact-check service returned an error response")
    claims = body.get("claims")
    if claims is None:
        return []  # The API omits "claims" when nothing matches.
    if not isinstance(claims, list):
        raise EvidenceProviderResponseError("The fact-check service returned a malformed response")

    results: list[FactCheckResult] = []
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        reviews = claim.get("claimReview")
        if not isinstance(reviews, list):
            continue
        for review in reviews:
            if len(results) >= limit:
                return results
            if not isinstance(review, dict):
                continue
            url = _text(review.get("url"))
            if not url or urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc or url in seen:
                continue
            publisher = review.get("publisher") if isinstance(review.get("publisher"), dict) else {}
            site = _text(publisher.get("site")) or None
            name = _text(publisher.get("name")) or site or urlparse(url).netloc or "Unknown publisher"
            seen.add(url)
            results.append(
                FactCheckResult(
                    claim_text=_text(claim.get("text")),
                    claimant=_text(claim.get("claimant")) or None,
                    publisher_name=name,
                    publisher_site=site,
                    review_url=url,
                    review_title=_text(review.get("title")),
                    textual_rating=_text(review.get("textualRating")),
                    review_date=_parse_date(review.get("reviewDate")),
                    language_code=_text(review.get("languageCode")) or None,
                )
            )
    return results


class GoogleFactCheckClient:
    provider_name = SOURCE_TYPE

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
        language_code: str | None = None,
    ):
        settings = get_settings()
        if api_key is None:
            api_key = settings.GOOGLE_FACT_CHECK_API_KEY
        self.api_key = (api_key or "").strip()
        self.timeout = timeout if timeout is not None else settings.GOOGLE_FACT_CHECK_TIMEOUT_SECONDS
        language = (language_code if language_code is not None else settings.GOOGLE_FACT_CHECK_LANGUAGE).strip()
        self.language_code = language if _LANGUAGE_RE.match(language) else None
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, max_results: int = 5) -> list[FactCheckResult]:
        if not self.api_key:
            raise EvidenceConfigurationError("Google Fact Check is not configured (missing API key)")
        clean_query = normalize_query(query)
        if not clean_query:
            return []
        limit = max(1, min(int(max_results), MAX_PAGE_SIZE))
        params = {"query": clean_query, "pageSize": limit}
        if self.language_code:
            params["languageCode"] = self.language_code
        headers = {"X-Goog-Api-Key": self.api_key}

        try:
            response = await request_with_retry(lambda: self._get(params, headers))
        except httpx.TimeoutException as exc:
            logger.warning("Google Fact Check search timed out")
            raise EvidenceTimeoutError("The fact-check service timed out") from exc
        except httpx.HTTPError as exc:
            logger.warning("Google Fact Check search failed: %s", type(exc).__name__)
            raise EvidenceProviderAPIError("The fact-check service could not be reached") from exc

        status = response.status_code
        if status != 200:
            logger.warning("Google Fact Check search returned status %s", status)
            if status == 429 or (status == 403 and "RESOURCE_EXHAUSTED" in response.text):
                raise FactCheckQuotaError("The fact-check service quota or rate limit was exceeded")
            if status in (401, 403) or (status == 400 and "API_KEY" in response.text.upper()):
                raise FactCheckAuthError("The fact-check API key was rejected or lacks permission")
            if status >= 500:
                raise EvidenceProviderAPIError("The fact-check service is unavailable")
            raise EvidenceProviderAPIError("The fact-check service returned an error")

        try:
            body = response.json()
        except ValueError as exc:
            raise EvidenceProviderResponseError("The fact-check service returned a malformed response") from exc
        return parse_claims_response(body, limit)

    async def _get(self, params: dict, headers: dict) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(
                FACT_CHECK_SEARCH_URL, params=params, headers=headers, timeout=self.timeout
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(FACT_CHECK_SEARCH_URL, params=params, headers=headers)


def get_fact_check_client() -> GoogleFactCheckClient:
    return GoogleFactCheckClient()
