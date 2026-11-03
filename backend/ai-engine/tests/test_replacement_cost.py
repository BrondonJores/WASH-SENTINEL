"""Coût de remplacement sourcé : fiche école > référentiel > non communiqué.

Jamais de 1 500 000 silencieux : chaque montant affiché porte son origine
(jury : « d'après quel site ? »).
"""
from __future__ import annotations

import unittest

from app.decision_agent import DecisionAgent
from app.replacement_cost import (
    SOURCE_ECOLE,
    SOURCE_INCONNU,
    SOURCE_REFERENTIEL,
    format_source_label,
    resolve_replacement_cost,
)
from app.schemas import SchoolMaintenanceHistory


CATALOGUE = [
    {"category": "water_point", "min_xaf": 63000, "max_xaf": 134500,
     "source_name": "NKCL Market", "source_url": "https://nkcl.example/pompe"},
    {"category": "water_point", "min_xaf": 8000000, "max_xaf": 8500000,
     "source_name": "ARMP Cameroun", "source_url": "https://armp.example/ao"},
]


class ResolveReplacementCostTest(unittest.TestCase):
    def test_school_cost_wins(self) -> None:
        resolved = resolve_replacement_cost(
            {"estimated_replacement_cost": 1500000.0},
            {"equipment_costs": CATALOGUE})
        self.assertEqual(resolved.cost, 1500000.0)
        self.assertEqual(resolved.source, SOURCE_ECOLE)

    def test_zero_school_cost_uses_catalogue_median(self) -> None:
        resolved = resolve_replacement_cost(
            {"estimated_replacement_cost": 0.0},
            {"equipment_costs": CATALOGUE})
        # Milieux : 98750 et 8250000 -> médiane (2 valeurs) = moyenne.
        self.assertEqual(resolved.cost, (98750.0 + 8250000.0) / 2.0)
        self.assertEqual(resolved.source, SOURCE_REFERENTIEL)
        self.assertIn("NKCL Market", resolved.source_names)
        self.assertIn("ARMP Cameroun", resolved.source_names)
        self.assertIn("https://armp.example/ao", resolved.source_urls)

    def test_no_cost_no_catalogue_is_unknown(self) -> None:
        resolved = resolve_replacement_cost(
            {"estimated_replacement_cost": 0.0}, {"equipment_costs": []})
        self.assertIsNone(resolved.cost)
        self.assertEqual(resolved.source, SOURCE_INCONNU)

    def test_source_labels(self) -> None:
        self.assertIn("fiche école", format_source_label(SOURCE_ECOLE))
        self.assertIn("NKCL", format_source_label(
            SOURCE_REFERENTIEL, ["NKCL Market"]))
        self.assertIn("non communiqué", format_source_label(SOURCE_INCONNU))
        self.assertIn("school record", format_source_label(SOURCE_ECOLE, lang="en"))


class VerdictWithoutRatioTest(unittest.TestCase):
    def test_unknown_cost_no_ratio_no_money_claim(self) -> None:
        hist = SchoolMaintenanceHistory(
            school_id=1, school_name="E", district="D",
            estimated_replacement_cost=0.0, incident_count=1,
            total_repair_cost=50000.0, total_days_without_service=3)
        analysis = DecisionAgent.evaluate_school_equipment(hist)
        self.assertIsNone(analysis.repair_to_replacement_ratio_percent)
        self.assertNotIn("%", analysis.justification)
        self.assertIn("non communiqué", analysis.justification)

    def test_unknown_cost_still_replaces_on_frequency(self) -> None:
        hist = SchoolMaintenanceHistory(
            school_id=1, school_name="E", district="D",
            estimated_replacement_cost=0.0, incident_count=6,
            total_repair_cost=50000.0, total_days_without_service=3)
        analysis = DecisionAgent.evaluate_school_equipment(hist)
        self.assertEqual(analysis.recommendation, "REPLACE_EQUIPMENT")
        self.assertIsNone(analysis.repair_to_replacement_ratio_percent)


class AnalyzeSourcedTest(unittest.TestCase):
    def test_analyze_carries_source(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {
            "schools": [{"school_id": 1, "school_name": "Ecole A",
                         "district": "Wouri", "estimated_replacement_cost": 0.0}],
            "incidents": [],
            "equipment_costs": CATALOGUE,
        }
        res = TOOL_EXECUTORS["analyze_school"]({"school": "Ecole A"}, ctx)
        self.assertEqual(res["replacement_source"], SOURCE_REFERENTIEL)
        self.assertIsNotNone(res["estimated_replacement_cost"])
        self.assertIsNotNone(res["repair_ratio_percent"])

    def test_analyze_unknown_cost_no_ratio(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {
            "schools": [{"school_id": 1, "school_name": "Ecole A",
                         "district": "Wouri", "estimated_replacement_cost": 0.0}],
            "incidents": [],
            "equipment_costs": [],
        }
        res = TOOL_EXECUTORS["analyze_school"]({"school": "Ecole A"}, ctx)
        self.assertEqual(res["replacement_source"], SOURCE_INCONNU)
        self.assertIsNone(res["estimated_replacement_cost"])
        self.assertIsNone(res["repair_ratio_percent"])
        self.assertIn("non communiqué", res["justification"])


class PrepVerdictCitesSourceTest(unittest.TestCase):
    def test_verdict_cites_school_record(self) -> None:
        from app.tools.prepare_intervention import execute
        ctx = {
            "schools": [{"school_id": 1, "school_name": "Ecole A",
                         "district": "Wouri", "estimated_replacement_cost": 1500000.0,
                         "incident_count": 5, "total_repair_cost": 900000.0,
                         "total_days_without_service": 10}],
            "incidents": [{"id": 7, "school_id": 1, "reference_code": "WASH-1",
                           "title": "Pompe HS", "status": "open",
                           "urgency": "critical", "affected_students": 100,
                           "reported_at": "2026-11-01T08:00:00+00:00"}],
            "equipment_costs": [],
        }
        obs = execute({"incident": "WASH-1", "date_text": "demain",
                       "budget": "budget 100000 XAF", "school": "",
                       "today": "2026-11-03"}, ctx)
        self.assertIn("fiche école", obs.get("budget_verdict") or "")


if __name__ == "__main__":
    unittest.main()
