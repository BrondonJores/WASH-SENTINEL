"""Tests du pont déterministe bbj->fr (AUCUN appel LLM).

Le lexique réel est entièrement UNVALIDATED : les tests de matching
utilisent un lexique de fixture SYNTHÉTIQUE (variantes « zz_* »,
évidemment fausses) pour ne jamais figer du faux ghomala'.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.bbj_bridge import (
    VALID_INFRASTRUCTURES,
    VALID_ISSUES,
    bridge_bbj_to_french,
    load_lexicon,
)

LEXICON_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "bbj_wash_lexicon.json"

#: Fixture SYNTHÉTIQUE — variantes inventées préfixées zz_ (pas du ghomala').
#: verified=True ici UNIQUEMENT pour exercer le matching en test ; le vrai
#: lexique reste entièrement verified=false tant qu'un locuteur natif n'a
#: pas validé (voir test_all_entries_unvalidated_by_default).
FIXTURE_LEXICON = [
    {"id": "water", "bbj": ["zz_wata"], "fr": "eau",
     "slot": "infrastructure", "maps_to": "water_point",
     "verified": True, "source": "fixture-test (zz_ synthétique)"},
    {"id": "broken", "bbj": ["zz_broken_a", "zz_broken_b"], "fr": "cassé",
     "slot": "issue", "maps_to": "total_breakdown",
     "verified": True, "source": "fixture-test (zz_ synthétique)"},
    {"id": "toilets", "bbj": ["zz_toilet"], "fr": "toilettes / latrines",
     "slot": "infrastructure", "maps_to": "toilets_latrines",
     "verified": True, "source": "fixture-test (zz_ synthétique)"},
    {"id": "urgent", "bbj": ["zz_urgent"], "fr": "urgent",
     "slot": "urgency", "maps_to": "high",
     "verified": True, "source": "fixture-test (zz_ synthétique)"},
]


class RealLexiconTest(unittest.TestCase):
    def test_loads_and_has_minimum_entries(self) -> None:
        entries = load_lexicon()
        self.assertGreaterEqual(len(entries), 30)

    def test_no_bbj_word_without_verified_source(self) -> None:
        """Garde-fou : aucun mot bbj sans validation + source citées.

        Règle : si bbj est non vide → verified=true ET source non vide.
        Entrées vides : source null autorisé + todo locuteur obligatoire.
        """
        for entry in load_lexicon():
            eid = entry.get("id")
            self.assertIn("source", entry, eid)
            if entry.get("bbj"):
                self.assertIs(entry.get("verified"), True, eid)
                self.assertTrue(entry.get("source"), eid)
            else:
                self.assertIn("todo", entry, eid)

    def test_all_entries_unvalidated_by_default(self) -> None:
        with open(LEXICON_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        for entry in data["entries"]:
            self.assertIs(entry.get("verified"), False, entry.get("id"))
            self.assertIn("locuteur natif", entry.get("note", ""))

    def test_all_entries_have_required_shape(self) -> None:
        for entry in load_lexicon():
            self.assertIn("bbj", entry)
            self.assertIsInstance(entry["bbj"], list)
            self.assertTrue(entry.get("fr"), entry.get("id"))
            self.assertIn(entry.get("slot"),
                          {"infrastructure", "issue", "urgency", "context"})
            if not entry["bbj"]:
                self.assertIn("todo", entry, entry.get("id"))

    def test_maps_to_values_are_extractor_compatible(self) -> None:
        for entry in load_lexicon():
            target = entry.get("maps_to")
            if target is None:
                continue
            valid = VALID_INFRASTRUCTURES | VALID_ISSUES | {"low", "medium", "high", "critical"}
            self.assertIn(target, valid, entry.get("id"))


class MatchingTest(unittest.TestCase):
    def test_unverified_entry_never_matches(self) -> None:
        lexicon = [
            {"id": "water", "bbj": ["zz_wata"], "fr": "eau",
             "slot": "infrastructure", "maps_to": "water_point",
             "verified": False, "source": None},
        ]
        out = bridge_bbj_to_french("report zz_wata problem", lexicon)
        self.assertEqual(out["matched_slots"], [])
        self.assertEqual(out["infrastructure_guess"], "unknown")

    def test_exact_match(self) -> None:
        out = bridge_bbj_to_french("report zz_wata problem", FIXTURE_LEXICON)
        self.assertEqual(len(out["matched_slots"]), 1)
        self.assertEqual(out["matched_slots"][0]["id"], "water")
        self.assertEqual(out["infrastructure_guess"], "water_point")

    def test_case_insensitive_match(self) -> None:
        out = bridge_bbj_to_french("Report ZZ_WATA Problem!", FIXTURE_LEXICON)
        self.assertEqual(len(out["matched_slots"]), 1)
        self.assertEqual(out["matched_slots"][0]["matched_variant"], "zz_wata")

    def test_punctuation_tolerant_match(self) -> None:
        out = bridge_bbj_to_french("...zz_broken-a???", FIXTURE_LEXICON)
        ids = [m["id"] for m in out["matched_slots"]]
        self.assertIn("broken", ids)
        self.assertEqual(out["issue_guess"], "total_breakdown")

    def test_second_variant_matches(self) -> None:
        out = bridge_bbj_to_french("zz_broken_b", FIXTURE_LEXICON)
        self.assertEqual(out["matched_slots"][0]["matched_variant"], "zz_broken_b")

    def test_multiple_slots_and_medium_confidence(self) -> None:
        out = bridge_bbj_to_french("zz_wata zz_broken_a zz_urgent", FIXTURE_LEXICON)
        self.assertEqual(len(out["matched_slots"]), 3)
        self.assertEqual(out["confidence"], "medium")
        self.assertEqual(out["urgency_guess"], "high")

    def test_single_match_is_low_confidence(self) -> None:
        out = bridge_bbj_to_french("zz_wata", FIXTURE_LEXICON)
        self.assertEqual(out["confidence"], "low")


class HumanCheckTest(unittest.TestCase):
    def test_no_match_needs_human_and_nonempty_pivot(self) -> None:
        out = bridge_bbj_to_french("xyzzy blabla unknown words", FIXTURE_LEXICON)
        self.assertTrue(out["needs_human_check"])
        self.assertTrue(out["french_pivot"])
        self.assertIn("ghomala", out["french_pivot"])
        self.assertEqual(out["matched_slots"], [])
        self.assertEqual(out["confidence"], "low")
        self.assertTrue(out["unmatched"])

    def test_human_check_always_true_even_with_matches(self) -> None:
        out = bridge_bbj_to_french("zz_wata zz_broken_a", FIXTURE_LEXICON)
        self.assertTrue(out["needs_human_check"])

    def test_empty_text_needs_human_and_nonempty_pivot(self) -> None:
        out = bridge_bbj_to_french("", FIXTURE_LEXICON)
        self.assertTrue(out["needs_human_check"])
        self.assertTrue(out["french_pivot"])

    def test_no_llm_ever_called(self) -> None:
        # Le pont est synchrone et sans dépendance provider : la signature
        # et l'absence d'import suffisent ; ce test fige le contrat.
        import inspect
        import app.bbj_bridge as bridge_mod
        self.assertFalse(inspect.iscoroutinefunction(bridge_mod.bridge_bbj_to_french))
        source = inspect.getsource(bridge_mod)
        self.assertNotIn("BaseLLMProvider", source)
        self.assertNotIn("generate_json", source)


class ExtractorCompatibilityTest(unittest.TestCase):
    def test_guesses_are_valid_or_unknown(self) -> None:
        for text in ["zz_wata zz_broken_a", "nothing matches here", ""]:
            out = bridge_bbj_to_french(text, FIXTURE_LEXICON)
            self.assertIn(out["infrastructure_guess"], VALID_INFRASTRUCTURES | {"unknown"})
            self.assertIn(out["issue_guess"], VALID_ISSUES | {"unknown"})

    def test_real_lexicon_yields_unknown_until_validated(self) -> None:
        out = bridge_bbj_to_french("texte ghomala' quelconque")
        self.assertEqual(out["infrastructure_guess"], "unknown")
        self.assertEqual(out["issue_guess"], "unknown")
        self.assertTrue(out["needs_human_check"])


if __name__ == "__main__":
    unittest.main()
