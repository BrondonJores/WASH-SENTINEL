"""Balayage du cutoff lieux (AXE 3) : échoue si PLACE_CUTOFF dérive.

Optimum mesuré sur tests/fixtures_places.py : ex æquo 0.70/0.75 à 40/40,
tie-break précision -> 0.75. Toute modification du scoring ou des fixtures
qui déplace l'optimum fait échouer ce test (anti-redérive SEUIL 0.45/0.75).
"""
from __future__ import annotations

import unittest

from app.textnorm import PLACE_CUTOFF, score_place
from tests.fixtures_places import DISTRICTS, PLACE_CASES, SCHOOLS

CUTOFFS = [round(0.40 + 0.05 * i, 2) for i in range(9)]  # 0.40..0.80


def _top1(fragment: str, pool: list[str]) -> tuple[float, str]:
    scored = sorted(((score_place(fragment, label), label) for label in pool),
                    key=lambda t: -t[0])
    return scored[0]


def sweep(cutoff: float) -> int:
    """Nombre de cas exacts (top-1 == attendu, ou rien si None attendu)."""
    exact = 0
    for fragment, kind, expected in PLACE_CASES:
        pool = SCHOOLS if kind == "school" else DISTRICTS
        best, label = _top1(fragment, pool)
        got = label if best >= cutoff else None
        if got == expected:
            exact += 1
    return exact


class PlaceThresholdTest(unittest.TestCase):
    def test_cutoff_is_sweep_optimum(self) -> None:
        results = [(sweep(c), c) for c in CUTOFFS]
        best_exact = max(exact for exact, _ in results)
        # Tie-break : le cutoff le plus haut (précision) parmi les optima.
        optimum = max(c for exact, c in results if exact == best_exact)
        self.assertEqual(
            optimum, PLACE_CUTOFF,
            f"optimum balayé {optimum} != PLACE_CUTOFF {PLACE_CUTOFF} "
            f"(détail : {sorted(results, reverse=True)})")

    def test_cutoff_scores_all_fixtures(self) -> None:
        self.assertEqual(sweep(PLACE_CUTOFF), len(PLACE_CASES))


if __name__ == "__main__":
    unittest.main()
