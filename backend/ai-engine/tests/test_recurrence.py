"""Tests de la détection prédictive de pannes récurrentes (pur, sans LLM)."""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta

from app.recurrence_watch import (
    PREVENTIVE_ACTIONS,
    preventive_plan,
    recurrence_risk,
    watch_recurrence,
)
from app.schemas import SchoolMaintenanceHistory

NOW = date(2026, 10, 31)


def ago(days: int) -> date:
    return NOW - timedelta(days=days)


def incident(issue_type: str, days_ago: int | None, **extra) -> dict:
    payload: dict = {"issue_type": issue_type}
    if days_ago is not None:
        payload["occurred_at"] = ago(days_ago).isoformat()
    payload.update(extra)
    return payload


def healthy_school(**over) -> SchoolMaintenanceHistory:
    base = dict(
        school_id=1,
        school_name="École de la Paix",
        district="District Ouest",
        incident_count=1,
        total_repair_cost=50000.0,
        total_days_without_service=2,
    )
    base.update(over)
    return SchoolMaintenanceHistory(**base)


class EmptyHistoryTest(unittest.TestCase):
    def test_none_is_none(self) -> None:
        risk = recurrence_risk(None, NOW)
        self.assertEqual(risk["level"], "none")
        self.assertTrue(risk["reasons"])

    def test_empty_list_is_none(self) -> None:
        risk = recurrence_risk([], NOW)
        self.assertEqual(risk["level"], "none")
        self.assertTrue(risk["reasons"])

    def test_empty_aggregate_is_none(self) -> None:
        risk = recurrence_risk(healthy_school(incident_count=0), NOW)
        self.assertEqual(risk["level"], "none")
        self.assertNotIn("predicted_issue", risk)


class HealthySchoolTest(unittest.TestCase):
    def test_aggregate_healthy_is_none(self) -> None:
        risk = recurrence_risk(healthy_school(), NOW)
        self.assertEqual(risk["level"], "none")

    def test_single_incident_is_none(self) -> None:
        risk = recurrence_risk([incident("leak", 5)], NOW)
        self.assertEqual(risk["level"], "none")

    def test_old_incidents_ignored(self) -> None:
        history = [incident("leak", 100), incident("leak", 120), incident("leak", 200)]
        risk = recurrence_risk(history, NOW)
        self.assertEqual(risk["level"], "none")
        self.assertIn("hors fenêtre", " ".join(risk["reasons"]))

    def test_mixed_types_stable_is_none(self) -> None:
        history = [incident("leak", 60), incident("blockage", 10)]
        risk = recurrence_risk(history, NOW)
        self.assertEqual(risk["level"], "none")


class HighRiskTest(unittest.TestCase):
    def test_three_leaks_high_with_figures(self) -> None:
        history = [incident("leak", 80), incident("leak", 40), incident("leak", 5)]
        risk = recurrence_risk(history, NOW)
        self.assertEqual(risk["level"], "high")
        self.assertEqual(risk["predicted_issue"], "leak")
        self.assertTrue(risk.get("suggested_action"))
        text = " ".join(risk["reasons"])
        self.assertIn("3", text)  # nombre de fuites
        self.assertIn("90", text)  # fenêtre en jours

    def test_shrinking_intervals_high(self) -> None:
        # Intervalles 20 j → 10 j → 5 j : moyenne 11,7 j < 30 et en diminution.
        history = [
            incident("total_breakdown", 50),
            incident("total_breakdown", 30),
            incident("total_breakdown", 20),
            incident("total_breakdown", 15),
        ]
        risk = recurrence_risk(history, NOW)
        self.assertEqual(risk["level"], "high")
        text = " ".join(risk["reasons"])
        self.assertIn("diminution", text)
        self.assertIn("30", text)

    def test_stable_intervals_not_high(self) -> None:
        # 1 panne de chaque type, intervalles stables 30 j → 30 j : pas high.
        history = [incident("leak", 60), incident("blockage", 30), incident("other", 0)]
        risk = recurrence_risk(history, NOW)
        self.assertEqual(risk["level"], "none")


class WatchTest(unittest.TestCase):
    def test_two_failures_watch(self) -> None:
        history = [incident("blockage", 45), incident("blockage", 7)]
        risk = recurrence_risk(history, NOW)
        self.assertEqual(risk["level"], "watch")
        self.assertEqual(risk["predicted_issue"], "blockage")
        text = " ".join(risk["reasons"])
        self.assertIn("2", text)
        self.assertIn("90", text)


class AggregateCoherenceTest(unittest.TestCase):
    def test_four_incidents_high(self) -> None:
        risk = recurrence_risk(healthy_school(incident_count=4), NOW)
        self.assertEqual(risk["level"], "high")

    def test_two_incidents_watch(self) -> None:
        risk = recurrence_risk(healthy_school(incident_count=2), NOW)
        self.assertEqual(risk["level"], "watch")

    def test_thirty_days_off_high(self) -> None:
        risk = recurrence_risk(
            healthy_school(incident_count=1, total_days_without_service=30), NOW
        )
        self.assertEqual(risk["level"], "high")


class PreventivePlanTest(unittest.TestCase):
    def test_plan_coherent_per_type(self) -> None:
        for issue in PREVENTIVE_ACTIONS:
            with self.subTest(issue=issue):
                risk = {
                    "level": "high",
                    "reasons": ["r"],
                    "predicted_issue": issue,
                }
                plan = preventive_plan(risk, [])
                self.assertGreaterEqual(len(plan["actions"]), 3)
                self.assertTrue(plan["parts_hint"])
                self.assertIn(plan["urgency"], ("high", "critical"))

    def test_contamination_high_is_critical(self) -> None:
        risk = {"level": "high", "reasons": ["r"], "predicted_issue": "contamination"}
        plan = preventive_plan(risk, [])
        self.assertEqual(plan["urgency"], "critical")
        self.assertTrue(any("Chloration" in a for a in plan["actions"]))

    def test_watch_is_medium(self) -> None:
        risk = {"level": "watch", "reasons": ["r"], "predicted_issue": "leak"}
        plan = preventive_plan(risk, [])
        self.assertEqual(plan["urgency"], "medium")
        self.assertTrue(plan["parts_hint"])

    def test_none_is_routine(self) -> None:
        plan = preventive_plan({"level": "none", "reasons": []}, [])
        self.assertEqual(plan["urgency"], "low")
        self.assertTrue(plan["actions"])
        self.assertNotIn("parts_hint", plan)

    def test_issue_recovered_from_history(self) -> None:
        history = [incident("dry_well", 10), incident("dry_well", 3)]
        risk = {"level": "watch", "reasons": ["r"]}  # sans predicted_issue
        plan = preventive_plan(risk, history)
        self.assertTrue(any("puits" in a for a in plan["actions"]))


class DeterminismTest(unittest.TestCase):
    def test_same_input_same_output(self) -> None:
        history = [incident("leak", 80), incident("leak", 40), incident("leak", 5)]
        first = recurrence_risk(history, NOW)
        second = recurrence_risk(history, NOW)
        self.assertEqual(first, second)
        self.assertEqual(
            preventive_plan(first, history), preventive_plan(second, history)
        )

    def test_input_not_mutated(self) -> None:
        history = [incident("leak", 80), incident("leak", 5)]
        snapshot = copy.deepcopy(history)
        recurrence_risk(history, NOW)
        preventive_plan({"level": "watch", "reasons": []}, history)
        self.assertEqual(history, snapshot)


class CombinedHelperTest(unittest.TestCase):
    def test_watch_recurrence_shape(self) -> None:
        history = [incident("vandalism", 20), incident("vandalism", 2)]
        result = watch_recurrence(history, NOW)
        self.assertEqual(result["risk"]["level"], "watch")
        self.assertEqual(result["plan"]["urgency"], "medium")
        self.assertIn("cadenas", result["plan"]["parts_hint"])


if __name__ == "__main__":
    unittest.main()
