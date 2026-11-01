"""Batterie textnorm (AXE 3) : fold, négation, districts, dates, dedup, lieux."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from app.textnorm import (
    contains_keyword,
    dedup_incidents,
    district_match,
    find_keyword_spans,
    fold,
    is_negated,
    negation_spans,
    parse_date,
    parse_dt,
    score_place,
    tokenize_folded,
)


class FoldTest(unittest.TestCase):
    def test_accents_case_spaces(self) -> None:
        self.assertEqual(fold("  Vallée-du-NTEM  "), "vallee-du-ntem")
        self.assertEqual(fold(None), "")
        self.assertEqual(fold(""), "")

    def test_tokenize(self) -> None:
        self.assertEqual(tokenize_folded("L'eau est Jaune!"),
                         ["l", "eau", "est", "jaune"])


class NegationTest(unittest.TestCase):
    def _muted(self, text: str, word: str) -> bool:
        t = fold(text)
        spans = negation_spans(t)
        hits = find_keyword_spans(t, word, "subword")
        self.assertTrue(hits, f"{word} introuvable dans {text!r}")
        return all(is_negated(s, e, spans) for s, e in hits)

    def test_french_negation_mutes_symptom(self) -> None:
        self.assertTrue(self._muted("pas de diarrhée signalée", "diarrh"))
        self.assertTrue(self._muted("sans choléra heureusement", "cholera"))
        self.assertTrue(self._muted("aucun vomissement", "vomiss"))

    def test_english_negation_mutes(self) -> None:
        self.assertTrue(self._muted("no vomiting in school", "vomit"))

    def test_clause_reset_keeps_positive(self) -> None:
        self.assertFalse(
            self._muted("pas de chloration, diarrhée partout", "diarrh"))
        self.assertFalse(
            self._muted("no closure but vomiting everywhere", "vomit"))

    def test_non_negatable_classes_stay_positive(self) -> None:
        # "pas d'eau" EST l'incident : les appelants passent negatable=False.
        self.assertTrue(contains_keyword(
            fold("pas d'eau au robinet"), "eau", "subword", False,
            negation_spans(fold("pas d'eau au robinet"))))
        self.assertTrue(contains_keyword(
            fold("L'eau ne coule plus"), "ne coule", "subword", False))

    def test_negatable_muted_via_contains(self) -> None:
        self.assertFalse(contains_keyword(
            fold("pas de diarrhée"), "diarrh", "subword", True))
        self.assertTrue(contains_keyword(
            fold("diarrhée dans trois classes"), "diarrh", "subword", True))

    def test_word_boundary_blocks_goutte(self) -> None:
        self.assertFalse(contains_keyword(
            fold("grosse goutte au robinet"), "gout", "word", True))
        self.assertTrue(contains_keyword(
            fold("mauvais gout de l'eau"), "gout", "word", True))


class DistrictMatchTest(unittest.TestCase):
    def test_exact_and_accents(self) -> None:
        self.assertTrue(district_match("Vallée-du-Ntem", "vallee-du-ntem"))
        self.assertTrue(district_match("Mvila", "MVILA"))
        self.assertFalse(district_match("Mvila", "Wouri"))

    def test_empty_wanted_is_no_filter(self) -> None:
        self.assertTrue(district_match("Mvila", ""))
        self.assertTrue(district_match("Mvila", None))
        self.assertFalse(district_match("", "Mvila"))

    def test_short_substring_rejected(self) -> None:
        # Bug historique : "oua" matchait "Douala".
        self.assertFalse(district_match("Douala", "oua"))
        self.assertFalse(district_match("Douala", "oua", allow_substring=True))

    def test_token_overlap_and_prefix(self) -> None:
        self.assertTrue(district_match("Dja-et-Lobo", "Dja et Lobo"))
        self.assertTrue(district_match("Vallée-du-Ntem", "Ntem".upper()))
        self.assertFalse(district_match("Douala", "Dou", allow_substring=True))

    def test_strict_mode(self) -> None:
        self.assertTrue(district_match("Mvila", "mvila", mode="strict"))
        self.assertFalse(district_match("Dja-et-Lobo", "Dja", mode="strict"))


class ParseDtTest(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertIsNone(parse_dt(None))
        self.assertIsNone(parse_dt(""))
        self.assertIsNone(parse_dt("n'importe quoi"))
        dt = parse_dt("2026-10-28T10:00:00Z")
        assert dt is not None
        self.assertEqual(dt.tzinfo, timezone.utc)
        naive = parse_dt("2026-10-28T10:00:00")
        assert naive is not None
        self.assertEqual(naive.tzinfo, timezone.utc)
        now = datetime.now(timezone.utc)
        self.assertEqual(parse_dt(now), now)
        self.assertEqual(parse_date(date(2026, 10, 28)),
                         date(2026, 10, 28))
        self.assertEqual(parse_date("2026-10-28"), date(2026, 10, 28))


class DedupTest(unittest.TestCase):
    def test_stable_id_and_row_keys(self) -> None:
        a = {"id": 1, "school_id": 1, "reported_at": "2026-10-28",
             "title": "Fuite"}
        b = {"id": 1, "school_id": 2, "reported_at": "2026-10-27",
             "title": "Autre"}
        c = {"school_id": 3, "reported_at": "2026-10-28", "title": "Fuite"}
        out = dedup_incidents([a, c], [b, c, None, "x"])
        self.assertEqual(out, [a, c])


class ScorePlaceTest(unittest.TestCase):
    def test_typo_suggests(self) -> None:
        self.assertGreaterEqual(
            score_place("Nkole", "École Primaire de Nkol"), 0.75)
        self.assertGreaterEqual(score_place("Mvilla", "Mvila"), 0.75)

    def test_hyphen_token_matches(self) -> None:
        self.assertGreaterEqual(
            score_place("Ntem", "Vallée-du-Ntem"), 0.75)

    def test_generic_alone_scores_low(self) -> None:
        self.assertLess(score_place("ecole", "École Primaire de Nkol"), 0.75)
        self.assertLess(score_place("oua", "Douala"), 0.75)


class DistrictParityTest(unittest.TestCase):
    """Les sites district s'accordent sur la table partagée.

    Détecteurs (epidemic_detector, epidemic_alerts, district_alerts) via
    district_match ; agrégations agent_tools via égalité repliée (stricte).
    """

    AGREE = [
        ("Mvila", "mvila", True),
        ("Vallée-du-Ntem", "vallee-du-ntem", True),
        ("Wouri", "wouri", True),
        ("Mvila", "Wouri", False),
        ("", "Mvila", False),
    ]

    TOLERANT_ONLY = [
        # Tolérance détecteurs (tokens/préfixe) ; agrégations strictes.
        ("Dja-et-Lobo", "Dja et Lobo"),
        ("Vallée-du-Ntem", "NTEM"),
    ]

    def test_agreement_table(self) -> None:
        for item, wanted, expected in self.AGREE:
            with self.subTest(item=item, wanted=wanted):
                self.assertEqual(district_match(item, wanted), expected)
                self.assertEqual(fold(item) == fold(wanted), expected)

    def test_tolerant_detectors_only(self) -> None:
        for item, wanted in self.TOLERANT_ONLY:
            with self.subTest(item=item, wanted=wanted):
                self.assertTrue(district_match(item, wanted))
                self.assertFalse(fold(item) == fold(wanted))


if __name__ == "__main__":
    unittest.main()
