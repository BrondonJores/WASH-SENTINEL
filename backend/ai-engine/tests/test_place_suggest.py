"""Suggestions « vouliez-vous dire ? » (AXE 3 : unittest réel, fini la dérive).

Historique : ces tests étaient en style pytest pur (jamais exécutés par
unittest discover), ce qui a masqué la dérive SEUIL 0.75 vs assert 0.45
et l'absence de from_marker dans le contrat attendu. Convertis en TestCase.
"""
from __future__ import annotations

import unittest

from app.place_suggest import SEUIL, suggest_places
from app.textnorm import PLACE_CUTOFF

CONTEXT = {
    "schools": [
        {"school_name": "École Primaire de Nkol", "district": "Mvila"},
        {"school_name": "École Publique de Biyem", "district": "Mvila"},
        {"school_name": "Lycée de Sangmélima", "district": "Dja-et-Lobo"},
        {"school_name": "École de Kribi Centre", "district": "Océan"},
    ],
    "incidents": [{"district": "Mvila"}, {"district": "Vallée-du-Ntem"}],
}


def _folded(label: str) -> str:
    return label.lower().replace("é", "e")


class PlaceSuggestTest(unittest.TestCase):
    def test_typo_nkole_suggests_nkol(self) -> None:
        out = suggest_places("Il y a une panne à l'école de Nkole", CONTEXT)
        self.assertEqual(out["fragment"], "Nkole")
        self.assertTrue(out["suggestions"],
                        "faute de frappe Nkole -> suggestion attendue")
        top = out["suggestions"][0]
        self.assertEqual(top["kind"], "school")
        self.assertIn("nkol", _folded(top["label"]))

    def test_typo_mvilla_suggests_mvila_district(self) -> None:
        out = suggest_places("Résume le district de Mvilla", CONTEXT)
        self.assertEqual(out["fragment"], "Mvilla")
        labels = [(s["label"], s["kind"]) for s in out["suggestions"]]
        self.assertIn(("Mvila", "district"), labels)

    def test_fragment_case_accents_insensibles(self) -> None:
        out = suggest_places("PANNE SUR L'ECOLE DE nKoLe", CONTEXT)
        self.assertEqual(out["fragment"], "nKoLe")
        self.assertTrue(out["suggestions"])
        self.assertIn("nkol", _folded(out["suggestions"][0]["label"]))

    def test_inconnu_total_donne_echantillons(self) -> None:
        out = suggest_places("panne à Zzzzxqw", CONTEXT)
        self.assertEqual(out["fragment"], "Zzzzxqw")
        self.assertEqual(out["suggestions"], [])
        self.assertEqual(len(out["ecoles_sample"]), 3)
        self.assertEqual(set(out["districts_sample"]), {
            "Mvila", "Dja-et-Lobo", "Océan", "Vallée-du-Ntem"})
        self.assertTrue(out["insight"], "jamais un mur : insight obligatoire")

    def test_contexte_vide_aide_generique(self) -> None:
        for ctx in ({}, {"schools": [], "incidents": []}):
            out = suggest_places("panne à Nkole", ctx)
            self.assertEqual(out["suggestions"], [])
            self.assertEqual(out["ecoles_sample"], [])
            self.assertEqual(out["districts_sample"], [])
            self.assertIn("école", out["insight"])
            self.assertIn("district", out["insight"])

    def test_seuil_filtre_scores_faibles(self) -> None:
        self.assertEqual(SEUIL, 0.75)
        self.assertEqual(SEUIL, PLACE_CUTOFF)
        out = suggest_places("panne à Xyzztop", CONTEXT)
        self.assertEqual(out["fragment"], "Xyzztop")
        self.assertEqual(out["suggestions"], [])
        # ... mais une quasi-exactitude passe toujours le seuil.
        out2 = suggest_places("panne à Nkol", CONTEXT)
        self.assertTrue(any("nkol" in _folded(s["label"])
                            for s in out2["suggestions"]))

    def test_questions_cliquables_non_vides(self) -> None:
        out = suggest_places("problème d'eau pour Nkole", CONTEXT)
        self.assertTrue(out["suggestions"])
        for s in out["suggestions"]:
            self.assertTrue(s["label"])
            self.assertIn(s["kind"], ("school", "district"))
            self.assertTrue(s["question"])
            self.assertGreater(len(s["question"]), len(s["label"]))
            self.assertIn(s["label"], s["question"])
        ecole_q = next(s["question"] for s in out["suggestions"]
                       if s["kind"] == "school")
        self.assertTrue(ecole_q.startswith("Analyser"))

    def test_contrat_retour_et_limite(self) -> None:
        out = suggest_places("panne vers Mvila", CONTEXT, limit=1)
        self.assertEqual(set(out), {"insight", "fragment", "from_marker",
                                    "suggestions", "ecoles_sample",
                                    "districts_sample"})
        self.assertLessEqual(len(out["suggestions"]), 1)
        out3 = suggest_places("panne vers Mvila", CONTEXT, limit=3)
        self.assertLessEqual(len(out3["suggestions"]), 3)


class PlaceSuggestEnglishTest(unittest.TestCase):
    def test_school_at_marker(self) -> None:
        out = suggest_places("leak at the school Nkole", CONTEXT)
        self.assertEqual(out["fragment"], "Nkole")
        self.assertTrue(out["from_marker"])
        self.assertTrue(out["suggestions"])
        self.assertIn("nkol", _folded(out["suggestions"][0]["label"]))

    def test_water_for_marker(self) -> None:
        out = suggest_places("no water for Bonanjo",
                             {"schools": [{"school_name":
                                            "École Publique de Bonanjo",
                                            "district": "Wouri"}],
                              "incidents": []})
        self.assertEqual(out["fragment"], "Bonanjo")
        self.assertTrue(out["from_marker"])
        self.assertTrue(out["suggestions"])


if __name__ == "__main__":
    unittest.main()
