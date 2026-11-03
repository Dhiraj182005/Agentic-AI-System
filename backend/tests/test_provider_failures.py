"""LLM provider failure handling and failed-debate integrity.

Part 1 drives GroqProvider against a fake SDK client (no network, no API
quota): error classification, bounded retries with backoff/Retry-After, no
retries for permanent errors, and the empty-answer budget escalation that
caused the real failure (openai/gpt-oss-20b spent all 1024 output tokens on
reasoning: finish_reason=length, empty content).

Part 2 runs real debates through the API with a scripted fake provider:
failure in a later round, preserved messages, safe stored failure reason,
resume without duplicate turns, status transitions, WebSocket events, and
no verdict for a failed debate.
"""

import asyncio
import os
import contextlib
import logging
import unittest.mock
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)
from sqlalchemy import select

from app.llm.base import (
    LLMAuthenticationError,
    LLMProviderAPIError,
    LLMBadRequestError,
    LLMContextLengthError,
    LLMEmptyResponseError,
    LLMModelNotFoundError,
    LLMRateLimitError,
    LLMResponse,
    LLMMessage,
    LLMServerError,
    LLMTimeoutError,
)
from app.llm.providers.groq_provider import GroqProvider
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.websocket import events as ws_events
from app.websocket.manager import connection_manager
from tests import test_report as base

SECRET_KEY = "gsk_test_secret_do_not_log_123"
REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
MESSAGES = [LLMMessage(role="user", content="hi")]


# ---------------------------------------------------------------------------
# Part 1: provider
# ---------------------------------------------------------------------------


def status_error(cls, status: int, *, headers=None, code: str | None = None):
    body = {"error": {"message": f"details mention {SECRET_KEY}", "code": code}}
    response = httpx.Response(status, headers=headers or {}, request=REQUEST, json=body)
    return cls(f"Error code: {status} - {SECRET_KEY}", response=response, body=body)


def completion(content, finish_reason="stop", reasoning_tokens=None, completion_tokens=None):
    usage = SimpleNamespace(
        completion_tokens=completion_tokens,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
    )
    choice = SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def provider_with(outcomes, **kwargs):
    """GroqProvider whose SDK client returns/raises `outcomes` in order."""
    # Hermetic: no fallback chain unless a test asks for one (the real
    # GROQ_FALLBACK_MODELS in .env must not change these tests).
    options = dict(max_retries=3, retry_base_delay=1.0, retry_max_delay=20.0,
                   max_output_tokens_ceiling=4096, fallback_models=[])
    options.update(kwargs)
    provider = GroqProvider(api_key=SECRET_KEY, model="openai/gpt-oss-20b", timeout=5, **options)
    create = AsyncMock(side_effect=outcomes)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    provider._sleep = fake_sleep
    return provider, create, sleeps


async def expect(exc_type, coro):
    try:
        await coro
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")


async def test_success():
    provider, create, sleeps = provider_with([completion("A reasoned answer.")])
    result = await provider.generate(MESSAGES, max_tokens=1024)
    assert result.content == "A reasoned answer." and result.model == "openai/gpt-oss-20b"
    assert create.await_count == 1 and sleeps == []
    print("1. successful response: PASSED")


async def test_invalid_api_key():
    provider, create, sleeps = provider_with([status_error(AuthenticationError, 401)] * 5)
    exc = await expect(LLMAuthenticationError, provider.generate(MESSAGES))
    assert create.await_count == 1 and sleeps == [], "permanent errors are not retried"
    assert "GROQ_API_KEY" in exc.user_message and SECRET_KEY not in exc.user_message
    print("2. invalid API key fails fast: PASSED")


async def test_invalid_model():
    provider, create, _ = provider_with([status_error(NotFoundError, 404, code="model_not_found")])
    exc = await expect(LLMModelNotFoundError, provider.generate(MESSAGES))
    assert create.await_count == 1 and "GROQ_MODEL" in exc.user_message
    provider, create, _ = provider_with([status_error(BadRequestError, 400, code="model_decommissioned")])
    await expect(LLMModelNotFoundError, provider.generate(MESSAGES))
    assert create.await_count == 1
    print("3. invalid model identifier fails fast: PASSED")


async def test_rate_limit():
    # Retry-After is honored, then the request succeeds.
    provider, create, sleeps = provider_with([
        status_error(RateLimitError, 429, headers={"retry-after": "2"}),
        completion("ok"),
    ])
    assert (await provider.generate(MESSAGES)).content == "ok"
    assert create.await_count == 2 and 2.0 <= sleeps[0] <= 2.25, sleeps
    # The live case: Groq on-demand TPM limit asked for 21 s. With the 60 s
    # default cap that is waited out instead of failing the turn.
    provider, create, sleeps = provider_with(
        [status_error(RateLimitError, 429, headers={"retry-after": "21"}), completion("ok")],
        retry_max_delay=60.0,
    )
    assert (await provider.generate(MESSAGES)).content == "ok"
    assert create.await_count == 2 and 21.0 <= sleeps[0] <= 21.25, sleeps
    # Groq 413 with code rate_limit_exceeded (request does not fit the
    # remaining per-minute window) is transient, like a 429.
    from groq import APIStatusError
    provider, create, sleeps = provider_with(
        [status_error(APIStatusError, 413, code="rate_limit_exceeded"), completion("ok")]
    )
    assert (await provider.generate(MESSAGES)).content == "ok" and create.await_count == 2
    provider, create, _ = provider_with([status_error(APIStatusError, 413)] * 3)
    await expect(LLMProviderAPIError, provider.generate(MESSAGES))
    assert create.await_count == 1, "other 413s stay permanent"
    # A wait longer than the limit (e.g. exhausted daily quota) fails fast.
    provider, create, sleeps = provider_with([status_error(RateLimitError, 429, headers={"retry-after": "3600"})] * 5)
    exc = await expect(LLMRateLimitError, provider.generate(MESSAGES))
    assert create.await_count == 1 and sleeps == [] and exc.retry_after == 3600
    # Persistent rate limiting stops after max_retries.
    provider, create, sleeps = provider_with([status_error(RateLimitError, 429)] * 10)
    await expect(LLMRateLimitError, provider.generate(MESSAGES))
    assert create.await_count == 4 and len(sleeps) == 3
    print("4. rate limit: Retry-After honored, bounded, fails fast on long waits: PASSED")


async def test_timeout():
    provider, create, sleeps = provider_with([APITimeoutError(request=REQUEST)] * 10)
    exc = await expect(LLMTimeoutError, provider.generate(MESSAGES))
    assert create.await_count == 4, "bounded: 1 try + 3 retries"
    # Exponential backoff with jitter: base*2^n scaled by [0.5, 1.0].
    for attempt, delay in enumerate(sleeps):
        assert 0.5 * 2 ** attempt <= delay <= 2 ** attempt, sleeps
    assert "in time" in exc.user_message
    provider, create, _ = provider_with([APIConnectionError(request=REQUEST), completion("ok")])
    assert (await provider.generate(MESSAGES)).content == "ok" and create.await_count == 2
    print("5. timeouts/connection errors retried with bounded backoff: PASSED")


async def test_server_error_then_success():
    provider, create, sleeps = provider_with([
        status_error(InternalServerError, 503),
        status_error(InternalServerError, 500),
        completion("recovered"),
    ])
    assert (await provider.generate(MESSAGES)).content == "recovered"
    assert create.await_count == 3 and len(sleeps) == 2
    provider, create, _ = provider_with([status_error(InternalServerError, 500)] * 9)
    await expect(LLMServerError, provider.generate(MESSAGES))
    assert create.await_count == 4
    print("6. temporary server error then successful retry: PASSED")


async def test_permanent_errors_not_retried():
    provider, create, sleeps = provider_with([status_error(BadRequestError, 400)] * 5)
    await expect(LLMBadRequestError, provider.generate(MESSAGES))
    assert create.await_count == 1 and sleeps == []
    provider, create, _ = provider_with([status_error(BadRequestError, 400, code="context_length_exceeded")])
    exc = await expect(LLMContextLengthError, provider.generate(MESSAGES))
    assert create.await_count == 1 and "too long" in exc.user_message
    print("7. permanent failures are not retried: PASSED")


async def test_reasoning_budget_escalation():
    # The production failure: all output tokens spent on reasoning.
    exhausted = completion(None, finish_reason="length", reasoning_tokens=1022, completion_tokens=1024)
    provider, create, sleeps = provider_with([exhausted, completion("Rebuttal text.")])
    result = await provider.generate(MESSAGES, max_tokens=1024)
    assert result.content == "Rebuttal text."
    assert [c.kwargs["max_tokens"] for c in create.await_args_list] == [1024, 2048]
    assert sleeps == []
    # Still empty at the ceiling -> a clear, specific error (bounded).
    provider, create, _ = provider_with([exhausted] * 9)
    exc = await expect(LLMEmptyResponseError, provider.generate(MESSAGES, max_tokens=1024))
    assert [c.kwargs["max_tokens"] for c in create.await_args_list] == [1024, 2048, 4096]
    assert "empty answer" in exc.user_message
    print("8. empty reasoning-model answer retried with larger budget: PASSED")


def groq_limit_error(kind_text: str, limit: int, used: int, requested: int, retry_after: str):
    """Groq's real 429 body shape (organisation id included, as Groq sends it)."""
    message = (
        "Rate limit reached for model `openai/gpt-oss-20b` in organization "
        f"`org_01secretorgid` service tier `on_demand` on {kind_text}: Limit {limit}, "
        f"Used {used}, Requested {requested}. Please try again in 11m52s."
    )
    body = {"error": {"message": message, "type": "tokens", "code": "rate_limit_exceeded"}}
    response = httpx.Response(
        429,
        headers={"retry-after": retry_after, "x-ratelimit-remaining-tokens": "7947",
                 "x-ratelimit-remaining-requests": "998"},
        request=REQUEST, json=body,
    )
    return RateLimitError(f"Error code: 429 - {message}", response=response, body=body)


async def test_rate_limit_kinds():
    """The observed failure: daily token quota (TPD) exhausted while the
    per-minute limits were fine; the Playground's small request still fit."""
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    log = logging.getLogger("app.llm.providers.groq_provider")
    log.addHandler(handler)
    try:
        # Daily token quota: never retried, even if the wait looks short.
        tpd = groq_limit_error("tokens per day (TPD)", 200000, 199523, 2126, "30")
        provider, create, sleeps = provider_with([tpd] * 5)
        exc = await expect(LLMRateLimitError, provider.generate(MESSAGES, max_tokens=2048))
        assert create.await_count == 1 and sleeps == []
        assert (exc.limit_kind, exc.limit, exc.used, exc.requested) == ("TPD", 200000, 199523, 2126)
        assert "daily token quota is used up (199,523 of 200,000 tokens used)" in exc.user_message
        assert "org_" not in exc.user_message

        # Per-minute token limit with a short wait: retried, then succeeds.
        tpm = groq_limit_error("tokens per minute (TPM)", 8000, 7900, 2126, "3")
        provider, create, sleeps = provider_with([tpm, completion("ok")])
        assert (await provider.generate(MESSAGES)).content == "ok" and create.await_count == 2

        rpd = groq_limit_error("requests per day (RPD)", 1000, 1000, 1, "120")
        provider, create, _ = provider_with([rpd] * 3)
        exc = await expect(LLMRateLimitError, provider.generate(MESSAGES))
        assert exc.limit_kind == "RPD" and create.await_count == 1
        assert "daily request quota" in exc.user_message

        rpm = groq_limit_error("requests per minute (RPM)", 30, 30, 1, "100")
        provider, create, _ = provider_with([rpm] * 3)
        exc = await expect(LLMRateLimitError, provider.generate(MESSAGES))
        assert exc.limit_kind == "RPM" and "per-minute request limit" in exc.user_message
    finally:
        log.removeHandler(handler)

    diagnostic = next(r for r in records if "limit=TPD" in r)
    for part in ("status=429", "code=rate_limit_exceeded", "used=199523", "of=200000",
                 "requested=2126", "retry_after=30.0", "remaining-tokens=7947",
                 "model=openai/gpt-oss-20b"):
        assert part in diagnostic, (part, diagnostic)
    assert not any("org_01secretorgid" in r for r in records), "organisation id never logged"
    print("rate limits classified (TPD/TPM/RPD/RPM), daily quota not retried, sanitized: PASSED")


async def test_daily_quota_model_fallback():
    """The observed failure: gpt-oss-120b's daily quota ran out, so claim
    extraction and the verdict failed. With GROQ_FALLBACK_MODELS the next
    model (own quota) answers; exhausted models are skipped afterwards."""
    from app.llm.providers.groq_provider import reset_exhausted_models

    reset_exhausted_models()
    try:
        tpd = groq_limit_error("tokens per day (TPD)", 200000, 199904, 4975, "2108")
        provider, create, sleeps = provider_with(
            [tpd, completion("from fallback"), completion("again fallback")],
            fallback_models=["qwen/qwen3.8-27b"],
        )
        first = await provider.generate(MESSAGES, max_tokens=2048)
        assert first.content == "from fallback" and first.model == "qwen/qwen3.8-27b"
        assert [c.kwargs["model"] for c in create.await_args_list] == ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
        assert sleeps == [], "a daily quota is never waited out"
        # The exhausted primary is skipped (no wasted refused call).
        second = await provider.generate(MESSAGES)
        assert second.model == "qwen/qwen3.8-27b" and create.await_count == 3

        # A per-minute limit does NOT switch models: it is retried on the same one.
        reset_exhausted_models()
        tpm = groq_limit_error("tokens per minute (TPM)", 8000, 7900, 2000, "2")
        provider, create, _ = provider_with([tpm, completion("same model")], fallback_models=["qwen/qwen3.8-27b"])
        result = await provider.generate(MESSAGES)
        assert result.model == "openai/gpt-oss-20b"
        assert [c.kwargs["model"] for c in create.await_args_list] == ["openai/gpt-oss-20b"] * 2

        # Every model exhausted: a clear error, never a fabricated answer.
        reset_exhausted_models()
        provider, create, _ = provider_with([tpd, tpd], fallback_models=["qwen/qwen3.8-27b"])
        exc = await expect(LLMRateLimitError, provider.generate(MESSAGES))
        assert "every configured language model" in exc.user_message and create.await_count == 2

        # Non-quota errors never fall back (e.g. invalid key).
        reset_exhausted_models()
        provider, create, _ = provider_with([status_error(AuthenticationError, 401)], fallback_models=["qwen/qwen3.8-27b"])
        await expect(LLMAuthenticationError, provider.generate(MESSAGES))
        assert create.await_count == 1
    finally:
        reset_exhausted_models()
    print("daily-quota fallback to the next model; TPM retried in place; no fabrication: PASSED")


async def test_services_report_specific_provider_reason():
    """Extraction / verdict used to say 'provider did not respond' for a quota."""
    from app.services.claim_extraction import ClaimExtractionError, ClaimExtractionService, MessageContext
    from app.services.verdict_service import VerdictLLMError, VerdictService

    class QuotaLLM:
        async def generate(self, *args, **kwargs):
            raise LLMRateLimitError("x", retry_after=2108, limit_kind="TPD", limit=200000, used=199904, requested=4975)

    import uuid as _uuid
    try:
        await ClaimExtractionService(provider=QuotaLLM()).extract(
            [MessageContext(message_id=_uuid.uuid4(), agent_id=_uuid.uuid4(), agent_name="A", content="text")]
        )
        raise AssertionError("expected ClaimExtractionError")
    except ClaimExtractionError as exc:
        assert "daily token quota is used up" in str(exc) and "did not respond" not in str(exc)
    try:
        await VerdictService(provider=QuotaLLM())._generate("prompt")
        raise AssertionError("expected VerdictLLMError")
    except VerdictLLMError as exc:
        assert "daily token quota is used up" in str(exc) and "did not respond" not in str(exc)
    print("services report the specific provider reason (quota), not 'did not respond': PASSED")


async def test_playground_and_debate_share_configuration(client):
    """Both paths resolve the same provider config; only max_tokens differs."""
    from app.agents.factory import get_agent_by_role
    from app.core.config import get_settings
    from app.orchestration.debate_engine import DebateEngine

    os.environ["GROQ_API_KEY"] = "audit-test-key"
    get_settings.cache_clear()
    settings = get_settings()
    playground = get_agent_by_role("economist").llm_provider
    debate_agent = DebateEngine(None)._runtime_agent(
        type("A", (), {"role": "doctor", "source": "builtin", "definition": None})()
    ).llm_provider
    for provider in (playground, debate_agent):
        assert type(provider).__name__ == "GroqProvider"
        assert provider.model_name == settings.GROQ_MODEL
        assert provider.timeout == settings.LLM_TIMEOUT_SECONDS
        assert provider.max_retries == settings.LLM_MAX_RETRIES
        assert bool(provider.api_key) == bool(settings.GROQ_API_KEY)

    seen: list[dict] = []

    class Recorder:
        async def generate(self, messages, temperature=None, max_tokens=None):
            seen.append({"max_tokens": max_tokens, "chars": sum(len(m.content) for m in messages)})
            return LLMResponse(content="ok", provider="groq", model=settings.GROQ_MODEL)

    token = await base.register_and_login(client, base.unique_email("pf-parity"))
    with use_provider(Recorder()):
        # The Agent Playground endpoint.
        resp = await client.post("/api/v1/agents/test", json={"agent": "economist", "message": "Hi"},
                                 headers=base.auth(token))
        assert resp.status_code == 200, resp.text
        debate_id = await new_debate(client, token, rounds=1)
        assert (await client.post(f"/api/v1/debates/{debate_id}/start",
                                  headers=base.auth(token))).status_code == 200
    assert seen[0]["max_tokens"] is None, "Playground sends no max_tokens"
    assert all(s["max_tokens"] == settings.DEBATE_MAX_RESPONSE_TOKENS for s in seen[1:])
    assert len(seen) == 3, "one Playground call + one call per debate turn, nothing extra"
    print("Playground and debate use the same provider config; only max_tokens differs: PASSED")


async def test_logs_never_contain_secrets():
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    log = logging.getLogger("app.llm.providers.groq_provider")
    log.addHandler(handler)
    try:
        provider, _, _ = provider_with([status_error(AuthenticationError, 401)])
        await expect(LLMAuthenticationError, provider.generate(MESSAGES))
        provider, _, _ = provider_with([status_error(RateLimitError, 429)] * 9)
        await expect(LLMRateLimitError, provider.generate(MESSAGES))
    finally:
        log.removeHandler(handler)
    assert records, "failures are logged"
    assert not any(SECRET_KEY in line for line in records), "logs leaked the key"
    print("provider logs never include credentials or payloads: PASSED")


# ---------------------------------------------------------------------------
# Part 2: debates
# ---------------------------------------------------------------------------


class ScriptedProvider:
    """Returns a numbered answer per call, raising where the script says."""

    def __init__(self, failures: dict[int, Exception] | None = None, on_call=None):
        self.failures = failures or {}
        self.calls = 0
        self.on_call = on_call

    async def generate(self, messages, temperature=None, max_tokens=None):
        index = self.calls
        self.calls += 1
        if self.on_call is not None:
            await self.on_call(index)
        if index in self.failures:
            raise self.failures[index]
        return LLMResponse(content=f"Answer number {index}.", provider="fake", model="fake")


@contextlib.contextmanager
def use_provider(provider):
    with unittest.mock.patch("app.agents.base_agent.get_llm_provider", return_value=provider):
        yield provider


@contextlib.contextmanager
def capture_events():
    events: list[dict] = []

    async def record(debate_id, event):
        events.append(event)
        return 0

    with unittest.mock.patch.object(connection_manager, "broadcast", side_effect=record):
        yield events


async def new_debate(client, token, rounds=3) -> str:
    resp = await client.post(
        "/api/v1/debates",
        json=base.base_payload(total_rounds=rounds, topic="Should cities fund tidal power?"),
        headers=base.auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def stored_state(debate_id):
    async with base._test_session() as session:
        debate = await session.get(Debate, debate_id)
        rounds = (
            await session.execute(
                select(DebateRound).where(DebateRound.debate_id == debate_id).order_by(DebateRound.round_number)
            )
        ).scalars().all()
        messages = (
            await session.execute(
                select(DebateMessage, DebateRound.round_number)
                .join(DebateRound, DebateRound.id == DebateMessage.round_id)
                .where(DebateMessage.debate_id == debate_id)
                .order_by(DebateRound.round_number, DebateMessage.turn_number)
            )
        ).all()
        return debate, [(r.round_number, r.status) for r in rounds], [
            (rn, m.turn_number, m.content, m.id) for m, rn in messages
        ]


async def test_later_round_failure_preserves_messages(client):
    token = await base.register_and_login(client, base.unique_email("pf-later"))
    debate_id = await new_debate(client, token)
    statuses_during_run = []

    async def peek(index):
        async with base._test_session() as session:
            statuses_during_run.append((await session.get(Debate, debate_id)).status)

    # 2 agents x 3 rounds; call 3 = round 2, turn 2 (lawyer).
    provider = ScriptedProvider({3: LLMEmptyResponseError("empty")}, on_call=peek)
    with use_provider(provider), capture_events() as events:
        resp = await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail.startswith("Round 2, turn 2 (Lawyer): "), detail
    assert "empty answer" in detail and "did not respond" not in detail

    debate, rounds, messages = await stored_state(debate_id)
    assert set(statuses_during_run) == {"running"}, "in-progress status while generating"
    assert debate.status == "failed" and debate.failure_reason == detail
    assert rounds == [(1, "completed"), (2, "failed")]
    assert [(r, t) for r, t, _, _ in messages] == [(1, 1), (1, 2), (2, 1)], "successful turns kept"

    body = (await client.get(f"/api/v1/debates/{debate_id}", headers=base.auth(token))).json()
    assert body["status"] == "failed" and body["failure_reason"] == detail

    types = [e["type"] for e in events]
    assert types[0] == ws_events.DEBATE_STARTED and types[-1] == ws_events.DEBATE_FAILED
    assert ws_events.DEBATE_COMPLETED not in types
    assert events[-1]["data"]["message"] == detail, "WebSocket matches the stored reason"
    assert types.count(ws_events.AGENT_MESSAGE) == 3, "one event per stored message"
    print("8/9. later-round failure keeps messages and records the reason: PASSED")
    return token, debate_id, messages


async def test_resume_without_duplicates(client, token, debate_id, before):
    provider = ScriptedProvider()
    with use_provider(provider), capture_events() as events:
        resp = await client.post(f"/api/v1/debates/{debate_id}/resume", headers=base.auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed" and resp.json()["failure_reason"] is None
    assert provider.calls == 3, "only the 3 missing turns are generated"

    debate, rounds, messages = await stored_state(debate_id)
    assert rounds == [(1, "completed"), (2, "completed"), (3, "completed")]
    positions = [(r, t) for r, t, _, _ in messages]
    assert positions == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)], positions
    assert len(set(positions)) == len(positions), "no duplicate turns"
    assert [m[3] for m in messages[:3]] == [m[3] for m in before], "earlier messages untouched"

    types = [e["type"] for e in events]
    assert types[0] == ws_events.DEBATE_STARTED and types[-1] == ws_events.DEBATE_COMPLETED
    started_rounds = [e["data"]["round_number"] for e in events if e["type"] == ws_events.ROUND_STARTED]
    assert started_rounds == [2, 3], "completed round 1 is not replayed"
    turns = [(e["data"]["round_number"], e["data"]["turn_number"]) for e in events if e["type"] == ws_events.AGENT_MESSAGE]
    assert turns == [(2, 2), (3, 1), (3, 2)]

    # Only failed debates can be resumed; ownership is enforced.
    again = await client.post(f"/api/v1/debates/{debate_id}/resume", headers=base.auth(token))
    assert again.status_code == 409
    pending_id = await new_debate(client, token)
    assert (await client.post(f"/api/v1/debates/{pending_id}/resume", headers=base.auth(token))).status_code == 409
    other = await base.register_and_login(client, base.unique_email("pf-other"))
    assert (await client.post(f"/api/v1/debates/{debate_id}/resume", headers=base.auth(other))).status_code == 404
    assert (await client.post(f"/api/v1/debates/{debate_id}/resume")).status_code == 401
    print("10/11/12. resume continues from the failed turn without duplicates: PASSED")


async def test_retry_inside_debate_creates_no_duplicates(client):
    token = await base.register_and_login(client, base.unique_email("pf-retry"))
    debate_id = await new_debate(client, token, rounds=1)
    provider, create, _ = provider_with([
        status_error(InternalServerError, 503),
        completion("First answer."),
        completion(None, finish_reason="length", reasoning_tokens=2048, completion_tokens=2048),
        completion("Second answer."),
    ])
    with use_provider(provider):
        resp = await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))
    assert resp.status_code == 200 and resp.json()["status"] == "completed", resp.text
    _, _, messages = await stored_state(debate_id)
    assert [m[2] for m in messages] == ["First answer.", "Second answer."]
    assert create.await_count == 4
    print("10. provider retries inside a debate never duplicate messages: PASSED")


async def test_timeout_and_permanent_errors_in_debate(client):
    token = await base.register_and_login(client, base.unique_email("pf-timeout"))
    debate_id = await new_debate(client, token, rounds=1)
    with use_provider(ScriptedProvider({0: LLMTimeoutError("t")})):
        resp = await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))
    assert resp.status_code == 504 and "in time" in resp.json()["detail"], resp.text

    debate_id = await new_debate(client, token, rounds=1)
    with use_provider(ScriptedProvider({0: LLMAuthenticationError("bad key " + SECRET_KEY)})):
        resp = await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))
    assert resp.status_code == 502 and "GROQ_API_KEY" in resp.json()["detail"]
    assert SECRET_KEY not in resp.text
    debate, _, _ = await stored_state(debate_id)
    assert SECRET_KEY not in (debate.failure_reason or "")
    print("timeouts (504) and permanent errors report safe reasons: PASSED")


async def test_no_verdict_for_failed_debate(client, token, failed_id):
    fake = ScriptedProvider()
    with unittest.mock.patch("app.services.verdict_service.get_llm_provider", return_value=fake):
        resp = await client.post(f"/api/v1/debates/{failed_id}/verdict", headers=base.auth(token))
    assert resp.status_code == 400 and fake.calls == 0, resp.text
    resp = await client.get(f"/api/v1/debates/{failed_id}/verdict", headers=base.auth(token))
    assert resp.status_code == 404
    pdf = await client.get(f"/api/v1/debates/{failed_id}/report.pdf", headers=base.auth(token))
    text = base.pdf_text_fragments(pdf.content)
    assert "PARTIAL REPORT" in text and "No final debate verdict has been generated" in text
    print("13. failed debate gets no verdict; report is labelled partial: PASSED")


# ---------------------------------------------------------------------------
# Part 3: interrupted debates, concurrent resume, stale analysis
# ---------------------------------------------------------------------------


async def make_interrupted(client, token, *, minutes_ago: int) -> str:
    """A debate left 'running' mid round 2 (round 1 done, 1 turn of round 2)."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update as sql_update

    debate_id = await new_debate(client, token)
    async with base._test_session() as session:
        debate = await session.get(Debate, debate_id)
        agents = list(debate.agents)
        r1 = DebateRound(debate_id=debate.id, round_number=1, status="completed")
        r2 = DebateRound(debate_id=debate.id, round_number=2, status="running")
        session.add_all([r1, r2])
        await session.flush()
        for turn, agent in enumerate(agents, start=1):
            session.add(DebateMessage(debate_id=debate.id, round_id=r1.id, agent_id=agent.id,
                                      turn_number=turn, message_type="opening", content=f"R1 T{turn}"))
        session.add(DebateMessage(debate_id=debate.id, round_id=r2.id, agent_id=agents[0].id,
                                  turn_number=1, message_type="rebuttal", content="R2 T1"))
        await session.commit()
        stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        await session.execute(
            sql_update(Debate).where(Debate.id == debate.id)
            .values(status="running", started_at=stamp, updated_at=stamp)
        )
        await session.commit()
    return debate_id


async def test_interrupted_debate_detection(client):
    from app.db.redis import redis_client
    from app.orchestration import liveness
    from app.services.debate_service import INTERRUPTED_REASON

    token = await base.register_and_login(client, base.unique_email("pf-interrupt"))

    # Live heartbeat: an old-looking debate still running in a worker stays running.
    alive_id = await make_interrupted(client, token, minutes_ago=60)
    await redis_client.set(liveness.heartbeat_key(alive_id), "x", ex=30)
    body = (await client.get(f"/api/v1/debates/{alive_id}", headers=base.auth(token))).json()
    assert body["status"] == "running", "a live heartbeat is never interrupted"
    await redis_client.delete(liveness.heartbeat_key(alive_id))

    # No heartbeat but updated moments ago (just claimed): grace window.
    fresh_id = await make_interrupted(client, token, minutes_ago=0)
    body = (await client.get(f"/api/v1/debates/{fresh_id}", headers=base.auth(token))).json()
    assert body["status"] == "running", "grace window protects a just-claimed debate"

    # No heartbeat and stale: interrupted -> failed with a clear reason + event.
    dead_id = await make_interrupted(client, token, minutes_ago=60)
    with capture_events() as events:
        listing = (await client.get("/api/v1/debates", headers=base.auth(token))).json()
    dead = next(d for d in listing["items"] if d["id"] == dead_id)
    assert dead["status"] == "failed" and dead["failure_reason"] == INTERRUPTED_REASON
    assert [e["type"] for e in events if e["debate_id"] == dead_id] == [ws_events.DEBATE_FAILED]
    _, rounds, messages = await stored_state(dead_id)
    assert rounds == [(1, "completed"), (2, "failed")] and len(messages) == 3, "nothing lost"

    # Resume continues from round 2, turn 2 without duplicating turns.
    provider = ScriptedProvider()
    with use_provider(provider):
        resp = await client.post(f"/api/v1/debates/{dead_id}/resume", headers=base.auth(token))
    assert resp.status_code == 200 and resp.json()["status"] == "completed", resp.text
    _, rounds, messages = await stored_state(dead_id)
    positions = [(r, t) for r, t, _, _ in messages]
    assert positions == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)] and provider.calls == 3

    # Redis down: fall back to the elapsed-time threshold (default 30 min).
    async def no_redis(_):
        return None

    with unittest.mock.patch.object(liveness, "is_alive", side_effect=no_redis):
        recent_id = await make_interrupted(client, token, minutes_ago=10)
        old_id = await make_interrupted(client, token, minutes_ago=45)
        recent = (await client.get(f"/api/v1/debates/{recent_id}", headers=base.auth(token))).json()
        old = (await client.get(f"/api/v1/debates/{old_id}", headers=base.auth(token))).json()
    assert recent["status"] == "running" and old["status"] == "failed"
    print("interrupted debates are detected safely and resumable: PASSED")


async def test_concurrent_resume_runs_once(client):
    from app.models.verdict import DebateVerdict

    token = await base.register_and_login(client, base.unique_email("pf-concurrent"))
    debate_id = await new_debate(client, token)
    with use_provider(ScriptedProvider({2: LLMEmptyResponseError("empty")})):
        assert (await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))).status_code == 502
    # A stale conclusion must not survive new messages.
    async with base._test_session() as session:
        session.add(DebateVerdict(
            debate_id=debate_id, position="supports", answer="stale", summary="s", reasoning="r",
            supporting_arguments=[], counterarguments=[], confidence="low", confidence_basis="b",
            limitations=[], unresolved_questions=[], evidence_snapshot={},
        ))
        await session.commit()

    async def slow(_index):
        await asyncio.sleep(0.05)

    provider = ScriptedProvider(on_call=slow)
    with use_provider(provider):
        first, second = await asyncio.gather(
            client.post(f"/api/v1/debates/{debate_id}/resume", headers=base.auth(token)),
            client.post(f"/api/v1/debates/{debate_id}/resume", headers=base.auth(token)),
        )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [200, 409], codes
    assert provider.calls == 4, "the debate ran exactly once"
    _, rounds, messages = await stored_state(debate_id)
    positions = [(r, t) for r, t, _, _ in messages]
    assert len(positions) == 6 == len(set(positions))
    assert (await client.get(f"/api/v1/debates/{debate_id}/verdict",
                             headers=base.auth(token))).status_code == 404, "stale verdict removed"
    print("concurrent resume runs once; stale analysis cleared: PASSED")


async def main():
    for test in (
        test_success, test_invalid_api_key, test_invalid_model, test_rate_limit,
        test_timeout, test_server_error_then_success, test_permanent_errors_not_retried,
        test_reasoning_budget_escalation, test_rate_limit_kinds, test_daily_quota_model_fallback,
        test_services_report_specific_provider_reason, test_logs_never_contain_secrets,
    ):
        await test()

    app = await base.setup()
    async with base.client_for(app) as client:
        token, debate_id, before = await test_later_round_failure_preserves_messages(client)
        await test_no_verdict_for_failed_debate(client, token, debate_id)
        await test_resume_without_duplicates(client, token, debate_id, before)
        await test_retry_inside_debate_creates_no_duplicates(client)
        await test_timeout_and_permanent_errors_in_debate(client)
        await test_playground_and_debate_share_configuration(client)
        await test_interrupted_debate_detection(client)
        await test_concurrent_resume_runs_once(client)
    await base.teardown()
    print("\nAll provider failure tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
