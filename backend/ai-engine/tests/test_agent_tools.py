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
        for line in actions["lines"]:
            self.assertNotIn("(s)", line)

    def test_district_filter(self) -> None:
        res = TOOL_EXECUTORS["build_briefing"]({"district": "Mvila"}, BRIEFING_CONTEXT)
        self.assertEqual(res["district"], "Mvila")
        self.assertEqual(res["slides"][0]["stats"][0]["value"], "1")

    def test_empty_context_is_honest(self) -> None:
        res = TOOL_EXECUTORS["build_briefing"]({}, {"schools": [], "incidents": []})
        self.assertEqual(res["slides"][0]["stats"][0]["value"], "0")
        self.assertIn("calme plat", res["slides"][1]["lines"][0])
        self.assertIn("surveillance", res["slides"][2]["lines"][0])


class InsightTest(unittest.TestCase):
    def test_rank_insight(self) -> None:
        ctx = {"schools": [{"school_id": 1}, {"school_id": 2}], "incidents": [
            {"school_id": 1, "status": "reported", "urgency": "critical",
             "affected_students": 100, "reported_at": None},
            {"school_id": 2, "status": "reported", "urgency": "low",
             "affected_students": 0, "reported_at": None},
        ]}
        # noms requis pour la phrase
        ctx["schools"][0]["school_name"] = "E1"
        ctx["schools"][1]["school_name"] = "E2"
        res = TOOL_EXECUTORS["rank_schools_by_need"]({}, ctx)
        self.assertIn("devance", res["insight"])
        self.assertIn("points", res["insight"])

    def test_rank_single_insight(self) -> None:
        ctx = {"schools": [{"school_id": 1, "school_name": "E1"}], "incidents": [
            {"school_id": 1, "status": "reported", "urgency": "high",
             "affected_students": 10, "reported_at": None}]}
        res = TOOL_EXECUTORS["rank_schools_by_need"]({}, ctx)
        self.assertIn("seule école", res["insight"])

    def test_trends_insight(self) -> None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        first = now.replace(day=1)
        prev = (first - timedelta(days=1)).replace(day=1)
        ctx = {"schools": [{"school_id": 1, "school_name": "E1"}],
               "maintenance_logs": [
                   {"school_id": 1, "repaired_at": first.isoformat(),
                    "cost_amount": 90000, "currency": "XAF", "days_without_service": 2},
                   {"school_id": 1, "repaired_at": prev.isoformat(),
                    "cost_amount": 10000, "currency": "XAF", "days_without_service": 0}],
               "recent_incidents": []}
        res = TOOL_EXECUTORS["repair_trends"]({"school": 1, "months": 2}, ctx)
        self.assertIn("90 %", res["insight"])
        self.assertIn("concentrés en", res["insight"])

    def test_district_insight(self) -> None:
        ctx = {"incidents": [
            {"status": "reported", "urgency": "critical", "category": "water_point",
             "affected_students": 10, "school_name": "E1"},
            {"status": "reported", "urgency": "high", "category": "water_point",
             "affected_students": 5, "school_name": "E1"},
            {"status": "reported", "urgency": "low", "category": "toilets_latrines",
             "affected_students": 0, "school_name": "E2"},
        ]}
        res = TOOL_EXECUTORS["summarize_district"]({}, ctx)
        self.assertIn("point d'eau", res["insight"])
        self.assertIn("2 incidents", res["insight"])

    def test_incident_insight(self) -> None:
        ctx = {"incidents": [{"id": 5, "school_name": "E", "district": "W",
                              "title": "Pompe cassée", "category": "water_point",
                              "urgency": "critical", "status": "triaged",
                              "priority_score": 94, "affected_students": 450,
                              "summary": "x", "reported_at": "2026-10-20T00:00:00Z"}]}
        res = TOOL_EXECUTORS["explain_incident"]({"incident_id": 5}, ctx)
        self.assertIn("94,0/100", res["insight"])
        self.assertIn("octobre", res["insight"])

    def test_territory_insight(self) -> None:
        res = TOOL_EXECUTORS["territory_overview"]({}, TERRITORY_CONTEXT)
        self.assertIn("1 urgence critique", res["insight"])


class DistrictInsightTest(unittest.TestCase):
    """Le résumé du district ne dit plus « sur 3 » quand tout est homogène."""

    def test_all_same_category(self) -> None:
        from app.agent_tools import tool_summarize_district
        obs = tool_summarize_district({}, {
            "incidents": [
                {"urgency": "critical", "category": "water_point",
                 "school_name": "A", "affected_students": 1, "status": "reported"},
                {"urgency": "high", "category": "water_point",
                 "school_name": "B", "affected_students": 2, "status": "reported"},
            ],
        })
        self.assertIn("Tous les 2 incidents ouverts", obs["insight"])

    def test_mixed_categories(self) -> None:
        from app.agent_tools import tool_summarize_district
        obs = tool_summarize_district({}, {
            "incidents": [
                {"urgency": "critical", "category": "water_point",
                 "school_name": "A", "affected_students": 1, "status": "reported"},
                {"urgency": "high", "category": "water_point",
                 "school_name": "B", "affected_students": 2, "status": "reported"},
                {"urgency": "low", "category": "toilets_latrines",
                 "school_name": "C", "affected_students": 3, "status": "reported"},
            ],
        })
        self.assertIn("sur 3 au total", obs["insight"])


class ListMaintenanceLogsTest(unittest.TestCase):
    """list_maintenance_logs : lecture seule des interventions déjà réalisées."""

    LOG_CONTEXT = {
        "schools": [
            {"school_id": 1, "school_name": "École Publique de Bonanjo", "district": "Wouri"},
            {"school_id": 2, "school_name": "École Rurale de Ngok", "district": "Mvila"},
        ],
        "maintenance_logs": [
            {"id": 11, "incident_id": 5, "incident_ref": "WASH-2026-0005",
             "incident_title": "Pompe cassée", "school_name": "École Publique de Bonanjo",
             "cost_amount": 50000.0, "notes": "Joint remplacé",
             "created_at": "2026-10-31T08:15:00+00:00"},
            {"id": 12, "incident_id": 6, "incident_ref": "WASH-2026-0006",
             "incident_title": "Fuite robinet", "school_name": "École Rurale de Ngok",
             "cost_amount": 12000.0, "notes": "Robinet changé",
             "created_at": "2026-10-31T14:40:00+00:00"},
            {"id": 13, "incident_id": 7, "incident_ref": "WASH-2026-0007",
             "incident_title": "Dalle latrines", "school_name": "École Rurale de Ngok",
             "cost_amount": 80000.0, "notes": "Dalle refaite",
             "created_at": "2026-10-30T09:00:00+00:00"},
        ],
    }

    def test_filters_by_date_prefix(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"]({"date": "2026-10-31"}, self.LOG_CONTEXT)
        self.assertEqual(res["total"], 2)
        self.assertEqual(len(res["items"]), 2)
        self.assertIn("2 interventions journalisées", res["insight"])

    def test_empty_day_is_honest(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"]({"date": "2026-10-29"}, self.LOG_CONTEXT)
        self.assertEqual(res["items"], [])
        self.assertEqual(res["insight"], "Aucune intervention journalisée le 2026-10-29.")

    def test_school_filter_matches_name_fragment(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"](
            {"date": "2026-10-31", "school": "Ngok"}, self.LOG_CONTEXT)
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["items"][0]["school_name"], "École Rurale de Ngok")

    def test_limit_caps_items_but_keeps_total(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"](
            {"date": "2026-10-31", "limit": 1}, self.LOG_CONTEXT)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["total"], 2)

    def test_default_date_is_today(self) -> None:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        ctx = {"schools": [], "maintenance_logs": [
            {"id": 1, "school_name": "E1", "created_at": f"{today}T07:00:00+00:00"},
            {"id": 2, "school_name": "E2", "created_at": "2000-01-01T07:00:00+00:00"},
        ]}
        res = TOOL_EXECUTORS["list_maintenance_logs"]({}, ctx)
        self.assertEqual(res["date"], today)
        self.assertEqual(res["total"], 1)

    def test_registered_with_read_only_description(self) -> None:
        from app.agent_tools import AGENT_TOOLS
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        self.assertIn("list_maintenance_logs", names)
        desc = next(t["function"]["description"] for t in AGENT_TOOLS
                    if t["function"]["name"] == "list_maintenance_logs")
        self.assertIn("lecture seule", desc.lower())
        self.assertIn("interventions passées", desc)
        self.assertIn("Exemple", desc)


class PrepareDescriptionsTest(unittest.TestCase):
    """Les prepare_* affichent une clause négative : JAMAIS pour lister/consulter."""

    def test_negative_clause_everywhere(self) -> None:
        from app.agent_tools import AGENT_TOOLS
        by_name = {t["function"]["name"]: t["function"]["description"] for t in AGENT_TOOLS}
        for name in ("prepare_incident", "prepare_report", "prepare_maintenance_log"):
            desc = by_name[name]
            self.assertIn("JAMAIS", desc, name)
            self.assertIn("lister", desc, name)
            self.assertIn("list_maintenance_logs", desc, name)
            self.assertIn("Exemple", desc, name)

    def test_prepare_incident_requires_creation_intent(self) -> None:
        from app.agent_tools import AGENT_TOOLS
        desc = next(t["function"]["description"] for t in AGENT_TOOLS
                    if t["function"]["name"] == "prepare_incident")
        self.assertIn("CREATION", desc)
        self.assertIn("UNIQUEMENT", desc)
