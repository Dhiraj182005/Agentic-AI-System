"""Structured debate turns (Phase 2): schema validation, rebuttal links,
per-phase prompts, persistence, transcript API and live events."""

import asyncio
import contextlib
import json
import unittest.mock

from sqlalchemy import select

from app.llm.base import LLMResponse
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.orchestration.round_manager import RoundManager
from app.orchestration.turn_format import (
    TranscriptEntry,
    parse_turn,
    render_turn,
    resolve_turn,
)
from app.websocket import events as ws_events
from app.websocket.manager import connection_manager
from tests import test_report as base


def turn_json(**overrides) -> str:
    data = {
        "position": "Subsidies are justified for pilot projects.",
        "position_changed": False,
        "main_argument": "Predictable tidal output lowers grid balancing costs.",
        "rebuttal_to": None,
        "reasoning": "Predictability reduces reserve capacity needs.",
        "factual_claims": ["Tides follow a predictable lunar cycle."],
        "evidence_references": [],
        "concession": None,
        "recommendation": "Fund two pilot sites.",
        "uncertainties": ["Long-term maintenance costs."],
    }
    data.update(overrides)
    return json.dumps(data)


def entry(round_number, name, structured=None, content="text", message_id="m1"):
    return TranscriptEntry(round_number=round_number, agent_name=name, content=content,
                           structured=structured, message_id=message_id, message_type="opening")


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_parse_and_validate():
    turn = parse_turn(turn_json())
    assert turn is not None and turn.main_argument.startswith("Predictable")
    assert parse_turn("```json\n" + turn_json() + "\n```") is not None, "fenced JSON accepted"
    assert parse_turn("Here is my answer: " + turn_json() + " Thanks.") is not None
    assert parse_turn("A plain essay with no JSON.") is None
    assert parse_turn(turn_json(main_argument="")) is None, "required field missing"
    assert parse_turn("{not json}") is None
    many = parse_turn(turn_json(uncertainties=[f"u{i}" for i in range(12)], concession="none"))
    assert len(many.uncertainties) == 5 and many.concession is None
    assert parse_turn(turn_json(position_changed="yes")).position_changed is True
    print("structured turn parsing and validation: PASSED")


def test_rebuttal_resolution_and_render():
    transcript = [entry(1, "Economist", message_id="m-econ"), entry(1, "Lawyer", message_id="m-law")]
    turn = parse_turn(turn_json(rebuttal_to={"ref": "r1-economist", "argument": "costs fall"},
                                concession="Costs are front-loaded."))
    resolved = resolve_turn(turn, transcript, speaker="Lawyer")
    link = resolved.structured["rebuttal_to"]
    assert link == {"ref": "R1-Economist", "message_id": "m-econ", "agent_name": "Economist",
                    "round_number": 1, "argument": "costs fall"}
    assert "**Responding to:** Economist (round 1)" in resolved.content
    assert "**Concession:** Costs are front-loaded." in resolved.content
    assert "**Main argument:**" in resolved.content and resolved.structured["word_count"] > 10

    # Unknown reference: keep what was said, never invent a link.
    turn = parse_turn(turn_json(rebuttal_to={"ref": "R9-Ghost", "argument": "something"}))
    resolved = resolve_turn(turn, transcript, speaker="Lawyer")
    assert resolved.structured["rebuttal_to"]["message_id"] is None and resolved.notes
    # An agent cannot rebut itself.
    turn = parse_turn(turn_json(rebuttal_to={"ref": "R1-Lawyer", "argument": "x"}))
    assert resolve_turn(turn, transcript, speaker="Lawyer").structured["rebuttal_to"]["message_id"] is None
    assert "Evidence referenced (not yet verified)" in render_turn(
        {**resolved.structured, "evidence_references": ["IEA 2023 report"]}
    )
    print("rebuttal references resolve only to real earlier turns: PASSED")


def test_phase_prompts():
    rm = RoundManager(None)
    opening = rm.build_user_prompt("Fund tidal power?", 1, 3, [], word_limit=200)
    assert "Present your strongest reasoned position" in opening
    assert "key assumption" in opening and "at most 200 words" in opening
    assert '"main_argument"' in opening and "Never invent statistics" in opening
    assert "Previous debate transcript" not in opening

    structured = json.loads(turn_json())
    history = [entry(1, "Economist", structured), entry(1, "Lawyer", None, content="Legacy free text " * 80)]
    rebuttal = rm.build_user_prompt("Fund tidal power?", 2, 3, history, agent_name="Economist", word_limit=180)
    assert "Respond to the arguments presented" in rebuttal
    assert "[R1-Economist]" in rebuttal and "Main argument: Predictable tidal output" in rebuttal
    assert "[R1-Lawyer]" in rebuttal and "Legacy free text" in rebuttal, "legacy messages still shown"
    assert "Your earlier turns (do not repeat them" in rebuttal
    assert "do not invent disagreement" in rebuttal and "rebuttal_to" in rebuttal

    closing = rm.build_user_prompt("Fund tidal power?", 3, 3, history, agent_name="Lawyer", word_limit=160)
    assert "Provide your final position" in closing and "strongest remaining objection" in closing
    assert "position_changed" in closing and "uncertainties that remain" in closing

    # Adapts to other round counts.
    assert "Provide your final position" in rm.build_user_prompt("T", 2, 2, history)
    for round_number in (2, 3, 4):
        assert "Respond to the arguments presented" in rm.build_user_prompt("T", round_number, 5, history)
    assert "Present your strongest" in rm.build_user_prompt("T", 1, 1, [])
    # Legacy tuple transcripts are still accepted.
    assert "[R1-Doctor]" in rm.build_user_prompt("T", 2, 3, [(1, "Doctor", "old text")])
    print("phase-specific prompts with limits and references: PASSED")


# ---------------------------------------------------------------------------
# Debate through the API
# ---------------------------------------------------------------------------


class TurnProvider:
    """Agents answer with structured JSON; later turns rebut the first one."""

    def __init__(self, plain_at: set[int] | None = None):
        self.calls = 0
        self.prompts: list[str] = []
        self.plain_at = plain_at or set()

    async def generate(self, messages, temperature=None, max_tokens=None):
        index = self.calls
        self.calls += 1
        self.prompts.append(messages[1].content)
        if index in self.plain_at:
            return LLMResponse(content="I simply think subsidies are wise.", provider="f", model="f")
        rebuttal = None if index == 0 else {"ref": "R1-Economist", "argument": "lower balancing costs"}
        concession = None if index == 0 else "Pilots alone may not prove scalability."
        return LLMResponse(
            content=turn_json(main_argument=f"Argument number {index}.",
                              rebuttal_to=rebuttal, concession=concession),
            provider="f", model="f",
        )


async def test_structured_debate_end_to_end(client):
    token = await base.register_and_login(client, base.unique_email("turns"))
    resp = await client.post("/api/v1/debates", json=base.base_payload(total_rounds=3),
                             headers=base.auth(token))
    debate_id = resp.json()["id"]

    events: list[dict] = []

    async def record(_debate_id, event):
        events.append(event)
        return 0

    provider = TurnProvider(plain_at={4})
    with unittest.mock.patch("app.agents.base_agent.get_llm_provider", return_value=provider), \
            unittest.mock.patch.object(connection_manager, "broadcast", side_effect=record):
        resp = await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))
    assert resp.status_code == 200 and resp.json()["status"] == "completed", resp.text
    assert provider.calls == 6, "one call per turn, no repair calls"

    transcript = (await client.get(f"/api/v1/debates/{debate_id}/messages",
                                   headers=base.auth(token))).json()["messages"]
    first, second = transcript[0], transcript[1]
    assert first["structured"]["main_argument"] == "Argument number 0."
    assert first["structured"]["rebuttal_to"] is None
    link = second["structured"]["rebuttal_to"]
    assert link["message_id"] == first["id"], "rebuttal links to the real earlier message"
    assert second["structured"]["concession"].startswith("Pilots alone")
    assert "**Main argument:** Argument number 1." in second["content"]

    plain = transcript[4]
    assert plain["structured"] is None and plain["content"] == "I simply think subsidies are wise."

    # Later prompts carry the structured history and the agent's own turns.
    round_three_prompt = provider.prompts[4]
    assert "[R1-Economist]" in round_three_prompt and "[R2-Lawyer]" in round_three_prompt
    assert "Your earlier turns" in round_three_prompt
    assert "at most 160 words" in round_three_prompt, "closing word limit"
    assert "at most 180 words" in provider.prompts[2], "rebuttal word limit"

    live = [e for e in events if e["type"] == ws_events.AGENT_MESSAGE]
    assert len(live) == 6
    assert live[1]["data"]["structured"]["rebuttal_to"]["message_id"] == first["id"]
    assert live[4]["data"]["structured"] is None

    async with base._test_session() as session:
        stored = (await session.execute(
            select(DebateMessage).join(DebateRound, DebateRound.id == DebateMessage.round_id)
            .where(DebateMessage.debate_id == debate_id)
        )).scalars().all()
    assert sum(1 for m in stored if m.structured) == 5

    pdf = await client.get(f"/api/v1/debates/{debate_id}/report.pdf", headers=base.auth(token))
    text = base.pdf_text_fragments(pdf.content)
    assert "Argument number 1." in text and "**" not in text, "readable turns in the PDF"
    print("structured debate end to end (API, WebSocket, PDF): PASSED")


async def main():
    test_parse_and_validate()
    test_rebuttal_resolution_and_render()
    test_phase_prompts()
    app = await base.setup()
    async with base.client_for(app) as client:
        await test_structured_debate_end_to_end(client)
    await base.teardown()
    print("\nAll structured debate turn tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
