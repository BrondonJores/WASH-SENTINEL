"""Routeur calibré : goldens migrés + confusables + seuils + compatibilité."""
from __future__ import annotations

import unittest

from app.agent_tools import PLUGIN_HINTS
from app.router import is_data_question, route
from tests.test_agent_loop import RouteIntentTest
from tests.test_prompt_eval import ROUTING_CASES

MIN_MARGIN = 0.15


def _label(question: str) -> str:
    return route(question, PLUGIN_HINTS)["intent"]


class RouterGoldenTest(unittest.TestCase):
    """Les 18 cas de routage + la table RouteIntent : label, marge, raisons."""

    def test_routing_cases_labels(self) -> None:
        for case in ROUTING_CASES:
            with self.subTest(case["id"]):
                self.assertEqual(
                    _label(case["question"]), case["intent"],
                    f"[{case['id']}] intent",
                )

    def test_routing_cases_margin_and_reasons(self) -> None:
        for case in ROUTING_CASES:
            with self.subTest(case["id"]):
                res = route(case["question"], PLUGIN_HINTS)
                if case["intent"] == "other":
                    self.assertEqual(res["scores"], {"list": 0.0, "create": 0.0},
                                     f"[{case['id']}] aucun indice")
                    continue
                self.assertGreaterEqual(
                    res["margin"], MIN_MARGIN, f"[{case['id']}] marge")
                self.assertGreaterEqual(
                    res["confidence"], 0.5, f"[{case['id']}] confiance")
                self.assertTrue(res["reasons"], f"[{case['id']}] raisons")

    def test_route_intent_table_labels(self) -> None:
        for question, expected in RouteIntentTest.CASES:
            with self.subTest(question=question):
                self.assertEqual(_label(question), expected)


class RouterConfusableTest(unittest.TestCase):
    """Collisions de sous-chaînes tuées par l'appariement sur tokens."""

    def test_cour_not_list(self) -> None:
        self.assertEqual(_label("cour de l'ecole"), "other")

    def test_cour_large_not_data_question(self) -> None:
        # "ou " apparaissait dans "cour " avec l'ancien test brut.
        self.assertFalse(is_data_question("La cour est grande", PLUGIN_HINTS))

    def test_notebook_not_create(self) -> None:
        res = route("J'ai acheté un notebook", PLUGIN_HINTS)
        self.assertEqual(res["intent"], "other")
        self.assertEqual(res["scores"]["create"], 0.0)

    def test_update_not_list(self) -> None:
        # "date" apparaissait dans "update" avec l'ancien test brut.
        self.assertEqual(_label("update le tableau"), "other")

    def test_carte_documented_intent(self) -> None:
        # Cas connu : "voir" route vers la consultation (masque prepare_*).
        # Comportement historique conservé tel quel par cet axe.
        res = route("Voir la carte du territoire", PLUGIN_HINTS)
        self.assertEqual(res["intent"], "list")
        self.assertTrue(any(r == "list:voir" for r in res["reasons"]))

    def test_mixed_list_and_create_tiebreak(self) -> None:
        res = route("signale une panne et montre la liste", PLUGIN_HINTS)
        self.assertEqual(res["intent"], "list")
        self.assertTrue(any("tiebreak:list-wins-on-ambiguity" in r
                            for r in res["reasons"]),
                        f"tiebreak explicite, raisons={res['reasons']}")

    def test_past_marker_tiebreak_logged(self) -> None:
        res = route("Journalise les interventions réalisées hier", PLUGIN_HINTS)
        self.assertEqual(res["intent"], "list")
        self.assertTrue(any("hier" in r for r in res["reasons"]),
                        f"marqueur passé journalisé, raisons={res['reasons']}")


class RouterThresholdTest(unittest.TestCase):
    """Seuils : vide/inconnu -> other, confiance basse documentée."""

    def test_empty_is_other(self) -> None:
        for question in ("", "   "):
            res = route(question, PLUGIN_HINTS)
            self.assertEqual(res["intent"], "other")
            self.assertEqual(res["confidence"], 0.0)
            self.assertEqual(res["reasons"], [])

    def test_gibberish_is_other(self) -> None:
        res = route("xyz blabla wxyz", PLUGIN_HINTS)
        self.assertEqual(res["intent"], "other")
        self.assertEqual(res["scores"], {"list": 0.0, "create": 0.0})

    def test_greeting_is_other(self) -> None:
        self.assertEqual(_label("Bonjour Sentinel"), "other")
        self.assertFalse(is_data_question("Bonjour", PLUGIN_HINTS))

    def test_data_vocab_triggers_data_question(self) -> None:
        self.assertTrue(is_data_question(
            "Quelles écoles ont le plus besoin d'aide ?", PLUGIN_HINTS))
        self.assertTrue(is_data_question(
            "Combien d'écoles sont sans eau ?", PLUGIN_HINTS))


class RouterCompatTest(unittest.TestCase):
    """route_intent() reste un fin wrapper du routeur calibré."""

    def test_wrapper_matches_router(self) -> None:
        from app.agent_loop import route_intent
        questions = [c["question"] for c in ROUTING_CASES]
        questions += [q for q, _ in RouteIntentTest.CASES]
        questions += ["", "Bonjour", "cour de l'ecole", "notebook"]
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(route_intent(question), _label(question))


if __name__ == "__main__":
    unittest.main()
