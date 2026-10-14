import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.llm.base import (
    LLMMessage,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

# Reasoning tokens count against max_tokens (see claim_extraction): 16000
# leaves comfortable headroom for the reasoning model to answer a single
# message evaluation.
EVALUATION_MAX_TOKENS = 16000
MAX_EXPLANATION_LENGTH = 500
MAX_CONTEXT_CHARS = 600
MAX_MESSAGE_CHARS = 4000
MAX_SUPPORTING_ITEMS = 6

SCORE_FIELDS = (
    "logical_soundness",
    "evidence_score",
    "relevance_score",
    "effectiveness_score",
    "overall_score",
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ArgumentEvaluationError(Exception):
    """Raised when argument evaluation fails or the LLM output is unusable."""


def _validate_score(value, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number between 0 and 10")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"{field_name} must be a number between 0 and 10"
            ) from exc
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number between 0 and 10")
    value = float(value)
    if not 0.0 <= value <= 10.0:
        raise ValueError(f"{field_name} must be between 0 and 10")
    return value


class ArgumentEvaluationOutput(BaseModel):
    """A single validated argument quality result produced by the LLM.

    Scores describe reasoning and presentation quality on a 0-10 scale.
    They never assert whether the underlying claims are true.
    """

    logical_soundness: float = Field(ge=0.0, le=10.0)
    evidence_score: float = Field(ge=0.0, le=10.0)
    relevance_score: float = Field(ge=0.0, le=10.0)
    effectiveness_score: float = Field(ge=0.0, le=10.0)
    overall_score: float = Field(ge=0.0, le=10.0)
    explanation: str = Field(min_length=1)

    @field_validator(
        "logical_soundness",
        "evidence_score",
        "relevance_score",
        "effectiveness_score",
        "overall_score",
        mode="before",
    )
    @classmethod
    def _check_score(cls, value, info) -> float:
        return _validate_score(value, info.field_name)

    @field_validator("explanation")
    @classmethod
    def _check_explanation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("explanation cannot be empty")
        if len(value) > MAX_EXPLANATION_LENGTH:
            value = value[:MAX_EXPLANATION_LENGTH].rstrip() + " [...]"
        return value


SYSTEM_PROMPT = (
    "You evaluate the QUALITY of a single argument from an AI debate.\n"
    "Score each dimension from 0 to 10:\n"
    "- logical_soundness: is the reasoning internally coherent and free of "
    "obvious logical flaws?\n"
    "- evidence_score: does the argument support itself with concrete facts, "
    "examples or cited evidence (as presented in the text)?\n"
    "- relevance_score: does it stay on the debate topic?\n"
    "- effectiveness_score: how clearly and persuasively is it delivered?\n"
    "- overall_score: the balanced overall quality of the argument.\n"
    "Scale: 0-2 very weak, 3-4 weak, 5-6 moderate, 7-8 strong, 9-10 "
    "excellent.\n"
    "Rules:\n"
    "- Score argument QUALITY only. A high score does NOT mean the argument's "
    "claims are factually true and a low score does NOT mean they are false. "
    "Never present a score as a truth verdict.\n"
    "- Do not judge the speaker, their personality or their motives, and "
    "remain neutral about every political, economic and social viewpoint.\n"
    "- Use only the supplied text and supporting context. Do not invent "
    "facts, sources or quotations.\n"
    "- Supporting context about already-retrieved evidence is reference only: "
    "do not re-verify claims and do not decide whether any claim is true.\n"
    "- explanation: one or two concise sentences justifying the scores. Only "
    "the justification - no hidden chain-of-thought, no step-by-step "
    "reasoning.\n"
    "Respond with ONLY a JSON object (no markdown, no commentary):\n"
    '{"logical_soundness": 0, "evidence_score": 0, "relevance_score": 0, '
    '"effectiveness_score": 0, "overall_score": 0.0, "explanation": "..."}'
)


def build_evaluation_prompt(
    content: str,
    agent_name: str,
    topic: str,
    context: str | None = None,
    supporting_context: list[str] | None = None,
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
        lines.append(f"Previous message for context (do not evaluate it): {context}")

    supporting = (supporting_context or [])[:MAX_SUPPORTING_ITEMS]
    if supporting:
        lines.append("")
        lines.append(
            "Stored context for claims inside this argument (reference only, "
            "do not re-verify):"
        )
        for item in supporting:
            item = item.strip()
            if len(item) > MAX_CONTEXT_CHARS:
                item = item[:MAX_CONTEXT_CHARS] + " [...]"
            lines.append(f"- {item}")

    lines.append("")
    lines.append("Evaluate the argument's quality.")
    return "\n".join(lines)


def _strip_code_fences(raw: str) -> str:
    match = _FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def parse_evaluation_payload(raw: str) -> ArgumentEvaluationOutput:
    """Parse and validate raw LLM output into an evaluation result.

    Raises ArgumentEvaluationError when the output cannot be used; invalid
    results are never persisted.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ArgumentEvaluationError(
            "The language model returned an empty response"
        )

    text = _strip_code_fences(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ArgumentEvaluationError(
            "The language model did not return a JSON object for evaluation"
        )

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ArgumentEvaluationError(
            "The language model returned malformed JSON for evaluation"
        ) from exc

    if not isinstance(parsed, dict):
        raise ArgumentEvaluationError(
            "The language model did not return a JSON object for evaluation"
        )

    try:
        return ArgumentEvaluationOutput(**parsed)
    except ValidationError as exc:
        raise ArgumentEvaluationError(
            "The language model returned an invalid evaluation result"
        ) from exc


class ArgumentEvaluationService:
    """Evaluates a single debate message's argument quality via the shared LLM provider."""

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def evaluate(
        self,
        content: str,
        agent_name: str,
        topic: str,
        context: str | None = None,
        supporting_context: list[str] | None = None,
    ) -> ArgumentEvaluationOutput:
        prompt = build_evaluation_prompt(
            content, agent_name, topic, context, supporting_context
        )

        try:
            response = await self.provider.generate(
                [
                    LLMMessage(role="system", content=SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=EVALUATION_MAX_TOKENS,
            )
        except ArgumentEvaluationError:
            raise
        except LLMProviderError as exc:
            logger.error(
                "Argument evaluation LLM call failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            if isinstance(exc, (LLMProviderAPIError, LLMTimeoutError)):
                raise ArgumentEvaluationError(
                    "Argument evaluation failed because the language model "
                    "provider did not respond"
                ) from exc
            raise ArgumentEvaluationError(
                "Argument evaluation failed because the language model "
                "returned no usable output"
            ) from exc
        except Exception as exc:  # unexpected failures
            logger.error(
                "Argument evaluation LLM call failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise ArgumentEvaluationError(
                "Argument evaluation failed because the language model "
                "provider did not respond"
            ) from exc

        return parse_evaluation_payload(response.content)
