"""Topic-aware automatic agent selection.

``AgentSelectionService.recommend`` asks the shared LLM provider for a
focused, topic-relevant selection of active core agents and always validates
the model output against the agents that actually exist in the database.
When the provider fails or returns unusable data the service falls back to a
deterministic keyword selector instead of returning every active agent.
"""

import json
import logging
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMMessage, LLMProviderError, LLMResponse
from app.llm.factory import get_llm_provider
from app.models.agent import Agent
from app.schemas.debate import MIN_AGENTS
from app.services.agent_service import list_active_core_agents

logger = logging.getLogger(__name__)

# Groq reasoning models spend completion tokens on reasoning before the visible
# answer; 32000 matches the headroom already used by claim extraction.
RECOMMENDATION_MAX_TOKENS = 32000

SELECTION_SOURCE_LLM: Literal["llm"] = "llm"
SELECTION_SOURCE_FALLBACK: Literal["fallback"] = "fallback"

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class AgentSelectionError(Exception):
    """Raised when the LLM selection fails or its output is unusable."""


class InsufficientAgentsError(AgentSelectionError):
    """Raised when too few active core agents exist to build a selection."""


class LLMSelectionItem(BaseModel):
    """One selection entry returned by the language model."""

    id: str | None = None
    role: str = Field(min_length=1)
    reason: str | None = None

    @field_validator("id", "role", "reason", mode="before")
    @classmethod
    def _strip_values(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

_SYSTEM_PROMPT = (
    "You select the most relevant expert debate agents for a given topic.\n"
    "You receive a JSON list of available agents, each with an id, role, name "
    "and description. Rules:\n"
    "- Select ONLY agents from the provided list, using the exact id and role "
    "given for each one.\n"
    "- Choose a focused set of experts whose capabilities are relevant to the "
    "topic; do not select every agent by default.\n"
    "- Prefer diverse relevant perspectives; when at least two agents are "
    "suitable, select at least two.\n"
    "- If the topic is broad, select a balanced group of relevant perspectives.\n"
    "- Give each selected agent a short one-sentence reason tied to the topic.\n"
    "Respond with ONLY a JSON object (no markdown, no commentary), e.g.\n"
    '{"agents": [{"id": "...", "role": "doctor", "reason": "..."}]}'
)

# Deterministic fallback lexicon: a keyword hit in the topic scores the role.
_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "economist": (
        "econom", "cost", "price", "market", "budget", "financ", "tax",
        "trade", "invest", "inflation", "wage", "employ", "gdp", "subsid",
        "spend", "revenue", "monetary", "fiscal", "profit", "unemployment",
    ),
    "lawyer": (
        "law", "legal", "regulat", "right", "court", "liab", "complian",
        "privacy", "contract", "legislat", "statut", "licens", "litigat",
        "constitutional", "patent", "copyright", "jurisdiction", "criminal",
    ),
    "scientist": (
        "scient", "research", "study", "experiment", "data", "evidence",
        "hypoth", "causal", "statistic", "methodolog", "peer review",
        "replicat", "empirical", "technolog", "software", "algorithm",
        "digital", "automat", "artificial intelligence", "autonomous",
        "robot", "comput", "innovation",
    ),
    "doctor": (
        "health", "medic", "patient", "diseas", "diagnos", "hospital",
        "clinic", "treatment", "doctor", "symptom", "therap", "surgery",
        "epidem", "vaccine", "mental health", "nurs",
    ),
    "ethicist": (
        "ethic", "moral", "fair", "justice", "consent", "harm", "bias",
        "equity", "values", "societal", "dignity", "autonomy", "discrimin",
        "welfare", "equality",
    ),
    "analyst": (
        "analy", "compar", "trade-off", "tradeoff", "risk", "decision",
        "criteri", "synthes", "overview", "pros and cons", "assessment",
        "metric", "kpi", "benchmark", "strateg",
    ),
}

# When the topic gives no signal at all, pad with these balanced roles first.
_BALANCED_PAD_ROLES = ("analyst", "ethicist")


def _strip_code_fences(raw: str) -> str:
    match = _FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def parse_selection_payload(raw: str) -> list[LLMSelectionItem]:
    """Parse the model's JSON object into validated selection entries.

    Raises AgentSelectionError for anything that is not a JSON object with an
    ``agents`` list of selection entries.
    """
    text = _strip_code_fences(raw or "")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise AgentSelectionError(
            "The language model did not return a JSON object of selected agents"
        )
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AgentSelectionError(
            "The language model returned malformed JSON for agent selection"
        ) from exc
    try:
        payload = data if isinstance(data, dict) else None
        items = payload.get("agents") if payload is not None else None
        if not isinstance(items, list):
            raise AgentSelectionError(
                "The language model response is missing the agents list"
            )
        return [LLMSelectionItem.model_validate(item) for item in items]
    except (ValidationError, AgentSelectionError) as exc:
        if isinstance(exc, AgentSelectionError):
            raise
        raise AgentSelectionError(
            "The language model returned invalid agent selections"
        ) from exc


def _matched_keywords(topic_lower: str, role: str) -> list[str]:
    return [kw for kw in _ROLE_KEYWORDS.get(role, ()) if kw in topic_lower]


def fallback_select(topic: str, agents: list[Agent]) -> list[tuple[Agent, str]]:
    """Deterministic topic/keyword selection used when the LLM is unusable.

    Agents with topic-keyword matches come first (most matches first); the
    selection is padded to MIN_AGENTS with balanced perspectives when needed.
    Never returns more agents than matched plus the minimum padding, and never
    falls back to "every active agent".
    """
    topic_lower = topic.lower()
    matched: list[tuple[Agent, list[str]]] = []
    for agent in agents:
        hits = _matched_keywords(topic_lower, agent.role.lower())
        if hits:
            matched.append((agent, hits))

    if matched:
        matched.sort(key=lambda pair: (-len(pair[1]), pair[0].name))
        pairs = [
            (
                agent,
                f"Topic match: {', '.join(sorted(hits)[:3])}. {agent.description}",
            )
            for agent, hits in matched
        ]
    else:
        pairs = []

    if len(pairs) < MIN_AGENTS:
        have = {agent.role.lower() for agent, _ in pairs}
        pad_order = sorted(
            agents,
            key=lambda agent: (
                _BALANCED_PAD_ROLES.index(agent.role.lower())
                if agent.role.lower() in _BALANCED_PAD_ROLES
                else len(_BALANCED_PAD_ROLES),
                agent.name,
            ),
        )
        pad_reason = (
            "Complementary perspective."
            if pairs
            else "Balanced perspective for a broad topic."
        )
        for agent in pad_order:
            if agent.role.lower() in have:
                continue
            pairs.append((agent, f"{pad_reason} {agent.description}"))
            have.add(agent.role.lower())
            if len(pairs) >= MIN_AGENTS:
                break

    return pairs


class AgentSelectionService:
    """Topic-aware selector over the active core agents in the database."""

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def recommend(
        self, db: AsyncSession, topic: str
    ) -> tuple[list[tuple[Agent, str]], str]:
        """Return ``([(agent, reason), ...], source)`` for the given topic.

        The LLM path is always validated against the active agents fetched
        from the database; any provider or output failure degrades to the
        deterministic fallback rather than to "every agent".
        """
        agents = await self._active_agents(db)
        try:
            pairs = await self._llm_select(topic, agents)
            return pairs, SELECTION_SOURCE_LLM
        except AgentSelectionError as exc:
            logger.warning("LLM agent selection unavailable, using fallback: %s", exc)
        except Exception:
            logger.exception("Unexpected agent selection failure, using fallback")
        return fallback_select(topic, agents), SELECTION_SOURCE_FALLBACK

    async def select_fallback(self, db: AsyncSession, topic: str) -> list[Agent]:
        """Deterministic topic-aware selection used during debate creation."""
        agents = await self._active_agents(db)
        return [agent for agent, _ in fallback_select(topic, agents)]

    async def _active_agents(self, db: AsyncSession) -> list[Agent]:
        agents = await list_active_core_agents(db)
        if len(agents) < MIN_AGENTS:
            raise InsufficientAgentsError(
                "Not enough active core agents are available for automatic "
                f"selection (need at least {MIN_AGENTS})"
            )
        return agents

    async def _llm_select(
        self, topic: str, agents: list[Agent]
    ) -> list[tuple[Agent, str]]:
        """Ask the provider for a selection and validate it against ``agents``."""
        roster = [
            {
                "id": str(agent.id),
                "role": agent.role,
                "name": agent.name,
                "description": agent.description,
            }
            for agent in agents
        ]
        user_prompt = (
            f"Debate topic: {topic}\n\n"
            f"Available agents (JSON):\n{json.dumps(roster, indent=2)}\n\n"
            "Select the most relevant agents for this topic and return the "
            "JSON object."
        )

        try:
            response: LLMResponse = await self.provider.generate(
                [
                    LLMMessage(role="system", content=_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=user_prompt),
                ],
                temperature=0.0,
                max_tokens=RECOMMENDATION_MAX_TOKENS,
            )
        except LLMProviderError as exc:
            raise AgentSelectionError(f"LLM provider failed: {exc}") from exc

        items = parse_selection_payload(response.content)

        by_role = {agent.role.lower(): agent for agent in agents}
        pairs: list[tuple[Agent, str]] = []
        seen: set[str] = set()
        for item in items:
            role = (item.role or "").lower()
            agent = by_role.get(role)
            if agent is None:
                # Unknown, inactive or non-core role: never trusted.
                continue
            if item.id is not None:
                try:
                    item_uuid = UUID(str(item.id))
                except ValueError:
                    continue
                if item_uuid != agent.id:
                    # An id that does not match the supplied agent is dropped.
                    continue
            if role in seen:
                continue
            seen.add(role)
            reason = (item.reason or "").strip() or agent.description
            pairs.append((agent, reason))

        if len(pairs) < MIN_AGENTS:
            raise AgentSelectionError(
                "The language model returned fewer than "
                f"{MIN_AGENTS} usable agent selections"
            )
        return pairs
