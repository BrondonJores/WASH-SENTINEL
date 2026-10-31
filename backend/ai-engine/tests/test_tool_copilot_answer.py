"""Plugin copilot_answer : conseil stratégique générique, offline et déterministe."""
from __future__ import annotations

import unittest


def _fixture_context() -> dict:
    return {
        "schools": [
            {
                "school_id": 1,
                "school_name": "École de Ngok",
                "district": "Douala",
                "equipment_type": "pompe_manuelle",
                "installation_year": 2015,
                "estimated_replacement_cost": 1500000.0,
                "incident_count": 5,
                "total_repair_cost": 1120000.0,
                "total_days_without_service": 42,
            },
            {
                "school_id": 2,
                "school_name": "Lycée de Mendong",
                "district": "Douala",
                "equipment_type": "forage_vergnet",
                "installation_year": 2023,
                "estimated_replacement_cost": 1800000.0,
                "incident_count": 1,
                "total_repair_cost": 180000.0,
                "total_days_without_service": 4,
            },
        ],
        "incidents": [
            {"id": 11, "school_id": 1, "status": "open", "urgency": "high"},
            {"id": 12, "school_id": 1, "status": "open", "urgency": "critical"},
            {"id": 13, "school_id": 2, "status": "resolved", "urgency": "low"},
        ],
        "maintenance_logs": [],
    }


class CopilotAnswerPluginTest(unittest.TestCase):
    def test_discovered_and_read_only(self) -> None:
        from app.agent_tools import AGENT_TOOLS, PLUGIN_HINTS, TOOL_EXECUTORS
        names = [t.get("function", {}).get("name") for t in AGENT_TOOLS]
        self.assertIn("copilot_answer", names)
        self.assertIn("copilot_answer", TOOL_EXECUTORS)
        self.assertIn("copilot_answer", PLUGIN_HINTS)
        from app.agent_loop import READ_TOOLS
        self.assertIn("copilot_answer", READ_TOOLS)

    def test_execute_offline_budget_with_fixture(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Quel budget prévoir pour l'école de Ngok ?"},
            _fixture_context(),
        )
        self.assertIn("insight", res)
        self.assertIn("recommendation", res)
        self.assertEqual(res["topic"], "budget")
        self.assertEqual(res["school_name"], "École de Ngok")
        # Chiffres repris de la fixture (1 120 000 XAF, 5 pannes).
        self.assertIn("1 120 000", res["insight"])
        self.assertIn("5 pannes", res["insight"])
        self.assertEqual(res["recommendation"], "REPLACE")

    def test_execute_recurrence_rule_replace(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Que faire face aux pannes à répétition à Ngok ?"},
            _fixture_context(),
        )
        self.assertEqual(res["topic"], "recurrence")
        self.assertEqual(res["recommendation"], "REPLACE")
        self.assertIn("seuil de 4", res["insight"])

    def test_execute_deterministic_and_offline(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        args = {"question": "Quel est ton avis sur Mendong ?"}
        first = TOOL_EXECUTORS["copilot_answer"](args, _fixture_context())
        second = TOOL_EXECUTORS["copilot_answer"](args, _fixture_context())
        self.assertEqual(first, second)
        self.assertEqual(first["school_name"], "Lycée de Mendong")

    def test_execute_missing_question_returns_error(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["copilot_answer"]({}, _fixture_context())
        self.assertIn("error", res)

    def test_router_routes_advice_to_list(self) -> None:
        from app.agent_loop import route_intent, tools_for_intent
        self.assertEqual(
            route_intent("Quel est ton conseil pour le budget des écoles ?"), "list")
        self.assertEqual(
            route_intent("Que dois-je faire en priorité à Douala ?"), "list")
        names = [t.get("function", {}).get("name")
                 for t in tools_for_intent("list")]
        self.assertIn("copilot_answer", names)
        self.assertNotIn("prepare_incident", names)

    def test_hints_exemptes_de_phrases_bannies(self) -> None:
        from app.tools.copilot_answer import INTENT_HINTS
        banned = ("faut-il", "réparer ou remplacer", "réparer", "remplacer",
                  "faut il", "reparer")
        for hint in INTENT_HINTS:
            self.assertEqual(hint, hint.lower(), f"hint non minuscule : {hint}")
            for phrase in banned:
                self.assertNotIn(phrase, hint, f"phrasé banni dans : {hint}")

    def test_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Quelle stratégie pour Ngok ?"}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("copilot_answer", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "copilot_answer")
        self.assertIsNotNone(cards[0])

    def test_card_none_on_error(self) -> None:
        from app.agent_loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("copilot_answer", {"error": "oups"})])
        self.assertEqual(cards, [])


if __name__ == "__main__":
    unittest.main()
