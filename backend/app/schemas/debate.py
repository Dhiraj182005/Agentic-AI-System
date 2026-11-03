from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExpertSelectionMode = Literal["auto", "manual"]
DebateMode = Literal["balanced", "pro_con"]

MIN_AGENTS = 2
MAX_AGENTS = 50
MAX_TOPIC_LENGTH = 1000
MAX_CONTEXT_LENGTH = 2000
MIN_ROUNDS = 1
MAX_ROUNDS = 10
MAX_DOMAIN_TAGS = 10
MAX_DOMAIN_TAG_LENGTH = 50


class DebateCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_LENGTH)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT_LENGTH)
    expert_selection_mode: ExpertSelectionMode = "manual"
    agent_ids: list[str] = Field(default_factory=list, max_length=MAX_AGENTS)
    domain_tags: list[str] | None = Field(default=None, max_length=MAX_DOMAIN_TAGS)
    mode: DebateMode = "balanced"
    total_rounds: int = Field(default=3, ge=MIN_ROUNDS, le=MAX_ROUNDS)
    verify_evidence: bool = True
    # AI specialist roles reviewed by the user (auto selection only); each is
    # re-validated on the server before any debate-scoped agent is created.
    specialists: list[dict] = Field(default_factory=list, max_length=6)

    @field_validator("topic")
    @classmethod
    def _strip_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Topic cannot be empty or whitespace only")
        return value

    @field_validator("context")
    @classmethod
    def _strip_context(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("agent_ids")
    @classmethod
    def _normalize_agent_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in value:
            role = raw.strip().lower()
            if not role:
                raise ValueError("Agent identifiers cannot be empty")
            if role in normalized:
                raise ValueError(f"Duplicate agent selected: {role}")
            normalized.append(role)
        return normalized

    @field_validator("domain_tags")
    @classmethod
    def _normalize_domain_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        tags: list[str] = []
        for raw in value:
            tag = raw.strip()
            if not tag:
                raise ValueError("Domain tags cannot be empty")
            if len(tag) > MAX_DOMAIN_TAG_LENGTH:
                raise ValueError(
                    f"Domain tag cannot exceed {MAX_DOMAIN_TAG_LENGTH} characters"
                )
            tags.append(tag)
        return tags

    @model_validator(mode="after")
    def _require_agents_for_manual_mode(self) -> "DebateCreateRequest":
        if self.expert_selection_mode == "manual" and len(self.agent_ids) < MIN_AGENTS:
            raise ValueError(
                f"At least {MIN_AGENTS} agents are required to create a debate"
            )
        return self


class DebateAgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    role: str
    description: str
    # "builtin" or "dynamic" (debate-scoped AI specialist role).
    source: str = "builtin"
    definition: dict | None = None


class RecommendAgentsRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_LENGTH)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT_LENGTH)
    mode: DebateMode = "balanced"
    # Opt in to topic analysis with dynamic AI specialist roles.
    include_specialists: bool = False

    @field_validator("topic")
    @classmethod
    def _strip_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Topic cannot be empty or whitespace only")
        return value


class RecommendedAgent(BaseModel):
    id: UUID
    name: str
    role: str
    reason: str


class RecommendedSpecialist(BaseModel):
    name: str
    domain: str
    subdomain: str = ""
    expertise: str
    debate_objective: str
    instructions: list[str] = []
    capabilities: list[str] = []
    reason: str = ""


class TopicAnalysisSummary(BaseModel):
    main_domain: str
    secondary_domains: list[str] = []
    key_questions: list[str] = []
    recommended_agent_count: int
    specialists_rationale: str = ""


class RejectedSpecialist(BaseModel):
    name: str
    reason: str


class RecommendAgentsResponse(BaseModel):
    topic: str
    selection_mode: ExpertSelectionMode = "auto"
    selection_source: Literal["llm", "fallback"] = "llm"
    agents: list[RecommendedAgent]
    # Only with include_specialists: the topic analysis, proposed AI
    # specialist roles and any proposals rejected by validation.
    analysis: TopicAnalysisSummary | None = None
    specialists: list[RecommendedSpecialist] = []
    rejected_specialists: list[RejectedSpecialist] = []
    cached: bool = False


class DebateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic: str
    context: str | None = None
    expert_selection_mode: str
    domain_tags: list[str] | None
    status: str
    execution_state: str = "created"
    mode: str
    total_rounds: int
    verify_evidence: bool
    round_count: int
    agents: list[DebateAgentResponse]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None


class DebateListResponse(BaseModel):
    items: list[DebateResponse]


class TranscriptAgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    role: str


class TranscriptMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    round_number: int
    turn_number: int
    agent: TranscriptAgentResponse
    message_type: str
    content: str
    structured: dict | None = None
    created_at: datetime


class TranscriptResponse(BaseModel):
    debate_id: UUID
    messages: list[TranscriptMessageResponse]


class DebateRoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    round_number: int
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DebateRoundsResponse(BaseModel):
    debate_id: UUID
    rounds: list[DebateRoundResponse]
