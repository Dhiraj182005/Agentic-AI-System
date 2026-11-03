# MAVES initial audit — 2026-11-03

This audit describes the working tree at task start, including extensive pre-existing uncommitted work. Existing changes are preserved. Secrets are excluded.

## Implemented paths found (execution not yet verified)

- React 18, Vite 5, TypeScript, Tailwind; Python 3.11, FastAPI, async SQLAlchemy, Alembic, JWT; PostgreSQL 16 and Redis 7 in Compose.
- Ownership checks for debate/message/claim reads and analysis; authenticated WebSocket transport; debate orchestration, resume/liveness handling and structured turns.
- Shared Groq provider with bounded retries, fallback models and timeouts.
- Tavily client, batched claim extraction, persisted evidence and claim verification.
- Google Fact Check Tools client, source attribution fields, migration 013, missing-key/error fallback, Evidence UI and mocked tests. This is an existing integration, not a missing service.
- Separate agent performance judgment and evidence-based final verdict, confidence caps, stored reports using ReportLab.

## Confirmed incomplete/broken behavior

1. No-fallacy outcomes are deliberately discarded, so a successful clean analysis looks unrun after refresh.
2. Fallacy batch is all-or-nothing and repeats every message. One provider failure discards earlier successful work.
3. Quality evaluation has only four criteria plus an LLM-generated overall value; no rubric version, strengths/weaknesses or batch route.
4. Published judge rubric is already v2 (responsiveness added; changed weights documented in code), while individual evaluation uses an unrelated scoring system. Must expose/version the actual rubric rather than silently alter it.
5. Automatic pipeline omits fallacy/quality stages and limits factual verification to eight claims. Existing claims prevent any later extraction recovery.
6. Verdict staleness compares counts only, missing changed ratings/explanations and new argument analysis with unchanged counts.
7. Frontend loads saved analysis but offers no batch quality control and does not refresh all persisted material after background completion.
8. Methodology combines historical judgment limitations with current state; needs a current database-derived coverage summary.
9. Compose backend has no root env_file. A key in root .env is not automatically passed into the container. Backend startup also does not apply migrations.
10. Existing test setup drops the public schema of its configured test database. These runners must only run against a newly created disposable database.
11. Frontend has no test or lint scripts. External service configuration and live requests remain unverified.

## Implementation priorities

Persist explicit clean analyses; share a resumable per-message pipeline with independent commits and bounded concurrency; use the existing versioned v2 rubric consistently; remove default verification cap; add coverage/progress and working controls; fingerprint verdict inputs; correct Compose configuration; test on an isolated database with mocked external calls, then separately probe configured services.

## Verification boundaries

No live external service success is inferred from environment variable presence. Database history must not be reset or deleted. Similar-claim grouping must preserve message provenance and avoid merging materially different assertions. Original publisher ratings remain external evidence, never automatic MAVES verdicts.
