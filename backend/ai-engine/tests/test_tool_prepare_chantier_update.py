"""Plugin prepare_chantier_update : dossier de suivi chantier (sans écriture)."""
from __future__ import annotations

import unittest

# Phrasés legacy figés (routage create/other) : aucun hint du plugin ne doit
# en être une sous-chaîne (le routeur fait gagner has_list).
LEGACY_CREATE = [
    "Crée une intervention pour fuite à l'école de Mendong",
    "Journalise une intervention à 50000 XAF pour WASH-001",
    "Enregistre une intervention de réparation de pompe",
    "Signale une panne de forage à Ngok",
    "Ajoute une nouvelle intervention pour latrines bouchées",
    "Crée une intervention pour l'école de Ngok",
    "Journalise des travaux pour 50000 XAF",
    "Signale une panne de pompe à Nkol",
    "Prépare un dossier pour une nouvelle fuite",
    "enregistre une intervention",
    "Enregistre une réparation de pompe à Ngok",
    "note les travaux",
    "note une réparation à 20000 XAF",
    "ajoute une réparation",
    "mets a jour le journal",
    "note une panne",
    "journalise les travaux",
    "mets à jour le journal",
]

LEGACY_OTHER = [
    "Bonjour Sentinel",
    "Résume mon district",
    "Résumer mon district",
    "Quelles écoles ont le plus besoin d'aide ?",
    "Explique l'incident WASH-001 en langage simple",
]


def _ctx() -> dict:
    return {
        "incidents": [
            {"id": 1, "school_id": 10, "school_name": "EP Bonanjo",
             "district": "Wouri", "reference_code": "WASH-2026-0001",
             "title": "Fuite tuyau principal", "urgency": "critical",
             "status": "open", "affected_students": 450},
            {"id": 2, "school_id": 11, "school_name": "EP Deido",
             "district": "Wouri", "reference_code": "WASH-2026-0002",
             "title": "Latrines bouchées", "urgency": "high",
             "status": "open", "affected_students": 300},
        ],
    }


class PrepareChantierUpdatePluginTest(unittest.TestCase):
    def test_discovered_write_and_merged(self) -> None:
        from app.agent_loop import READ_TOOLS
        from app.agent_tools import AGENT_TOOLS, PLUGIN_HINTS, TOOL_EXECUTORS
        names = [t.get("function", {}).get("name") for t in AGENT_TOOLS]
        self.assertIn("prepare_chantier_update", names)
        self.assertIn("prepare_chantier_update", TOOL_EXECUTORS)
        self.assertIn("prepare_chantier_update", PLUGIN_HINTS)
        # Outil d'écriture : hors garde-fou lecture, masqué en consultation.
        self.assertNotIn("prepare_chantier_update", READ_TOOLS)
        tool_def = next(t["function"] for t in AGENT_TOOLS
                        if t["function"]["name"] == "prepare_chantier_update")
        self.assertIn("JAMAIS", tool_def["description"])
        self.assertIn("lister", tool_def["description"])
        props = tool_def["parameters"]["properties"]
        for key in ("incident", "progress_percent", "step", "cost_amount", "notes"):
            self.assertIn(key, props)

    def test_partial_dossier_missing_and_questions(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["prepare_chantier_update"](
            {"progress_percent": 50}, _ctx())
        self.assertNotIn("error", res)
        self.assertFalse(res["ready"])
        self.assertEqual(res["missing"], ["incident", "step"])
        self.assertEqual(len(res["questions"]), 2)
        self.assertTrue(all(q.strip().endswith("?") for q in res["questions"]))
        self.assertEqual(res["fields"]["progress_percent"], 50)
        self.assertIn("insight", res)
        self.assertTrue(res["insight"].strip())

    def test_complete_dossier_ready(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["prepare_chantier_update"]({
            "incident": "WASH-2026-0001",
            "progress_percent": 80,
            "step": "Finitions",
            "cost_amount": 150000,
            "notes": "Photos envoyées par le chef de chantier",
        }, _ctx())
        self.assertNotIn("error", res)
        self.assertTrue(res["ready"])
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["questions"], [])
        self.assertEqual(res["fields"]["incident_id"], 1)
        self.assertIn("Fuite tuyau principal", res["fields"]["incident_label"])
        self.assertEqual(res["fields"]["progress_percent"], 80)
        self.assertEqual(res["fields"]["step"], "Finitions")

    def test_incident_fuzzy_resolve_and_ambiguous_choices(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        # Titre approximatif -> résolu.
        res = TOOL_EXECUTORS["prepare_chantier_update"]({
            "incident": "fuite tuyau", "progress_percent": 10,
            "step": "Diagnostic"}, _ctx())
        self.assertEqual(res["fields"]["incident_id"], 1)
        self.assertTrue(res["ready"])
        # Référence inconnue -> incident manquant + choix proposés, sans crash.
        res2 = TOOL_EXECUTORS["prepare_chantier_update"]({
            "incident": "ZZZ-999", "progress_percent": 10,
            "step": "Diagnostic"}, _ctx())
        self.assertFalse(res2["ready"])
        self.assertIn("incident", res2["missing"])
        self.assertIn("incident_choices", res2)
        # Pourcentage hors borne -> traité comme manquant.
        res3 = TOOL_EXECUTORS["prepare_chantier_update"]({
            "incident": 2, "progress_percent": 150, "step": "Gros œuvre"}, _ctx())
        self.assertFalse(res3["ready"])
        self.assertIn("progress_percent", res3["missing"])

    def test_route_create_or_other_exposes_prepare(self) -> None:
        from app.agent_loop import route_intent, tools_for_intent
        intent = route_intent("Crée un point de suivi pour WASH-2026-0001")
        self.assertEqual(intent, "create")
        intent2 = route_intent("Point de suivi WASH-2026-0001")
        self.assertEqual(intent2, "other")
        for intent in ("create", "other"):
            names = [t.get("function", {}).get("name")
                     for t in tools_for_intent(intent)]
            self.assertIn("prepare_chantier_update", names)
        masked = [t.get("function", {}).get("name")
                  for t in tools_for_intent("list")]
        self.assertNotIn("prepare_chantier_update", masked)
        # Non-régression legacy : spot-check create/other inchangés.
        for question in ("enregistre une intervention", "note les travaux",
                         "Journalise des travaux pour 50000 XAF"):
            self.assertEqual(route_intent(question), "create")
        for question in ("Résumer mon district", "Bonjour Sentinel"):
            self.assertEqual(route_intent(question), "other")

    def test_hints_never_match_legacy_phrases(self) -> None:
        from app.agent_tools import PLUGIN_HINTS
        legacy = [q.lower() for q in LEGACY_CREATE + LEGACY_OTHER]
        for hint in PLUGIN_HINTS.get("prepare_chantier_update", frozenset()):
            for phrase in legacy:
                self.assertNotIn(hint, phrase,
                                 f"hint {hint!r} dans {phrase!r}")

    def test_card_built_and_defensive(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["prepare_chantier_update"]({
            "incident": 1, "progress_percent": 80,
            "step": "Finitions"}, _ctx())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("prepare_chantier_update", obs)])
        self.assertEqual(len(cards), 1)
        self.assertIsNotNone(cards[0])
        self.assertEqual(cards[0].type, "chantier_dossier")
        # Défensif : vide -> aucune carte, erreur -> carte de guidage.
        self.assertEqual(
            AgentLoop._build_cards(loop, [("prepare_chantier_update", {})]), [])
        err_cards = AgentLoop._build_cards(
            loop, [("prepare_chantier_update", {"error": "x"})])
        self.assertEqual(len(err_cards), 1)
        self.assertEqual(err_cards[0].type, "guidance")


if __name__ == "__main__":
    unittest.main()
