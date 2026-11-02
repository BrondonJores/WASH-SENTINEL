"""Tests du pont déterministe bbj->fr (AUCUN appel LLM).

Le lexique réel est entièrement UNVALIDATED (verified=false partout) :
les tests de mécanique utilisent un lexique de fixture SYNTHÉTIQUE
(variantes « zz_* », évidemment fausses). Les formes ghomala' RÉELLES
testées ici sont toutes sourcées (candidats web cités du lexique) —
jamais inventées — et servent à verrouiller le matching, la couverture
et le repli "incertain".
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


class CandidatesPolicyTest(unittest.TestCase):
    def test_lexicon_has_sixty_plus_entries(self) -> None:
        self.assertGreaterEqual(len(load_lexicon()), 60)

    def test_candidates_require_source(self) -> None:
        """Candidats web non vides -> source citée obligatoire."""
        for entry in load_lexicon():
            cands = entry.get("candidates") or []
            self.assertIsInstance(cands, list, entry.get("id"))
            if cands:
                self.assertTrue(entry.get("source"), entry.get("id"))

    def test_every_candidate_matches_its_own_entry(self) -> None:
        """Non-régression : chaque candidat sourcé est matchable tel quel.

        Verrouille la règle de longueur minimale et le repli bbj : si un
        candidat cesse de matcher (seuil durci, régression du fold...),
        c'est ici que ça casse — pas en production silencieuse.
        """
        entries = load_lexicon()
        checked = 0
        for entry in entries:
            for cand in entry.get("candidates") or []:
                out = bridge_bbj_to_french(cand, entries)
                ids = [m["id"] for m in out["matched_slots"]]
                self.assertIn(entry["id"], ids, cand)
                checked += 1
        self.assertGreater(checked, 100)


class WebTierMatchingTest(unittest.TestCase):
    """Matching des formes sourcées (lexique réel, niveau `web`)."""

    def test_water_and_variants(self) -> None:
        for form in ("shya", "shyə", "SHYƏ", "Shyă"):
            out = bridge_bbj_to_french(form)
            ids = [m["id"] for m in out["matched_slots"]]
            self.assertIn("water", ids, form)
            self.assertEqual(out["infrastructure_guess"], "water_point", form)

    def test_bbj_fold_maps_special_letters(self) -> None:
        # ʉ->u, ŋ->n, ɔ->o, ə->e : la forme ASCII (transcription ASR
        # probable) matche les formes canoniques du lexique.
        out = bridge_bbj_to_french("ghum shye")
        self.assertIn("well", [m["id"] for m in out["matched_slots"]])
        out = bridge_bbj_to_french("sok lunga")
        ids = [m["id"] for m in out["matched_slots"]]
        self.assertIn("soap", ids)
        self.assertIn("bucket", ids)

    def test_well_locution(self) -> None:
        out = bridge_bbj_to_french("ghʉm shyə")
        self.assertIn("well", [m["id"] for m in out["matched_slots"]])
        self.assertEqual(out["infrastructure_guess"], "water_point")

    def test_school_variants(self) -> None:
        for form in ("dyôtâ", "sàkú", "sakú", "SAKÚ"):
            out = bridge_bbj_to_french(form)
            self.assertIn("school", [m["id"] for m in out["matched_slots"]], form)

    def test_thirst_locution_maps_to_dry_well(self) -> None:
        out = bridge_bbj_to_french("ji shya")
        self.assertIn("thirst", [m["id"] for m in out["matched_slots"]])
        self.assertEqual(out["issue_guess"], "dry_well")

    def test_sick_locution_but_never_bare_gho(self) -> None:
        out = bridge_bbj_to_french("wə go")
        self.assertIn("sick", [m["id"] for m in out["matched_slots"]])
        self.assertEqual(out["issue_guess"], "contamination")
        # "gho sakú" = aller à l'école : school OUI, sick NON (homophone).
        out = bridge_bbj_to_french("gho sakú")
        ids = [m["id"] for m in out["matched_slots"]]
        self.assertIn("school", ids)
        self.assertNotIn("sick", ids)

    def test_short_homophones_never_match(self) -> None:
        # mu (un/quelqu'un), pu (on), ca (ça), la (article FR) : exclus.
        for form, forbidden in (("mu", "children"), ("pu", "hand"),
                                ("ca", "broken"), ("la", "village")):
            out = bridge_bbj_to_french(form)
            self.assertNotIn(forbidden,
                             [m["id"] for m in out["matched_slots"]], form)

    def test_no_substring_match(self) -> None:
        # "sok" (savon) ne matche PAS dans "sokoto" (mot-entier strict).
        out = bridge_bbj_to_french("sokoto")
        ids = [m["id"] for m in out["matched_slots"]]
        self.assertNotIn("soap", ids)
        self.assertNotIn("handwash", ids)

    def test_web_tier_is_labeled(self) -> None:
        out = bridge_bbj_to_french("shya sakú")
        self.assertTrue(out["matched_slots"])
        for match in out["matched_slots"]:
            self.assertEqual(match["tier"], "web")
        self.assertIn("source web", out["french_pivot"])

    def test_validated_tier_is_labeled(self) -> None:
        out = bridge_bbj_to_french("report zz_wata problem", FIXTURE_LEXICON)
        self.assertEqual(out["matched_slots"][0]["tier"], "validated")

    def test_web_matches_cap_confidence_at_low(self) -> None:
        # 2 indices web (jamais validés) restent "low" : medium exige 2+
        # indices TOUS validés (cf. test_multiple_slots_and_medium_confidence).
        out = bridge_bbj_to_french("shya sakú")
        self.assertGreaterEqual(len(out["matched_slots"]), 2)
        self.assertEqual(out["confidence"], "low")

    def test_todo_entries_never_match(self) -> None:
        # Entrées sans bbj ni candidats (todo locuteur) : rien à matcher.
        lexicon = [
            {"id": "pump", "bbj": [], "fr": "pompe",
             "slot": "infrastructure", "maps_to": "water_point",
             "verified": False, "source": None,
             "todo": "locuteur requis"},
        ]
        out = bridge_bbj_to_french("pompe sôk", lexicon)
        self.assertEqual(out["matched_slots"], [])


class CoverageVerdictTest(unittest.TestCase):
    def test_full_coverage_yields_indices(self) -> None:
        out = bridge_bbj_to_french("shya sakú")
        self.assertAlmostEqual(out["coverage"], 1.0)
        self.assertEqual(out["verdict"], "indices")

    def test_partial_coverage_above_threshold(self) -> None:
        out = bridge_bbj_to_french("shya xyz")
        self.assertAlmostEqual(out["coverage"], 0.5)
        self.assertEqual(out["verdict"], "indices")
        self.assertEqual(out["infrastructure_guess"], "water_point")

    def test_low_coverage_forces_unknown_without_inventing(self) -> None:
        # 1 mot reconnu sur 10 : l'indice est listé MAIS aucune panne
        # n'est déduite (repli honnête).
        out = bridge_bbj_to_french(
            "sîm alpha bravo charlie delta echo foxtrot golf hotel india")
        self.assertLess(out["coverage"], 0.30)
        self.assertEqual(out["verdict"], "incertain")
        self.assertEqual(out["issue_guess"], "unknown")
        self.assertEqual(out["infrastructure_guess"], "unknown")
        self.assertEqual(out["confidence"], "low")
        self.assertTrue(out["matched_slots"])
        self.assertIn("incertain", out["french_pivot"])
        self.assertIn("aucune panne déduite", out["french_pivot"])

    def test_zero_coverage(self) -> None:
        out = bridge_bbj_to_french("xyzzy plugh")
        self.assertAlmostEqual(out["coverage"], 0.0)
        self.assertEqual(out["verdict"], "incertain")
        self.assertIn("aucun mot reconnu", out["french_pivot"])

    def test_empty_text_is_incertain(self) -> None:
        out = bridge_bbj_to_french("")
        self.assertAlmostEqual(out["coverage"], 0.0)
        self.assertEqual(out["verdict"], "incertain")
        self.assertTrue(out["french_pivot"])
        self.assertTrue(out["needs_human_check"])

    def test_result_exposes_coverage_and_verdict(self) -> None:
        out = bridge_bbj_to_french("shya", FIXTURE_LEXICON)
        self.assertIn("coverage", out)
        self.assertIn("verdict", out)
        self.assertIsInstance(out["coverage"], float)
        self.assertGreaterEqual(out["coverage"], 0.0)
        self.assertLessEqual(out["coverage"], 1.0)


class RealCaseTest(unittest.TestCase):
    def test_garbled_brother_voice_is_incertain(self) -> None:
        """Cas réel WASH-2026-RIVTOZ : vocal ghomala' du frère transcrit
        "da cas bolilam dmla" (Whisper FR forcé sur parole ghomala',
        fixture tests/fixtures/voice_bbj_brother_01.ogg). Le pont ne doit
        JAMAIS inventer une panne dessus : verdict "incertain", guesses
        "unknown", tokens intacts dans `unmatched` pour le locuteur.
        """
        out = bridge_bbj_to_french("da cas bolilam dmla")
        self.assertEqual(out["verdict"], "incertain")
        self.assertEqual(out["infrastructure_guess"], "unknown")
        self.assertEqual(out["issue_guess"], "unknown")
        self.assertEqual(out["urgency_guess"], "unknown")
        self.assertAlmostEqual(out["coverage"], 0.0)
        self.assertEqual(out["matched_slots"], [])
        self.assertEqual(out["unmatched"], ["da", "cas", "bolilam", "dmla"])
        self.assertTrue(out["needs_human_check"])
        self.assertIn("incertain", out["french_pivot"])


if __name__ == "__main__":
    unittest.main()
