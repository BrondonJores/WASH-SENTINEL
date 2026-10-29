"""Régression agent : analyze_school doit résoudre un nom approximatif.

Contexte : le modèle ne connaît jamais les ids internes. Quand l'utilisateur
dit « l'école de Ngok », l'outil doit retrouver « École Rurale de Ngok » seul,
au lieu de pousser le modèle à réclamer des précisions.

Lancer depuis backend/ai-engine : python3 -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest

from app.agent_tools import TOOL_EXECUTORS

CONTEXT = {
    "schools": [
        {
            "school_id": 1,
            "school_name": "École Publique de Bonanjo",
            "district": "Wouri",
            "equipment_type": "pompe_manuelle",
            "installation_year": 2015,
            "estimated_replacement_cost": 1500000.0,
            "incident_count": 2,
            "total_repair_cost": 450000.0,
            "total_days_without_service": 5,
        },
        {
            "school_id": 2,
            "school_name": "École Rurale de Ngok",
            "district": "Mvila",
            "equipment_type": "pompe_manuelle",
            "installation_year": 2010,
            "estimated_replacement_cost": 1500000.0,
            "incident_count": 4,
            "total_repair_cost": 900000.0,
            "total_days_without_service": 22,
        },
        {
            "school_id": 3,
            "school_name": "École de Nkol",
            "district": "Mvila",
            "equipment_type": "forage_solaire",
            "installation_year": 2022,
            "estimated_replacement_cost": 2500000.0,
            "incident_count": 1,
            "total_repair_cost": 80000.0,
            "total_days_without_service": 12,
        },
    ],
    "incidents": [],
}


class AnalyzeSchoolTest(unittest.TestCase):
    def test_fuzzy_name_resolves(self) -> None:
        result = TOOL_EXECUTORS["analyze_school"]({"school": "Ngok"}, CONTEXT)
        self.assertNotIn("error", result)
        self.assertEqual(result["school_name"], "École Rurale de Ngok")
        self.assertIn("repair_ratio_percent", result)
        self.assertIn("recommendation", result)

    def test_numeric_id_still_accepted(self) -> None:
        result = TOOL_EXECUTORS["analyze_school"]({"school": 2}, CONTEXT)
        self.assertNotIn("error", result)
        self.assertEqual(result["school_id"], 2)

    def test_unknown_school_guides_retry(self) -> None:
        result = TOOL_EXECUTORS["analyze_school"]({"school": "XYZ"}, CONTEXT)
        self.assertIn("error", result)
        self.assertIn("École Rurale de Ngok", result["error"])


if __name__ == "__main__":
    unittest.main()


TERRITORY_CONTEXT = {
    "schools": [
        {"school_id": 1, "school_name": "E1", "district": "Wouri",
         "latitude": 4.0, "longitude": 9.6},
        {"school_id": 2, "school_name": "E2", "district": "Mvila",
         "latitude": None, "longitude": None},
        {"school_id": 3, "school_name": "E3", "district": "Wouri", "lat": 4.1, "lng": 9.7},
    ],
    "incidents": [
        {"id": 1, "school_id": 1, "status": "reported",
         "urgency": "critical", "affected_students": 100},
        {"id": 2, "school_id": 1, "status": "resolved",
         "urgency": "low", "affected_students": 5},
        {"id": 3, "school_id": 3, "status": "in_progress",
         "urgency": "medium", "affected_students": 20},
    ],
}


class TerritoryOverviewTest(unittest.TestCase):
    def test_points_and_missing(self) -> None:
        res = TOOL_EXECUTORS["territory_overview"]({}, TERRITORY_CONTEXT)
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["missing_gps"], ["E2"])
        e1 = next(s for s in res["schools"] if s["school_id"] == 1)
        self.assertEqual(e1["open_incidents"], 1)
        self.assertEqual(e1["top_urgency"], "critical")
        self.assertEqual(e1["affected_students"], 100)

    def test_district_filter_case_insensitive(self) -> None:
        res = TOOL_EXECUTORS["territory_overview"]({"district": "mVILA"}, TERRITORY_CONTEXT)
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["missing_gps"], ["E2"])


BRIEFING_CONTEXT = {
    "schools": [
        {"school_id": 1, "school_name": "E1", "district": "Wouri"},
        {"school_id": 2, "school_name": "E2", "district": "Mvila"},
    ],
    "incidents": [
        {"id": 1, "school_id": 1, "school_name": "E1", "district": "Wouri",
         "title": "Pompe cassée", "status": "reported", "urgency": "critical",
         "affected_students": 450, "reported_at": "2026-09-01T00:00:00Z"},
        {"id": 2, "school_id": 2, "school_name": "E2", "district": "Mvila",
         "title": "Fuite", "status": "in_progress", "urgency": "medium",
         "affected_students": 20, "reported_at": "2026-10-28T00:00:00Z"},
    ],
}


class BuildBriefingTest(unittest.TestCase):
    def test_deck_structure(self) -> None:
        res = TOOL_EXECUTORS["build_briefing"]({}, BRIEFING_CONTEXT)
        self.assertEqual(res["total"], 3)
        cover, prio, actions = res["slides"]
        self.assertEqual(cover["kind"], "cover")
        self.assertEqual(len(cover["stats"]), 3)
        self.assertIn("E1", prio["lines"][0])
        self.assertIn("critique", prio["lines"][0])
        self.assertTrue(any("critique" in a for a in actions["lines"]))
        self.assertTrue(any("7 jours" in a for a in actions["lines"]))

    def test_district_filter(self) -> None:
        res = TOOL_EXECUTORS["build_briefing"]({"district": "Mvila"}, BRIEFING_CONTEXT)
        self.assertEqual(res["district"], "Mvila")
        self.assertEqual(res["slides"][0]["stats"][0]["value"], "1")

    def test_empty_context_is_honest(self) -> None:
        res = TOOL_EXECUTORS["build_briefing"]({}, {"schools": [], "incidents": []})
        self.assertEqual(res["slides"][0]["stats"][0]["value"], "0")
        self.assertIn("calme plat", res["slides"][1]["lines"][0])
        self.assertIn("surveillance", res["slides"][2]["lines"][0])
