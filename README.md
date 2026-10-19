# Multi-Agent LLM Based Argument Verification and Evidence-Based Decisions

> Final Year B.Tech CSE (Data Science) Project — Academic Year 2026–27

---

## Current Architecture

```
frontend → backend → PostgreSQL
                   → Redis
```

## Technologies

- **Backend:** Python 3.11, FastAPI, SQLAlchemy (async), Alembic, Pydantic
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
| `/debates` | List the authenticated user's debates |
| `/debates/new` | Create a debate (topic, manual/auto selection, agent cards, tags, mode, rounds, evidence toggle) |
| `/debates/{id}` | Debate details: topic, status, configuration, participating agents |

All three are protected routes and use the centralized API client (environment-based API URL + automatic Bearer token). Client-side validation mirrors the backend rules, but backend validation stays authoritative.

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
   ordering. Extraction runs **at most once per debate** — when claims already
   exist they are returned as-is, so repeated requests cannot duplicate claims
   and do not spend another LLM call.

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
   (delete + insert), so repeated runs never accumulate duplicates. Only real
   fallacies are persisted - `no_fallacy` results are returned with
   `id: null` and not stored.
5. All messages of one request commit in a single transaction: either the
   whole analysis is stored or nothing is.

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
| `no_fallacy` | No clear fallacy detected (not persisted) |

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
model returns `no_fallacy`) and a quality block (four dimension scores plus
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
- `no_fallacy` is never persisted, so an empty `GET .../fallacies` means
  "nothing detected", not "not analyzed".
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

A results dashboard (`/dashboard`) that helps the authenticated user understand
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
| Fallacy statistics | `fallacies` | Stored detections only; "no fallacy" results are never persisted, so absence is never presented as clean. |
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
- `frontend/src/pages/Dashboard.tsx` — dashboard UI (loading / success / empty / partial / error states)
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
  `dashboard.e2e.js`, `judge.e2e.js`, `analysis.e2e.js` and
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
- Analytics dashboard page (`/dashboard`) with KPIs, activity chart, status distribution and recent debates
- Analytics API: summary, debate activity, claim verification, agent performance, argument quality, recent debates (owner-scoped SQL aggregation)
- Claim-verification analytics that keep unverified claims separate from insufficient-evidence verdicts
- Agent performance comparison from stored Module 11 judgments (unavailable, never zero, for agents without appearances)
- Shared UI design system: tokens (buttons, inputs, cards, badges, alerts) in `index.css` + shared `AppHeader` / `PageShell` / `ErrorBanner` / `LoadingState` components
- Unified navigation with active states (`aria-current`), responsive wrapping header and Logout on every authenticated page
- Consistent client error handling: shared `apiErrorMessage`, `role="alert"` error banners, expected-404 empty states, no swallowed failures
- Auth hardening: refresh-safe session, expired/garbage token cleanup, no redirect loops
- Debate detail integration fixes: merge (not replace) of WebSocket + HTTP data with stale-response guards, orphan-round rendering, start double-click guard, `aria-live` live regions
- Accessibility and responsive pass: label/control pairing, focus rings, single `h1` heading hierarchy, 375px layout without horizontal overflow

## NOT YET IMPLEMENTED

- LangGraph workflow
- Confidence scoring
- PDF reports
- Custom agents
