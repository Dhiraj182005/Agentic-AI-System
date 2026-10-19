from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExpertSelectionMode = Literal["auto", "manual"]
DebateMode = Literal["balanced", "pro_con"]

MIN_AGENTS = 2
MAX_AGENTS = 50
MAX_TOPIC_LENGTH = 1000
MIN_ROUNDS = 1
MAX_ROUNDS = 10
MAX_DOMAIN_TAGS = 10
MAX_DOMAIN_TAG_LENGTH = 50


class DebateCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_LENGTH)
    expert_selection_mode: ExpertSelectionMode = "manual"
    agent_ids: list[str] = Field(default_factory=list, max_length=MAX_AGENTS)
    domain_tags: list[str] | None = Field(default=None, max_length=MAX_DOMAIN_TAGS)
    mode: DebateMode = "balanced"
    total_rounds: int = Field(default=3, ge=MIN_ROUNDS, le=MAX_ROUNDS)
    verify_evidence: bool = True

    @field_validator("topic")
    @classmethod
    def _strip_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Topic cannot be empty or whitespace only")
        return value

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


class RecommendAgentsRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_LENGTH)

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


class RecommendAgentsResponse(BaseModel):
    topic: str
    selection_mode: ExpertSelectionMode = "auto"
    selection_source: Literal["llm", "fallback"] = "llm"
    agents: list[RecommendedAgent]


class DebateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic: str
    expert_selection_mode: str
    domain_tags: list[str] | None
    status: str
    mode: str
    total_rounds: int
    verify_evidence: bool
    round_count: int
    agents: list[DebateAgentResponse]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


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
