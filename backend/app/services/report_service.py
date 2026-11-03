"""Downloadable PDF conclusion report for a debate (final UI task).

The report is built exclusively from data already persisted for the debate:
metadata, rounds, transcript counts, the stored judgment, claims, stored
verifications, retrieved evidence, fallacy rows and argument evaluations.
It never calls the LLM, the evidence provider or any other external service
and it never runs new analysis. Missing parts are represented with explicit
honest statements instead of fabricated content.

Rendering happens fully in memory (BytesIO); no temporary files are written.
Unicode is handled safely: text is normalized and folded to the Latin-1 range
supported by the PDF base fonts, so unusual characters can never break the
document.
"""

from __future__ import annotations

import asyncio
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.evidence import Evidence
from app.models.judge import DebateJudgment
from app.models.user import User
from app.models.verdict import DebateVerdict
from app.services import debate_service
from app.services import judge_rubric
from app.services.argument_analysis_service import list_evaluations, list_fallacies
from app.services.claim_service import list_claims
from app.services.verdict_service import verdict_response_payload

REPORT_MEDIA_TYPE = "application/pdf"

# Labels used for the three stored verdicts. insufficient_evidence must never
# be rendered as "false" - it means the retrieved evidence did not settle it.
VERDICT_LABELS = {
    "supported": "Supported",
    "partially_supported": "Partially supported",
    "contradicted": "Contradicted",
    "insufficient_evidence": "Insufficient evidence",
}
CONFIDENCE_LABELS = {"low": "Low", "medium": "Medium", "high": "High"}
OUTCOME_LABELS = {
    "winner": "Winner",
    "tie": "Tie",
    "inconclusive": "Inconclusive",
}
CLAIM_TYPE_LABELS = {
    "factual": "Factual",
    "opinion": "Opinion",
    "prediction": "Prediction",
    "definition": "Definition",
    "other": "Other",
}
FALLACY_LABELS = {
    "ad_hominem": "Ad hominem",
    "straw_man": "Straw man",
    "false_dilemma": "False dilemma",
    "slippery_slope": "Slippery slope",
    "appeal_to_authority": "Appeal to authority",
    "appeal_to_emotion": "Appeal to emotion",
    "hasty_generalization": "Hasty generalization",
    "circular_reasoning": "Circular reasoning",
    "red_herring": "Red herring",
    "false_cause": "False cause",
    "bandwagon": "Bandwagon",
    "loaded_question": "Loaded question",
    "tu_quoque": "Tu quoque",
    "no_fallacy": "No fallacy",
}
ROUND_STATUS_LABELS = {
    "pending": "Pending",
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
}

_NO_JUDGMENT_TEXT = (
    "No final judgment has been generated for this debate. "
    "Judge the debate to store a conclusion."
)

# Common typographic characters folded to ASCII equivalents before rendering.
_PUNCTUATION_MAP = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2013": "-",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u2026": "...",
    "\u00a0": " ",
    "\u2022": "-",
    "\u00b7": "-",
    "\u2192": "->",
    "\u2190": "<-",
    "\u00d7": "x",
    "\u00f7": "/",
    "\u20ac": "EUR",
    "\u00a3": "GBP",
    "\u00a5": "JPY",
    "\u00ae": "(R)",
    "\u2122": "(TM)",
    "\u00ba": "o",
    "\u00aa": "a",
}


class ReportRenderError(Exception):
    """Raised when the PDF document could not be rendered."""


def safe_text(value) -> str:
    """Fold arbitrary text into the Latin-1 range used by the base fonts.

    NFKD-normalizes, strips combining marks, translates common punctuation
    and replaces anything still unsupported with '?'. Never raises.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "".join(_PUNCTUATION_MAP.get(ch, ch) for ch in text)
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if code < 32:
            if ch in ("\n", "\t", "\r"):
                out.append(" ")
            continue
        out.append(ch if code <= 255 else "?")
    return "".join(out)


def report_filename(topic: str, debate_id: UUID) -> str:
    """Safe, meaningful ASCII filename for the download."""
    slug = re.sub(r"[^a-z0-9]+", "-", safe_text(topic).lower()).strip("-")
    slug = slug[:48].strip("-") or "debate"
    return f"maves-{slug}-{str(debate_id)[:8]}.pdf"


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "Not available"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_score(value) -> str:
    if value is None:
        return "Unavailable"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if number == int(number):
        return f"{int(number)}/10"
    return f"{number:.2f}/10"


def _truncate(text: str, limit: int = 160) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _content_paragraphs(content: str) -> list[str]:
    """Split a stored message into readable paragraphs.

    Messages are markdown-ish LLM output; keep line structure (one Paragraph
    per non-empty line, so long transcripts can break across pages) and drop
    the markup characters that would otherwise show up literally.
    """
    paragraphs = []
    for line in (content or "").splitlines():
        line = re.sub(r"^\s*#{1,6}\s*", "", line)
        line = line.replace("**", "").replace("__", "").strip()
        if line:
            paragraphs.append(line)
    return paragraphs


def _safe_url(url: str) -> str | None:
    """Only http(s) URLs are rendered as clickable links."""
    cleaned = (url or "").strip()
    if cleaned.lower().startswith(("http://", "https://")):
        return cleaned
    return None


# ---------------------------------------------------------------------------
# Report data (all fields sourced from persisted rows)
# ---------------------------------------------------------------------------


@dataclass
class ClaimRow:
    text: str
    claim_type: str
    agent_name: str
    verdict: str | None
    confidence: str | None
    explanation: str | None
    evidence_summary: str | None


@dataclass
class EvidenceRow:
    claim_text: str
    title: str
    url: str
    source_name: str
    snippet: str
    relevance_score: float | None
    source_type: str = "web"
    publisher: str | None = None
    external_rating: str | None = None
    claim_reviewed: str | None = None
    review_date: datetime | None = None
    retrieved_at: datetime | None = None


@dataclass
class FallacyRow:
    round_number: int
    turn_number: int
    agent_name: str
    fallacy_type: str
    severity: str
    confidence: float
    explanation: str
    evidence_span: str | None


@dataclass
class EvaluationRow:
    round_number: int
    turn_number: int
    agent_name: str
    logical_soundness: float
    evidence_score: float
    relevance_score: float
    effectiveness_score: float
    overall_score: float
    explanation: str
    criterion_scores: dict | None = None
    rubric_version: int | None = None
    strengths: list | None = None
    weaknesses: list | None = None


@dataclass
class TranscriptRow:
    round_number: int
    turn_number: int
    agent_name: str
    agent_role: str
    message_type: str
    content: str


@dataclass
class ReportData:
    topic: str
    status: str
    mode: str
    expert_selection_mode: str
    domain_tags: list[str]
    total_rounds: int
    verify_evidence: bool
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    debate_id: UUID
    generated_at: datetime
    agents: list[tuple[str, str, int]] = field(default_factory=list)
    rounds: list[tuple[int, str, datetime | None, datetime | None]] = field(
        default_factory=list
    )
    message_count: int = 0
    messages_by_agent: list[tuple[str, int]] = field(default_factory=list)
    judgment: DebateJudgment | None = None
    winner_name: str | None = None
    claims: list[ClaimRow] = field(default_factory=list)
    evidence: list[EvidenceRow] = field(default_factory=list)
    fallacies: list[FallacyRow] = field(default_factory=list)
    evaluations: list[EvaluationRow] = field(default_factory=list)
    transcript: list[TranscriptRow] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    context: str | None = None
    # verdict_response_payload() output: the final answer to the debate
    # question with cited stored claims expanded.
    verdict: dict | None = None

    @property
    def is_partial(self) -> bool:
        """Partial until the debate completed and has a final verdict."""
        return self.status != "completed" or self.verdict is None


async def build_report_data(
    db: AsyncSession, user: User, debate_id: UUID
) -> ReportData:
    """Load every persisted input for the report. Read-only, no LLM calls."""
    debate = await debate_service.get_debate(db, user, debate_id)

    transcript = await debate_service.get_debate_transcript(db, user, debate_id)
    rounds = await debate_service.get_debate_rounds(db, user, debate_id)
    claim_rows = await list_claims(db, user, debate_id)
    fallacy_rows = await list_fallacies(db, user, debate_id)
    evaluation_rows = await list_evaluations(db, user, debate_id)

    judgment = (
        await db.execute(
            select(DebateJudgment).where(DebateJudgment.debate_id == debate.id)
        )
    ).scalar_one_or_none()

    verdict_row = (
        await db.execute(
            select(DebateVerdict).where(DebateVerdict.debate_id == debate.id)
        )
    ).scalar_one_or_none()
    verdict = (
        await verdict_response_payload(db, verdict_row) if verdict_row else None
    )

    claim_ids = [claim.id for claim, _ in claim_rows]
    verifications: dict[UUID, ClaimVerification] = {}
    evidence_by_claim: dict[UUID, list[Evidence]] = {}
    if claim_ids:
        verification_rows = (
            await db.execute(
                select(ClaimVerification).where(ClaimVerification.claim_id.in_(claim_ids))
            )
        ).scalars().all()
        verifications = {row.claim_id: row for row in verification_rows}
        evidence_rows = (
            await db.execute(
                select(Evidence)
                .where(Evidence.claim_id.in_(claim_ids))
                .order_by(Evidence.position, Evidence.retrieved_at, Evidence.id)
            )
        ).scalars().all()
        for row in evidence_rows:
            evidence_by_claim.setdefault(row.claim_id, []).append(row)

    # Transcript-derived context: message -> round/turn and per-agent counts.
    message_position: dict[UUID, tuple[int, int]] = {}
    counts: dict[str, int] = {}
    transcript_rows: list[TranscriptRow] = []
    for message, round_number in transcript:
        message_position[message.id] = (round_number, message.turn_number)
        agent_name = message.agent.name if message.agent is not None else "Unknown"
        counts[agent_name] = counts.get(agent_name, 0) + 1
        transcript_rows.append(
            TranscriptRow(
                round_number=round_number,
                turn_number=message.turn_number,
                agent_name=agent_name,
                agent_role=(
                    ""
                    if message.agent is None
                    else "AI specialist role"
                    if getattr(message.agent, "source", "builtin") == "dynamic"
                    else message.agent.role
                ),
                message_type=message.message_type,
                content=message.content,
            )
        )

    # debate.agents is ordered by the stored speaker position (selectin).
    agents = [
        (
            agent.name,
            "AI specialist role (generated)" if getattr(agent, "source", "builtin") == "dynamic" else agent.role,
            position,
        )
        for position, agent in enumerate(debate.agents, start=1)
    ]

    winner_name = None
    if judgment is not None and judgment.winner_agent_id is not None:
        winner_name = next(
            (agent.name for agent in debate.agents if agent.id == judgment.winner_agent_id),
            None,
        )
        if winner_name is None and judgment.agent_scores:
            for card in judgment.agent_scores:
                if str(card.get("agent_id")) == str(judgment.winner_agent_id):
                    winner_name = card.get("agent_name")
                    break

    claims: list[ClaimRow] = []
    for claim, agent_name in claim_rows:
        verification = verifications.get(claim.id)
        claims.append(
            ClaimRow(
                text=claim.text,
                claim_type=claim.claim_type,
                agent_name=agent_name,
                verdict=verification.verdict if verification else None,
                confidence=verification.confidence if verification else None,
                explanation=verification.explanation if verification else None,
                evidence_summary=(
                    verification.evidence_summary if verification else None
                ),
            )
        )

    evidence: list[EvidenceRow] = []
    for claim, _ in claim_rows:
        for row in evidence_by_claim.get(claim.id, []):
            evidence.append(
                EvidenceRow(
                    claim_text=claim.text,
                    title=row.title,
                    url=row.url,
                    source_name=row.source_name,
                    snippet=row.snippet,
                    relevance_score=row.relevance_score,
                    source_type=row.source_type, publisher=row.publisher,
                    external_rating=row.external_rating, claim_reviewed=row.claim_reviewed,
                    review_date=row.review_date, retrieved_at=row.retrieved_at,
                )
            )

    fallacies: list[FallacyRow] = []
    for fallacy, agent_name in fallacy_rows:
        round_number, turn_number = message_position.get(
            fallacy.message_id, (0, 0)
        )
        fallacies.append(
            FallacyRow(
                round_number=round_number,
                turn_number=turn_number,
                agent_name=agent_name,
                fallacy_type=fallacy.fallacy_type,
                severity=fallacy.severity,
                confidence=fallacy.confidence,
                explanation=fallacy.explanation,
                evidence_span=fallacy.evidence_span,
            )
        )

    evaluations: list[EvaluationRow] = []
    for evaluation, agent_name in evaluation_rows:
        round_number, turn_number = message_position.get(
            evaluation.message_id, (0, 0)
        )
        evaluations.append(
            EvaluationRow(
                round_number=round_number,
                turn_number=turn_number,
                agent_name=agent_name,
                logical_soundness=evaluation.logical_soundness,
                evidence_score=evaluation.evidence_score,
                relevance_score=evaluation.relevance_score,
                effectiveness_score=evaluation.effectiveness_score,
                overall_score=evaluation.overall_score,
                explanation=evaluation.explanation,
                criterion_scores=evaluation.criterion_scores, rubric_version=evaluation.rubric_version,
                strengths=evaluation.strengths, weaknesses=evaluation.weaknesses,
            )
        )

    from app.services.analysis_coverage import coverage_payload
    return ReportData(
        coverage=await coverage_payload(db, debate),
        topic=debate.topic,
        status=debate.status,
        mode=debate.mode,
        expert_selection_mode=debate.expert_selection_mode,
        domain_tags=list(debate.domain_tags or []),
        total_rounds=debate.total_rounds,
        verify_evidence=debate.verify_evidence,
        created_at=debate.created_at,
        started_at=debate.started_at,
        completed_at=debate.completed_at,
        debate_id=debate.id,
        generated_at=datetime.now(timezone.utc),
        agents=agents,
        rounds=[
            (r.round_number, r.status, r.started_at, r.completed_at)
            for r in rounds
        ],
        message_count=len(transcript),
        messages_by_agent=sorted(counts.items(), key=lambda item: item[0]),
        judgment=judgment,
        winner_name=winner_name,
        claims=claims,
        evidence=evidence,
        fallacies=fallacies,
        evaluations=evaluations,
        transcript=transcript_rows,
        context=debate.context,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# PDF rendering (pure, sync, in-memory)
# ---------------------------------------------------------------------------

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d1d5db")
HEAD_BG = colors.HexColor("#1f2937")
HEAD_FG = colors.white
ALT_BG = colors.HexColor("#f3f4f6")
LINK_COLOR = colors.HexColor("#1d4ed8")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            alignment=TA_LEFT,
            textColor=INK,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            textColor=MUTED,
            spaceAfter=2,
        ),
        "h2": ParagraphStyle(
            "ReportH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=INK,
            spaceBefore=14,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "ReportH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#374151"),
            spaceBefore=9,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=INK,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
            spaceAfter=2,
        ),
        "speaker": ParagraphStyle(
            "ReportSpeaker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#374151"),
            spaceBefore=6,
            spaceAfter=2,
        ),
        "notice": ParagraphStyle(
            "ReportNotice",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#92400e"),
            backColor=colors.HexColor("#fef3c7"),
            borderColor=colors.HexColor("#f59e0b"),
            borderWidth=0.5,
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "cover_brand": ParagraphStyle(
            "CoverBrand", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=12, leading=16, textColor=colors.HexColor("#a5b4fc"),
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=30, leading=36, alignment=TA_LEFT, textColor=colors.white,
        ),
        "cover_topic": ParagraphStyle(
            "CoverTopic", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=17, leading=23, textColor=colors.HexColor("#e0e7ff"),
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=14, textColor=colors.HexColor("#cbd5e1"),
        ),
        "cover_meta_strong": ParagraphStyle(
            "CoverMetaStrong", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=11, leading=15, textColor=colors.HexColor("#c7d2fe"),
        ),
        "verdict_label": ParagraphStyle(
            "VerdictLabel", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, leading=11, textColor=MUTED, spaceAfter=3,
        ),
        "verdict_answer": ParagraphStyle(
            "VerdictAnswer", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=12.5, leading=17, textColor=INK, spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "ReportCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=INK,
        ),
        "cell_head": ParagraphStyle(
            "ReportCellHead",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=HEAD_FG,
        ),
    }


def _para(text, style) -> Paragraph:
    return Paragraph(xml_escape(safe_text(text)), style)


def _link_para(text, url, style) -> Paragraph:
    cleaned = _safe_url(url)
    if cleaned is None:
        return _para(text, style)
    href = xml_escape(cleaned, {'"': "&quot;"})
    label = xml_escape(safe_text(text))
    return Paragraph(f'<link href="{href}" color="#1d4ed8">{label}</link>', style)


def _kv_table(pairs: list[tuple[str, str]], styles: dict, width: float = 487.0) -> Table:
    rows = [
        [_para(key, styles["cell_head"]), _para(value, styles["cell"])]
        for key, value in pairs
    ]
    table = Table(rows, colWidths=[130, width - 130], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), HEAD_BG),
                ("TEXTCOLOR", (0, 0), (0, -1), HEAD_FG),
                ("GRID", (0, 0), (-1, -1), 0.5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _grid_table(
    header: list[str],
    rows: list[list],
    col_widths: list[float],
    styles: dict,
) -> Table:
    data = [[_para(h, styles["cell_head"]) for h in header]]
    for row in rows:
        data.append(
            [
                cell if isinstance(cell, Paragraph) else _para(cell, styles["cell"])
                for cell in row
            ]
        )
    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("GRID", (0, 0), (-1, -1), 0.5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_BG]),
            ]
        )
    )
    return table


def _verdict_label(verdict: str | None) -> str:
    if verdict is None:
        return "Not verified"
    return VERDICT_LABELS.get(verdict, verdict.replace("_", " ").capitalize())


def _outcome_line(data: ReportData) -> str:
    judgment = data.judgment
    assert judgment is not None
    label = OUTCOME_LABELS.get(judgment.outcome, judgment.outcome.capitalize())
    if judgment.outcome == "winner" and data.winner_name:
        return f"{label}: {data.winner_name}"
    if judgment.outcome == "tie":
        return f"{label} - no single winner"
    if judgment.outcome == "inconclusive":
        return f"{label} - the stored data was not sufficient to pick a winner"
    return label


POSITION_LABELS = {
    "supports": "Supports the proposition",
    "opposes": "Opposes the proposition",
    "mixed": "Mixed - depends on conditions",
    "inconclusive": "Inconclusive",
}
POSITION_COLORS = {
    "supports": ("#ecfdf5", "#059669"),
    "opposes": ("#fef2f2", "#dc2626"),
    "mixed": ("#eff6ff", "#2563eb"),
    "inconclusive": ("#fffbeb", "#d97706"),
}

_NO_VERDICT_TEXT = (
    "No final debate verdict has been generated for this debate. Generate "
    "the verdict on the debate page to store a conclusion."
)


def _callout(flowables: list, background: str, border: str) -> Table:
    """A tinted, bordered box around a list of flowables."""
    table = Table([[flowables]], colWidths=[487], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(border)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(border)),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


def _cited_claims(claims: list[dict], styles: dict) -> list:
    out = []
    for claim in claims:
        status = _verdict_label(claim.get("verdict"))
        out.append(
            _para(
                f'Cited claim ({claim.get("agent_name")}): "{_truncate(claim.get("text", ""), 220)}"'
                f" - stored verification: {status}",
                styles["small"],
            )
        )
        for source in (claim.get("sources") or [])[:3]:
            url = source.get("url") or ""
            out.append(
                _link_para(
                    f"Source: {source.get('title') or url} ({source.get('source_name') or 'unknown'})",
                    url,
                    styles["small"],
                )
            )
    return out


def _cover(data: ReportData, styles: dict) -> list:
    story: list = [Spacer(1, 120)]
    story.append(_para("MAVES - AI Debate Arena", styles["cover_brand"]))
    story.append(Spacer(1, 18))
    story.append(_para("Debate Analysis Report", styles["cover_title"]))
    story.append(Spacer(1, 14))
    story.append(_para(data.topic, styles["cover_topic"]))
    story.append(Spacer(1, 26))
    if data.verdict is not None:
        story.append(
            _para(
                "Final verdict: "
                + POSITION_LABELS.get(data.verdict["position"], data.verdict["position"]),
                styles["cover_meta_strong"],
            )
        )
        story.append(_para(data.verdict["answer"], styles["cover_meta"]))
        story.append(Spacer(1, 18))
    meta = [
        ("Generated", _fmt_dt(data.generated_at)),
        ("Status", data.status.replace("_", " ").capitalize()),
        ("Rounds", str(data.total_rounds)),
        ("Messages", str(data.message_count)),
        ("Agents", ", ".join(name for name, _, _ in data.agents) or "None"),
        ("Debate ID", str(data.debate_id)),
    ]
    for key, value in meta:
        story.append(_para(f"{key}: {value}", styles["cover_meta"]))
    if data.is_partial:
        reasons = []
        if data.status != "completed":
            reasons.append(f"the debate status is '{data.status}'")
        if data.verdict is None:
            reasons.append("no final verdict is stored")
        if data.judgment is None:
            reasons.append("no final judgment is stored")
        story.append(Spacer(1, 22))
        story.append(
            _para(
                "PARTIAL REPORT - " + " and ".join(reasons) + ". Sections show "
                "only what has been persisted so far.",
                styles["notice"],
            )
        )
    story.append(PageBreak())
    return story


def _build_story(data: ReportData, styles: dict) -> list:
    story: list = _cover(data, styles)
    numbering = iter(range(1, 100))

    def section(title: str) -> Paragraph:
        # Optional sections are skipped entirely, so number them as rendered.
        return _para(f"{next(numbering)}. {title}", styles["h2"])

    verdict = data.verdict
    judgment = data.judgment

    # ---- Executive summary -------------------------------------------------
    story.append(section("Executive Summary"))
    if verdict is not None:
        story.append(_para(verdict["summary"], styles["body"]))
    elif judgment is not None:
        story.append(_para(_NO_VERDICT_TEXT, styles["body"]))
    else:
        story.append(_para(_NO_VERDICT_TEXT, styles["body"]))
        story.append(_para(_NO_JUDGMENT_TEXT, styles["body"]))
    summary_bits = [f"{data.message_count} stored messages"]
    if data.claims:
        summary_bits.append(f"{len(data.claims)} extracted claims")
    if data.evidence:
        summary_bits.append(f"{len(data.evidence)} retrieved evidence sources")
    story.append(
        _para("Stored overview: " + ", ".join(summary_bits) + ".", styles["body"])
    )

    # ---- Final debate verdict ---------------------------------------------
    story.append(section("Final Debate Verdict"))
    if verdict is None:
        story.append(_para(_NO_VERDICT_TEXT, styles["body"]))
    else:
        background, border = POSITION_COLORS.get(
            verdict["position"], ("#f3f4f6", "#6b7280")
        )
        box = [
            _para(
                POSITION_LABELS.get(verdict["position"], verdict["position"]).upper(),
                styles["verdict_label"],
            ),
            _para(verdict["answer"], styles["verdict_answer"]),
        ]
        if verdict.get("preferred_position"):
            box.append(
                _para(
                    f"Better-supported position: {verdict['preferred_position']}",
                    styles["body"],
                )
            )
        box.append(
            _para(
                f"Confidence: {verdict['confidence'].capitalize()}",
                styles["body"],
            )
        )
        story.append(_callout(box, background, border))
        story.append(Spacer(1, 8))
        story.append(_para("Reasoning", styles["h3"]))
        story.append(_para(verdict["reasoning"], styles["body"]))
        if verdict.get("assumptions"):
            story.append(_para("Assumptions in the question", styles["h3"]))
            for item in verdict["assumptions"]:
                story.append(
                    _para(
                        f"- [{item.get('status', 'unclear')}] {item.get('assumption', '')}: "
                        f"{item.get('assessment', '')}",
                        styles["body"],
                    )
                )
        if verdict.get("sub_verdicts"):
            story.append(_para("Each part of the question", styles["h3"]))
            for item in verdict["sub_verdicts"]:
                story.append(
                    _para(
                        f"- {item.get('question', '')} -> "
                        f"{POSITION_LABELS.get(item.get('position'), item.get('position'))}: "
                        f"{item.get('answer', '')}",
                        styles["body"],
                    )
                )
        story.append(
            _para(
                "This verdict is the system's synthesized assessment of the "
                "debate question. It is separate from the agent performance "
                "ranking: the best-performing agent is not assumed to be right.",
                styles["small"],
            )
        )

        # ---- Strongest arguments -----------------------------------------
        story.append(section("Strongest Supporting and Opposing Arguments"))
        story.append(
            _para(
                "Points are attributed to the agent that made them (opinions). "
                "Only cited claims with a stored verification count as evidence.",
                styles["small"],
            )
        )
        for title, items in (
            ("Supporting arguments", verdict.get("supporting_arguments") or []),
            ("Counterarguments", verdict.get("counterarguments") or []),
        ):
            story.append(_para(title, styles["h3"]))
            if not items:
                story.append(_para("None recorded.", styles["body"]))
            for item in items:
                who = f" ({item['agent_name']})" if item.get("agent_name") else ""
                story.append(_para(f"- {item['point']}{who}", styles["body"]))
                if item.get("impact"):
                    story.append(
                        _para(f"Impact on the conclusion: {item['impact']}", styles["small"])
                    )
                story.extend(_cited_claims(item.get("claims") or [], styles))

        # ---- Confidence and uncertainty ----------------------------------
        story.append(section("Confidence and Uncertainty"))
        snap = verdict.get("evidence_snapshot") or {}
        story.append(
            _kv_table(
                [
                    ("Confidence", verdict["confidence"].capitalize()),
                    ("Basis", verdict["confidence_basis"]),
                    (
                        "Stored claim verdicts",
                        f"{snap.get('supported', 0)} supported, "
                        f"{snap.get('contradicted', 0)} contradicted, "
                        f"{snap.get('insufficient_evidence', 0)} insufficient evidence, "
                        f"{snap.get('unverified', 0)} not verified "
                        f"(of {snap.get('total_claims', 0)})",
                    ),
                    ("Evidence sources", str(snap.get("evidence_sources", 0))),
                    (
                        "Evidence analysis run",
                        f"{snap.get('analysis_state', 'not_run')}"
                        + (
                            f" ({snap.get('analysis_failures')} technical failure(s) - not evidence)"
                            if snap.get("analysis_failures")
                            else ""
                        ),
                    ),
                ],
                styles,
            )
        )
        story.append(
            _para(
                "Confidence is a qualitative label (low: little or no verified "
                "or conflicting evidence; medium: some claims verified; high: "
                "most claims verified and consistent), capped by evidence "
                "coverage. It is not a calibrated probability.",
                styles["small"],
            )
        )
        if verdict.get("unresolved_questions"):
            story.append(_para("Unresolved questions", styles["h3"]))
            for item in verdict["unresolved_questions"]:
                story.append(_para(f"- {item}", styles["body"]))
        if verdict.get("limitations"):
            story.append(_para("Verdict limitations", styles["h3"]))
            for item in verdict["limitations"]:
                story.append(_para(f"- {item}", styles["body"]))

    # ---- Debate overview ---------------------------------------------------
    story.append(section("Debate Overview"))
    overview = [("Topic", safe_text(data.topic))]
    if data.context:
        overview.append(("Context", data.context))
    overview += [
        ("Mode", "Pro/Con" if data.mode == "pro_con" else "Balanced"),
        (
            "Expert selection",
            "Automatic (topic-aware)" if data.expert_selection_mode == "auto" else "Manual",
        ),
        ("Rounds", str(data.total_rounds)),
        ("Evidence verification during debate", "Enabled" if data.verify_evidence else "Disabled"),
        ("Domain tags", ", ".join(safe_text(t) for t in data.domain_tags) or "None"),
        ("Created", _fmt_dt(data.created_at)),
        ("Started", _fmt_dt(data.started_at)),
        ("Completed", _fmt_dt(data.completed_at)),
    ]
    story.append(_kv_table(overview, styles))
    story.append(_para("Stored rounds", styles["h3"]))
    if data.rounds:
        story.append(
            _grid_table(
                ["Round", "Status", "Started", "Completed"],
                [
                    [str(number), ROUND_STATUS_LABELS.get(status, status),
                     _fmt_dt(started), _fmt_dt(completed)]
                    for number, status, started, completed in data.rounds
                ],
                [50, 90, 173, 174],
                styles,
            )
        )
    else:
        story.append(_para("No rounds have been stored for this debate.", styles["body"]))

    # ---- Agent participation -----------------------------------------------
    story.append(section("Agent Participation and Arguments"))
    if data.agents:
        counts = dict(data.messages_by_agent)
        first_message: dict[str, str] = {}
        for row in data.transcript:
            first_message.setdefault(row.agent_name, row.content)
        rows = []
        for name, role, position in data.agents:
            opening = " ".join(_content_paragraphs(first_message.get(name, "")))
            rows.append(
                [
                    str(position),
                    f"{name}\n{role}",
                    str(counts.get(name, 0)),
                    _truncate(opening, 260) or "No messages stored.",
                ]
            )
        story.append(
            _grid_table(["#", "Agent", "Messages", "Opening argument (excerpt)"],
                        rows, [24, 110, 58, 295], styles)
        )
        story.append(
            _para("Full statements are in the Debate Transcript section.", styles["small"])
        )
    if not data.messages_by_agent:
        story.append(_para("No messages have been stored for this debate yet.", styles["body"]))

    # ---- Agent performance (judge) ----------------------------------------
    story.append(section("Agent Performance"))
    story.append(
        _para(
            "Rubric scores for how well each agent argued. This ranking is "
            "separate from the final verdict and does not decide the debate "
            "question.",
            styles["small"],
        )
    )
    if judgment is None:
        story.append(_para(_NO_JUDGMENT_TEXT, styles["body"]))
    else:
        story.append(
            _kv_table(
                [
                    ("Outcome", _outcome_line(data)),
                    ("Overall score", _fmt_score(judgment.overall_score)),
                    ("Judgment date", _fmt_dt(judgment.created_at)),
                ],
                styles,
            )
        )
        story.append(Spacer(1, 6))
        story.append(_para(judgment.summary, styles["body"]))
        cards = judgment.agent_scores or []
        if cards:
            story.append(
                _grid_table(
                    ["Agent", "Role", "Final score"],
                    [
                        [str(card.get("agent_name") or "Unknown"),
                         str(card.get("agent_role") or ""),
                         _fmt_score(card.get("final_score"))]
                        for card in cards
                    ],
                    [200, 170, 117],
                    styles,
                )
            )
            for card in cards:
                name = card.get("agent_name") or "Unknown"
                role = card.get("agent_role") or ""
                story.append(
                    _para(f"{name} ({role}) - {_fmt_score(card.get('final_score'))}", styles["h3"])
                )
                dimensions = card.get("dimensions") or {}
                dim_rows = []
                for key in judge_rubric.WEIGHTS:
                    if key not in dimensions and key not in (card.get("unavailable_dimensions") or []):
                        continue
                    dim_rows.append(
                        [judge_rubric.DIMENSION_LABELS.get(key, key),
                         _fmt_score(dimensions.get(key)),
                         f"{judge_rubric.WEIGHTS[key] * 100:.0f}%"]
                    )
                if dim_rows:
                    story.append(
                        _grid_table(["Dimension", "Score", "Weight"], dim_rows, [260, 130, 97], styles)
                    )
                if card.get("strengths"):
                    story.append(_para("Strengths: " + "; ".join(card["strengths"]), styles["body"]))
                if card.get("weaknesses"):
                    story.append(_para("Weaknesses: " + "; ".join(card["weaknesses"]), styles["body"]))
                for key, label in (
                    ("reasoning_quality", "Reasoning quality"),
                    ("evidence_quality_assessment", "Evidence quality"),
                    ("factual_support_assessment", "Factual support (from stored verdicts)"),
                    ("fallacy_impact_assessment", "Fallacy impact"),
                    ("confidence", "Judge confidence"),
                ):
                    if card.get(key):
                        story.append(_para(f"{label}: {card[key]}", styles["small"]))
                if card.get("limitations"):
                    story.append(_para("Limitations: " + "; ".join(card["limitations"]), styles["small"]))

    # ---- Claims and verification ------------------------------------------
    story.append(section("Key Claims and Verification"))
    if not data.claims:
        story.append(_para("No claims have been extracted and stored for this debate.", styles["body"]))
    for index, claim in enumerate(data.claims, start=1):
        story.append(
            _para(
                f"Claim {index} - {claim.agent_name} "
                f"({CLAIM_TYPE_LABELS.get(claim.claim_type, claim.claim_type)})",
                styles["h3"],
            )
        )
        story.append(_para(claim.text, styles["body"]))
        story.append(
            _kv_table(
                [
                    ("Verdict", _verdict_label(claim.verdict)),
                    ("Confidence", CONFIDENCE_LABELS.get(claim.confidence or "", claim.confidence or "Not available")),
                ],
                styles,
            )
        )
        if claim.explanation:
            story.append(_para(claim.explanation, styles["body"]))
        if claim.evidence_summary:
            story.append(_para(f"Evidence summary: {claim.evidence_summary}", styles["small"]))
    if data.claims:
        supported = sum(1 for c in data.claims if c.verdict == "supported")
        contradicted = sum(1 for c in data.claims if c.verdict == "contradicted")
        insufficient = sum(1 for c in data.claims if c.verdict == "insufficient_evidence")
        partial = sum(1 for c in data.claims if c.verdict == "partially_supported")
        unverified = sum(1 for c in data.claims if c.verdict is None)
        story.append(_para("Verification summary", styles["h3"]))
        story.append(
            _grid_table(
                ["Stored claim verdicts", "Claims"],
                [["Supported", str(supported)], ["Contradicted", str(contradicted)],
                 ["Partially supported", str(partial)], ["Insufficient evidence", str(insufficient)], ["Not verified", str(unverified)]],
                [300, 187],
                styles,
            )
        )
        story.append(
            _para(
                "Verdicts describe what the retrieved evidence indicates. "
                "Insufficient evidence never means a claim is false.",
                styles["small"],
            )
        )

    # ---- Evidence sources --------------------------------------------------
    story.append(section("Evidence Sources"))
    if not data.evidence:
        story.append(_para("No retrieved evidence is stored for this debate.", styles["body"]))
    else:
        rows = []
        for item in data.evidence:
            link = _safe_url(item.url)
            title_cell = (
                _para(item.title or item.url, styles["cell"])
                if link is None
                else _link_para(item.title or link, link, styles["cell"])
            )
            rows.append(
                [
                    title_cell,
                    item.source_name or "Unknown source",
                    f"{item.relevance_score:.2f}" if item.relevance_score is not None else "Not scored",
                    _truncate(item.claim_text, 80),
                ]
            )
        story.append(
            _grid_table(["Evidence title (clickable)", "Source", "Relevance", "Claim"],
                        rows, [190, 100, 60, 137], styles)
        )
        story.append(_para("Source URLs", styles["h3"]))
        for item in data.evidence:
            link = _safe_url(item.url)
            if link:
                story.append(_link_para(link, link, styles["small"]))
            if item.source_type == "google_fact_check":
                story.append(_para(
                    f"Published fact-check: {item.publisher or item.source_name}. "
                    f"Original rating: {item.external_rating or 'Not provided'}. "
                    f"Reviewed claim: {item.claim_reviewed or 'Not provided'}. "
                    f"Review date: {item.review_date or 'Not provided'}. Retrieved: {item.retrieved_at or 'Not recorded'}. "
                    "This publisher rating is external evidence, not the MAVES verdict.", styles["small"]))

    # ---- Fallacy and argument quality (only when stored) -------------------
    if data.fallacies or data.evaluations:
        story.append(section("Fallacy and Argument Analysis"))
        if data.fallacies:
            story.append(_para("Stored fallacy detections", styles["h3"]))
            story.append(
                _grid_table(
                    ["Round", "Agent", "Type", "Severity", "Confidence"],
                    [
                        [str(row.round_number), row.agent_name,
                         FALLACY_LABELS.get(row.fallacy_type, row.fallacy_type.replace("_", " ")),
                         row.severity.capitalize(), f"{round(row.confidence * 100)}%"]
                        for row in data.fallacies
                    ],
                    [45, 130, 150, 80, 82],
                    styles,
                )
            )
            for row in data.fallacies:
                story.append(_para(f"Round {row.round_number}, {row.agent_name}: {row.explanation}", styles["small"]))
        if data.evaluations:
            story.append(_para("Stored argument quality evaluations", styles["h3"]))
            story.append(
                _grid_table(
                    ["Round", "Agent", "Logical", "Evidence", "Relevance", "Effect.", "Overall"],
                    [
                        [str(row.round_number), row.agent_name, _fmt_score(row.logical_soundness),
                         _fmt_score(row.evidence_score), _fmt_score(row.relevance_score),
                         _fmt_score(row.effectiveness_score), _fmt_score(row.overall_score)]
                        for row in data.evaluations
                    ],
                    [45, 120, 55, 60, 65, 62, 80],
                    styles,
                )
            )
            for row in data.evaluations:
                story.append(_para(f"Round {row.round_number}, {row.agent_name}: {row.explanation}", styles["small"]))
                story.append(_para(f"Rubric: {row.rubric_version or 'legacy (unversioned)'}", styles["small"]))
                if row.criterion_scores:
                    story.append(_para("; ".join(f"{key.replace('_', ' ')}: {_fmt_score(value)}" for key, value in row.criterion_scores.items()), styles["small"]))
                for label, items in (("Strengths", row.strengths), ("Weaknesses", row.weaknesses)):
                    if items:
                        story.append(_para(label + ": " + "; ".join(items), styles["small"]))

    # ---- Debate transcript -------------------------------------------------
    story.append(section("Debate Transcript"))
    if not data.transcript:
        story.append(_para("No messages have been stored for this debate yet.", styles["body"]))
    current_round = None
    for row in data.transcript:
        if row.round_number != current_round:
            current_round = row.round_number
            story.append(_para(f"Round {row.round_number}", styles["h3"]))
        speaker = f"{row.agent_name} ({row.agent_role})" if row.agent_role else row.agent_name
        kind = row.message_type.replace("_", " ")
        story.append(_para(f"Turn {row.turn_number} - {speaker} - {kind}", styles["speaker"]))
        for paragraph in _content_paragraphs(row.content):
            story.append(_para(paragraph, styles["body"]))

    # ---- Limitations and methodology --------------------------------------
    story.append(section("Limitations and Methodology"))
    if data.coverage:
        story.append(_para("Current persisted analysis coverage", styles["h3"]))
        story.append(_kv_table([
            (key.replace("_", " ").capitalize(), str(value).replace("_", " "))
            for key, value in data.coverage.items()
            if isinstance(value, (int, str))
        ], styles))
    availability: list[str] = []
    if verdict is None:
        availability.append("No final debate verdict is stored for this debate.")
    if judgment is None:
        availability.append("No final judgment is stored for this debate.")
    if not data.claims:
        availability.append("No claims are stored for this debate.")
    if data.claims and not data.evidence:
        availability.append("No evidence has been retrieved for these claims.")
    if data.claims and all(c.verdict is None for c in data.claims):
        availability.append("None of the stored claims have been verified.")
    if not data.fallacies:
        availability.append("No fallacy analysis is stored for this debate.")
    if not data.evaluations:
        availability.append("No argument evaluations are stored for this debate.")
    if data.status != "completed":
        availability.append(f"The debate status is '{data.status}', so its analysis may be incomplete.")
    if availability:
        story.append(_para("Data availability", styles["h3"]))
        for item in availability:
            story.append(_para(f"- {item}", styles["body"]))
    if judgment is not None and judgment.limitations:
        from app.services.debate_judge_service import qualitative_limitations
        items = qualitative_limitations(judgment.limitations)
        if items:
            story.append(_para("Agent performance limitations", styles["h3"]))
        for item in items:
            story.append(_para(f"- {safe_text(item)}", styles["body"]))

    story.append(_para("Important disclaimer", styles["h3"]))
    story.append(
        _para(
            "This report summarizes stored debate records. It is not a "
            "statement of objective truth. LLM-generated text, verdicts, "
            "scores and claim checks can be wrong and must be checked against "
            "the cited sources. Insufficient evidence is not the same as a "
            "confirmed contradiction.",
            styles["body"],
        )
    )
    story.append(_para("Final verdict", styles["h3"]))
    story.append(
        _para(
            "The language model receives the debate question, the stored "
            "transcript and the stored claims with their verification results "
            "(never the agent scores or winner) and answers the question. The "
            "server keeps only citations that match stored claims, forces an "
            "inconclusive verdict when no claim is supported or contradicted "
            "by stored evidence, and caps the confidence by how many claims "
            "the evidence covers.",
            styles["body"],
        )
    )
    if judgment is not None and judgment.scoring_rubric:
        stored = judgment.scoring_rubric or {}
        formula = stored.get("formula") or judge_rubric.FORMULA_TEXT
        weights = stored.get("weights") or judge_rubric.WEIGHTS
    else:
        formula = judge_rubric.FORMULA_TEXT
        weights = judge_rubric.WEIGHTS
    rubric_block = [_para("Agent performance rubric", styles["h3"]), _para(str(formula), styles["body"])]
    if weights:
        rubric_block.append(
            _grid_table(
                ["Dimension", "Weight"],
                [[judge_rubric.DIMENSION_LABELS.get(key, key), f"{float(value) * 100:.0f}%"]
                 for key, value in weights.items()],
                [340, 147],
                styles,
            )
        )
    story.append(KeepTogether(rubric_block))
    story.append(_para("Evidence retrieval and verification", styles["h3"]))
    story.append(
        _para(
            "Evidence is retrieved with the configured web-search provider "
            "using the claim text as the query and stored as neutral sources. "
            "Verification asks the language model whether the stored sources "
            "support, contradict or are insufficient for each claim.",
            styles["body"],
        )
    )
    story.append(_para("Report generation", styles["h3"]))
    story.append(
        _para(
            "This PDF was assembled from stored rows at the generation time "
            "shown on the cover. It runs no new debate, no LLM call and no new "
            "analysis.",
            styles["body"],
        )
    )
    return story


NAVY = colors.HexColor("#0b1230")


class _NumberedCanvas(canvas.Canvas):
    """Canvas that stamps 'Page N of M' once the total is known."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#94a3b8") if self._pageNumber == 1 else MUTED)
        self.drawString(54, 24, "MAVES - AI Debate Arena | Debate Analysis Report")
        self.drawRightString(
            self._pagesize[0] - 54, 24, f"Page {self._pageNumber} of {total}"
        )
        self.restoreState()


def _draw_cover(canv: canvas.Canvas, doc):
    canv.saveState()
    width, height = canv._pagesize
    canv.setFillColor(NAVY)
    canv.rect(0, 0, width, height, stroke=0, fill=1)
    canv.setFillColor(colors.HexColor("#4f46e5"))
    canv.rect(0, height - 8, width, 8, stroke=0, fill=1)
    canv.setStrokeColor(colors.HexColor("#312e81"))
    canv.setLineWidth(1)
    canv.line(54, 60, width - 54, 60)
    canv.restoreState()


def _draw_header(canv: canvas.Canvas, doc):
    canv.saveState()
    width, height = canv._pagesize
    canv.setFillColor(colors.HexColor("#4f46e5"))
    canv.rect(54, height - 37, 10, 10, stroke=0, fill=1)
    canv.setFont("Helvetica-Bold", 8.5)
    canv.setFillColor(INK)
    canv.drawString(70, height - 35, "MAVES")
    canv.setFont("Helvetica", 8)
    canv.setFillColor(MUTED)
    canv.drawRightString(width - 54, height - 35, "Debate Analysis Report")
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.5)
    canv.line(54, height - 42, width - 54, height - 42)
    canv.restoreState()


def render_report_pdf(data: ReportData) -> bytes:
    """Render the assembled data to PDF bytes entirely in memory."""
    styles = _styles()
    buffer = io.BytesIO()
    try:
        doc = SimpleDocTemplate(
            buffer,
            pagesize=(595.27, 841.89),  # A4 portrait
            leftMargin=54,
            rightMargin=54,
            topMargin=58,
            bottomMargin=54,
            title=f"Debate Analysis Report - {safe_text(data.topic)[:80]}",
            author="MAVES - AI Debate Arena",
            subject="Stored debate verdict and analysis",
        )
        doc.build(
            _build_story(data, styles),
            onFirstPage=_draw_cover,
            onLaterPages=_draw_header,
            canvasmaker=_NumberedCanvas,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise ReportRenderError(f"PDF rendering failed: {exc}") from exc
    return buffer.getvalue()


async def build_report(
    db: AsyncSession, user: User, debate_id: UUID
) -> tuple[bytes, str]:
    """Load persisted report data and render the PDF. Returns (bytes, filename).

    Raises debate_service.DebateNotFoundError when the debate does not exist
    or belongs to another user. Never calls the LLM or any external service.
    """
    data = await build_report_data(db, user, debate_id)
    filename = report_filename(data.topic, data.debate_id)
    pdf_bytes = await asyncio.to_thread(render_report_pdf, data)
    return pdf_bytes, filename
