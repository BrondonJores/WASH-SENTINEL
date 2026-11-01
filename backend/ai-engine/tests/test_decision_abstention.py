"""Copilot honnête : abstention 200 sans données, démo sur opt-in explicite.

LLM moqué, aucun réseau. Sans schools_data, aucune école fictive
(Saint-Michel...) ne doit apparaître dans la réponse.
"""
from __future__ import annotations

import unittest

from app.decision_agent import DecisionAgent
from app.schemas import DecisionCopilotRequest, SchoolMaintenanceHistory


class StubLLM:
    model = "stub-copilot"

    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_json(self, prompt: str, system: str = "") -> dict:
        return dict(self.payload)


def _history() -> SchoolMaintenanceHistory:
    return SchoolMaintenanceHistory(
        school_id=9,
        school_name="École Réelle de Test",
        district="District Test",
        equipment_type="Pompe manuelle",
        installation_year=2020,
        estimated_replacement_cost=1000000.0,
        incident_count=1,
        total_repair_cost=50000.0,
        total_days_without_service=2,
    )


class CopilotAbstentionTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_abstains_without_demo_schools(self) -> None:
        agent = DecisionAgent(llm=StubLLM({}))  # type: ignore[arg-type]
        res = await agent.answer_decision_query(
            DecisionCopilotRequest(user_query="Que remplacer ?", district="District Test")
        )
        self.assertIn("données insuffisantes", res.answer.lower())
        self.assertIn("District Test", res.answer)
        self.assertEqual(res.tools_executed, [])
        self.assertEqual(res.replace_recommendations, [])
        self.assertNotIn("Saint-Michel", res.answer)
        self.assertNotIn("Bonabéri", res.answer)
        self.assertEqual(res.data_source, "empty")
        self.assertTrue(res.warnings)
        self.assertTrue(res.next_action)
        self.assertTrue(
            any("historique" in a.lower() or "laravel" in a.lower() for a in res.strategic_action_plan)
        )

    async def test_allow_demo_opt_in_keeps_fixtures(self) -> None:
        payload = {
            "answer": "Rapport de démonstration avec des chiffres illustratifs pour le jury.",
            "action_plan": ["Valider la démo"],
        }
        agent = DecisionAgent(llm=StubLLM(payload))  # type: ignore[arg-type]
        res = await agent.answer_decision_query(
            DecisionCopilotRequest(user_query="Démo ?", district="District Test"),
            allow_demo=True,
        )
        self.assertEqual(len(res.replace_recommendations), 3)
        names = [a.school_name for a in res.replace_recommendations]
        self.assertTrue(any("Saint-Michel" in n for n in names))
        self.assertEqual(res.data_source, "real")

    async def test_real_data_uses_real_schools(self) -> None:
        payload = {
            "answer": "Analyse complète du district avec des recommandations chiffrées détaillées.",
            "action_plan": ["Maintenir l'équipement actuel"],
        }
        agent = DecisionAgent(llm=StubLLM(payload))  # type: ignore[arg-type]
        res = await agent.answer_decision_query(
            DecisionCopilotRequest(
                user_query="Que remplacer ?",
                district="District Test",
                schools_data=[_history()],
            )
        )
        self.assertEqual(len(res.replace_recommendations), 1)
        self.assertEqual(res.replace_recommendations[0].school_name, "École Réelle de Test")
        self.assertEqual(res.data_source, "real")
        self.assertEqual(res.warnings, [])


class CopilotDegradedLabelTest(unittest.IsolatedAsyncioTestCase):
    async def test_mute_llm_labeled_degraded(self) -> None:
        agent = DecisionAgent(llm=StubLLM({}))  # type: ignore[arg-type]
        res = await agent.answer_decision_query(
            DecisionCopilotRequest(
                user_query="Que remplacer ?",
                district="District Test",
                schools_data=[_history()],
            )
        )
        self.assertIn("secours sans LLM", res.answer)
        self.assertTrue(res.warnings)
        self.assertIn("secours sans LLM", res.warnings[0])
        self.assertTrue(res.next_action)
        self.assertEqual(res.data_source, "real")


if __name__ == "__main__":
    unittest.main()
