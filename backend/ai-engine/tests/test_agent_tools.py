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
