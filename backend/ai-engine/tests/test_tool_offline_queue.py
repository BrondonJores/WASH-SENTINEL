"""Plugin offline_queue : file d'attente hors-ligne (synchro + connectivite)."""
from __future__ import annotations

import unittest


def _fixture_context() -> dict:
    return {
        "offline_queue": [
            {"temp_id": "tmp-001", "school": "EP Bonanjo",
             "summary": "Fuite tuyau cour", "created_at": "2026-10-31T08:00:00+00:00",
             "status": "pending"},
            {"id": 42, "school": "EP Mendong",
             "summary": "Pompe manuelle cassee", "created_at": "2026-10-31T09:15:00+00:00",
             "status": "pending"},
        ],
        "sync_status": {"online": False, "last_sync": "2026-10-30T18:00:00+00:00"},
    }


class OfflineQueueExecuteTest(unittest.TestCase):
    def test_execute_offline_with_two_pending(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["offline_queue"]({}, _fixture_context())
        self.assertNotIn("error", res)
        self.assertIn("insight", res)
        self.assertEqual(res["count"], 2)
        self.assertEqual(len(res["pending"]), 2)
        self.assertFalse(res["online"])
        self.assertIn("2", res["insight"])
        self.assertIn("attente", res["insight"].lower())

    def test_execute_missing_keys_returns_honest_error(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["offline_queue"]({}, {})
        self.assertIn("error", res)
        self.assertIn("hors-ligne", res["error"].lower())
        self.assertIn("inconnue", res["error"].lower())

    def test_execute_empty_queue_known(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["offline_queue"](
            {}, {"offline_queue": [], "sync_status": {"online": True}})
        self.assertNotIn("error", res)
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["pending"], [])
        self.assertTrue(res["online"])
        self.assertIn("vide", res["insight"].lower())


class OfflineQueueRouteCardTest(unittest.TestCase):
    def test_discovered_readonly_and_merged(self) -> None:
        from app.agent_loop import READ_TOOLS
        from app.agent_tools import AGENT_TOOLS, PLUGIN_HINTS, TOOL_EXECUTORS
        names = [t.get("function", {}).get("name") for t in AGENT_TOOLS]
        self.assertIn("offline_queue", names)
        self.assertIn("offline_queue", TOOL_EXECUTORS)
        self.assertIn("offline_queue", PLUGIN_HINTS)
        self.assertIn("offline_queue", READ_TOOLS)

    def test_router_routes_offline_to_list(self) -> None:
        from app.agent_loop import route_intent, tools_for_intent
        self.assertEqual(
            route_intent("Quels signalements sont en attente de synchro hors ligne ?"),
            "list")
        self.assertEqual(route_intent("Pas de réseau, ma file d'attente ?"), "list")
        names = [t.get("function", {}).get("name") for t in tools_for_intent("list")]
        self.assertIn("offline_queue", names)
        self.assertNotIn("prepare_incident", names)

    def test_card_built_when_data(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["offline_queue"]({}, _fixture_context())
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("offline_queue", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "offline_queue")
        self.assertIsNotNone(cards[0])

    def test_card_none_on_error(self) -> None:
        from app.agent_loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("offline_queue", {"error": "oups"})])
        self.assertEqual(cards, [])

    def test_hints_lowercase_and_no_legacy_collision(self) -> None:
        from app.tools.offline_queue import INTENT_HINTS
        from tests.test_agent_loop import RouteIntentTest
        from tests.test_prompt_eval import GOLDEN_CASES, ROUTING_CASES
        for hint in INTENT_HINTS:
            self.assertEqual(hint, hint.lower(), f"hint non minuscule : {hint}")
        legacy = [c["text"].lower() for c in GOLDEN_CASES]
        legacy += [c["question"].lower() for c in ROUTING_CASES
                   if c["intent"] != "list"]
        legacy += [q.lower() for q, exp in RouteIntentTest.CASES if exp != "list"]
        legacy += ["enregistre une intervention",
                   "enregistre une réparation de pompe à ngok",
                   "note les travaux", "note une réparation à 20000 xaf",
                   "ajoute une réparation", "mets a jour le journal",
                   "mets à jour le journal", "journalise les travaux",
                   "note une panne"]
        for hint in INTENT_HINTS:
            for phrase in legacy:
                self.assertNotIn(hint, phrase,
                                 f"hint {hint!r} collide avec un phrasé legacy")

    def test_legacy_routing_untouched(self) -> None:
        from app.agent_loop import route_intent
        for question in ("Prépare un dossier pour une nouvelle fuite",
                         "Enregistre une intervention de réparation de pompe",
                         "note les travaux",
                         "mets a jour le journal"):
            with self.subTest(question=question):
                self.assertEqual(route_intent(question), "create")
        for question in ("Résume mon district", "Bonjour Sentinel",
                         "Résumer mon district",
                         "Quelles écoles ont le plus besoin d'aide ?",
                         "Explique l'incident WASH-001 en langage simple"):
            with self.subTest(question=question):
                self.assertEqual(route_intent(question), "other")


if __name__ == "__main__":
    unittest.main()
