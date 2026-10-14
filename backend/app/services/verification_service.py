import json
import logging
import re
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.llm.base import (
    LLMMessage,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.llm.factory import get_llm_provider
from app.models.claim import Claim
from app.models.evidence import Evidence

logger = logging.getLogger(__name__)

VERDICTS = ("supported", "contradicted", "insufficient_evidence")
CONFIDENCE_LEVELS = ("low", "medium", "high")

VERDICT_ALIASES = {
    "supported": "supported",
    "support": "supported",
    "supports": "supported",
    "supported by evidence": "supported",
    "contradicted": "contradicted",
    "contradict": "contradicted",
    "contradicts": "contradicted",
    "refuted": "contradicted",
    "insufficient_evidence": "insufficient_evidence",
    "insufficient evidence": "insufficient_evidence",
    "insufficient": "insufficient_evidence",
    "insufficient-evidence": "insufficient_evidence",
    "not enough evidence": "insufficient_evidence",
    "inconclusive": "insufficient_evidence",
}

CONFIDENCE_ALIASES = {
    "low": "low",
    "medium": "medium",
    "med": "medium",
    "high": "high",
}

VERIFICATION_MAX_TOKENS = 4000
MAX_EXPLANATION_LENGTH = 800
MAX_SUMMARY_LENGTH = 1200
MAX_EVIDENCE_CHARS = 500

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+|www\.[^\s\"'<>]+", re.IGNORECASE)


class ClaimVerificationError(Exception):
    """Raised when verification fails or the LLM output is unusable."""


class VerificationOutput(BaseModel):
    """A single validated verification result produced by the evaluation LLM."""

    verdict: str
    confidence: str
    explanation: str = Field(min_length=1)
    evidence_summary: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, value) -> str:
        if not isinstance(value, str):
            raise ValueError("Verdict must be a string")
        normalized = VERDICT_ALIASES.get(value.strip().lower().rstrip(":.!?"))
        if normalized is None:
            raise ValueError(
                "Verdict must be supported, contradicted or insufficient_evidence"
            )
        return normalized

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value) -> str:
        if not isinstance(value, str):
            raise ValueError("Confidence must be a string")
        normalized = CONFIDENCE_ALIASES.get(value.strip().lower().rstrip(":.!?"))
        if normalized is None:
            raise ValueError("Confidence must be low, medium or high")
        return normalized

    @field_validator("explanation")
    @classmethod
    def _check_explanation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Explanation cannot be empty")
        if len(value) > MAX_EXPLANATION_LENGTH:
            value = value[:MAX_EXPLANATION_LENGTH].rstrip() + " [...]"
        return value

    @field_validator("evidence_summary", mode="before")
    @classmethod
    def _check_summary(cls, value) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("Evidence summary must be a string")
        value = value.strip()
        if len(value) > MAX_SUMMARY_LENGTH:
            value = value[:MAX_SUMMARY_LENGTH].rstrip() + " [...]"
        return value


SYSTEM_PROMPT = (
    "You evaluate whether retrieved web evidence supports, contradicts, or is "
    "insufficient to evaluate a single claim.\n"
    "Rules:\n"
    "- Evaluate ONLY the provided claim, using ONLY the provided evidence "
    "snippets.\n"
    "- Do not use outside knowledge. Do not invent sources, URLs, article "
    "titles, organizations, statistics, quotations or citations.\n"
    "- You may only reference evidence items that were provided. Quote their "
    "titles exactly as given or refer to them generically (e.g. 'the provided "
    "source 2').\n"
    "- Verdict 'supported': the provided evidence is consistent with and "
    "supports the claim.\n"
    "- Verdict 'contradicted': the provided evidence directly conflicts with "
    "the claim.\n"
    "- Verdict 'insufficient_evidence': there is no evidence, the evidence is "
    "ambiguous, irrelevant or does not establish the claim, or the provided "
    "sources conflict in a way that cannot be resolved from the snippets.\n"
    "- Do not force supported or contradicted when the evidence is "
    "inconclusive. Do not pretend certainty where the evidence is weak.\n"
    "- Do not evaluate the debate, the agents, or anyone's personality. "
    "Remain neutral.\n"
    "- explanation: 1-3 concise sentences stating what the evidence indicates. "
    "No essays and no hidden chain-of-thought.\n"
    "- evidence_summary: 1-2 sentences describing what the provided sources "
    "say, or an empty string if there is nothing useful to summarize.\n"
    "- confidence: one of low, medium, high.\n"
    "Respond with ONLY a JSON object (no markdown, no commentary):\n"
    '{"verdict": "...", "confidence": "...", "explanation": "...", '
    '"evidence_summary": "..."}'
)


def build_verification_prompt(
    claim: Claim, evidence: list[Evidence]
) -> str:
    lines = [
        f"Claim (type: {claim.claim_type}):",
        (claim.text or "").strip()[:2000],
        "",
        "Evidence retrieved for this claim:",
    ]
    for index, item in enumerate(evidence, start=1):
        snippet = (item.snippet or "").strip()
        if len(snippet) > MAX_EVIDENCE_CHARS:
            snippet = snippet[:MAX_EVIDENCE_CHARS] + " [...]"
        title = (item.title or "").strip()
        source = (item.source_name or "").strip()
        url = (item.url or "").strip()
        lines.append(
            f"[{index}] title: {title} | source: {source} | url: {url}\n"
            f"snippet: {snippet}"
        )
    if not evidence:
        lines.append("(no evidence available)")
    lines.append("")
    lines.append("Evaluate the claim against this evidence.")
    return "\n".join(lines)


def _strip_code_fences(raw: str) -> str:
    match = _FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def parse_verification_payload(raw: str) -> VerificationOutput:
    """Parse and validate raw LLM output into a verification result.

    Raises ClaimVerificationError when the output cannot be used; invalid
    results are never persisted.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ClaimVerificationError(
            "The language model returned an empty response"
        )

    text = _strip_code_fences(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ClaimVerificationError(
            "The language model did not return a JSON object for verification"
        )

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ClaimVerificationError(
            "The language model returned malformed JSON for verification"
        ) from exc

    if not isinstance(parsed, dict):
        raise ClaimVerificationError(
            "The language model did not return a JSON object for verification"
        )

    try:
        return VerificationOutput(**parsed)
    except ValidationError as exc:
        raise ClaimVerificationError(
            "The language model returned an invalid verification result"
        ) from exc


def _normalize_url(url: str) -> str:
    value = url.strip().lower().rstrip(".,;:!?)\"'")
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.rstrip("/")


def assert_sources_stored(
    output: VerificationOutput, evidence: list[Evidence]
) -> None:
    """Reject results that reference URLs not present in stored evidence.

    The verification may only cite evidence already stored for the claim:
    every URL it mentions must match a stored evidence URL exactly, or - when
    written without a path - must be the domain of a stored evidence URL.
    """
    allowed_urls: set[str] = set()
    allowed_domains: set[str] = set()
    for item in evidence:
        if not item.url:
            continue
        normalized = _normalize_url(item.url)
        allowed_urls.add(normalized)
        allowed_domains.add(normalized.split("/")[0])

    for field_name in ("explanation", "evidence_summary"):
        value = getattr(output, field_name)
        for found in _URL_RE.findall(value or ""):
            normalized = _normalize_url(found)
            if "/" in normalized:
                if normalized not in allowed_urls:
                    raise ClaimVerificationError(
                        "The verification result referenced a source that is "
                        "not part of the stored evidence"
                    )
            elif normalized not in allowed_domains:
                raise ClaimVerificationError(
                    "The verification result referenced a source that is "
                    "not part of the stored evidence"
                )


class ClaimVerificationService:
    """Evaluates a claim against its stored evidence using the shared LLM provider."""

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def verify(
        self, claim: Claim, evidence: list[Evidence]
    ) -> VerificationOutput:
        if not evidence:
            raise ClaimVerificationError(
                "No stored evidence is available for this claim"
            )

        prompt = build_verification_prompt(claim, evidence)

        try:
            response = await self.provider.generate(
                [
                    LLMMessage(role="system", content=SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=VERIFICATION_MAX_TOKENS,
            )
        except ClaimVerificationError:
            raise
        except LLMProviderError as exc:
            logger.error(
                "Claim verification LLM call failed: %s", type(exc).__name__
            )
            if isinstance(exc, (LLMProviderAPIError, LLMTimeoutError)):
                raise ClaimVerificationError(
                    "Claim verification failed because the language model "
                    "provider did not respond"
                ) from exc
            raise ClaimVerificationError(
                "Claim verification failed because the language model "
                "returned no usable output"
            ) from exc
        except Exception as exc:  # unexpected failures
            logger.error(
                "Claim verification LLM call failed: %s", type(exc).__name__
            )
            raise ClaimVerificationError(
                "Claim verification failed because the language model "
                "provider did not respond"
            ) from exc

        output = parse_verification_payload(response.content)
        assert_sources_stored(output, evidence)
        return output
