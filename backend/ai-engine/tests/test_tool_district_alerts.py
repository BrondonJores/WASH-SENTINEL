"""Plugin district_alerts : alertes actionnables (critiques >7j, sans eau, pics)."""
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
             "title": "Latrines bouchées", "summary": "Latrines bouchées",
             "issue_type": "blockage", "urgency": "critical",
             "affected_students": 120, "reported_at": _iso(10)},
            {"id": 12, "school_id": 2, "school_name": "École de Mendong",
             "district": "Douala", "reference_code": "WASH-2026-BBBB",
             "title": "Forage à sec", "summary": "Forage à sec, école sans eau",
             "issue_type": "dry_well", "urgency": "high",
             "affected_students": 300, "reported_at": _iso(2)},
            {"id": 13, "school_id": 2, "school_name": "École de Mendong",
             "district": "Douala", "reference_code": "WASH-2026-CCCC",
             "title": "Petite fuite", "summary": "Petite fuite au robinet",
             "issue_type": "leak", "urgency": "low",
             "affected_students": 10, "reported_at": _iso(1)},
        ],
        "recent_incidents": [
            {"id": 21, "school_id": 1, "reported_at": _iso(1)},
            {"id": 22, "school_id": 2, "reported_at": _iso(2)},
            {"id": 23, "school_id": 1, "reported_at": _iso(3)},
        ],
    }


class DistrictAlertsExecuteTest(unittest.TestCase):
    def test_execute_offline_detects_all_kinds(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["district_alerts"]({"district": "Douala"}, _fixture_context())
        self.assertIn("insight", res)
        kinds = {a["kind"] for a in res["alerts"]}
        self.assertEqual(kinds, {"critical_stale", "no_water", "spike"})
        self.assertEqual(res["total"], 3)
        self.assertTrue(all(a.get("action") for a in res["alerts"]))

    def test_execute_empty_returns_error(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {"schools": [], "incidents": [], "recent_incidents": []}
        res = TOOL_EXECUTORS["district_alerts"]({}, ctx)
        self.assertIn("error", res)
        self.assertEqual(res["alerts"], [])

    def test_execute_no_data_returns_error_without_exception(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["district_alerts"]({}, {})
        self.assertIn("error", res)


class DistrictAlertsRouterTest(unittest.TestCase):
    def test_route_intent_alerts_to_list(self) -> None:
        from app.agent_loop import READ_TOOLS, route_intent, tools_for_intent
        self.assertEqual(route_intent("Y a-t-il des alertes dans mon district ?"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("district_alerts", names)
        self.assertNotIn("prepare_incident", names)
        self.assertIn("district_alerts", READ_TOOLS)

    def test_hints_never_substring_of_legacy_phrases(self) -> None:
        from app.tools.district_alerts import INTENT_HINTS
        from tests.test_prompt_eval import GOLDEN_CASES, ROUTING_CASES
        legacy = [c["text"].lower() for c in GOLDEN_CASES]
        legacy += [c["question"].lower() for c in ROUTING_CASES]
        for hint in INTENT_HINTS:
            for phrase in legacy:
                self.assertNotIn(hint, phrase, f"hint {hint!r} collide avec un phrasé legacy")


class DistrictAlertsCardTest(unittest.TestCase):
    def test_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["district_alerts"]({"district": "Douala"}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("district_alerts", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "district_alerts")

    def test_card_none_when_empty(self) -> None:
        from app.tools.district_alerts import CARD_BUILDERS
        self.assertIsNone(CARD_BUILDERS["district_alerts"]({"alerts": [], "error": "x"}))


if __name__ == "__main__":
    unittest.main()
