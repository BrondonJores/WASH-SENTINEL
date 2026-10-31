"""Système de tools plugins : découverte, fusion, routage, cartes."""
from __future__ import annotations

import unittest


class PluginDiscoveryTest(unittest.TestCase):
    def test_capabilities_discovered_and_merged(self) -> None:
        from app.agent_tools import AGENT_TOOLS, PLUGIN_HINTS, TOOL_EXECUTORS
        names = [t.get("function", {}).get("name") for t in AGENT_TOOLS]
        self.assertIn("capabilities", names)
        self.assertIn("capabilities", TOOL_EXECUTORS)
        self.assertIn("capabilities", PLUGIN_HINTS)
        # Legacy intact : 11 outils historiques toujours présents.
        for legacy in ("rank_schools_by_need", "prepare_incident",
                       "list_maintenance_logs", "repair_trends"):
            self.assertIn(legacy, names)

    def test_capabilities_execute_offline(self) -> None:
        from app.agent_tools import TOOL_EXECUTORS
        res = TOOL_EXECUTORS["capabilities"]({}, {})
        self.assertIn("insight", res)
        self.assertGreaterEqual(len(res["items"]), 5)

    def test_router_routes_help_to_list(self) -> None:
        from app.agent_loop import READ_TOOLS, route_intent, tools_for_intent
        self.assertEqual(route_intent("Que sais-tu faire ?"), "list")
        names = [t.get("function", {}).get("name")
                 for t in tools_for_intent("list")]
        self.assertIn("capabilities", names)
        self.assertNotIn("prepare_incident", names)
        self.assertIn("capabilities", READ_TOOLS)

    def test_capabilities_card_built(self) -> None:
        from app.agent_loop import AgentLoop
        from app.agent_tools import TOOL_EXECUTORS
        obs = TOOL_EXECUTORS["capabilities"]({}, {})
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(loop, [("capabilities", obs)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "capabilities_list")


if __name__ == "__main__":
    unittest.main()
