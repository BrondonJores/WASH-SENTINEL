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


class PrepareSchemaDisambiguationTest(unittest.TestCase):
    """Les prepare_* se distinguent par leur schéma, pas par de la prose."""

    def _fn(self, name: str) -> dict:
        from app.agent_tools import AGENT_TOOLS
        return next(t["function"] for t in AGENT_TOOLS
                    if t["function"]["name"] == name)

    def test_kind_discriminator(self) -> None:
        report = self._fn("prepare_report")["parameters"]
        incident = self._fn("prepare_incident")["parameters"]
        self.assertEqual(report["properties"]["kind"].get("const"), "report")
        self.assertEqual(incident["properties"]["kind"].get("const"), "incident")
        self.assertIn("kind", report["required"])
        self.assertIn("kind", incident["required"])

    def test_distinctive_slots_required_and_exclusive(self) -> None:
        report = self._fn("prepare_report")["parameters"]
        incident = self._fn("prepare_incident")["parameters"]
        self.assertIn("description", report["required"])
        self.assertEqual(report["not"], {"required": ["title"]})
        self.assertIn("title", incident["required"])
        self.assertEqual(incident["not"], {"required": ["description"]})

    def test_category_urgency_enums(self) -> None:
        for name in ("prepare_report", "prepare_incident"):
            props = self._fn(name)["parameters"]["properties"]
            self.assertEqual(props["category"].get("enum"),
                             ["water_point", "toilets_latrines", "handwashing", "sewage_drainage"],
                             name)
            self.assertEqual(props["urgency"].get("enum"),
                             ["low", "medium", "high", "critical"], name)

    def test_neutral_prose_and_short_description(self) -> None:
        for name in ("prepare_report", "prepare_incident", "prepare_maintenance_log"):
            fn = self._fn(name)
            for banned in ("JAMAIS", "STOP", "UNIQUEMENT", "CREATION"):
                self.assertNotIn(banned, fn["description"], name)
            short = fn.get("short_description", "")
            self.assertTrue(short, f"{name} porte short_description")
            self.assertLessEqual(len(short), 140, name)

    def test_maintenance_log_cost_documented(self) -> None:
        props = self._fn("prepare_maintenance_log")["parameters"]["properties"]
        self.assertEqual(props["cost_amount"].get("minimum"), 0)
        self.assertIn("WASH", props["incident"].get("description", ""))


class TolerantSchoolFilterTest(unittest.TestCase):
    """Filtre école tolérant : hint parasite → filtre ignoré + avertissement.

    Non-régression : le petit modèle passait « aujourd'hui » comme école, ce
    qui renvoyait items=[] en silence alors que des logs existaient.
    """

    def test_parasite_hint_today_ignores_filter(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"](
            {"date": "2026-10-31", "school": "aujourd'hui"},
            ListMaintenanceLogsTest.LOG_CONTEXT)
        self.assertEqual(res["total"], 2)
        self.assertEqual(len(res["items"]), 2)
        self.assertTrue(res["insight"].startswith(
            "École aujourd'hui non reconnue — filtre ignoré. "))
        self.assertFalse(res["is_empty"])
        self.assertEqual(res["applied_filters"],
                         {"date": "2026-10-31", "school_raw": "aujourd'hui",
                          "school_matched": False})

    def test_parasite_hint_xyz_ignores_filter(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"](
            {"date": "2026-10-31", "school": "xyz"},
            ListMaintenanceLogsTest.LOG_CONTEXT)
        self.assertEqual(res["total"], 2)
        self.assertTrue(res["insight"].startswith(
            "École xyz non reconnue — filtre ignoré. "))
        self.assertFalse(res["applied_filters"]["school_matched"])

    def test_parasite_hint_on_empty_day_warns_but_stays_honest(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"](
            {"date": "2026-10-29", "school": "xyz"},
            ListMaintenanceLogsTest.LOG_CONTEXT)
        self.assertEqual(res["total"], 0)
        self.assertTrue(res["is_empty"])
        self.assertTrue(res["insight"].startswith(
            "École xyz non reconnue — filtre ignoré. "))
        self.assertIn("Aucune intervention journalisée le 2026-10-29.",
                      res["insight"])

    def test_valid_partial_hint_still_filters(self) -> None:
        ctx = {
            "schools": [
                {"school_id": 1, "school_name": "École Publique de Bonanjo"},
                {"school_id": 3, "school_name": "École de Nkol"},
            ],
            "maintenance_logs": [
                {"id": 11, "school_name": "École Publique de Bonanjo",
                 "created_at": "2026-10-31T08:15:00+00:00"},
                {"id": 12, "school_name": "École de Nkol",
                 "created_at": "2026-10-31T14:40:00+00:00"},
            ],
        }
        res = TOOL_EXECUTORS["list_maintenance_logs"](
            {"date": "2026-10-31", "school": "nkol"}, ctx)
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["items"][0]["school_name"], "École de Nkol")
        self.assertNotIn("non reconnue", res["insight"])
        self.assertTrue(res["applied_filters"]["school_matched"])
        self.assertFalse(res["is_empty"])

    def test_reverse_substring_counts_as_match(self) -> None:
        from app.agent_tools import _school_hint_matches_known
        self.assertTrue(_school_hint_matches_known(
            "École Rurale de Ngok et environs",
            ListMaintenanceLogsTest.LOG_CONTEXT))
        self.assertFalse(_school_hint_matches_known(
            "xyz", ListMaintenanceLogsTest.LOG_CONTEXT))

    def test_absurd_or_missing_date_falls_back_to_today(self) -> None:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        ctx = {"schools": [], "maintenance_logs": [
            {"id": 1, "school_name": "E1",
             "created_at": f"{today}T07:00:00+00:00"},
            {"id": 2, "school_name": "E2",
             "created_at": "2000-01-01T07:00:00+00:00"},
        ]}
        for bad in ("aujourd'hui", "xyz", "", "2026-13-99", "31/10/2026", None):
            with self.subTest(date=bad):
                res = TOOL_EXECUTORS["list_maintenance_logs"]({"date": bad}, ctx)
                self.assertEqual(res["date"], today)
                self.assertEqual(res["total"], 1)
                self.assertEqual(res["applied_filters"]["date"], today)

    def test_echo_present_on_empty_observation(self) -> None:
        res = TOOL_EXECUTORS["list_maintenance_logs"](
            {"date": "2026-10-29"}, ListMaintenanceLogsTest.LOG_CONTEXT)
        self.assertTrue(res["is_empty"])
        self.assertEqual(res["applied_filters"],
                         {"date": "2026-10-29", "school_raw": None,
                          "school_matched": True})


class PartialSlotFillingTest(unittest.TestCase):
    """TACHE 2 : prepare_maintenance_log accepte tout sous-ensemble d'args."""

    SLOT_CONTEXT = {
        "schools": [
            {"school_id": 1, "school_name": "École Publique de Bonanjo",
             "district": "Wouri"},
        ],
        "incidents": [
            {"id": 5, "school_id": 1, "reference_code": "WASH-2026-0005",
             "title": "Pompe cassée", "status": "reported", "urgency": "high",
             "affected_students": 100},
        ],
    }

    def test_partial_incident_only(self) -> None:
        res = TOOL_EXECUTORS["prepare_maintenance_log"](
            {"incident": 5}, self.SLOT_CONTEXT)
        self.assertFalse(res["complete"])
        self.assertEqual(res["missing"], ["cost_amount"])
        self.assertEqual(len(res["questions"]), 1)
        self.assertIn("coût", res["questions"][0].lower())
        self.assertEqual(res["slots"]["incident_id"], 5)

    def test_partial_cost_only(self) -> None:
        res = TOOL_EXECUTORS["prepare_maintenance_log"](
            {"cost_amount": 50000}, self.SLOT_CONTEXT)
        self.assertFalse(res["complete"])
        self.assertEqual(res["missing"], ["incident"])
        self.assertEqual(len(res["questions"]), 1)
        self.assertIn("incident", res["questions"][0].lower())

    def test_partial_empty_returns_missing_and_two_questions(self) -> None:
        res = TOOL_EXECUTORS["prepare_maintenance_log"]({}, self.SLOT_CONTEXT)
        self.assertFalse(res["complete"])
        self.assertEqual(res["missing"], ["incident", "cost_amount"])
        self.assertEqual(len(res["questions"]), 2)
        for question in res["questions"]:
            self.assertTrue(question.strip().endswith("?"))


class RepairTrendsEnrichedTest(unittest.TestCase):
    """TACHE 4 : payload tendances enrichi, forme legacy inchangee."""

    @staticmethod
    def _ctx() -> dict:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        stamp = now.replace(day=1).isoformat()
        return {
            "schools": [
                {"school_id": 1, "school_name": "E1", "district": "Wouri"},
                {"school_id": 2, "school_name": "E2", "district": "Wouri"},
            ],
            "maintenance_logs": [
                {"school_id": 1, "repaired_at": stamp, "cost_amount": 90000,
                 "currency": "XAF", "days_without_service": 2},
                {"school_id": 2, "repaired_at": stamp, "cost_amount": 10000,
                 "currency": "XAF", "days_without_service": 1},
            ],
            "recent_incidents": [
                {"school_id": 1, "reported_at": stamp, "urgency": "critical"},
                {"school_id": 2, "reported_at": stamp, "urgency": "low"},
            ],
        }

    def test_enriched_keys_present(self) -> None:
        res = TOOL_EXECUTORS["repair_trends"](
            {"school": 1, "months": 2}, self._ctx())
        self.assertNotIn("error", res)
        self.assertIn("per_school", res)
        self.assertIn("by_urgency", res)
        self.assertIn("totals", res)
        self.assertLessEqual(len(res["per_school"]), 5)
        top = res["per_school"][0]
        self.assertIn("school_name", top)
        self.assertIn("cost", top)
        self.assertIn("incidents", top)
        self.assertEqual(
            set(res["by_urgency"]), {"critique", "haute", "moyenne", "basse"})
        self.assertEqual(res["by_urgency"]["critique"], 1)
        self.assertEqual(res["by_urgency"]["basse"], 1)
        for key in ("cost", "incidents", "days"):
            self.assertIn(key, res["totals"])

    def test_legacy_shape_unchanged(self) -> None:
        res = TOOL_EXECUTORS["repair_trends"](
            {"school": 1, "months": 2}, self._ctx())
        for key in ("school_id", "school_name", "months", "insight",
                    "labels", "datasets", "figures"):
            self.assertIn(key, res)
        self.assertEqual(res["school_id"], 1)
        self.assertEqual(res["months"], 2)
        self.assertEqual(len(res["labels"]), 2)
        self.assertEqual(len(res["datasets"]), 3)
        for key in ("total_cost", "currency", "total_incidents",
                    "total_days_lost", "avg_cost_per_month", "trend_direction"):
            self.assertIn(key, res["figures"])


class CalendarHeatmapTest(unittest.TestCase):
    """Nouveau payload calendar_heatmap : bucketing, fuseau, vide."""

    def test_bucketing_groups_same_day(self) -> None:
        from datetime import datetime, timedelta, timezone
        from app.agent_tools import build_calendar_heatmap
        try:
            from zoneinfo import ZoneInfo
            douala = ZoneInfo("Africa/Douala")
        except Exception:
            douala = timezone.utc
        stamp = datetime.now(timezone.utc).replace(
            hour=12, minute=0, second=0, microsecond=0)
        expected_day = stamp.astimezone(douala).date().isoformat()
        pool = [
            {"id": 1, "school_id": 1, "school_name": "E1",
             "reported_at": stamp.isoformat()},
            {"id": 2, "school_id": 2, "school_name": "E2",
             "reported_at": (stamp + timedelta(hours=1)).isoformat()},
        ]
        res = build_calendar_heatmap(pool, [])
        self.assertEqual(len(res["days"]), 90)
        day = next(d for d in res["days"] if d["date"] == expected_day)
        self.assertEqual(day["pannes"], 2)
        self.assertEqual(day["incidents"], 2)
        self.assertEqual(sorted(day["ecoles_touchees"]), ["E1", "E2"])
        self.assertEqual(res["total_pannes"], 2)
        dates = [d["date"] for d in res["days"]]
        self.assertEqual(dates, sorted(dates))

    def test_timezone_is_douala_civil_day(self) -> None:
        from datetime import datetime, timedelta, timezone
        from app.agent_tools import build_calendar_heatmap
        # 23h30 UTC = 00h30 le lendemain à Douala (UTC+1, sans DST).
        now = datetime(2026, 11, 1, 0, 30, tzinfo=timezone(timedelta(hours=1)))
        pool = [{"id": 9, "school_id": 1, "school_name": "E1",
                 "reported_at": "2026-10-31T23:30:00+00:00"}]
        res = build_calendar_heatmap(pool, [], now=now)
        by_date = {d["date"]: d for d in res["days"]}
        if res["timezone"] == "Africa/Douala":
            self.assertEqual(res["end"], "2026-11-01")
            self.assertEqual(by_date["2026-11-01"]["pannes"], 1)
            self.assertEqual(by_date["2026-10-31"]["pannes"], 0)
        else:  # repli UTC documenté
            self.assertTrue(res["timezone"].startswith("UTC"))
            self.assertEqual(by_date["2026-10-31"]["pannes"], 1)

    def test_empty_pool_yields_90_zero_days(self) -> None:
        from app.agent_tools import build_calendar_heatmap
        res = build_calendar_heatmap([], [])
        self.assertEqual(len(res["days"]), 90)
        self.assertEqual(res["total_pannes"], 0)
        self.assertEqual(res["total_incidents"], 0)
        for day in res["days"]:
            self.assertEqual(day["pannes"], 0)
            self.assertEqual(day["ecoles_touchees"], [])
        self.assertIn("timezone", res)
        self.assertEqual(res["window_days"], 90)


class IncidentTimelineTest(unittest.TestCase):
    """Nouveau payload timeline : ordre et fait/non-fait selon statut."""

    def test_steps_order_and_shape(self) -> None:
        from app.agent_tools import build_incident_timeline
        steps = build_incident_timeline(
            {"status": "reported", "reported_at": "2026-10-20T00:00:00Z"})
        self.assertEqual([s["etape"] for s in steps],
                         ["signale", "triage", "assigne", "en_cours", "resolu"])
        for step in steps:
            for key in ("etape", "step", "label", "date", "fait", "done"):
                self.assertIn(key, step)
        self.assertEqual(steps[0]["date"], "2026-10-20T00:00:00Z")
        self.assertTrue(all(s["date"] is None for s in steps[1:]))

    def test_done_flags_follow_status(self) -> None:
        from app.agent_tools import build_incident_timeline
        mid = build_incident_timeline({"status": "in_progress"})
        self.assertEqual([s["fait"] for s in mid],
                         [True, True, True, True, False])
        self.assertEqual([s["done"] for s in mid],
                         [True, True, True, True, False])
        done = build_incident_timeline({"status": "resolved"})
        self.assertTrue(all(s["fait"] for s in done))
        closed = build_incident_timeline({"status": "closed"})
        self.assertTrue(all(s["fait"] for s in closed))
        early = build_incident_timeline({"status": "triaged"})
        self.assertEqual([s["fait"] for s in early],
                         [True, True, False, False, False])

    def test_unknown_status_yields_only_reported(self) -> None:
        from app.agent_tools import build_incident_timeline
        steps = build_incident_timeline({"status": "bizarre"})
        self.assertEqual([s["fait"] for s in steps],
                         [True, False, False, False, False])

    def test_explain_incident_carries_timeline(self) -> None:
        res = TOOL_EXECUTORS["explain_incident"](
            {"incident_id": 5},
            {"incidents": [{"id": 5, "school_name": "E", "district": "W",
                            "title": "Pompe cassée", "category": "water_point",
                            "urgency": "critical", "status": "assigned",
                            "priority_score": 80, "affected_students": 10,
                            "summary": "x",
                            "reported_at": "2026-10-20T00:00:00Z"}]})
        self.assertNotIn("error", res)
        self.assertEqual([s["etape"] for s in res["timeline"]],
                         ["signale", "triage", "assigne", "en_cours", "resolu"])
        self.assertEqual([s["fait"] for s in res["timeline"]],
                         [True, True, True, False, False])


class BudgetCompareTest(unittest.TestCase):
    """Nouveau payload budget_compare : cumuls, top 5, parts."""

    @staticmethod
    def _ctx() -> dict:
        schools = [{"school_id": i, "school_name": f"E{i}", "district": "Wouri"}
                   for i in range(1, 8)]
        return {
            "schools": schools,
            "incidents": [
                {"id": 101, "school_id": 1, "school_name": "E1",
                 "category": "water_point", "status": "resolved",
                 "reported_at": "2026-09-01T00:00:00Z"},
                {"id": 102, "school_id": 1, "school_name": "E1",
                 "category": "toilets_latrines", "status": "resolved",
                 "reported_at": "2026-09-02T00:00:00Z"},
                {"id": 103, "school_id": 2, "school_name": "E2",
                 "category": "water_point", "status": "reported",
                 "reported_at": "2026-09-03T00:00:00Z"},
            ],
            "recent_incidents": [],
            "maintenance_logs": [
                {"school_id": 1, "incident_id": 101, "cost_amount": 60000,
                 "repaired_at": "2026-09-05T00:00:00Z"},
                {"school_id": 1, "incident_id": 102, "cost_amount": 15000,
                 "repaired_at": "2026-09-06T00:00:00Z"},
                {"school_id": 2, "incident_id": 103, "cost_amount": 5000,
                 "repaired_at": "2026-09-07T00:00:00Z"},
            ],
        }

    def test_cumuls_and_incident_counts(self) -> None:
        from app.agent_tools import build_budget_compare
        res = build_budget_compare(self._ctx())
        e1 = next(e for e in res["ecoles"] if e["school_id"] == 1)
        self.assertEqual(e1["nom"], "E1")
        self.assertEqual(e1["cumul_reparations_XAF"], 75000)
        self.assertEqual(e1["total_cost_XAF"], 75000)
        self.assertEqual(e1["nb_pannes"], 2)
        self.assertEqual(e1["incidents"], 2)
        self.assertEqual(res["currency"], "XAF")
        self.assertEqual(res["total_XAF"], 80000)

    def test_top5_sorted_desc(self) -> None:
        from app.agent_tools import build_budget_compare
        ctx = self._ctx()
        for i in range(3, 8):
            ctx["maintenance_logs"].append(
                {"school_id": i, "cost_amount": 1000 * i,
                 "repaired_at": "2026-09-08T00:00:00Z"})
        res = build_budget_compare(ctx)
        self.assertLessEqual(len(res["ecoles"]), 5)
        self.assertEqual(res["top"], 5)
        cumuls = [e["cumul_reparations_XAF"] for e in res["ecoles"]]
        self.assertEqual(cumuls, sorted(cumuls, reverse=True))
        self.assertEqual(res["ecoles"][0]["school_id"], 1)

    def test_category_shares(self) -> None:
        from app.agent_tools import build_budget_compare
        res = build_budget_compare(self._ctx())
        by_cat = res["par_categorie_XAF"]
        self.assertEqual(by_cat["water_point"], 65000)
        self.assertEqual(by_cat["toilets_latrines"], 15000)
        self.assertEqual(res["by_category_XAF"], by_cat)
        self.assertAlmostEqual(res["parts_pct"]["water_point"], 81.2, places=1)
        self.assertAlmostEqual(res["parts_pct"]["toilets_latrines"], 18.8, places=1)
        self.assertEqual(res["shares_pct"], res["parts_pct"])
        self.assertAlmostEqual(sum(res["parts_pct"].values()), 100.0, places=0)

    def test_unlinked_costs_go_to_unknown(self) -> None:
        from app.agent_tools import build_budget_compare
        ctx = self._ctx()
        ctx["maintenance_logs"].append(
            {"school_id": 1, "cost_amount": 20000,
             "repaired_at": "2026-09-09T00:00:00Z"})
        res = build_budget_compare(ctx)
        self.assertEqual(res["par_categorie_XAF"]["unknown"], 20000)


class NewPayloadsNonRegressionTest(unittest.TestCase):
    """Les payloads legacy restent intacts malgré les ajouts."""

    def test_repair_trends_legacy_plus_new(self) -> None:
        res = TOOL_EXECUTORS["repair_trends"](
            {"school": 1, "months": 2}, RepairTrendsEnrichedTest._ctx())
        for key in ("school_id", "school_name", "months", "insight",
                    "labels", "datasets", "figures", "district",
                    "per_school", "by_urgency", "totals"):
            self.assertIn(key, res)
        self.assertIn("calendar_heatmap", res)
        self.assertIn("budget_compare", res)
        self.assertEqual(len(res["calendar_heatmap"]["days"]), 90)
        self.assertIn("ecoles", res["budget_compare"])

    def test_summarize_and_explain_legacy_intact(self) -> None:
        ctx = {"incidents": [
            {"id": 5, "status": "reported", "urgency": "critical",
             "category": "water_point", "affected_students": 10,
             "school_name": "E1", "district": "W", "title": "Pompe cassée",
             "priority_score": 90, "summary": "x",
             "reported_at": "2026-10-20T00:00:00Z"},
        ]}
        district = TOOL_EXECUTORS["summarize_district"]({}, ctx)
        for key in ("open_incidents", "by_urgency", "by_category",
                    "total_affected_students", "schools_involved", "insight"):
            self.assertIn(key, district)
        incident = TOOL_EXECUTORS["explain_incident"]({"incident_id": 5}, ctx)
        for key in ("insight", "id", "school_name", "title", "category",
                    "urgency", "status", "reported_at"):
            self.assertIn(key, incident)


class RepairTrendsDistrictTest(unittest.TestCase):
    """District seul (sans école) : agrégation, pas d'erreur."""

    @staticmethod
    def _ctx() -> dict:
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).replace(day=1).isoformat()
        return {
            "schools": [
                {"school_id": 1, "school_name": "E1", "district": "Mvila"},
                {"school_id": 2, "school_name": "E2", "district": "Mvila"},
                {"school_id": 3, "school_name": "E3", "district": "Wouri"},
            ],
            "maintenance_logs": [
                {"school_id": 1, "repaired_at": stamp, "cost_amount": 90000,
                 "currency": "XAF", "days_without_service": 2},
                {"school_id": 2, "repaired_at": stamp, "cost_amount": 10000,
                 "currency": "XAF", "days_without_service": 1},
            ],
            "recent_incidents": [
                {"school_id": 1, "reported_at": stamp, "urgency": "critical"},
                {"school_id": 3, "reported_at": stamp, "urgency": "low"},
            ],
        }

    def test_district_aggregates_without_school(self) -> None:
        res = TOOL_EXECUTORS["repair_trends"](
            {"district": "Mvila", "months": 2}, self._ctx())
        self.assertNotIn("error", res)
        self.assertIsNone(res["school_id"])
        self.assertEqual(res["school_name"], "District Mvila")
        self.assertEqual(res["figures"]["total_cost"], 100000)
        self.assertEqual(res["figures"]["total_incidents"], 1)
        self.assertIn("calendar_heatmap", res)
        self.assertIn("budget_compare", res)

    def test_unknown_district_still_errors(self) -> None:
        res = TOOL_EXECUTORS["repair_trends"](
            {"district": "Nowhere", "months": 2}, self._ctx())
        self.assertIn("error", res)


class ExplainIncidentRefTest(unittest.TestCase):
    """explain_incident accepte référence et id (l'utilisateur donne la réf)."""

    @staticmethod
    def _ctx() -> dict:
        return {"incidents": [
            {"id": 7, "reference_code": "WASH-2026-QJHIPH", "title": "Latrines bouchées",
             "school_name": "Bonanjo", "status": "triaged", "urgency": "medium",
             "priority_score": 40, "affected_students": 0, "reported_at": None},
            {"id": 5, "reference_code": "WASH-2026-ZQNU8W", "title": "Fuite robinet",
             "school_name": "Nkol", "status": "reported", "urgency": "medium",
             "priority_score": 30, "affected_students": 0, "reported_at": None},
        ]}

    def test_reference_code_resolves(self) -> None:
        res = TOOL_EXECUTORS["explain_incident"](
            {"incident_id": "WASH-2026-QJHIPH"}, self._ctx())
        self.assertNotIn("error", res)
        self.assertEqual(res["id"], 7)
        self.assertIn("timeline", res)

    def test_numeric_id_still_works(self) -> None:
        res = TOOL_EXECUTORS["explain_incident"]({"incident_id": 5}, self._ctx())
        self.assertNotIn("error", res)
        self.assertEqual(res["reference_code"], "WASH-2026-ZQNU8W")

    def test_unknown_lists_choices(self) -> None:
        res = TOOL_EXECUTORS["explain_incident"]({"incident_id": "ZZZ"}, self._ctx())
        self.assertIn("error", res)
        self.assertIn("WASH-2026-QJHIPH", res["error"])


class ResolveSchoolFuzzyTest(unittest.TestCase):
    """AXE 3 : typo résolue, égalité -> None, district accentué."""

    def test_typo_resolves_best(self) -> None:
        from app.agent_tools import _resolve_school
        hit = _resolve_school(CONTEXT, "Nkole")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["school_name"], "École de Nkol")

    def test_tie_returns_none(self) -> None:
        from app.agent_tools import _resolve_school
        ctx = {"schools": [
            {"school_id": 1, "school_name": "École Alpha"},
            {"school_id": 2, "school_name": "École Beta"},
        ]}
        # "ecole" seul : les deux noms scorent à égalité -> ambigu.
        self.assertIsNone(_resolve_school(ctx, "École"))

    def test_accented_district_filter(self) -> None:
        ctx = {"schools": [
            {"school_id": 1, "school_name": "E1",
             "district": "Vallée-du-Ntem",
             "latitude": 4.0, "longitude": 9.6},
            {"school_id": 2, "school_name": "E2",
             "district": "Mvila",
             "latitude": None, "longitude": None},
        ], "incidents": []}
        res = TOOL_EXECUTORS["territory_overview"](
            {"district": "vallee-du-ntem"}, ctx)
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["schools"][0]["school_name"], "E1")
