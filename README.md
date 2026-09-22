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
| POST | `/api/v1/agents/test` | Test a single role-based agent (Bearer token) |
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

## NOT YET IMPLEMENTED

- Multi-agent debate orchestration
- Debate rounds
- LangGraph workflow
- WebSockets
- Live transcript
- Evidence retrieval
- Claim extraction
- Fact verification
- Fallacy detection
- Argument evaluation
- Judge AI
- Debate results
- Results dashboard
- Analytics
- PDF reports
- Custom agents
