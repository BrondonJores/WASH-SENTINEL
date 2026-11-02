"""Cohérence des graphiques agent : non-régression sur données réelles constatées.

Couvre les 4 incohérences prouvées (contexte mimant le vrai contexte
Laravel : incidents ouverts seuls dans "incidents", snapshots récents
minimaux, journaux liés à des incidents résolus) :
  1. budget_compare : les 935 000 XAF (Nyo 505K + Libermann 430K) sur
     incidents résolus ne doivent plus tomber en bucket "unknown".
  2. heatmap == tendances sur fixture commune (même pool dédupliqué,
     même périmètre école/district).
  3. privation réelle (ancienneté incident ouvert) affichée même quand
     les journaux consignent 0 jour.
  4. élèves affectés unifiés : dispatch (tournée) et synthèse partagent
     la règle max-par-école (clés *_max), sommes legacy inchangées.

Lancer depuis backend/ai-engine : python3 -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.agent_tools import TOOL_EXECUTORS, build_budget_compare


def _noon(days_ago: int) -> str:
    """Horodatage à midi UTC : loin des frontières jour/mois (anti-flaky)."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(
        hour=12, minute=0, second=0, microsecond=0).isoformat()


class BudgetResolvedCategoriesTest(unittest.TestCase):
    """BUG 1 : coûts sur incidents résolus ventilés, unknown vide."""

    @staticmethod
    def _ctx() -> dict:
        # Contexte réel : "incidents" = ouverts seuls ; "recent_incidents" =
        # snapshots minimaux SANS catégorie (ancien format Laravel) ;
        # journaux liés aux incidents résolus #13 (Nyo) et #6 (Libermann).
        return {
            "schools": [
                {"school_id": 8, "school_name": "École de Nyo",
                 "district": "Sanaga-Maritime"},
                {"school_id": 2, "school_name": "Collège Libermann",
                 "district": "Wouri"},
            ],
            "incidents": [
                {"id": 21, "school_id": 8, "school_name": "École de Nyo",
                 "category": "sewage_drainage", "status": "reported",
                 "reported_at": _noon(9)},
            ],
            "recent_incidents": [
                {"id": 13, "school_id": 8, "reported_at": _noon(65)},
                {"id": 6, "school_id": 2, "reported_at": _noon(40)},
            ],
            "maintenance_logs": [
                {"school_id": 8, "incident_id": 13, "cost_amount": 505000,
                 "repaired_at": _noon(9)},
                {"school_id": 2, "incident_id": 6, "cost_amount": 430000,
                 "repaired_at": _noon(5)},
            ],
            # Map Laravel (clés chaînes comme après round-trip JSON).
            "incident_categories": {"13": "water_point",
                                    "6": "toilets_latrines"},
        }

    def test_unknown_empty_when_categories_resolved(self) -> None:
        res = build_budget_compare(self._ctx())
        by_cat = res["par_categorie_XAF"]
        self.assertNotIn("unknown", by_cat)
        self.assertEqual(by_cat["water_point"], 505000)
        self.assertEqual(by_cat["toilets_latrines"], 430000)
        self.assertEqual(res["total_XAF"], 935000)

    def test_log_category_fallback_without_map(self) -> None:
        # Sans map (ancien contexte) mais catégorie portée par les logs :
        # même ventilation, zéro régression du cas nominal.
        ctx = self._ctx()
        del ctx["incident_categories"]
        ctx["maintenance_logs"][0]["category"] = "water_point"
        ctx["maintenance_logs"][1]["category"] = "toilets_latrines"
        res = build_budget_compare(ctx)
        self.assertNotIn("unknown", res["par_categorie_XAF"])
        self.assertEqual(res["par_categorie_XAF"]["water_point"], 505000)
        self.assertEqual(res["par_categorie_XAF"]["toilets_latrines"], 430000)

    def test_pool_category_still_wins_nominal(self) -> None:
        # Cas nominal historique : incident du pool avec catégorie.
        ctx = self._ctx()
        del ctx["incident_categories"]
        ctx["recent_incidents"] = [
            {"id": 13, "school_id": 8, "category": "water_point",
             "reported_at": _noon(65)},
            {"id": 6, "school_id": 2, "category": "toilets_latrines",
             "reported_at": _noon(40)},
        ]
        res = build_budget_compare(ctx)
        self.assertNotIn("unknown", res["par_categorie_XAF"])


class HeatmapTrendsAlignmentTest(unittest.TestCase):
    """INCOHÉRENCE 2 : heatmap et tendances comptent les mêmes pannes."""

    @staticmethod
    def _ctx() -> dict:
        return {
            "schools": [
                {"school_id": 4, "school_name": "École Rurale de Ngok",
                 "district": "Mvila"},
                {"school_id": 5, "school_name": "École de Nkol",
                 "district": "Mvila"},
            ],
            "incidents": [
                # Ngok : 1 ouvert récent (pool "incidents").
                {"id": 31, "school_id": 4, "school_name": "École Rurale de Ngok",
                 "status": "reported", "urgency": "high",
                 "reported_at": _noon(10)},
                # Nkol : 5 pannes qui NE doivent pas polluer Ngok.
                *[{"id": 100 + k, "school_id": 5, "status": "reported",
                    "urgency": "low", "reported_at": _noon(10 + k)}
                   for k in range(5)],
            ],
            "recent_incidents": [
                # Ngok : 1 snapshot récent (pool "recent_incidents").
                {"id": 32, "school_id": 4, "reported_at": _noon(20)},
            ],
            "maintenance_logs": [],
        }

    def test_heatmap_equals_trends_on_common_fixture(self) -> None:
        res = TOOL_EXECUTORS["repair_trends"](
            {"school": "Ngok", "months": 3}, self._ctx())
        self.assertNotIn("error", res)
        self.assertEqual(res["figures"]["total_incidents"], 2)
        self.assertEqual(res["calendar_heatmap"]["total_pannes"], 2)
        self.assertEqual(res["calendar_heatmap"]["total_incidents"], 2)
        self.assertEqual(res["calendar_heatmap"]["scope"],
                         "École Rurale de Ngok")

    def test_district_mode_shares_scope(self) -> None:
        res = TOOL_EXECUTORS["repair_trends"](
            {"district": "Mvila", "months": 3}, self._ctx())
        self.assertNotIn("error", res)
        # 2 (Ngok) + 5 (Nkol), des deux côtés.
        self.assertEqual(res["figures"]["total_incidents"], 7)
        self.assertEqual(res["calendar_heatmap"]["total_pannes"], 7)
        self.assertEqual(res["calendar_heatmap"]["scope"], "District Mvila")


class ServiceDisruptionTest(unittest.TestCase):
    """INCOHÉRENCE 3 : privation réelle affichée même à 0 jour consigné."""

    def test_24_days_disruption_shown(self) -> None:
        reported = (datetime.now(timezone.utc)
                    - timedelta(days=24)).isoformat()
        ctx = {
            "schools": [{"school_id": 4, "school_name": "École Rurale de Ngok",
                         "district": "Mvila"}],
            "incidents": [
                {"id": 31, "school_id": 4, "school_name": "École Rurale de Ngok",
                 "title": "Forage à sec", "status": "reported",
                 "urgency": "high", "reported_at": reported},
            ],
            "recent_incidents": [],
            "maintenance_logs": [],
        }
        res = TOOL_EXECUTORS["repair_trends"](
            {"school": "Ngok", "months": 3}, ctx)
        self.assertNotIn("error", res)
        self.assertEqual(res["figures"]["total_days_lost"], 0)
        self.assertEqual(res["figures"]["service_disruption_days"], 24)
        self.assertEqual(res["figures"]["service_disruption_since"], reported)
        self.assertIn("24 jours", res["insight"])
        self.assertIn("Forage à sec", res["insight"])
        # Libellé explicite : le dataset reste repérable (mot-clé "jour").
        labels = [d["label"] for d in res["datasets"]]
        self.assertTrue(any("consign" in label.lower() for label in labels))
        self.assertTrue(any("jour" in label.lower() for label in labels))

    def test_no_disruption_sentence_when_logs_cover(self) -> None:
        ctx = {
            "schools": [{"school_id": 4, "school_name": "École Rurale de Ngok",
                         "district": "Mvila"}],
            "incidents": [
                {"id": 31, "school_id": 4, "status": "reported",
                 "title": "Fuite", "reported_at": _noon(2)},
            ],
            "recent_incidents": [],
            "maintenance_logs": [
                {"school_id": 4, "repaired_at": _noon(1), "cost_amount": 1000,
                 "days_without_service": 5},
            ],
        }
        res = TOOL_EXECUTORS["repair_trends"](
            {"school": "Ngok", "months": 3}, ctx)
        self.assertNotIn("error", res)
        self.assertNotIn("Privation réelle", res["insight"])


class AffectedStudentsUnifiedTest(unittest.TestCase):
    """INCOHÉRENCE 4 : dispatch et synthèse partagent le max par école."""

    @staticmethod
    def _ctx() -> dict:
        incidents = [
            {"id": 40 + k, "school_id": 1,
             "school_name": "École Publique de Bonanjo", "district": "Wouri",
             "title": f"Panne {k}", "status": "reported", "urgency": "high",
             "affected_students": n, "reported_at": _noon(3)}
            for k, n in enumerate([450, 50, 40, 30, 30])
        ]
        return {
            "schools": [{"school_id": 1,
                         "school_name": "École Publique de Bonanjo",
                         "district": "Wouri"}],
            "incidents": incidents,
            "maintenance_logs": [],
        }

    def test_bonanjo_unified(self) -> None:
        ctx = self._ctx()
        dispatch = TOOL_EXECUTORS["maintenance_team"]({}, ctx)
        synthese = TOOL_EXECUTORS["summarize_district"]({}, ctx)
        tour = next(s for s in dispatch["suggested_tour"]
                    if s["school_id"] == 1)
        # Sommes legacy inchangées (600 = 450+50+40+30+30).
        self.assertEqual(tour["affected_students"], 600)
        self.assertEqual(synthese["total_affected_students"], 600)
        # Valeur unifiée partagée : max par école = 450, des deux côtés.
        self.assertEqual(tour["affected_students_max"], 450)
        self.assertEqual(synthese["total_affected_students_max"], 450)
        self.assertEqual(tour["affected_students_max"],
                         synthese["total_affected_students_max"])
        by_d = {w["district"]: w for w in dispatch["workload"]}
        self.assertEqual(by_d["Wouri"]["affected_students_max"], 450)

    def test_unified_keys_across_displays(self) -> None:
        ctx = self._ctx()
        compare = TOOL_EXECUTORS["compare_schools"](
            {"schools": ["Bonanjo", "Bonanjo", "X"]}, ctx)
        # Une seule école connue : comparaison impossible, mais la règle
        # max se vérifie sur les autres affichages.
        self.assertIn("error", compare)
        ranking = TOOL_EXECUTORS["rank_schools_by_need"]({}, ctx)
        self.assertEqual(ranking["ranking"][0]["affected_students_max"], 450)
        observatoire = TOOL_EXECUTORS["observatoire"]({}, ctx)
        self.assertEqual(
            observatoire["totals"]["affected_students_max"], 450)
        briefing = TOOL_EXECUTORS["build_briefing"]({"district": "Wouri"}, ctx)
        self.assertEqual(briefing["affected_students_max"], 450)
        analysis = TOOL_EXECUTORS["analyze_school"]({"school": "Bonanjo"}, ctx)
        self.assertEqual(analysis["affected_students_max"], 450)


if __name__ == "__main__":
    unittest.main()
