"""Cartes de guidage : une erreur d'outil ne donne jamais du vide."""
from __future__ import annotations

import unittest

from app.guidance import build_guidance_card


def _assert_valid_card(test: unittest.TestCase, card) -> dict:
    test.assertIsNotNone(card)
    test.assertEqual(card.type, "guidance")
    test.assertTrue(card.title and card.title.strip())
    test.assertIn("insight", card.data)
    test.assertIn("explication", card.data)
    test.assertIn("causes_possibles", card.data)
    test.assertIn("actions", card.data)
    test.assertTrue(card.data["insight"].strip())
    test.assertTrue(card.data["explication"].strip())
    causes = card.data["causes_possibles"]
    test.assertGreaterEqual(len(causes), 2)
    test.assertLessEqual(len(causes), 3)
    actions = card.data["actions"]
    test.assertGreaterEqual(len(actions), 2)
    for action in actions:
        test.assertTrue(action.get("label", "").strip())
        test.assertTrue(action.get("question", "").strip())
    return card.data


class NoneSansErreurTest(unittest.TestCase):
    def test_succes_sans_error_retourne_none(self):
        obs = {"insight": "3 alertes à Mvila.", "alerts": [], "total": 0}
        self.assertIsNone(build_guidance_card("district_alerts", obs))

    def test_error_vide_retourne_none(self):
        self.assertIsNone(build_guidance_card("observatoire", {"error": ""}))
        self.assertIsNone(build_guidance_card("observatoire", {"error": None}))
        self.assertIsNone(build_guidance_card("observatoire", {}))


class FamilleLieuInconnuTest(unittest.TestCase):
    def test_ecole_introuvable(self):
        obs = {"error": ("École 'Zorglub' introuvable. Écoles valides : "
                         "École de Ngok, École de Mendong.")}
        data = _assert_valid_card(self, build_guidance_card("analyze_school", obs))
        self.assertIn("Vérifiez", data["explication"])


class FamillePeriodeVideTest(unittest.TestCase):
    def test_aucune_alerte_sur_periode(self):
        obs = {"alerts": [], "total": 0,
               "error": "Aucune alerte actionnable à Mvila sur la période."}
        data = _assert_valid_card(
            self, build_guidance_card("district_alerts", obs))
        self.assertIn("période", data["explication"])

    def test_aucun_cluster(self):
        obs = {"error": "Aucun cluster sanitaire détecté à Wouri sur les 7 jours."}
        _assert_valid_card(self, build_guidance_card("epidemic_alerts", obs))


class FamilleDonneesAbsentesTest(unittest.TestCase):
    def test_aucune_donnee_incident(self):
        obs = {"total": 0, "error": ("Aucune donnée d'incident disponible "
                                     "pour l'observatoire.")}
        data = _assert_valid_card(self, build_guidance_card("observatoire", obs))
        self.assertIn("infos", data["explication"] + data["insight"])


class FamilleParametreManquantTest(unittest.TestCase):
    def test_question_manquante(self):
        obs = {"error": "Question manquante : précisez votre besoin."}
        data = _assert_valid_card(
            self, build_guidance_card("copilot_answer", obs))
        self.assertIn("nom", data["explication"])

    def test_precisez_deux_ecoles(self):
        obs = {"error": ("Précisez au moins 2 écoles à comparer : "
                         "{'schools': ['École A', 'École B']}.")}
        _assert_valid_card(self, build_guidance_card("compare_schools", obs))


class FamilleFileInconnueTest(unittest.TestCase):
    def test_file_hors_ligne_inconnue(self):
        obs = {"error": ("File hors-ligne inconnue : le contexte ne contient ni "
                         "file d'attente ni statut de synchro.")}
        data = _assert_valid_card(
            self, build_guidance_card("offline_queue", obs))
        blob = data["explication"] + " ".join(data["causes_possibles"])
        self.assertIn("message", blob)


class FamilleDefautTest(unittest.TestCase):
    def test_erreur_technique_generique_utile(self):
        obs = {"error": "ValueError: time data 'xyz' does not match format"}
        data = _assert_valid_card(self, build_guidance_card("observatoire", obs))
        # Defaut generique-utile : ce qui s'est passe + 2 actions.
        self.assertTrue(data["explication"].strip())
        self.assertGreaterEqual(len(data["actions"]), 2)

    def test_outil_inconnu_n_est_pas_un_lieu(self):
        obs = {"error": "Outil inconnu : zorglub_tool."}
        data = _assert_valid_card(self, build_guidance_card("zorglub_tool", obs))
        self.assertNotIn("Mvila", data["explication"])


class MappingParOutilTest(unittest.TestCase):
    def test_district_inexistant_avec_exemples(self):
        obs = {"error": "District 'Zorglub' introuvable. Choix : Mvila, Wouri."}
        data = _assert_valid_card(
            self, build_guidance_card("district_alerts", obs))
        self.assertIn("Mvila", data["explication"])
        labels = [a["label"] for a in data["actions"]]
        self.assertIn("Voir tous les districts", labels)

    def test_outil_ecole_propose_les_ecoles(self):
        obs = {"error": "École 'Zorglub' introuvable."}
        data = _assert_valid_card(
            self, build_guidance_card("compare_schools", obs))
        labels = [a["label"] for a in data["actions"]]
        self.assertIn("Voir les écoles suivies", labels)


class ActionsNonVidesTest(unittest.TestCase):
    def test_toutes_familles_actions_cliquables(self):
        cas = [
            ("analyze_school", {"error": "École 'X' introuvable."}),
            ("district_alerts", {"error": "Aucune alerte sur la période."}),
            ("observatoire", {"error": "Aucune donnée d'incident disponible."}),
            ("copilot_answer", {"error": "Question manquante."}),
            ("offline_queue", {"error": "File hors-ligne inconnue."}),
            ("relances_proactives", {"error": "KeyError: 'boom'"}),
        ]
        for tool, obs in cas:
            with self.subTest(tool=tool):
                card = build_guidance_card(tool, obs)
                data = _assert_valid_card(self, card)
                for action in data["actions"]:
                    self.assertIn("?", action["question"])


if __name__ == "__main__":
    unittest.main()
