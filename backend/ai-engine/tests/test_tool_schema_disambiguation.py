"""Désambiguïsation structurelle prepare_report / prepare_incident."""
from __future__ import annotations

import unittest

from app.agent_loop import compact_tools
from app.agent_tools import AGENT_TOOLS, TOOL_EXECUTORS

CTX = {"schools": [
    {"school_id": 3, "school_name": "École Publique de Bonanjo",
     "district": "Wouri"},
    {"school_id": 6, "school_name": "École Rurale de Ngok",
     "district": "Mvila"},
], "incidents": []}


def _fn(name: str) -> dict:
    return next(t["function"] for t in AGENT_TOOLS
                if t["function"]["name"] == name)


class SchemaStructureTest(unittest.TestCase):
    def test_const_kind_differs(self) -> None:
        report = _fn("prepare_report")["parameters"]["properties"]
        incident = _fn("prepare_incident")["parameters"]["properties"]
        self.assertEqual(report["kind"].get("const"), "report")
        self.assertEqual(incident["kind"].get("const"), "incident")

    def test_required_slots_differ(self) -> None:
        report = _fn("prepare_report")["parameters"]
        incident = _fn("prepare_incident")["parameters"]
        self.assertIn("description", report["required"])
        self.assertNotIn("title", report["properties"])
        self.assertIn("title", incident["required"])
        self.assertNotIn("description", incident["properties"])

    def test_title_description_exclusivity(self) -> None:
        report = _fn("prepare_report")["parameters"]
        incident = _fn("prepare_incident")["parameters"]
        self.assertEqual(report["not"], {"required": ["title"]})
        self.assertEqual(incident["not"], {"required": ["description"]})

    def test_enums_from_alias_tables(self) -> None:
        from app.agent_tools import CATEGORY_ALIASES, URGENCY_ALIASES
        for name in ("prepare_report", "prepare_incident"):
            props = _fn(name)["parameters"]["properties"]
            self.assertEqual(set(props["category"]["enum"]),
                             set(CATEGORY_ALIASES.values()), name)
            self.assertEqual(set(props["urgency"]["enum"]),
                             set(URGENCY_ALIASES.values()), name)

    def test_maintenance_log_structurally_distinct(self) -> None:
        props = _fn("prepare_maintenance_log")["parameters"]["properties"]
        self.assertIn("incident", props)
        self.assertIn("cost_amount", props)
        self.assertNotIn("school", props)
        self.assertEqual(props["cost_amount"].get("minimum"), 0)


class WrapperSnapshotTest(unittest.TestCase):
    """Observations identiques à l'implémentation pré-fusion (oracle git HEAD)."""

    maxDiff = None

    def test_report_complete(self) -> None:
        obs = TOOL_EXECUTORS["prepare_report"]({
            "school": "Bonanjo",
            "description": "Fuite au robinet de la cour",
            "category": "pompe", "urgency": "haute",
            "affected_students": 120,
        }, CTX)
        self.assertEqual(obs, {
            "action": "create_report",
            "complete": True,
            "slots": {
                "school_id": 3,
                "school_name": "École Publique de Bonanjo",
                "description": "Fuite au robinet de la cour",
                "category": "water_point",
                "urgency": "high",
                "affected_students": 120,
            },
            "missing": [],
            "missing_labels": [],
            "questions": [],
            "recap": ("Nouveau signalement\n"
                      "École : École Publique de Bonanjo\n"
                      "Description : Fuite au robinet de la cour\n"
                      "Catégorie : water_point\nUrgence : high\n"
                      "Élèves affectés : 120"),
        })

    def test_report_empty(self) -> None:
        obs = TOOL_EXECUTORS["prepare_report"]({}, CTX)
        self.assertEqual(obs["action"], "create_report")
        self.assertFalse(obs["complete"])
        self.assertEqual(obs["missing"],
                         ["school", "description", "category",
                          "urgency", "affected_students"])
        self.assertEqual(obs["questions"],
                         ["Quelle école est concernée ?",
                          "Décrivez la panne en quelques mots ?"])
        self.assertEqual(obs["slots"], {
            "school_id": None, "school_name": None, "description": None,
            "category": None, "urgency": None, "affected_students": None,
        })
        self.assertIn("Manquant : l'école concernée", obs["recap"])

    def test_incident_unknown_school(self) -> None:
        obs = TOOL_EXECUTORS["prepare_incident"](
            {"school": "xyz-unknown", "title": "Fuite"}, CTX)
        self.assertEqual(obs["action"], "create_incident")
        self.assertFalse(obs["complete"])
        self.assertEqual(obs["hint_unmatched"], "xyz-unknown")
        self.assertEqual(obs["school_choices"],
                         "École Publique de Bonanjo (id 3), "
                         "École Rurale de Ngok (id 6)")
        self.assertEqual(obs["missing"],
                         ["school", "category", "urgency",
                          "affected_students"])
        self.assertEqual(obs["slots"]["title"], "Fuite")
        self.assertIn("Titre : Fuite", obs["recap"])


class ShortDescriptionTest(unittest.TestCase):
    def test_all_core_tools_have_short_description(self) -> None:
        core = {"analyze_school", "rank_schools_by_need", "summarize_district",
                "explain_incident", "list_maintenance_logs", "repair_trends",
                "build_briefing", "territory_overview", "prepare_report",
                "prepare_incident", "prepare_maintenance_log"}
        names = set()
        for tool in AGENT_TOOLS:
            fn = tool["function"]
            if fn["name"] in core:
                names.add(fn["name"])
                self.assertLessEqual(len(fn.get("short_description", "")), 140,
                                     fn["name"])
                self.assertTrue(fn.get("short_description"), fn["name"])
        self.assertEqual(names, core)

    def test_compact_uses_short_description(self) -> None:
        compacted = compact_tools(AGENT_TOOLS, "llama3.2:3b")
        by_name = {t["function"]["name"]: t["function"] for t in compacted}
        self.assertEqual(by_name["prepare_report"]["description"],
                         _fn("prepare_report")["short_description"])
        self.assertEqual(by_name["summarize_district"]["description"],
                         _fn("summarize_district")["short_description"])

    def test_compact_falls_back_without_short_description(self) -> None:
        tools = [{"type": "function",
                  "function": {"name": "x",
                               "description": "Usage court. Exemple : bla"}}]
        compacted = compact_tools(tools, "qwen:3b")
        self.assertEqual(compacted[0]["function"]["description"],
                         "Usage court.")

    def test_big_model_identity(self) -> None:
        self.assertIs(compact_tools(AGENT_TOOLS, "llama3.1:70b"), AGENT_TOOLS)


if __name__ == "__main__":
    unittest.main()
