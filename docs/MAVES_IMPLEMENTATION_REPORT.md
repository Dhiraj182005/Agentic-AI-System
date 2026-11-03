# MAVES implementation and verification report

Date: 3 November 2026 (Asia/Calcutta). Work was performed in the existing repository, preserving its substantial pre-existing uncommitted changes. No commit, database reset, history deletion, or project rewrite was performed.

## Result and verification boundary

The post-debate data path now processes every eligible participant message, stores clean fallacy outcomes and versioned quality evaluations, verifies all extracted factual claim occurrences by default, and refreshes the UI from persisted results. Successful work survives partial failures. Verdict and performance generation use persisted material and remain separate.

Verification includes **23 backend script modules**, **12 frontend tests**, TypeScript, ESLint, production builds, migration consistency, PostgreSQL/Redis health, and a separate **real-provider workflow**. The browser login page was smoke-tested after rebuilding. Authenticated tab interactions were exercised through component integration tests; the live backend workflow used FastAPI's ASGI transport, real PostgreSQL/Redis, and real external providers. This was not a full automated browser journey against every screen or device size.

## Initial audit: working, incomplete, and disconnected features

The complete initial findings are in `MAVES_INITIAL_AUDIT.md`.

Already implemented paths included authentication/ownership checks, debate creation and orchestration, dynamic/built-in agents, resume/liveness handling, WebSockets, Groq retries and model fallback, Tavily, claim extraction/verification, separate performance judgments and debate verdicts, and ReportLab export. Regression tests exercised these paths.

The working tree already contained a genuine Google Fact Check integration, migration 013, publisher attribution fields and an Evidence component. It was extended rather than duplicated. The endpoint and request parameters were checked against the [official claims.search documentation](https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search).

Confirmed defects repaired:

- Clean fallacy results were intentionally discarded, making successful analyses appear unrun after refresh.
- The fallacy batch repeated successful calls and committed everything together; a later failure lost prior work.
- Quality evaluation had four criteria and an LLM-chosen total, without batch processing or rubric metadata.
- The automatic pipeline omitted fallacy/quality stages and verified at most eight claims.
- Existing claims prevented incomplete extraction from being resumed.
- The Methodology UI displayed old v1 weights while the judge actually used documented v2 weights.
- The judge treated explicit clean analyses as missing and sometimes reported a single targeted participant assessment as the coverage of the entire debate.
- Verdict staleness depended on record counts, missing same-count edits. Concurrent generation and changes during inference also needed protection.
- Background completion did not refresh all claims and analysis panels.
- Root and backend environment files disagreed about the model; Compose did not explicitly pass root settings and overrode the JWT secret with a literal development value.
- ORM timestamp constraints disagreed with migrations. Development SQL logging exposed SQL parameter values.
- PDF evidence rows omitted original publisher rating metadata; methodology and pagination needed correction.
- There was no frontend test/lint setup. The original Vite dependency had a high-severity advisory.

Frontend actions now reach real backend operations. The existing per-message actions were already wired, but their results were incompletely persisted and their batch equivalents were missing or disconnected. No remaining decorative analysis button was identified in the repaired panels.

## Feature classification

| Feature | Classification | Evidence / practical limit |
|---|---|---|
| Authentication, ownership, debate orchestration/resume | Implemented and tested | Existing regression modules, plus real registration/login/create/complete workflow in isolated QA DB |
| WebSocket authentication and streaming | Implemented and tested | Existing WebSocket regression module; not a public network soak test |
| Individual and batch fallacy detection | Implemented and tested | Persisted no-fallacy outcomes, idempotency, multiple agents, partial failure/retry; live clean outcomes for both participants |
| Fallacy categories including Cherry Picking | Implemented and tested | Schema/parser tests; migration extends PostgreSQL enum; strongest-fallacy-per-message contract retained |
| Individual and batch argument quality | Implemented and tested | Deterministic v2 total, complete new criterion output, timestamps, strengths/weaknesses, successful live evaluations for both participants |
| Google Fact Check | Implemented and tested | Mocked success/empty/error/timeout/partial-field/persistence tests and successful live searches/attribution |
| Tavily retrieval and claim verification | Implemented and tested | Failure/retry tests and ten factual claim occurrences verified in live QA |
| Claim normalization/grouping | Implemented and tested | Conservative typographical normalization and canonical links preserve every message occurrence; repeated searches can reuse evidence |
| Arbitrary semantic/paraphrase merging | Partially implemented | Conservative normalization handles close textual duplicates. Uncertain paraphrases are deliberately retained separately; there is no semantic clustering model |
| Final verdict and regeneration | Implemented and tested | Real saved verdict; mocked inconclusive, preservation, concurrency and same-count/in-flight change regressions |
| Agent performance | Implemented and tested | Every posting participant assessed using the same published rubric; missing dimensions remain explicit; live two-agent judgment saved |
| Methodology and coverage | Implemented and tested | Database-derived counts, stage states, current rubric, provider status and failures; qualitative model text cannot establish coverage |
| Frontend analysis/evidence integration | Implemented and tested | Twelve component integration tests, real service request wiring, loading/empty/error/success/refresh states, build/typecheck/lint |
| PDF export | Implemented and tested | Existing report regression suite plus rendered live-data report, visual layout inspection and publisher attribution |
| Migrations/history preservation | Implemented and tested | Existing application upgraded to 017; fresh database migration chain; `alembic check` passes; counts unchanged |
| Durable background worker queue / automatic restart continuation | Not implemented | Existing in-process approach retained; persisted progress and stale leases permit explicit recovery/retry |
| Comprehensive browser/device and long-duration load testing | Not implemented | Coverage boundaries described above; not claimed as completed |

No credential-dependent integration is being classified as successful merely from configuration presence. All three configured external services responded to live probes, and the live workflow used `openai/gpt-oss-20b`.

## Persistence, retries, and scoring

Message analyses commit independently using separate sessions and bounded concurrency (default one; clamped to four). PostgreSQL advisory locks serialize competing changes before inference. Successful results are skipped unless explicitly reanalyzed. A failed model call cannot delete a successful fallacy result, score, verdict, or performance judgment.

Extraction stores progress per message, including an explicit completed extraction with zero claims. Successful extraction batches commit before later batches run. Canonical claim links preserve message provenance; verification remains limited to factual claims. Opinions/predictions cannot receive a factual verification verdict through the repaired endpoint. Supported, Contradicted, Partially Supported, Insufficient Evidence and absence of a stored verification remain distinct.

Search retries have a finite budget, bounded backoff, timeouts and limited Retry-After waits. Google problems do not block Tavily. Missing/failed Google search is reported as partial analysis rather than full completion; publisher ratings remain separate from MAVES assessments. Empty Google results remain “No matching published fact-check found.”

The existing **rubric v2** was preserved, not silently replaced with the stale UI's v1 weights:

| Dimension | Weight |
|---|---:|
| Logical soundness | 0.20 |
| Evidence quality | 0.15 |
| Factual support | 0.15 |
| Responsiveness | 0.15 |
| Relevance | 0.10 |
| Effectiveness / clarity | 0.10 |
| Completeness | 0.05 |
| Fallacy risk | 0.10, inverted as `10 - risk` |

Unavailable dimensions are excluded and the available weights renormalized. New message evaluations store their dimension map, computed total, explanation, strengths/weaknesses, evaluation timestamp and rubric version. Historical unversioned scores are preserved and visibly labeled legacy. Quality and performance scores are not factual truth verdicts.

Verdict inputs include the topic, transcript, stored claims/verification explanations, evidence snippets/URLs, publisher ratings and message analysis. Material fingerprints detect changed content even when counts stay the same. Snapshots are captured before inference, so new material arriving during inference marks its result outdated. Explicit regeneration really reruns the verdict; regeneration failure returns an error while retaining the prior successful record.

## Migrations and history

Created and applied:

- **014** — quality criteria/metadata and per-message extraction completion; Cherry Picking enum label.
- **015** — Partially Supported verification enum label.
- **016** — indexed self-referencing canonical claim link, with `SET NULL` on deletion.
- **017** — timestamp nullability aligned with existing ORM metadata. Checks for historical NULLs before changing constraints; never fabricates dates.

Application counts before and after these migrations were identical:

| Users | Debates | Messages | Claims | Evidence rows |
|---:|---:|---:|---:|---:|
| 84 | 82 | 440 | 655 | 436 |

QA data is in separate `maves_audit_test_20261103` and `maves_audit_live_20261103` databases. No existing application history was reset or removed. PostgreSQL enum labels are retained on downgrade to avoid destroying historical values.

## API changes

All paths below retain authentication and ownership checks:

| Method and path | Change |
|---|---|
| `POST /api/v1/messages/{id}/fallacies/analyze?force=true` | Explicit reanalysis; default false reuses stored success |
| `GET /api/v1/debates/{id}/fallacies` | Includes persisted clean outcomes, original argument and timestamp |
| `POST /api/v1/debates/{id}/fallacies/analyze` | Resumable batch; successful results plus individual failures |
| `POST /api/v1/messages/{id}/evaluation?force=true` | Explicit reevaluation; versioned deterministic scoring |
| `GET /api/v1/debates/{id}/evaluations` | Expanded criterion/rubric/strength/weakness/time metadata |
| `POST /api/v1/debates/{id}/evaluations` | New idempotent batch evaluation route |
| `POST /api/v1/debates/{id}/analysis` | Background processing now includes both message analysis stages |
| `GET /api/v1/debates/{id}/analysis` | Adds live stage progress and database-derived coverage/methodology |
| `POST /api/v1/claims/{id}/evidence/retrieve?force=true` | Optional explicit web-source refresh; retains successful sources on failure |
| `POST /api/v1/claims/{id}/verify` | Factual-only verification; Partially Supported allowed |
| `POST/GET /api/v1/debates/{id}/verdict` | Latest-input fingerprint, real regeneration, concurrent generation protection and safe failure behavior |
| `POST /api/v1/debates/{id}/judge` | Correct clean-analysis context, coverage limitations and material snapshot |
| `GET /api/v1/debates/{id}/report.pdf` | Actual analysis metadata, publisher ratings and current coverage |

Google remains a server-side evidence service, not a frontend call exposing its key. Existing claim/evidence retrieval endpoints return its attributed records.

## Configuration

Required environment variable **names only**:

- Runtime/database: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `FRONTEND_URL`.
- Inference: `LLM_PROVIDER`, `GROQ_API_KEY`, `GROQ_MODEL`.
- Evidence: `EVIDENCE_PROVIDER`, `TAVILY_API_KEY`, `GOOGLE_FACT_CHECK_API_KEY`.
- Frontend: `VITE_API_URL`.

Optional controls: `AUTO_ANALYSIS_AFTER_DEBATE`, `ANALYSIS_MAX_VERIFIED_CLAIMS`, `ANALYSIS_MESSAGE_CONCURRENCY`, `ANALYSIS_STALE_SECONDS`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_RETRY_BASE_DELAY_SECONDS`, `LLM_RETRY_MAX_DELAY_SECONDS`, `LLM_MAX_OUTPUT_TOKENS_CEILING`, `GROQ_FALLBACK_MODELS`, `GOOGLE_FACT_CHECK_LANGUAGE`, `GOOGLE_FACT_CHECK_TIMEOUT_SECONDS`, `GOOGLE_FACT_CHECK_MAX_RESULTS`, `GOOGLE_FACT_CHECK_CONCURRENCY`, `JUDGE_MIN_SCORE_GAP`.

Root `.env` specifies `openai/gpt-oss-20b`; the previous container inherited `openai/gpt-oss-120b` from `backend/.env`. Compose now explicitly passes root settings and honors the configured JWT secret. The effective model and the model stored on the live verdict were verified as `openai/gpt-oss-20b`. Rebuilt backend images were checked to contain neither `/app/.env` nor QA artifacts; Compose still supplies runtime settings. Keep the two environment files aligned for standalone backend launches. No real secret values are included here.

## Live workflow evidence

The isolated real-provider workflow registered/logged in, created and completed one two-agent, one-round debate, then persisted:

- 2 transcript messages, 2 clean fallacy outcomes and 2 versioned quality evaluations.
- 10 factual claim occurrences, representing 9 normalized claim groups; all 10 verified.
- 4 attributed Google fact-check records and 50 Tavily source associations.
- 1 insufficient-evidence result, with supported/contradicted/partially-supported findings kept distinct.
- A separate two-agent performance judgment and a saved final verdict using `openai/gpt-oss-20b`.
- A PDF exported from these records and visually inspected after rendering.

The first verdict call hit a real provider rate limit. A retry used the saved extraction/search/verification/message results and successfully generated the verdict. A subsequent run returned `up_to_date`, demonstrating that successful stages were not repeated. The first QA script used the wrong report URL and received 404; it was corrected to `/report.pdf`, and export then succeeded. These were recorded rather than reported as initial successes.

Detailed local evidence is in ignored `backend/test-results/summary.json`, per-module logs, `live-workflow.json`, `live-workflow.pdf`, and `pdf-preview/`. These are QA artifacts, not production demo records.

## Tests and checks executed

The guarded runner ran all existing modules and the new audit workflow module, rerunning affected modules after changes. Final summary: **23 modules with exit code 0**. It uses a disposable database and blanks external credentials for routine runs. Existing fixture setup recreates that disposable database's schema; the guarded runner refuses application database names.

Backend modules: auth, basic, agents, agent selection, debates, dynamic agents, structured debate turns, demo, orchestration, WebSocket, LLM, provider failures, claims, verification, fallacy/evaluation, judge, judgment quality, verdict, report, analytics, analysis pipeline, Google fact check and audit workflow.

Frontend: **12 tests passed**, covering loading, empty/error/success states, saved clean outcomes, actual message/debate IDs in requests, batch controls, background refresh, publisher attribution, missing publisher fields, empty Google search and Tavily fallback. TypeScript and ESLint pass with zero lint warnings. Production builds pass after the Vite upgrade.

Commands executed included:

```powershell
docker exec agentsystem-backend-1 python -m compileall -q app scripts
docker exec agentsystem-backend-1 alembic upgrade head
docker exec agentsystem-backend-1 alembic check
docker exec agentsystem-backend-1 alembic heads
docker exec -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/maves_audit_test_20261103 -e TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/maves_audit_test_20261103 agentsystem-backend-1 python -m scripts.run_audit_tests
docker exec agentsystem-frontend-1 npm test
docker exec agentsystem-frontend-1 npm run typecheck
docker exec agentsystem-frontend-1 npm run lint
docker exec agentsystem-frontend-1 npm run build
docker exec agentsystem-frontend-1 npm audit --audit-level=high
docker exec agentsystem-backend-1 python -m scripts.probe_services
docker compose build frontend
docker compose up -d --no-deps frontend
pdfinfo backend/test-results/live-workflow.pdf
pdftoppm -scale-to 1000 -png backend/test-results/live-workflow.pdf backend/test-results/pdf-preview/page
```

Both Docker images were rebuilt successfully. The rebuilt API reported PostgreSQL and Redis connected; an actual unauthenticated WebSocket connection closed with code 4401, as required.

`live_workflow` and `resume_live_workflow` were also executed with `DATABASE_URL` pointed to the separate live QA database. Unlike routine tests, these explicitly consume real quota.

## Files created or extended in this task

This list describes task-owned edits, not every pre-existing working-tree modification.

**Created:**

- `docs/MAVES_INITIAL_AUDIT.md`, `docs/MAVES_IMPLEMENTATION_REPORT.md`.
- `backend/alembic/versions/014_message_analysis.py`, `015_partial_verification.py`, `016_claim_groups.py`, `017_timestamp_constraints.py`.
- `backend/app/services/message_pipeline.py`, `analysis_coverage.py`; `backend/app/evidence/retry.py`.
- `backend/scripts/run_audit_tests.py`, `probe_services.py`, `live_workflow.py`, `resume_live_workflow.py`.
- `backend/tests/test_audit_workflow.py`.
- `frontend/eslint.config.js`, `frontend/vitest.config.ts`, `frontend/src/test/setup.ts`, `analysis.test.tsx`, `evidence.test.tsx`.
- `backend/.dockerignore`, `frontend/.dockerignore`.

**Extended or modified:**

- Backend config/database: `app/core/config.py`, `app/db/database.py`.
- Backend models: `argument_evaluation.py`, `fallacy.py`, `claim.py`, `claim_verification.py`, `debate_message.py`.
- Backend schemas: `evaluation.py`, `fallacy.py`, `claim.py`, `analytics.py`.
- Backend APIs: `evaluations.py`, `fallacies.py`, `claims.py`, `verdict.py`, `judge.py`.
- Backend services: `argument_analysis_service.py`, `argument_evaluation.py`, `fallacy_detection.py`, `claim_service.py`, `analysis_pipeline.py`, `analysis_coverage.py`, `verification_service.py`, `verdict_service.py`, `debate_judge_service.py`, `judge_rubric.py`, `analytics_service.py`, `report_service.py`.
- Evidence clients: `google_fact_check.py`, `tavily.py`.
- Tests updated for new behavior or guarded nonduplicated execution: `test_analysis_pipeline.py`, `test_fact_check.py`, `test_fallacy.py`, `test_claims.py`, `test_agents.py`, `test_provider_failures.py`, `test_analytics.py`, `test_judge.py`, `test_agent_selection.py`, `test_debates.py`, `test_orchestration.py`, `test_verification.py`.
- Frontend: `src/pages/DebateDetail.tsx`, `src/services/analysis.ts`, `claims.ts`, `verdict.ts`, `package.json`, `package-lock.json`, `Dockerfile`.
- Repository: `.env.example`, `.gitignore`, `docker-compose.yml`, `README.md`.

## Remaining limitations and manual follow-up

1. There are **13 moderate npm advisories**, primarily Router v6 and lint/minimatch dependencies. No high/critical findings remain. Major Router migration or broad transitive overrides were not forced into this feature repair. `npm audit --audit-level=high` passes; this does not mean a zero-advisory audit.
2. Background execution is in-process. A process restart does not automatically resume a job; interrupted jobs are recoverable through the stale lease and explicit retry. This is not a durable worker queue.
3. Historical successful quality rows remain legacy until explicitly reevaluated. Re-evaluate an individual message in Transcript to obtain v2 metadata. They were not silently assigned new criteria or rewritten.
4. Claim grouping is conservative. Semantically similar but differently worded claims may remain separate. Counts distinguish occurrences and normalized groups; sources can be associated with several claims.
5. LLM outputs and search snippets remain fallible. Credibility/relevance assessment is qualitative, not a guarantee or an authoritative publisher trust database. Extraction and prompt size limits remain; long text can be excerpted, and extraction selects at most five examinable claims per message.
6. The inherited PDF approach folds unsupported Unicode into base-font-compatible text. Common dash forms were repaired; comprehensive multilingual font support is not implemented.
7. QA databases and ignored QA artifacts were intentionally retained for review. They contain new isolated test data; no application records were deleted. No cleanup command is required to run the application.
8. Migration 017 refuses to invent dates if another installation has historical NULL timestamps. Such installations must recover those original dates before applying that constraint migration. The current application passed the check without data changes.

## Exact run and verification steps

From the repository root, keep real credentials in root `.env` and do not replace the existing file with the example. The environment names above identify the required configuration.

For an upgraded installation:

```powershell
docker compose up -d db redis
docker compose build backend frontend
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python seed.py
docker compose up -d backend frontend
docker compose exec backend alembic check
```

Seeding is idempotent for built-in agents and does not reset debates. Do not use `docker compose down -v` or run test fixtures against the application database.

Open [MAVES](http://localhost:5173) and [API documentation](http://localhost:8000/docs). The health endpoint is [health](http://localhost:8000/api/v1/health); database and Redis should both report connected.

1. Sign in normally and create a debate with at least two participants. Enable evidence verification to schedule post-debate analysis automatically, or use the analysis controls after completion.
2. Start the debate and verify every participant's transcript messages appear. Completed debate status is separate from ongoing analysis status.
3. Open Fallacy Detection and use **Analyze all arguments / retry failed**. The same pipeline also populates quality/evidence. In Argument Quality the control is labeled **Evaluate all arguments / retry failed**. Watch per-stage progress.
4. Confirm clean analyses are stored as explicit outcomes and quality cards show criterion values, unavailable dimensions, rubric version, strengths/weaknesses and timestamp. Refresh the page to confirm persistence.
5. Check Claims & Verification and Evidence. Expand a claim's evidence to see publisher rating, reviewed claim, date and article link. A missing match must not become a false verdict.
6. Inspect Methodology counts and stage states. A failed/unavailable provider or partial analysis must remain visible. Retry preserves successes and processes missing work.
7. Use Transcript's **Re-analyze Argument** or **Re-evaluate Argument** for explicit individual regeneration. To refresh web evidence explicitly, use the authenticated retrieval endpoint with `force=true`.
8. Generate or regenerate the final verdict and, separately, judge agent performance. New persisted material makes an old verdict/performance assessment outdated. Quality rankings do not decide factual verdicts.
9. Download the PDF and compare its claims, sources, analysis and coverage with the saved tabs.

To rerun routine tests, create a **new** disposable database name, set both database URLs to it and invoke the guarded runner; then run frontend tests/typecheck/lint/build. Never point those variables at `aidebate`. Live probes and the live workflow are optional quota-consuming checks, separate from routine tests.


A concrete isolated test setup (create this database once; never substitute the application database):

```powershell
docker compose exec db createdb -U postgres maves_audit_test_local
docker compose exec -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/maves_audit_test_local -e TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/maves_audit_test_local backend python -m scripts.run_audit_tests
docker compose exec frontend npm test
docker compose exec frontend npm run typecheck
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```
