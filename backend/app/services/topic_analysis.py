"""Topic analysis and dynamic AI specialist roles.

One structured LLM call (existing provider abstraction) analyses the debate
topic, picks relevant built-in agents and proposes additional AI specialist
roles only where the built-ins do not cover needed expertise. Everything the
model returns is validated here before it can reach a prompt:

- schema and length limits (``SpecialistDefinition``);
- safety: definitions that try to override instructions, mention secrets,
  credentials, tools, code execution, URLs or configuration are rejected;
  roles may not claim to be licensed professionals or human experts;
- deduplication against built-ins and between specialists;
- relevance: a specialist must share vocabulary with the topic analysis;
- budget: total agents and specialists are capped by settings.

Specialists are perspectives, not new knowledge: their runtime prompt is a
fixed template (``app/agents/dynamic.py``) that keeps the debate protocol,
evidence and integrity rules, with the definition inserted as data.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import get_settings
from app.llm.base import LLMMessage, LLMProviderError
from app.llm.factory import get_llm_provider
from app.models.agent import Agent

logger = logging.getLogger(__name__)

ANALYSIS_MAX_TOKENS = 4000
MIN_AGENTS = 2

_UNSAFE_PATTERNS = [
    r"\bignore\b.*\b(instruction|rule|prompt)s?\b",
    r"\b(disregard|override|bypass|forget)\b",
    r"\bsystem prompt\b",
    r"\bjailbreak\b|\bdeveloper mode\b",
    r"\b(api[ _-]?key|secret|password|credential|token|private key)s?\b",
    r"\b(execute|run) (code|commands?|scripts?)\b|\bshell\b|\bterminal\b",
    r"\b(call|use|invoke) (a |the )?(tool|function|api)s?\b",
    r"\b(environment variable|config(uration)?)\b",
    r"https?://|www\.",
]
_UNSAFE_RE = re.compile("|".join(_UNSAFE_PATTERNS), re.IGNORECASE)
_CREDENTIAL_CLAIM_RE = re.compile(
    r"\b(licensed|board[- ]certified|certified|accredited|registered)\b"
    r"|\b(i am|i'm) an? (real|human|practicing|qualified)\b|\bdr\.?\s",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z &/\-]{2,59}$")

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about", "should",
    "would", "could", "their", "there", "which", "what", "when", "where", "while",
    "will", "more", "most", "than", "they", "them", "have", "been", "being", "over",
    "under", "between", "within", "without", "allowed", "make", "important", "debate",
    "topic", "question", "questions", "specialist", "expert", "experts", "analysis",
    "perspective", "role", "focus", "issues", "impact", "impacts", "policy", "policies",
}
_GENERIC_TITLE_WORDS = {
    "specialist", "expert", "analyst", "researcher", "engineer", "officer",
    "consultant", "advisor", "adviser", "scientist", "planner",
}


class AnalysisError(Exception):
    """The topic analysis LLM call failed or returned unusable output."""


def _clip(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _words(text: str) -> set[str]:
    return {
        w[:6]
        for w in re.findall(r"[a-z]+", (text or "").lower())
        if len(w) >= 4 and w not in _STOPWORDS
    }


def _title_core(name: str) -> set[str]:
    words = {w for w in re.findall(r"[a-z]+", name.lower())}
    core = words - _GENERIC_TITLE_WORDS
    return core or words


class SpecialistDefinition(BaseModel):
    """A dynamic AI specialist role. All fields are plain data inserted into
    a fixed prompt template; nothing here can replace system rules."""

    name: str = Field(min_length=3, max_length=60)
    domain: str = Field(min_length=2, max_length=60)
    subdomain: str = Field(default="", max_length=60)
    expertise: str = Field(min_length=20, max_length=400)
    debate_objective: str = Field(min_length=10, max_length=300)
    instructions: list[str] = Field(default_factory=list, max_length=5)
    capabilities: list[str] = Field(default_factory=list, max_length=6)
    reason: str = Field(default="", max_length=300)

    @field_validator("name", "domain", "subdomain", "expertise", "debate_objective", "reason", mode="before")
    @classmethod
    def _clean_text(cls, value):
        return " ".join(str(value or "").split())

    @field_validator("instructions", "capabilities", mode="before")
    @classmethod
    def _clean_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("expected a list")
        return [" ".join(str(v).split()) for v in value if str(v or "").strip()]

    @field_validator("instructions")
    @classmethod
    def _instruction_length(cls, value: list[str]) -> list[str]:
        if any(len(item) > 200 for item in value):
            raise ValueError("each instruction must be at most 200 characters")
        return value

    @field_validator("capabilities")
    @classmethod
    def _capability_length(cls, value: list[str]) -> list[str]:
        if any(len(item) > 60 for item in value):
            raise ValueError("each capability must be at most 60 characters")
        return value

    @field_validator("name")
    @classmethod
    def _name_format(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("name must be a plain role title")
        return value

    def all_text(self) -> str:
        return " ".join(
            [self.name, self.domain, self.subdomain, self.expertise,
             self.debate_objective, self.reason, *self.instructions, *self.capabilities]
        )

    def safety_problem(self) -> str | None:
        text = self.all_text()
        if _UNSAFE_RE.search(text):
            return "contains instructions outside the debate role (overrides, secrets, tools, URLs or configuration)"
        if _CREDENTIAL_CLAIM_RE.search(text):
            return "claims professional licensing or human-expert status"
        return None


class BuiltinPick(BaseModel):
    role: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=300)

    @field_validator("role", "reason", mode="before")
    @classmethod
    def _clean(cls, value):
        return " ".join(str(value or "").split())


class TopicAnalysisOutput(BaseModel):
    main_domain: str = Field(min_length=2, max_length=80)
    secondary_domains: list[str] = Field(default_factory=list)
    key_questions: list[str] = Field(default_factory=list)
    recommended_agent_count: int = 4
    builtin_agents: list[BuiltinPick] = Field(default_factory=list)
    specialists: list[dict] = Field(default_factory=list)
    specialists_rationale: str = ""

    @field_validator("main_domain", "specialists_rationale", mode="before")
    @classmethod
    def _text(cls, value):
        return _clip(value, 400)

    @field_validator("builtin_agents", mode="before")
    @classmethod
    def _picks(cls, value):
        # Models sometimes list built-ins as plain strings or with "name".
        if not isinstance(value, list):
            return []
        picks = []
        for item in value:
            if isinstance(item, str):
                picks.append({"role": item})
            elif isinstance(item, dict):
                role = item.get("role") or item.get("id") or item.get("name")
                if role:
                    picks.append({"role": role, "reason": item.get("reason", "")})
        return picks

    @field_validator("specialists", mode="before")
    @classmethod
    def _specialist_items(cls, value):
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @field_validator("secondary_domains", "key_questions", mode="before")
    @classmethod
    def _lists(cls, value):
        if not isinstance(value, list):
            return []
        return [_clip(v, 200) for v in value if str(v or "").strip()][:6]

    @field_validator("recommended_agent_count", mode="before")
    @classmethod
    def _count(cls, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 4


@dataclass
class TopicAnalysis:
    main_domain: str
    secondary_domains: list[str]
    key_questions: list[str]
    recommended_agent_count: int
    builtins: list[tuple[Agent, str]]
    specialists: list[SpecialistDefinition]
    rejected: list[dict] = field(default_factory=list)
    specialists_rationale: str = ""


SYSTEM_PROMPT = (
    "You plan the expert panel for an AI debate.\n"
    "1. Analyse the debate question: main domain, up to 4 secondary domains, "
    "and the 2-5 key questions that need expert perspectives.\n"
    "2. For each key question decide who covers it best. Choose BUILT-IN "
    "agents from the provided list (exact role ids) only if they answer at "
    "least one key question directly - do not include every built-in by "
    "default. A focused panel of 3-5 is usually best.\n"
    "3. Add an AI specialist role when a key question needs domain depth "
    "that a built-in covers only generically (e.g. encryption and security "
    "engineering, clinical safety, energy grids, blockchain protocols). For "
    "an everyday topic the built-ins usually suffice: return an empty "
    "specialists list. Never propose a role that duplicates a built-in.\n"
    "4. recommended_agent_count: the total panel size (2-6) the topic needs.\n"
    "Specialist rules: a plain job title (e.g. 'Clinical Safety Specialist'); "
    "these are AI perspectives, never licensed professionals or real people; "
    "instructions describe only the debate perspective (what to focus on), "
    "never tools, links, secrets or changes to rules.\n"
    "Respond with ONLY a JSON object:\n"
    '{"main_domain": "...", "secondary_domains": ["..."], '
    '"key_questions": ["..."], "recommended_agent_count": 4, '
    '"builtin_agents": [{"role": "doctor", "reason": "..."}], '
    '"specialists": [{"name": "...", "domain": "...", "subdomain": "...", '
    '"expertise": "one or two sentences", "debate_objective": "...", '
    '"instructions": ["focus on ..."], "capabilities": ["..."], '
    '"reason": "why the built-ins do not cover this"}], '
    '"specialists_rationale": "..."}'
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_analysis(raw: str) -> TopicAnalysisOutput:
    if not isinstance(raw, str) or not raw.strip():
        raise AnalysisError("empty analysis response")
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise AnalysisError("analysis response is not a JSON object")
    try:
        return TopicAnalysisOutput(**json.loads(text[start : end + 1]))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AnalysisError("analysis response failed validation") from exc


def validate_specialists(
    raw_items: list,
    builtins: list[Agent],
    *,
    relevance_text: str | None,
    limit: int,
) -> tuple[list[SpecialistDefinition], list[dict]]:
    """Validate, de-duplicate and (optionally) relevance-check specialists.

    Returns (accepted, rejected) where rejected items carry a reason. With
    ``relevance_text=None`` the relevance check is skipped (used at debate
    creation, where the user has already reviewed the panel).
    """
    accepted: list[SpecialistDefinition] = []
    rejected: list[dict] = []
    builtin_cores = [(_title_core(a.name), a.name) for a in builtins]
    context_words = _words(relevance_text) if relevance_text is not None else None

    for raw in raw_items:
        label = (str(raw.get("name") or "").strip()[:60] if isinstance(raw, dict) else "") or "?"
        try:
            spec = SpecialistDefinition(**raw) if isinstance(raw, dict) else None
        except ValidationError:
            spec = None
        if spec is None:
            rejected.append({"name": label, "reason": "invalid definition (schema or length limits)"})
            continue
        problem = spec.safety_problem()
        if problem:
            rejected.append({"name": spec.name, "reason": problem})
            continue
        core = _title_core(spec.name)
        # "Economist" duplicates the built-in; "Energy Economist" is more specific.
        dup_builtin = next((name for c, name in builtin_cores if core <= c), None)
        if dup_builtin:
            rejected.append({"name": spec.name, "reason": f"duplicates built-in agent {dup_builtin}"})
            continue
        duplicate = next(
            (
                other.name
                for other in accepted
                if other.name.lower() == spec.name.lower()
                or len(core & _title_core(other.name)) / max(len(core | _title_core(other.name)), 1) >= 0.5
                or (
                    other.domain.lower() == spec.domain.lower()
                    and other.subdomain.lower() == spec.subdomain.lower()
                    and spec.subdomain
                )
            ),
            None,
        )
        if duplicate:
            rejected.append({"name": spec.name, "reason": f"duplicates specialist {duplicate}"})
            continue
        if context_words is not None:
            own = _words(" ".join([spec.name, spec.domain, spec.subdomain, spec.expertise]))
            if not own & context_words:
                rejected.append({"name": spec.name, "reason": "not relevant to the debate topic"})
                continue
        if len(accepted) >= limit:
            rejected.append({"name": spec.name, "reason": "agent budget reached"})
            continue
        accepted.append(spec)
    return accepted, rejected


def specialist_record(spec: SpecialistDefinition, *, source: str, model: str | None) -> dict:
    """Definition persisted on the debate-scoped Agent row (audit/reproduce)."""
    data = spec.model_dump()
    data["provenance"] = {"source": source, "model": model, "label": "AI specialist role"}
    return data


class TopicAnalysisService:
    async def _generate_json(self, messages):
        """Ask for JSON mode when the provider supports it (Groq does);
        older providers and test fakes without the flag are called plainly."""
        kwargs = {"temperature": 0.0, "max_tokens": ANALYSIS_MAX_TOKENS}
        try:
            if "json_mode" in inspect.signature(self.provider.generate).parameters:
                kwargs["json_mode"] = True
        except (TypeError, ValueError):
            pass
        return await self.provider.generate(messages, **kwargs)

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def analyze(
        self,
        topic: str,
        builtins: list[Agent],
        *,
        context: str | None = None,
        mode: str | None = None,
    ) -> TopicAnalysis:
        settings = get_settings()
        roster = [
            {"role": a.role, "name": a.name, "description": a.description} for a in builtins
        ]
        user_prompt = (
            f"Debate question: {_clip(topic, 800)}\n"
            + (f"Context: {_clip(context, 1000)}\n" if context else "")
            + f"Format: {'pro/con' if mode == 'pro_con' else 'balanced'}\n"
            + f"Maximum panel size: {settings.DEBATE_MAX_AGENTS}; at most "
            f"{settings.DEBATE_MAX_SPECIALISTS} specialists.\n\n"
            f"Built-in agents (JSON):\n{json.dumps(roster, indent=2)}\n\n"
            "Return the JSON object."
        )
        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]
        output = None
        for attempt in range(2):  # one bounded re-ask on invalid output
            try:
                response = await self._generate_json(messages)
            except LLMProviderError as exc:
                raise AnalysisError(f"provider failed: {type(exc).__name__}") from exc
            try:
                output = parse_analysis(response.content)
                break
            except AnalysisError as exc:
                logger.warning("Topic analysis output invalid (attempt %d): %s", attempt + 1, exc)
                if attempt == 1:
                    raise

        by_key: dict[str, Agent] = {}
        for agent in builtins:
            by_key[agent.role.lower()] = agent
            by_key[agent.name.lower()] = agent
        picks: list[tuple[Agent, str]] = []
        unmatched: list[str] = []
        for pick in output.builtin_agents:
            key = pick.role.lower().strip()
            agent = by_key.get(key) or next(
                (a for k, a in by_key.items() if re.search(rf"\b{re.escape(k)}\b", key)), None
            )
            if agent is None:
                unmatched.append(pick.role[:40])
                continue
            if all(agent.id != a.id for a, _ in picks):
                picks.append((agent, pick.reason or agent.description))
        if unmatched:
            logger.info("Topic analysis named unknown built-in roles: %s", unmatched)

        max_agents = max(MIN_AGENTS, settings.DEBATE_MAX_AGENTS)
        target = min(max(output.recommended_agent_count, MIN_AGENTS), max_agents)
        picks = picks[:max_agents]
        room = max(0, min(settings.DEBATE_MAX_SPECIALISTS, target - len(picks), max_agents - len(picks)))
        relevance = " ".join(
            [topic, context or "", output.main_domain, *output.secondary_domains, *output.key_questions]
        )
        selected_builtins = [a for a, _ in picks]
        specialists, rejected = validate_specialists(
            output.specialists, selected_builtins, relevance_text=relevance, limit=room
        )
        for item in rejected:
            logger.info("Rejected specialist %r: %s", item["name"], item["reason"])

        if len(picks) + len(specialists) < MIN_AGENTS:
            # Keep the analysis (and any valid specialists) and complete the
            # panel with the deterministic topic-keyword selector.
            from app.services.agent_selection import fallback_select

            for agent, reason in fallback_select(topic, builtins):
                if len(picks) + len(specialists) >= MIN_AGENTS:
                    break
                if all(agent.id != a.id for a, _ in picks):
                    picks.append((agent, reason))
            logger.info("Topic analysis panel completed with keyword-selected built-ins")
        if len(picks) + len(specialists) < MIN_AGENTS:
            raise AnalysisError("analysis selected fewer than two usable agents")

        return TopicAnalysis(
            main_domain=output.main_domain,
            secondary_domains=output.secondary_domains,
            key_questions=output.key_questions,
            recommended_agent_count=target,
            builtins=picks,
            specialists=specialists,
            rejected=rejected,
            specialists_rationale=output.specialists_rationale,
        )
