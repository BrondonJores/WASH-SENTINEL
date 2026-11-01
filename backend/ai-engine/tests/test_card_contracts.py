"""Contrat cartes : clés d'observation consommées par AgentCards.tsx.

Verrouille les formes exactes que les rendus frontend lisent
(school_name, action, figures objet, stats des slides...).
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import get_args

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

    def test_chantier_dossier_keys(self) -> None:
        from app.tools.prepare_chantier_update import execute
        res = execute({"incident": "Bonanjo", "progress_percent": 50}, CONTEXT)
        for key in ("insight", "fields", "missing", "questions", "ready"):
            self.assertIn(key, res)

    def test_saisie_assistee_keys(self) -> None:
        from app.tools.saisie_assistee import execute
        res = execute({}, CONTEXT)
        for key in ("step", "question", "options", "progress_percent"):
            self.assertIn(key, res)
        self.assertGreater(len(res["options"]), 0)

    def test_offline_queue_keys(self) -> None:
        from app.tools.offline_queue import execute
        ctx = dict(CONTEXT)
        ctx["offline_queue"] = [
            {"id": "tmp-1", "school": "École de Nkol",
             "summary": "Fuite signalée hors ligne",
             "created_at": RECENT, "status": "pending"},
        ]
        ctx["sync_status"] = {"online": False, "last_sync": OLD}
        res = execute({}, ctx)
        for key in ("insight", "pending", "count", "online"):
            self.assertIn(key, res)
        self.assertGreater(len(res["pending"]), 0)

    def test_relances_keys(self) -> None:
        from app.tools.relances_proactives import execute
        ctx = {"schools": SCHOOLS, "incidents": [INCIDENTS[0]],
               "maintenance_logs": []}
        res = execute({"days": 7}, ctx)
        self.assertGreater(len(res.get("items", [])), 0)
        for key in ("school_name", "incident_title", "reference_code",
                    "days_idle", "draft_message"):
            self.assertIn(key, res["items"][0])

    def test_observatoire_keys(self) -> None:
        from app.tools.observatoire import execute
        res = execute({}, CONTEXT)
        for key in ("incidents_open", "schools", "affected_students",
                    "critical"):
            self.assertIn(key, res.get("totals", {}))
        self.assertGreater(len(res.get("by_district", [])), 0)
        for key in ("district", "open"):
            self.assertIn(key, res["by_district"][0])
        self.assertGreater(len(res.get("by_urgency", [])), 0)
        for key in ("urgency", "count"):
            self.assertIn(key, res["by_urgency"][0])
        self.assertGreater(len(res.get("trend", [])), 0)
        for key in ("month", "count"):
            self.assertIn(key, res["trend"][0])


def _emitted_card_types() -> set[str]:
    """Tous les types émis : CARD_BUILDERS + codés en dur (loop, guidance)."""
    from app.agent_tools import PLUGIN_CARDS
    emitted: set[str] = set()
    for builders in PLUGIN_CARDS.values():
        emitted.update(builders.keys())
    app_dir = Path(__file__).resolve().parent.parent / "app"
    for source in ("agent_loop.py", "guidance.py"):
        text = (app_dir / source).read_text(encoding="utf-8")
        emitted.update(re.findall(r'type="([a-z_]+)"', text))
    return emitted


def _frontend_card_cases() -> set[str]:
    """Labels `case '...'` du switch AgentCards.tsx."""
    here = Path(__file__).resolve()
    tsx: Path | None = None
    for parent in here.parents:
        candidate = parent / "frontend" / "src" / "components" / "AgentCards.tsx"
        if candidate.is_file():
            tsx = candidate
            break
    assert tsx is not None, "AgentCards.tsx introuvable depuis les tests"
    text = tsx.read_text(encoding="utf-8")
    return set(re.findall(r"case '([a-z_]+)':", text))


class CardTypeContractTest(unittest.TestCase):
    def test_card_types_documented(self) -> None:
        from app.schemas import FRONTEND_RESERVED, CardType
        literal = set(get_args(CardType))
        self.assertGreater(len(literal), 0)
        self.assertLessEqual(set(FRONTEND_RESERVED), literal)
        emitted = _emitted_card_types()
        self.assertLessEqual(
            emitted, literal,
            f"types émis hors CardType : {sorted(emitted - literal)}")
        self.assertLessEqual(
            literal, emitted | set(FRONTEND_RESERVED),
            f"membres CardType ni émis ni réservés : "
            f"{sorted(literal - emitted - set(FRONTEND_RESERVED))}")

    def test_frontend_parity(self) -> None:
        emitted = _emitted_card_types()
        handled = _frontend_card_cases()
        self.assertLessEqual(
            emitted, handled,
            f"types backend sans case frontend : {sorted(emitted - handled)}")


class CardErrorEmptyPolicyTest(unittest.TestCase):
    def test_builders_none_on_error(self) -> None:
        from app.agent_tools import PLUGIN_CARDS
        for tool, builders in sorted(PLUGIN_CARDS.items()):
            for card_type, builder in sorted(builders.items()):
                with self.subTest(tool=tool, card=card_type):
                    self.assertIsNone(builder({"error": "x"}))

    def test_district_typed_empty(self) -> None:
        from app.tools.district_alerts import CARD_BUILDERS
        build = CARD_BUILDERS["district_alerts"]
        self.assertIsNone(build({"alerts": [], "error": "x"}))
        self.assertIsNone(build({}))
        card = build({"alerts": [], "total": 0, "district": "Douala",
                      "days": 7, "insight": "Aucune alerte."})
        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card.type, "district_alerts")
        self.assertIn("Aucune", card.title)

    def test_epidemic_typed_empty(self) -> None:
        from app.tools.epidemic_alerts import CARD_BUILDERS
        build = CARD_BUILDERS["epidemic_alerts"]
        self.assertIsNone(build({"error": "x"}))
        self.assertIsNone(build({}))
        card = build({"clusters": [], "district": None, "days": 7,
                      "signals_count": 1, "insight": "Aucun cluster."})
        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card.type, "epidemic_alerts")
        self.assertIn("Aucun", card.title)

    def test_offline_typed_empty(self) -> None:
        from app.tools.offline_queue import CARD_BUILDERS
        build = CARD_BUILDERS["offline_queue"]
        self.assertIsNone(build({"error": "x"}))
        card = build({"pending": [], "count": 0, "online": True,
                      "insight": "File vide."})
        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card.type, "offline_queue")

    def test_saisie_none_on_error_or_missing_question(self) -> None:
        from app.tools.saisie_assistee import CARD_BUILDERS
        build = CARD_BUILDERS["saisie_assistee"]
        self.assertIsNone(build({"error": "x"}))
        self.assertIsNone(build({}))
        self.assertIsNone(build({"step": "ecole"}))

    def test_loop_substitutes_guidance_on_error(self) -> None:
        from app.agent_loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)
        for name in ("district_alerts", "epidemic_alerts", "saisie_assistee",
                     "offline_queue"):
            with self.subTest(tool=name):
                cards = AgentLoop._build_cards(
                    loop, [(name, {"error": "boom"})])
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0].type, "guidance")

    def test_loop_passes_typed_empty_through(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        loop = AgentLoop.__new__(AgentLoop)
        quiet = {"schools": [], "incidents": [], "recent_incidents": []}
        for name, obs in (
            ("district_alerts", TOOL_EXECUTORS["district_alerts"]({}, quiet)),
            ("epidemic_alerts", TOOL_EXECUTORS["epidemic_alerts"]({}, quiet)),
        ):
            with self.subTest(tool=name):
                self.assertNotIn("error", obs)
                cards = AgentLoop._build_cards(loop, [(name, obs)])
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0].type, name)


class Axe7KeysContractTest(unittest.TestCase):
    def test_district_alert_rows_carry_age_days(self) -> None:
        from app.tools.district_alerts import execute
        res = execute({}, CONTEXT)
        self.assertGreater(len(res.get("alerts", [])), 0)
        for alert in res["alerts"]:
            self.assertIn("age_days", alert)

    def test_offline_pending_may_carry_urgency_category(self) -> None:
        from app.tools.offline_queue import execute
        ctx = {"offline_queue": [
            {"id": "tmp-1", "school": "École de Nkol",
             "summary": "Eau trouble", "created_at": RECENT,
             "status": "pending", "urgency": "CRITICAL",
             "category": "water_point", "affected_students": 120},
        ], "sync_status": {"online": False}}
        res = execute({}, ctx)
        row = res["pending"][0]
        for key in ("urgency", "category", "affected_students"):
            self.assertIn(key, row)
        self.assertEqual(row["urgency"], "critical")
        self.assertEqual(row["category"], "water_point")

    def test_saisie_search_and_recap_keys(self) -> None:
        from app.tools.saisie_assistee import execute
        schools = [{"school_id": i, "school_name": f"École {i:02d} de Nkol"}
                   for i in range(1, 10)]
        ctx = {"schools": schools}
        first = execute({}, ctx)
        self.assertEqual(first["total_ecoles"], 9)
        self.assertEqual(len(first["options"]), 6)
        recap = execute({
            "etape": "recap",
            "recap": {"ecole": "École 03 de Nkol",
                      "probleme": "Fuite d'eau", "urgence": "Haute"},
        }, ctx)
        self.assertEqual(recap["step"], "recap")
        for key in ("ecole_id", "urgence_level", "ready"):
            self.assertIn(key, recap["recap"] if key != "ready" else recap)
        self.assertEqual(recap["recap"]["ecole_id"], 3)
        self.assertEqual(recap["recap"]["urgence_level"], "high")
        self.assertTrue(recap["ready"])


if __name__ == "__main__":
    unittest.main()
