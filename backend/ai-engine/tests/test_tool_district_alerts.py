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

    def test_execute_empty_returns_typed_empty(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {"schools": [], "incidents": [], "recent_incidents": []}
        res = TOOL_EXECUTORS["district_alerts"]({}, ctx)
        # Vide valide (AXE 7 / P1b) : pas d'erreur, carte typée vide.
        self.assertNotIn("error", res)
        self.assertEqual(res["alerts"], [])
        self.assertEqual(res["total"], 0)
        self.assertIn("Aucune alerte", res["insight"])

    def test_execute_no_data_returns_error_without_exception(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["district_alerts"]({}, {})
        self.assertIn("error", res)

    def test_execute_dateless_critical_kept(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {
            "schools": [
                {"school_id": 1, "school_name": "École de Ngok",
                 "district": "Douala"},
            ],
            "incidents": [
                {"id": 11, "school_id": 1, "school_name": "École de Ngok",
                 "district": "Douala", "reference_code": "WASH-2026-DATE",
                 "title": "Pompe cassée", "summary": "Pompe cassée",
                 "issue_type": "total_breakdown", "urgency": "critical",
                 "affected_students": 120},  # sans reported_at
            ],
            "recent_incidents": [],
        }
        res = TOOL_EXECUTORS["district_alerts"]({"district": "Douala"}, ctx)
        self.assertNotIn("error", res)
        kinds = [a["kind"] for a in res["alerts"]]
        self.assertIn("critical_stale", kinds)
        stale = next(a for a in res["alerts"]
                     if a["kind"] == "critical_stale")
        self.assertIsNone(stale["age_days"])
        self.assertEqual(stale["severity"], "critical")
        self.assertIn("sans date", stale["action"])

    def test_execute_spike_from_incidents_only(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {
            "schools": [
                {"school_id": 1, "school_name": "École de Ngok",
                 "district": "Douala"},
            ],
            "incidents": [
                {"id": 11, "school_id": 1, "school_name": "École de Ngok",
                 "district": "Douala", "title": f"Petite fuite {i}",
                 "summary": "Petite fuite", "issue_type": "leak",
                 "urgency": "low", "reported_at": _iso(1)}
                for i in range(3)
            ],
            "recent_incidents": [],
        }
        # Ids distincts requis pour 3 incidents frais.
        for pos, incident in enumerate(ctx["incidents"]):
            incident["id"] = 11 + pos
        res = TOOL_EXECUTORS["district_alerts"]({"district": "Douala"}, ctx)
        self.assertNotIn("error", res)
        spikes = [a for a in res["alerts"] if a["kind"] == "spike"]
        self.assertEqual(len(spikes), 1)
        self.assertIn("3 incidents", spikes[0]["title"])

    def test_execute_spike_dedups_across_pools(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        incident = {"id": 11, "school_id": 1, "school_name": "École de Ngok",
                    "district": "Douala", "title": "Fuite",
                    "summary": "Fuite", "issue_type": "leak",
                    "urgency": "low", "reported_at": _iso(1)}
        ctx = {
            "schools": [{"school_id": 1, "school_name": "École de Ngok",
                         "district": "Douala"}],
            "incidents": [dict(incident, id=11), dict(incident, id=12),
                          dict(incident, id=13)],
            # Mêmes ids dans recent_incidents : doublons à dédupliquer.
            "recent_incidents": [{"id": 11, "school_id": 1,
                                  "reported_at": _iso(1)},
                                 {"id": 12, "school_id": 1,
                                  "reported_at": _iso(1)}],
        }
        res = TOOL_EXECUTORS["district_alerts"]({"district": "Douala"}, ctx)
        spikes = [a for a in res["alerts"] if a["kind"] == "spike"]
        self.assertEqual(len(spikes), 1)
        self.assertIn("3 incidents", spikes[0]["title"])


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

    def test_card_none_on_error(self) -> None:
        from app.tools.district_alerts import CARD_BUILDERS
        build = CARD_BUILDERS["district_alerts"]
        self.assertIsNone(build({"alerts": [], "error": "x"}))
        self.assertIsNone(build({}))

    def test_card_typed_when_empty(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {"schools": [], "incidents": [], "recent_incidents": []}
        obs = TOOL_EXECUTORS["district_alerts"]({"district": "Douala"}, ctx)
        self.assertNotIn("error", obs)
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("district_alerts", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "district_alerts")
        self.assertEqual(cards[0].data["alerts"], [])


if __name__ == "__main__":
    unittest.main()
