"""Plugin maintenance_team : dispatch futur (charge + tournée)."""
from __future__ import annotations

import unittest


def _fixture_context() -> dict:
    return {
        "incidents": [
            {"id": 1, "school_id": 10, "school_name": "EP Bonanjo",
             "district": "Wouri", "reference_code": "WASH-2026-0001",
             "title": "Fuite tuyau", "urgency": "critical", "status": "open",
             "priority_score": 90.0, "affected_students": 450,
             "assigned_to_user_id": 7},
            {"id": 2, "school_id": 11, "school_name": "EP Deido",
             "district": "Wouri", "reference_code": "WASH-2026-0002",
             "title": "Latrines bouchées", "urgency": "high", "status": "open",
             "priority_score": 70.0, "affected_students": 300},
            {"id": 3, "school_id": 20, "school_name": "EP Mendong",
             "district": "Mvila", "reference_code": "WASH-2026-0003",
             "title": "Forage à sec", "urgency": "medium", "status": "open",
             "priority_score": 50.0, "affected_students": 120,
             "assignee": "Amina"},
            {"id": 4, "school_id": 10, "school_name": "EP Bonanjo",
             "district": "Wouri", "reference_code": "WASH-2026-0004",
             "title": "Pompe cassée", "urgency": "low", "status": "resolved",
             "priority_score": 10.0, "affected_students": 50},
        ],
    }


class MaintenanceTeamPluginTest(unittest.TestCase):
    def test_discovered_readonly_and_merged(self) -> None:
        from app.agent_loop import READ_TOOLS
        from app.agent_tools import AGENT_TOOLS, PLUGIN_HINTS, TOOL_EXECUTORS
        names = [t.get("function", {}).get("name") for t in AGENT_TOOLS]
        self.assertIn("maintenance_team", names)
        self.assertIn("maintenance_team", TOOL_EXECUTORS)
        self.assertIn("maintenance_team", PLUGIN_HINTS)
        self.assertIn("maintenance_team", READ_TOOLS)

    def test_execute_offline_with_fixture(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["maintenance_team"]({}, _fixture_context())
        self.assertIn("insight", res)
        self.assertNotIn("error", res)
        # Charge : 2 districts, résolu ignoré (3 ouverts).
        by_d = {w["district"]: w for w in res["workload"]}
        self.assertEqual(set(by_d), {"Wouri", "Mvila"})
        self.assertEqual(by_d["Wouri"]["open_incidents"], 2)
        self.assertEqual(by_d["Mvila"]["open_incidents"], 1)
        self.assertEqual(by_d["Wouri"]["assigned"], 1)
        self.assertEqual(by_d["Wouri"]["unassigned"], 1)
        # Tournée : 3 écoles, groupées par district, triées par urgence.
        tour = res["suggested_tour"]
        self.assertEqual(len(tour), 3)
        self.assertEqual(tour[0]["district"], "Mvila")
        wouri = [s for s in tour if s["district"] == "Wouri"]
        self.assertEqual(wouri[0]["school_name"], "EP Bonanjo")
        self.assertEqual(wouri[0]["max_urgency"], "critical")

    def test_execute_district_filter(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["maintenance_team"]({"district": "wouri"}, _fixture_context())
        self.assertEqual([w["district"] for w in res["workload"]], ["Wouri"])
        self.assertTrue(all(s["district"] == "Wouri" for s in res["suggested_tour"]))

    def test_router_routes_dispatch_to_list(self) -> None:
        from app.agent_loop import route_intent, tools_for_intent
        self.assertEqual(route_intent("Quelle tournée pour l'équipe ?"), "list")
        self.assertEqual(route_intent("Qui envoyer à Douala, charge de travail ?"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("maintenance_team", names)
        self.assertNotIn("prepare_incident", names)

    def test_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["maintenance_team"]({}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("maintenance_team", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "maintenance_team")
        self.assertIsNotNone(cards[0])


if __name__ == "__main__":
    unittest.main()
