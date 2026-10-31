from __future__ import annotations

import unittest

from app.agent_loop import AgentLoop
from app.agent_tools import (
    tool_prepare_incident,
    tool_prepare_maintenance_log,
    tool_prepare_report,
)


def _context() -> dict:
    return {
        "schools": [
            {"school_id": 3, "school_name": "École Publique de Bonanjo", "district": "Wouri"},
            {"school_id": 6, "school_name": "École Rurale de Ngok", "district": "Mvila"},
        ],
        "incidents": [
            {"id": 7, "reference_code": "WASH-2026-QJHIPH", "title": "Latrines bouchées",
             "status": "triaged", "school_id": 3},
        ],
    }


class PrepareReportTest(unittest.TestCase):
    def test_complete_slots(self) -> None:
        obs = tool_prepare_report({
            "school": "Bonanjo", "description": "Fuite au robinet",
            "category": "water_point", "urgency": "high", "affected_students": 200,
        }, _context())
        self.assertTrue(obs["complete"])
        self.assertEqual(obs["slots"]["school_id"], 3)
        self.assertIn("Bonanjo", obs["recap"])

    def test_missing_in_order(self) -> None:
        obs = tool_prepare_report({}, _context())
        self.assertFalse(obs["complete"])
        self.assertEqual(obs["missing"], ["school", "description", "category", "urgency", "affected_students"])
        self.assertEqual(len(obs["missing_labels"]), 5)

    def test_french_aliases(self) -> None:
        obs = tool_prepare_report({
            "school": 6, "description": "Latrines pleines",
            "category": "latrines", "urgency": "critique", "affected_students": "50",
        }, _context())
        self.assertTrue(obs["complete"])
        self.assertEqual(obs["slots"]["category"], "toilets_latrines")
        self.assertEqual(obs["slots"]["urgency"], "critical")
        self.assertEqual(obs["slots"]["affected_students"], 50)

    def test_unmatched_school_gives_choices(self) -> None:
        obs = tool_prepare_report({"school": "ZzzTop", "description": "x"}, _context())
        self.assertIn("school", obs["missing"])
        self.assertEqual(obs["hint_unmatched"], "ZzzTop")
        self.assertIn("Bonanjo", obs["school_choices"])

    def test_bad_numbers_stay_missing(self) -> None:
        obs = tool_prepare_report({
            "school": 3, "description": "x", "category": "eau",
            "urgency": "moyenne", "affected_students": "beaucoup",
        }, _context())
        self.assertIn("affected_students", obs["missing"])
        self.assertEqual(obs["slots"]["category"], "water_point")


class PrepareIncidentTest(unittest.TestCase):
    def test_complete(self) -> None:
        obs = tool_prepare_incident({
            "school": "Ngok", "title": "Forage à réhabiliter",
            "category": "water_point", "urgency": "high", "affected_students": 195,
        }, _context())
        self.assertTrue(obs["complete"])
        self.assertEqual(obs["action"], "create_incident")
        self.assertEqual(obs["slots"]["school_id"], 6)


def _context_multi() -> dict:
    ctx = _context()
    ctx["incidents"] = [
        {"id": 7, "reference_code": "WASH-2026-QJHIPH", "title": "Latrines bouchées",
         "status": "triaged", "school_id": 3},
        {"id": 8, "reference_code": "WASH-2026-ZQNU8W",
         "title": "Fuite sur le robinet du préau", "status": "triaged", "school_id": 7},
        {"id": 9, "reference_code": "WASH-2026-AAAAAA", "title": "Fuite au château d'eau",
         "status": "open", "school_id": 3},
    ]
    return ctx


class PrepareLogTest(unittest.TestCase):
    def test_complete_by_reference(self) -> None:
        obs = tool_prepare_maintenance_log({
            "incident": "WASH-2026-QJHIPH", "cost_amount": 150000, "notes": "Débouchage",
        }, _context())
        self.assertTrue(obs["complete"])
        self.assertEqual(obs["slots"]["incident_id"], 7)
        self.assertIn("QJHIPH", obs["slots"]["incident_label"])

    def test_negative_cost_missing(self) -> None:
        obs = tool_prepare_maintenance_log({"incident": 7, "cost_amount": -5}, _context())
        self.assertIn("cost_amount", obs["missing"])

    def test_resolves_by_title_substring(self) -> None:
        obs = tool_prepare_maintenance_log({
            "incident": "robinet du préau", "cost_amount": 150000,
        }, _context_multi())
        self.assertTrue(obs["complete"])
        self.assertEqual(obs["slots"]["incident_id"], 8)

    def test_resolves_by_title_tokens(self) -> None:
        obs = tool_prepare_maintenance_log({
            "incident": "fuite préau", "cost_amount": 150000,
        }, _context_multi())
        self.assertTrue(obs["complete"])
        self.assertEqual(obs["slots"]["incident_id"], 8)

    def test_ambiguous_title_gives_choices(self) -> None:
        obs = tool_prepare_maintenance_log({
            "incident": "fuite", "cost_amount": 150000,
        }, _context_multi())
        self.assertFalse(obs["complete"])
        self.assertIn("incident", obs["missing"])
        self.assertIsNone(obs["slots"]["incident_id"])
        self.assertIn("ZQNU8W", obs["incident_choices"])
        self.assertIn("AAAAAA", obs["incident_choices"])

    def test_unknown_title_keeps_raw_ref(self) -> None:
        obs = tool_prepare_maintenance_log({
            "incident": "ZzzTop", "cost_amount": 150000,
        }, _context_multi())
        self.assertIsNone(obs["slots"]["incident_id"])
        self.assertEqual(obs["slots"]["incident_ref"], "ZzzTop")

    def test_exact_id_skips_ambiguity(self) -> None:
        obs = tool_prepare_maintenance_log({
            "incident": 8, "cost_amount": 150000,
        }, _context_multi())
        self.assertTrue(obs["complete"])
        self.assertEqual(obs["slots"]["incident_id"], 8)


class ProposalCardsTest(unittest.TestCase):
    def test_only_complete_proposals_make_cards(self) -> None:
        loop = AgentLoop(llm=None)  # type: ignore[arg-type]
        done = tool_prepare_report({
            "school": 3, "description": "x", "category": "water_point",
            "urgency": "low", "affected_students": 0,
        }, _context())
        pending = tool_prepare_incident({"school": 3}, _context())
        cards = loop._build_cards([("prepare_report", done), ("prepare_incident", pending)])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "action_confirmation")
        self.assertEqual(cards[0].data["action"], "create_report")


if __name__ == "__main__":
    unittest.main()
