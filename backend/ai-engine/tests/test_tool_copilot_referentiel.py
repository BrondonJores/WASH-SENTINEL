"""copilot_answer + référentiel prix : origine du coût (ecole/referentiel/defaut).

Additif : coût école inchangé dès qu'il est renseigné ; médiane du
catalogue (point d'eau) + citation des sources quand le coût école est à 0.
"""
from __future__ import annotations

import unittest


def _catalogue() -> list:
    return [
        {"equipment_key": "pompe_immergee_750w", "category": "water_point",
         "min_xaf": 63000, "max_xaf": 134500, "source_name": "NKCL Market"},
        {"equipment_key": "forage_equipe_pmh", "category": "water_point",
         "min_xaf": 8000000, "max_xaf": 8500000, "source_name": "ARMP Cameroun"},
        {"equipment_key": "bloc_latrines_vip", "category": "toilets_latrines",
         "min_xaf": 3500000, "max_xaf": 4290000, "source_name": "MINEPAT"},
    ]


def _context(school_cost: float, with_catalogue: bool = True) -> dict:
    ctx = {
        "schools": [
            {
                "school_id": 9,
                "school_name": "École de Test",
                "district": "Wouri",
                "equipment_type": "pompe_manuelle",
                "installation_year": 2020,
                "estimated_replacement_cost": school_cost,
                "incident_count": 4,
                "total_repair_cost": 500000.0,
                "total_days_without_service": 10,
            },
        ],
        "incidents": [],
        "maintenance_logs": [],
    }
    if with_catalogue:
        ctx["equipment_costs"] = _catalogue()
    return ctx


class CopilotReferentielTest(unittest.TestCase):
    def test_cout_ecole_renseigne_reste_inchange(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Quel budget prévoir pour l'école de Test ?"},
            _context(1500000.0),
        )
        self.assertEqual(res["figures"]["estimated_replacement_cost"], 1500000.0)
        self.assertEqual(res["figures"]["replacement_source"], "ecole")
        self.assertNotIn("référentiel national", res["insight"])

    def test_cout_zero_utilise_mediane_catalogue_et_cite_sources(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Quel budget prévoir pour l'école de Test ?"},
            _context(0.0),
        )
        # Milieux water_point : (63000+134500)/2=98750,
        # (8000000+8500000)/2=8250000 -> médiane paire = 4174375.
        self.assertEqual(res["figures"]["estimated_replacement_cost"], 4174375.0)
        self.assertEqual(res["figures"]["replacement_source"], "referentiel")
        self.assertIn("référentiel national", res["insight"])
        self.assertIn("4 174 375", res["insight"])
        self.assertIn("NKCL Market", res["insight"])

    def test_cout_zero_sans_catalogue_vaut_defaut(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Quel budget prévoir pour l'école de Test ?"},
            _context(0.0, with_catalogue=False),
        )
        self.assertEqual(res["figures"]["estimated_replacement_cost"], 0.0)
        self.assertEqual(res["figures"]["replacement_source"], "defaut")
        self.assertNotIn("référentiel national", res["insight"])

    def test_repli_toutes_categories_sans_point_eau(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = _context(0.0)
        ctx["equipment_costs"] = [r for r in _catalogue() if r["category"] != "water_point"]
        res = TOOL_EXECUTORS["copilot_answer"](
            {"question": "Quel budget prévoir pour l'école de Test ?"},
            ctx,
        )
        # Un seul item : médiane = son milieu (3500000+4290000)/2.
        self.assertEqual(res["figures"]["estimated_replacement_cost"], 3895000.0)
        self.assertEqual(res["figures"]["replacement_source"], "referentiel")


if __name__ == "__main__":
    unittest.main()
