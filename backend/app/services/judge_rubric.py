"""Deterministic scoring rubric for the debate judge (rubric v2).

This module is the single documented configuration for the judge's scoring
formula. The LLM never invents or modifies these weights: it only provides
per-dimension values and qualitative text; final scores are always computed
here in plain Python. Every judgment stores a snapshot of the rubric it used,
so judgments created under rubric v1 stay interpretable.

Eight dimensions per agent, each 0-10 (see DIMENSION_DEFINITIONS):

    logical_soundness   20%  (LLM)  premises support the conclusion
    evidence_quality    15%  (LLM, only when evidence rows exist)
    factual_support     15%  (deterministic from stored claim verdicts)
    responsiveness      15%  (LLM)  engages the strongest opposing arguments
    relevance           10%  (LLM)
    effectiveness       10%  (LLM)  clarity: concise, understandable, structured
    completeness         5%  (LLM)  addresses the key aspects of the question
    fallacy_risk        10%  (deterministic from stored fallacy rows;
                              a PENALTY dimension, inverted before weighting)

Formula (all dimensions available):

    Agent Score = sum(weight * value) with fallacy value = 10 - Fallacy Risk

When a dimension's underlying data is unavailable, its weight is excluded and
the remaining weights are renormalized (divided by their sum) instead of
fabricating a value. A score is always in 0-10; only the final displayed
score is rounded to two decimals.

Rubric v1 (Module 11) had no responsiveness dimension and weighted evidence
quality 20%, relevance 15% and completeness 10%. It ranked agents only when
optional analyses existed; v2 ranks on transcript-based dimensions too and
reports missing analyses as limitations instead of refusing to rank.
"""

from __future__ import annotations

from uuid import UUID

RUBRIC_VERSION = 2

# Single documented weight configuration (sums to 1.0).
WEIGHTS: dict[str, float] = {
    "logical_soundness": 0.20,
    "evidence_quality": 0.15,
    "factual_support": 0.15,
    "responsiveness": 0.15,
    "relevance": 0.10,
    "effectiveness": 0.10,
    "completeness": 0.05,
    "fallacy_risk": 0.10,
}

DIMENSION_LABELS: dict[str, str] = {
    "logical_soundness": "Logical Soundness",
    "evidence_quality": "Evidence Quality",
    "factual_support": "Factual Support",
    "responsiveness": "Responsiveness",
    "relevance": "Relevance",
    "effectiveness": "Clarity",
    "completeness": "Completeness",
    "fallacy_risk": "Fallacy Risk",
}

DIMENSION_DEFINITIONS: dict[str, str] = {
    "logical_soundness": "Premises are stated and actually support the conclusion; no leaps.",
    "evidence_quality": "Uses relevant, specific, attributable evidence (only scored when evidence was retrieved).",
    "factual_support": "Share of the agent's claims that stored verification found supported vs contradicted.",
    "responsiveness": "Engages the strongest opposing arguments specifically, concedes valid points, does not talk past others.",
    "relevance": "Stays on the debate question.",
    "effectiveness": "Clear, concise and well structured; no padding or repetition.",
    "completeness": "Covers the key aspects of the question from the agent's perspective.",
    "fallacy_risk": "Detected fallacies weighted by severity and confidence (lower is better).",
}

# Dimensions whose values are assessed by the LLM (validated 0-10); the rest
# are derived deterministically from stored database records.
LLM_DIMENSIONS = (
    "logical_soundness",
    "evidence_quality",
    "responsiveness",
    "relevance",
    "effectiveness",
    "completeness",
)

SEVERITY_RISK_WEIGHT: dict[str, float] = {"low": 1.0, "medium": 2.0, "high": 3.0}

# Score bands (0-2 very weak ... 9-10 excellent).
SCORE_BANDS = (
    (2.0, "very weak"),
    (4.0, "weak"),
    (6.0, "moderate"),
    (8.0, "strong"),
    (10.0, "excellent"),
)

FORMULA_TEXT = (
    "Agent Score = 0.20*Logical Soundness + 0.15*Evidence Quality "
    "+ 0.15*Factual Support + 0.15*Responsiveness + 0.10*Relevance "
    "+ 0.10*Clarity + 0.05*Completeness + 0.10*(10 - Fallacy Risk); "
    "unavailable dimensions are excluded and the remaining weights renormalized."
)


def clamp_score(value: float) -> float:
    """Clamp a dimension score into the 0-10 range."""
    return max(0.0, min(10.0, float(value)))


def round_final(value: float) -> float:
    """Round only the final displayed score to two decimals."""
    return round(float(value), 2)


def compute_factual_support(verdicts: list[str]) -> float | None:
    """Deterministic factual-support score (0-10) from stored claim verdicts.

    supported contributes positively, contradicted negatively, and
    insufficient_evidence is neutral (never treated as true or false).
    Returns None when no verification records exist (data unavailable).
    """
    if not verdicts:
        return None
    net = 0
    for verdict in verdicts:
        if verdict == "supported":
            net += 1
        elif verdict == "contradicted":
            net -= 1
        elif verdict == "partially_supported":
            net += 0.5
        # insufficient_evidence stays neutral by design
    ratio = net / len(verdicts)  # -1..1
    return clamp_score((ratio + 1.0) / 2.0 * 10.0)


def compute_fallacy_risk(
    fallacies: list[tuple[str, float]], message_count: int
) -> float | None:
    """Deterministic fallacy-risk score (0-10, higher = riskier).

    fallacies is a list of (severity, confidence) rows for one agent.
    Duplicate (severity, confidence, position) detections are deduplicated by
    the caller (rows are unique per message + type already). Risk scales with
    severity-weighted confidence relative to how much the agent said.
    Returns None when no fallacy analysis exists for the agent (unavailable,
    never an unjustified value).
    """
    if not fallacies:
        return None
    messages = max(int(message_count), 1)
    total = 0.0
    for severity, confidence in fallacies:
        weight = SEVERITY_RISK_WEIGHT.get(severity, 1.0)
        total += weight * max(0.0, min(1.0, float(confidence)))
    # A single low-severity fallacy in a long debate stays a small penalty;
    # concentrated high-severity findings approach 10.
    return clamp_score(total / messages * 5.0)


def fallacy_quality(risk_score: float) -> float:
    """Transform the penalty dimension into a positive quality score."""
    return clamp_score(10.0 - risk_score)


def compute_agent_score(dimensions: dict[str, float | None]) -> float:
    """Weighted rubric score (0-10) over the available dimensions.

    ``fallacy_risk`` is given as a risk value and inverted to
    ``10 - risk`` before weighting. Dimensions with value None are excluded
    and the remaining weights are renormalized. Raises ValueError when no
    dimension data is available at all.
    """
    weighted = 0.0
    total_weight = 0.0
    for dimension, weight in WEIGHTS.items():
        value = dimensions.get(dimension)
        if value is None:
            continue
        value = clamp_score(value)
        if dimension == "fallacy_risk":
            value = fallacy_quality(value)
        weighted += weight * value
        total_weight += weight
    if total_weight <= 0.0:
        raise ValueError("No scoring dimension data is available for this agent")
    score = weighted / total_weight
    return clamp_score(score)


def decide_outcome(
    ranked_scores: list[tuple[UUID, float]],
    min_score_gap: float,
    data_sufficient: bool,
) -> tuple[str, UUID | None]:
    """Winner-selection policy: (outcome, winner_agent_id).

    - data not sufficient -> inconclusive (no manufactured winner)
    - fewer than two participants -> inconclusive (nothing to compare)
    - top-two gap >= min_score_gap -> winner
    - otherwise -> tie (winner_agent_id is None)

    ranked_scores must be ordered highest first as (agent_id, score) pairs
    using the rounded final scores that are also displayed.
    """
    if not data_sufficient:
        return "inconclusive", None
    if len(ranked_scores) < 2:
        return "inconclusive", None
    top_id, top_score = ranked_scores[0]
    _, second_score = ranked_scores[1]
    if top_score - second_score >= min_score_gap:
        return "winner", top_id
    return "tie", None


def rubric_snapshot(min_score_gap: float) -> dict:
    """The stored scoring_rubric payload for a judgment."""
    return {
        "version": RUBRIC_VERSION,
        "weights": dict(WEIGHTS),
        "formula": FORMULA_TEXT,
        "definitions": dict(DIMENSION_DEFINITIONS),
        "min_score_gap": min_score_gap,
        "score_bands": [
            {"max": upper, "label": label} for upper, label in SCORE_BANDS
        ],
        "dimension_sources": {
            "logical_soundness": "llm",
            "evidence_quality": "llm (only when evidence rows exist)",
            "factual_support": "deterministic from claim verdicts",
            "responsiveness": "llm (informed by stored rebuttal links and concessions)",
            "relevance": "llm",
            "effectiveness": "llm",
            "completeness": "llm",
            "fallacy_risk": "deterministic from fallacy rows (inverted)",
        },
        "unavailable_dimension_policy": (
            "excluded and remaining weights renormalized; reported as a limitation"
        ),
    }
