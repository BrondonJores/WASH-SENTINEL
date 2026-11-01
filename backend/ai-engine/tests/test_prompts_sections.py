"""Prompts structurés : sections, schémas, few-shots, rendus neutres."""
from __future__ import annotations

import json
import unittest

from app import prompts
from app.prompts import (
    agent_sections,
    extractor_sections,
    render_agent_prompt,
    render_extractor_prompt,
    render_repair_prompt,
    repair_sections,
)

SECTION_KEYS = {"role", "schema", "rules", "few_shots", "output_contract"}
BANNED_CAPS = ("JAMAIS", "STOP")


class BuilderShapeTest(unittest.TestCase):
    def test_all_builders_return_all_sections(self) -> None:
        for builder in (agent_sections, extractor_sections, repair_sections):
            with self.subTest(builder=builder.__name__):
                sections = builder()
                self.assertEqual(set(sections), SECTION_KEYS)
                self.assertTrue(sections["role"])
                self.assertTrue(sections["rules"])
                self.assertTrue(sections["output_contract"])

    def test_rules_are_short_sentences(self) -> None:
        for builder in (agent_sections, extractor_sections, repair_sections):
            for rule in builder()["rules"]:
                with self.subTest(rule=rule[:40]):
                    self.assertLessEqual(len(rule), 400)
                    self.assertTrue(rule[0].isupper())


class SchemaSourceTest(unittest.TestCase):
    def test_extractor_schema_matches_schemas_py(self) -> None:
        from app.schemas import ExtractedWashIncident
        schema = extractor_sections()["schema"]
        json.dumps(schema)  # sérialisable
        model_props = ExtractedWashIncident.model_json_schema()["properties"]
        for field in ("school_detected", "infrastructure_type", "issue_type",
                      "urgency_level", "estimated_affected_students",
                      "health_hazard_risk", "short_summary"):
            self.assertIn(field, schema["properties"], field)
            self.assertEqual(schema["properties"][field], model_props[field],
                             field)
        # Le score est calculé localement, jamais demandé au LLM.
        self.assertNotIn("recommended_priority_score", schema["properties"])

    def test_repair_schema_matches_schemas_py(self) -> None:
        from app.schemas import RepairPlanResponse
        schema = repair_sections()["schema"]
        json.dumps(schema)  # sérialisable
        model_props = RepairPlanResponse.model_json_schema()["properties"]
        for field in ("required_tools", "spare_parts_needed",
                      "estimated_intervention_time",
                      "immediate_safety_measures", "estimated_cost_tier"):
            self.assertIn(field, schema["properties"], field)
            self.assertEqual(schema["properties"][field], model_props[field],
                             field)

    def test_agent_has_no_json_schema(self) -> None:
        self.assertIsNone(agent_sections()["schema"])


class FewShotsTest(unittest.TestCase):
    def test_extractor_few_shots_opt_in(self) -> None:
        self.assertEqual(extractor_sections()["few_shots"], [])
        shots = extractor_sections(include_few_shots=True)["few_shots"]
        self.assertGreaterEqual(len(shots), 2)
        self.assertLessEqual(len(shots), 3)
        for shot in shots:
            payload = json.loads(shot["output"])
            self.assertIn(payload["issue_type"],
                          ("leak", "blockage", "dry_well"))

    def test_repair_few_shots_opt_in(self) -> None:
        self.assertEqual(repair_sections()["few_shots"], [])
        shots = repair_sections(include_few_shots=True)["few_shots"]
        self.assertGreaterEqual(len(shots), 2)
        self.assertLessEqual(len(shots), 3)
        for shot in shots:
            payload = json.loads(shot["output"])
            self.assertIn("required_tools", payload)
            self.assertIn("estimated_cost_tier", payload)

    def test_small_model_gets_few_shots(self) -> None:
        self.assertTrue(prompts.is_small_model("llama3.2:3b"))
        self.assertTrue(prompts.is_small_model("qwen2.5-coder:3b-mini"))
        self.assertFalse(prompts.is_small_model("llama3.1:70b"))
        self.assertFalse(prompts.is_small_model(""))


class RenderedPromptTest(unittest.TestCase):
    def test_no_caps_words(self) -> None:
        rendered = [
            render_agent_prompt(),
            render_extractor_prompt(),
            render_extractor_prompt(include_few_shots=True),
            render_repair_prompt(),
            render_repair_prompt(include_few_shots=True),
        ]
        for text in rendered:
            for banned in BANNED_CAPS:
                self.assertNotIn(banned, text)

    def test_rendered_prompts_keep_behavioral_rules(self) -> None:
        agent = render_agent_prompt()
        self.assertIn("2 à 4 phrases", agent)
        self.assertIn("tool de liste", agent)
        self.assertIn("propose tes capacités", agent)
        extractor = render_extractor_prompt()
        self.assertIn("INTERDIT", extractor)
        self.assertNotIn("| other", extractor)

    def test_deprecated_constants_importable(self) -> None:
        from app.agent_loop import SYSTEM_PROMPT
        from app.extractor import WASH_SYSTEM_PROMPT
        from app.repair_advisor import REPAIR_ADVISOR_SYSTEM
        self.assertEqual(SYSTEM_PROMPT, render_agent_prompt())
        self.assertEqual(WASH_SYSTEM_PROMPT, render_extractor_prompt())
        self.assertEqual(REPAIR_ADVISOR_SYSTEM, render_repair_prompt())


if __name__ == "__main__":
    unittest.main()
