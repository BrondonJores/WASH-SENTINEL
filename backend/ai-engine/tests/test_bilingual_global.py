"""Passe bilingue global : chaque synthèse/carte/titre respecte context lang=en.

FR par défaut (appels historiques sans lang inchangés), EN quand lang=en.
Données terrain (écoles, titres) jamais traduites : seuls les libellés UI.
"""
from __future__ import annotations

import unittest

from app.agent_loop import (
    AgentLoop,
    _annotate_period_obs,
    _summarize_analysis,
    _summarize_briefing,
    _summarize_district,
    _summarize_incidents,
    _summarize_maintenance_logs,
    _summarize_ranking,
    _summarize_territory,
    _summarize_trends,
    period_place_suffix,
    time_window_label,
)
from app.tools.document_briefing import execute as briefing_execute
from app.tools.dossier_decideur import build_dossier
from app.tools.epidemic_alerts import execute as epidemic_execute
from app.tools.interventoils_mission import execute as mission_execute
from app.tools.maintenance_team import execute as team_execute
from app.tools.observatoire import execute as observatoire_execute
from app.tools.offline_queue import execute as offline_execute
from app.tools.prepare_chantier_update import execute as chantier_execute
from app.tools.relances_proactives import execute as relances_execute
from app.tools.saisie_assistee import execute as saisie_execute


EN_CTX = {"lang": "en"}
FR_CTX = {"lang": "fr"}


def _loop() -> AgentLoop:
    return AgentLoop.__new__(AgentLoop)


class PeriodLabelsTest(unittest.TestCase):
    def test_window_labels_en(self) -> None:
        self.assertEqual(time_window_label({"preset": "today"}, "en"), "today")
        self.assertEqual(time_window_label({"preset": "last_7d"}, "en"), "the last 7 days")
        self.assertEqual(time_window_label({"preset": "today"}, "fr"), "aujourd'hui")

    def test_place_suffix_en(self) -> None:
        scope = {"scope": "district", "district": "Mvila", "schools": []}
        self.assertEqual(period_place_suffix(scope, "en"), " in the Mvila district")
        self.assertEqual(period_place_suffix(scope, "fr"), " dans le district Mvila")

    def test_annotate_uses_lang(self) -> None:
        obs_en: dict = {}
        _annotate_period_obs("rank_schools_by_need", obs_en,
                             {"preset": "today"}, 6, " at Bonanjo", "en")
        self.assertEqual(obs_en["time_window"]["label"], "today")
        obs_fr: dict = {}
        _annotate_period_obs("rank_schools_by_need", obs_fr,
                             {"preset": "today"}, 6, " à Bonanjo")
        self.assertEqual(obs_fr["time_window"]["label"], "aujourd'hui")


class LoopSummarizersBilingualTest(unittest.TestCase):
    def test_district(self) -> None:
        obs = {"open_incidents": 2, "total_affected_students": 50,
               "schools_involved": ["A", "B"],
               "by_urgency": {"critical": 1}, "lang": "en"}
        text = _summarize_district(obs)
        self.assertIn("2 open incidents", text)
        self.assertIn("Details are in the card below.", text)
        self.assertNotIn("élèves", text)

    def test_district_fr_default(self) -> None:
        text = _summarize_district({"open_incidents": 1, "schools_involved": ["A"]})
        self.assertIn("incident ouvert", text)

    def test_trends(self) -> None:
        obs = {"school_name": "Bonanjo", "months": 3, "lang": "en",
               "figures": {"total_incidents": 2, "total_cost": 5000,
                           "currency": "XAF", "trend_direction": "up"}}
        text = _summarize_trends(obs)
        self.assertIn("At Bonanjo over 3 months", text)
        self.assertIn("rising trend", text)

    def test_ranking(self) -> None:
        obs = {"lang": "en", "total": 2,
               "ranking": [{"school_name": "A", "need_score": 9.5},
                           {"school_name": "B", "need_score": 3.1}]}
        text = _summarize_ranking(obs)
        self.assertIn("2 schools need help, leading: A (score 9.5).", text)

    def test_analysis(self) -> None:
        obs = {"lang": "en", "school_name": "Ngok",
               "open_incidents": [{}, {}], "repair_ratio_percent": 62.5,
               "recommendation": "REPLACE_EQUIPMENT"}
        text = _summarize_analysis(obs)
        self.assertIn("At Ngok: 2 open breakdowns", text)
        self.assertIn("Verdict: replace the equipment.", text)

    def test_incidents_day(self) -> None:
        text = _summarize_incidents({"items": [], "total": 0,
                                     "date": "2026-11-03", "lang": "en"})
        self.assertEqual(text, "No report filed on 2026-11-03.")

    def test_logs_day(self) -> None:
        text = _summarize_maintenance_logs({"items": [], "total": 0,
                                            "date": "2026-11-03", "lang": "en"})
        self.assertEqual(text, "No intervention logged on 2026-11-03.")

    def test_territory(self) -> None:
        text = _summarize_territory({"total": 5, "open_incidents": 3,
                                     "missing_gps": ["X"], "lang": "en"})
        self.assertIn("5 geolocated schools, 3 open incidents.", text)
        self.assertIn("1 school without GPS.", text)

    def test_briefing(self) -> None:
        obs = {"total": 4, "lang": "en",
               "slides": [{"stats": [{"value": "7"}]}]}
        text = _summarize_briefing(obs)
        self.assertIn("Briefing ready: 4 slides (7 open incidents).", text)

    def test_fallback_answer_en_no_data(self) -> None:
        loop = _loop()
        text = AgentLoop._fallback_answer(loop, [], {"lang": "en", "schools": []})
        self.assertIn("I could not retrieve data", text)
        self.assertIn("Which schools need the most help?", text)

    def test_fallback_answer_fr_unchanged(self) -> None:
        loop = _loop()
        text = AgentLoop._fallback_answer(loop, [], {"schools": []})
        self.assertIn("Je n'ai pas pu récupérer de données", text)


class PluginsBilingualTest(unittest.TestCase):
    def test_dossier_en(self) -> None:
        ctx = {"lang": "en", "schools": [], "incidents": [], "maintenance_logs": []}
        built = build_dossier(None, None, None, ctx)
        report = built["report"]
        self.assertEqual(report["subject"], "Decision brief — the whole territory")
        headings = [s["heading"] for s in report["sections"]]
        self.assertEqual(headings[0], "Executive summary")
        self.assertEqual(len(headings), 6)
        self.assertIn("not disclosed", report["period"])
        self.assertIn("Scope:", report["sections"][0]["body_md"])

    def test_dossier_fr_default(self) -> None:
        built = build_dossier(None, None, None, {})
        self.assertEqual(built["report"]["subject"], "Dossier décideur — tout le territoire")

    def test_briefing_en(self) -> None:
        inc = {"status": "open", "urgency": "high", "affected_students": 20,
               "school_id": 1, "school_name": "Bonanjo", "district": "Wouri",
               "title": "Pump down", "reported_at": "2026-11-02T08:00:00+00:00"}
        ctx = dict(EN_CTX, schools=[], incidents=[inc], maintenance_logs=[])
        obs = briefing_execute({"format": "diaporama"}, ctx)
        titles = [s["title"] for s in obs["sections"]]
        self.assertEqual(titles[:4],
                         ["Summary", "Key figures", "Priorities", "Recommended actions"])
        self.assertIn("WASH brief", obs["slides"][0]["title"])
        self.assertIn("monitored school(s)", obs["insight"])

    def test_epidemic_empty_en(self) -> None:
        obs = epidemic_execute({}, dict(EN_CTX, incidents=[], schools=[]))
        self.assertIn("No health cluster detected", obs["insight"])
        self.assertEqual(obs["lang"], "en")

    def test_observatoire_en(self) -> None:
        inc = {"status": "open", "urgency": "critical", "affected_students": 10,
               "school_id": 1, "district": "Wouri"}
        obs = observatoire_execute({}, dict(EN_CTX, incidents=[inc], schools=[]))
        self.assertIn("1 open incident in 0 schools", obs["insight"])
        self.assertIn("Wouri district concentrates", obs["insight"])

    def test_relances_en(self) -> None:
        inc = {"status": "open", "district": "Wouri", "school_name": "A",
               "title": "Pump down", "reported_at": "2020-01-01T00:00:00+00:00"}
        obs = relances_execute({"days": 7}, dict(EN_CTX, incidents=[inc]))
        self.assertIn("dormant incident", obs["insight"])
        self.assertIn("following up on case", obs["items"][0]["draft_message"])

    def test_offline_en(self) -> None:
        obs = offline_execute({}, dict(EN_CTX, offline_queue=[], sync_status={"online": True}))
        self.assertIn("Offline queue empty", obs["insight"])

    def test_missions_en(self) -> None:
        obs = mission_execute({"days": 30}, dict(EN_CTX, maintenance_logs=[], schools=[]))
        self.assertIn("No field mission found over the last 30 days.", obs["insight"])

    def test_chantier_en(self) -> None:
        obs = chantier_execute({}, dict(EN_CTX, incidents=[]))
        self.assertIn("Partial site file", obs["insight"])
        self.assertIn("progress in %", obs["missing_labels"][1])
        self.assertEqual(obs["lang"], "en")

    def test_dispatch_en(self) -> None:
        obs = team_execute({}, dict(EN_CTX, incidents=[]))
        self.assertIn("No open incidents", obs["insight"])

    def test_saisie_en(self) -> None:
        ctx = dict(EN_CTX, schools=[{"school_id": 1, "school_name": "Bonanjo"}])
        obs = saisie_execute({"etape": "ecole"}, ctx)
        self.assertIn("Which school has a problem?", obs["question"])
        self.assertEqual(obs["lang"], "en")
        obs2 = saisie_execute({"etape": "probleme"}, ctx)
        self.assertIn("Water leak", obs2["options"])
        self.assertIn("What is the problem?", obs2["question"])


if __name__ == "__main__":
    unittest.main()
