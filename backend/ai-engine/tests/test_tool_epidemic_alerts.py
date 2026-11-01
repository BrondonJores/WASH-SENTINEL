"""Plugin epidemic_alerts : cluster multi-écoles, routage, carte, anti-collision."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

try:
    from tests.test_prompt_eval import GOLDEN_CASES, ROUTING_CASES
except ImportError:  # discover ajoute tests/ au path
    from test_prompt_eval import GOLDEN_CASES, ROUTING_CASES  # type: ignore[no-redef]


def _incident(iid: int, school_id: int, school: str, district: str,
              title: str, summary: str = "", days_ago: int = 1,
              issue_type: str = "other") -> dict:
    seen = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"id": iid, "school_id": school_id, "school_name": school,
            "district": district, "title": title, "summary": summary or title,
            "issue_type": issue_type, "reported_at": seen}


def _cluster_context() -> dict:
    return {"incidents": [
        _incident(1, 11, "École de Bonanjo", "Wouri",
                  "Eau jaune et trouble au robinet de la cour"),
        _incident(2, 12, "École de Ngok", "Wouri",
                  "Enfants malades, suspicion de contamination de l'eau"),
        _incident(3, 21, "École de Mendong", "Mvila",
                  "Pompe manuelle cassée"),
    ]}


class EpidemicAlertsExecuteTest(unittest.TestCase):
    def test_cluster_detected_two_schools_same_district(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["epidemic_alerts"]({}, _cluster_context())
        self.assertIn("insight", res)
        self.assertNotIn("error", res)
        self.assertEqual(len(res["clusters"]), 1)
        cluster = res["clusters"][0]
        self.assertEqual(cluster["district"], "Wouri")
        self.assertEqual(cluster["school_count"], 2)
        self.assertEqual(cluster["incident_count"], 2)
        self.assertIn("Wouri", res["insight"])

    def test_isolated_incident_returns_typed_empty(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {"incidents": [
            _incident(1, 11, "École de Bonanjo", "Wouri",
                      "Eau jaune au robinet"),
        ]}
        res = TOOL_EXECUTORS["epidemic_alerts"]({}, ctx)
        # Vide valide (AXE 7 / P1b) : pas d'erreur, carte typée vide.
        self.assertNotIn("error", res)
        self.assertEqual(res["clusters"], [])
        self.assertIn("Aucun cluster", res["insight"])
        # Même signal, districts différents -> pas de cluster.
        ctx2 = {"incidents": [
            _incident(1, 11, "École de Bonanjo", "Wouri", "Eau jaune"),
            _incident(2, 21, "École de Mendong", "Mvila", "Eau jaune"),
        ]}
        res2 = TOOL_EXECUTORS["epidemic_alerts"]({}, ctx2)
        self.assertNotIn("error", res2)
        self.assertEqual(res2["clusters"], [])

    def test_missing_pools_returns_error(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        run = TOOL_EXECUTORS["epidemic_alerts"]
        res = run({}, {})
        self.assertIn("error", res)
        self.assertIn("donnée", res["error"].lower())

    def test_dateless_signals_kept_prudent(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        first = _incident(1, 11, "École de Bonanjo", "Wouri",
                          "Eau jaune et trouble au robinet")
        second = _incident(2, 12, "École de Ngok", "Wouri",
                           "Suspicion de contamination de l'eau")
        del first["reported_at"]
        del second["reported_at"]
        res = TOOL_EXECUTORS["epidemic_alerts"](
            {}, {"incidents": [first, second]})
        self.assertNotIn("error", res)
        self.assertEqual(len(res["clusters"]), 1)
        self.assertEqual(res["clusters"][0]["school_count"], 2)

    def test_district_filter_and_days_window(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        run = TOOL_EXECUTORS["epidemic_alerts"]
        ctx = _cluster_context()
        res = run({"district": "wouri"}, ctx)
        self.assertEqual(len(res["clusters"]), 1)
        mvil = run({"district": "Mvila"}, ctx)
        self.assertNotIn("error", mvil)
        self.assertEqual(mvil["clusters"], [])
        # Fenêtre : signaux vieux de 30 j exclus par défaut (7 j).
        old = {"incidents": [
            _incident(1, 11, "École A", "Wouri", "Eau jaune", days_ago=30),
            _incident(2, 12, "École B", "Wouri", "Eau trouble", days_ago=30),
        ]}
        self.assertEqual(run({}, old)["clusters"], [])
        self.assertEqual(len(run({"days": 60}, old)["clusters"]), 1)

    def test_deterministic_offline(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        run = TOOL_EXECUTORS["epidemic_alerts"]
        ctx = _cluster_context()
        self.assertEqual(run({}, ctx), run({}, ctx))
        self.assertEqual(run({"district": "Wouri"}, ctx),
                         run({"district": "Wouri"}, ctx))


class EpidemicAlertsRoutingTest(unittest.TestCase):
    def test_discovered_and_merged(self) -> None:
        from app.agent_tools import AGENT_TOOLS, PLUGIN_HINTS, TOOL_EXECUTORS
        names = [t.get("function", {}).get("name") for t in AGENT_TOOLS]
        self.assertIn("epidemic_alerts", names)
        self.assertIn("epidemic_alerts", TOOL_EXECUTORS)
        self.assertIn("epidemic_alerts", PLUGIN_HINTS)

    def test_routes_epidemic_question_to_list(self) -> None:
        from app.agent_loop import READ_TOOLS, route_intent, tools_for_intent
        self.assertEqual(
            route_intent("Y a-t-il un risque d'épidémie de choléra à Douala ?"),
            "list")
        self.assertEqual(route_intent("Contamination de l'eau à Bonanjo ?"),
                         "list")
        names = [t.get("function", {}).get("name")
                 for t in tools_for_intent("list")]
        self.assertIn("epidemic_alerts", names)
        self.assertNotIn("prepare_incident", names)
        self.assertIn("epidemic_alerts", READ_TOOLS)

    def test_hints_never_substring_of_legacy_phrasing(self) -> None:
        from app.tools.epidemic_alerts import INTENT_HINTS
        legacy = ([c["text"].lower() for c in GOLDEN_CASES]
                  + [c["question"].lower() for c in ROUTING_CASES]
                  + ["que sais-tu faire ?"])
        for hint in INTENT_HINTS:
            for phrase in legacy:
                self.assertNotIn(
                    hint, phrase,
                    f"hint {hint!r} sous-chaîne du phrasé legacy {phrase!r}")


class EpidemicAlertsCardTest(unittest.TestCase):
    def test_card_built_on_cluster(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["epidemic_alerts"]({}, _cluster_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("epidemic_alerts", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "epidemic_alerts")

    def test_typed_card_when_empty(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["epidemic_alerts"](
            {}, {"incidents": [
                _incident(1, 11, "École de Bonanjo", "Wouri",
                          "Eau jaune au robinet"),
            ]})
        self.assertNotIn("error", obs)
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("epidemic_alerts", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "epidemic_alerts")
        self.assertEqual(cards[0].data["clusters"], [])

    def test_no_card_on_error(self) -> None:
        from app.agent_loop import AgentLoop
        from app.tools.epidemic_alerts import CARD_BUILDERS
        self.assertIsNone(CARD_BUILDERS["epidemic_alerts"]({"error": "x"}))
        self.assertIsNone(CARD_BUILDERS["epidemic_alerts"]({}))
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("epidemic_alerts", {"error": "x"})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "guidance")


if __name__ == "__main__":
    unittest.main()


class EpidemicAlertsNegationTest(unittest.TestCase):
    """AXE 3 : symptômes niés ignorés ; synonymes locaux détectés."""

    def test_negated_symptom_no_cluster(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {"incidents": [
            _incident(1, 11, "École de Bonanjo", "Wouri",
                      "Pas de diarrhée ni de vomissements cette semaine"),
            _incident(2, 12, "École de Ngok", "Wouri",
                      "Aucun cas de choléra, eau claire au forage"),
        ]}
        res = TOOL_EXECUTORS["epidemic_alerts"]({}, ctx)
        self.assertEqual(res["clusters"], [])
        self.assertIn("Aucun", res["insight"])

    def test_pidgin_synonym_clusters(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        ctx = {"incidents": [
            _incident(1, 11, "École de Bonanjo", "Wouri",
                      "Pikin them get running stomach since morning"),
            _incident(2, 12, "École de Ngok", "Wouri",
                      "Dirty wata for tap, pikin them dey sick"),
        ]}
        res = TOOL_EXECUTORS["epidemic_alerts"]({}, ctx)
        self.assertEqual(len(res["clusters"]), 1)
        self.assertEqual(res["clusters"][0]["school_count"], 2)
