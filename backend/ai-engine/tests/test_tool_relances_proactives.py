"""Plugin relances_proactives : incidents dormants + brouillons de relance."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _fixture_context() -> dict:
    return {
        "schools": [
            {"school_id": 1, "school_name": "École de Ngok", "district": "Douala"},
            {"school_id": 2, "school_name": "École de Mendong", "district": "Douala"},
        ],
        "incidents": [
            {"id": 11, "school_id": 1, "school_name": "École de Ngok",
             "district": "Douala", "reference_code": "WASH-2026-AAAA",
             "title": "Pompe cassée", "summary": "Pompe manuelle cassée",
             "status": "open", "urgency": "high",
             "affected_students": 120, "reported_at": _iso(21)},
            {"id": 12, "school_id": 2, "school_name": "École de Mendong",
             "district": "Douala", "reference_code": "WASH-2026-BBBB",
             "title": "Fuite au robinet", "summary": "Fuite au robinet",
             "status": "open", "urgency": "low",
             "affected_students": 30, "reported_at": _iso(12)},
            {"id": 13, "school_id": 2, "school_name": "École de Mendong",
             "district": "Douala", "reference_code": "WASH-2026-CCCC",
             "title": "Latrines bouchées", "summary": "Latrines bouchées",
             "status": "open", "urgency": "medium",
             "affected_students": 60, "reported_at": _iso(30)},
            {"id": 14, "school_id": 1, "school_name": "École de Ngok",
             "district": "Douala", "reference_code": "WASH-2026-DDDD",
             "title": "Forage récent", "summary": "Forage à sec signalé hier",
             "status": "open", "urgency": "critical",
             "affected_students": 300, "reported_at": _iso(1)},
            {"id": 15, "school_id": 1, "school_name": "École de Ngok",
             "district": "Douala", "reference_code": "WASH-2026-EEEE",
             "title": "Fuite résolue", "summary": "Fuite résolue",
             "status": "resolved", "urgency": "low",
             "affected_students": 10, "reported_at": _iso(40)},
        ],
        "maintenance_logs": [
            {"id": 101, "incident_id": 13, "incident_ref": "WASH-2026-CCCC",
             "school_name": "École de Mendong", "notes": "Visite de suivi",
             "created_at": _iso(2)},
        ],
    }


class RelancesExecuteTest(unittest.TestCase):
    def test_execute_detects_dormant_with_draft(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["relances_proactives"](
            {"days": 7}, _fixture_context())
        self.assertIn("insight", res)
        refs = [i["reference_code"] for i in res["items"]]
        # 11 et 12 dormants ; 13 a un journal récent ; 14 frais ; 15 résolu.
        self.assertEqual(refs, ["WASH-2026-AAAA", "WASH-2026-BBBB"])
        self.assertEqual(res["total"], 2)
        idles = [i["days_idle"] for i in res["items"]]
        self.assertEqual(idles, sorted(idles, reverse=True))
        for item in res["items"]:
            for key in ("school_name", "incident_title", "reference_code",
                        "days_idle", "draft_message"):
                self.assertIn(key, item)
            self.assertTrue(item["draft_message"])
            self.assertIn(str(item["days_idle"]), item["draft_message"])

    def test_execute_none_dormant_returns_error(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {"incidents": [
            {"id": 1, "school_name": "E", "district": "D",
             "reference_code": "WASH-1", "title": "Frais",
             "status": "open", "reported_at": _iso(1)},
        ], "maintenance_logs": []}
        res = TOOL_EXECUTORS["relances_proactives"]({"days": 7}, ctx)
        self.assertIn("error", res)
        self.assertEqual(res.get("items"), [])

    def test_execute_no_data_returns_error_without_exception(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["relances_proactives"]({}, {})
        self.assertIn("error", res)

    def test_execute_district_filter(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["relances_proactives"](
            {"days": 7, "district": "Yaoundé"}, _fixture_context())
        self.assertIn("error", res)


class RelancesRouterTest(unittest.TestCase):
    def test_route_intent_relance_to_list(self) -> None:
        from app.agent_loop import READ_TOOLS, route_intent, tools_for_intent
        self.assertEqual(
            route_intent("Quels incidents dormants dois-je relancer ?"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("relances_proactives", names)
        self.assertNotIn("prepare_incident", names)
        self.assertIn("relances_proactives", READ_TOOLS)

    def test_hints_never_substring_of_legacy_phrases(self) -> None:
        from app.tools.relances_proactives import INTENT_HINTS
        from tests.test_agent_loop import RouteIntentTest
        from tests.test_prompt_eval import GOLDEN_CASES, ROUTING_CASES
        legacy = [c["text"].lower() for c in GOLDEN_CASES]
        legacy += [c["question"].lower() for c in ROUTING_CASES]
        legacy += [q.lower() for q, _ in RouteIntentTest.CASES]
        legacy += ["enregistre une intervention", "note une panne",
                   "journalise les travaux", "mets à jour le journal",
                   "mets a jour le journal", "note les travaux",
                   "que sais-tu faire ?", "bonjour sentinel"]
        for hint in INTENT_HINTS:
            for phrase in legacy:
                self.assertNotIn(hint, phrase,
                                 f"hint {hint!r} collide avec un phrasé legacy")


class RelancesCardTest(unittest.TestCase):
    def test_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["relances_proactives"](
            {"days": 7}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("relances_proactives", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "relances")

    def test_card_none_when_empty(self) -> None:
        from app.tools.relances_proactives import CARD_BUILDERS
        self.assertIsNone(CARD_BUILDERS["relances"]({"items": [], "error": "x"}))


if __name__ == "__main__":
    unittest.main()
