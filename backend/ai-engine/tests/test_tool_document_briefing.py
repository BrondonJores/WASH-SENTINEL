"""Plugin document_briefing : document structuré / deck de slides (100 % offline)."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _fixture_context() -> dict:
    return {
        "schools": [
            {"school_id": 1, "school_name": "École de Ngok", "district": "Mvila"},
            {"school_id": 2, "school_name": "École de Mendong", "district": "Mvila"},
        ],
        "incidents": [
            {"id": 11, "school_id": 1, "school_name": "École de Ngok",
             "district": "Mvila", "reference_code": "WASH-2026-AAAA",
             "title": "Pompe cassée", "summary": "Pompe manuelle cassée",
             "issue_type": "total_breakdown", "urgency": "critical",
             "status": "reported", "affected_students": 450,
             "reported_at": _iso(10)},
            {"id": 12, "school_id": 2, "school_name": "École de Mendong",
             "district": "Mvila", "reference_code": "WASH-2026-BBBB",
             "title": "Fuite robinet", "summary": "Petite fuite au robinet",
             "issue_type": "leak", "urgency": "medium",
             "status": "in_progress", "affected_students": 20,
             "reported_at": _iso(1)},
            {"id": 13, "school_id": 2, "school_name": "École de Mendong",
             "district": "Mvila", "title": "Vieux joint",
             "urgency": "low", "status": "resolved", "affected_students": 999,
             "reported_at": _iso(40)},
        ],
        "maintenance_logs": [
            {"id": 101, "school_id": 1, "school_name": "École de Ngok",
             "incident_id": 11, "incident_ref": "WASH-2026-AAAA",
             "incident_title": "Pompe cassée", "cost_amount": 80000,
             "notes": "Remplacement clapet", "created_at": _iso(2)},
        ],
    }


class DocumentBriefingExecuteTest(unittest.TestCase):
    def test_execute_offline_builds_sections(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["document_briefing"]({"topic": "Mvila"}, _fixture_context())
        self.assertIn("insight", res)
        self.assertNotIn("error", res)
        self.assertEqual(res["format"], "briefing")
        titles = [s["title"] for s in res["sections"]]
        self.assertEqual(titles, ["Résumé", "Chiffres clés", "Priorités",
                                  "Actions recommandées"])
        self.assertTrue(all(s["bullets"] for s in res["sections"]))
        self.assertEqual(res["slides"], [])
        self.assertIn("Mvila", res["insight"])

    def test_execute_fuzzy_topic_matches_school(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["document_briefing"]({"topic": "ngok"}, _fixture_context())
        self.assertNotIn("error", res)
        self.assertIn("ngok", res["sections"][0]["bullets"][0].lower())
        self.assertIn("École de Ngok", res["sections"][2]["bullets"][0])

    def test_execute_diaporama_builds_slides(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["document_briefing"](
            {"topic": "Mvila", "format": "diaporama"}, _fixture_context())
        self.assertNotIn("error", res)
        self.assertGreaterEqual(len(res["slides"]), 2)
        cover = res["slides"][0]
        self.assertEqual(cover["kind"], "cover")
        self.assertEqual(len(cover["stats"]), 3)
        for slide in res["slides"][1:]:
            self.assertIn("title", slide)
            self.assertTrue(slide["lines"])
        self.assertIn("slides", res["insight"])

    def test_execute_rapport_adds_school_detail(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["document_briefing"](
            {"topic": "Mvila", "format": "rapport"}, _fixture_context())
        self.assertNotIn("error", res)
        titles = [s["title"] for s in res["sections"]]
        self.assertIn("Détail par école", titles)

    def test_execute_unknown_topic_returns_error(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["document_briefing"](
            {"topic": "DistrictInexistant"}, _fixture_context())
        self.assertIn("error", res)

    def test_execute_empty_context_returns_error_without_exception(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["document_briefing"]({}, {})
        self.assertIn("error", res)
        res2 = TOOL_EXECUTORS["document_briefing"](
            {"format": "nimporte-quoi"}, {"schools": [], "incidents": []})
        self.assertIn("error", res2)


class DocumentBriefingRouterTest(unittest.TestCase):
    def test_route_intent_document_to_list(self) -> None:
        from app.agent_loop import READ_TOOLS, route_intent, tools_for_intent
        self.assertEqual(
            route_intent("Fais-moi un diaporama du district Mvila"), "list")
        self.assertEqual(
            route_intent("Génère un rapport pour l'école de Ngok"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("document_briefing", names)
        self.assertIn("build_briefing", names)
        self.assertNotIn("prepare_incident", names)
        self.assertIn("document_briefing", READ_TOOLS)

    def test_hints_never_substring_of_legacy_create_other(self) -> None:
        from app.tools.document_briefing import INTENT_HINTS
        from tests.test_agent_loop import RouteIntentTest
        from tests.test_prompt_eval import GOLDEN_CASES, ROUTING_CASES
        legacy = [c["text"].lower() for c in GOLDEN_CASES]
        legacy += [c["question"].lower() for c in ROUTING_CASES
                   if c["intent"] != "list"]
        legacy += [q.lower() for q, exp in RouteIntentTest.CASES if exp != "list"]
        legacy += ["enregistre une intervention",
                   "enregistre une réparation de pompe à ngok",
                   "note les travaux", "note une réparation à 20000 xaf",
                   "ajoute une réparation", "mets a jour le journal",
                   "mets à jour le journal", "journalise les travaux",
                   "note une panne"]
        for hint in INTENT_HINTS:
            for phrase in legacy:
                self.assertNotIn(hint, phrase,
                                 f"hint {hint!r} collide avec un phrasé legacy")

    def test_legacy_create_other_routing_untouched(self) -> None:
        from app.agent_loop import route_intent
        for question in ("Prépare un dossier pour une nouvelle fuite",
                         "Enregistre une intervention de réparation de pompe",
                         "note les travaux"):
            self.assertEqual(route_intent(question), "create")
        for question in ("Résume mon district", "Bonjour Sentinel",
                         "Résumer mon district",
                         "Explique l'incident WASH-001 en langage simple"):
            self.assertEqual(route_intent(question), "other")


class DocumentBriefingCardTest(unittest.TestCase):
    def test_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["document_briefing"](
            {"topic": "Mvila", "format": "diaporama"}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("document_briefing", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "document_briefing")
        self.assertIsNotNone(cards[0])

    def test_card_none_when_empty(self) -> None:
        from app.tools.document_briefing import CARD_BUILDERS
        self.assertIsNone(CARD_BUILDERS["document_briefing"]({"sections": []}))
        self.assertIsNone(CARD_BUILDERS["document_briefing"]({"error": "x"}))


if __name__ == "__main__":
    unittest.main()
