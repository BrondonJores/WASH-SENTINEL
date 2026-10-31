"""Streaming SSE Sentinel : ordre tools -> deltas -> done + intégrité du contenu.

Lancer depuis backend/ai-engine : .venv/bin/python -m unittest tests.test_agent_stream
"""
from __future__ import annotations

import json
import unittest

from app.agent_loop import AgentLoop
from app.agent_stream import CHUNK_SIZE, format_sse, stream_agent_events
from app.schemas import AgentChatRequest, AgentContext

CONTEXT = AgentContext(
    schools=[],
    incidents=[
        {"id": 1, "school_name": "E1", "urgency": "critical",
         "category": "water_point", "affected_students": 100},
    ],
)

ANSWER = (
    "Le district compte 1 incident ouvert critique touchant 100 élèves. "
    "Le détail est dans la carte ci-dessous."
)

CALL_DISTRICT = {
    "raw": {"role": "assistant", "content": ""},
    "content": "",
    "tool_calls": [{"id": "1", "name": "summarize_district", "arguments": {}}],
}

FINAL = {
    "raw": {"role": "assistant", "content": ANSWER},
    "content": ANSWER,
    "tool_calls": [],
}


class StubLLM:
    """Provider scripté : rejoue les réponses puis répète la dernière."""

    def __init__(self, script: list[dict]):
        self.model = "stub"
        self.script = list(script)

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        return {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}


async def _collect(loop: AgentLoop, message: str = "résume") -> list[dict]:
    req = AgentChatRequest(message=message, context=CONTEXT)
    return [event async for event in stream_agent_events(loop, req)]


class AgentStreamOrderTest(unittest.IsolatedAsyncioTestCase):
    async def test_order_is_tools_cards_deltas_done(self) -> None:
        events = await _collect(AgentLoop(StubLLM([CALL_DISTRICT, FINAL])))
        kinds = [e["event"] for e in events]
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(kinds[0], "tools")
        self.assertEqual(kinds[1], "cards")
        self.assertEqual(kinds[-1], "done")
        middle = kinds[2:-1]
        self.assertTrue(middle, "la réponse doit être découpée en deltas")
        self.assertTrue(all(k == "delta" for k in middle))

    async def test_tools_cards_and_done_payloads(self) -> None:
        events = await _collect(AgentLoop(StubLLM([CALL_DISTRICT, FINAL])))
        by_kind = {e["event"]: e for e in events if e["event"] != "delta"}
        self.assertEqual(by_kind["tools"]["tools"], ["summarize_district"])
        self.assertEqual(len(by_kind["cards"]["cards"]), 1)
        self.assertEqual(by_kind["cards"]["cards"][0]["type"], "district_summary")
        self.assertEqual(by_kind["done"]["model"], "stub")
        self.assertIsInstance(by_kind["done"]["follow_ups"], list)


class AgentStreamContentTest(unittest.IsolatedAsyncioTestCase):
    async def test_deltas_reassemble_full_answer(self) -> None:
        events = await _collect(AgentLoop(StubLLM([CALL_DISTRICT, FINAL])))
        deltas = [e["text"] for e in events if e["event"] == "delta"]
        self.assertEqual("".join(deltas), ANSWER)

    async def test_delta_chunks_are_short(self) -> None:
        events = await _collect(AgentLoop(StubLLM([CALL_DISTRICT, FINAL])))
        deltas = [e["text"] for e in events if e["event"] == "delta"]
        self.assertGreater(len(deltas), 1)
        for text in deltas:
            self.assertLessEqual(len(text), CHUNK_SIZE)

    async def test_format_sse_named_event(self) -> None:
        frame = format_sse({"event": "delta", "text": "abc"})
        self.assertTrue(frame.startswith("event: delta\n"))
        self.assertIn('"text": "abc"', frame)
        self.assertTrue(frame.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
