# MAVES — Pre-deployment audit

Review date: **3 November 2026 (Asia/Calcutta)**. Scope: current repository, application configuration, persisted workflow, tests, dependencies, and deployment artifacts. This is an implementation and readiness review, not a penetration-test certificate.

## Executive summary

**Overall classification: NOT READY for unrestricted public hosting in its current configuration.**

The core academic workflow is implemented and covered by mocked-provider integration tests. The saved full backend run has **25 successful modules**; frontend integration coverage includes **27 tests**. Authentication, debate persistence/recovery, claims/evidence, message analyses, independent agent performance and verdicts, PDF export, and WebSocket handling have executable coverage.

Public deployment still needs strong production credentials, real DNS/TLS and WebSocket proxying, abuse/rate/spending controls, backups and a restore drill, monitoring, and a deliberately limited single-worker hosting model. The current local environment remains a development environment; real `.env` files were not rewritten. A development server or successful build does not establish production readiness.

New production Dockerfiles and a standalone Compose configuration provide a safer starting point: non-root application containers, no backend reload, static frontend serving, private authenticated database/cache services, and loopback application ports. Production startup rejects several unsafe defaults. They do not replace operational controls.

## Feature verification table

“Fully implemented and tested” below means exercised within the stated automated/QA boundary; it does not assert model correctness, public-host validation, or universal test coverage.

| Feature | Status | Evidence / reason | Required action |
|---|---|---|---|
| Registration, login, JWT expiry/validation, protected APIs and ownership | Fully implemented and tested | `test_auth`, `test_debates`, `test_websocket`, `test_deployment`; frontend login/logout/restore integration | Use a unique production signing key and HTTPS; add abuse limits |
| Password hashing and compatibility | Fully implemented and tested | New versioned prehash avoids bcrypt truncation; legacy hashes authenticate and upgrade on successful login; Unicode/suffix tests | Legacy long-password truncation semantics persist until that account next successfully signs in |
| Client logout | Fully implemented and tested | Frontend token removal and protected-route redirect | Server-side token revocation is not implemented |
| Debate creation, panels, mode and round configuration | Fully implemented and tested | Debate/selection/dynamic-agent modules and frontend creation request assertions | Validate actual provider quota for intended panel sizes |
| Multi-round arguments/rebuttals and saved messages | Fully implemented and tested | Orchestration, structured-turn and failure/resume suites | Model output may fall back to preserved plain text when structured formatting fails |
| Async start, lifecycle, exact turn/round progress and refresh recovery | Fully implemented and tested | `test_live_execution`; execution snapshot and activity UI; isolated browser QA used mocked providers | Keep one backend worker/replica |
| Groq provider and model configuration | Fully implemented and tested | Factory/provider retries, rate-limit, timeout, budget and fallback tests; configured model inspected as `openai/gpt-oss-20b` | No fresh live API inference was run for this pre-deployment audit; validate account access before hosting |
| Structured claim extraction | Fully implemented and tested | JSON object/legacy array, fenced/surrounding text, Pydantic validation, bounded repair, source ID checks, zero-vs-failure and retry tests | Human review remains necessary for extraction/classification accuracy |
| Claim normalization and source-message links | Fully implemented and tested | Canonical links retain original occurrences; audit workflow regressions | Arbitrary semantic/paraphrase clustering is only partially implemented |
| Google Fact Check lookup, attribution and persistence | Fully implemented and tested | `test_fact_check`: successful/multiple/empty/incomplete/error/quota/timeout responses and persistence; real client traced | Optional; key presence was inspected without revealing it. Current provider credential/quota health was not externally retested |
| Tavily search and stored evidence | Fully implemented and tested | Mocked search success/failure, source links and persistence tests | Requires valid Tavily configuration/quota; no fresh live search in this audit |
| Claim verification and insufficient evidence | Fully implemented and tested | Supported/contradicted/partial/insufficient states; factual-only analysis, technical-error separation, partial failure/retry | Do not interpret search counts or external publisher ratings as proof |
| Individual/batch fallacy detection | Fully implemented and tested | Fallacy and audit suites; explicit clean outcomes, categories, persistence and successful-result reuse | One strongest fallacy or clean outcome per message; not exhaustive multi-fallacy annotation |
| Argument quality and rubric | Fully implemented and tested | Versioned persisted criteria, deterministic v2 calculation, missing-value handling, batch/message tests | Quality is not truth. Missing dimensions are excluded and remaining weights renormalized |
| Agent performance | Fully implemented and tested | Per-participant judge, rubric and input-completeness suites | Rankings assess performance, not factual correctness |
| Final verdict, evidence use, INCONCLUSIVE, staleness and regeneration | Fully implemented and tested | Verdict, pipeline and audit suites; old successful data survives regeneration failure | Disclose incomplete stages; confidence is qualitative, not calibrated |
| Analysis concurrency, joining existing jobs, retry and stale leases | Fully implemented and tested | Atomic claim, heartbeat, run-ID fencing, duplicate/join tests, interruption recovery | Job continuation after a process crash requires explicit retry/resume |
| WebSocket auth/events, reconnect, duplicate/out-of-order handling | Fully implemented and tested | Backend WebSocket suite and frontend transport/hook tests | TLS proxy upgrade/timeouts and production log redaction still require host verification |
| Persisted methodology and analysis coverage | Fully implemented and tested | Database-derived counts and comparison rows; frontend analyses/coverage tests | No hardcoded completeness claim; partial/failed/pending states remain visible |
| PDF generation and download | Fully implemented and tested | `test_report`: saved data, authorization, safe filename/content, unicode/long text and missing results; frontend download wiring | In-memory generation; monitor large-report memory use |
| Frontend auth, creation, results, loading/empty/error/refresh states | Fully implemented and tested | 27 Testing Library/Vitest tests, real service request wiring with mocked HTTP | Not every screen/action has a full browser E2E test |
| Mobile layout/accessibility | Implemented but not fully tested | Responsive classes, keyboard tab navigation and reduced-motion rules; desktop QA | Test real mobile viewports, keyboard and screen reader before public presentation |
| Production containers and Compose | Implemented but not fully tested | Both production images build; non-root backend and Nginx configuration verified; public proxy integration untested | Public TLS/domain/edge integration is operator work |
| Durable distributed jobs and multi-worker event fan-out | Not implemented | Tasks and connection manager live in one backend process | Required for autoscaling/serverless or automatic crash continuation |
| Per-account billing quotas / rate limiting / abuse controls | Not implemented | Per-debate caps exist; no deployment-wide account/IP spending protection | Critical blocker for unrestricted public signup/AI execution |
| Password reset, email verification, MFA and token revocation | Not implemented | No corresponding working routes/services | Decide account-recovery/security policy before accepting public users |
| Public DNS, certificates, backup schedule, restore drill, monitoring | Not implemented in this repository | Host-specific operational setup is absent | Complete the checklist before opening access |

## Testing results

### Backend

Executed against the separate disposable database `maves_audit_test_liveux_20261103`, not the application database:

```bash
docker exec -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/maves_audit_test_liveux_20261103 -e TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/maves_audit_test_liveux_20261103 agentsystem-backend-1 python -m scripts.run_audit_tests
```

The completed run recorded **25 modules with exit code 0** in `backend/test-results/summary.json`. Logs contain 351 `PASSED` markers; these are script output markers, **not 351 independently collected test cases or a coverage percentage**.

Modules: `test_agent_selection`, `test_agents`, `test_analysis_pipeline`, `test_analytics`, `test_audit_workflow`, `test_auth`, `test_basic`, `test_claims`, `test_debate_turns`, `test_debates`, `test_demo`, `test_deployment`, `test_dynamic_agents`, `test_fact_check`, `test_fallacy`, `test_judge`, `test_judgment_quality`, `test_live_execution`, `test_llm`, `test_orchestration`, `test_provider_failures`, `test_report`, `test_verdict`, `test_verification`, `test_websocket`.

The runner blanks external API keys and uses mocked providers. Every destructive schema fixture now checks the disposable database prefix even when invoked directly. Existing application data was not reset or deleted.

### Frontend and build checks

Executed in the Docker environment before the interruption; the final host repeat is recorded below:

```bash
docker exec agentsystem-frontend-1 npm test -- --reporter=dot
docker exec agentsystem-frontend-1 npm run typecheck
docker exec agentsystem-frontend-1 npm run lint
docker exec agentsystem-frontend-1 npm run build
```

Vitest: **27 passed across four files**. The resumed host verification also passed TypeScript, ESLint and the production asset build after correcting an unsupported Testing Library option in the new auth test. Initial host attempts failed because dependencies were absent and then because the restricted Windows sandbox denied temporary-cache writes; `npm ci` and execution with normal permissions resolved those environment failures. Exact final checks are recorded below.

Earlier failing checks were resolved: the engine's test-only no-session constructor needed to tolerate `None`; concurrency expectations needed the intentional 202 joined-job response; a new test referenced a nonexistent `skipped` counter and was corrected to compare actual persisted record IDs; a frontend agent mock initially used the wrong response envelope. The completed suites above pass after those corrections.

### Dependency review

- `pip-audit -r /app/requirements.txt --format=json`: **no known vulnerabilities** in the final resolved report saved to ignored `backend/test-results/dependency-audit.json`.
- `npm audit --omit=dev --json`: **zero production dependency advisories** after React Router update.
- Full `npm audit`: **11 moderate development-tool dependency findings** remain through the ESLint/typescript-eslint/minimatch chain. They concern processing untrusted glob patterns; do not run repository tooling on untrusted input. A forced major override was not applied without compatibility evidence.
- Initial findings prompted updates of FastAPI, Starlette, PyJWT, python-dotenv and React Router. Official change references: [FastAPI](https://fastapi.tiangolo.com/release-notes/), [Starlette](https://starlette.dev/release-notes/), [PyJWT](https://pyjwt.readthedocs.io/en/stable/changelog.html).

Dependency scanners are point-in-time checks, not proof that all packages, container base layers, or application logic are vulnerability-free. OS image CVE scanning was not completed.

## Security findings and fixes

### Fixed in this pre-deployment work

1. **Unsafe production defaults:** production mode now rejects short/default JWT secrets, non-HTTPS/wildcard frontend origins, default database credentials, unauthenticated Redis URLs, shared demo login, invalid JWT algorithm policy and nonpositive token lifetime. Pydantic error strings hide configuration inputs so a startup error does not print credentials.
2. **Password truncation:** new hashes prehash the full UTF-8 password before bcrypt and carry a version marker. Legacy bcrypt remains supported and upgrades at successful login. No password table reset or destructive migration was used.
3. **Malformed signed JWT subjects:** invalid UUID subjects return 401 rather than reaching PostgreSQL UUID conversion and raising an internal error.
4. **Duplicate-registration race:** uniqueness violations now roll back and return the existing duplicate-email response rather than an unhandled database exception.
5. **Test safety:** direct destructive fixtures reject application/generic database names, supplementing the guarded runner.
6. **Secret-file hygiene:** `.gitignore` covers private `.env*` variants while permitting explicit example templates. Demo mode is disabled in the example. Docker build contexts exclude real environment files.
7. **Dependency findings:** updated affected framework/auth/config/router dependencies, then reran the regression suites. Original backend versions were not assumed safe because they compiled.
8. **Deployment separation:** production Dockerfiles use non-root application users, static Nginx serving and a single non-reloading backend worker; standalone Compose exposes only loopback application ports and keeps PostgreSQL/Redis off host ports.

### Reviewed with remaining boundaries

- No private-key/token patterns were found in the 270-file working-tree scan performed during the audit. No real `.env` file was tracked in the inspected index or found in the checked environment-file history. This is a bounded scan, not a guarantee about remote forks, inaccessible history or previously leaked credentials. Rotate any key ever shared elsewhere.
- The frontend contains public API origin configuration, not private provider keys. `VITE_*` values are public build inputs.
- Authentication dependencies and service ownership checks are present; SQLAlchemy uses bound values. No file-upload route or user-controlled shell execution was identified in the application paths inspected.
- Google keys are sent in a header rather than URL parameters. Provider exception responses use safe categories. Application logging redacts bearer tokens and WebSocket JWT query values; the reverse proxy needs equivalent redaction.
- JWTs live in browser local storage. There is no refresh/revocation service; logout only removes the local token. Production needs an appropriate XSS/CSP and session policy.
- The production frontend supplies basic anti-framing, content-type and referrer headers. TLS/HSTS and a domain-specific CSP are not configured here.
- Shared demo credentials are deliberately public when that optional local feature is enabled. Production mode refuses it. The real development `.env` was left intact.
- The development Compose file exposes services and uses development database credentials; it must not be published as-is.
- `/health` reports database and Redis fields. Its overall label follows database availability, so readiness monitoring must check **both** fields, not just HTTP 200.
- There are no app-level login/registration rate limits, account AI quotas, signup verification or provider-budget enforcement across users. A publicly reachable backend is financially abuse-prone without edge/account controls.

## Infrastructure requirements

- Always-on single backend worker/replica with enough memory for SQLAlchemy sessions and in-memory PDFs. Do not deploy long jobs onto request-lifetime/serverless hosting.
- PostgreSQL 16 with persistent storage, private networking, unique credentials, backups and tested restore.
- Redis 7 on a private network with authentication; use TLS for managed/external connections where required by the host.
- Static frontend hosting with SPA fallback, built using the correct public HTTPS `VITE_API_URL`.
- HTTPS reverse proxy with WebSocket upgrade forwarding, appropriate idle timeouts, request/body limits, rate limits, query-string redaction and restricted trusted-proxy headers.
- Groq key/model access and Tavily quota; Google Fact Check key is optional. Validate provider usage/privacy policies before sending user topics to third parties.
- Explicit migrations and built-in agent seeding during release. The application does not migrate on startup.

Environment names: `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `FRONTEND_URL`, `VITE_API_URL`, `LLM_PROVIDER`, `GROQ_API_KEY`, `GROQ_MODEL`, `TAVILY_API_KEY`, optional `GOOGLE_FACT_CHECK_API_KEY`, analysis/retry/budget settings documented in the README, and production Compose `POSTGRES_PASSWORD`/`REDIS_PASSWORD`. No real values are included in this report.

## Critical blockers before public hosting

1. Fill a new production secret file with unique signing/database/cache credentials and real HTTPS domains; do not reuse development settings.
2. Configure DNS, TLS, secure WebSocket forwarding, restricted proxy trust, request limits and credential-safe proxy logging. Test from an external browser.
3. Enforce login/signup/AI request rate limits and spending/account quotas, or put the entire demo behind controlled access with a strict provider spending cap. Public account creation plus unbounded paid inference is not ready.
4. Back up PostgreSQL, rehearse restore, and define release/migration/rollback procedures.
5. Keep one backend instance and document manual crash recovery; do not advertise durable jobs, autoscaling or uninterrupted deployment.
6. Revalidate real provider credentials/model access in the intended hosting environment. Presence of a key does not establish access, billing or quota health.

## Non-critical improvements

- Durable workers/shared notifications before scaling; automated cleanup/retention for execution events and old reports/data.
- Account recovery, email verification, MFA, server-side token invalidation and a stronger session policy.
- Mobile/screen-reader testing, full browser E2E journeys, load/soak testing, calibrated AI evaluation and human review.
- Lock transitive backend dependencies/base image digests for reproducible releases; add CI and automated security scans.
- Resolve the development minimatch tooling chain when compatible upstream releases are available; do not use `npm audit fix --force` blindly.
- Select a repository license. None was found; no MIT or other license is asserted.

## Manual verification and deployment checklist

### Prepare without exposing the development stack

1. Read the README and finish the blockers above. Keep real `.env` files private. Generate independent random signing, database and cache credentials. Use URL-safe hex passwords or percent-encode reserved URL characters.
2. Make a database backup and retain it outside Git. For existing development data, these commands avoid binary redirection problems in Windows PowerShell:

   ```bash
   docker compose exec -T db pg_dump -U postgres -d aidebate -Fc -f /tmp/maves-before-deploy.dump
   docker compose cp db:/tmp/maves-before-deploy.dump ./maves-before-deploy.dump
   ```

   Store the dump securely. Restore first into a separate staging database and verify record access; do not overwrite the application database. Migrating existing history to a new production volume needs a planned restore, not an empty reseed.
3. Copy `.env.production.example` to ignored `.env.production`. Set matching database/cache service credentials and URLs, a long unique JWT key, actual `FRONTEND_URL` and `VITE_API_URL`, and provider credentials. Keep demo login disabled.
4. Use a separate production project. Do **not** combine development and production Compose files. Stop conflicting development application ports before a real deployment; preserve their volumes.

### Build, migrate, and start a fresh production installation

```bash
docker compose --env-file .env.production -f docker-compose.production.yml -p maves-production config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml -p maves-production build
docker compose --env-file .env.production -f docker-compose.production.yml -p maves-production up -d db redis
docker compose --env-file .env.production -f docker-compose.production.yml -p maves-production run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.production.yml -p maves-production run --rm backend python seed.py
docker compose --env-file .env.production -f docker-compose.production.yml -p maves-production up -d backend frontend
docker compose --env-file .env.production -f docker-compose.production.yml -p maves-production exec backend alembic check
```

These commands create the separate production project's persistent volume. They do not transfer existing development history. Use a staging-tested restore plan if history must move. Never run `down -v` against valuable data.

Put your host TLS reverse proxy in front of loopback port 8080 (frontend) and 8000 (backend). A proxy in another container cannot reach the host's loopback bindings directly; configure networking deliberately rather than exposing database/cache ports. Preserve `/api/v1`, `/docs` as intended, and `/ws` WebSocket upgrades. Trust forwarded headers only from the actual proxy. Changing the backend domain requires rebuilding frontend assets because `VITE_API_URL` is a build-time value.

### Verify the hosted workflow

- [ ] Health shows both database and Redis connected; migration head is 018 and `alembic check` is clean.
- [ ] Frontend contains the intended HTTPS API origin and no localhost/provider secrets; WSS connects through the proxy.
- [ ] Register/login work, incorrect/expired tokens are rejected, logout removes local access, and a second user cannot read another user's debates/reports.
- [ ] A short two-agent/two-round debate saves turns, shows live agents/rounds, and recovers after refresh and a network reconnect.
- [ ] Double-clicking start/analysis does not duplicate work. An existing run shows progress instead of a confusing conflict.
- [ ] Extraction distinguishes running, successful zero claims, and failure. Retry preserves successful message analyses.
- [ ] Google reviews retain publisher/rating/URL; empty lookup is not treated as false. Tavily sources and claim findings persist and refresh automatically.
- [ ] Every eligible participant gets fallacy/quality analysis; clean results and missing scores are explicit.
- [ ] Verdict uses saved evidence, INCONCLUSIVE is possible, limitations disclose failed stages, and regeneration updates the saved result.
- [ ] PDF downloads with actual persisted analyses/citations and no fabricated empty sections.
- [ ] Kill/restart a **staging** worker mid-job; verify interruption detection, manual resume/retry and no lost/duplicated successful turns.
- [ ] Test narrow/mobile viewports, keyboard tabs, reduced motion, long questions/transcripts, provider failures, and quota exhaustion.
- [ ] Edge rate/spending controls work; backups restore successfully; logs contain no JWT query strings or private API keys.

## Final deployment recommendation

| Target | Recommendation |
|---|---|
| Local demonstration | **READY WITH LIMITATIONS**: configure providers and infrastructure; expect LLM uncertainty and recoverable provider errors |
| College project presentation | **READY WITH LIMITATIONS**: rehearse a short workflow, disclose mocked/optional stages honestly, and have saved history available if quota fails |
| Public portfolio demonstration | **NOT READY as currently configured**. A gated, budget-limited single-worker deployment is reasonable after the manual blockers are completed and verified |
| General production/multi-user service | **NOT READY**: needs abuse/account controls, recovery/operational testing and a deployment architecture appropriate to availability/load requirements |

## Change inventory

Created: `.env.production.example`, `docker-compose.production.yml`, `backend/Dockerfile.production`, `frontend/Dockerfile.production`, `frontend/nginx.conf`, `backend/tests/test_deployment.py`, `frontend/src/test/auth-and-create.test.tsx`, this audit.

Updated: root README, `.env.example`, `.gitignore`, backend settings/security/auth service, dependency manifests/lockfile, disposable-database guards across destructive test fixtures, and live-execution recovery assertions. The earlier live-workspace work introduced execution migration **018**; no additional database migration is required for this security/documentation phase. Real `.env` files and existing debate records were not overwritten/reset.

## Completion verification appendix

Completed in the resumed environment:

| Check | Actual outcome |
|---|---|
| `npm ci` in `frontend` | Passed; installed lockfile dependencies |
| `npm test -- --reporter=dot` | 27 tests passed across 4 files |
| `npm run typecheck` | Passed after fixing unsupported `exact` test query options |
| `npm run lint` | Passed |
| `npm run build` | Passed; one non-blocking warning for the 507.57 kB JavaScript chunk (146.49 kB gzip) |
| `npm audit --omit=dev --json` | Passed; 0 production advisories |
| Production Compose `config --quiet` with isolated dummy credentials | Passed; no application environment file modified |
| Host production-configuration, password-format and disposable-fixture unit checks | All 3 passed; no database/API calls |
| Documentation local links and code fences | Passed for README and this audit |
| `git diff --check` | Passed |
| Credential-pattern scan | 270 files considered; no credential-pattern findings; no actual environment values printed |
| Saved complete backend run | 25 modules, all exit code 0; database migration consistency rechecked after Docker recovery |

Docker Desktop initially failed to expose its Linux engine and IPC server despite launcher processes running. The user also confirmed the application would not open. The controlled process restart recovered the Linux engine (Docker 29.3.1). Both production image builds subsequently passed. The backend image runs as UID 10001, and the frontend image passed `nginx -t`. Application PostgreSQL migration head is 018 and `alembic check` reports no new upgrade operations. These checks do not establish public TLS/proxy integration or constitute a deployed production workflow. No Docker factory reset, volume deletion, application-database reset or public deployment was performed.


Final container commands executed successfully:

```bash
docker build -q -f backend/Dockerfile.production -t maves-predeploy-backend:qa backend
docker build -q -f frontend/Dockerfile.production --build-arg VITE_API_URL=https://api.maves.example.com -t maves-predeploy-frontend:qa frontend
docker run --rm --entrypoint id maves-predeploy-backend:qa
docker run --rm maves-predeploy-frontend:qa nginx -t
docker exec agentsystem-backend-1 alembic current
docker exec agentsystem-backend-1 alembic check
```

The frontend image used an explicit example HTTPS origin for build validation, not a claimed live deployment. Rebuild with your actual API origin before hosting. The Nginx entrypoint emitted an informational message that it could not rewrite the non-root configuration; the configuration syntax test itself passed.
