"""Calibration du repli Jaccard (AXE 8) : chiffres épinglés, pas d'opinion.

Corpus n=179 (171 paires non-doublons + 8 paraphrases, fixés AVANT le sweep
dans tests/fixtures_duplicates.py) :
- non-doublon le plus dur : 0.222 (pompe cassée vs pompe bloquée, panne
  différente sur même famille d'équipement) ;
- à l'ancien seuil 0.50 : TP=0 FP=0 FN=8 -> rappel 0.00 (le repli ne servait
  quasiment jamais) ;
- au seuil 0.25 : TP=5 FP=0 FN=3 -> P=1.00 R=0.625 F1=0.77 ;
- 0.25 est la borne haute inclusive de l'intervalle de séparation
  (0.222, 0.250] (paraphrase la plus faible captée : 0.250, vol de robinets
  rewordé) : marge 0.028 au-dessus du non-doublon max, choix pro-précision
  cohérent avec PLACE_CUTOFF ;
- limite résiduelle : 3 paraphrases à fort rewording (0.150-0.222)
  chevauchent la plage des non-doublons (<=0.222) : AUCUN seuil Jaccard ne
  les sépare, rappel plafonné à 0.625 en mode dégradé. Le chemin nominal
  (embeddings cosinus) les traite.
"""
from __future__ import annotations

import itertools
import unittest

from app.thresholds import DUPLICATE_JACCARD_FALLBACK
from tests.fixtures_duplicates import NON_DUP_TEXTS, PARAPHRASE_PAIRS, jaccard


def _non_dup_scores() -> list[float]:
    return [jaccard(NON_DUP_TEXTS[i], NON_DUP_TEXTS[j])
            for i, j in itertools.combinations(range(len(NON_DUP_TEXTS)), 2)]


def _paraphrase_scores() -> list[float]:
    return [jaccard(a, b) for a, b in PARAPHRASE_PAIRS]


class CalibrationCorpusTest(unittest.TestCase):
    def test_corpus_sizes_frozen(self) -> None:
        self.assertEqual(len(NON_DUP_TEXTS), 19)
        self.assertEqual(len(PARAPHRASE_PAIRS), 8)
        self.assertEqual(len(_non_dup_scores()), 171)

    def test_hardest_non_duplicate_pinned(self) -> None:
        scores = _non_dup_scores()
        self.assertAlmostEqual(max(scores), 0.222, places=3)
        hardest = max(
            itertools.combinations(range(len(NON_DUP_TEXTS)), 2),
            key=lambda p: jaccard(NON_DUP_TEXTS[p[0]], NON_DUP_TEXTS[p[1]]),
        )
        pair = {NON_DUP_TEXTS[hardest[0]], NON_DUP_TEXTS[hardest[1]]}
        self.assertTrue(any("cassée" in t for t in pair))
        self.assertTrue(any("bloquée" in t for t in pair))


class JaccardThresholdTest(unittest.TestCase):
    def test_threshold_value_is_calibrated_quarter(self) -> None:
        self.assertEqual(DUPLICATE_JACCARD_FALLBACK, 0.25)

    def test_old_threshold_killed_recall(self) -> None:
        tp = sum(1 for s in _paraphrase_scores() if s >= 0.50)
        fp = sum(1 for s in _non_dup_scores() if s >= 0.50)
        self.assertEqual((tp, fp), (0, 0))

    def test_calibrated_threshold_precision_recall(self) -> None:
        thr = DUPLICATE_JACCARD_FALLBACK
        tp = sum(1 for s in _paraphrase_scores() if s >= thr)
        fp = sum(1 for s in _non_dup_scores() if s >= thr)
        fn = len(PARAPHRASE_PAIRS) - tp
        self.assertEqual((tp, fp, fn), (5, 0, 3))
        precision = tp / (tp + fp)
        recall = tp / len(PARAPHRASE_PAIRS)
        f1 = 2 * precision * recall / (precision + recall)
        self.assertAlmostEqual(precision, 1.00, places=2)
        self.assertAlmostEqual(recall, 0.625, places=3)
        self.assertAlmostEqual(f1, 0.77, places=2)

    def test_separation_margin_documented(self) -> None:
        # Aucun non-doublon n'atteint le seuil (marge 0.028).
        self.assertLess(max(_non_dup_scores()), DUPLICATE_JACCARD_FALLBACK)
        # La paraphrase la plus faible captée touche le seuil (borne incluse).
        kept = [s for s in _paraphrase_scores() if s >= DUPLICATE_JACCARD_FALLBACK]
        self.assertAlmostEqual(min(kept), 0.250, places=3)


class FallbackIntegrationTest(unittest.TestCase):
    def test_fallback_matches_sweep_on_paraphrase(self) -> None:
        from app.duplicate_detector import DuplicateDetector
        from app.schemas import DuplicateCheckRequest, IncidentItem

        kept = next((a, b) for a, b in PARAPHRASE_PAIRS if jaccard(a, b) >= 0.25)
        req = DuplicateCheckRequest(
            incoming_summary=kept[0],
            active_incidents=[IncidentItem(id=1, summary=kept[1], category="water")],
        )
        res = DuplicateDetector(llm=None)._fallback_text_match(req)  # type: ignore[arg-type]
        self.assertTrue(res.is_duplicate)
        self.assertEqual(res.matched_incident_id, 1)

    def test_fallback_rejects_hardest_non_duplicate(self) -> None:
        from app.duplicate_detector import DuplicateDetector
        from app.schemas import DuplicateCheckRequest, IncidentItem

        hardest = max(
            itertools.combinations(range(len(NON_DUP_TEXTS)), 2),
            key=lambda p: jaccard(NON_DUP_TEXTS[p[0]], NON_DUP_TEXTS[p[1]]),
        )
        req = DuplicateCheckRequest(
            incoming_summary=NON_DUP_TEXTS[hardest[0]],
            active_incidents=[IncidentItem(
                id=2, summary=NON_DUP_TEXTS[hardest[1]], category="water")],
        )
        res = DuplicateDetector(llm=None)._fallback_text_match(req)  # type: ignore[arg-type]
        self.assertFalse(res.is_duplicate)


if __name__ == "__main__":
    unittest.main()
