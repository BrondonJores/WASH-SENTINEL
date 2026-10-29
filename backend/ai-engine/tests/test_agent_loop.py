"""Boucle agent : un outil déjà appelé ne doit jamais être ré-exécuté.

Contexte : les petits modèles rappellent parfois le même outil au lieu de
conclure (5x summarize_district -> 5 cartes identiques). La boucle doit
détecter la répétition, recadrer le modèle, puis s'arrêter proprement.

Lancer depuis backend/ai-engine : python3 -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import unittest

from app.agent_loop import AgentLoop
from app.schemas import AgentChatRequest, AgentContext

CONTEXT = AgentContext(
    schools=[],
    incidents=[
        {"id": 1, "school_name": "E1", "urgency": "critical",
         "category": "water_point", "affected_students": 100},
        {"id": 2, "school_name": "E2", "urgency": "high",
         "category": "toilets_latrines", "affected_students": 50},
    ],
)

CALL_DISTRICT = {
    "raw": {"role": "assistant", "content": ""},
    "content": "",
    "tool_calls": [{"id": "1", "name": "summarize_district", "arguments": {}}],
}


class StubLLM:
    """Provider scripté : rejoue les réponses puis répète la dernière."""

    def __init__(self, script: list[dict]):
        self.model = "stub"
        self.script = list(script)
        self.calls = 0

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls += 1
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        return {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}


class AgentLoopRepeatTest(unittest.IsolatedAsyncioTestCase):
    async def test_stubborn_model_executes_once(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertEqual(res.tools_executed, ["summarize_district"])
        self.assertEqual(len(res.cards), 1)
        self.assertEqual(res.cards[0].type, "district_summary")

    async def test_reasonable_model_keeps_answer(self) -> None:
        loop = AgentLoop(StubLLM([
            CALL_DISTRICT,
            {"raw": {"role": "assistant", "content": "2 incidents ouverts."},
             "content": "2 incidents ouverts.", "tool_calls": []},
        ]))
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertEqual(res.answer, "2 incidents ouverts.")
        self.assertEqual(len(res.cards), 1)

    def test_identical_cards_deduplicated(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        obs = {"open_incidents": 2, "by_urgency": {}, "by_category": {},
               "total_affected_students": 150, "schools_involved": ["E1"]}
        cards = loop._build_cards([("summarize_district", obs), ("summarize_district", obs)])
        self.assertEqual(len(cards), 1)


if __name__ == "__main__":
    unittest.main()
