import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.llm.base import (
    LLMMessage,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.llm.factory import get_llm_provider
from app.models.fallacy import FALLACY_SEVERITIES, FALLACY_TYPES

logger = logging.getLogger(__name__)

# The Groq model is a reasoning model: chain-of-thought tokens count against
# max_tokens (see claim_extraction). Detection runs on a single message with
# a short prompt, so 16000 leaves comfortable headroom for reasoning plus the
# JSON answer without risking an empty completion.
FALLACY_MAX_TOKENS = 16000
MAX_EXPLANATION_LENGTH = 600
MAX_SPAN_LENGTH = 500
MAX_CONTEXT_CHARS = 600
MAX_MESSAGE_CHARS = 4000

FALLACY_TYPE_ALIASES = {
    "ad_hominem": "ad_hominem",
    "ad hominem": "ad_hominem",
    "adhominem": "ad_hominem",
    "personal_attack": "ad_hominem",
    "straw_man": "straw_man",
    "straw man": "straw_man",
    "strawman": "straw_man",
    "false_dilemma": "false_dilemma",
    "false dilemma": "false_dilemma",
    "false_choice": "false_dilemma",
    "black_or_white": "false_dilemma",
    "slippery_slope": "slippery_slope",
    "slippery slope": "slippery_slope",
    "appeal_to_authority": "appeal_to_authority",
    "appeal to authority": "appeal_to_authority",
    "argument_from_authority": "appeal_to_authority",
    "appeal_to_emotion": "appeal_to_emotion",
    "appeal to emotion": "appeal_to_emotion",
    "emotional_manipulation": "appeal_to_emotion",
    "hasty_generalization": "hasty_generalization",
    "hasty generalization": "hasty_generalization",
    "overgeneralization": "hasty_generalization",
    "circular_reasoning": "circular_reasoning",
    "circular reasoning": "circular_reasoning",
    "begging_the_question": "circular_reasoning",
    "red_herring": "red_herring",
    "red herring": "red_herring",
    "false_cause": "false_cause",
    "false cause": "false_cause",
    "post_hoc": "false_cause",
    "cum_hoc": "false_cause",
    "bandwagon": "bandwagon",
    "appeal_to_popularity": "bandwagon",
    "appeal to popularity": "bandwagon",
    "loaded_question": "loaded_question",
    "loaded question": "loaded_question",
    "complex_question": "loaded_question",
    "tu_quoque": "tu_quoque",
    "tu quoque": "tu_quoque",
    "whataboutism": "tu_quoque",
    "no_fallacy": "no_fallacy",
    "no fallacy": "no_fallacy",
    "none": "no_fallacy",
    "no": "no_fallacy",
}

SEVERITY_ALIASES = {
    "low": "low",
    "minor": "low",
    "medium": "medium",
    "moderate": "medium",
    "med": "medium",
    "high": "high",
    "severe": "high",
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class FallacyDetectionError(Exception):
    """Raised when fallacy analysis fails or the LLM output is unusable."""


class DetectedFallacy(BaseModel):
    """A single validated fallacy analysis result produced by the LLM."""

    fallacy_type: str
    severity: str
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1)
    evidence_span: str | None = None

    @field_validator("fallacy_type", mode="before")
    @classmethod
    def _normalize_fallacy_type(cls, value) -> str:
        if not isinstance(value, str):
            raise ValueError(
                "fallacy_type must be one of: " + ", ".join(FALLACY_TYPES)
            )
        key = (
            value.strip()
            .lower()
            .rstrip(":.!?")
            .replace("-", "_")
            .replace(" ", "_")
        )
        normalized = FALLACY_TYPE_ALIASES.get(key)
        if normalized is None:
            raise ValueError(
                "fallacy_type must be one of: " + ", ".join(FALLACY_TYPES)
            )
        return normalized

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value) -> str:
        if not isinstance(value, str):
            raise ValueError("severity must be low, medium or high")
        normalized = SEVERITY_ALIASES.get(value.strip().lower().rstrip(":.!?"))
        if normalized is None:
            raise ValueError("severity must be low, medium or high")
        return normalized

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value) -> float:
        if isinstance(value, bool):
            raise ValueError("confidence must be a number between 0 and 1")
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError as exc:
                raise ValueError(
                    "confidence must be a number between 0 and 1"
                ) from exc
        if not isinstance(value, (int, float)):
            raise ValueError("confidence must be a number between 0 and 1")
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError("confidence must be a number between 0 and 1")
        return float(value)

    @field_validator("explanation")
    @classmethod
    def _check_explanation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("explanation cannot be empty")
        if len(value) > MAX_EXPLANATION_LENGTH:
            value = value[:MAX_EXPLANATION_LENGTH].rstrip() + " [...]"
        return value

    @field_validator("evidence_span", mode="before")
    @classmethod
    def _check_span(cls, value) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("evidence_span must be a string or null")
        value = value.strip()
        if not value:
            return None
        if len(value) > MAX_SPAN_LENGTH:
            value = value[:MAX_SPAN_LENGTH].rstrip() + " [...]"
        return value

    @model_validator(mode="after")
    def _no_fallacy_needs_no_span(self) -> "DetectedFallacy":
        if self.fallacy_type == "no_fallacy":
            self.evidence_span = None
        return self


SYSTEM_PROMPT = (
    "You analyze a single argument from an AI debate for logical and "
    "rhetorical fallacies.\n"
    "Rules:\n"
    "- Analyze the reasoning pattern objectively, using only the supplied "
    "text and context.\n"
    "- A fallacy is a flaw in the REASONING STRUCTURE, not a disagreeable or "
    "controversial conclusion. Disagreement is not a fallacy.\n"
    "- Do not label an argument fallacious because you disagree with its "
    "position or find it politically or ideologically objectionable. Remain "
    "neutral about every political, economic and social viewpoint.\n"
    "- Do not judge the speaker, their personality or their motives. Judge "
    "only the text of the argument.\n"
    "- Do not judge whether the underlying claim is factually true or false; "
    "truth of claims is a separate concern.\n"
    "- Strong claims, predictions and emotional language are not fallacies "
    "by themselves. Mentioning an expert is not automatically an appeal to "
    "authority. Correlation mentioned without causation is not automatically "
    "a false cause.\n"
    "- Prefer 'no_fallacy' whenever the evidence for a fallacy is weak or "
    "ambiguous. A false accusation is worse than a missed fallacy.\n"
    "- When a fallacy IS present, name the exact fallacy type, quote the "
    "shortest text span that shows the pattern in evidence_span, and state in "
    "the explanation WHY that pattern qualifies as this fallacy.\n"
    "- fallacy_type: one of " + ", ".join(FALLACY_TYPES) + ".\n"
    "- severity: low, medium or high - how much the fallacy undermines this "
    "argument's reasoning (not whether any claim is false).\n"
    "- confidence: a number between 0 and 1 for how certain the diagnosis "
    "is.\n"
    "- explanation: 1-3 concise sentences. No essays and no hidden "
    "chain-of-thought.\n"
    "Respond with ONLY a JSON object (no markdown, no commentary):\n"
    '{"fallacy_type": "...", "severity": "...", "confidence": 0.0, '
    '"explanation": "...", "evidence_span": "..."}\n'
    "When no fallacy applies use:\n"
    '{"fallacy_type": "no_fallacy", "severity": "low", "confidence": 0.9, '
    '"explanation": "The argument does not show a clear recognizable logical '
    'fallacy.", "evidence_span": null}'
)


def build_detection_prompt(
    content: str,
    agent_name: str,
    topic: str,
    context: str | None = None,
) -> str:
    content = (content or "").strip()
    if len(content) > MAX_MESSAGE_CHARS:
        content = content[:MAX_MESSAGE_CHARS] + " [...]"
    lines = [
        f"Debate topic: {(topic or '').strip()[:500]}",
        f"Argument by {agent_name}:",
        content,
    ]
    if context:
        context = context.strip()
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS] + " [...]"
        lines.append("")
        lines.append(f"Previous message for context (do not analyze it): {context}")
    lines.append("")
    lines.append("Analyze the argument for fallacies.")
    return "\n".join(lines)


def _strip_code_fences(raw: str) -> str:
    match = _FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def parse_fallacy_payload(raw: str) -> DetectedFallacy:
    """Parse and validate raw LLM output into a fallacy analysis result.

    Raises FallacyDetectionError when the output cannot be used; invalid
    results are never persisted.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise FallacyDetectionError(
            "The language model returned an empty response"
        )

    text = _strip_code_fences(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise FallacyDetectionError(
            "The language model did not return a JSON object for fallacy analysis"
        )

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise FallacyDetectionError(
            "The language model returned malformed JSON for fallacy analysis"
        ) from exc

    if not isinstance(parsed, dict):
        raise FallacyDetectionError(
            "The language model did not return a JSON object for fallacy analysis"
        )

    try:
        return DetectedFallacy(**parsed)
    except ValidationError as exc:
        raise FallacyDetectionError(
            "The language model returned an invalid fallacy analysis result"
        ) from exc


class FallacyDetectionService:
    """Analyzes a single debate message for fallacies via the shared LLM provider."""

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def detect(
        self,
        content: str,
        agent_name: str,
        topic: str,
        context: str | None = None,
    ) -> DetectedFallacy:
        prompt = build_detection_prompt(content, agent_name, topic, context)

        try:
            response = await self.provider.generate(
                [
                    LLMMessage(role="system", content=SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=FALLACY_MAX_TOKENS,
            )
        except FallacyDetectionError:
            raise
        except LLMProviderError as exc:
            logger.error(
                "Fallacy detection LLM call failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            if isinstance(exc, (LLMProviderAPIError, LLMTimeoutError)):
                raise FallacyDetectionError(
                    "Fallacy analysis failed because the language model "
                    "provider did not respond"
                ) from exc
            raise FallacyDetectionError(
                "Fallacy analysis failed because the language model returned "
                "no usable output"
            ) from exc
        except Exception as exc:  # unexpected failures
            logger.error(
                "Fallacy detection LLM call failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise FallacyDetectionError(
                "Fallacy analysis failed because the language model provider "
                "did not respond"
            ) from exc

        return parse_fallacy_payload(response.content)
