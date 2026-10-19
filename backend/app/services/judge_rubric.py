"""Deterministic scoring rubric for the debate judge (Module 11).

This module is the single documented configuration for the judge's scoring
formula. The LLM never invents or modifies these weights: it only provides
per-dimension values and qualitative text; final scores are always computed
here in plain Python.

Seven dimensions per agent, each 0-10:

    logical_soundness  20%   (LLM-assessed)
    evidence_quality    20%   (LLM-assessed, only when evidence rows exist)
    factual_support     15%   (deterministic from stored claim verdicts)
    relevance           15%   (LLM-assessed)
    effectiveness       10%   (LLM-assessed)
    completeness        10%   (LLM-assessed)
    fallacy_risk        10%   (deterministic from stored fallacy rows;
                               a PENALTY dimension, inverted before weighting)

Formula (all dimensions available):

    Fallacy Quality = 10 - Fallacy Risk
    Agent Score = 0.20*Logical + 0.20*Evidence + 0.15*Factual + 0.15*Relevance
                + 0.10*Effectiveness + 0.10*Completeness + 0.10*FallacyQuality

When a dimension's underlying data is unavailable, its weight is excluded and
the remaining weights are renormalized (divided by their sum) instead of
fabricating a value. A score is always in 0-10; only the final displayed
score is rounded to two decimals.

Mapping to Module 10 argument evaluations: stored per-message evaluations
(logical soundness / evidence / relevance / effectiveness, 0-10) are passed to
the LLM as supporting context for its logical_soundness, evidence_quality,
relevance and effectiveness assessments; they are not a separate formula
dimension and their criteria are not reinterpreted.
"""

from __future__ import annotations

from uuid import UUID

# Single documented weight configuration (sums to 1.0).
WEIGHTS: dict[str, float] = {
    "logical_soundness": 0.20,
    "evidence_quality": 0.20,
    "factual_support": 0.15,
    "relevance": 0.15,
    "effectiveness": 0.10,
    "completeness": 0.10,
    "fallacy_risk": 0.10,
}

DIMENSION_LABELS: dict[str, str] = {
    "logical_soundness": "Logical Soundness",
    "evidence_quality": "Evidence Quality",
    "factual_support": "Factual Support",
    "relevance": "Relevance",
    "effectiveness": "Effectiveness",
    "completeness": "Completeness",
    "fallacy_risk": "Fallacy Risk",
}

# Dimensions whose values are assessed by the LLM (validated 0-10); the rest
# are derived deterministically from stored database records.
LLM_DIMENSIONS = (
    "logical_soundness",
    "evidence_quality",
    "relevance",
    "effectiveness",
    "completeness",
)

SEVERITY_RISK_WEIGHT: dict[str, float] = {"low": 1.0, "medium": 2.0, "high": 3.0}

# Score bands documented in prompt 11 section 5 (0-2 very weak ... 9-10 excellent).
SCORE_BANDS = (
    (2.0, "very weak"),
    (4.0, "weak"),
    (6.0, "moderate"),
    (8.0, "strong"),
    (10.0, "excellent"),
)

FORMULA_TEXT = (
    "Agent Score = 0.20*Logical Soundness + 0.20*Evidence Quality "
    "+ 0.15*Factual Support + 0.15*Relevance + 0.10*Effectiveness "
    "+ 0.10*Completeness + 0.10*(10 - Fallacy Risk); unavailable dimensions "
    "are excluded and the remaining weights renormalized."
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
        "weights": dict(WEIGHTS),
        "formula": FORMULA_TEXT,
        "min_score_gap": min_score_gap,
        "score_bands": [
            {"max": upper, "label": label} for upper, label in SCORE_BANDS
        ],
        "dimension_sources": {
            "logical_soundness": "llm",
            "evidence_quality": "llm (only when evidence rows exist)",
            "factual_support": "deterministic from claim verdicts",
            "relevance": "llm",
            "effectiveness": "llm",
            "completeness": "llm",
            "fallacy_risk": "deterministic from fallacy rows (inverted)",
        },
        "unavailable_dimension_policy": (
            "excluded and remaining weights renormalized; reported as a limitation"
        ),
    }
