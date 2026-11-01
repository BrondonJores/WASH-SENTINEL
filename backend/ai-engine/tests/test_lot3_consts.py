"""LOT 3 anti-valeurs-en-dur : risques/dispatch/décision.

Épingle les défauts historiques (aucune valeur métier changée), vérifie
chaque override ENV, la table pannes canonique unique (extractor, importée
par recurrence_watch), les seuils copilot importés de decision_agent, le
correctif 2026 figé -> date.today().year, et des goldens comportementaux
équité/décision capturés AVANT refactor.
"""
from __future__ import annotations

import ast
import importlib
import os
import unittest
from datetime import date
from unittest.mock import patch


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


class Lot3EpidemicTest(unittest.TestCase):
    def test_defaults_pinned(self) -> None:
        from app import epidemic_detector as ed
        self.assertEqual(ed.CLUSTER_WINDOW_DAYS, 7)
        self.assertEqual(ed.OUTBREAK_MIN_STRONG_SCHOOLS, 3)
        self.assertEqual(ed.HIGH_MIN_STRONG_SCHOOLS, 2)
        self.assertEqual(ed.MODERATE_MIN_SCHOOLS, 1)
        self.assertEqual(
            ed.DEFAULT_HEALTH_ACTIONS,
            [
                "Distribution d'urgence de pastilles de purification d'eau (Aquatabs)",
                "Sensibilisation immédiate au lavage des mains au savon dans les classes",
                "Inspection sanitaire de la source d'approvisionnement communale",
            ],
        )

    def test_rule_level_uses_consts(self) -> None:
        from app import epidemic_detector as ed
        self.assertEqual(ed.EpidemicDetector._rule_level(3, 0), ("outbreak_warning", True))
        self.assertEqual(ed.EpidemicDetector._rule_level(2, 5), ("high", True))
        self.assertEqual(ed.EpidemicDetector._rule_level(1, 0), ("moderate", False))
        self.assertEqual(ed.EpidemicDetector._rule_level(0, 1), ("moderate", False))
        self.assertEqual(ed.EpidemicDetector._rule_level(0, 0), ("normal", False))

    def test_env_overrides(self) -> None:
        cases = [
            ("EPIDEMIC_CLUSTER_WINDOW_DAYS", "CLUSTER_WINDOW_DAYS", "10", 10),
            ("EPIDEMIC_OUTBREAK_MIN_STRONG_SCHOOLS", "OUTBREAK_MIN_STRONG_SCHOOLS", "5", 5),
            ("EPIDEMIC_HIGH_MIN_STRONG_SCHOOLS", "HIGH_MIN_STRONG_SCHOOLS", "4", 4),
            ("EPIDEMIC_MODERATE_MIN_SCHOOLS", "MODERATE_MIN_SCHOOLS", "2", 2),
        ]
        for env_name, attr, override, expected in cases:
            with self.subTest(env=env_name):
                self.addCleanup(importlib.reload, importlib.import_module("app.epidemic_detector"))
                mod = _reload_with_env("app.epidemic_detector", {env_name: override})
                self.assertEqual(getattr(mod, attr), expected)
                importlib.reload(mod)

    def test_invalid_env_falls_back(self) -> None:
        self.addCleanup(importlib.reload, importlib.import_module("app.epidemic_detector"))
        mod = _reload_with_env("app.epidemic_detector", {"EPIDEMIC_CLUSTER_WINDOW_DAYS": "nope"})
        self.assertEqual(mod.CLUSTER_WINDOW_DAYS, 7)
        importlib.reload(mod)


class Lot3EquityTest(unittest.TestCase):
    def test_defaults_pinned(self) -> None:
        from app import equity_dispatcher as eq
        self.assertEqual(eq.EQUITY_WATER_NORM_DAYS, 20.0)
        self.assertEqual(eq.EQUITY_URGENCY_LOW, 15.0)
        self.assertEqual(eq.EQUITY_URGENCY_MEDIUM, 45.0)
        self.assertEqual(eq.EQUITY_URGENCY_HIGH, 75.0)
        self.assertEqual(eq.EQUITY_URGENCY_CRITICAL, 100.0)
        self.assertEqual(
            eq.EQUITY_URGENCY_SCORES,
            {"low": 15.0, "medium": 45.0, "high": 75.0, "critical": 100.0},
        )
        self.assertEqual(eq.EQUITY_FEMALE_RATIO_MIN, 0.3)
        self.assertEqual(eq.EQUITY_FEMALE_RATIO_MAX, 0.7)
        self.assertEqual(eq.EQUITY_LATRINE_NORM_COUNT, 4.0)
        self.assertEqual(eq.EQUITY_LATRINE_BASELINE_SCORE, 0.1)
        self.assertEqual(eq.EQUITY_GENDER_AMPLIFIER, 1.5)
        self.assertEqual(eq.EQUITY_DISTANCE_NORM_KM, 70.0)
        self.assertEqual(eq.EQUITY_DISTANCE_MAX_POINTS, 50.0)
        self.assertEqual(eq.EQUITY_ABANDON_NORM_MONTHS, 18.0)
        self.assertEqual(eq.EQUITY_ABANDON_MAX_POINTS, 50.0)
        self.assertEqual(eq.EQUITY_WEIGHT_WATER, 0.30)
        self.assertEqual(eq.EQUITY_WEIGHT_URGENCY, 0.25)
        self.assertEqual(eq.EQUITY_WEIGHT_GENDER, 0.25)
        self.assertEqual(eq.EQUITY_WEIGHT_ISOLATION, 0.20)
        self.assertEqual(eq.EQUITY_REASON_MIN_DAYS_WITHOUT_WATER, 10)
        self.assertEqual(eq.EQUITY_REASON_MIN_BROKEN_TOILETS, 2)
        self.assertEqual(eq.EQUITY_REASON_MIN_ISOLATION_KM, 40)
        self.assertEqual(eq.EQUITY_ROUTE_MAX_DIST_DIFF_KM, 18.0)
        self.assertEqual(eq.EQUITY_ROUTE_SAVED_KM_FACTOR, 1.6)
        self.assertEqual(eq.EQUITY_ROUTE_MAX_PIGGYBACK, 2)
        self.assertEqual(eq.EQUITY_TRANSPARENCY_NOTE_MIN_CHARS, 100)

    def test_env_overrides(self) -> None:
        cases = [
            ("EQUITY_WATER_NORM_DAYS", "EQUITY_WATER_NORM_DAYS", "25.0", 25.0),
            ("EQUITY_URGENCY_LOW", "EQUITY_URGENCY_LOW", "11.0", 11.0),
            ("EQUITY_URGENCY_MEDIUM", "EQUITY_URGENCY_MEDIUM", "44.0", 44.0),
            ("EQUITY_URGENCY_HIGH", "EQUITY_URGENCY_HIGH", "74.0", 74.0),
            ("EQUITY_URGENCY_CRITICAL", "EQUITY_URGENCY_CRITICAL", "99.0", 99.0),
            ("EQUITY_FEMALE_RATIO_MIN", "EQUITY_FEMALE_RATIO_MIN", "0.2", 0.2),
            ("EQUITY_FEMALE_RATIO_MAX", "EQUITY_FEMALE_RATIO_MAX", "0.8", 0.8),
            ("EQUITY_LATRINE_NORM_COUNT", "EQUITY_LATRINE_NORM_COUNT", "5.0", 5.0),
            ("EQUITY_LATRINE_BASELINE_SCORE", "EQUITY_LATRINE_BASELINE_SCORE", "0.2", 0.2),
            ("EQUITY_GENDER_AMPLIFIER", "EQUITY_GENDER_AMPLIFIER", "2.0", 2.0),
            ("EQUITY_DISTANCE_NORM_KM", "EQUITY_DISTANCE_NORM_KM", "60.0", 60.0),
            ("EQUITY_DISTANCE_MAX_POINTS", "EQUITY_DISTANCE_MAX_POINTS", "40.0", 40.0),
            ("EQUITY_ABANDON_NORM_MONTHS", "EQUITY_ABANDON_NORM_MONTHS", "12.0", 12.0),
            ("EQUITY_ABANDON_MAX_POINTS", "EQUITY_ABANDON_MAX_POINTS", "60.0", 60.0),
            ("EQUITY_WEIGHT_WATER", "EQUITY_WEIGHT_WATER", "0.4", 0.4),
            ("EQUITY_WEIGHT_URGENCY", "EQUITY_WEIGHT_URGENCY", "0.2", 0.2),
            ("EQUITY_WEIGHT_GENDER", "EQUITY_WEIGHT_GENDER", "0.2", 0.2),
            ("EQUITY_WEIGHT_ISOLATION", "EQUITY_WEIGHT_ISOLATION", "0.2", 0.2),
            ("EQUITY_REASON_MIN_DAYS_WITHOUT_WATER", "EQUITY_REASON_MIN_DAYS_WITHOUT_WATER", "7", 7),
            ("EQUITY_REASON_MIN_BROKEN_TOILETS", "EQUITY_REASON_MIN_BROKEN_TOILETS", "3", 3),
            ("EQUITY_REASON_MIN_ISOLATION_KM", "EQUITY_REASON_MIN_ISOLATION_KM", "30", 30),
            ("EQUITY_ROUTE_MAX_DIST_DIFF_KM", "EQUITY_ROUTE_MAX_DIST_DIFF_KM", "10.0", 10.0),
            ("EQUITY_ROUTE_SAVED_KM_FACTOR", "EQUITY_ROUTE_SAVED_KM_FACTOR", "2.0", 2.0),
            ("EQUITY_ROUTE_MAX_PIGGYBACK", "EQUITY_ROUTE_MAX_PIGGYBACK", "3", 3),
            ("EQUITY_TRANSPARENCY_NOTE_MIN_CHARS", "EQUITY_TRANSPARENCY_NOTE_MIN_CHARS", "50", 50),
        ]
        for env_name, attr, override, expected in cases:
            with self.subTest(env=env_name):
                self.addCleanup(importlib.reload, importlib.import_module("app.equity_dispatcher"))
                mod = _reload_with_env("app.equity_dispatcher", {env_name: override})
                self.assertEqual(getattr(mod, attr), expected)
                importlib.reload(mod)

    def test_urgency_table_built_from_consts(self) -> None:
        self.addCleanup(importlib.reload, importlib.import_module("app.equity_dispatcher"))
        mod = _reload_with_env("app.equity_dispatcher", {"EQUITY_URGENCY_HIGH": "74.0"})
        self.assertEqual(mod.EQUITY_URGENCY_SCORES["high"], 74.0)
        importlib.reload(mod)

    def test_equity_goldens_unchanged(self) -> None:
        """Scores capturés AVANT refactor : la formule est inchangée."""
        from app.equity_dispatcher import EquityDispatcher
        from app.schemas import SchoolEquityProfile

        class _LLM:
            model = "lot3"

        eq = EquityDispatcher(llm=_LLM())  # type: ignore[arg-type]
        prof = SchoolEquityProfile(
            school_id=1, school_name="Snap A", district="D",
            distance_from_center_km=72.0, days_without_water=22,
            total_students=380, female_students=195, broken_toilets=4,
            months_since_last_intervention=14, urgency_level="critical",
            issue_summary="x",
        )
        score, reason = eq.calculate_equity_score(prof)
        self.assertEqual(score, 92.0)
        self.assertIn("22j sans eau", reason)
        self.assertIn("Zone isolée", reason)
        prof2 = SchoolEquityProfile(
            school_id=2, school_name="Snap B", district="D",
            distance_from_center_km=3.0, days_without_water=2,
            total_students=650, female_students=310, broken_toilets=1,
            months_since_last_intervention=2, urgency_level="medium",
            issue_summary="y",
        )
        self.assertEqual(eq.calculate_equity_score(prof2), (20.3, "Maintenance programmée standard"))
        prof3 = SchoolEquityProfile(
            school_id=4, school_name="Snap D", district="D",
            distance_from_center_km=12.0, days_without_water=5,
            total_students=290, female_students=140, broken_toilets=0,
            months_since_last_intervention=5, urgency_level="medium",
            issue_summary="w",
        )
        self.assertEqual(eq.calculate_equity_score(prof3), (25.1, "Maintenance programmée standard"))


class Lot3DecisionTest(unittest.TestCase):
    def test_defaults_pinned(self) -> None:
        from app import decision_agent as da
        self.assertEqual(da.DECISION_REPLACE_MIN_RATIO_PCT, 55.0)
        self.assertEqual(da.DECISION_REPLACE_MIN_INCIDENTS, 4)
        self.assertEqual(da.DECISION_REPLACE_MIN_DAYS_OFF, 30)
        self.assertEqual(da.DECISION_REPAIR_SAVING_RATIO, 0.45)
        self.assertEqual(da.DECISION_SAVING_HORIZON_MONTHS, 24)
        self.assertEqual(da.DECISION_MONITOR_MIN_RATIO_PCT, 30.0)
        self.assertEqual(da.DECISION_MONITOR_MIN_INCIDENTS, 2)

    def test_env_overrides(self) -> None:
        cases = [
            ("DECISION_REPLACE_MIN_RATIO_PCT", "DECISION_REPLACE_MIN_RATIO_PCT", "60.0", 60.0),
            ("DECISION_REPLACE_MIN_INCIDENTS", "DECISION_REPLACE_MIN_INCIDENTS", "5", 5),
            ("DECISION_REPLACE_MIN_DAYS_OFF", "DECISION_REPLACE_MIN_DAYS_OFF", "45", 45),
            ("DECISION_REPAIR_SAVING_RATIO", "DECISION_REPAIR_SAVING_RATIO", "0.5", 0.5),
            ("DECISION_SAVING_HORIZON_MONTHS", "DECISION_SAVING_HORIZON_MONTHS", "12", 12),
            ("DECISION_MONITOR_MIN_RATIO_PCT", "DECISION_MONITOR_MIN_RATIO_PCT", "25.0", 25.0),
            ("DECISION_MONITOR_MIN_INCIDENTS", "DECISION_MONITOR_MIN_INCIDENTS", "3", 3),
        ]
        for env_name, attr, override, expected in cases:
            with self.subTest(env=env_name):
                self.addCleanup(importlib.reload, importlib.import_module("app.decision_agent"))
                mod = _reload_with_env("app.decision_agent", {env_name: override})
                self.assertEqual(getattr(mod, attr), expected)
                importlib.reload(mod)

    def test_year_is_dynamic_not_frozen(self) -> None:
        """Le bug 2026 figé est corrigé : l'année courante réelle est utilisée."""
        from app.decision_agent import DecisionAgent
        from app.schemas import SchoolMaintenanceHistory

        school = SchoolMaintenanceHistory(
            school_id=1, school_name="E", district="D", equipment_type="P",
            installation_year=2020, estimated_replacement_cost=1000000.0,
            incident_count=6, total_repair_cost=10000.0, total_days_without_service=1,
        )
        expected_years = max(1, date.today().year - 2020)
        analysis = DecisionAgent.evaluate_school_equipment(school)
        self.assertEqual(analysis.annualized_failure_rate, round(6 / expected_years, 1))

        class _FakeDate(date):
            @classmethod
            def today(cls) -> date:  # type: ignore[override]
                return date(2030, 6, 1)

        with patch("app.decision_agent.date", _FakeDate):
            moved = DecisionAgent.evaluate_school_equipment(school)
        # 2030 - 2020 = 10 ans : le taux suit l'année mockée, pas 2026.
        self.assertEqual(moved.annualized_failure_rate, round(6 / 10, 1))

    def test_decision_goldens_unchanged(self) -> None:
        """Analyses capturées AVANT refactor (on est en 2026 : identiques)."""
        from app.decision_agent import DecisionAgent
        from app.schemas import SchoolMaintenanceHistory

        replace = SchoolMaintenanceHistory(
            school_id=1, school_name="H Replace", district="D",
            equipment_type="Pompe", installation_year=2019,
            estimated_replacement_cost=1500000.0, incident_count=5,
            total_repair_cost=1120000.0, total_days_without_service=42,
        )
        analysis = DecisionAgent.evaluate_school_equipment(replace)
        self.assertEqual(analysis.recommendation, "REPLACE_EQUIPMENT")
        self.assertEqual(analysis.repair_to_replacement_ratio_percent, 74.7)
        self.assertEqual(analysis.annualized_failure_rate, 0.7)
        self.assertIn("504,000 FCFA sur les 24 prochains mois",
                      analysis.financial_saving_potential)

        edge = SchoolMaintenanceHistory(
            school_id=4, school_name="H Edge", district="D",
            equipment_type="Cuve", installation_year=2020,
            estimated_replacement_cost=1000000.0, incident_count=2,
            total_repair_cost=300000.0, total_days_without_service=10,
        )
        analysis = DecisionAgent.evaluate_school_equipment(edge)
        self.assertEqual(analysis.recommendation, "MONITOR_CLOSELY")
        self.assertEqual(analysis.repair_to_replacement_ratio_percent, 30.0)

        repair = SchoolMaintenanceHistory(
            school_id=3, school_name="H Repair", district="D",
            equipment_type="Robinet", installation_year=2025,
            estimated_replacement_cost=1000000.0, incident_count=1,
            total_repair_cost=50000.0, total_days_without_service=2,
        )
        analysis = DecisionAgent.evaluate_school_equipment(repair)
        self.assertEqual(analysis.recommendation, "CONTINUE_REPAIR")


class Lot3RecurrenceTest(unittest.TestCase):
    def test_defaults_pinned(self) -> None:
        from app import recurrence_watch as rw
        self.assertEqual(rw.RECURRENCE_WINDOW_DAYS, 90)
        self.assertEqual(rw.HIGH_SAME_TYPE_COUNT, 3)
        self.assertEqual(rw.WATCH_SAME_TYPE_COUNT, 2)
        self.assertEqual(rw.MEAN_INTERVAL_ALERT_DAYS, 30.0)
        self.assertEqual(rw.AGGREGATE_HIGH_INCIDENT_COUNT, 4)
        self.assertEqual(rw.AGGREGATE_WATCH_INCIDENT_COUNT, 2)
        self.assertEqual(rw.AGGREGATE_CRITICAL_DAYS_OFF, 30)

    def test_env_overrides(self) -> None:
        cases = [
            ("RECURRENCE_WINDOW_DAYS", "RECURRENCE_WINDOW_DAYS", "60", 60),
            ("RECURRENCE_HIGH_SAME_TYPE_COUNT", "HIGH_SAME_TYPE_COUNT", "5", 5),
            ("RECURRENCE_WATCH_SAME_TYPE_COUNT", "WATCH_SAME_TYPE_COUNT", "3", 3),
            ("RECURRENCE_MEAN_INTERVAL_ALERT_DAYS", "MEAN_INTERVAL_ALERT_DAYS", "20.0", 20.0),
            ("RECURRENCE_AGGREGATE_HIGH_INCIDENT_COUNT", "AGGREGATE_HIGH_INCIDENT_COUNT", "6", 6),
            ("RECURRENCE_AGGREGATE_WATCH_INCIDENT_COUNT", "AGGREGATE_WATCH_INCIDENT_COUNT", "3", 3),
            ("RECURRENCE_AGGREGATE_CRITICAL_DAYS_OFF", "AGGREGATE_CRITICAL_DAYS_OFF", "45", 45),
        ]
        for env_name, attr, override, expected in cases:
            with self.subTest(env=env_name):
                self.addCleanup(importlib.reload, importlib.import_module("app.recurrence_watch"))
                mod = _reload_with_env("app.recurrence_watch", {env_name: override})
                self.assertEqual(getattr(mod, attr), expected)
                importlib.reload(mod)

    def test_canonical_table_single_definition(self) -> None:
        """Table pannes définie UNE fois (extractor), importée par recurrence."""
        from app import extractor, recurrence_watch
        self.assertIs(recurrence_watch._ISSUE_LABELS, extractor.ISSUE_TYPE_LABELS)
        self.assertIs(recurrence_watch._ISSUE_ALIASES, extractor.ISSUE_TYPE_ALIASES)
        self.assertEqual(
            extractor.ISSUE_TYPE_LABELS,
            {
                "leak": "fuites",
                "total_breakdown": "pannes totales",
                "contamination": "contaminations",
                "blockage": "obstructions",
                "dry_well": "assèchements de puits",
                "vandalism": "actes de vandalisme",
                "other": "pannes",
            },
        )
        # Échantillon d'alias historiques (contenu inchangé).
        for alias, code in (("fuites", "leak"), ("pompe cassee", "total_breakdown"),
                            ("eau contaminee", "contamination"), ("bouchon", "blockage"),
                            ("puits sec", "dry_well"), ("vandalisme", "vandalism"),
                            ("unknown", "other")):
            self.assertEqual(extractor.ISSUE_TYPE_ALIASES[alias], code)
        # Zéro recopie : le littéral distinctif n'apparaît qu'à un endroit.
        import app
        root = os.path.dirname(app.__file__)
        hits = []
        for dirpath, _, filenames in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf-8") as fh:
                    if '"pannes totales"' in fh.read():
                        hits.append(path)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].endswith("extractor.py"))


class Lot3CopilotTest(unittest.TestCase):
    def test_thresholds_imported_from_decision_agent(self) -> None:
        from app import decision_agent as da
        from app.tools import copilot_answer as ca
        self.assertEqual(ca.DECISION_REPLACE_MIN_INCIDENTS, da.DECISION_REPLACE_MIN_INCIDENTS)
        self.assertEqual(ca.DECISION_REPLACE_MIN_RATIO_PCT, da.DECISION_REPLACE_MIN_RATIO_PCT)
        self.assertEqual(ca.DECISION_REPLACE_MIN_DAYS_OFF, da.DECISION_REPLACE_MIN_DAYS_OFF)
        self.assertEqual(ca.DECISION_MONITOR_MIN_INCIDENTS, da.DECISION_MONITOR_MIN_INCIDENTS)
        self.assertEqual(ca.DECISION_MONITOR_MIN_RATIO_PCT, da.DECISION_MONITOR_MIN_RATIO_PCT)
        self.assertEqual(ca.DECISION_REPLACE_MIN_INCIDENTS, 4)
        self.assertEqual(ca.DECISION_REPLACE_MIN_RATIO_PCT, 55.0)
        self.assertEqual(ca.DECISION_REPLACE_MIN_DAYS_OFF, 30)
        self.assertEqual(ca.DECISION_MONITOR_MIN_INCIDENTS, 2)
        self.assertEqual(ca.DECISION_MONITOR_MIN_RATIO_PCT, 30.0)

    def test_local_consts_pinned(self) -> None:
        from app.tools import copilot_answer as ca
        self.assertEqual(ca.SCHOOL_TOKEN_MIN_LEN, 4)
        self.assertEqual(ca.BUDGET_REPLACE_MARGIN, 1.2)
        self.assertEqual(ca.BUDGET_MAINTAIN_FRACTION, 0.5)
        self.assertEqual(ca.BUDGET_MIN_ENVELOPE_XAF, 100000.0)

    def test_no_recopied_threshold_literals(self) -> None:
        """_recommend et l'enveloppe n'ont aucun seuil brut (noms importés)."""
        import app.tools.copilot_answer as ca

        def _numbers(node: ast.AST) -> list:
            return [
                n.value for n in ast.walk(node)
                if isinstance(n, ast.Constant)
                and isinstance(n.value, (int, float))
                and not isinstance(n.value, bool)
            ]

        with open(ca.__file__, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        recommend = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_recommend"
        )
        self.assertEqual(_numbers(recommend), [])
        envelopes = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "envelope" for t in n.targets)
        ]
        self.assertEqual(len(envelopes), 1)
        self.assertEqual(_numbers(envelopes[0].value), [])

    def test_recommend_matches_decision_matrix(self) -> None:
        from app.tools.copilot_answer import _recommend
        self.assertEqual(_recommend(4, 0.0, 0), "REPLACE")
        self.assertEqual(_recommend(0, 55.0, 0), "REPLACE")
        self.assertEqual(_recommend(0, 0.0, 30), "REPLACE")
        self.assertEqual(_recommend(2, 0.0, 0), "MONITOR")
        self.assertEqual(_recommend(0, 30.0, 0), "MONITOR")
        self.assertEqual(_recommend(1, 10.0, 4), "MAINTAIN")

    def test_budget_floor_unchanged(self) -> None:
        """Plancher 100 000 XAF : Mendong (90 000) -> 100 000 affichés."""
        from app.agent_tools import TOOL_EXECUTORS
        context = {
            "schools": [
                {
                    "school_id": 2,
                    "school_name": "Lycée de Mendong",
                    "district": "Douala",
                    "estimated_replacement_cost": 1800000.0,
                    "incident_count": 1,
                    "total_repair_cost": 180000.0,
                    "total_days_without_service": 4,
                },
            ],
            "incidents": [],
            "maintenance_logs": [],
        }
        res = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Quel budget prévoir pour Mendong ?"}, context
        )
        self.assertEqual(res["recommendation"], "MAINTAIN")
        self.assertIn("100 000", res["insight"])


if __name__ == "__main__":
    unittest.main()
