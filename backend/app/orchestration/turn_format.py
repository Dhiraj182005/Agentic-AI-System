"""Structured debate turns.

Each agent turn is requested as a small JSON object so the debate reads as
a real exchange (position, one main argument, what it rebuts, concessions,
uncertainty) instead of parallel essays. The structured form is stored in
``debate_messages.structured``; ``content`` keeps a readable rendering of it
so every existing consumer (claim extraction, fallacy detection, judge,
verdict, PDF) keeps working. When a model ignores the format, its real text
is stored unstructured - nothing is invented and no extra call is made.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError, field_validator

MAX_FIELD_CHARS = 1500
MAX_LIST_ITEMS = 5
MAX_ITEM_CHARS = 400

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _clean(value, limit: int = MAX_FIELD_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[:limit].rstrip() + " ..."
    return text


def _clean_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items = [_clean(item, MAX_ITEM_CHARS) for item in value if str(item or "").strip()]
    return items[:MAX_LIST_ITEMS]


class RebuttalTarget(BaseModel):
    ref: str = ""
    argument: str = ""


class StructuredTurn(BaseModel):
    """One agent turn. Only ``position``, ``main_argument`` and ``reasoning``
    are required; everything else is optional and may stay empty."""

    position: str = Field(min_length=1)
    position_changed: bool = False
    main_argument: str = Field(min_length=1)
    rebuttal_to: RebuttalTarget | None = None
    reasoning: str = Field(min_length=1)
    factual_claims: list[str] = []
    evidence_references: list[str] = []
    concession: str | None = None
    recommendation: str | None = None
    uncertainties: list[str] = []

    @field_validator("position", "main_argument", "reasoning", mode="before")
    @classmethod
    def _required(cls, value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("required text field is empty")
        return _clean(value)

    @field_validator("concession", "recommendation", mode="before")
    @classmethod
    def _optional(cls, value):
        text = _clean(value) if value is not None else ""
        return text if text and text.lower() not in ("none", "null", "n/a", "-") else None

    @field_validator("factual_claims", "evidence_references", "uncertainties", mode="before")
    @classmethod
    def _lists(cls, value) -> list[str]:
        return _clean_list(value)

    @field_validator("position_changed", mode="before")
    @classmethod
    def _bool(cls, value) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1")
        return bool(value)

    @field_validator("rebuttal_to", mode="before")
    @classmethod
    def _rebuttal(cls, value):
        if value is None or value == "" or value == {}:
            return None
        if isinstance(value, str):
            return {"ref": "", "argument": _clean(value, MAX_ITEM_CHARS)}
        if isinstance(value, dict):
            return {
                "ref": str(value.get("ref") or "").strip(),
                "argument": _clean(value.get("argument"), MAX_ITEM_CHARS),
            }
        return None

    def word_count(self) -> int:
        parts = [self.position, self.main_argument, self.reasoning,
                 self.concession or "", self.recommendation or ""]
        parts += self.factual_claims + self.evidence_references + self.uncertainties
        return sum(len(part.split()) for part in parts)


def parse_turn(raw: str) -> StructuredTurn | None:
    """Parse a model reply into a StructuredTurn, or None if it isn't one."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        if not isinstance(data, dict):
            return None
        return StructuredTurn(**data)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return None


@dataclass
class TranscriptEntry:
    """One earlier turn as shown to the next speaker."""

    round_number: int
    agent_name: str
    content: str
    structured: dict | None = None
    message_id: str | None = None
    message_type: str = ""
    agent_role: str = ""

    @property
    def ref(self) -> str:
        return f"R{self.round_number}-{self.agent_name}"


@dataclass
class ResolvedTurn:
    structured: dict
    content: str
    notes: list[str] = field(default_factory=list)


def resolve_turn(turn: StructuredTurn, transcript: list[TranscriptEntry], speaker: str) -> ResolvedTurn:
    """Validate the rebuttal reference against real earlier turns and build
    the stored structured payload plus its readable rendering."""
    by_ref = {entry.ref.casefold(): entry for entry in transcript}
    rebuttal = None
    notes: list[str] = []
    if turn.rebuttal_to is not None and (turn.rebuttal_to.ref or turn.rebuttal_to.argument):
        target = by_ref.get(turn.rebuttal_to.ref.casefold()) if turn.rebuttal_to.ref else None
        if target is not None and target.agent_name == speaker:
            target = None  # an agent cannot rebut itself
        if target is not None:
            rebuttal = {
                "ref": target.ref,
                "message_id": target.message_id,
                "agent_name": target.agent_name,
                "round_number": target.round_number,
                "argument": turn.rebuttal_to.argument,
            }
        elif turn.rebuttal_to.argument:
            # Keep what the agent said it responds to, but never invent a link.
            rebuttal = {"ref": None, "message_id": None, "agent_name": None,
                        "round_number": None, "argument": turn.rebuttal_to.argument}
            if turn.rebuttal_to.ref:
                notes.append(f"unknown rebuttal reference {turn.rebuttal_to.ref!r}")

    structured = {
        "position": turn.position,
        "position_changed": turn.position_changed,
        "main_argument": turn.main_argument,
        "rebuttal_to": rebuttal,
        "reasoning": turn.reasoning,
        "factual_claims": turn.factual_claims,
        "evidence_references": turn.evidence_references,
        "concession": turn.concession,
        "recommendation": turn.recommendation,
        "uncertainties": turn.uncertainties,
        "word_count": turn.word_count(),
    }
    return ResolvedTurn(structured=structured, content=render_turn(structured), notes=notes)


def render_turn(structured: dict) -> str:
    """Readable markdown for the full transcript, analysis and the PDF."""
    lines = [f"**Position{' (revised)' if structured.get('position_changed') else ''}:** {structured['position']}"]
    rebuttal = structured.get("rebuttal_to")
    if rebuttal:
        who = (
            f"{rebuttal['agent_name']} (round {rebuttal['round_number']})"
            if rebuttal.get("agent_name")
            else "an earlier argument"
        )
        quoted = f' - "{rebuttal["argument"]}"' if rebuttal.get("argument") else ""
        lines.append(f"**Responding to:** {who}{quoted}")
    lines.append(f"**Main argument:** {structured['main_argument']}")
    lines.append(f"**Reasoning:** {structured['reasoning']}")
    for key, label in (
        ("factual_claims", "Factual claims"),
        ("evidence_references", "Evidence referenced (not yet verified)"),
    ):
        if structured.get(key):
            lines.append(f"**{label}:**")
            lines.extend(f"- {item}" for item in structured[key])
    if structured.get("concession"):
        lines.append(f"**Concession:** {structured['concession']}")
    if structured.get("recommendation"):
        lines.append(f"**Recommendation:** {structured['recommendation']}")
    if structured.get("uncertainties"):
        lines.append("**Uncertainties:**")
        lines.extend(f"- {item}" for item in structured["uncertainties"])
    return "\n\n".join(lines)
