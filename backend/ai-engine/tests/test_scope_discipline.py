"""Discipline de périmètre : une école demandée = UNIQUEMENT cette école.

Non-régression prod : « Faut-il réparer à Ngok ? » ne doit plus parler des
incidents d'autres écoles (cartes district/alertes, mentions parasites).

Lancer depuis backend/ai-engine : ./.venv/bin/python -m unittest
"""
from __future__ import annotations

import json
import unittest

from app.agent_loop import (
    AgentLoop,
    _blocked_by_scope,
    _follow_ups,
    detect_scope,
    mentioned_places,
    strip_other_school_mentions,
    tools_for_intent,
)
from app.schemas import AgentChatRequest, AgentContext

NGOK = "École Rurale de Ngok"
BONANJO = "École Publique de Bonanjo"
KRIBI = "École de Kribi Centre"

CONTEXT = AgentContext(
    schools=[
        {"school_id": 1, "school_name": NGOK, "district": "Mvila",
         "lat": 3.5, "lng": 11.5},
        {"school_id": 2, "school_name": BONANJO, "district": "Wouri",
         "lat": 4.0, "lng": 9.7},
        {"school_id": 3, "school_name": KRIBI, "district": "Océan",
         "lat": 2.9, "lng": 9.9},
    ],
    incidents=[
        {"id": 1, "school_id": 1, "school_name": NGOK, "district": "Mvila",
         "title": "Pompe cassée", "urgency": "high",
         "affected_students": 120, "status": "open"},
        {"id": 2, "school_id": 2, "school_name": BONANJO, "district": "Wouri",
         "title": "Fuite robinet", "urgency": "critical",
         "affected_students": 300, "status": "open"},
    ],
)
CTX = CONTEXT.model_dump()


def _scope_single() -> dict:
    return detect_scope("Faut-il réparer à Ngok ?", CTX)


def _call(name: str, args: dict) -> dict:
    return {"raw": {"role": "assistant", "content": ""}, "content": "",
            "tool_calls": [{"id": "1", "name": name, "arguments": args}]}


def _text(content: str) -> dict:
    return {"raw": {"role": "assistant", "content": content},
            "content": content, "tool_calls": []}


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


class DetectScopeTest(unittest.TestCase):
    def test_single_school(self) -> None:
        scope = detect_scope("Faut-il réparer à Ngok ?", CTX)
        self.assertEqual(scope["scope"], "school")
        self.assertEqual(scope["school"], NGOK)
        self.assertEqual(scope["schools"], [NGOK])

    def test_single_school_with_generic_word(self) -> None:
        # « école » générique ne désigne aucune école : Ngok seule.
        scope = detect_scope("Tendances de l'école Ngok", CTX)
        self.assertEqual(scope["scope"], "school")
        self.assertEqual(scope["schools"], [NGOK])

    def test_district_word_widens(self) -> None:
        scope = detect_scope("Résumez mon district", CTX)
        self.assertEqual(scope["scope"], "district")
        scope = detect_scope("Résume le district de Mvila", CTX)
        self.assertEqual(scope["scope"], "district")
        self.assertEqual(scope["district"], "Mvila")

    def test_territory_widens(self) -> None:
        scope = detect_scope("Montrez la carte du territoire", CTX)
        self.assertEqual(scope["scope"], "territory")

    def test_all_schools_widens(self) -> None:
        scope = detect_scope("Toutes les écoles ont-elles de l'eau ?", CTX)
        self.assertEqual(scope["scope"], "district")
        scope = detect_scope("Et les autres écoles ?", CTX)
        self.assertEqual(scope["scope"], "district")

    def test_explicit_comparison_is_multi_school(self) -> None:
        scope = detect_scope("Compare Ngok et Kribi", CTX)
        self.assertEqual(scope["scope"], "school")
        self.assertEqual(scope["schools"], [NGOK, KRIBI])
        scope = detect_scope("Ngok vs Bonanjo : laquelle a plus de pannes ?", CTX)
        self.assertEqual(scope["scope"], "school")
        self.assertEqual(len(scope["schools"]), 2)

    def test_compare_over_time_stays_single_school(self) -> None:
        scope = detect_scope("Compare les tendances de Ngok sur 6 mois", CTX)
        self.assertEqual(scope["scope"], "school")
        self.assertEqual(scope["schools"], [NGOK])

    def test_default_without_place_is_broad(self) -> None:
        scope = detect_scope("Bonjour", CTX)
        self.assertEqual(scope["scope"], "district")
        self.assertEqual(scope["schools"], [])

    def test_mentioned_places_reuses_known_places(self) -> None:
        schools, districts = mentioned_places("Compare Ngok et Kribi", CTX)
        self.assertEqual(schools, [NGOK, KRIBI])
        self.assertEqual(districts, [])
        schools, districts = mentioned_places("Résume le district de Mvila", CTX)
        self.assertEqual(schools, [])
        self.assertEqual(districts, ["Mvila"])


class BlockedByScopeTest(unittest.TestCase):
    def test_district_tools_blocked_for_single_school(self) -> None:
        scope = _scope_single()
        for name in ("summarize_district", "district_alerts", "epidemic_alerts",
                     "territory_overview", "observatoire", "rank_schools_by_need",
                     "build_briefing", "compare_schools"):
            with self.subTest(tool=name):
                self.assertIsNotNone(_blocked_by_scope(name, {}, scope))

    def test_school_tools_allowed_for_single_school(self) -> None:
        scope = _scope_single()
        self.assertIsNone(_blocked_by_scope("analyze_school", {"school": "Ngok"}, scope))
        self.assertIsNone(_blocked_by_scope(
            "repair_trends", {"school": "Ngok", "months": 3}, scope))
        self.assertIsNone(_blocked_by_scope("explain_incident", {"incident_id": 1}, scope))

    def test_global_calls_blocked_for_single_school(self) -> None:
        scope = _scope_single()
        self.assertIsNotNone(_blocked_by_scope("repair_trends", {}, scope))
        self.assertIsNotNone(
            _blocked_by_scope("repair_trends", {"district": "Mvila"}, scope))
        self.assertIsNotNone(
            _blocked_by_scope("list_maintenance_logs", {"date": "2026-10-15"}, scope))
        self.assertIsNone(_blocked_by_scope(
            "list_maintenance_logs", {"school": "Ngok"}, scope))

    def test_other_school_call_blocked(self) -> None:
        scope = _scope_single()
        self.assertIsNotNone(
            _blocked_by_scope("analyze_school", {"school": "Kribi"}, scope))

    def test_broad_scope_blocks_nothing(self) -> None:
        for scope in (None,
                      detect_scope("Résumez mon district", CTX),
                      detect_scope("Compare Ngok et Kribi", CTX)):
            with self.subTest(scope=(scope or {}).get("scope")):
                self.assertIsNone(_blocked_by_scope("summarize_district", {}, scope))
                self.assertIsNone(_blocked_by_scope("territory_overview", {}, scope))

    def test_exposed_tools_masked_for_single_school(self) -> None:
        names = [t.get("function", {}).get("name", "")
                 for t in tools_for_intent("other", _scope_single())]
        self.assertNotIn("summarize_district", names)
        self.assertNotIn("territory_overview", names)
        self.assertIn("analyze_school", names)
        self.assertIn("repair_trends", names)


class StripMentionsTest(unittest.TestCase):
    def test_other_school_sentence_dropped_generic_kept(self) -> None:
        scope = _scope_single()
        answer = ("À Ngok : 1 panne ouverte. "
                  "À Bonanjo : 1 panne critique touche 300 élèves. "
                  "La situation est stable.")
        scrubbed = strip_other_school_mentions(answer, scope, CTX)
        self.assertIn("Ngok", scrubbed)
        self.assertIn("La situation est stable.", scrubbed)
        self.assertNotIn("Bonanjo", scrubbed)
        self.assertNotIn("300", scrubbed)

    def test_comparison_keeps_both_schools(self) -> None:
        scope = detect_scope("Compare Ngok et Kribi", CTX)
        answer = "À Ngok : 1 panne. À Kribi : 0 panne."
        self.assertEqual(strip_other_school_mentions(answer, scope, CTX), answer)

    def test_district_scope_unchanged(self) -> None:
        scope = detect_scope("Résumez mon district", CTX)
        answer = "À Ngok : 1 panne. À Bonanjo : 1 panne."
        self.assertEqual(strip_other_school_mentions(answer, scope, CTX), answer)


class SchoolCardsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = AgentLoop(StubLLM([_text("ok")]))

    def test_only_school_cards_for_single_school(self) -> None:
        executed = [
            ("analyze_school", {"school_name": NGOK, "open_incidents": [{}],
                                "recommendation": "MONITOR_CLOSELY",
                                "repair_ratio_percent": 10.0}),
            ("summarize_district", {"open_incidents": 2, "by_urgency": {},
                                    "total_affected_students": 420,
                                    "schools_involved": [NGOK, BONANJO]}),
            ("repair_trends", {"school_name": NGOK, "months": 3,
                               "figures": {"total_incidents": 1},
                               "calendar_heatmap": {"days": []},
                               "budget_compare": {"total_XAF": 999}}),
            ("territory_overview", {"district": None, "schools": [],
                                    "missing_gps": [], "total": 0,
                                    "open_incidents": 0}),
        ]
        cards = self.loop._build_cards(executed, CTX, scope=_scope_single())
        types = [c.type for c in cards]
        self.assertIn("school_analysis", types)
        self.assertIn("trend_chart", types)
        self.assertIn("calendar_heatmap", types)
        self.assertNotIn("district_summary", types)
        self.assertNotIn("territory_map", types)
        self.assertNotIn("budget_compare", types)

    def test_other_school_incident_card_dropped(self) -> None:
        executed = [
            ("explain_incident", {"id": 2, "reference_code": "WASH-2026-0002",
                                  "school_name": BONANJO, "title": "Fuite",
                                  "urgency": "critical",
                                  "affected_students": 300}),
        ]
        cards = self.loop._build_cards(executed, CTX, scope=_scope_single())
        self.assertEqual(cards, [])

    def test_district_scope_keeps_all_cards(self) -> None:
        executed = [
            ("summarize_district", {"open_incidents": 2, "by_urgency": {},
                                    "total_affected_students": 420,
                                    "schools_involved": [NGOK, BONANJO]}),
        ]
        scope = detect_scope("Résumez mon district", CTX)
        cards = self.loop._build_cards(executed, CTX, scope=scope)
        self.assertEqual([c.type for c in cards], ["district_summary"])

    def test_guidance_actions_stay_in_school_scope(self) -> None:
        cards = self.loop._build_cards(
            [("analyze_school", {"error": "école introuvable"})],
            CTX, scope=_scope_single())
        self.assertEqual(len(cards), 1)
        questions = " ".join(a.get("question", "")
                             for a in cards[0].data.get("actions", []))
        self.assertIn("Ngok", questions)
        self.assertNotIn("district", questions.lower())


class SchoolFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = AgentLoop(StubLLM([_text("ok")]))

    def test_fallback_proposes_same_school_not_district(self) -> None:
        text = self.loop._fallback_answer([], CTX, scope=_scope_single())
        self.assertIn("Ngok", text)
        self.assertNotIn("district", text.lower())
        self.assertNotIn("territoire", text.lower())

    def test_follow_ups_stay_in_school_scope(self) -> None:
        chips = _follow_ups("Bonjour, parle-moi de Ngok", [], CTX,
                            _scope_single())
        self.assertTrue(chips)
        joined = " ".join(chips)
        self.assertIn("Ngok", joined)
        self.assertNotIn("district", joined.lower())


class SchoolChatIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_district_tool_not_executed_for_school_question(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("summarize_district", {}),
            _call("analyze_school", {"school": "Ngok"}),
            _text("À Ngok : 1 panne ouverte. À Bonanjo : tout va bien."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="Faut-il réparer à Ngok ?", context=CONTEXT))
        self.assertNotIn("summarize_district", res.tools_executed)
        self.assertIn("analyze_school", res.tools_executed)
        self.assertNotIn("Bonanjo", res.answer)
        self.assertNotIn("district_summary",
                         [c.type for c in res.cards])


if __name__ == "__main__":
    unittest.main()
