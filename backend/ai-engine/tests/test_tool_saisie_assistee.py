"""Plugin saisie_assistee : guide pas à pas, machine à états déterministe."""
from __future__ import annotations

import unittest


def _fixture_context() -> dict:
    return {
        "schools": [
            {"school_id": 1, "school_name": "École Publique de Bonanjo"},
            {"school_id": 2, "school_name": "École de Nkol"},
            {"school_id": 3, "school_name": "École Rurale de Ngok"},
        ],
    }


class SaisieAssisteePluginTest(unittest.TestCase):
    def test_discovered_readonly_and_merged(self) -> None:
        from app.agent_loop import READ_TOOLS
        from app.agent_tools import AGENT_TOOLS, PLUGIN_HINTS, TOOL_EXECUTORS
        names = [t.get("function", {}).get("name") for t in AGENT_TOOLS]
        self.assertIn("saisie_assistee", names)
        self.assertIn("saisie_assistee", TOOL_EXECUTORS)
        self.assertIn("saisie_assistee", PLUGIN_HINTS)
        self.assertIn("saisie_assistee", READ_TOOLS)

    def test_first_step_without_args(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["saisie_assistee"]({}, _fixture_context())
        self.assertNotIn("error", res)
        self.assertIn("insight", res)
        self.assertEqual(res["step"], "ecole")
        self.assertTrue(res["question"])
        self.assertIsInstance(res["options"], list)
        self.assertGreater(len(res["options"]), 0)
        self.assertEqual(res["progress_percent"], 0)
        self.assertEqual(res["recap"], {})

    def test_valid_answer_advances_step(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ex = TOOL_EXECUTORS["saisie_assistee"]
        ctx = _fixture_context()
        # École floue (sans accent, partiel) -> étape problème.
        res = ex({"etape": "ecole", "reponse": "nkol"}, ctx)
        self.assertEqual(res["step"], "probleme")
        self.assertEqual(res["recap"].get("ecole"), "École de Nkol")
        self.assertEqual(res["progress_percent"], 33)
        # Problème par indice -> étape urgence, recap cumulé.
        res2 = ex({"etape": "probleme", "reponse": "1", "recap": res["recap"]}, ctx)
        self.assertEqual(res2["step"], "urgence")
        self.assertEqual(res2["recap"].get("probleme"), "Fuite d'eau")
        self.assertEqual(res2["recap"].get("ecole"), "École de Nkol")
        # Urgence valide -> récapitulatif terminal.
        res3 = ex({"etape": "urgence", "reponse": "haute", "recap": res2["recap"]}, ctx)
        self.assertEqual(res3["step"], "recap")
        self.assertEqual(res3["progress_percent"], 100)
        self.assertEqual(res3["recap"].get("urgence"), "Haute")
        self.assertIn("Nkol", res3["question"])
        self.assertIn("Fuite", res3["question"])

    def test_invalid_answer_reasks_same_step(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ex = TOOL_EXECUTORS["saisie_assistee"]
        ctx = _fixture_context()
        res = ex({"etape": "ecole", "reponse": "XYZ introuvable"}, ctx)
        self.assertEqual(res["step"], "ecole")
        self.assertGreater(len(res["options"]), 0)
        self.assertNotIn("ecole", res["recap"])
        res = ex({"etape": "urgence", "reponse": "demain peut-être"}, ctx)
        self.assertEqual(res["step"], "urgence")
        self.assertEqual(res["options"], ["Basse", "Moyenne", "Haute", "Critique"])

    def test_route_guided_phrasing_to_list(self) -> None:
        from app.agent_loop import route_intent, tools_for_intent
        self.assertEqual(route_intent("Aide-moi à remplir un signalement"), "list")
        self.assertEqual(route_intent("Guide-moi pas à pas pour signaler"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("saisie_assistee", names)
        self.assertNotIn("prepare_incident", names)

    def test_search_beyond_six_schools(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ex = TOOL_EXECUTORS["saisie_assistee"]
        ctx = {"schools": [
            {"school_id": i, "school_name": f"École {i:02d} de Nkol"}
            for i in range(1, 9)
        ]}
        first = ex({}, ctx)
        self.assertEqual(first["step"], "ecole")
        self.assertEqual(first["total_ecoles"], 8)
        self.assertEqual(len(first["options"]), 6)
        self.assertIn("chercher", first["question"])
        narrowed = ex({"etape": "ecole", "recherche": "03"}, ctx)
        self.assertEqual(narrowed["total_ecoles"], 8)
        self.assertEqual(narrowed["recherche"], "03")
        self.assertEqual(narrowed["options"], ["École 03 de Nkol"])
        # Réponse tapée au-delà des 6 visibles : correspondance globale.
        matched = ex({"etape": "ecole", "reponse": "École 08"}, ctx)
        self.assertEqual(matched["step"], "probleme")
        self.assertEqual(matched["recap"]["ecole"], "École 08 de Nkol")

    def test_recap_validates_school_server_side(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ex = TOOL_EXECUTORS["saisie_assistee"]
        ctx = _fixture_context()
        valid = ex({"etape": "recap", "recap": {
            "ecole": "École de Nkol", "probleme": "Fuite d'eau",
            "urgence": "Haute"}}, ctx)
        self.assertEqual(valid["step"], "recap")
        self.assertEqual(valid["recap"]["ecole_id"], 2)
        self.assertTrue(valid["recap"]["ecole_valide"])
        self.assertEqual(valid["recap"]["urgence_level"], "high")
        self.assertEqual(valid["recap"]["probleme_code"], "leak")
        self.assertTrue(valid["ready"])
        self.assertIn("prepare_report", valid["confirmation"])
        # École inventée : rejet dur vers l'étape école.
        rejected = ex({"etape": "recap", "recap": {
            "ecole": "XYZ introuvable", "probleme": "Fuite d'eau",
            "urgence": "Haute"}}, ctx)
        self.assertEqual(rejected["step"], "ecole")
        self.assertIn("XYZ introuvable", rejected["question"])
        # Sans référentiel : nom brut accepté, jamais perdu.
        passthrough = ex({"etape": "recap", "recap": {
            "ecole": "École du village", "probleme": "Autre problème",
            "urgence": "Basse"}}, {"schools": []})
        self.assertEqual(passthrough["step"], "recap")
        self.assertEqual(passthrough["recap"]["ecole"], "École du village")
        self.assertIsNone(passthrough["recap"]["ecole_id"])
        self.assertEqual(passthrough["recap"]["urgence_level"], "low")
        self.assertEqual(passthrough["recap"]["probleme_code"], "other")

    def test_urgence_step_produces_validated_recap(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ex = TOOL_EXECUTORS["saisie_assistee"]
        ctx = _fixture_context()
        res = ex({"etape": "urgence", "reponse": "critique",
                  "recap": {"ecole": "École de Nkol",
                            "probleme": "Eau sale ou contaminée"}}, ctx)
        self.assertEqual(res["step"], "recap")
        self.assertEqual(res["recap"]["ecole_id"], 2)
        self.assertEqual(res["recap"]["urgence_level"], "critical")
        self.assertEqual(res["recap"]["probleme_code"], "contamination")
        self.assertTrue(res["ready"])
        # Saut direct à l'urgence sans école : retour à l'école.
        jumped = ex({"etape": "urgence", "reponse": "haute"}, ctx)
        self.assertEqual(jumped["step"], "ecole")

    def test_card_built_non_none(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["saisie_assistee"]({}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("saisie_assistee", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "saisie_assistee")
        # Erreur -> carte de guidage (jamais de vide).
        cards = AgentLoop._build_cards(loop, [("saisie_assistee", {"error": "x"})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "guidance")


if __name__ == "__main__":
    unittest.main()
