"""LOT 1 anti-valeurs-en-dur : défauts historiques + overrides ENV.

Vérifie que les seuils centralisés gardent leurs valeurs métier historiques
par défaut et que chaque variable ENV dédiée les surcharge (reload).
Ne modifie aucun comportement métier : valeurs par défaut inchangées.
"""
from __future__ import annotations

import ast
import importlib
import os
import unittest


def _reload_with_env(module_name: str, env: dict[str, str]):
    """Recharge un module avec des ENV posées ; restaure tout après."""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return importlib.reload(importlib.import_module(module_name))
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


class Lot1DefaultsTest(unittest.TestCase):
    """Les défauts sont les valeurs historiques (aucune valeur métier changée)."""

    def test_thresholds_defaults(self) -> None:
        from app import thresholds
        self.assertEqual(thresholds.DUPLICATE_DECISION_THRESHOLD, 0.80)
        self.assertEqual(thresholds.DUPLICATE_MATCH_CUTOFF, 0.70)
        self.assertEqual(thresholds.DUPLICATE_JACCARD_FALLBACK, 0.25)

    def test_router_defaults(self) -> None:
        from app import router
        self.assertEqual(router.MARGIN_MIN, 0.15)
        self.assertEqual(router.CREATE_MIN_SCORE, 1.0)
        self.assertEqual(router.DATA_MIN_SCORE, 1.0)
        self.assertEqual(router.PLUGIN_FEATURE_WEIGHT, 2.0)

    def test_textnorm_defaults(self) -> None:
        from app import textnorm
        self.assertEqual(textnorm.NEGATION_WINDOW_TOKENS, 3)
        self.assertEqual(textnorm.NEGATION_NE_CLOSER_WINDOW, 5)
        self.assertEqual(textnorm.DISTRICT_MIN_LEN, 4)
        self.assertEqual(textnorm.PLACE_CUTOFF, 0.75)


class Lot1EnvOverrideTest(unittest.TestCase):
    """Chaque ENV dédiée surcharge son seuil (reload), puis restauration."""

    def _check_override(self, module_name: str, env_name: str,
                        attr: str, override: str, expected) -> None:
        for mod_name in (module_name,):
            self.addCleanup(importlib.reload, importlib.import_module(mod_name))
        mod = _reload_with_env(module_name, {env_name: override})
        self.assertEqual(getattr(mod, attr), expected)
        # Restauration immédiate : défaut historique retrouvé sans ENV.
        restored = importlib.reload(mod)
        saved_env = os.environ.pop(env_name, None)
        try:
            restored = importlib.reload(restored)
        finally:
            if saved_env is not None:
                os.environ[env_name] = saved_env
        return restored

    def test_thresholds_env(self) -> None:
        self._check_override("app.thresholds", "DUPLICATE_DECISION_THRESHOLD",
                             "DUPLICATE_DECISION_THRESHOLD", "0.91", 0.91)
        self._check_override("app.thresholds", "DUPLICATE_MATCH_CUTOFF",
                             "DUPLICATE_MATCH_CUTOFF", "0.61", 0.61)
        self._check_override("app.thresholds", "DUPLICATE_JACCARD_FALLBACK",
                             "DUPLICATE_JACCARD_FALLBACK", "0.33", 0.33)

    def test_router_env(self) -> None:
        self._check_override("app.router", "ROUTER_MARGIN_MIN",
                             "MARGIN_MIN", "0.31", 0.31)
        self._check_override("app.router", "ROUTER_CREATE_MIN_SCORE",
                             "CREATE_MIN_SCORE", "2.5", 2.5)
        self._check_override("app.router", "ROUTER_DATA_MIN_SCORE",
                             "DATA_MIN_SCORE", "2.5", 2.5)
        self._check_override("app.router", "ROUTER_PLUGIN_FEATURE_WEIGHT",
                             "PLUGIN_FEATURE_WEIGHT", "3.5", 3.5)

    def test_textnorm_env(self) -> None:
        self._check_override("app.textnorm", "TEXTNORM_NEGATION_WINDOW",
                             "NEGATION_WINDOW_TOKENS", "5", 5)
        self._check_override("app.textnorm", "TEXTNORM_NEGATION_NE_WINDOW",
                             "NEGATION_NE_CLOSER_WINDOW", "7", 7)
        self._check_override("app.textnorm", "TEXTNORM_DISTRICT_MIN_LEN",
                             "DISTRICT_MIN_LEN", "6", 6)
        self._check_override("app.textnorm", "TEXTNORM_PLACE_CUTOFF",
                             "PLACE_CUTOFF", "0.55", 0.55)

    def test_invalid_env_falls_back_to_default(self) -> None:
        self.addCleanup(importlib.reload, importlib.import_module("app.thresholds"))
        mod = _reload_with_env("app.thresholds",
                               {"DUPLICATE_DECISION_THRESHOLD": "not-a-float"})
        self.assertEqual(mod.DUPLICATE_DECISION_THRESHOLD, 0.80)
        importlib.reload(mod)


class Lot1NoDuplicationTest(unittest.TestCase):
    """duplicate_detector.py ne porte aucun seuil brut (source unique thresholds)."""

    def test_no_raw_threshold_literals(self) -> None:
        import app.duplicate_detector as dd
        from app import thresholds
        # Mêmes valeurs via import (zéro duplication).
        self.assertEqual(dd.DUPLICATE_MATCH_CUTOFF,
                         thresholds.DUPLICATE_MATCH_CUTOFF)
        self.assertEqual(dd.DUPLICATE_JACCARD_FALLBACK,
                         thresholds.DUPLICATE_JACCARD_FALLBACK)
        self.assertEqual(dd.DEFAULT_SIMILARITY_THRESHOLD,
                         thresholds.DUPLICATE_DECISION_THRESHOLD)
        # Aucun littéral flottant 0.8/0.7/0.25 dans le code (hors docstrings).
        with open(dd.__file__, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        floats = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                floats.add(node.value)
        # 0.0/1.0 : neutres d'init, pas des seuils ; 0.25/0.7/0.8 interdits.
        self.assertFalse({0.8, 0.7, 0.25} & floats,
                         f"seuils bruts dupliqués : {sorted(floats)}")


if __name__ == "__main__":
    unittest.main()
