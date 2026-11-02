"""Câblage contexte IA : teams + equipment_costs traversent AgentContext.

Régression : Laravel envoyait déjà ces clés mais AgentContext (pydantic,
extra ignorés) les éliminait au model_dump() avant les outils.
"""
from __future__ import annotations

import unittest

from app.schemas import AgentContext


class AgentContextWiringTest(unittest.TestCase):
    def test_teams_and_costs_survive_dump(self) -> None:
        ctx = AgentContext(
            teams=[{"id": 1, "name": "Équipe Wouri Nord",
                    "district": "Wouri", "specialties": ["plomberie"]}],
            equipment_costs=[{"equipment_key": "pompe_immergee_750w",
                              "label": "Pompe immergée",
                              "category": "water_point",
                              "min_xaf": 63000, "max_xaf": 134500,
                              "source_name": "NKCL Market",
                              "source_url": "https://example.com"}],
        )
        dumped = ctx.model_dump()
        self.assertEqual(dumped["teams"][0]["name"], "Équipe Wouri Nord")
        self.assertEqual(dumped["equipment_costs"][0]["min_xaf"], 63000)

    def test_defaults_empty(self) -> None:
        dumped = AgentContext().model_dump()
        self.assertEqual(dumped["teams"], [])
        self.assertEqual(dumped["equipment_costs"], [])


if __name__ == "__main__":
    unittest.main()
