# Multi-Agent LLM Based Argument Verification and Evidence-Based Decisions

> Final Year B.Tech CSE (Data Science) Project — Academic Year 2026–27

---

## Current Architecture

```
frontend → backend → PostgreSQL
                   → Redis
```

## Technologies

- **Backend:** Python 3.11, FastAPI, SQLAlchemy (async), Alembic, Pydantic, ReportLab (PDF)
- **Frontend:** React 18, Vite, TypeScript, TailwindCSS
- **Database:** PostgreSQL 16
- **Cache:** Redis 7
- **Containerization:** Docker, Docker Compose

## Folder Structure

```
project-root/
├── frontend/              # React + Vite
│   ├── src/
│   ├── public/
│   └── package.json
│
├── backend/               # FastAPI
│   ├── app/
│   │   ├── api/           # Route handlers
│   │   ├── agents/        # AI agents (BaseAgent)
│   │   ├── llm/           # LLM provider abstraction + factory
│   │   ├── core/          # Config, logging, security
│   │   ├── db/            # Database + Redis
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic
│   │   └── main.py
│   ├── alembic/           # Migrations
│   ├── tests/
│   └── requirements.txt
│
├── docker-compose.yml
├── .env.example
└── .gitignore
```

## Environment Setup

1. Copy `.env.example` to `.env` and configure values
2. Ensure Docker is running

## How to Start PostgreSQL and Redis

```bash
docker-compose up -d db redis
```

## How to Start Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Or via Docker:
```bash
docker-compose up backend
```

## How to Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Or via Docker:
```bash
docker-compose up frontend
```

## How to Run Migrations

```bash
cd backend
alembic upgrade head
```

## How to Seed Agents

```bash
cd backend
python seed.py
```

## How to Run Tests

```bash
cd backend
python -m tests.test_basic     # requires PostgreSQL/Redis (health, DB, seeding)
python -m tests.test_auth      # requires a dedicated `aidebate_test` database
python -m tests.test_llm       # LLM provider + BaseAgent (provider is mocked, no API key needed)
python -m tests.test_agents    # Core role-based agents + factory + endpoint (provider mocked)
python -m tests.test_debates   # Debate creation + agent selection (also re-runs auth and LLM tests)
python -m tests.test_orchestration  # Debate orchestration engine (also re-runs auth, LLM and agent tests)
python -m tests.test_websocket      # Live WebSocket streaming + event manager (also runs auth/orchestration paths)
python -m tests.test_claims        # Claim extraction + evidence retrieval (also re-runs auth and debate tests)
python -m tests.test_verification  # Claim verification + evaluation (also re-runs auth, debate and claim tests)
python -m tests.test_fallacy       # Fallacy detection + argument quality evaluation
python -m tests.test_judge         # Debate judge + scoring policy
python -m tests.test_analytics     # Analytics dashboard + full regression of every earlier suite
python -m tests.test_agent_selection  # Topic-aware automatic agent selection (LLM mocked)
python -m tests.test_report     # PDF conclusion report service + endpoint (read-only, no LLM)
python -m tests.test_verdict    # Final debate verdict (LLM mocked; guards, auth, context)
python -m tests.test_demo       # Demo account + login (normal auth flow)
python -m tests.test_provider_failures  # LLM provider errors, retries, failed-debate resume (no network)
python -m tests.test_debate_turns       # Structured debate turns: schema, prompts, rebuttal links
python -m tests.test_judgment_quality   # Judge input completeness, rubric v2, stale/state separation
python -m tests.test_dynamic_agents     # Topic analysis, AI specialist roles, budgets, request IDs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API info |
| GET | `/api/v1/health` | Health check (DB + Redis) |
| POST | `/api/v1/auth/register` | Register a user |
| POST | `/api/v1/auth/login` | Login, returns JWT |
| GET | `/api/v1/auth/me` | Current user (Bearer token) |
| POST | `/api/v1/ai/test` | Test BaseAgent → LLM (Bearer token, mocked in tests) |
| GET | `/api/v1/agents` | Active core agents for selection (Bearer token) |
| POST | `/api/v1/agents/test` | Test a single role-based agent (Bearer token) |
| POST | `/api/v1/debates` | Create a debate and assign agents (Bearer token) |
| GET | `/api/v1/debates` | List the authenticated user's debates (Bearer token) |
| GET | `/api/v1/debates/{debate_id}` | Get one owned debate (Bearer token) |
| POST | `/api/v1/debates/{debate_id}/start` | Execute a created debate (Bearer token, synchronous) |
| GET | `/api/v1/debates/{debate_id}/messages` | Debate transcript ordered by round/turn (Bearer token) |
| GET | `/api/v1/debates/{debate_id}/rounds` | Debate rounds with status and timestamps (Bearer token) |
| WS | `/ws/debates/{debate_id}?token=<JWT>` | Live debate events for an owned debate (subscription channel) |
| POST | `/api/v1/debates/{debate_id}/claims/extract` | Extract claims from a debate's messages (Bearer token, owner only) |
| GET | `/api/v1/debates/{debate_id}/claims` | List stored claims in deterministic order (Bearer token, owner only) |
| POST | `/api/v1/claims/{claim_id}/evidence/retrieve` | Retrieve + persist search results for a claim (Bearer token, owner only) |
| GET | `/api/v1/claims/{claim_id}/evidence` | Stored evidence for a claim, database read only (Bearer token, owner only) |
| POST | `/api/v1/claims/{claim_id}/verify` | Evaluate a claim against its stored evidence (Bearer token, owner only) |
| GET | `/api/v1/claims/{claim_id}/verification` | Latest stored verification result, database read only (Bearer token, owner only) |
| POST | `/api/v1/debates/{debate_id}/judge` | Generate (or reuse) the stored debate judgment (Bearer token, owner only) |
| GET | `/api/v1/debates/{debate_id}/judgment` | Read the stored judgment, database read only (Bearer token, owner only) |
| POST | `/api/v1/debates/{debate_id}/verdict` | Generate the final debate verdict (`?regenerate=true` replaces it; Bearer token, owner only) |
| GET | `/api/v1/debates/{debate_id}/verdict` | Stored final verdict with cited claims and sources (never calls the LLM) |
| POST | `/api/v1/debates/{debate_id}/resume` | Continue a failed debate from the failed turn (keeps completed rounds and stored messages; 409 unless status is failed) |
| POST | `/api/v1/debates/recommend-agents` with `include_specialists: true` | Topic analysis + built-in picks + proposed AI specialist roles (cached in Redis; falls back to built-in selection) |
| GET | `/api/v1/auth/demo` | Demo login credentials when demo mode is enabled and set up; otherwise `{"enabled": false}` |
| GET | `/api/v1/debates/{debate_id}/report.pdf` | Downloadable PDF conclusion report built from stored data (Bearer token, owner only) |
| GET | `/api/v1/analytics/summary` | Dashboard KPI counts + status distribution (Bearer token, owner only) |
| GET | `/api/v1/analytics/debate-activity` | Debates created per UTC day over a range (Bearer token, owner only) |
| GET | `/api/v1/analytics/claim-verification` | Stored verdict + confidence distributions (Bearer token, owner only) |
| GET | `/api/v1/analytics/agent-performance` | Judgment score aggregates per agent (Bearer token, owner only) |
| GET | `/api/v1/analytics/argument-quality` | Fallacy + evaluation aggregates (Bearer token, owner only) |
| GET | `/api/v1/analytics/recent-debates` | Paginated recent debates with summary fields (Bearer token, owner only) |
| GET | `/docs` | Swagger UI |

## LLM Provider and Base Agent

### Provider Abstraction

LLM access goes through a clean provider abstraction:

```
API Endpoint (POST /api/v1/ai/test)
      ↓
BaseAgent
      ↓
BaseLLMProvider
      ↓
LLM Factory
      ↓
GroqProvider
      ↓
Groq API
```

- `app/llm/base.py` — `BaseLLMProvider` interface, `LLMMessage`, normalized `LLMResponse`, and provider error types.
- `app/llm/factory.py` — `get_llm_provider()` reads `LLM_PROVIDER` and returns the right provider.
- `app/llm/providers/groq_provider.py` — the first provider, using the official Groq SDK.
- `app/agents/base_agent.py` — `BaseAgent`, the reusable base for all future role-specific agents.

### Groq as the Initial Provider

`GroqProvider`:

- reads `GROQ_API_KEY` and `GROQ_MODEL` from configuration
- uses async Groq chat completions
- respects `LLM_TIMEOUT_SECONDS`
- converts the internal message format to the Groq SDK format
- normalizes every response into the project's `LLMResponse`
- never exposes API keys or provider credentials in errors or logs

Agents never import the Groq SDK. They only depend on `BaseLLMProvider`.

### Normalized Responses

Every provider returns the same structure, so agents and callers never depend on SDK-specific shapes:

```json
{
    "content": "Generated answer",
    "provider": "groq",
    "model": "configured-model"
}
```

### BaseAgent

`BaseAgent` supports a `name`, `role`, and configurable `system_prompt`. Its `generate_response(user_input)` builds a system + user message pair and sends them through the provider abstraction, returning a normalized `LLMResponse`. Future role-specific agents (Economist, Lawyer, etc.) will subclass it.

### Environment Configuration

Copy `.env.example` to `.env` and set:

| Variable | Description |
|----------|-------------|
| `LLM_PROVIDER` | Provider to use, e.g. `groq` |
| `GROQ_API_KEY` | Your Groq API key |
| `GROQ_MODEL` | A supported Groq model name |
| `LLM_TIMEOUT_SECONDS` | Request timeout in seconds (default `60`) |

The backend fails with a clear configuration error if an LLM endpoint is called without required configuration. Never commit a real API key (`.env` is git-ignored).

### Protected Test Endpoint

`POST /api/v1/ai/test` is protected by the existing JWT authentication from Module 2:

```json
// Request
{ "message": "Explain the importance of renewable energy in two sentences." }

// Response
{ "response": "...", "provider": "groq", "model": "..." }
```

Unauthenticated requests receive `401`. Invalid input receives `422`. Provider failures, timeouts, and configuration errors are mapped to controlled responses.

### Adding Future Providers

To add a provider later (OpenAI, Gemini, Anthropic, ...):

1. Implement a new class extending `BaseLLMProvider` under `app/llm/providers/`.
2. Return it from the factory based on `LLM_PROVIDER`.

Agents and the API layer do not change.

## Core Role-Based AI Agents

Six core role-specific agents reuse the Module 3 `BaseAgent` + LLM provider architecture. Every role agent inherits from `BaseAgent` → `BaseLLMProvider` → `GroqProvider`. No agent imports the Groq SDK directly.

```
BaseAgent
   ↓
RoleBasedAgent
   ↓
EconomistAgent  LawyerAgent  DoctorAgent  ScientistAgent  EthicistAgent  AnalystAgent
   ↓
LLM Provider (BaseLLMProvider)
   ↓
GroqProvider → Groq API
```

| Agent | Identifier | Purpose |
|------|------|------|
| Economist | economist | Economic analysis |
| Lawyer | lawyer | Legal reasoning |
| Doctor | doctor | Health/medical perspective |
| Scientist | scientist | Scientific reasoning |
| Ethicist | ethicist | Ethical analysis |
| Analyst | analyst | General structured analysis |

### Role-Based System Prompts

Each agent carries a high-quality role-specific system prompt kept in `backend/app/agents/prompts/` (one module per role). Prompts define the professional perspective, reasoning style, domain focus, limitations, and response behavior. They describe analytical AI roles and never claim to be licensed professionals.

### Agent Factory / Registry

`backend/app/agents/factory.py` provides one centralized registry:

- `get_agent_by_role("economist")` → `EconomistAgent`
- Unsupported roles raise `UnsupportedAgentError`
- Machine-readable identifiers (`economist`, `lawyer`, ...) drive internal logic; display names (`Economist`, `Lawyer`, ...) stay for the UI.

### Agent Relationship to Database Records

The six seeded `Agent` DB records (Economist, Lawyer, Scientist, Doctor, Ethicist, Analyst) provide persistence/configuration metadata. The Python role agents provide runtime behavior. Both share the same role identifiers; no duplicate records are created.

### Test Endpoint

`POST /api/v1/agents/test` is protected by the Module 2 JWT dependency and executes exactly one agent per request:

```json
// Request
{ "agent": "economist", "message": "What are the economic effects of electric vehicles?" }

// Response
{ "agent": "economist", "role": "Economist", "response": "...", "provider": "groq", "model": "openai/gpt-oss-20b" }
```

Unauthenticated requests receive `401`, unsupported agents receive `404`, empty/missing messages receive `422`, and provider failures, timeouts, and configuration errors map to controlled `5xx` responses.

A minimal developer test page exists at `/agents` in the frontend (agent dropdown, message input, send button, response display). It is not a debate interface.

## Debate Creation and Agent Selection

Module 5 stores debates and their participating agents. It is a data/API layer only.

```
Authenticated User
      ↓
POST /api/v1/debates (topic + configuration + agent selection)
      ↓
Validate request and selected agents
      ↓
Create Debate row  +  Debate-Agent association rows (one transaction)
      ↓
Return debate details (status: pending = created, waiting to start)
```

Creating a debate does **not** start the debate. No Groq/LLM call, no runtime agent instantiation, no round, no WebSocket and no background job happens at creation time. Debate execution belongs to a later module.

### Debate-agent relationship

Participation is stored in a normalized `debate_agents` association table (Alembic migration `002`):

- `debate_id` → `debates.id` (cascade delete)
- `agent_id` → `agents.id` (cascade delete)
- `created_at`
- composite primary key on `(debate_id, agent_id)` prevents duplicate assignment
- index on `agent_id`

Agent data is never duplicated into the `debates` table.

### Agent selection modes

| Mode | Behaviour |
|------|-----------|
| `manual` | The user explicitly selects core agents. At least 2 are required. |
| `auto` | Deterministic rule: **all active core agents** participate. No LLM, no ranking model. Intelligent (AI-based) selection may be added later. |

Selection uses the stable role identifiers (`economist`, `lawyer`, `doctor`, `scientist`, `ethicist`, `analyst`). Database UUIDs are never hardcoded in requests. Validation rejects unknown, inactive, non-core and duplicate agents.

### Debate configuration and status

Existing model conventions are reused: `mode` is `balanced` or `pro_con`, `total_rounds` is 1–10, `domain_tags` is an optional list, `verify_evidence` is a boolean, and `status` starts at `pending` — the existing enum's state for a created debate that is stored and waiting to start.

### Debate ownership

The application is multi-user. `GET /api/v1/debates` only returns the caller's debates, and `GET /api/v1/debates/{debate_id}` returns `404` when the debate does not exist **or** belongs to another user, so users cannot probe each other's debates.

### Frontend pages

| Route | Page |
|-------|------|
| `/` | Dashboard: summary counts (incl. final verdicts), recent debates, recent verdicts, "Start New Debate" |
| `/debates/new` | New Debate in three steps (question + optional context, expert panel with automatic topic-aware or manual selection, format); **Start Debate** creates and starts it |
| `/debates` | My Debates: search by topic/agent and filter by backend status |
| `/debates/{id}` | Debate results: overview, live run, conclusion, claims, evidence, analysis, transcript, PDF download |
| `/reports` | Reports: every finished (completed / failed / cancelled) debate with a Download PDF action |
| `/analytics` | Analytics (previously `/dashboard`, which now redirects here) |
| `/agents` | Agent Playground: send one message to a single agent |
| `/profile` | Profile: account details, demo-account notice, sign out |

All are protected routes and use the centralized API client (environment-based API URL + automatic Bearer token). Client-side validation mirrors the backend rules, but backend validation stays authoritative.

### Key files

- `backend/app/models/debate_agent.py` — association model
- `backend/app/schemas/debate.py` — request/response schemas
- `backend/app/services/debate_service.py` — creation, selection, listing, ownership
- `backend/app/services/agent_service.py` — active core agent discovery
- `backend/app/api/debates.py` — protected debate endpoints
- `backend/alembic/versions/002_debate_agents.py` — migration
- `backend/tests/test_debates.py` — module tests (also re-runs Module 2 and Module 3 suites)

## Debate Orchestration

Debate creation (Module 5) only stores the debate. Execution happens exclusively through `POST /api/v1/debates/{debate_id}/start`, which runs the whole debate synchronously and answers only after it completed or failed. Creating a debate never touches the LLM.

### Debate lifecycle

`pending` → `running` → `completed`, or `running` → `failed` when execution cannot continue.

- `pending` — created and stored, not started. Only this state may be started.
- `running` — at least one round has begun; the start endpoint holds the request open.
- `completed` — every configured round finished and every message is stored.
- `failed` — an unrecoverable error occurred. Failed debates are never silently marked completed, and they cannot be started again (no retry support yet).

`started_at` and `completed_at` are stored on the debate; `GET /api/v1/debates/{debate_id}` reports `status`, `round_count`, `started_at` and `completed_at` (the transcript is deliberately not embedded there).

### Rounds

Each debate stores its rounds in `debate_rounds` (`round_number`, `status`, `started_at`, `completed_at`), with one row per configured round and a unique `(debate_id, round_number)` constraint, so a duplicate start cannot create duplicate rounds.

Round statuses follow `pending` → `running` → `completed`, or `failed` when the round is interrupted by an error.

Message types are deterministic from the round position:

| Round | Message type |
|-------|--------------|
| First round | `opening` |
| Middle rounds | `rebuttal` |
| Final round | `closing` |

A one-round debate only produces `opening` messages.

### Turn ordering

The speaking order is the order in which the agents were selected for the debate, stored in `debate_agents.position` (1, 2, 3, ...). The same order is reused in every round — agents are never shuffled, removed or re-selected, and no LLM is involved in ordering. Within a round, turn numbers restart at 1, so ordering is always `round_number` then `turn_number`.

### Sequential agent execution

Agents execute **sequentially**, never in parallel: later agents need the previous agents' responses as context. The sequence for one round is:

```
Agent A generates → message persisted → Agent B receives A's message
  → Agent B generates → message persisted → Agent C receives A + B → ...
```

The runtime prompt for each turn contains the topic, the previous debate transcript (from round 2 on), the current round number and a fixed instruction for the message type. The role-specific system prompt of the agent is untouched, so every agent stays inside its professional perspective. Transcript context is bounded (most recent messages, truncated per message, hard prompt length cap), so a long debate cannot grow the prompt without limit.

### Transcript persistence

Every generated message is committed to `debate_messages` immediately after generation — not at the end of the debate — so a failure later on never loses the messages that already succeeded. Each message stores `debate_id`, `round_id`, `agent_id`, `turn_number`, `message_type`, `content` and `created_at`.

Transactions stay short: status change → commit → generate → save message → commit → continue. One long-lived transaction is never held around LLM calls.

### Failure handling

If a generation fails:

1. The failure is logged on the server only (no credentials, no stack traces in the response).
2. The current round is marked `failed`.
3. The debate is marked `failed` (never `completed`).
4. All previously generated messages are preserved and remain readable through the transcript endpoint.

Provider failures return `502` with a generic message, internal errors return `500` with a generic message. Retries are only the ones already built into the Groq SDK's provider layer (exponential backoff, including `429` rate limits).

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/debates/{debate_id}/start` | Executes the debate synchronously. `404` when it is not the caller's debate, `409` when it is not in `pending` state, `502`/`500` on execution failure. |
| GET | `/api/v1/debates/{debate_id}/messages` | Transcript ordered by `round_number`, then `turn_number`, including the speaking agent. |
| GET | `/api/v1/debates/{debate_id}/rounds` | Round number, status, `started_at`, `completed_at`. |

All three require Bearer authentication and only expose the authenticated user's own debates.

### Frontend

`/debates/{id}` shows a **Start debate** button while the debate is `pending`; the button is disabled during execution so a page cannot fire two starts (the backend enforces this regardless). After execution the page shows the round list and the transcript grouped by round, with the real API data for each agent message. Loading or refreshing the page always fetches the current status and transcript from the backend.

### Key files

- `backend/app/orchestration/debate_engine.py` — lifecycle, rounds, sequential turns, persistence, failure handling
- `backend/app/orchestration/round_manager.py` — round status transitions and prompt/context building
- `backend/app/orchestration/turn_manager.py` — deterministic speaker order
- `backend/app/models/debate_round.py`, `backend/app/models/debate_message.py` — execution models
- `backend/app/services/debate_service.py` — `start_debate`, transcript and round queries
- `backend/app/api/debates.py` — start/messages/rounds endpoints
- `backend/alembic/versions/003_debate_rounds_messages.py` — migration
- `backend/tests/test_orchestration.py` — module tests (also re-runs Module 2, 3 and 4 suites)

## Live Debate Streaming

The debate detail page shows the run **live** while `POST /debates/{id}/start`
is still executing: status, rounds, the current speaker and every new message
appear as they are persisted.

```
DebateEngine ──after each commit──▶ DebateEventManager ──▶ ConnectionManager ──▶ subscribed sockets
```

### Endpoint and authentication

- `WS /ws/debates/{debate_id}?token=<JWT>` — the same Module 2 JWT used for
  HTTP, passed as a query parameter (browsers cannot set headers on WebSocket
  handshakes).
- The token is only decoded: it is **never logged** (uvicorn access-log lines
  are scrubbed by `RedactSecretsFilter`), **never broadcast** and **never
  stored**.
- Ownership is re-checked per connection. Close codes:

| Code | Meaning |
|------|---------|
| 4401 | Missing, invalid or expired token |
| 4403 | Authenticated, but the debate belongs to another user |
| 4404 | Debate does not exist |

### Event types

Every event has `{type, debate_id, timestamp, data}`:

| Type | `data` payload |
|------|----------------|
| `debate_started` | `status` |
| `round_started` | `round_number` |
| `agent_turn_started` | `round_number`, `turn_number`, `agent{id,name,role}` |
| `agent_message` | `round_number`, `turn_number`, `message_type`, `message_id`, `agent`, `content` |
| `agent_turn_completed` | `round_number`, `turn_number`, `agent` |
| `round_completed` | `round_number` |
| `debate_completed` | `status` |
| `debate_failed` | `status`, safe `message` (identical to the HTTP error text) |
| `error` | `message` (e.g. malformed client frame) |

### Delivery rules

- Events are emitted **only after the database commit**, so a client that
  receives `agent_message` can always fetch that message from the transcript
  endpoint (same `message_id`).
- A failing socket is dropped and never breaks the broadcast for the others.
- The socket is an observation channel only: clients cannot drive the debate,
  and broadcast problems never fail a debate.
- The manager is process-local (single backend worker); a multi-instance
  deployment would need shared fan-out (e.g. Redis Pub/Sub).

### Frontend

- `services/websocket.ts` — `DebateWebSocketClient`: connect/disconnect, JSON
  event parsing, limited exponential-backoff reconnect, and **no** reconnect
  after 4401/4403/4404.
- `pages/DebateDetail.tsx` — opens the socket *before* firing the (blocking)
  start request, appends live messages deduplicated by `message_id`, shows a
  live panel (connection state, current round, current speaker) and reconciles
  the final view with the HTTP transcript/rounds when the debate finishes.

### Key files

- `backend/app/websocket/manager.py` — `ConnectionManager` (register/unregister/broadcast)
- `backend/app/websocket/events.py` — `DebateEventManager` (payload building + publish)
- `backend/app/websocket/auth.py` — token/ownership checks and close codes
- `backend/app/api/websocket.py` — the WebSocket route
- `backend/app/core/logging.py` — `RedactSecretsFilter` (JWT/API-key scrubbing)
- `frontend/src/services/websocket.ts` — browser client
- `backend/tests/test_websocket.py` — Module 7 tests (sections 27-32)

## Evidence Retrieval + Claim Extraction

### Purpose

A post-debate analysis layer that (1) extracts examinable claims from a
completed debate's messages and (2) retrieves external search results for
selected claims. Analysis is explicitly triggered over HTTP; it is never part
of the live debate WebSocket flow.

> **Important limitation:** Evidence retrieval does not determine whether a
> claim is true or false. Results are neutral search results; no verdict,
> confidence score or fact-check is produced (that is the future fact
> verification module).

### Claim extraction flow

1. `POST /api/v1/debates/{debate_id}/claims/extract` (owner only) loads the
   debate's persisted messages (ordered by round/turn) or returns 400 when the
   debate has no messages.
2. `ClaimExtractionService` builds a strict JSON prompt and calls the **shared
   LLM provider abstraction** (no direct Groq SDK usage, none of the six debate
   agents are involved).
3. Raw output is parsed defensively: markdown fences stripped, first JSON array
   extracted, every item validated with Pydantic (`message_id` must exist,
   claim non-empty, `claim_type` normalized to
   `factual/opinion/prediction/definition/other`, unknown types become `other`).
   Malformed output raises a clear application error (HTTP 502) and never
   creates corrupt records.
4. Claims are persisted with `debate_id`, `message_id`, `agent_id` (taken from
   the original message), `text`, `claim_type` and a `position` for stable
   ordering. Extraction completion is recorded per message, including empty
   results. Successful batches commit independently and retries process only
   missing messages without duplicating stored claims.

### Evidence retrieval flow

1. `POST /api/v1/claims/{claim_id}/evidence/retrieve` (ownership derived
   claim → debate → user) takes the claim text as the search query (trimmed,
   capped at 300 characters, max 5 results).
2. The configured `EvidenceProvider` (from the provider factory) is called; the
   first implementation is **Tavily** (`app/evidence/tavily.py`) using the
   server-side `TAVILY_API_KEY`. Responses are normalized to
   `{title, url, snippet, source_name, relevance_score}` so no other code ever
   depends on Tavily's raw response format.
3. Results are persisted in the `evidence` table. Stored evidence is returned
   as-is on later requests (no repeated provider calls); `GET .../evidence`
   only reads PostgreSQL and never calls the provider.
4. Missing API key → 503, provider failure/timeout/malformed payload → 502 with
   a safe detail message (never any key material or stack traces).

### Database entities

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `claims` | Extracted claims | `debate_id` → `debates`, `message_id` → `debate_messages`, `agent_id` → `agents` (all CASCADE), `text`, `claim_type` (enum), `position`, `created_at` |
| `evidence` | Stored search results | `claim_id` → `claims` (CASCADE), `title`, `url`, `snippet`, `source_name`, `relevance_score`, `position`, `retrieved_at` |

Migration: `backend/alembic/versions/004_claims_evidence.py` (upgrade +
downgrade).

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/debates/{debate_id}/claims/extract` | Extract + persist claims (400 empty debate, 404 not owner, 502 LLM failure) |
| GET | `/api/v1/debates/{debate_id}/claims` | Claims with agent names, ordered by round/turn/position |
| POST | `/api/v1/claims/{claim_id}/evidence/retrieve` | Search + persist (404 not owner, 503 not configured, 502 provider failure) |
| GET | `/api/v1/claims/{claim_id}/evidence` | Stored evidence only (no provider call) |

### Environment variables

```
EVIDENCE_PROVIDER=tavily      # provider factory selector (supported: tavily)
TAVILY_API_KEY=               # server-side only, backend/.env — never in frontend/Git
SERPAPI_API_KEY=              # reserved for a future provider
```

### Tavily setup

1. Create an API key at app.tavily.com.
2. Put it in `backend/.env` as `TAVILY_API_KEY=tvly-...` (the real key stays
   server-side; `.env.example` documents the variable with an empty value).
3. Restart the backend. Without a key the retrieval endpoint answers 503 with
   "Evidence provider is not configured" and the frontend shows that state.

### Published fact-checks (Google Fact Check Tools API)

Google Fact Check **complements** Tavily (it never replaces it). For each
selected factual claim the analysis pipeline runs, in order:

1. claim extraction → 2. **Google Fact Check search** → 3. Tavily web search
→ 4. evidence stored per claim with a relevance score → 5. LLM verification
over all stored evidence → 6. final verdict (regenerated when evidence changed).

- Client: `app/evidence/google_fact_check.py` calls
  `GET https://factchecktools.googleapis.com/v1alpha1/claims:search` with
  `query` (whitespace-normalized claim text, ≤300 chars), `languageCode`
  and `pageSize`. The key is sent in the `X-Goog-Api-Key` header, never in
  the URL, logs or API responses, and never reaches the frontend.
- Each `claimReview` becomes an `evidence` row with `source_type =
  'google_fact_check'`, `publisher`, `external_rating` (the publisher's
  textual rating), `claim_reviewed`, `claimant`, `review_date`, the review URL
  and `retrieved_at`. Web results keep `source_type = 'web'`. A partial
  unique index prevents storing the same fact-check twice for a claim
  (migration `013_google_fact_checks.py`; no data is deleted).
- Identical claim texts share one request; at most
  `GOOGLE_FACT_CHECK_CONCURRENCY` requests run at once. A claim is searched
  once; failures are retried on the next analysis run.
- **External rating ≠ MAVES verdict.** The verification prompt labels
  fact-checks as a publisher's rating of the claim *they* reviewed and asks
  the model to check it is the same statement; the verdict prompt states that
  external ratings never override MAVES's verification. "No matching
  published fact-check found" is a neutral state, never "false".
- Missing key, invalid key, permission error, quota (429), timeout or outage:
  recorded as a warning in `analysis_status.fact_check` and on the claim
  (`claims.fact_check_status = unavailable | failed`); Tavily and verification
  still run and the UI shows the warning.
- New fact-checks re-verify the affected claims and regenerate the verdict
  (its evidence snapshot changes), so the verdict is never left stale.

Setup:

1. In Google Cloud Console, create or select a project, then enable
   **Fact Check Tools API** (APIs & Services → Library).
2. Create an API key (APIs & Services → Credentials). Restrict it to the
   Fact Check Tools API.
3. Put it in `backend/.env` as `GOOGLE_FACT_CHECK_API_KEY=...` (optional:
   `GOOGLE_FACT_CHECK_LANGUAGE`, `_TIMEOUT_SECONDS`, `_MAX_RESULTS`,
   `_CONCURRENCY`), run `alembic upgrade head`, and restart the backend.

Tests (`python -m tests.test_fact_check`) mock HTTP with `httpx.MockTransport`
and never use a real key; `tests/__init__.py` blanks the key for every suite.

### Frontend

The debate detail page gains a **Claims** section after the transcript:
"Extract Claims" runs extraction and refreshes the list; each claim shows the
agent name, claim text and type badge, plus a "Retrieve Evidence" button whose
stored results render under the neutral heading "Retrieved sources" (title
link opening safely in a new tab, source/domain, snippet, URL). Loading, empty
and error states are handled per section so a failed analysis never breaks the
transcript or the live debate.

### How to test

```bash
python -m tests.test_claims   # mocked LLM + mocked Tavily HTTP; no API keys needed
```

### Key files

- `backend/app/models/claim.py`, `backend/app/models/evidence.py` — models
- `backend/alembic/versions/004_claims_evidence.py` — migration
- `backend/app/evidence/base.py` — `EvidenceProvider` interface + errors
- `backend/app/evidence/tavily.py` — Tavily provider (httpx)
- `backend/app/evidence/factory.py` — provider factory (`EVIDENCE_PROVIDER`)
- `backend/app/services/claim_extraction.py` — LLM extraction + robust parsing
- `backend/app/services/claim_service.py` — extraction/evidence persistence + ownership
- `backend/app/api/claims.py` — the four endpoints
- `frontend/src/services/claims.ts` — frontend API client
- `backend/tests/test_claims.py` — Module 8 tests

## Fact Verification + Claim Evaluation

**Purpose:** evaluate already-extracted claims against already-retrieved
evidence and store a structured, evidence-based result per claim. This module
is about claim evaluation only - it never judges the debate, the agents, or
anyone's personality.

**Important:** The verification system evaluates claims against retrieved
evidence. It does not provide an absolute guarantee of truth.

### Verification flow

1. `POST /api/v1/claims/{claim_id}/verify` loads the claim (ownership:
   user -> debate -> claim) and its stored evidence rows.
2. Evidence exists -> the shared LLM provider receives a constrained
   evaluation prompt (claim + evidence snippets only) and returns structured
   JSON: verdict, confidence, explanation, evidence_summary.
3. The response is validated (controlled verdict/confidence enums, non-empty
   explanation) and checked so every URL it mentions matches stored evidence.
   Invalid or fabricated results are rejected (502) and never persisted.
4. No evidence -> a structured `insufficient_evidence` result is stored
   directly, without calling the LLM or the search provider.
5. The result is persisted: one current row per claim, re-verification
   updates it (unique `claim_id`).

### Verification statuses

| Verdict | Meaning |
|---------|---------|
| `supported` | The retrieved evidence is consistent with the claim |
| `contradicted` | The retrieved evidence directly conflicts with the claim |
| `insufficient_evidence` | No/ambiguous/irrelevant evidence, or sources conflict unresolved |

Confidence: `low` | `medium` | `high`. Verdicts deliberately avoid
true/false: they describe what the retrieved evidence indicates.

### How evidence is used

Only evidence already stored in the `evidence` table (Module 8) is used. The
verification endpoints never call Tavily or any search provider, the LLM may
not invent sources/URLs/statistics, and each result records the
`evidence_ids` it considered so the evaluation stays traceable to the
sources shown in the UI.

### API endpoints

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/v1/claims/{claim_id}/verify` | Runs/refreshes the evaluation (404 not owner, 502 unusable LLM output or provider failure) |
| GET | `/api/v1/claims/{claim_id}/verification` | Reads the stored result only, never the LLM (404 when never verified) |

### Database model

`claim_verifications`: `id`, `claim_id` (FK -> claims, CASCADE, unique),
`verdict` (`claim_verdict_enum`), `confidence`
(`verification_confidence_enum`), `explanation`, `evidence_summary`,
`evidence_ids` (JSON list), `created_at`, `updated_at`. Migration
`005_claim_verification` (upgrade/downgrade verified).

### Frontend

Each claim card in the Claims section gains a "Verify Claim" button and an
"Evidence Evaluation" block: verdict badge (emerald Supported / red
Contradicted / slate Insufficient Evidence), confidence, concise
explanation, optional evidence summary, and a disclaimer that the result is
not an absolute guarantee of truth. Stored results reload with the page
(database read), errors render per claim, and the retrieved sources remain
inspectable beneath the verdict.

### How to test

```bash
python -m tests.test_verification   # all mocked (LLM mocked, no Groq/Tavily keys needed)
```

### Limitations

- Verdicts reflect only the evidence retrieved for the claim; missing
  evidence yields `insufficient_evidence`, never a truth judgement.
- Live Tavily search still requires `TAVILY_API_KEY`; without it,
  verification evaluates whatever evidence rows exist (usually none).
- LLM evaluation output that is malformed or cites un-stored sources is
  rejected rather than persisted.

### Key files

- `backend/app/models/claim_verification.py` — model
- `backend/alembic/versions/005_claim_verification.py` — migration
- `backend/app/services/verification_service.py` — prompt, parsing, validation, source checks
- `backend/app/services/claim_service.py` — verify/get orchestration + ownership
- `backend/app/schemas/claim.py` — `ClaimVerificationResponse`
- `backend/app/api/claims.py` — the two verification endpoints
- `frontend/src/services/claims.ts` + `frontend/src/pages/DebateDetail.tsx` — UI
- `backend/tests/test_verification.py` — Module 9 tests

## Fallacy Detection + Debate Quality Analysis

**Purpose:** detect logical/rhetorical fallacies in debate messages and
evaluate argument quality with structured 0-10 scores. Analysis judges the
argument's reasoning only - never speakers, positions, or the truth of the
topic.

**Important:** Fallacy detection does not determine whether a claim is true
or false. Argument quality scores measure reasoning quality and do not
represent absolute truth. A fallacy flag marks a flaw in reasoning, not a
false claim; quality scores describe how well an argument is constructed and
are analytical reference points only.

### Fallacy detection flow

1. `POST /api/v1/debates/{debate_id}/fallacies/analyze` loads every message of
   the debate (ownership: user -> debate) and runs detection sequentially per
   message; `POST /api/v1/messages/{message_id}/fallacies/analyze` handles a
   single message.
2. Each call sends the message (with speaker role and neighbouring context)
   to the shared LLM provider with a controlled-vocabulary prompt that
   prefers `no_fallacy` over speculative labels (anti-over-detection) and
   judges the reasoning, not the speaker or side.
3. Output is validated: only controlled types, severity `low|medium|high`,
   confidence strictly 0-1 (bools rejected), bounded explanation/evidence
   span. Invalid output is rejected with 502 and never persisted.
4. Duplicate protection: re-analysis replaces each message's stored rows
   (delete + insert) only on explicit reanalysis. Successful stored results are
   otherwise reused. Clean `no_fallacy` results have an ID and timestamp too.
5. Each successful message commits independently. A batch reports individual
   failures and can retry them without losing successful analyses.

### Fallacy vocabulary (controlled)

| Type | Meaning |
|------|---------|
| `ad_hominem` | Attacking the speaker instead of the argument |
| `straw_man` | Misrepresenting an opponent's position |
| `false_dilemma` | Presenting only two options when more exist |
| `slippery_slope` | Assuming a chain of extreme consequences |
| `appeal_to_authority` | Citing authority outside its competence |
| `appeal_to_emotion` | Substituting emotion for reasoning |
| `hasty_generalization` | Broad conclusion from too few cases |
| `circular_reasoning` | Conclusion used to support itself |
| `red_herring` | Diverting to an irrelevant topic |
| `false_cause` | Wrong causal link (post hoc, etc.) |
| `bandwagon` | "True because many believe it" |
| `loaded_question` | Question smuggling an unproven premise |
| `tu_quoque` | Dismissing criticism with "you too" |
| `cherry_picking` | Selective evidence that ignores relevant contrary evidence |
| `no_fallacy` | Explicit persisted outcome: no clear fallacy detected |

Severity (`low`/`medium`/`high`) describes how much the fallacy undermines
the reasoning - it never means the underlying claim is false. Confidence is
0-1.

### Argument evaluation flow

1. `POST /api/v1/messages/{message_id}/evaluation` loads the message
   (ownership: user -> debate -> message) and passes its argument, plus any
   stored claims, verification verdicts and evidence titles, to the shared
   LLM provider.
2. Evidence context is REFERENCE ONLY: the evaluation may lean on stored
   results but never re-verifies, re-searches or invents facts; without
   stored context the call runs on the argument alone.
3. Output is validated: five scores (logical soundness, evidence use,
   relevance, effectiveness, overall) each 0-10 plus a bounded explanation.
   Invalid output is rejected with 502.
4. Upsert: one row per message (unique `message_id`), re-evaluation replaces
   the stored result - repeated runs never duplicate rows.

### API endpoints

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/v1/debates/{debate_id}/fallacies/analyze` | Analyze all messages (404 not owner, 502 provider failure) |
| GET | `/api/v1/debates/{debate_id}/fallacies` | Stored rows only, never the LLM |
| POST | `/api/v1/messages/{message_id}/fallacies/analyze` | Single message (404 unknown/not owner) |
| POST | `/api/v1/messages/{message_id}/evaluation` | Run/refresh quality evaluation (upsert) |
| GET | `/api/v1/debates/{debate_id}/evaluations` | Stored evaluations only, never the LLM |

### Database model

- `fallacies`: `id`, `debate_id`/`message_id`/`agent_id` (FK -> CASCADE,
  indexed), `fallacy_type` (`fallacy_type_enum`), `severity`
  (`fallacy_severity_enum`), `confidence` (float), `explanation`,
  `evidence_span`, `created_at`; unique (`message_id`, `fallacy_type`).
- `argument_evaluations`: `id`, `debate_id`/`message_id`/`agent_id`
  (FK -> CASCADE, indexed), five float scores (0-10), `explanation`,
  `created_at`; unique (`message_id`).

Migration `006_fallacies_evaluations` (upgrade -> downgrade -> upgrade
round-trip verified).

### Frontend

Each transcript message gains "Analyze Argument" and "Evaluate Argument"
buttons with per-message loading states. Analysis results render as a
fallacy block (type/severity/confidence badges, explanation, evidence span,
plus the reasoning-only disclaimer; or "No clear fallacy detected." when the
model returns `no_fallacy`) and a quality block (versioned criterion scores plus
overall `X/10`, explanation, plus the scores-are-not-truth disclaimer).
Stored results reload with the page (database read), errors render per
message without breaking the transcript, and WebSocket/live behaviour is
untouched (HTTP-only feature).

### How to test

```bash
python -m tests.test_fallacy   # all mocked (LLM mocked, includes regression suites)
```

### Limitations

- Detection vocabulary is fixed to the controlled list above; the model may
  return `no_fallacy` for anything it cannot justify, and borderline calls
  belong to the model, not a rigid heuristic.
- Live analysis needs a working LLM provider (Groq key); provider failures
  surface as 502 per request and leave stored results untouched.
- `no_fallacy` is persisted explicitly. An empty `GET .../fallacies` means no
  successful checks are stored; it must not be interpreted as fallacy-free.
- Scores are analytical references for comparing arguments within a debate;
  they never assert that a claim is true or false.

### Key files

- `backend/app/models/fallacy.py`, `backend/app/models/argument_evaluation.py` — models
- `backend/alembic/versions/006_fallacies_evaluations.py` — migration
- `backend/app/services/fallacy_detection.py` — detection prompt, parsing, validation
- `backend/app/services/argument_evaluation.py` — evaluation prompt, parsing, validation
- `backend/app/services/argument_analysis_service.py` — ownership, loop, persistence, evaluation orchestration
- `backend/app/schemas/fallacy.py`, `backend/app/schemas/evaluation.py` — responses
- `backend/app/api/fallacies.py`, `backend/app/api/evaluations.py` — the five endpoints
- `frontend/src/services/analysis.ts` + `frontend/src/pages/DebateDetail.tsx` — UI
- `backend/tests/test_fallacy.py` — Module 10 tests

## Debate Judge + Overall Scoring

### Purpose

After a debate completes, the judge scores every participating agent (agents
that actually posted messages) against a fixed seven-dimension rubric,
computes an overall debate score, and decides the outcome. Scoring
configuration lives in exactly one place: `backend/app/services/judge_rubric.py`.
The LLM never chooses weights and never decides the winner; it only supplies
per-dimension values and qualitative commentary, while all arithmetic runs in
plain deterministic Python.

### Scoring formula

Seven dimensions per agent, each 0-10, weights sum to 1.0:

| Dimension | Weight | Source |
|-----------|--------|--------|
| Logical Soundness | 0.20 | LLM (Module 10 evaluations supplied as context) |
| Evidence Quality | 0.20 | LLM (only when retrieved evidence rows exist) |
| Factual Support | 0.15 | Deterministic from stored claim verdicts |
| Relevance | 0.15 | LLM (Module 10 evaluations supplied as context) |
| Effectiveness | 0.10 | LLM (Module 10 evaluations supplied as context) |
| Completeness | 0.10 | LLM |
| Fallacy Risk | 0.10 | Deterministic from stored fallacy rows (penalty) |

```
Fallacy Quality = 10 - Fallacy Risk
Agent Score = 0.20*Logical + 0.20*Evidence + 0.15*Factual + 0.15*Relevance
            + 0.10*Effectiveness + 0.10*Completeness + 0.10*FallacyQuality
```

- Only the final displayed score is rounded (two decimals); intermediate
  values stay full precision.
- **Factual support (deterministic)**: over the agent's claim verdicts,
  `supported` contributes +1, `contradicted` -1, `insufficient_evidence` 0
  (neutral by design — insufficient evidence never counts for or against
  truth). Score = `(ratio + 1) / 2 * 10`. No verification rows → dimension
  unavailable.
- **Fallacy risk (deterministic)**: `sum(severity_weight * confidence) /
  message_count * 5` for the agent's fallacy rows (low=1, medium=2, high=3),
  capped at 10; higher = riskier, inverted to quality before weighting. No
  fallacy rows → dimension unavailable (reported as a limitation, never a
  fabricated low-risk score).

### Data-availability policy

- A dimension whose underlying data does not exist is `null` (unavailable),
  its weight is excluded, and the remaining weights are renormalized; every
  unavailable dimension is reported as a judgment limitation.
- `insufficient_evidence` verdicts stay neutral; `contradicted` verdicts
  reduce factual support.
- The evidence-quality dimension is only scored when retrieved evidence rows
  exist for the debate.
- Only agents that posted messages are scored (one card per participant).

### Winner selection policy

- Overall debate score = mean of the participants' final (rounded) scores.
- `data_sufficient` requires at least one of: claim verdicts, fallacy
  analyses, or argument evaluations for the debate.
- Inconclusive: data not sufficient, or fewer than two participating agents
  (no manufactured winner in either case).
- Winner: top-two gap >= `JUDGE_MIN_SCORE_GAP` (Settings, default 0.5).
- Otherwise: tie (no winner).

### API endpoints

- `POST /api/v1/debates/{debate_id}/judge` — validates (owner, completed,
  has messages), asks the LLM once, computes the deterministic score and
  persists one row per debate. Idempotent: an existing judgment is returned
  without calling the LLM again. Errors: 400 (not completed / no messages),
  404 (missing or foreign debate), 502 (LLM/provider failure or invalid LLM
  output).
- `GET /api/v1/debates/{debate_id}/judgment` — stored judgment, database
  read only, never calls the LLM. 404 when no judgment exists.

Example:

```bash
curl -X POST http://localhost:8000/api/v1/debates/<debate_id>/judge \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json"

curl http://localhost:8000/api/v1/debates/<debate_id>/judgment \
  -H "Authorization: Bearer <token>"
```

### Persistence

Single `debate_judgments` row per debate (unique `debate_id`) holding
`overall_score`, `outcome`, `winner_agent_id`, `summary`, the exact
`scoring_rubric` snapshot used (weights, formula, min gap, bands, sources),
per-agent dimension cards with unavailable markers, and limitations.

### Frontend

Judge section on the debate detail page (completed debates only): a Judge
Debate button (re-entry safe while judging), overall score, outcome badge
(winner / tie / inconclusive), winner name, summary, per-agent cards with all
seven dimensions (Unavailable when `null`), strengths, weaknesses, qualitative
assessments, per-agent limitations, judgment-level limitations, and a
disclaimer that scores measure argument quality against the rubric and do not
establish objective truth.

### How to test

- `docker exec -e PYTHONPATH=/app agentsystem-backend-1 python -m tests.test_judge`
  covers the weight configuration, deterministic dimensions, rounding, the
  outcome policy, parsing, all endpoint behaviors (auth, ownership, status,
  no messages, data insufficiency, persistence/idempotency, LLM failures) and
  runs every earlier suite as regression.

### Limitations

- The judge evaluates argument quality from stored debate data; it does not
  establish objective truth, and a declared winner is a rubric
  recommendation, not proof of factual correctness.
- Missing analysis data shrinks the rubric via renormalization and is always
  reported; inconclusive outcomes are preferred over manufactured winners.
- LLM failures surface as 502 and leave no partial row; a stored judgment is
  never recomputed (re-judging requires deleting the row).

### Key files

- `backend/app/models/judge.py` — `DebateJudgment` model
- `backend/alembic/versions/007_debate_judgments.py` — migration
- `backend/app/services/judge_rubric.py` — single weight configuration + deterministic scoring
- `backend/app/services/debate_judge_service.py` — context loading, prompt, parsing, orchestration, persistence
- `backend/app/schemas/judge.py`, `backend/app/api/judge.py` — response schema + endpoints
- `frontend/src/services/judge.ts`, `frontend/src/pages/DebateDetail.tsx` — UI
- `backend/tests/test_judge.py` — Module 11 tests + full regression

## Analytics Dashboard

### Purpose

A results dashboard (`/analytics`, formerly `/dashboard`) that helps the authenticated user understand
debate activity, compare participating agents, review factual-support verdicts,
analyze argument quality and inspect final judgment results. Every figure is
computed from the user's own stored records (debates, messages, claims,
verifications, fallacies, evaluations, judgments). No hardcoded statistics,
mock production data or invented accuracy metrics exist anywhere in the
implementation.

### Dashboard features

- **Key performance indicators** — total / completed / running / failed debates,
  total messages, extracted claims, claims with completed verification, debates
  with a generated judgment, completion rate (only when total > 0).
- **Debate activity** — debates created per UTC day as a dependency-free inline
  SVG bar chart with an exact per-day count list; time range selector
  (7 / 30 / 90 / 365 days, default 30).
- **Debate status distribution** — labelled counts + bars for the modelled
  lifecycle states only: pending, running, completed, failed, cancelled.
- **Claim verification analytics** — verdict counts (supported / contradicted /
  insufficient evidence) with share-of-verified percentages, confidence-level
  distribution, and an explicit note that unverified claims are **not** counted
  as insufficient evidence.
- **Agent performance comparison** — per-agent average of stored Module 11
  judgment scores (the same rubric, no second formula), judged appearances,
  per-dimension averages and saved strengths/weaknesses. Agents without judged
  appearances show as Unavailable, never as 0.
- **Argument quality and fallacy analytics** — stored Module 10 fallacy type /
  severity counts, evaluated vs not-yet-analyzed message counts and average
  evaluation scores per dimension.
- **Recent debates** — paginated table (topic link to the existing debate
  detail page, creation date, status, agent/round/message counts, verification
  and judgment flags); judged debates get a "View results" link.
- **Debate results detail** — reuses the existing debate detail page's judge
  section (Module 11) instead of duplicating it.

### Analytics endpoints

All routes require authentication and only aggregate the caller's own debates.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/analytics/summary` | KPI counts + status distribution |
| GET | `/api/v1/analytics/debate-activity?days=30` | Debates per UTC day (`days` 1-365) |
| GET | `/api/v1/analytics/claim-verification` | Verdict + confidence distributions |
| GET | `/api/v1/analytics/agent-performance` | Judgment score aggregates per agent |
| GET | `/api/v1/analytics/argument-quality` | Fallacy + evaluation aggregates |
| GET | `/api/v1/analytics/recent-debates?page=1&page_size=10` | Paginated recent debates (`page_size` 1-50) |

Example:

```bash
curl http://localhost:8000/api/v1/analytics/summary -H "Authorization: Bearer <token>"
curl "http://localhost:8000/api/v1/analytics/debate-activity?days=30" -H "Authorization: Bearer <token>"
```

Invalid query values (`days=0`, `page=0`, `page_size=51`, ...) answer 422.

### Metric definitions and counting rules

| Metric | Source | Rule |
|--------|--------|------|
| Debate counts | `debates.status` | Persisted status only; a debate with messages is not automatically "completed". |
| Completion rate | completed / total | `null` when the account has no debates. |
| Message counts | `debates_messages` | One row per posted message. |
| Extracted claims | `claims` | Rows in the claims table. |
| Verified claims | `claim_verifications` | A claim is verified only when its verification row exists (1:1 unique constraint; joins cannot inflate). |
| Debates judged | `debate_judgments` | One judgment row per debate; agent cards inside a judgment do not multiply the count. |
| Activity buckets | `debates.created_at` | Grouped by UTC calendar day (`created_at AT TIME ZONE 'UTC'`); empty days are zero-filled. |
| Agent performance | `debate_judgments.agent_scores` | Averages of stored Module 11 final scores; dimension averages skip unavailable (`null`) values. |
| Fallacy statistics | `fallacies` | Detection counts exclude clean results; coverage includes explicit persisted no-fallacy checks. |
| Not-yet-analyzed messages | `debates_messages` − distinct evaluated `message_id` | Falls back to `null` when the account has no messages. |

### Authentication and ownership

Every endpoint uses the existing JWT dependency and filters every query by the
authenticated user's `user_id`; another user's debates, claims or judgments are
never returned. No new database table was added and no migration was created —
analytics are computed from existing persisted records with grouped SQL
aggregation (no N+1 queries, no Redis caching).

### Chart dependencies

None. Charts are small inline SVG bar charts with per-bar `<title>` tooltips,
plus visible exact counts and text summaries beside every visualization, so
nothing depends on color alone. No chart library was installed.

### How to test

- `docker exec -e PYTHONPATH=/app agentsystem-backend-1 python -m tests.test_analytics`
  covers summary counts, status distribution, activity grouping and range
  filtering, claim-verdict counts (unverified excluded from verdicts), agent
  score aggregation, missing judgment / fallacy / evaluation records, empty
  accounts, pagination and query validation, authentication, ownership
  isolation, duplicate-join inflation, and runs every earlier suite as
  regression.
- Frontend: `npx tsc --noEmit && npm run build` in `frontend/`.

### Limitations

- Stored claim-verification verdict distributions are **not** equivalent to
  independently measured factual accuracy; they only reflect what the
  evidence-check step stored for your claims.
- Fallacy statistics cover stored detections only; a message without a row may
  simply never have been analyzed, and the dashboard says so.
- Agent performance is only as good as the judgments that exist; with zero
  judgments the section reports an unavailable state instead of inventing
  scores.
- Activity grouping uses UTC days; accounts near midnight boundaries see UTC
  dates, not local ones.

### Key files

- `backend/app/schemas/analytics.py` — response schemas + shared metric vocabularies
- `backend/app/services/analytics_service.py` — aggregation queries and counting rules
- `backend/app/api/analytics.py` — the six endpoints
- `frontend/src/services/analytics.ts` — typed API client
- `frontend/src/pages/Analytics.tsx` — analytics UI (loading / success / empty / partial / error states)
- `backend/tests/test_analytics.py` — Module 12 tests + full regression

## UI Design System and Navigation

### Purpose

Module 13 standardizes the entire frontend onto one shared design system and
one consistent navigation shell, and hardens the page-to-API integration
states (loading, empty, error, offline, unauthorized) so every page behaves
predictably.

### Design tokens

Tokens live in `frontend/src/index.css` under `@layer components` (Tailwind
v3.4.10, no extra dependencies). The utilities layer still wins, so variants
like `btn-primary px-3` keep working:

| Token class | Purpose |
|-------------|---------|
| `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-ghost` | All actions |
| `.input`, `.label`, `.field-hint` | Forms (label + input always paired with `htmlFor`/`id`) |
| `.card`, `.card-title`, `.section-title`, `.page-title` | Page and section structure |
| `.badge` | Status pills (tone via extra Tailwind classes) |
| `.alert-error`, `.alert-info` | Inline notices |

### Shared components

- `frontend/src/components/ui/AppHeader.tsx` — the single header used by every
  authenticated page: brand link, primary nav (Home / My Debates / New
  Debate / Agents / Dashboard) with `aria-current="page"` active states
  (`end` matching so `/debates/new` does not light up "My Debates"), wrapped
  on narrow viewports, user email, Logout.
- `frontend/src/components/ui/PageShell.tsx` — consistent max-width layout
  wrapper (`sm` = 3-column pages, `md` = dashboard width).
- `frontend/src/components/ui/ErrorBanner.tsx` — `role="alert"` error block
  with optional retry callback.
- `frontend/src/components/ui/LoadingState.tsx` — `role="status"` spinner
  used by page loads, `ProtectedRoute` and inline fetch states.

### Integration and error handling

- `apiErrorMessage(err, fallback)` in `frontend/src/services/api.ts` is the
  single place that turns `ApiClientError` detail / network `TypeError` into
  user-facing text; all pages use it (no per-page copies, no swallowed
  failures). Expected 404s (missing judgment, verification, evidence) render
  explicit "nothing yet" states rather than errors.
- Auth: 401 responses clear the token and broadcast an auth-change event;
  `ProtectedRoute` keeps the session across refreshes and redirects
  unauthenticated or invalid/expired tokens to `/login` without loops.
- Debate detail: live WebSocket transcript merges (never replaces) persisted
  HTTP data with sequence guards against stale async responses; round
  messages without a stored round still render (orphan rounds); start button
  disables while starting (double-click guard); `aria-live` on live panels;
  external links restricted to http/https.
- Responsive: 375px viewport verified with no horizontal overflow on Home,
  Dashboard, New Debate and Debate list; heading hierarchy fixed (one
  `h1` per page, no skipped levels); visible focus rings on all controls.

### How to test

- `npx tsc --noEmit && npm run build` in `frontend/`.
- End-to-end (playwright-core + Edge, frontend on `:5173`):
  `dashboard.e2e.js`, `judge.e2e.js`, `analysis.e2e.js`, `report.e2e.js` and
  `integration.e2e.js` (register → create → execute → claims/evidence/
  verify → analyze → judge → analytics → refresh/ownership/logout/invalid
  token → 375px layout) under `C:\Users\ASUS\AppData\Local\Temp\opencode\e2e`.
- Backend regression (unchanged by Module 13):
  `python -m tests.test_analytics`.

### Key files

- `frontend/src/index.css` — design tokens
- `frontend/src/components/ui/{AppHeader,PageShell,ErrorBanner,LoadingState}.tsx`
- `frontend/src/services/api.ts` — API client + shared error mapping
- `frontend/src/App.tsx`, `frontend/src/context/AuthContext.tsx`,
  `frontend/src/components/ProtectedRoute.tsx` — routes, session, guards

## Topic-Aware Automatic Agent Selection

### Purpose

Auto selection no longer picks every active agent. The topic the user types
is analyzed and a focused set of relevant experts is recommended, each with a
short reason, before the debate is created.

### How recommendations are generated

1. `POST /api/v1/debates/recommend-agents` takes `{ "topic": "..." }`
   (authenticated, topic validated up to 1000 characters).
2. The backend loads the **active core agents from the database** (ids, roles,
   names, descriptions) — nothing is hardcoded on the frontend.
3. `AgentSelectionService` sends the topic plus that agent roster to the
   existing Groq provider abstraction with a structured-JSON instruction and
   temperature 0; the response must be
   `{"agents": [{"id": "...", "role": "...", "reason": "..."}]}`.
4. Every entry is validated against the roster: unknown/inactive roles are
   dropped, ids must match the supplied agent, duplicates are removed, and
   fewer than two usable entries counts as a failure. Only agents actually
   stored in the database can ever be returned.

Response:

```json
{
  "topic": "...",
  "selection_mode": "auto",
  "selection_source": "llm",
  "agents": [{ "id": "…uuid…", "name": "Doctor", "role": "doctor", "reason": "…" }]
}
```

### How the fallback works

If the provider fails, times out, or returns malformed/unusable JSON (or too
few valid entries), the service uses a deterministic selector instead of
failing and instead of "every agent":

- each active agent is scored by keyword hits between the topic and a
  per-role lexicon (e.g. `hospital/diagnos/patient` → doctor,
  `inflation/tax/market` → economist);
- agents with matches are returned, most matches first, each reason quoting
  the matched keywords plus the agent's description;
- if fewer than two matched, the selection is padded with balanced
  perspectives (`analyst`, then `ethicist`);
- if fewer than two active core agents exist at all, a clear 400 error is
  returned — agents are never fabricated.

`selection_source` in the response tells the client whether `"llm"` or
`"fallback"` produced the result (the UI shows an offline-selector notice for
fallback results).

### Frontend behavior (New Debate page)

- Manual mode: unchanged checkbox selection and validation.
- Auto mode: recommendations load after a 600 ms topic debounce with a
  loading state, per-agent reasons, recommended agents pre-checked (locked)
  in the agent grid, and a Refresh action; switching to Manual pre-fills the
  recommendation so it can be edited.
- Guard rails: no API call per keystroke, at most one request in flight
  (a topic change during a request is queued, and an older response never
  overwrites a newer one), clearing the topic clears stale recommendations,
  and submitting in Auto mode is blocked until fresh recommendations for the
  current topic exist.
- On creation, the recommended role ids are sent through the existing
  `POST /api/v1/debates` flow; the backend re-validates them (still active,
  core, known) so the stored `debate_agents` rows match exactly what was
  shown — creation itself never calls the LLM.

### How to test

- Backend: `docker exec -e PYTHONPATH=/app agentsystem-backend-1 python -m tests.test_agent_selection`
  — 16 tests (domain quality, auth, validation, dedupe, inactive/unknown
  rejection, fallback on failure, creation persistence, manual mode, no-LLM
  creation) with a mocked provider; no Groq key needed. It is also chained
  from `python -m tests.test_analytics` (full regression).
- Frontend: `npx tsc --noEmit && npm run build`; E2E
  `agent_selection.e2e.js` (debounce, loading, error + retry, stale-response
  and duplicate-request guards, manual prefill, live recommendation → debate
  creation with matching stored agents).

### Limitations

- Selection quality depends on the LLM's judgment; **no formal accuracy
  benchmark has been conducted**, only example-topic spot checks.
- The fallback is a keyword heuristic, not a semantic model: unusual phrasing
  may yield a generic (but still minimum, still relevant-by-description)
  pair, and the UI marks fallback results explicitly.
- Recommendations are per-request; there is no server-side caching, so
  repeated refreshes call the provider again.
- Agent capabilities come from the seeded `description` texts; adding new
  roles works without algorithm changes, but their lexicon entries are what
  drive the fallback.

### Key files

- `backend/app/services/agent_selection.py` — service, LLM validation,
  deterministic fallback
- `backend/app/api/debates.py` — `POST /api/v1/debates/recommend-agents`
- `backend/app/schemas/debate.py` — `RecommendAgentsRequest` /
  `RecommendAgentsResponse`
- `backend/app/services/debate_service.py` — AUTO creation branch
  (`select_auto_agents`)
- `frontend/src/services/debates.ts` — `recommendAgents()` + types
- `frontend/src/pages/DebateNew.tsx` — auto-mode UI, debounce/guards
- `backend/tests/test_agent_selection.py` — backend suite

## Application Layout, Final Verdict, Demo Login and PDF Report

### Navigation

All signed-in pages share `PageShell`: a fixed sidebar on large screens and a
top bar with a toggleable menu below the `lg` breakpoint (no horizontal page
scroll at 375px). Sections: **Dashboard**, **New Debate**, **My Debates**,
**Reports**, **Analytics**, **Agent Playground** and **Profile**, plus Sign
out. The neutral palette is a navy-tinted `gray` scale defined once in
`frontend/tailwind.config.js`, so every page shares it. Every number on the
Dashboard and Analytics pages comes from the backend.

### Debate results page

Header: topic, status badge, panel size and **Download PDF Report**
(completed debates; failed/cancelled debates offer a partial report; pending
and running debates show the button disabled with an explanation). Below it,
tabs that only appear when their data can exist (`#hash` keeps the tab in the
URL, e.g. `/debates/{id}#verdict`):

1. **Overview** - configuration, start / live state (WebSocket connecting,
   connected, reconnecting, unavailable), agents, and a verdict-at-a-glance
   card.
2. **Final Verdict** - the answer to the debate question (see below).
3. **Agent Arguments** - each agent's statements grouped per agent.
4. **Claims & Verification**, 5. **Evidence**, 6. **Fallacy Detection**,
   7. **Argument Quality** - stored analysis with the existing actions.
8. **Agent Performance** - the rubric judge (scores, bars, winner/tie/
   inconclusive), explicitly labelled as *not* the debate's answer.
9. **Transcript**, 10. **Methodology**.

### Final debate verdict vs. agent performance

These answer different questions and are stored separately:

| | Final verdict (`debate_verdicts`) | Agent performance (`debate_judgments`) |
|---|---|---|
| Question | What is the answer to the debate question, and which position does the evidence support? | Which agent argued best under the rubric? |
| Output | `position` (`supports` / `opposes` / `mixed` / `inconclusive`), one-sentence `answer`, `preferred_position`, `summary`, `reasoning`, supporting arguments, counterarguments (with impact), `confidence` + `confidence_basis`, limitations, unresolved questions, evidence snapshot | per-agent scores, winner / tie / inconclusive |
| Endpoint | `POST /api/v1/debates/{id}/verdict[?regenerate=true]`, `GET .../verdict` | `POST .../judge`, `GET .../judgment` |

`app/services/verdict_service.py` sends the debate question, optional
context, transcript and the stored claims with their stored verifications to
the existing Groq provider (via `get_llm_provider`). The judge's scores and
winner are never included, so the best-performing agent is never equated with
the correct answer. Server-side guards:

- **No invented citations.** The model may cite only the numbered stored
  claims it was given; unknown references are dropped and reported as a
  limitation. Responses expand each citation to the stored claim, its stored
  verification and its stored sources (titles + URLs).
- **Inconclusive when the evidence is missing.** If no stored claim is
  `supported` or `contradicted`, the position is forced to `inconclusive`
  (no preferred position) with an explanation to verify claims first.
- **Confidence is capped by evidence coverage.** `low` when nothing is
  decisively verified; at most `medium` unless at least 3 claims and half of
  all claims are supported/contradicted. `confidence_basis` records why.
- Established evidence (verified claims), agent opinions (attributed
  arguments) and the system's synthesized assessment are shown separately in
  the UI and the PDF.

Generating is idempotent (one row per debate); `regenerate=true` replaces it,
for example after verifying more claims, and a failed regeneration keeps the
stored verdict. Errors: 404 (missing / other user's debate), 400 (debate not
completed / no messages), 502 (provider failure; nothing stored).

Optional **debate context** (`context`, max 2000 characters) is stored on the
debate, passed to every agent prompt as "Background provided by the user" and
included in the verdict prompt.

### Demo login

For demonstrations the login page can offer **Fill Demo Credentials** (fills
the email and password; you still press Login) and **Login with Demo
Account** (fills and submits the normal login form).

1. Set in `backend/.env` (placeholders are in `.env.example`):
   `DEMO_ACCOUNT_ENABLED=true`, `DEMO_ACCOUNT_EMAIL=...`,
   `DEMO_ACCOUNT_PASSWORD=...` (at least 8 characters).
2. Create (or reset the password of) the account once:
   `docker compose exec backend python seed.py --demo`.
3. Reload the login page - the demo buttons appear.

How it works and why it is safe:

- `GET /api/v1/auth/demo` returns `{enabled, email, password}` only while the
  feature is enabled, configured **and** the account exists; otherwise
  `{"enabled": false}` and the login page shows "Demo login is not configured
  on this server".
- The account is created only by the explicit `seed.py --demo` step
  (`ensure_demo_account` refuses when the feature is off) - never implicitly
  at startup, in production or otherwise.
- It is an ordinary user: bcrypt-hashed password, normal `POST /auth/login`,
  normal JWT, normal ownership checks. It sees only debates it created.
  `GET /auth/me` returns `is_demo: true`, which the sidebar and Profile page
  show as a "Demo account" badge/notice.
- Credentials are configured on the server, not baked into the frontend
  bundle, and are held only in React state on the login page (never in
  localStorage/sessionStorage).
- **The demo password is public by design** while the feature is on. Use a
  dedicated throwaway account, never a real user or admin, and remember that
  everyone using the demo login shares its debates.
- **To disable:** set `DEMO_ACCOUNT_ENABLED=false` (or remove the variables)
  and restart the backend; optionally delete the demo user.

### PDF report endpoint

`GET /api/v1/debates/{debate_id}/report.pdf`

- **Auth:** `Authorization: Bearer <JWT>` (the same token as every other API
  call). Missing/invalid token -> 401. Debates owned by another user -> 404
  (indistinguishable from a missing debate, so ids cannot be probed).
  Malformed id -> 422.
- **Response:** `200`, `Content-Type: application/pdf`,
  `Content-Disposition: attachment; filename="maves-{topic-slug}-{id8}.pdf"`
  (ASCII only, slug capped at 48 chars). CORS exposes `Content-Disposition`
  so the frontend can reuse the server filename.
- **Errors:** JSON `{"detail": ...}` with generic messages; internal
  exceptions are logged, never returned.
- **Any status is allowed.** A debate that is not `completed` or has no stored
  final verdict produces a report with a highlighted **PARTIAL REPORT**
  notice on the cover explaining why.

Architecture (`backend/app/services/report_service.py`):

- `build_report_data` (async, read-only) loads the debate through the
  ownership-checked `debate_service` helpers, then the stored rounds,
  transcript, claims + verifications + evidence, fallacies, evaluations and
  judgment. **It never calls the LLM, the evidence provider or any other
  external service** and writes nothing.
- `render_report_pdf` (sync, run via `asyncio.to_thread`) renders with
  ReportLab into an in-memory buffer: a navy cover page (title, topic, final
  verdict headline, date, status, agents, debate id), then numbered sections
  - Executive Summary, **Final Debate Verdict**, Strongest Supporting and
  Opposing Arguments (with cited stored claims and source links), Confidence
  and Uncertainty, Debate Overview, Agent Participation and Arguments,
  **Agent Performance** (labelled as separate from the verdict), Key Claims
  and Verification, Evidence Sources (clickable http(s) links plus the URL
  list), Fallacy and Argument Analysis (only when stored), Debate Transcript
  (grouped by round and speaker, flows over as many pages as needed) and
  Limitations and Methodology. Every page after the cover has a MAVES header;
  every page has a "Page N of M" footer. Missing parts are stated as
  unavailable.
- Text is escaped before it reaches ReportLab's markup parser, so topics,
  messages and source titles cannot inject formatting.

### Downloading a report

1. Sign in and open **Reports** (or a finished debate's page).
2. Click **Download PDF** / **Download PDF Report**. The button shows
   "Preparing PDF..." and is disabled until the request finishes; failures
   show an error banner with Retry.
3. The browser saves `maves-<topic>-<id>.pdf`.

The frontend uses `requestBlob` in the shared API client
(`frontend/src/services/api.ts`) - the token travels in the `Authorization`
header, never in the URL - and the `useReportDownload` hook
(`frontend/src/hooks/useReportDownload.ts`), which saves the blob via a
temporary object URL and revokes it afterwards.

From a shell:

```bash
curl -H "Authorization: Bearer $TOKEN" -o report.pdf http://localhost:8000/api/v1/debates/<debate_id>/report.pdf
```

### Dependency

`reportlab==4.2.5` (pure Python wheels; no system packages). It is in
`backend/requirements.txt`, so `pip install -r requirements.txt` or
`docker compose build backend` installs it.

### New environment variables and migration

- `DEMO_ACCOUNT_ENABLED`, `DEMO_ACCOUNT_EMAIL`, `DEMO_ACCOUNT_PASSWORD`
  (optional; see Demo login). No other new variables.
- Migration `008` adds `debates.context` and the `debate_verdicts` table:
  `docker compose exec backend alembic upgrade head`.

### Limitations

- The PDF uses the built-in Helvetica font, which only covers Latin-1.
  Accented Latin text is folded (e.g. "Cafe"), typographic quotes and dashes
  become ASCII, and characters outside Latin-1 (CJK, emoji, Cyrillic, ...)
  render as `?`. Embedding a Unicode TTF would lift this.
- The report reflects the database at download time; re-running the judge
  changes the next report.

### Tests

- `python -m tests.test_verdict` (7 tests): evidence-supported conclusion,
  conflicting evidence (confidence capped), insufficient evidence (forced
  inconclusive), missing optional analyses, no judgment / winner is not the
  verdict (the judge summary never reaches the prompt), regenerate +
  failures (502 stores nothing, failed regeneration keeps the old verdict,
  401/404/400, unauthorized requests never reach the LLM) and debate
  context reaching agent prompts.
- `python -m tests.test_demo` (5 tests): disabled by default, misconfigured
  or missing account stays hidden, login through the normal endpoint with
  `is_demo`, wrong password -> normal 401, ownership still enforced,
  password rotation, protected routes stay protected.
- `python -m tests.test_report` (14 tests): valid PDF for a judged debate,
  persisted data in the content, no-judgment and missing-analysis states,
  PARTIAL REPORT labelling (unjudged and failed debates), transcript section,
  a long transcript spanning several pages without leaking markdown, the
  final verdict leading the report ahead of agent performance,
  long/Unicode text, safe filename from an unusual topic, 401 / 404 (other
  user's debate) / 422, and a guard that fails if any LLM or evidence
  provider is touched. Chained into `python -m tests.test_analytics`.
- Frontend: `npm run build` (runs `tsc`). There is no frontend unit-test
  framework in this repository.

### Key files

- `backend/app/services/report_service.py`, `backend/app/api/debates.py`,
  `backend/tests/test_report.py`
- `backend/app/models/verdict.py`, `backend/app/schemas/verdict.py`,
  `backend/app/services/verdict_service.py`, `backend/app/api/verdict.py`,
  `backend/alembic/versions/008_debate_context_verdicts.py`,
  `backend/tests/test_verdict.py`
- `backend/app/services/demo_account.py`, `backend/app/api/auth.py`,
  `backend/seed.py`, `backend/tests/test_demo.py`
- `frontend/src/components/{VerdictPanel,AgentArguments}.tsx`,
  `frontend/src/services/verdict.ts`, `frontend/src/pages/{Login,Profile}.tsx`
- `frontend/src/components/ui/{AppHeader,PageShell,PageHeader,StatusBadge}.tsx`
- `frontend/src/hooks/useReportDownload.ts`
- `frontend/src/pages/{Dashboard,DebateList,DebateNew,DebateDetail,Reports,Analytics}.tsx`

## LLM Provider Failures, Retries and Resume

### What failed (October 2026 incident)

A debate failed in round 2 with "the language model provider did not
respond". The provider had in fact answered `200 OK` in about 1.7 s: the
configured model `openai/gpt-oss-20b` is a reasoning model, and with the
per-turn limit of `max_tokens=1024` it spent 1022 tokens on hidden reasoning
(`finish_reason=length`) and returned no text. The longer round-2 prompt
(round-1 transcript included) made it reason more than in round 1. The
generic error mapping then mislabeled it as a non-response.

### Fixes

- Per-turn budget is now `DEBATE_MAX_RESPONSE_TOKENS` (default 2048).
- `GroqProvider` retries an empty answer caused by an exhausted budget with a
  doubled `max_tokens` (at most twice, capped by
  `LLM_MAX_OUTPUT_TOKENS_CEILING`).
- Provider errors are classified (`app/llm/base.py`):
  - transient, retried with exponential backoff + jitter, bounded by
    `LLM_MAX_RETRIES`: rate limits (Retry-After honored; waits longer than
    `LLM_RETRY_MAX_DELAY_SECONDS` (60 s), e.g. an exhausted daily quota, fail
    fast). Groq's on-demand tier limits `openai/gpt-oss-20b` to 8,000 tokens
    per minute and asks for ~20 s waits when it is exceeded; the cap was 20 s
    at first, which made those waits fail a debate turn instead of retrying,
    5xx, timeouts, connection errors;
  - permanent, never retried: invalid API key (401/403), unknown or
    decommissioned model, bad request, context length exceeded.
  The SDK's own retries are disabled so the two layers never multiply.
  Retrying is safe: a message is persisted only after its generation
  succeeds.
- The failure message names the round, turn and agent plus a safe reason
  (e.g. "Round 2, turn 1 (Doctor): The language model returned an empty
  answer ..."). It is returned by the API (502, or 504 for timeouts), sent
  over the WebSocket and stored in `debates.failure_reason` (migration 009).
  Logs record the error class, status and provider error code only - never
  keys or payloads.

### Which rate limit was hit

Groq enforces several independent limits per model. The provider parses
Groq's error body and reports which one:

| Kind | Example (on-demand tier, `openai/gpt-oss-20b`) | Behaviour |
|---|---|---|
| TPM - tokens per minute | 8,000 | retried after Retry-After (up to 60 s) |
| RPM - requests per minute | per tier | retried after Retry-After (up to 60 s) |
| TPD - tokens per day | 200,000 | **not retried**; message shows usage and when the request fits again |
| RPD - requests per day | 1,000 | **not retried** |

Groq admits a request only if its *requested* tokens (input + `max_tokens`)
fit what remains. Near an exhausted daily quota a small request without
`max_tokens` (the Agent Playground) can still succeed while a debate turn
(`max_tokens` = `DEBATE_MAX_RESPONSE_TOKENS`) is refused - same key, model and
configuration. The log line shows `limit=TPD used=... of=... requested=...
retry_after=... remaining-tokens=...` (never the organisation id or key).
A 3-round, 4-agent debate with judgment and verdict needs roughly 60-90k
tokens, so on the 200k/day tier only a few full debates fit per day.

Each Groq model has its own daily quota. When `openai/gpt-oss-20b` was
exhausted, the deployment was switched to `GROQ_MODEL=openai/gpt-oss-120b`
(same provider and key, separate quota, same reasoning-model behaviour).
To see which models a key can use and whether a debate-sized request fits,
list `client.models.list()` and send one tiny request with `max_tokens=2048`.

### Resuming a failed debate

`POST /api/v1/debates/{id}/resume` (or **Resume from failed turn** on the
debate page) keeps completed rounds and every stored message and generates
only the missing turns of the interrupted round onward. The unique
`(round_id, turn_number)` constraint guarantees no duplicate turns. Failed
debates never have a judgment or verdict (both require `completed`), so
nothing stale survives. The page shows "N of M rounds completed", the stored
reason, and no final verdict until the debate completes.

### Debate states, interruption and safe re-runs

| State | Meaning |
|---|---|
| `pending` | Created, queued, not started ("Not started" in the UI) |
| `running` | Executing in a worker that keeps a live Redis heartbeat |
| `failed` | Stopped by an error, or **interrupted** (worker stopped mid-run); `failure_reason` says which |
| `completed` | Every round finished |

- **Interrupted debates.** A debate runs inside the request that started it,
  so a server restart used to leave it `running` forever. The worker now
  refreshes `maves:debate:{id}:heartbeat` (TTL `DEBATE_HEARTBEAT_TTL_SECONDS`,
  default 90 s) while it executes. When a `running` debate is read and has no
  heartbeat and no update for one more TTL, it is atomically marked `failed`
  with an "interrupted" reason, its unfinished round is marked failed, and a
  `debate_failed` WebSocket event is sent. If Redis is unreachable, a debate
  with no update for `DEBATE_STALE_AFTER_SECONDS` (30 min) is treated the
  same way. Open debate pages poll the status every 30 s while a debate runs
  elsewhere, so the Resume action appears without a reload.
- **Start and resume are atomic.** Both use a conditional
  `UPDATE ... WHERE status = <expected>` to claim the debate, so double
  clicks or concurrent requests run it once; the other request gets 409.
- **No stale conclusions.** Resuming removes any judgment or verdict for the
  debate (none should exist, since both require `completed`) before new
  messages are generated.

## Structured Debate Turns

Agents answer each turn with a small JSON object instead of a free essay,
validated by `StructuredTurn` (`app/orchestration/turn_format.py`):

| Field | Meaning |
|---|---|
| `position` / `position_changed` | Current position; flag when it was revised |
| `main_argument` | One concise argument |
| `rebuttal_to` | `{ref, argument}` - the earlier turn being answered, cited as `R<round>-<Agent>` |
| `reasoning` | Why the argument supports the position |
| `factual_claims` | Checkable statements, kept apart from reasoning and opinion |
| `evidence_references` | Sources the agent names; shown as "not yet verified" |
| `concession` | A valid opposing point acknowledged |
| `recommendation`, `uncertainties` | What should be done; what remains unclear |

**Round phases** (`round_manager.py`, adapted to any round count):
round 1 = opening (position, main argument, key assumption, what evidence
would change it); middle rounds = rebuttal (challenge one specific argument
not yet addressed, agree or disagree with reasons, concede the strongest
opposing point, no artificial disagreement); last round = closing (answer the
strongest remaining objection, correct earlier mistakes, strongest defensible
conclusion, open uncertainties). A 2-round debate is opening + closing.

**Prompt rules:** specialist perspective, no greetings or speeches, no
repetition (each agent also sees its own earlier turns), engage with what
others actually said, never invent statistics/studies/URLs, revising a
position is allowed, agreeing is allowed. Word limits per phase:
`DEBATE_OPENING_WORD_LIMIT` (200), `DEBATE_REBUTTAL_WORD_LIMIT` (180),
`DEBATE_CLOSING_WORD_LIMIT` (160). Earlier turns are passed to the next
speaker compactly (position, main argument, rebuttal target, concession).

**Storage:** `debate_messages.structured` (JSON, migration 010) holds the
validated turn; `rebuttal_to` is resolved server-side to the real earlier
message (`message_id`) - an unknown or self reference is never linked.
`content` keeps a readable rendering, so claim extraction, fallacy
detection, judge, verdict, transcript export and the PDF work unchanged, and
debates stored before this change still display. If a model ignores the
format, its actual text is stored unstructured (no extra LLM call, nothing
invented).

**Transcript UI:** each turn shows agent and role, round, a colour-coded
type (opening / rebuttal / closing), position, the main argument, a
"Responding to" link that jumps to the referenced turn, a concession box,
factual claims, agent-cited evidence, uncertainties and an expandable full
response.

## Judgment Quality (rubric v2)

### Why every agent used to get the same score (e.g. 5.09)

Not a default or hardcoded value. In debates without claim verification,
fallacy checks or evaluations, three data-driven dimensions (evidence
quality, factual support, fallacy risk) were unavailable, and the judge LLM
gave every agent the same integer scores for the rest (logical 3, relevance
8, effectiveness 5, completeness 5). The renormalized formula then yields
(0.2*3 + 0.15*8 + 0.1*5 + 0.1*5) / 0.55 = 5.09 for everyone. The judge could
not tell agents apart because each message reached it cut to its first 600
characters, with no information about who rebutted whom. Separately, the
ranking rule refused to rank without optional analyses and showed that as
"Not enough stored debate data to produce a verdict".

Complete input alone was not enough: live tests with `openai/gpt-oss-20b`
still produced identical scores for four agents when all of them were scored
in one answer (the model copies one score card). The judge therefore scores
**one agent per call**: the target agent in full, the others compactly as
context. Live result on the same debate: 8.17 / 7.92 / 7.83 / 7.42 instead of
5.09 for everyone. The summary is written from the computed scores, so no
extra call is made.

### Fixes

- **One judge call per agent** (N calls for N agents).
- **Complete judge input:** structured turns field by field (legacy
  free-text turns up to 1,500 characters within a 26k budget), turn
  references (`R2-Lawyer`), debate format and context, per-agent
  responsiveness signals (linked rebuttals, concessions), retrieved evidence
  titles, and explicit "not run" lines for missing analyses.
- **Rubric v2** (`app/services/judge_rubric.py`, stored with every judgment
  as `scoring_rubric.version`):

  | Dimension | Weight | Source | Meaning |
  |---|---|---|---|
  | Logical soundness | 20% | LLM | Premises support the conclusion |
  | Evidence quality | 15% | LLM (only with retrieved evidence) | Specific, relevant, attributable evidence |
  | Factual support | 15% | Stored verdicts | Supported vs contradicted claims |
  | Responsiveness | 15% | LLM + rebuttal links | Engages the strongest opposing arguments, concedes valid points |
  | Relevance | 10% | LLM | Stays on the question |
  | Clarity | 10% | LLM | Concise, structured, no repetition |
  | Completeness | 5% | LLM | Covers the key aspects |
  | Fallacy risk | 10% | Stored fallacy rows (penalty) | Severity x confidence |

  Unavailable dimensions are excluded and the rest renormalized. The judge
  must score each agent on its own turns with one decimal, cite turn
  references, and may give equal scores only when it says why; equal final
  scores are flagged in the limitations.
- **Ranking without optional analyses:** best performer when the top gap is
  at least `JUDGE_MIN_SCORE_GAP`, otherwise tie; "No ranking" only with fewer
  than two speakers. Missing analyses become limitations.
- **Re-run and staleness:** `POST /judge?regenerate=true` replaces the
  judgment (a failed re-run keeps the old one). Judgments store the counts of
  messages, claims, verifications, evidence, fallacies and evaluations they
  used; `stale: true` is returned (and shown) when those changed. Verdicts do
  the same against their evidence snapshot.

### States on the results page

| Situation | What is shown |
|---|---|
| Debate failed / interrupted | Failure reason + Resume; no verdict, no judgment (API 400) |
| Debate pending or running | Verdict and performance unavailable until completed |
| Completed, not yet judged / no verdict | Empty state with the generate button (API 404) |
| Judge or verdict call failed | Error banner with retry; nothing stored (API 502) |
| Completed, verdict with evidence | Position, reasoning, evidence basis (partial / substantial) |
| Completed, insufficient evidence | Inconclusive **with the reason**: no verified evidence, conflicting evidence, or incomplete evidence |

**Confidence** is a qualitative label - low (little or no verified or
conflicting evidence), medium (some claims verified), high (most claims
verified and consistent) - capped by evidence coverage. It is not a
calibrated probability.

## Dynamic AI Specialist Roles

**Flow.** In automatic mode the New Debate page calls
`POST /api/v1/debates/recommend-agents` with `include_specialists: true`
(topic, optional context, mode). `TopicAnalysisService`
(`app/services/topic_analysis.py`) makes one structured call through the
existing provider (Groq JSON mode, one bounded re-ask on invalid output) and
returns the main and secondary domains, key questions, a suggested panel
size, built-in picks with reasons, and proposed AI specialist roles. The page
shows all of it; each specialist can be unticked before the debate is
created. Manual selection is never extended.

**Validation** (server-side, on proposal and again at creation):

- Schema and limits: name (plain job title, 3-60 chars), domain, subdomain,
  expertise (20-400), debate objective, up to 5 instructions (200 chars
  each), up to 6 capabilities.
- Safety: rejects text that tries to override instructions, mentions secrets,
  credentials, tools, code execution, URLs or configuration, and any claim
  of licensing or human-expert status.
- Deduplication against built-ins ("Economist" is rejected; "Energy
  Economist" is kept) and between specialists; relevance to the topic
  analysis; budget (`DEBATE_MAX_AGENTS` 6, `DEBATE_MAX_SPECIALISTS` 3).
- Rejected proposals are returned with reasons and shown on the page.

**Lifecycle.** Each accepted specialist becomes a debate-scoped `agents` row
(`source='dynamic'`, `debate_id`, validated `definition` with provenance;
migration 011). This keeps messages, claims and judgments referentially
intact and makes the debate reproducible; the rows are deleted with their
debate and never appear in agent lists or other debates. Built-in agents are
unchanged (`source='builtin'`).

**Runtime.** `DynamicSpecialistAgent` uses the same shared LLM provider with a
fixed template: it states that the role is an AI perspective, not a licensed
professional or human expert; inserts the definition as data; and always ends
with the integrity rules (evidence vs opinion, no invented sources, state
uncertainty, follow the debate protocol). Specialists follow the same round
structure, evidence verification and judging rubric as built-ins, and are
labelled "AI specialist role" in the UI and PDF.

**Fallbacks.** If the analysis fails, the endpoint returns the previous
built-in recommendation (LLM or keyword fallback) without specialists. If the
model names fewer than two usable built-ins, the panel is completed by the
keyword selector while valid specialists are kept.

## Cost, Performance and Observability

- **Budgets at creation:** at most `DEBATE_MAX_AGENTS` agents and
  `DEBATE_MAX_TURNS` turns (agents x rounds); estimated tokens
  (turns x (2000 + `DEBATE_MAX_RESPONSE_TOKENS`)) must stay under
  `DEBATE_TOKEN_BUDGET`. Violations return 400 with the numbers.
- **Per-call budgets:** debate turn 2048, per-agent judge 6000, verdict
  6000, topic analysis 4000 output tokens (empty answers from reasoning
  models escalate up to 8192).
- **No duplicate LLM work:** start/resume are atomic; judge and verdict are
  idempotent unless `regenerate=true`; identical topic analyses are served
  from Redis for `RECOMMENDATION_CACHE_TTL_SECONDS`.
- **Correlation IDs:** every response carries `X-Request-ID` (a valid
  incoming one is reused) and every log line has `req=<id>`.
- **LLM call log** (one line per generation, no prompt text, no keys):
  `llm_call provider=groq model=... outcome=ok|error [category=...]
  duration_ms=... attempts=... escalations=... agent=... debate=... round=... turn=...`.
  Secrets are additionally scrubbed by the existing redaction filter.

## Evaluation

See [docs/EVALUATION.md](docs/EVALUATION.md) for the end-to-end procedure,
the per-debate checklist and the recorded live findings.
`python -m scripts.evaluate_topics` prints the panel MAVES would choose for
the evaluation topics (real provider, read-only).

## CURRENTLY IMPLEMENTED

- Project foundation
- PostgreSQL
- Redis
- FastAPI
- React frontend (minimal)
- SQLAlchemy (async)
- Alembic migrations
- User/Debate/Agent models
- Authentication (JWT)
- Password hashing
- Protected routes
- Health checks with DB/Redis status
- Core agent seeding (6 agents)
- CORS configuration
- LLM provider abstraction
- Groq provider
- BaseAgent
- Economist Agent
- Lawyer Agent
- Doctor Agent
- Scientist Agent
- Ethicist Agent
- Analyst Agent
- Agent factory/registry
- Role-based system prompts
- Authenticated debate creation
- Agent selection (manual and automatic)
- Debate-agent relationships (`debate_agents`)
- Debate configuration and initial status
- Debate ownership (per-user debates)
- Debate list and debate details frontend pages
- Debate orchestration
- Debate rounds
- Sequential agent turns
- Debate transcript persistence
- Live debate streaming (WebSocket events for a running debate)
- WebSocket authentication with ownership checks (4401/4403/4404)
- Live transcript, round and speaker updates on the debate detail page
- Claim extraction from completed debate messages (shared LLM provider)
- Claims and evidence persistence (`claims`, `evidence` tables)
- Evidence provider abstraction with Tavily as the first provider
- Claims + retrieved sources UI on the debate detail page
- Claim verification against stored evidence (`claim_verifications` table)
- Evidence Evaluation verdicts (supported / contradicted / insufficient_evidence) with confidence
- Verify Claim button + verdict display on the debate detail page
- Fallacy detection on debate messages (controlled vocabulary, severity + confidence)
- Per-message fallacy results with "No clear fallacy detected" handling (`fallacies` table)
- Argument quality evaluation (logical soundness / evidence / relevance / effectiveness / overall, 0-10)
- Analyze Argument + Evaluate Argument buttons and result blocks on the debate detail page
- Debate judge: deterministic 7-dimension rubric with documented weights and renormalization for unavailable data
- Winner / tie / inconclusive outcome policy with configurable minimum score gap (`JUDGE_MIN_SCORE_GAP`)
- Judge endpoint + stored judgment read endpoint (one judgment per debate, idempotent)
- Judge UI section on the debate detail page (scores, outcome, per-agent cards, limitations)
- Analytics page (`/analytics`, formerly `/dashboard`) with KPIs, activity chart, status distribution and recent debates
- Analytics API: summary, debate activity, claim verification, agent performance, argument quality, recent debates (owner-scoped SQL aggregation)
- Claim-verification analytics that keep unverified claims separate from insufficient-evidence verdicts
- Agent performance comparison from stored Module 11 judgments (unavailable, never zero, for agents without appearances)
- Shared UI design system: tokens (buttons, inputs, cards, badges, alerts) in `index.css` + shared `AppHeader` / `PageShell` / `ErrorBanner` / `LoadingState` components
- Unified navigation with active states (`aria-current`), responsive wrapping header and Logout on every authenticated page
- Consistent client error handling: shared `apiErrorMessage`, `role="alert"` error banners, expected-404 empty states, no swallowed failures
- Auth hardening: refresh-safe session, expired/garbage token cleanup, no redirect loops
- Debate detail integration fixes: merge (not replace) of WebSocket + HTTP data with stale-response guards, orphan-round rendering, start double-click guard, `aria-live` live regions
- Accessibility and responsive pass: label/control pairing, focus rings, single `h1` heading hierarchy, 375px layout without horizontal overflow
- Topic-aware automatic agent selection: `POST /api/v1/debates/recommend-agents` (LLM + validated against DB agents, deterministic keyword fallback), `AgentSelectionService`
- New Debate Auto mode: debounced topic analysis, recommended agents with reasons, loading/error/refresh states, stale-response and duplicate-request guards, recommendation prefill for Manual mode
- AUTO debate creation persists the validated recommendation (creation never calls the LLM); empty `agent_ids` fall back to the deterministic topic-aware selector instead of "every agent"
- Debate results page restructured into the eight documented sections (Overview → Final Conclusion → Agent Comparison → Claims and Verification → Evidence Sources → Fallacy and Argument Analysis → Transcript → Limitations and Methodology) with conditional in-page section navigation
- Downloadable PDF conclusion report: `GET /api/v1/debates/{debate_id}/report.pdf` (reportlab, in-memory, stored data only, owner-only, topic-slug filename, partial-report labelling, full transcript) + download buttons on the results and Reports pages
- App-wide layout: sidebar navigation (Dashboard, New Debate, My Debates, Reports, Analytics, Agent Playground), overview Dashboard, searchable/filterable My Debates, stepped New Debate form

## NOT YET IMPLEMENTED

- LangGraph workflow
- Confidence scoring
- Custom agents


## November 2026 backend and analysis audit

See [the initial audit](docs/MAVES_INITIAL_AUDIT.md) and [the implementation and verification report](docs/MAVES_IMPLEMENTATION_REPORT.md) for migrations, endpoint changes, the rubric reconciliation, isolated test commands, live service verification, and current limitations. Compose now loads the root `.env`; the frontend uses Node 24 and Vite 8. Apply Alembic migrations before serving an upgraded database. Do not run legacy test fixtures against the application database.
