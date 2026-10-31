"""Plugin interventoils_mission : timeline passée des missions terrain."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


def _ctx() -> dict:
    today = datetime.now(timezone.utc).date()

    def day(n: int) -> str:
        return (today - timedelta(days=n)).isoformat() + "T08:00:00+00:00"

    return {
        "schools": [
            {"school_id": 1, "school_name": "Ecole Ngok", "district": "Mvila"},
            {"school_id": 2, "school_name": "Ecole Mendong", "district": "Mvila"},
            {"school_id": 3, "school_name": "Ecole Bonanjo", "district": "Wouri"},
        ],
        "incidents": [],
        "maintenance_logs": [
            {"id": 1, "school_id": 1, "school_name": "Ecole Ngok",
             "incident_title": "Réparation pompe", "cost_amount": 50000,
             "created_at": day(2)},
            {"id": 2, "school_id": 2, "school_name": "Ecole Mendong",
             "incident_title": "Fuite tuyau", "cost_amount": 30000,
             "created_at": day(5)},
            {"id": 3, "school_id": 1, "school_name": "Ecole Ngok",
             "incident_title": "Latrines", "cost_amount": 20000,
             "created_at": day(40)},
        ],
    }


class MissionTimelineExecuteTest(unittest.TestCase):
    def test_execute_offline_returns_sorted_timeline_and_totals(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["interventoils_mission"]({}, _ctx())
        self.assertIn("insight", res)
        self.assertNotIn("error", res)
        # Fenêtre défaut 30 j : les 2 logs récents, triés chronologiquement.
        self.assertEqual(len(res["items"]), 2)
        dates = [i["date"] for i in res["items"]]
        self.assertEqual(dates, sorted(dates))
        for item in res["items"]:
            for key in ("date", "school", "action", "cost"):
                self.assertIn(key, item)
        self.assertEqual(res["totals"]["missions"], 2)
        self.assertEqual(res["totals"]["schools_visited"], 2)
        self.assertEqual(res["totals"]["total_cost"], 80000)

    def test_execute_filters_days_school_district(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        run = TOOL_EXECUTORS["interventoils_mission"]
        res = run({"days": 60}, _ctx())
        self.assertEqual(res["totals"]["missions"], 3)
        res = run({"days": 60, "school": "Ngok"}, _ctx())
        self.assertEqual(res["totals"]["missions"], 2)
        self.assertTrue(all("Ngok" in i["school"] for i in res["items"]))
        res = run({"district": "Wouri"}, _ctx())
        self.assertEqual(res["items"], [])
        self.assertIn("Aucune mission", res["insight"])


class MissionTimelineRouteCardTest(unittest.TestCase):
    def test_route_timeline_question_to_list(self) -> None:
        from app.agent_loop import READ_TOOLS, route_intent, tools_for_intent
        # Aucun indice legacy dans cette question : seul le plugin route list.
        self.assertEqual(route_intent("Où sont-ils allés ?"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("interventoils_mission", names)
        self.assertIn("interventoils_mission", READ_TOOLS)

    def test_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["interventoils_mission"]({}, _ctx())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("interventoils_mission", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "mission_timeline")
        self.assertIsNotNone(cards[0])

    def test_legacy_routing_intact_no_collision(self) -> None:
        from app.agent_loop import route_intent
        # Spot-check anti-collision : ces phrasés legacy ne doivent pas bouger.
        for question, expected in (
            ("mets a jour le journal", "create"),
            ("Journalise des travaux pour 50000 XAF", "create"),
            ("Enregistre une intervention de réparation de pompe", "create"),
            ("Résumer mon district", "other"),
            ("Quelles écoles ont le plus besoin d'aide ?", "other"),
            ("Explique l'incident WASH-001 en langage simple", "other"),
        ):
            with self.subTest(question=question):
                self.assertEqual(route_intent(question), expected)


if __name__ == "__main__":
    unittest.main()
