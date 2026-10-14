import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.llm.base import (
    LLMMessage,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

CLAIM_TYPES = ("factual", "opinion", "prediction", "definition", "other")
CLAIM_TYPE_ALIASES = {
    "factual": "factual",
    "fact": "factual",
    "opinion": "opinion",
    "prediction": "prediction",
    "forecast": "prediction",
    "definition": "definition",
    "other": "other",
}

MAX_CLAIMS_PER_MESSAGE = 5
MAX_TOTAL_CLAIMS = 40
MAX_CLAIM_LENGTH = 1000
MAX_MESSAGES_PER_REQUEST = 40
MAX_MESSAGE_CONTENT_CHARS = 1500
# Root cause of the extract 502: the Groq model (openai/gpt-oss-20b) is a
# reasoning model whose chain-of-thought tokens count against max_tokens.
# Longer debates can need ~10k reasoning tokens plus several thousand tokens
# of JSON output; with a smaller budget Groq returns finish_reason=length and
# an empty content, which surfaced as a 502. 32000 gives comfortable headroom
# (measured: reasoning ~9.1k + output ~5.4k = ~14.5k completion tokens).
EXTRACTION_MAX_TOKENS = 32000

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ClaimExtractionError(Exception):
    """Raised when claim extraction fails or the LLM output is unusable."""


class ExtractedClaim(BaseModel):
    """A single validated claim produced by the extraction LLM."""

    message_id: str = Field(min_length=1)
    claim: str = Field(min_length=1, max_length=MAX_CLAIM_LENGTH)
    claim_type: str = "other"

    @field_validator("claim")
    @classmethod
    def _strip_claim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Claim cannot be empty or whitespace only")
        return value

    @field_validator("claim_type", mode="before")
    @classmethod
    def _normalize_claim_type(cls, value: Any) -> str:
        if not isinstance(value, str):
            return "other"
        return CLAIM_TYPE_ALIASES.get(value.strip().lower().rstrip(":.!?"), "other")


@dataclass
class MessageContext:
    """One debate message handed to the extractor."""

    message_id: UUID
    agent_id: UUID
    agent_name: str
    content: str


SYSTEM_PROMPT = (
    "You extract examinable claims from AI debate messages.\n"
    "A claim is a statement that could be examined against external evidence.\n"
    "For every claim output its message_id exactly as given, the claim text "
    "(preserving the original meaning), and a claim_type of one of: "
    "factual, opinion, prediction, definition, other.\n"
    "Rules:\n"
    "- Only extract claims that actually appear in the provided messages.\n"
    "- Never invent claims or add information not present in the message.\n"
    "- Do not judge whether any claim is true or false.\n"
    "- Do not convert every sentence into a claim; skip greetings, rhetorical "
    "questions, transitions and pure restatements.\n"
    "- Avoid duplicate claims within the same message.\n"
    "Respond with ONLY a JSON array (no markdown, no commentary), e.g.\n"
    '[{"message_id": "...", "claim": "...", "claim_type": "factual"}]\n'
    "Use an empty array if there are no claims."
)


def build_extraction_prompt(messages: list[MessageContext]) -> str:
    parts = []
    for context in messages[:MAX_MESSAGES_PER_REQUEST]:
        content = context.content.strip()
        if len(content) > MAX_MESSAGE_CONTENT_CHARS:
            content = content[:MAX_MESSAGE_CONTENT_CHARS] + " [...]"
        parts.append(
            f"Message {context.message_id} | Agent: {context.agent_name}:\n{content}"
        )
    return (
        "Extract the claims from these debate messages.\n\n" + "\n\n".join(parts)
    )


def _strip_code_fences(raw: str) -> str:
    match = _FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def parse_claims_payload(raw: str, valid_message_ids: set[str]) -> list[ExtractedClaim]:
    """Parse and validate raw LLM output into structured claims.

    Raises ClaimExtractionError when the output cannot be used at all;
    individual invalid items are dropped rather than persisted.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ClaimExtractionError("The language model returned an empty response")

    text = _strip_code_fences(raw)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ClaimExtractionError(
            "The language model did not return a JSON array of claims"
        )

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ClaimExtractionError(
            "The language model returned malformed JSON for claims"
        ) from exc

    if not isinstance(parsed, list):
        raise ClaimExtractionError(
            "The language model returned malformed JSON for claims"
        )

    if not parsed:
        return []

    claims: list[ExtractedClaim] = []
    seen: set[tuple[str, str]] = set()
    per_message: dict[str, int] = {}

    for item in parsed:
        if not isinstance(item, dict):
            continue
        raw_claim = item.get("claim")
        if not isinstance(raw_claim, str) or not raw_claim.strip():
            continue
        message_id = item.get("message_id")
        if not isinstance(message_id, str) or message_id not in valid_message_ids:
            continue
        try:
            claim = ExtractedClaim(
                message_id=message_id,
                claim=raw_claim[:MAX_CLAIM_LENGTH],
                claim_type=item.get("claim_type", "other"),
            )
        except ValueError:
            continue

        dedupe_key = (message_id, claim.claim.lower())
        if dedupe_key in seen:
            continue
        if per_message.get(message_id, 0) >= MAX_CLAIMS_PER_MESSAGE:
            continue
        if len(claims) >= MAX_TOTAL_CLAIMS:
            break

        seen.add(dedupe_key)
        per_message[message_id] = per_message.get(message_id, 0) + 1
        claims.append(claim)

    if not claims:
        raise ClaimExtractionError(
            "The language model output contained no usable claims"
        )

    return claims


class ClaimExtractionService:
    """Utility service that extracts claims using the shared LLM provider."""

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def extract(self, messages: list[MessageContext]) -> list[ExtractedClaim]:
        if not messages:
            raise ClaimExtractionError("No messages were provided for extraction")

        valid_ids = {str(m.message_id) for m in messages}
        prompt = build_extraction_prompt(messages)

        try:
            response = await self.provider.generate(
                [
                    LLMMessage(role="system", content=SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=EXTRACTION_MAX_TOKENS,
            )
        except ClaimExtractionError:
            raise
        except LLMProviderError as exc:
            logger.error(
                "Claim extraction LLM call failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            if isinstance(exc, (LLMProviderAPIError, LLMTimeoutError)):
                raise ClaimExtractionError(
                    "Claim extraction failed because the language model "
                    "provider did not respond"
                ) from exc
            raise ClaimExtractionError(
                "Claim extraction failed because the language model returned "
                "no usable output"
            ) from exc
        except Exception as exc:  # unexpected failures
            logger.error(
                "Claim extraction LLM call failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise ClaimExtractionError(
                "Claim extraction failed because the language model provider "
                "did not respond"
            ) from exc

        return parse_claims_payload(response.content, valid_ids)
