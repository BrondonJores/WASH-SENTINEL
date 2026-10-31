"""Contrat cartes : clés d'observation consommées par AgentCards.tsx.

Verrouille les formes exactes que les rendus frontend lisent
(school_name, action, figures objet, stats des slides...).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

_NOW = datetime.now(timezone.utc)
OLD = (_NOW - timedelta(days=10)).isoformat()
RECENT = (_NOW - timedelta(days=1)).isoformat()

SCHOOLS = [
    {"school_id": 1, "school_name": "École Publique de Bonanjo", "district": "Wouri"},
    {"school_id": 2, "school_name": "École de Nkol", "district": "Mvila"},
    {"school_id": 3, "school_name": "École Rurale de Ngok", "district": "Mvila"},
]

INCIDENTS = [
    {"id": 1, "school_id": 1, "school_name": "École Publique de Bonanjo",
     "district": "Wouri", "title": "Pompe cassée",
     "summary": "Pompe principale hors service", "status": "open",
     "urgency": "critical", "affected_students": 450,
     "reported_at": OLD, "reference_code": "WASH-001"},
    {"id": 2, "school_id": 2, "school_name": "École de Nkol",
     "district": "Mvila", "title": "Eau contaminée",
     "summary": "Eau jaunâtre au forage, suspicion contamination",
     "status": "open", "urgency": "high", "affected_students": 160,
     "reported_at": RECENT, "reference_code": "WASH-002"},
    {"id": 3, "school_id": 3, "school_name": "École Rurale de Ngok",
     "district": "Mvila", "title": "Latrines débordées",
     "summary": "Latrines débordées, risque choléra",
     "status": "open", "urgency": "high", "affected_students": 195,
     "reported_at": RECENT, "reference_code": "WASH-003"},
]

LOGS = [
    {"id": 1, "school_id": 1, "school_name": "École Publique de Bonanjo",
     "school": "École Publique de Bonanjo", "district": "Wouri",
     "action": "Remplacement du joint de pompe",
     "notes": "Remplacement du joint de pompe",
     "cost_amount": 50000, "cost": 50000,
     "date": RECENT[:10], "created_at": RECENT, "day": RECENT[:10],
     "days_without_service": 2, "incident_ref": "WASH-001"},
    {"id": 2, "school_id": 2, "school_name": "École de Nkol",
     "school": "École de Nkol", "district": "Mvila",
     "action": "Chloration du forage", "notes": "Chloration du forage",
     "cost_amount": 25000, "cost": 25000,
     "date": RECENT[:10], "created_at": RECENT, "day": RECENT[:10],
     "days_without_service": 1, "incident_ref": "WASH-002"},
]

CONTEXT = {"schools": SCHOOLS, "incidents": INCIDENTS,
           "maintenance_logs": LOGS}


class CardContractTest(unittest.TestCase):
    def test_district_alerts_keys(self) -> None:
        from app.tools.district_alerts import execute
        res = execute({}, CONTEXT)
        self.assertIn("insight", res)
        self.assertGreater(len(res.get("alerts", [])), 0)
        for key in ("school_name", "title", "action"):
            self.assertIn(key, res["alerts"][0])

    def test_epidemic_alerts_keys(self) -> None:
        from app.tools.epidemic_alerts import execute
        res = execute({}, CONTEXT)
        self.assertGreater(len(res.get("clusters", [])), 0)
        for key in ("district", "schools", "signals", "risk_level"):
            self.assertIn(key, res["clusters"][0])

    def test_maintenance_team_keys(self) -> None:
        from app.tools.maintenance_team import execute
        res = execute({}, CONTEXT)
        self.assertGreater(len(res.get("workload", [])), 0)
        for key in ("district", "open_incidents"):
            self.assertIn(key, res["workload"][0])
        self.assertGreater(len(res.get("suggested_tour", [])), 0)
        for key in ("school_name", "max_urgency"):
            self.assertIn(key, res["suggested_tour"][0])

    def test_compare_schools_keys(self) -> None:
        from app.tools.compare_schools import execute
        res = execute({"schools": ["Bonanjo", "Nkol"]}, CONTEXT)
        self.assertGreater(len(res.get("columns", [])), 0)
        for key in ("school_name", "open_incidents", "affected_students",
                    "interventions", "total_cost_XAF"):
            self.assertIn(key, res["columns"][0])
        self.assertTrue(res.get("verdict"))

    def test_copilot_answer_keys(self) -> None:
        from app.tools.copilot_answer import execute
        res = execute({"question": "Quel budget prévoir pour les réparations ?"},
                      CONTEXT)
        self.assertTrue(res.get("recommendation_label"))
        self.assertIsInstance(res.get("figures"), dict)

    def test_mission_timeline_keys(self) -> None:
        from app.tools.interventoils_mission import execute
        res = execute({"days": 30}, CONTEXT)
        self.assertGreater(len(res.get("items", [])), 0)
        for key in ("date", "school", "action", "cost"):
            self.assertIn(key, res["items"][0])
        for key in ("missions", "schools_visited", "total_cost"):
            self.assertIn(key, res.get("totals", {}))

    def test_document_briefing_keys(self) -> None:
        from app.tools.document_briefing import execute
        res = execute({"topic": "Mvila", "format": "diaporama"}, CONTEXT)
        self.assertGreater(len(res.get("sections", [])), 0)
        for key in ("title", "bullets"):
            self.assertIn(key, res["sections"][0])
        self.assertGreater(len(res.get("slides", [])), 0)
        for key in ("kind", "title", "lines", "stats"):
            self.assertIn(key, res["slides"][0])


if __name__ == "__main__":
    unittest.main()
