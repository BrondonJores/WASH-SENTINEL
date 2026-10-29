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


class TerritoryCardTest(unittest.TestCase):
    def test_territory_card_type(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        cards = loop._build_cards([("territory_overview", {
            "district": None, "schools": [], "missing_gps": [], "total": 0,
            "open_incidents": 0})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "territory_map")


class FallbackSummaryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.loop = AgentLoop(StubLLM([CALL_DISTRICT]))

    def test_district(self) -> None:
        text = self.loop._fallback_answer([("summarize_district", {
            "open_incidents": 3, "by_urgency": {"critical": 1, "high": 1, "medium": 1},
            "by_category": {"water_point": 3}, "total_affected_students": 645,
            "schools_involved": ["A", "B", "C"]})])
        self.assertIn("3 incidents ouverts", text)
        self.assertIn("645", text)
        self.assertIn("1 critique", text)
        self.assertIn("carte", text)

    def test_trends(self) -> None:
        text = self.loop._fallback_answer([("repair_trends", {
            "school_name": "École Publique de Bonanjo", "months": 3,
            "figures": {"total_cost": 0, "currency": "XAF", "total_incidents": 1,
                        "total_days_lost": 0, "trend_direction": "stable"}})])
        self.assertIn("Bonanjo", text)
        self.assertIn("1 panne", text)
        self.assertIn("carte", text)

    def test_ranking(self) -> None:
        text = self.loop._fallback_answer([("rank_schools_by_need", {
            "ranking": [{"school_name": "École Publique de Bonanjo", "need_score": 14.5}],
            "total": 3})])
        self.assertIn("Bonanjo", text)
        self.assertIn("14,5", text)
        self.assertIn("carte", text)

    def test_ranking_empty(self) -> None:
        text = self.loop._fallback_answer([("rank_schools_by_need", {"ranking": [], "total": 0})])
        self.assertIn("Aucune école", text)

    def test_analysis(self) -> None:
        text = self.loop._fallback_answer([("analyze_school", {
            "school_name": "École Rurale de Ngok", "open_incidents": [{}, {}],
            "recommendation": "REPLACE_EQUIPMENT", "repair_ratio_percent": 60.0})])
        self.assertIn("Ngok", text)
        self.assertIn("remplacer", text)
        self.assertIn("60,0", text)
        self.assertIn("carte", text)

    def test_incident(self) -> None:
        text = self.loop._fallback_answer([("explain_incident", {
            "reference_code": "WASH-2026-0042", "school_name": "E", "title": "Pompe cassée",
            "urgency": "critical", "affected_students": 450})])
        self.assertIn("WASH-2026-0042", text)
        self.assertIn("450", text)
        self.assertIn("carte", text)

    def test_report(self) -> None:
        text = self.loop._fallback_answer([("prepare_report", {
            "description": "Fuite", "matched_school": {"school_name": "Ecole X"}})])
        self.assertIn("Ecole X", text)
        self.assertIn("carte", text)

    def test_territory(self) -> None:
        text = self.loop._fallback_answer([("territory_overview", {
            "district": None, "schools": [{}, {}], "missing_gps": ["E3"],
            "total": 2, "open_incidents": 3})])
        self.assertIn("2 écoles géolocalisées", text)
        self.assertIn("3 incidents", text)
        self.assertIn("carte", text)

    def test_no_success_is_honest(self) -> None:
        text = self.loop._fallback_answer([("analyze_school", {"error": "introuvable"})])
        self.assertNotIn("Voici ce que j'ai trouvé", text)
        self.assertIn("Reformulez", text)
        self.assertEqual(self.loop._fallback_answer([]), text)

    async def test_stubborn_gets_human_summary(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertNotIn("Voici ce que j'ai trouvé", res.answer)
        self.assertIn("carte", res.answer)


class BriefingCardTest(unittest.TestCase):
    def test_briefing_card_type(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        cards = loop._build_cards([("build_briefing", {
            "district": "Mvila", "slides": [], "total": 0})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "briefing_deck")

    def test_briefing_fallback(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        text = loop._fallback_answer([("build_briefing", {
            "district": None, "total": 3,
            "slides": [{"stats": [{"value": "2"}]}]})])
        self.assertIn("3 slides", text)
        self.assertIn("carte", text)
