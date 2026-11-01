"""Plugin observatoire : chiffres clés du territoire, routage, carte."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


def _fixture_context() -> dict:
    now = datetime.now(timezone.utc)
    day = now - timedelta(days=2)
    old_month = now - timedelta(days=45)
    stamp = day.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    old_stamp = old_month.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return {
        "schools": [
            {"school_id": 1, "district": "Douala"},
            {"school_id": 2, "district": "Bonanjo"},
        ],
        "incidents": [
            {"id": 1, "status": "open", "district": "Douala",
             "urgency": "critical", "category": "water",
             "affected_students": 100, "reported_at": stamp},
            {"id": 2, "status": "open", "district": "Douala",
             "urgency": "high", "category": "sanitation",
             "affected_students": 50, "reported_at": stamp},
            {"id": 3, "status": "open", "district": "Bonanjo",
             "urgency": "medium", "category": "water",
             "affected_students": 30, "reported_at": old_stamp},
            {"id": 4, "status": "resolved", "district": "Douala",
             "urgency": "critical", "category": "water",
             "affected_students": 999, "reported_at": old_stamp},
        ],
    }


class ObservatoireExecuteTest(unittest.TestCase):
    def test_execute_offline_with_fixture(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["observatoire"]({}, _fixture_context())
        self.assertNotIn("error", res)
        self.assertIn("insight", res)
        totals = res["totals"]
        self.assertEqual(totals["incidents_open"], 3)
        self.assertEqual(totals["schools"], 2)
        self.assertEqual(totals["affected_students"], 180)
        self.assertEqual(totals["critical"], 1)
        by_district = {s["district"]: s for s in res["by_district"]}
        self.assertEqual(by_district["Douala"]["open"], 2)
        self.assertEqual(by_district["Douala"]["critical"], 1)
        self.assertEqual(by_district["Bonanjo"]["open"], 1)
        urgencies = {u["urgency"]: u["count"] for u in res["by_urgency"]}
        self.assertEqual(urgencies, {"critical": 1, "high": 1, "medium": 1})
        self.assertEqual(len(res["trend"]), 6)
        for point in res["trend"]:
            self.assertRegex(point["month"], r"^\d{4}-\d{2}$")
            self.assertIsInstance(point["count"], int)
        self.assertGreaterEqual(sum(p["count"] for p in res["trend"]), 3)
        # Insight FR en 2 phrases.
        self.assertEqual(res["insight"].count("."), 2)

    def test_execute_empty_returns_error(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["observatoire"]({}, {"incidents": [], "schools": []})
        self.assertIn("error", res)
        res_none = TOOL_EXECUTORS["observatoire"]({}, {})
        self.assertIn("error", res_none)


class ObservatoireRoutingTest(unittest.TestCase):
    def test_route_to_list(self) -> None:
        from app.agent_loop import READ_TOOLS, route_intent, tools_for_intent
        self.assertEqual(route_intent("Montre-moi l'observatoire du territoire"), "list")
        self.assertEqual(route_intent("Donne les chiffres clés du territoire"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("observatoire", names)
        self.assertNotIn("prepare_incident", names)
        self.assertIn("observatoire", READ_TOOLS)

    def test_hints_never_substring_of_legacy(self) -> None:
        from app.tools.observatoire import INTENT_HINTS
        from tests.test_agent_loop import RouteIntentTest
        from tests.test_prompt_eval import GOLDEN_CASES, ROUTING_CASES
        for hint in INTENT_HINTS:
            for banned in ("état", "etat", "aide", "besoin"):
                self.assertNotIn(banned, hint, f"hint {hint!r} contient {banned!r}")
        legacy = [c["text"].lower() for c in GOLDEN_CASES]
        legacy += [c["question"].lower() for c in ROUTING_CASES
                   if c["intent"] != "list"]
        legacy += [q.lower() for q, exp in RouteIntentTest.CASES if exp != "list"]
        for hint in INTENT_HINTS:
            for phrase in legacy:
                self.assertNotIn(hint, phrase,
                                 f"hint {hint!r} collide avec un phrasé legacy")


class ObservatoireCardTest(unittest.TestCase):
    def test_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["observatoire"]({}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("observatoire", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "observatoire")
        self.assertIsNotNone(cards[0])

    def test_no_card_on_error(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["observatoire"]({}, {})
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("observatoire", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "guidance")


if __name__ == "__main__":
    unittest.main()
