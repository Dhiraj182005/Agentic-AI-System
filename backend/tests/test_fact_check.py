"""Google Fact Check Tools integration: client (HTTP mocked with
httpx.MockTransport - no real key, no network), persistence, pipeline order,
Tavily fallback, duplicate prevention and verdict regeneration. All LLM and
search providers are mocked."""

import asyncio
import contextlib
import json
import unittest.mock
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.evidence.base import (
    EvidenceConfigurationError,
    EvidenceProviderAPIError,
    EvidenceProviderResponseError,
    EvidenceTimeoutError,
)
from app.evidence.google_fact_check import (
    FACT_CHECK_SEARCH_URL,
    FactCheckAuthError,
    FactCheckQuotaError,
    FactCheckResult,
    GoogleFactCheckClient,
    normalize_query,
)
from app.models.claim import Claim
from app.models.evidence import Evidence
from app.models.verdict import DebateVerdict
from tests import test_report as base
from tests.test_analysis_pipeline import (
    ExtractionLLM,
    Search,
    VerdictLLM,
    VerifyLLM,
    completed_debate,
    counts,
    providers,
    verdict_url,
)

FAKE_KEY = "test-key-not-real-123"

SAMPLE = {
    "claims": [
        {
            "text": "Teen social media use rose 10 percent.",
            "claimant": "A viral post",
            "claimDate": "2025-01-02T00:00:00Z",
            "claimReview": [
                {
                    "publisher": {"name": "PolitiFact", "site": "politifact.com"},
                    "url": "https://www.politifact.com/factchecks/teen-use/",
                    "title": "Did teen social media use rise 10%?",
                    "reviewDate": "2025-02-03T00:00:00Z",
                    "textualRating": "Mostly True",
                    "languageCode": "en",
                },
                {   # incomplete: no URL -> cannot be cited, skipped
                    "publisher": {"name": "NoLink"},
                    "textualRating": "False",
                },
            ],
        },
        {
            "text": "Teen social media use doubled.",
            "claimReview": [
                {   # incomplete: no publisher name, no rating, bad date
                    "publisher": {"site": "factcheck.org"},
                    "url": "https://www.factcheck.org/teen-doubled/",
                    "reviewDate": "not a date",
                },
                {   # duplicate URL -> skipped
                    "publisher": {"name": "PolitiFact"},
                    "url": "https://www.politifact.com/factchecks/teen-use/",
                    "textualRating": "Mostly True",
                },
            ],
        },
    ]
}


def mock_client(handler) -> tuple[GoogleFactCheckClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request):
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return GoogleFactCheckClient(api_key=FAKE_KEY, client=http, language_code="en"), seen


async def expect(exc_type, coro):
    try:
        await coro
    except exc_type as exc:
        assert FAKE_KEY not in str(exc), "API key must never appear in errors"
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")


# --------------------------------------------------------------------- client


async def test_client_parses_multiple_results():
    client, seen = mock_client(lambda r: httpx.Response(200, json=SAMPLE))
    results = await client.search('  "Teen   social media use rose 10 percent."  ', max_results=5)
    assert [r.review_url for r in results] == [
        "https://www.politifact.com/factchecks/teen-use/",
        "https://www.factcheck.org/teen-doubled/",
    ]
    first, second = results
    assert first.publisher_name == "PolitiFact" and first.publisher_site == "politifact.com"
    assert first.textual_rating == "Mostly True" and first.claimant == "A viral post"
    assert first.claim_text == "Teen social media use rose 10 percent."
    assert first.review_date == datetime(2025, 2, 3, tzinfo=timezone.utc)
    # Incomplete fields are normalised instead of failing.
    assert second.publisher_name == "factcheck.org" and second.textual_rating == ""
    assert second.review_date is None and second.review_title == ""

    request = seen[0]
    assert str(request.url).startswith(FACT_CHECK_SEARCH_URL)
    assert request.url.params["query"] == "Teen social media use rose 10 percent."
    assert request.url.params["languageCode"] == "en" and request.url.params["pageSize"] == "5"
    assert request.headers["X-Goog-Api-Key"] == FAKE_KEY
    assert FAKE_KEY not in str(request.url), "key is sent as a header, never in the URL"
    print("client: multiple results, incomplete fields, dedupe, key in header only: PASSED")


async def test_client_empty_and_malformed():
    client, _ = mock_client(lambda r: httpx.Response(200, json={}))
    assert await client.search("Nothing matches this") == []
    client, _ = mock_client(lambda r: httpx.Response(200, json={"claims": []}))
    assert await client.search("Nothing matches this") == []
    client, seen = mock_client(lambda r: httpx.Response(200, json={}))
    assert await client.search('  ""  ') == [] and seen == [], "empty query never calls the API"

    client, _ = mock_client(lambda r: httpx.Response(200, json=[1, 2]))
    await expect(EvidenceProviderResponseError, client.search("x claim"))
    client, _ = mock_client(lambda r: httpx.Response(200, json={"claims": "oops"}))
    await expect(EvidenceProviderResponseError, client.search("x claim"))
    client, _ = mock_client(lambda r: httpx.Response(200, text="<html>not json</html>"))
    await expect(EvidenceProviderResponseError, client.search("x claim"))
    print("client: empty and malformed responses: PASSED")


async def test_client_errors():
    called = []
    unconfigured = GoogleFactCheckClient(api_key="", client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: called.append(r) or httpx.Response(200, json={}))))
    assert not unconfigured.configured
    await expect(EvidenceConfigurationError, unconfigured.search("claim"))
    assert called == [], "missing key never calls the API"

    invalid = {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT",
                         "details": [{"reason": "API_KEY_INVALID"}]}}
    for response, exc_type in [
        (httpx.Response(400, json=invalid), FactCheckAuthError),
        (httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}}), FactCheckAuthError),
        (httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}), FactCheckQuotaError),
        (httpx.Response(503, text="unavailable"), EvidenceProviderAPIError),
        (httpx.Response(400, json={"error": {"message": "bad query"}}), EvidenceProviderAPIError),
    ]:
        client, _ = mock_client(lambda r, resp=response: resp)
        exc = await expect(exc_type, client.search("claim"))
        assert type(exc) is exc_type or exc_type is EvidenceProviderAPIError

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    def network(request):
        raise httpx.ConnectError("connection refused", request=request)

    client, _ = mock_client(timeout)
    await expect(EvidenceTimeoutError, client.search("claim"))
    client, _ = mock_client(network)
    await expect(EvidenceProviderAPIError, client.search("claim"))

    assert normalize_query("  a\n\tb  ") == "a b"
    long = normalize_query("word " * 200)
    assert len(long) <= 300 and not long.endswith(" ")
    print("client: missing/invalid key, permission, quota, 5xx, timeout, network: PASSED")


# ------------------------------------------------------------------- pipeline


class FakeFactCheck:
    """Stands in for GoogleFactCheckClient in the pipeline."""

    def __init__(self, configured=True, fail: Exception | None = None, empty=False):
        self.configured = configured
        self.fail = fail
        self.empty = empty
        self.queries: list[str] = []

    async def search(self, query, max_results=5):
        self.queries.append(query)
        if self.fail:
            raise self.fail
        if self.empty:
            return []
        slug = "".join(ch for ch in query.lower() if ch.isalnum())[:40]
        return [
            FactCheckResult(
                claim_text=query, publisher_name="PolitiFact", publisher_site="politifact.com",
                review_url=f"https://www.politifact.com/factchecks/{slug}/",
                review_title=f"Fact-check: {query[:40]}", textual_rating="Mostly True",
                review_date=datetime(2025, 2, 3, tzinfo=timezone.utc),
            ),
            FactCheckResult(
                claim_text="Teen screen time stayed flat.", publisher_name="Full Fact",
                review_url=f"https://fullfact.org/{slug}/", textual_rating="",
            ),
        ]


class RecordingVerifyLLM(VerifyLLM):
    def __init__(self):
        super().__init__()
        self.prompts = []

    async def generate(self, messages, temperature=None, max_tokens=None, **_):
        self.prompts.append(messages[1].content)
        return await super().generate(messages, temperature, max_tokens)


@contextlib.contextmanager
def fact_checks(fake):
    with unittest.mock.patch("app.services.claim_service.get_fact_check_client", return_value=fake):
        yield


async def fact_check_rows(debate_id):
    async with base._test_session() as session:
        return (await session.execute(
            select(Evidence).join(Claim).where(Claim.debate_id == debate_id)
            .where(Evidence.source_type == "google_fact_check")
        )).scalars().all()


async def test_pipeline_stores_and_associates_fact_checks(client):
    token = await base.register_and_login(client, base.unique_email("fc-ok"))
    # 12 messages -> two extraction batches that repeat claim texts.
    debate_id = await completed_debate(client, token, agents=3, rounds=4)
    fake, search, verify = FakeFactCheck(), Search(), RecordingVerifyLLM()
    with providers(search=search, verify=verify), fact_checks(fake):
        resp = await client.post(verdict_url(debate_id), headers=base.auth(token))
    assert resp.status_code == 200, resp.text

    claims, verifications, _, status = await counts(debate_id)
    selected = [c for c in claims if c.fact_check_searched_at is not None]
    assert status["state"] == "completed" and status["fact_check"]["status"] == "ok", status
    assert status["fact_check"]["matched"] == len(selected) == status["claims_selected"]
    assert all(c.claim_type == "factual" and c.fact_check_status == "matched" for c in selected)
    # Duplicate searches avoided: one request per distinct claim text.
    assert len(fake.queries) == len({c.text for c in selected}) < len(selected)

    rows = await fact_check_rows(debate_id)
    assert len(rows) == 2 * len(selected), "each claim keeps its own associated fact-checks"
    by_claim = {c.id: c for c in selected}
    for row in rows:
        claim = by_claim[row.claim_id]
        assert row.publisher in ("PolitiFact", "Full Fact") and row.retrieved_at is not None
        if row.publisher == "PolitiFact":
            assert row.external_rating == "Mostly True" and row.claim_reviewed == claim.text
            assert row.relevance_score == 1.0 and row.review_date is not None
        else:
            assert row.external_rating is None and row.relevance_score < 0.5
    # Tavily still runs: fact-checks complement web search.
    assert search.calls == len({c.canonical_claim_id or c.id for c in selected})
    assert all(len(v.evidence_ids) == 4 for v in verifications)

    prompt = verify.prompts[0]
    assert "published fact-check | publisher: PolitiFact" in prompt
    assert "publisher's external rating: Mostly True" in prompt
    assert "web search result" in prompt

    claim_id = selected[0].id
    body = (await client.get(f"/api/v1/claims/{claim_id}/evidence", headers=base.auth(token))).json()
    assert body["fact_check_status"] == "matched"
    types = [item["source_type"] for item in body["evidence"]]
    assert types.count("google_fact_check") == 2 and types.count("web") == 2
    fc = next(i for i in body["evidence"] if i["publisher"] == "PolitiFact")
    assert fc["external_rating"] == "Mostly True" and fc["url"].startswith("https://www.politifact.com/")
    listed = (await client.get(f"/api/v1/debates/{debate_id}/claims", headers=base.auth(token))).json()
    assert {c["fact_check_status"] for c in listed["claims"]} >= {"matched", None}
    print("pipeline: fact-checks stored, associated, relevance-scored, used in verification: PASSED")

    # Re-running never searches again or stores duplicates.
    with providers(search=search), fact_checks(fake):
        assert (await client.post(verdict_url(debate_id), headers=base.auth(token))).status_code == 200
        resp = await client.post(f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=base.auth(token))
    assert resp.status_code == 200 and len(resp.json()["evidence"]) == 4
    assert len(fake.queries) == len({c.text for c in selected})
    assert len(await fact_check_rows(debate_id)) == len(rows)
    print("duplicate prevention across runs and manual retrieval: PASSED")


async def test_missing_key_falls_back_to_tavily(client):
    token = await base.register_and_login(client, base.unique_email("fc-nokey"))
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    fake, search, verdict = FakeFactCheck(configured=False), Search(), VerdictLLM()
    with providers(search=search, verdict=verdict), fact_checks(fake):
        resp = await client.post(verdict_url(debate_id), headers=base.auth(token))
    assert resp.status_code == 200, resp.text
    claims, verifications, evidence, status = await counts(debate_id)
    assert fake.queries == [] and status["fact_check"]["status"] == "unavailable"
    assert status["state"] == "partial" and status["failures"] == [], "optional provider unavailable is transparent partial coverage"
    assert search.calls == status["claims_selected"] == len(verifications) and evidence > 0
    assert verdict.calls == 1
    selected = [c for c in claims if c.fact_check_status is not None]
    assert all(c.fact_check_status == "unavailable" and c.fact_check_searched_at is None for c in selected)
    body = (await client.get(f"/api/v1/claims/{selected[0].id}/evidence", headers=base.auth(token))).json()
    assert body["fact_check_status"] == "unavailable"
    assert all(item["source_type"] == "web" for item in body["evidence"])
    print("missing key: debate analysis continues with Tavily, warning recorded: PASSED")


async def test_empty_results_are_neutral(client):
    token = await base.register_and_login(client, base.unique_email("fc-empty"))
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    fake = FakeFactCheck(empty=True)
    with providers(), fact_checks(fake):
        assert (await client.post(verdict_url(debate_id), headers=base.auth(token))).status_code == 200
    claims, verifications, _, status = await counts(debate_id)
    assert status["fact_check"]["no_match"] == status["claims_selected"] and status["fact_check"]["matched"] == 0
    selected = [c for c in claims if c.fact_check_status]
    assert all(c.fact_check_status == "no_match" and c.fact_check_searched_at for c in selected)
    # No published fact-check never means "false": verification follows the web evidence.
    assert all(v.verdict == "supported" for v in verifications)
    assert await fact_check_rows(debate_id) == []
    print("no matching published fact-check: neutral status, never 'false': PASSED")


async def test_failure_then_retry_regenerates_verdict(client):
    token = await base.register_and_login(client, base.unique_email("fc-retry"))
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    failing, verdict = FakeFactCheck(fail=FactCheckQuotaError("quota")), VerdictLLM()
    with providers(verdict=verdict), fact_checks(failing):
        assert (await client.post(verdict_url(debate_id), headers=base.auth(token))).status_code == 200
    claims, verifications, _, status = await counts(debate_id)
    assert status["fact_check"]["status"] == "failed" and status["state"] == "partial"
    assert len(verifications) == status["claims_selected"] > 0, "Tavily + verification still ran"
    assert verdict.calls == 1
    assert all(c.fact_check_status == "failed" and c.fact_check_searched_at is None
               for c in claims if c.fact_check_status)
    async with base._test_session() as session:
        first = (await session.execute(select(DebateVerdict).where(DebateVerdict.debate_id == debate_id))).scalar_one()
        first_sources = first.evidence_snapshot["evidence_sources"]

    # The service recovers: the next run retries, adds fact-checks, re-verifies
    # those claims and regenerates the verdict on the updated evidence.
    working, verify = FakeFactCheck(), RecordingVerifyLLM()
    with providers(verify=verify, verdict=verdict), fact_checks(working):
        assert (await client.post(verdict_url(debate_id), headers=base.auth(token))).status_code == 200
    _, _, _, status = await counts(debate_id)
    assert status["fact_check"]["matched"] == status["claims_selected"]
    assert status["verified"] == status["claims_selected"] and status["verdict"] == "generated"
    assert verdict.calls == 2 and "published fact-checks (external ratings)" in verdict.prompts[-1]
    assert all("published fact-check" in p for p in verify.prompts)
    body = (await client.get(f"/api/v1/debates/{debate_id}/verdict", headers=base.auth(token))).json()
    assert body["stale"] is False and body["evidence_snapshot"]["evidence_sources"] > first_sources
    print("fact-check failure is retried; new evidence regenerates the verdict: PASSED")


async def test_api_never_exposes_key(client):
    token = await base.register_and_login(client, base.unique_email("fc-key"))
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    fake = FakeFactCheck(fail=FactCheckAuthError("The fact-check API key was rejected or lacks permission"))
    with providers(), fact_checks(fake):
        assert (await client.post(verdict_url(debate_id), headers=base.auth(token))).status_code == 200
    analysis = (await client.get(f"/api/v1/debates/{debate_id}/analysis", headers=base.auth(token))).json()
    assert analysis["fact_check"]["status"] == "failed"
    assert FAKE_KEY not in json.dumps(analysis)
    print("invalid key: recorded as failed, no secret in API responses: PASSED")


async def main():
    await test_client_parses_multiple_results()
    await test_client_empty_and_malformed()
    await test_client_errors()
    app = await base.setup()
    async with base.client_for(app) as client:
        await test_pipeline_stores_and_associates_fact_checks(client)
        await test_missing_key_falls_back_to_tavily(client)
        await test_empty_results_are_neutral(client)
        await test_failure_then_retry_regenerates_verdict(client)
        await test_api_never_exposes_key(client)
    await base.teardown()
    print("\nAll Google Fact Check tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
