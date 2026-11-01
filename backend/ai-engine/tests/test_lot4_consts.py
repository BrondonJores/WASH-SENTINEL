"""LOT 4 anti-valeurs-en-dur : boucle agent + outils, comportement inchangé.

Épingle les VALEURS des constantes centralisées (défauts historiques) et
vérifie les overrides ENV (agent_loop, agent_tools), la source unique
SMALL_MODEL_RE (prompts.py), le paramètre district_examples (guidance) et
les constantes partagées app.tool_consts importées par les tools.
"""
from __future__ import annotations

import importlib
import os
import unittest


def _reload_with_env(module_name: str, env: dict[str, str]):
    """Recharge un module avec des ENV posées ; restaure les ENV après."""
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


class Lot4DefaultsTest(unittest.TestCase):
    """Les défauts sont les valeurs historiques (aucune valeur métier changée)."""

    def test_agent_loop_defaults(self) -> None:
        from app import agent_loop
        self.assertEqual(agent_loop.MAX_ITERATIONS, 5)
        self.assertEqual(agent_loop.RUN_BUDGET_S, 100.0)
        self.assertEqual(agent_loop.MAX_LLM_CALLS, 6)
        self.assertEqual(agent_loop.HISTORY_TURNS, 6)
        self.assertEqual(agent_loop.HISTORY_TURN_MAX_CHARS, 1200)
        self.assertEqual(agent_loop.HISTORY_MAX_CHARS, 4000)
        self.assertEqual(agent_loop.OBS_LIST_MAX_ITEMS, 12)
        self.assertEqual(agent_loop.OBS_STR_MAX_CHARS, 2000)
        self.assertEqual(agent_loop._LANG_MIN_HITS, 2)
        self.assertEqual(agent_loop._LANG_MIN_TOKENS, 4)

    def test_small_model_re_single_source(self) -> None:
        from app import agent_loop, prompts
        self.assertIs(agent_loop.SMALL_MODEL_RE, prompts.SMALL_MODEL_RE)

    def test_agent_tools_defaults(self) -> None:
        from app import agent_tools
        self.assertEqual(agent_tools.HEATMAP_WINDOW_DAYS, 90)
        self.assertEqual(agent_tools.SCHOOL_CHOICES_LIMIT, 10)
        self.assertEqual(agent_tools.INCIDENT_CHOICES_LIMIT, 5)
        self.assertEqual(agent_tools.BUDGET_COMPARE_TOP, 5)
        self.assertEqual(agent_tools.TRENDS_PER_SCHOOL_TOP, 5)
        self.assertEqual(agent_tools.MAINTENANCE_LOGS_DEFAULT_LIMIT, 10)
        self.assertEqual(agent_tools.MAINTENANCE_LOGS_LIMIT_MIN, 1)
        self.assertEqual(agent_tools.MAINTENANCE_LOGS_LIMIT_MAX, 50)
        self.assertEqual(agent_tools.TREND_RATIO_THRESHOLD, 0.15)

    def test_tool_consts_defaults(self) -> None:
        from app import tool_consts
        self.assertEqual(tool_consts.ALERT_WINDOW_DAYS_DEFAULT, 7)
        self.assertEqual(tool_consts.ALERT_WINDOW_DAYS_MIN, 1)
        self.assertEqual(tool_consts.ALERT_WINDOW_DAYS_MAX, 90)
        self.assertEqual(tool_consts.MISSION_WINDOW_DAYS_DEFAULT, 30)
        self.assertEqual(tool_consts.MISSION_WINDOW_DAYS_MIN, 1)
        self.assertEqual(tool_consts.MISSION_WINDOW_DAYS_MAX, 365)
        self.assertEqual(tool_consts.STALE_AFTER_DAYS, 7)
        self.assertEqual(tool_consts.LOG_WINDOW_DAYS, 30)
        self.assertEqual(tool_consts.TREND_MONTHS, 6)
        self.assertEqual(tool_consts.MAX_ECOLE_OPTIONS, 6)
        self.assertEqual(tool_consts.INCIDENT_FUZZY_MIN_RATIO, 0.6)

    def test_tools_use_shared_consts(self) -> None:
        from app import tool_consts
        from app.tools import (
            district_alerts,
            document_briefing,
            epidemic_alerts,
            interventoils_mission,
            observatoire,
            prepare_chantier_update,
            relances_proactives,
            saisie_assistee,
        )
        from app import agent_tools
        # Alias privés branchés sur la source unique.
        self.assertEqual(district_alerts._STALE_DAYS, tool_consts.STALE_AFTER_DAYS)
        self.assertEqual(document_briefing._STALE_DAYS, tool_consts.STALE_AFTER_DAYS)
        self.assertEqual(document_briefing._LOG_WINDOW_DAYS, tool_consts.LOG_WINDOW_DAYS)
        self.assertEqual(observatoire._TREND_MONTHS, tool_consts.TREND_MONTHS)
        self.assertEqual(saisie_assistee._MAX_ECOLE_OPTIONS, tool_consts.MAX_ECOLE_OPTIONS)
        # Ratio flou partagé agent_tools <-> prepare_chantier_update.
        self.assertEqual(agent_tools.INCIDENT_FUZZY_MIN_RATIO,
                         tool_consts.INCIDENT_FUZZY_MIN_RATIO)
        self.assertEqual(prepare_chantier_update.INCIDENT_FUZZY_MIN_RATIO,
                         tool_consts.INCIDENT_FUZZY_MIN_RATIO)
        # Schémas d'outils : mêmes défauts exposés au LLM.
        self.assertEqual(district_alerts.TOOL_DEF["parameters"]["properties"]["days"]["default"], 7)
        self.assertEqual(epidemic_alerts.TOOL_DEF["parameters"]["properties"]["days"]["default"], 7)
        self.assertEqual(relances_proactives.TOOL_DEF["parameters"]["properties"]["days"]["default"], 7)
        self.assertEqual(
            interventoils_mission.TOOL_DEF["parameters"]["properties"]["days"]["default"], 30)

    def test_guidance_defaults(self) -> None:
        from app import guidance
        self.assertEqual(guidance.DISTRICT_EXAMPLES, "Mvila, Wouri, Yaoundé, Douala")
        self.assertEqual(guidance.GUIDANCE_PERIOD_DAYS, 90)

    def test_place_suggest_defaults(self) -> None:
        from app import place_suggest
        self.assertEqual(place_suggest.SUGGEST_DEFAULT_LIMIT, 3)
        self.assertEqual(place_suggest.ECOLES_SAMPLE_SIZE, 3)
        self.assertEqual(place_suggest.FRAGMENT_MAX_WORDS, 3)
        self.assertEqual(place_suggest.FRAGMENT_MIN_TOKEN_LEN, 3)


class Lot4EnvOverrideTest(unittest.TestCase):
    """Chaque ENV dédiée surcharge sa constante (reload), puis restauration."""

    def _check_override(self, module_name: str, env_name: str,
                        attr: str, override: str, expected) -> None:
        mod = importlib.import_module(module_name)
        self.addCleanup(importlib.reload, mod)
        try:
            reloaded = _reload_with_env(module_name, {env_name: override})
            self.assertEqual(getattr(reloaded, attr), expected)
        finally:
            importlib.reload(importlib.import_module(module_name))

    def test_agent_loop_env(self) -> None:
        cases = [
            ("AGENT_MAX_ITERATIONS", "MAX_ITERATIONS", "9", 9),
            ("AGENT_RUN_BUDGET_S", "RUN_BUDGET_S", "12.5", 12.5),
            ("AGENT_MAX_LLM_CALLS", "MAX_LLM_CALLS", "9", 9),
            ("AGENT_HISTORY_TURNS", "HISTORY_TURNS", "9", 9),
            ("AGENT_HISTORY_TURN_MAX_CHARS", "HISTORY_TURN_MAX_CHARS", "99", 99),
            ("AGENT_HISTORY_MAX_CHARS", "HISTORY_MAX_CHARS", "99", 99),
            ("AGENT_OBS_LIST_MAX_ITEMS", "OBS_LIST_MAX_ITEMS", "99", 99),
            ("AGENT_OBS_STR_MAX_CHARS", "OBS_STR_MAX_CHARS", "99", 99),
            ("AGENT_LANG_MIN_HITS", "_LANG_MIN_HITS", "9", 9),
            ("AGENT_LANG_MIN_TOKENS", "_LANG_MIN_TOKENS", "9", 9),
        ]
        for env_name, attr, override, expected in cases:
            with self.subTest(env=env_name):
                self._check_override("app.agent_loop", env_name, attr, override, expected)

    def test_agent_tools_env(self) -> None:
        cases = [
            ("AGENT_TOOLS_HEATMAP_WINDOW_DAYS", "HEATMAP_WINDOW_DAYS", "30", 30),
            ("AGENT_TOOLS_SCHOOL_CHOICES_LIMIT", "SCHOOL_CHOICES_LIMIT", "3", 3),
            ("AGENT_TOOLS_INCIDENT_CHOICES_LIMIT", "INCIDENT_CHOICES_LIMIT", "3", 3),
            ("AGENT_TOOLS_BUDGET_COMPARE_TOP", "BUDGET_COMPARE_TOP", "3", 3),
            ("AGENT_TOOLS_TRENDS_PER_SCHOOL_TOP", "TRENDS_PER_SCHOOL_TOP", "3", 3),
            ("AGENT_TOOLS_MAINTENANCE_LOGS_LIMIT", "MAINTENANCE_LOGS_DEFAULT_LIMIT", "3", 3),
            ("AGENT_TOOLS_MAINTENANCE_LOGS_MIN", "MAINTENANCE_LOGS_LIMIT_MIN", "2", 2),
            ("AGENT_TOOLS_MAINTENANCE_LOGS_MAX", "MAINTENANCE_LOGS_LIMIT_MAX", "20", 20),
            ("AGENT_TOOLS_TREND_RATIO_THRESHOLD", "TREND_RATIO_THRESHOLD", "0.3", 0.3),
        ]
        for env_name, attr, override, expected in cases:
            with self.subTest(env=env_name):
                self._check_override("app.agent_tools", env_name, attr, override, expected)

    def test_invalid_env_falls_back_to_default(self) -> None:
        for module_name in ("app.agent_loop", "app.agent_tools"):
            self.addCleanup(importlib.reload, importlib.import_module(module_name))
        mod = _reload_with_env("app.agent_loop", {"AGENT_MAX_ITERATIONS": "not-an-int"})
        self.assertEqual(mod.MAX_ITERATIONS, 5)
        importlib.reload(mod)
        mod = _reload_with_env(
            "app.agent_tools", {"AGENT_TOOLS_TREND_RATIO_THRESHOLD": "not-a-float"})
        self.assertEqual(mod.TREND_RATIO_THRESHOLD, 0.15)
        importlib.reload(mod)


class Lot4GuidanceCallerTest(unittest.TestCase):
    """DISTRICT_EXAMPLES : fourni par l'appelant, sinon repli historique."""

    def test_caller_examples_win(self) -> None:
        from app.guidance import build_guidance_card
        obs = {"error": "District 'Zorglub' introuvable."}
        card = build_guidance_card("district_alerts", obs, district_examples="Foo, Bar")
        assert card is not None
        self.assertIn("Foo, Bar", card.data["explication"])
        self.assertNotIn("Mvila", card.data["explication"])

    def test_fallback_without_caller(self) -> None:
        from app.guidance import build_guidance_card
        obs = {"error": "District 'Zorglub' introuvable."}
        card = build_guidance_card("district_alerts", obs)
        assert card is not None
        self.assertIn("Mvila", card.data["explication"])


if __name__ == "__main__":
    unittest.main()
