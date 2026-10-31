"""Plugin compare_schools : comparaison côte à côte + verdict (100 % offline)."""
from __future__ import annotations

import unittest


def _ctx() -> dict:
    return {
        "schools": [
            {"school_id": 1, "school_name": "École de Ngök"},
            {"school_id": 2, "school_name": "École de Mendong"},
            {"school_id": 3, "school_name": "École de Bonanjo"},
        ],
        "incidents": [
            {"id": 11, "school_id": 1, "school_name": "École de Ngök",
             "title": "Forage à sec", "urgency": "critical", "status": "open",
             "affected_students": 300},
            {"id": 12, "school_id": 1, "school_name": "École de Ngök",
             "title": "Fuite tuyau", "urgency": "medium", "status": "open",
             "affected_students": 150},
            {"id": 13, "school_id": 1, "school_name": "École de Ngök",
             "title": "Vieux robinet", "urgency": "low", "status": "resolved",
             "affected_students": 999},
            {"id": 21, "school_id": 2, "school_name": "École de Mendong",
             "title": "Pompe grippée", "urgency": "medium", "status": "open",
             "affected_students": 60},
        ],
        "maintenance_logs": [
            {"id": 101, "school_id": 1, "school_name": "École de Ngök",
             "cost_amount": 80000, "days_without_service": 5},
            {"id": 102, "school_id": 2, "school_name": "École de Mendong",
             "cost_amount": 10000, "days_without_service": 1},
            {"id": 103, "school_id": 2, "school_name": "École de Mendong",
             "cost_amount": 5000, "days_without_service": 0},
        ],
    }


# Snapshot des phrasés legacy qui NE doivent PAS router vers "list"
# (test_agent_loop.RouteIntentTest + tests/test_prompt_eval.py ROUTING_CASES).
LEGACY_CREATE = [
    "Crée une intervention pour l'école de Ngok",
    "Journalise des travaux pour 50000 XAF",
    "Signale une panne de pompe à Nkol",
    "Prépare un dossier pour une nouvelle fuite",
    "Crée une intervention pour fuite à l'école de Mendong",
    "Journalise une intervention à 50000 XAF pour WASH-001",
    "Enregistre une intervention de réparation de pompe",
    "Signale une panne de forage à Ngok",
    "Ajoute une nouvelle intervention pour latrines bouchées",
    "enregistre une intervention",
    "Enregistre une réparation de pompe à Ngok",
    "note les travaux",
    "note une réparation à 20000 XAF",
    "ajoute une réparation",
    "mets a jour le journal",
]
LEGACY_OTHER = [
    "Bonjour Sentinel",
    "Résume mon district",
    "Résumer mon district",
    "Quelles écoles ont le plus besoin d'aide ?",
    "Explique l'incident WASH-001 en langage simple",
]


class CompareSchoolsTest(unittest.TestCase):
    def test_execute_offline_via_registry(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["compare_schools"](
            {"schools": ["Ngok", "Mendong"]}, _ctx())
        self.assertNotIn("error", res)
        self.assertIn("insight", res)
        self.assertIn("verdict", res)
        self.assertEqual(len(res["columns"]), 2)
        ngok, mendong = res["columns"]
        self.assertEqual(ngok["school_name"], "École de Ngök")
        self.assertEqual(ngok["open_incidents"], 2)  # le résolu est exclu
        self.assertEqual(ngok["affected_students"], 450)
        self.assertEqual(ngok["interventions"], 1)
        self.assertEqual(ngok["total_cost_XAF"], 80000)
        self.assertEqual(ngok["days_without_service"], 5)
        self.assertEqual(mendong["open_incidents"], 1)
        self.assertIn("Ngök", res["verdict"])  # la plus en besoin gagne
        self.assertIn("critique", res["verdict"])
        self.assertEqual(res["unresolved"], [])

    def test_fuzzy_resolution_accents_case(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["compare_schools"](
            {"schools": ["ngok", "MENDONG"]}, _ctx())
        self.assertNotIn("error", res)
        names = [c["school_name"] for c in res["columns"]]
        self.assertEqual(names, ["École de Ngök", "École de Mendong"])

    def test_unknown_school_goes_to_unresolved(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["compare_schools"](
            {"schools": ["Ngok", "Mendong", "Atlantide"]}, _ctx())
        self.assertNotIn("error", res)
        self.assertEqual(len(res["columns"]), 2)
        self.assertEqual(res["unresolved"], ["Atlantide"])
        # Moins de 2 écoles reconnues -> erreur explicite, pas de crash.
        res2 = TOOL_EXECUTORS["compare_schools"](
            {"schools": ["Ngok", "Atlantide"]}, _ctx())
        self.assertIn("error", res2)
        self.assertEqual(res2["unresolved"], ["Atlantide"])
        res3 = TOOL_EXECUTORS["compare_schools"]({"schools": ["Ngok"]}, _ctx())
        self.assertIn("error", res3)

    def test_route_to_list_and_card_built(self) -> None:
        from app.agent_loop import READ_TOOLS, AgentLoop, route_intent, tools_for_intent
        from app.agent_tools import TOOL_EXECUTORS
        self.assertEqual(
            route_intent("Compare l'école de Ngok et celle de Mendong"), "list")
        names = [t.get("function", {}).get("name")
                 for t in tools_for_intent("list")]
        self.assertIn("compare_schools", names)
        self.assertIn("compare_schools", READ_TOOLS)
        obs = TOOL_EXECUTORS["compare_schools"](
            {"schools": ["Ngok", "Mendong"]}, _ctx())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("compare_schools", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "compare_schools")
        # Carte défensive : observation vide -> None, pas de crash.
        cards_empty = AgentLoop._build_cards(loop, [("compare_schools", {})])
        self.assertEqual(cards_empty, [])

    def test_legacy_routing_untouched(self) -> None:
        from app.agent_loop import route_intent
        from app.agent_tools import PLUGIN_HINTS
        for question in LEGACY_CREATE:
            with self.subTest(question=question):
                self.assertEqual(route_intent(question), "create")
        for question in LEGACY_OTHER:
            with self.subTest(question=question):
                self.assertEqual(route_intent(question), "other")
        # Garde-fou direct : aucun hint n'est sous-chaîne d'un phrasé legacy.
        legacy = [q.lower() for q in LEGACY_CREATE + LEGACY_OTHER]
        for hint in PLUGIN_HINTS.get("compare_schools", frozenset()):
            for question in legacy:
                self.assertNotIn(hint, question, f"hint {hint!r} dans {question!r}")


if __name__ == "__main__":
    unittest.main()
