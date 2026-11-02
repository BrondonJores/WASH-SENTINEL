"""Préparation d'intervention à venir : slots déterministes + branche boucle.

Scénario jury : « Prépare une intervention pour le lendemain avec un budget
de 100 000 XAF pour réparer la pompe principale » -> dossier ciblé sur
l'UNIQUE incident (date/budget/kit/verdict), JAMAIS la carte large
« Analyse école » ni une question vide (« quelle équipe ? » sans rien
d'autre). Hors ligne : kit de réparation de repli, date relative résolue.

Lancer depuis backend/ai-engine : ./.venv/bin/python -m unittest
tests.test_prepare_intervention -v
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from typing import get_args

from app.agent_loop import AgentLoop
from app.schemas import AgentChatRequest, AgentContext, CardType

_MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
)


def _tomorrow_label() -> str:
    day = date.today() + timedelta(days=1)
    return f"{day.day} {_MONTHS_FR[day.month - 1]} {day.year}"

SCHOOL = {
    "school_id": 1,
    "school_name": "École Publique de Bonanjo",
    "district": "Wouri",
    "incident_count": 6,
    "total_repair_cost": 50000.0,
    "total_days_without_service": 0,
    "estimated_replacement_cost": 1500000.0,
}

PUMP = {
    "id": 10,
    "reference_code": "WASH-2026-PUMP",
    "title": "Pompe principale hors service",
    "school_id": 1,
    "school_name": "École Publique de Bonanjo",
    "district": "Wouri",
    "category": "water_point",
    "issue_type": "total_breakdown",
    "urgency": "critical",
    "status": "triaged",
    "affected_students": 450,
}

LATRINES = {
    "id": 11,
    "reference_code": "WASH-2026-LAT",
    "title": "Latrines des filles bouchées",
    "school_id": 1,
    "school_name": "École Publique de Bonanjo",
    "district": "Wouri",
    "category": "toilets_latrines",
    "issue_type": "blockage",
    "urgency": "medium",
    "status": "triaged",
    "affected_students": 0,
}

CONTEXT = {"schools": [dict(SCHOOL)], "incidents": [dict(PUMP), dict(LATRINES)]}
TODAY = "2026-11-02"  # un lundi ; lendemain = mardi 3 novembre 2026.

FULL_MESSAGE = (
    "Prépare une intervention pour le lendemain avec un budget de "
    "100 000 XAF pour réparer la pompe principale"
)


class PrepStubLLM:
    """Stub : boucle LLM interdite sur la branche préparation (compteur)."""

    def __init__(self):
        self.model = "stub"
        self.chat_calls = 0

    async def chat(self, messages, tools=None):
        self.chat_calls += 1
        return {"raw": {"role": "assistant", "content": "hors branche"},
                "content": "hors branche", "tool_calls": []}

    async def generate_json(self, prompt, system=""):
        return {}

    def format_tool_result(self, name, result, call_id=None):
        import json as _json
        return {"role": "tool",
                "content": _json.dumps(result, ensure_ascii=False)}


def _req(message):
    return AgentChatRequest(
        message=message,
        context=AgentContext(schools=[dict(SCHOOL)],
                             incidents=[dict(PUMP), dict(LATRINES)]),
    )


class CardContractTest(unittest.TestCase):
    def test_intervention_prep_declared(self) -> None:
        self.assertIn("intervention_prep", get_args(CardType))


class PluginSlotsTest(unittest.TestCase):
    def test_full_slots_team_missing_only(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({
            "incident": "pompe principale",
            "budget": "100 000 XAF",
            "date_text": "lendemain",
            "school": "Bonanjo",
            "today": TODAY,
        }, {k: [dict(r) for r in v] for k, v in CONTEXT.items()})
        self.assertNotIn("error", obs)
        self.assertEqual(obs["fields"]["incident_id"], 10)
        self.assertEqual(obs["fields"]["budget_xaf"], 100000)
        self.assertEqual(obs["fields"]["date"], "2026-11-03")
        self.assertEqual(obs["missing"], ["team"])
        self.assertEqual(len(obs["questions"]), 1)
        self.assertIn("quipe", obs["questions"][0])

    def test_match_without_school_derives_school(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({"incident": "pompe principale", "today": TODAY},
                      {k: [dict(r) for r in v] for k, v in CONTEXT.items()})
        self.assertEqual(obs["fields"]["incident_id"], 10)
        self.assertEqual(obs["fields"]["school_name"],
                         "École Publique de Bonanjo")

    def test_ambiguous_incident_offers_picker(self) -> None:
        from app.tools.prepare_intervention import execute
        ctx = {k: [dict(r) for r in v] for k, v in CONTEXT.items()}
        ctx["incidents"].append({**PUMP, "id": 12,
                                 "reference_code": "WASH-2026-PUMP2",
                                 "title": "Pompe secondaire en panne"})
        obs = execute({"incident": "pompe", "today": TODAY}, ctx)
        self.assertIn("incident", obs["missing"])
        self.assertGreaterEqual(len(obs.get("candidates", [])), 2)

    def test_unknown_incident_lists_choices(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({"incident": "piscine olympique", "today": TODAY},
                      {k: [dict(r) for r in v] for k, v in CONTEXT.items()})
        self.assertIn("incident", obs["missing"])
        self.assertIn("WASH-2026-PUMP", obs.get("incident_choices", ""))

    def test_budget_below_replacement_flagged(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({
            "incident": "pompe principale",
            "budget": "100 000 XAF",
            "school": "Bonanjo",
            "today": TODAY,
        }, {k: [dict(r) for r in v] for k, v in CONTEXT.items()})
        self.assertEqual(obs["verdict"]["recommendation"], "REPLACE")
        self.assertIn("insuffisant", obs["budget_verdict"].lower())

    def test_invalid_date_is_missing(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({"incident": "pompe principale",
                       "date_text": "quand les poules auront des dents",
                       "today": TODAY},
                      {k: [dict(r) for r in v] for k, v in CONTEXT.items()})
        self.assertIn("date", obs["missing"])

    def test_team_choices_from_assignees(self) -> None:
        from app.tools.prepare_intervention import execute
        ctx = {k: [dict(r) for r in v] for k, v in CONTEXT.items()}
        ctx["incidents"][0]["assignee"] = "Équipe Wouri Nord"
        obs = execute({"incident": "pompe principale", "today": TODAY}, ctx)
        self.assertIn("Équipe Wouri Nord", obs.get("team_choices", []))


class LoopBranchTest(unittest.IsolatedAsyncioTestCase):
    async def test_jury_scenario_bypasses_llm(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(_req(FULL_MESSAGE))
        self.assertEqual(res.tools_executed, ["prepare_intervention"])
        self.assertEqual([c.type for c in res.cards], ["intervention_prep"])
        self.assertEqual(stub.chat_calls, 0)
        self.assertIn(_tomorrow_label(), res.answer)
        self.assertIn("100 000", res.answer)
        kit = res.cards[0].data.get("repair_kit") or {}
        self.assertTrue(kit.get("spare_parts_needed"))

    async def test_briefing_not_captured(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(_req("Prépare un briefing du district"))
        self.assertNotIn("prepare_intervention", res.tools_executed)

    async def test_new_incident_not_captured(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(
            _req("Prépare une intervention pour une nouvelle panne à Bonanjo"))
        self.assertNotIn("prepare_intervention", res.tools_executed)


if __name__ == "__main__":
    unittest.main()
