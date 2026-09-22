# Multi-Agent LLM Based Argument Verification and Evidence-Based Decisions
### Structured Multi-Agent Debate & Verification Platform

> **Project type:** Final Year B.Tech CSE (Data Science)  
> **Academic Year:** 2026–27  
> **Primary goal:** Build a real, working multi-agent AI debate and argument-verification platform — not a mockup or a simple chatbot.

---

## 1. Project Overview

**Multi-Agent LLM Based Argument Verification and Evidence-Based Decisions** is a web-based multi-agent LLM system that helps a user analyze a complex topic before making a decision.

Instead of asking one LLM for one answer, the system creates a structured debate between multiple AI expert agents. Each expert has a different role and reasoning perspective. The agents generate arguments, challenge opposing arguments, participate in multiple rounds, and use externally retrieved evidence where factual claims need verification.

After the debate, a separate analysis pipeline evaluates the arguments for:

- Logical soundness
- Evidence quality
- Relevance
- Effectiveness
- Factual support
- Logical fallacies
- Counterargument handling

A separate **Judge AI** then evaluates the complete debate and produces an explainable final report containing the strongest and weakest arguments, evidence, detected fallacies, scores, uncertainties, and decision guidance.

The application should help the user make a more informed decision. It should **not** pretend that an LLM can provide an absolutely correct answer.

The project synopsis describes the system as combining multi-agent reasoning, argument analysis, logical fallacy detection, fact verification, and evidence-based decision support. fileciteturn1file0L48-L65

---

# 2. IMPORTANT BUILD INSTRUCTION

If you are an AI coding agent receiving this README, follow these rules:

1. **Build the actual working application.**
2. Do not create only static frontend screens.
3. Do not hard-code fake debate responses as the main implementation.
4. Do not claim that evidence was retrieved if no external source was actually queried.
5. Do not invent citations, URLs, statistics, or facts.
6. Keep LLM providers configurable.
7. Keep evidence providers configurable.
8. Use structured JSON outputs between AI modules wherever possible.
9. Make the debate state persistent and recoverable.
10. Stream debate progress to the frontend in real time.
11. Handle API failures, rate limits, timeouts, malformed LLM responses, and empty search results gracefully.
12. Keep the architecture modular so individual agents, LLM providers, and search providers can be replaced.
13. The application must clearly distinguish:
   - factual claims
   - opinions
   - assumptions
   - evidence
   - model-generated reasoning
   - uncertainty
14. Never force the Judge AI to declare a winner when the evidence is inconclusive.
15. Do not expose private API keys in frontend code.
16. Add proper validation, logging, error handling, tests, and documentation.
17. Prefer PostgreSQL as the main database and Redis for caching/session state.
18. Use **LangGraph as the preferred orchestration framework**. CrewAI can be considered only as an alternative; do not unnecessarily mix both.
19. Build the MVP end-to-end first, then add advanced functionality.
20. Every major feature should be testable independently.

---

# 3. Problem Statement

Traditional LLM applications generally produce a single answer to a complex question. This makes it difficult for users to compare multiple perspectives, identify weaknesses in reasoning, verify factual claims, or recognize logical fallacies.

LLMs can also generate information that sounds convincing while being inaccurate.

The proposed system addresses this by integrating several AI agents with different roles and by evaluating their arguments against external evidence.

The project objectives explicitly include critical argument evaluation, logical fallacy identification, fact checking against other sources, agent questioning/rebuttal, analysis using evidence/logic/relevance/effectiveness, and generation of an organized analytical report. fileciteturn1file0L182-L204

---

# 4. Core User Experience

The user experience should follow this flow:

```text
                    ┌─────────────────────┐
                    │       USER          │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Enter Debate Topic  │
                    └──────────┬──────────┘
                               │
                               ▼
              ┌─────────────────────────────────────┐
              │  EXPERT SELECTION MODE               │
              │  (Auto or Manual — user chooses)     │
              └──────────┬────────────────┴──────────┘
                         │               │
              ┌──────────▼──────┐  ┌─────▼──────────┐
              │ AUTO            │  │ MANUAL         │
              │ Topic Analyzer  │  │ Full agent     │
              │ → suggested     │  │ list, user     │
              │   agents        │  │ picks experts  │
              │ (user confirms  │  │                │
              │  or adjusts)    │  │                │
              └──────────┬──────┘  └─────┬──────────┘
                         │               │
                         ▼               ▼
                    ┌─────────────────────┐
                    │ Select Rounds       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Create Debate       │
                    │ Initialize State    │
                    └──────────┬──────────┘
                               │
                               ▼
              ┌─────────────────────────────────┐
              │      MULTI-AGENT DEBATE         │
              │                                 │
              │ Economist → Lawyer → Scientist  │
              │ → Ethicist → Analyst → ...      │
              │                                 │
              │       Multiple Rounds            │
              │       Rebuttals                  │
              └────────────────┬────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Claim Extraction    │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Evidence Retrieval  │
                    │ & Fact Verification │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Argument Evaluation │
                    │ Fallacy Detection   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      JUDGE AI       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Final Report        │
                    │ + Confidence        │
                    │ + Uncertainty       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Results Dashboard   │
                    │ + PDF Export        │
                    └─────────────────────┘
```

---

# 5. System Architecture

The provided architecture diagram defines six main layers:

1. User Interface
2. FastAPI Backend
3. Role-Based AI Expert Agents
4. Debate & Analysis Engine
5. Data & Storage
6. Analytics Dashboard

The project synopsis also specifies Python 3.11, FastAPI, LangGraph/CrewAI, React.js + TailwindCSS, Git/GitHub, and Docker as the proposed development stack. fileciteturn1file0L213-L229

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 1. USER INTERFACE                                                    │
│                                                                      │
│  Debate Setup  │  Live Debate Transcript  │  Results & Dashboard    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ REST + WebSocket
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. BACKEND - FASTAPI                                                 │
│                                                                      │
│ Request Routing │ Agent Manager │ Debate Orchestrator               │
│ Response Aggregator │ Authentication & API Layer                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. ROLE-BASED AI EXPERT AGENTS                                      │
│                                                                      │
│ Economist │ Lawyer │ Doctor │ Scientist │ Ethicist │ Analyst │      │
│ Custom/Other                                                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. DEBATE & ANALYSIS ENGINE                                         │
│                                                                      │
│ Debate Engine → Argument Evaluation → Fallacy Detection →            │
│ Judge AI & Summary Generator → Final Report & Confidence            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. DATA & STORAGE                                                   │
│                                                                      │
│ PostgreSQL │ Redis │ File/PDF Storage │ Analytics Data               │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 6. ANALYTICS DASHBOARD                                              │
│                                                                      │
│ Debate Overview │ Argument Scores │ Fallacy Distribution             │
│ Agent Performance │ Trends & Insights │ Export Reports              │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 6. Technology Stack

## Backend

- Python 3.11
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- REST API
- WebSockets
- AsyncIO

## Frontend

- React.js
- TailwindCSS
- React Router
- Axios or Fetch
- Recharts or another charting library
- WebSocket client

## Multi-Agent Orchestration

**Preferred:** LangGraph

Responsibilities:

- Agent sequencing
- Shared debate state
- Round management
- Conditional workflow
- Rebuttal routing
- Analysis pipeline
- Judge invocation

## LLM Providers

The synopsis proposes Claude API / GPT-4o for persona-driven argument generation. fileciteturn1file0L243-L250

Implement an abstraction:

```text
LLMProvider
├── OpenAIProvider
└── AnthropicProvider
```

Configuration should determine which provider is active.

Example:

```env
LLM_PROVIDER=openai
LLM_MODEL=<configured-model>
```

Do not hard-code one provider into every agent.

## NLP / Analysis

The synopsis lists:

- spaCy
- Hugging Face Transformers

for NLP/fallacy analysis. fileciteturn1file0L243-L250

Use a hybrid architecture:

```text
LLM reasoning
+
deterministic validation/rules
+
NLP/Transformer analysis
```

Do not rely on one LLM call for every analytical task.

## Evidence Retrieval

The synopsis specifies:

- Tavily Search API / SerpAPI
- Google Fact Check Tools API / WikiCheck API

for evidence and fact verification. fileciteturn1file0L247-L254

Create a common provider interface:

```python
class EvidenceProvider:
    async def search(self, query: str) -> list:
        raise NotImplementedError
```

## Database

- PostgreSQL — primary persistent database
- Redis — cache/session/temporary state

## Reports

- ReportLab and/or WeasyPrint
- PDF export

## Deployment

- Docker
- Docker Compose
- Git
- GitHub

The synopsis identifies Docker for containerized backend services and Git/GitHub for version control/team collaboration. fileciteturn1file0L217-L229

---

# 7. AI Expert Agents

The architecture contains these role-based agents:

```text
Economist
Lawyer
Doctor
Scientist
Ethicist
Analyst
Other / Custom Agents
```

Each agent must have a unique system prompt and domain-specific behavior.

## 7.1 Economist Agent

Focus on:

- Economic impact
- Costs and benefits
- Employment
- Markets
- Incentives
- Productivity
- Financial feasibility
- Distributional effects

Should challenge unsupported economic assumptions.

---

## 7.2 Lawyer Agent

Focus on:

- Laws
- Regulations
- Rights
- Legal constraints
- Compliance
- Policy implications
- Jurisdiction

The agent must distinguish between general legal information and definitive legal advice.

---

## 7.3 Doctor Agent

Focus on:

- Health effects
- Medical evidence
- Public health
- Risks
- Benefits
- Human impact

Medical claims should be treated as evidence-sensitive.

---

## 7.4 Scientist Agent

Focus on:

- Scientific research
- Evidence
- Methodology
- Causality
- Uncertainty
- Experimental results

Should explicitly distinguish correlation from causation.

---

## 7.5 Ethicist Agent

Focus on:

- Ethical implications
- Fairness
- Rights
- Moral principles
- Social consequences
- Conflicting values

The agent should identify value assumptions rather than presenting moral judgments as facts.

---

## 7.6 Analyst Agent

Focus on:

- Cross-domain comparison
- Trade-offs
- Risks
- Decision criteria
- Contradictions
- Overall synthesis

The Analyst must not automatically agree with the majority.

---

## 7.7 Custom Agent

Users/developers should be able to create additional agents.

Example:

```json
{
  "name": "Environmental Expert",
  "role": "environmental analyst",
  "focus": [
    "climate impact",
    "resource usage",
    "environmental risk"
  ]
}
```

---

## 7.8 Automatic Expert Assignment

The system must support **two expert selection modes** controlled by the user:

| Mode | Behavior |
|---|---|
| **Auto** | The system analyzes the topic and automatically suggests the most relevant expert agents. The user can review, accept, or adjust the suggestions before starting. |
| **Manual** | The user picks experts manually from the full agent list. |

### 7.8.1 Auto-Mode Sub-Pipeline

When the user applies the topic, a topic-analysis step runs before agent selection:

```text
User enters topic
      ↓
Topic Analyzer (one lightweight LLM call, configurable)
      ↓
Domain tags extracted (economy, law, health, science, ethics, ...)
      ↓
Relevance score computed per agent role
      ↓
Top agents selected and ordered by relevance
      ↓
Suggested agents returned to the user
      ↓
User accepts suggestions OR manually adjusts the set
      ↓
Create debate with the confirmed agent list
```

### 7.8.2 Topic → Domain → Agent Mapping

The Topic Analyzer assigns domain tags, which map to recommended agents. This mapping is the default heuristic and may be overridden by the LLM's relevance scoring.

```text
Domain tags                          Recommended agents
-----------------------------------  -------------------------------------
economy, finance, tax, budget,       Economist, Analyst
markets, employment, incentives
law, regulation, policy, rights,     Lawyer, Ethicist
legal, compliance, jurisdiction
health, medicine, disease,           Doctor, Scientist
treatment, public health, risk
science, research, technology,       Scientist, Ethicist
climate, environment, data
ethics, morality, fairness,          Ethicist, Analyst
justice, social impact
conflict / trade-off, decision-      Analyst (cross-domain synthesis)
making, cross-domain
mixed / multiple domains             Top 2–4 agents across matched domains
unclear / general                    All six core agents
```

### 7.8.3 Topic Analyzer Output

The analyzer must return structured JSON so the suggestion is explainable to the user:

```json
{
  "domain_tags": ["economy", "employment"],
  "agent_scores": [
    { "agent": "economist", "relevance": 0.94 },
    { "agent": "analyst", "relevance": 0.87 },
    { "agent": "lawyer", "relevance": 0.52 }
  ],
  "suggested_agent_ids": ["economist", "analyst"],
  "reasoning": "Topic concerns employment and market impact, which map to the Economist and Analyst roles."
}
```

### 7.8.4 Rules

- Never force the user to accept the auto suggestion; the user can switch to Manual mode or edit the suggested list.
- Auto mode must not be a hidden magic step — show the suggested agents and the domain tags that produced them.
- If topic analysis fails (LLM error, timeout), fall back to returning all six core agents with a clear note, and never block the user.
- The Topic Analyzer uses the same configurable LLM provider as the agents.
- The chosen mode (`auto` or `manual`) and any generated `domain_tags` must be persisted with the debate for reproducibility.

---

# 8. Agent Interface

All agents should implement the same interface.

Example:

```python
class BaseAgent:
    name: str
    role: str
    system_prompt: str

    async def generate_argument(
        self,
        topic: str,
        round_number: int,
        debate_context: dict,
        evidence: list
    ) -> dict:
        ...
```

The agent should return structured output.

Example:

```json
{
  "agent": "Economist",
  "position": "support",
  "argument": "....",
  "claims": [
    {
      "text": "....",
      "type": "factual",
      "importance": "high"
    }
  ],
  "counterpoints": [
    "...."
  ],
  "confidence": 0.78
}
```

---

# 9. Prompting Rules

Every agent should receive:

```text
TOPIC
YOUR ROLE
CURRENT ROUND
DEBATE OBJECTIVE
PREVIOUS ARGUMENTS
OPPOSING ARGUMENTS
AVAILABLE VERIFIED EVIDENCE
KNOWN UNCERTAINTIES
```

Prompt requirements:

- Do not invent facts.
- Do not invent citations.
- Separate facts from opinions.
- Identify assumptions.
- Address opposing arguments.
- Provide claims that can be verified.
- Acknowledge uncertainty.
- Stay within the assigned expert perspective.
- Do not simply agree with another agent.
- Do not reveal hidden chain-of-thought or private reasoning.
- Return concise, structured reasoning suitable for evaluation.

---

# 10. Debate Modes

Implement at least two modes.

## Mode A — Balanced Debate

Agents receive the topic and independently form positions.

Example:

```text
Round 1:
Economist → Lawyer → Scientist → Ethicist → Analyst

Round 2:
Each agent rebuts selected opposing arguments

Round 3:
Agents refine their position using evidence
```

## Mode B — Pro vs Con

Agents are assigned explicit positions:

```text
PRO:
Economist
Scientist
Analyst

CON:
Lawyer
Ethicist
Other Expert
```

The user should be able to configure the mode.

---

# 11. Debate Orchestrator

The Debate Orchestrator is the central workflow controller.

Responsibilities:

1. Validate the debate request.
2. Create a debate record.
3. Select active agents (from the user's confirmed list; in Auto mode this comes from the `suggest-agents` analysis and any user adjustments).
4. Initialize shared state.
5. Start the first round.
6. Call agents in the configured order.
7. Store each turn.
8. Extract factual claims.
9. Retrieve evidence.
10. Run argument/fallacy analysis.
11. Start subsequent rounds.
12. Provide previous arguments to agents.
13. Generate rebuttals.
14. Evaluate final arguments.
15. Invoke Judge AI.
16. Generate final report.
17. Persist all outputs.
18. Notify the frontend.
19. Mark the debate completed or failed.

---

# 12. Debate State

Use a typed state model.

Example:

```python
class DebateState:
    debate_id: str
    topic: str
    expert_selection_mode: str        # "auto" or "manual"
    domain_tags: list | None          # populated in auto mode
    agents: list
    current_round: int
    total_rounds: int
    turns: list
    claims: list
    evidence: list
    fallacies: list
    evaluations: list
    judge_result: dict | None
    final_report: dict | None
    status: str
```

Possible statuses:

```text
created
initializing
running
verifying
evaluating
judging
completed
failed
cancelled
```

---

# 13. Detailed Debate Workflow

```text
1. User enters topic
        ↓
2. Validate input
        ↓
3. Create debate
        ↓
4. Select agents
        ↓
5. Initialize LangGraph state
        ↓
6. Round 1 argument generation
        ↓
7. Extract claims
        ↓
8. Retrieve external evidence
        ↓
9. Verify claims
        ↓
10. Detect fallacies
        ↓
11. Score arguments
        ↓
12. Round 2 rebuttals
        ↓
13. Re-evaluate claims/arguments
        ↓
14. Round 3 refinement
        ↓
15. Final evaluation
        ↓
16. Judge AI
        ↓
17. Summary generation
        ↓
18. Confidence + uncertainty calculation
        ↓
19. Save final report
        ↓
20. Display results
        ↓
21. Allow PDF export
```

The number of rounds must be configurable.

---

# 14. Argument Evaluation

Do not use only one overall score.

Each argument should be evaluated on:

### Logical Soundness

Does the conclusion reasonably follow from the premises?

### Evidence

Is the argument supported by credible evidence?

### Relevance

Does the argument directly address the topic?

### Effectiveness

Is the argument clear, coherent, and persuasive?

Recommended range:

```text
0–10
```

Example:

```json
{
  "logical_soundness": 8,
  "evidence": 7,
  "relevance": 9,
  "effectiveness": 8,
  "overall": 8.0
}
```

The project literature review specifically states that argument quality should not always be represented by a single score and highlights logical soundness, evidential support, and relevance as separate criteria. fileciteturn1file0L126-L135

---

# 15. Logical Fallacy Detection

Initial supported categories:

- Ad Hominem
- Straw Man
- False Dilemma
- Appeal to Authority
- Appeal to Emotion
- Slippery Slope
- Hasty Generalization
- Circular Reasoning
- False Cause / Post Hoc
- Red Herring
- Bandwagon
- Anecdotal Fallacy
- Equivocation
- Loaded Question

Example output:

```json
{
  "fallacy": "False Dilemma",
  "severity": "medium",
  "confidence": 0.86,
  "explanation": "The argument presents only two alternatives while ignoring other plausible options.",
  "evidence_span": "..."
}
```

Every detection should include an explanation.

Important:

> Fallacy detection is probabilistic. The UI must show confidence and must not claim that every model-generated detection is objectively proven.

---

# 16. Claim Extraction

Every generated argument should pass through a claim extraction step.

Classify claims as:

```text
FACTUAL
OPINION
VALUE_JUDGMENT
PREDICTION
ASSUMPTION
DEFINITION
```

Only appropriate claims should be sent to external verification.

Example:

```json
{
  "claim_text": "Remote work increased productivity by 15%.",
  "claim_type": "FACTUAL",
  "importance": "HIGH",
  "needs_verification": true
}
```

Example opinion:

```json
{
  "claim_text": "Remote work is a better lifestyle.",
  "claim_type": "OPINION",
  "needs_verification": false
}
```

---

# 17. Evidence Verification

Core pipeline:

```text
Argument
   ↓
Claim Extraction
   ↓
Claim Classification
   ↓
Is factual?
   ├── NO → keep as opinion/value/prediction
   │
   └── YES
        ↓
     Search Query
        ↓
     External Search
        ↓
     Evidence Ranking
        ↓
     Claim Verification
        ↓
     Store Sources
```

Verification labels:

```text
SUPPORTED
CONTRADICTED
MIXED
INSUFFICIENT_EVIDENCE
NOT_VERIFIABLE
```

Each evidence record should contain:

```text
claim_id
source_title
source_url
source_domain
snippet
relevance_score
retrieved_at
provider
```

Never fabricate evidence.

---

# 18. Evidence Provider Architecture

Create a provider abstraction.

```python
class EvidenceProvider:
    async def search(self, query: str) -> list:
        raise NotImplementedError
```

Implement providers independently:

```text
evidence/
├── base.py
├── tavily.py
├── serpapi.py
├── google_factcheck.py
└── wikicheck.py
```

Configuration:

```env
EVIDENCE_PROVIDER=tavily
```

Handle:

- API failure
- Rate limits
- Timeout
- No results
- Duplicate sources
- Conflicting evidence
- Low-quality results

The project synopsis explicitly identifies live fact-checking/evidence retrieval and Google Fact Check Tools/WikiCheck as part of the proposed setup. fileciteturn1file0L243-L254

---

# 19. Evidence Quality

Do not treat every search result as equally reliable.

Create an evidence score using factors such as:

```text
source relevance
source consistency
claim coverage
source diversity
retrieval confidence
```

If source credibility cannot be reliably determined, label the source as:

```text
Credibility: Not independently assessed
```

Do not invent a credibility score.

---

# 20. Judge AI

The Judge is a separate component from the debating agents.

It should evaluate:

- Argument quality
- Logical soundness
- Evidence quality
- Factual support
- Relevance
- Rebuttal quality
- Fallacies
- Consistency
- Remaining uncertainty

It must be allowed to output:

```text
SUPPORT
OPPOSE
BALANCED
INCONCLUSIVE
```

The Judge should not simply choose the agent with the highest rhetorical score.

Example:

```json
{
  "winning_position": "support",
  "confidence": 0.72,
  "reasoning_summary": "...",
  "strongest_arguments": [],
  "weakest_arguments": [],
  "key_evidence": [],
  "major_uncertainties": [],
  "decision_guidance": "..."
}
```

If evidence is balanced, return:

```text
INCONCLUSIVE
```

This is a required behavior, not an error.

---

# 21. Final Report

The final report must contain:

## A. Debate Topic

Original user question.

## B. Executive Summary

Concise explanation of the debate.

## C. Positions

Major positions represented.

## D. Strongest Arguments

Arguments with reasons for their strength.

## E. Weakest Arguments

Arguments with weaknesses.

## F. Evidence Summary

Important factual claims and verification status.

## G. Fallacy Summary

Detected fallacies with confidence and explanation.

## H. Argument Score Breakdown

Show:

```text
Logical Soundness
Evidence
Relevance
Effectiveness
Overall
```

## I. Judge Evaluation

Explain the final assessment.

## J. Uncertainty

Show:

- Missing evidence
- Conflicting evidence
- Unverified claims
- Model uncertainty
- Assumptions

## K. Decision Guidance

Provide considerations that help the user decide.

Do not phrase the result as unquestionable truth.

## L. Confidence

Example:

```text
Overall Confidence: 74%

Evidence Quality: 78%
Argument Quality: 81%
Verification Coverage: 69%
Consensus Strength: 65%
Uncertainty: Moderate
```

The confidence calculation should be transparent and documented.

---

# 22. Analytics Dashboard

The architecture requires:

### Debate Overview

- Total debates
- Completed debates
- Failed debates
- Average rounds
- Average duration
- Most common topics/categories

### Argument Scores

Charts for:

- Logical soundness
- Evidence
- Relevance
- Effectiveness
- Overall score

### Fallacy Distribution

Show:

- Fallacy type
- Count
- Percentage
- Average confidence

### Agent Performance

Show:

- Average argument score
- Evidence score
- Rebuttal effectiveness
- Fallacy frequency
- Verification success

Do not interpret "highest score" as "most truthful."

### Trends & Insights

Examples:

- Most frequent fallacy
- Most common position
- Average evidence confidence
- Highest disagreement debates
- Strongest rebuttal patterns

### Export Reports

Allow completed debates to be exported as PDF.

---

# 23. Database Design

Use PostgreSQL as the primary database.

## users

```text
id
email
password_hash
name
created_at
updated_at
```

## debates

```text
id
user_id
topic
expert_selection_mode        -- NEW: "auto" or "manual"
domain_tags                  -- NEW: JSON array, populated in auto mode (nullable)
status
mode
total_rounds
started_at
completed_at
created_at
updated_at
```

## agents

```text
id
name
role
description
system_prompt
is_active
created_at
```

## debate_agents

```text
id
debate_id
agent_id
position
created_at
```

## debate_turns

```text
id
debate_id
agent_id
round_number
turn_number
content
position
metadata_json
created_at
```

## claims

```text
id
debate_id
turn_id
claim_text
claim_type
importance
verification_status
verification_confidence
created_at
```

## evidence

```text
id
claim_id
source_title
source_url
source_domain
snippet
relevance_score
provider
retrieved_at
```

## fallacies

```text
id
turn_id
fallacy_type
severity
confidence
explanation
evidence_span
created_at
```

## evaluations

```text
id
turn_id
logical_soundness
evidence_score
relevance_score
effectiveness_score
overall_score
explanation
created_at
```

## judge_results

```text
id
debate_id
winning_position
confidence
summary
strongest_arguments_json
weakest_arguments_json
uncertainties_json
decision_guidance
created_at
```

## reports

```text
id
debate_id
report_json
pdf_path
created_at
```

---

# 24. API Specification

Base prefix:

```text
/api/v1
```

## Authentication

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
```

## Agents

```http
GET /api/v1/agents
GET /api/v1/agents/{agent_id}
POST /api/v1/agents
```

## Expert Selection (Auto Mode)

```http
POST /api/v1/debates/suggest-agents
Body: { "topic": "..." }
Response: {
  "domain_tags": ["economy", "employment"],
  "suggested_agent_ids": ["economist", "analyst"],
  "agent_scores": [{ "agent": "economist", "relevance": 0.94 }],
  "reasoning": "..."
}
```

## Debates

```http
POST /api/v1/debates
GET  /api/v1/debates
GET  /api/v1/debates/{debate_id}
POST /api/v1/debates/{debate_id}/start
POST /api/v1/debates/{debate_id}/cancel
```

### Create Debate — Request

`expert_selection_mode` is required and must be one of `auto` or `manual`.

```json
{
  "topic": "Should India adopt a four-day work week?",
  "expert_selection_mode": "auto",
  "agent_ids": ["economist", "analyst"],
  "domain_tags": ["economy", "employment"],
  "mode": "balanced",
  "total_rounds": 3,
  "verify_evidence": true
}
```

- In **manual** mode: `agent_ids` are provided directly by the user and `expert_selection_mode = "manual"`.
- In **auto** mode: `agent_ids` come from the user accepting (or editing) the `suggest-agents` response; `domain_tags` may be stored for reprogability. If `agent_ids` is empty in auto mode, the backend runs the `suggest-agents` analysis server-side at creation time.

## Transcript

```http
GET /api/v1/debates/{debate_id}/turns
```

## Claims

```http
GET /api/v1/debates/{debate_id}/claims
```

## Evidence

```http
GET /api/v1/debates/{debate_id}/evidence
```

## Fallacies

```http
GET /api/v1/debates/{debate_id}/fallacies
```

## Evaluations

```http
GET /api/v1/debates/{debate_id}/evaluations
```

## Judge

```http
GET /api/v1/debates/{debate_id}/judge
```

## Report

```http
GET /api/v1/debates/{debate_id}/report
```

## Export

```http
GET /api/v1/debates/{debate_id}/export/pdf
```

---

# 25. WebSocket Specification

Endpoint:

```text
WS /api/v1/debates/{debate_id}/stream
```

Events:

```json
{
  "event": "debate_started",
  "debate_id": "...",
  "expert_selection_mode": "auto",
  "domain_tags": ["economy", "employment"]
}
```

```json
{
  "event": "round_started",
  "round": 1,
  "total_rounds": 3
}
```

```json
{
  "event": "agent_turn_started",
  "round": 1,
  "agent": "Economist"
}
```

```json
{
  "event": "agent_turn_completed",
  "round": 1,
  "agent": "Economist",
  "turn_id": "...",
  "content": "..."
}
```

```json
{
  "event": "claim_extracted",
  "claim_id": "...",
  "claim": "..."
}
```

```json
{
  "event": "evidence_found",
  "claim_id": "...",
  "sources": []
}
```

```json
{
  "event": "fallacy_detected",
  "turn_id": "...",
  "fallacy": "Straw Man",
  "confidence": 0.82
}
```

```json
{
  "event": "evaluation_completed",
  "turn_id": "...",
  "scores": {
    "logical_soundness": 8,
    "evidence": 7,
    "relevance": 9,
    "effectiveness": 8
  }
}
```

```json
{
  "event": "judge_started"
}
```

```json
{
  "event": "debate_completed",
  "debate_id": "..."
}
```

---

# 26. Frontend Pages

## 26.1 Home / Debate Setup

Display:

- Project title
- Explanation
- Topic input
- Example topics
- **Expert selection mode (Auto or Manual, user chooses)**
- Agent selection (manual list OR auto-suggested list)
- Number of rounds
- Debate mode
- Evidence verification toggle
- Start Debate button

Example:

```text
MULTI-AGENT LLM BASED ARGUMENT VERIFICATION AND EVIDENCE-BASED DECISIONS

Analyze a topic from multiple expert perspectives.

Topic:
[ Should India adopt a four-day work week? ]

Expert Selection:
( ) Auto — let the system assign experts based on the topic
(*) Manual — choose experts yourself

// If MANUAL is selected:
Experts:
[x] Economist
[x] Lawyer
[x] Scientist
[x] Ethicist
[x] Analyst

// If AUTO is selected (shown after the Topic Analyzer returns):
Domain detected: economy, employment
Suggested Experts:
[x] Economist   (relevance 0.94)
[x] Analyst     (relevance 0.87)
[ ] Lawyer      (relevance 0.52)
[ Re-analyze ]  [ Use these experts ]

Rounds:
[ 3 ]

Mode:
[ Balanced Debate ]

Evidence Verification:
[ ON ]

[ START DEBATE ]
```

---

# 27. Live Debate UI

The live screen must show:

- Debate topic
- Current round
- Current agent
- Agent role
- Position
- Argument
- Rebuttal
- Evidence
- Verification status
- Fallacy warnings
- Scores
- Progress

Example:

```text
ROUND 2 / 3

┌──────────────────────────────────────┐
│ ECONOMIST                             │
│ Position: Support                    │
│                                      │
│ Argument:                            │
│ ...                                  │
│                                      │
│ Evidence:                            │
│ ✓ Source 1                           │
│ ✓ Source 2                           │
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ LAWYER                               │
│ Rebuttal                             │
│ ...                                  │
│                                      │
│ ⚠ Possible Straw Man                │
└──────────────────────────────────────┘
```

Use WebSockets so turns appear progressively.

---

# 28. Results Page

After completion, display:

### Header

```text
Debate Completed
Topic: ...
Verdict: ...
Confidence: ...
```

### Tabs

```text
Overview
Transcript
Arguments
Evidence
Fallacies
Scores
Judge
Report
```

### Overview

Show:

- Final assessment
- Confidence
- Main arguments
- Main evidence
- Major uncertainties

---

# 29. Transcript Page

Every turn should show:

```text
Agent Name
Role
Round
Position
Argument
Claims
Evidence
Fallacies
Scores
Timestamp
```

Allow filtering by:

- Agent
- Round
- Position
- Fallacy
- Verification status

---

# 30. Evidence UI

For each claim:

```text
CLAIM
"...."

STATUS
SUPPORTED

CONFIDENCE
84%

SOURCES

[Source title]
Domain: example.com
Retrieved: ...
Relevance: 0.91

[Open Source]
```

If contradictory evidence exists, show both sides.

---

# 31. Fallacy UI

Example:

```text
⚠ STRAW MAN

Confidence: 82%
Severity: Medium

Why:
The response appears to misrepresent the opposing position
before attacking it.

Text:
"..."
```

---

# 32. Score UI

Use visual score cards.

```text
Logical Soundness    8.2 / 10
Evidence             7.6 / 10
Relevance            9.0 / 10
Effectiveness        8.1 / 10
──────────────────────────────
Overall              8.2 / 10
```

---

# 33. Recommended Backend Structure

```text
backend/
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── auth.py
│   │   ├── debates.py
│   │   ├── agents.py
│   │   ├── analysis.py
│   │   ├── reports.py
│   │   └── websocket.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── logging.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repositories/
│   │
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── debate.py
│   │   ├── expert_selection.py      -- NEW: suggest-agents input/output + selection-mode fields
│   │   ├── agent.py
│   │   ├── claim.py
│   │   ├── evidence.py
│   │   ├── evaluation.py
│   │   └── report.py
│   │
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── expert_selector.py       -- NEW: topic analysis + auto-assignment
│   │   ├── economist.py
│   │   ├── lawyer.py
│   │   ├── doctor.py
│   │   ├── scientist.py
│   │   ├── ethicist.py
│   │   ├── analyst.py
│   │   └── custom_agent.py
│   │
│   ├── orchestration/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── orchestrator.py
│   │   └── prompts.py
│   │
│   ├── analysis/
│   │   ├── argument_evaluator.py
│   │   ├── fallacy_detector.py
│   │   ├── claim_extractor.py
│   │   ├── fact_verifier.py
│   │   └── judge.py
│   │
│   ├── evidence/
│   │   ├── base_provider.py
│   │   ├── tavily_provider.py
│   │   ├── serpapi_provider.py
│   │   ├── google_factcheck.py
│   │   └── wikicheck_provider.py
│   │
│   ├── llm/
│   │   ├── base_provider.py
│   │   ├── openai_provider.py
│   │   └── anthropic_provider.py
│   │
│   ├── reports/
│   │   ├── generator.py
│   │   └── pdf.py
│   │
│   └── services/
│       ├── debate_service.py
│       ├── evidence_service.py
│       ├── analytics_service.py
│       └── export_service.py
│
├── tests/
├── alembic/
├── requirements.txt
├── Dockerfile
└── .env.example
```

---

# 34. Recommended Frontend Structure

```text
frontend/
├── src/
│   ├── components/
│   │   ├── DebateSetup.jsx
│   │   ├── AgentCard.jsx
│   │   ├── ExpertSelector.jsx        -- NEW: Auto/Manual mode toggle + suggested/selected list
│   │   ├── DebateTurn.jsx
│   │   ├── DebateTimeline.jsx
│   │   ├── EvidenceCard.jsx
│   │   ├── FallacyBadge.jsx
│   │   ├── ScoreCard.jsx
│   │   ├── AgentSelector.jsx
│   │   ├── RoundProgress.jsx
│   │   └── LoadingState.jsx
│   │
│   ├── pages/
│   │   ├── Home.jsx
│   │   ├── Debate.jsx
│   │   ├── Results.jsx
│   │   ├── History.jsx
│   │   └── Dashboard.jsx
│   │
│   ├── services/
│   │   ├── api.js
│   │   └── websocket.js
│   │
│   ├── hooks/
│   │   └── useDebateStream.js
│   │
│   ├── utils/
│   │   ├── formatting.js
│   │   └── scoring.js
│   │
│   ├── App.jsx
│   └── main.jsx
│
├── package.json
└── Dockerfile
```

---

# 35. Environment Variables

Create `.env.example`.

```env
# Application
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
SECRET_KEY=change-me

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/aidebate

# Redis
REDIS_URL=redis://redis:6379/0

# LLM
LLM_PROVIDER=openai
LLM_MODEL=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Evidence
EVIDENCE_PROVIDER=tavily
TAVILY_API_KEY=
SERPAPI_API_KEY=

# Fact checking
GOOGLE_FACT_CHECK_API_KEY=

# Frontend
FRONTEND_URL=http://localhost:5173
```

Never commit the real `.env` file.

---

# 36. Authentication

Implement basic authentication.

Required:

- Registration
- Login
- Password hashing
- JWT/session authentication
- Current-user endpoint
- Protected debate history

The authentication layer exists in the proposed architecture.

For the academic MVP, keep authentication simple and secure. Do not over-engineer OAuth unless required.

---

# 37. Error Handling

The application must handle:

### LLM errors

```text
timeout
rate limit
invalid response
provider unavailable
JSON parsing failure
```

### Search errors

```text
timeout
rate limit
no results
provider unavailable
```

### Database errors

```text
connection failure
transaction failure
constraint failure
```

### Debate errors

```text
agent failure
orchestration failure
cancelled debate
partial completion
```

If one agent fails, the entire application should not necessarily crash.

Possible strategy:

```text
Agent failed
   ↓
Retry
   ↓
Retry failed?
   ↓
Mark agent turn unavailable
   ↓
Continue debate if safe
```

---

# 38. Observability

Add structured logs.

Log:

```text
debate_id
user_id
round
agent
event
duration
provider
status
error
```

Never log API keys or sensitive credentials.

Useful metrics:

- LLM latency
- Search latency
- Debate duration
- Tokens/cost if provider exposes them
- Agent failure rate
- Evidence retrieval success
- Verification coverage

---

# 39. Security

Required:

- Never expose API keys to React.
- Hash passwords.
- Validate all user inputs.
- Sanitize generated HTML before rendering.
- Restrict CORS.
- Use environment variables for secrets.
- Add request size limits.
- Add reasonable rate limiting.
- Validate WebSocket authentication.
- Avoid arbitrary URL fetching from user input.
- Do not execute generated code.
- Do not trust LLM-generated URLs without validation.

---

# 40. PDF Report

The PDF should contain:

```text
MULTI-AGENT LLM BASED ARGUMENT VERIFICATION AND EVIDENCE-BASED DECISIONS

Topic
Date
Debate Configuration

Executive Summary

Positions

Argument Analysis

Evidence Verification

Logical Fallacies

Argument Scores

Judge Evaluation

Strongest Arguments

Weakest Arguments

Uncertainties

Decision Guidance

Confidence Score

Complete Debate Transcript
```

Use ReportLab or WeasyPrint.

The synopsis explicitly proposes ReportLab/WeasyPrint for exportable debate reports. fileciteturn1file0L243-L252

---

# 41. Testing Requirements

Create unit tests for:

### Agents

- Prompt construction
- Structured response parsing
- Invalid LLM output

### Expert Selection (Auto Mode)

- Domain tag extraction from a topic
- Correct agent suggestion from the domain mapping
- Relevance score ranges (0–1)
- Topic Analyzer failure → graceful fallback to all core agents
- `suggest-agents` endpoint validation
- Manual mode ignores suggestions and uses user-picked agents
- User overrides suggestions correctly

### Claim Extraction

- Factual claims
- Opinions
- Multiple claims
- Empty arguments

### Fallacy Detection

- Known fallacy examples
- No-fallacy examples
- Confidence output

### Evidence

- Search success
- No results
- Provider error
- Duplicate sources

### Scoring

- Score range validation
- Missing scores
- Overall calculation

### Orchestration

- Correct round order
- Agent failure handling
- Debate completion
- Cancellation

### API

- Authentication
- Debate creation (manual mode)
- Debate creation (auto mode with empty agent_ids triggering server-side analysis)
- `suggest-agents` endpoint
- Debate retrieval
- Report export

### Frontend

- Debate setup
- Auto/Manual expert selection mode toggle
- Suggested experts rendering and override
- WebSocket events
- Loading states
- Error states
- Results rendering

---

# 42. MVP Definition

The first working version should implement:

```text
✓ React frontend
✓ FastAPI backend
✓ PostgreSQL
✓ Redis
✓ User authentication
✓ Topic submission
✓ Automatic and manual expert selection
✓ 4–7 configurable agents
✓ LangGraph orchestration
✓ 2–3 debate rounds
✓ Real-time WebSocket transcript
✓ Claim extraction
✓ Evidence retrieval
✓ Basic fact verification
✓ Basic fallacy detection
✓ Argument scoring
✓ Judge AI
✓ Final report
✓ Results dashboard
✓ PDF export
```

Do not attempt every advanced feature before the complete MVP works.

---

# 43. Recommended Development Order

## Phase 1 — Project Setup

Create:

```text
frontend
backend
database
redis
docker-compose
```

Make sure frontend and backend communicate.

## Phase 2 — Authentication

Implement:

```text
register
login
current user
protected routes
```

## Phase 3 — Debate Creation

Implement:

```text
POST /debates
GET /debates
GET /debates/{id}
POST /debates/suggest-agents
```

Support both `expert_selection_mode` values (`auto` and `manual`) in the create payload, with `expert_selector.py` backing the `suggest-agents` endpoint.

## Phase 4 — Single Agent

Before multi-agent orchestration, verify one agent can:

```text
receive topic
generate structured argument
store result
```

## Phase 5 — Multi-Agent Debate

Add:

```text
Economist
Lawyer
Scientist
Ethicist
Analyst
```

Then add Doctor and custom agents.

## Phase 6 — LangGraph

Implement:

```text
START
 ↓
Agent Selection
 ↓
Round
 ↓
Claim Extraction
 ↓
Evidence
 ↓
Evaluation
 ↓
Next Round
 ↓
Judge
 ↓
Report
 ↓
END
```

## Phase 7 — WebSocket Streaming

Stream:

```text
round started
agent started
agent response
evidence
fallacy
score
judge
completed
```

## Phase 8 — Verification

Implement:

```text
claim extraction
search
evidence ranking
verification status
```

## Phase 9 — Analysis

Implement:

```text
fallacy detection
argument evaluation
judge
```

## Phase 10 — Dashboard

Implement:

```text
overview
scores
fallacies
agent performance
evidence
transcript
```

## Phase 11 — Reports

Implement PDF generation.

## Phase 12 — Testing & Deployment

Add:

```text
tests
Docker
Docker Compose
README
.env.example
deployment instructions
```

---

# 44. Docker Architecture

Recommended:

```text
docker-compose.yml

services:

  frontend
      |
      +--> backend

  backend
      |
      +--> postgres
      |
      +--> redis
      |
      +--> external LLM APIs
      |
      +--> external evidence APIs
```

Development commands should eventually be:

```bash
docker compose up --build
```

and the README should document local non-Docker development as well.

---

# 45. Suggested API Request

Creating a debate (manual expert selection):

```json
{
  "topic": "Should India adopt a four-day work week?",
  "expert_selection_mode": "manual",
  "mode": "balanced",
  "total_rounds": 3,
  "agent_ids": [
    "economist",
    "lawyer",
    "scientist",
    "ethicist",
    "analyst"
  ],
  "verify_evidence": true
}
```

Creating a debate (auto expert selection — agents suggested by the system):

```json
{
  "topic": "Should India adopt a four-day work week?",
  "expert_selection_mode": "auto",
  "mode": "balanced",
  "total_rounds": 3,
  "agent_ids": [],
  "verify_evidence": true
}
```

Requesting suggested agents without creating a debate:

```json
POST /api/v1/debates/suggest-agents
{
  "topic": "Should India adopt a four-day work week?"
}
```

---

# 46. Suggested Final Result JSON

```json
{
  "debate_id": "debate_123",
  "topic": "Should India adopt a four-day work week?",
  "status": "completed",
  "rounds": 3,
  "judge": {
    "result": "BALANCED",
    "confidence": 0.72
  },
  "scores": {
    "logical_soundness": 7.8,
    "evidence": 7.2,
    "relevance": 8.5,
    "effectiveness": 8.0
  },
  "claims": [],
  "evidence": [],
  "fallacies": [],
  "strongest_arguments": [],
  "weakest_arguments": [],
  "uncertainties": [],
  "decision_guidance": "..."
}
```

---

# 47. UI Design Direction

The UI should look like a serious AI analysis platform, not a generic chatbot.

Recommended visual hierarchy:

```text
Dark/neutral professional background
+
Clear cards
+
Expert role badges
+
Live timeline
+
Evidence indicators
+
Fallacy warnings
+
Score visualization
+
Clean charts
```

Avoid:

- Excessive gradients
- Fake AI-looking animations
- Unnecessary 3D graphics
- Overloaded screens
- ChatGPT clone styling
- Fake loading animations that hide actual processing

The primary focus should be readability and transparency.

---

# 48. Important UX Principle: Transparency

The user should always be able to answer:

```text
Who said this?
What position did they take?
Why did they say it?
What factual claim did they make?
Was that claim verified?
What evidence was found?
Was a fallacy detected?
How was the argument scored?
Why did the Judge reach its conclusion?
What remains uncertain?
```

If the system cannot answer one of these questions, the UI should not pretend that the result is fully explainable.

---

# 49. Handling Hallucinations

The motivation for the project specifically identifies AI hallucinations as a concern: LLMs can generate information that appears credible but is false, while external fact verification can provide another verification layer. fileciteturn1file0L152-L169

Therefore:

```text
LLM statement
      ↓
Is it factual?
      ↓
YES → Search external evidence
      ↓
Compare claim and evidence
      ↓
Show verification status
```

Never use:

```text
LLM said it
→ therefore it is true
```

---

# 50. Handling Conflicting Evidence

If sources disagree:

```text
Source A → supports claim
Source B → contradicts claim
Source C → mixed
```

The system should output:

```text
MIXED / CONFLICTING EVIDENCE
```

and explain the disagreement.

Do not arbitrarily choose one source without justification.

---

# 51. Handling Agent Disagreement

Disagreement is not an error.

Example:

```text
Economist → Support
Lawyer → Oppose
Scientist → Mixed
Ethicist → Oppose
Analyst → Inconclusive
```

The final result should preserve this disagreement.

The project is specifically intended to help users compare conflicting viewpoints rather than merely receive one unified AI-generated answer. fileciteturn1file0L48-L65

---

# 52. Research Foundation

The project synopsis references research areas including:

- Argument mining
- Logical fallacy detection
- Fact verification and evidence retrieval
- Multi-agent LLM reasoning
- Debate analysis and argument evaluation

The literature review describes the project as combining these areas into one workflow. fileciteturn1file0L93-L135

Referenced works include:

1. **Generative Agents: Interactive Simulacra of Human Behavior** — Park et al., 2023
2. **Improving Factuality and Reasoning in Language Models through Multiagent Debate** — Du et al., 2023
3. **Encouraging Divergent Thinking in Large Language Models through Multi-Agent Debate** — Liang et al., 2023
4. **On the Dangers of Stochastic Parrots: Can Language Models Be Too Big?** — Bender et al., 2021
5. **Argumentation Theory: A Very Short Introduction** — Douglas Walton, 2009
6. **Chain-of-Thought Prompting Elicits Reasoning in Large Language Models** — Wei et al., 2022
7. **MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework** — Hong et al., 2023
8. **A Survey on Automated Fact-Checking** — Guo, Schlichtkrull & Vlachos, 2022
9. **Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks** — Lewis et al., 2020
10. **CAMEL: Communicative Agents for “Mind” Exploration of Large Scale Language Model Society** — Li et al., 2023
11. **ChatEval: Towards Better LLM-based Evaluators through Multi-Agent Debate** — Chan et al., 2023/24
12. **AI Safety via Debate** — Irving, Christiano & Amodei, 2018

These references are taken from the submitted synopsis. fileciteturn1file0L261-L354

---

# 53. Hardware / Runtime Requirements

The project synopsis specifies:

```text
Processor: Intel Core i5 8th Gen or AMD Ryzen 5
RAM: 8 GB minimum, 16 GB recommended
Storage: 256 GB SSD or above
Internet: Required for LLM API calls and live fact checking
```

fileciteturn1file0L234-L240

The application should therefore primarily use cloud/API LLMs rather than assuming a powerful local GPU.

---

# 54. What NOT to Build

Do not turn the project into:

### ❌ A normal chatbot

The central feature is multi-agent debate + verification.

### ❌ A fake multi-agent UI

Showing several cards while calling one LLM behind the scenes is not sufficient.

### ❌ A static demo

The debate must actually execute dynamically.

### ❌ An unverified web search summary

Evidence must be associated with individual claims.

### ❌ A forced-victory system

The Judge must be able to return balanced/inconclusive.

### ❌ A single-score evaluation

Keep multiple evaluation dimensions.

### ❌ A hallucinated citation system

Only display sources actually returned by the evidence provider.

---

# 55. Performance Considerations

Multi-agent systems can become expensive and slow.

Implement:

- Async LLM calls where safe
- Caching
- Limited search queries
- Configurable number of rounds
- Configurable agent count
- Timeouts
- Retry with exponential backoff
- Evidence deduplication
- Token-conscious prompts
- Persistent debate state

Do not make seven agents perform seven searches for every sentence.

A better strategy:

```text
Agent turns
    ↓
Extract important factual claims
    ↓
Search only claims that need verification
    ↓
Reuse evidence across agents when relevant
```

---

# 56. Cost Control

Expose configuration:

```env
MAX_ROUNDS=3
MAX_AGENTS=7
MAX_CLAIMS_PER_TURN=5
MAX_EVIDENCE_RESULTS=5
```

The application should avoid unnecessary LLM calls.

For development, support a mock provider:

```env
LLM_PROVIDER=mock
```

This is useful for testing frontend/orchestration without spending API credits.

Important: mock mode must be clearly labeled and must not be presented as real AI output.

---

# 57. Reproducibility

Each debate should store:

```text
topic
configuration
agents
agent prompts/version identifiers
model/provider
rounds
turns
retrieved evidence
verification results
evaluation results
judge result
timestamps
```

This allows the team to reproduce and analyze previous debates.

---

# 58. Explainability

For every final conclusion, the report should allow the user to trace:

```text
Conclusion
   ↓
Judge evaluation
   ↓
Argument
   ↓
Claim
   ↓
Evidence
   ↓
Source
```

This traceability is one of the most important parts of the project.

---

# 59. Definition of Done

The project is considered functional only when the following complete flow works:

```text
User opens website
        ↓
Creates account / logs in
        ↓
Enters topic
        ↓
Selects expert agents
        ↓
Selects rounds
        ↓
Starts debate
        ↓
Frontend receives live turns
        ↓
Multiple agents actually generate arguments
        ↓
Agents rebut each other
        ↓
Claims are extracted
        ↓
External evidence is retrieved
        ↓
Claims are verified
        ↓
Fallacies are detected
        ↓
Arguments are scored
        ↓
Judge AI evaluates debate
        ↓
Final report is generated
        ↓
Dashboard displays results
        ↓
User can inspect evidence
        ↓
User can inspect fallacies
        ↓
User can inspect scores
        ↓
User can export PDF
        ↓
Debate remains available in history
```

---

# 60. Final Instruction to the Coding AI

Build this project as a **production-style academic prototype**.

Start with the smallest complete end-to-end flow:

```text
React
→ FastAPI
→ LangGraph
→ 3 agents
→ LLM
→ PostgreSQL
→ WebSocket
→ basic evidence search
→ argument evaluation
→ Judge
→ results
```

Once that works reliably, expand to all seven agent roles, richer verification, analytics, and PDF export.

Do not build everything simultaneously and leave the core workflow broken.

The priority order is:

```text
1. Correct architecture
2. Working end-to-end debate
3. Real multi-agent orchestration
4. Real evidence verification
5. Reliable persistence
6. Transparent evaluation
7. Good UI
8. Analytics
9. PDF export
10. Advanced optimization
```

The system's purpose is **evidence-based decision support through multi-agent debate and argument verification**, not simply generating persuasive AI text.

---

## Source Specification

This README is based on the project's submitted synopsis, **“Multi-Agent LLM for Argument Verification & Evidence-Based Decisions,”** and the supplied **Multi-Agent LLM Based Argument Verification and Evidence-Based Decisions – System Architecture** diagram. The synopsis identifies the project's abstract, objectives, architecture, technology stack, libraries/services, and research foundation. fileciteturn1file0L48-L65 fileciteturn1file0L195-L204

