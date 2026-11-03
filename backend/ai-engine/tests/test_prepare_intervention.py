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


TEAMS = [
    {"id": 1, "name": "Équipe Wouri Nord", "district": "Wouri",
     "phone": "+237 690 11 22", "specialties": ["forage"],
     "is_active": True},
    {"id": 2, "name": "Équipe Wouri Sud", "district": "Wouri",
     "phone": None, "specialties": ["latrines"], "is_active": True},
    {"id": 3, "name": "Équipe Mvila Rurale", "district": "Mvila",
     "phone": None, "specialties": ["forage solaire"], "is_active": True},
    {"id": 4, "name": "Équipe Fantôme", "district": "Wouri",
     "phone": None, "specialties": [], "is_active": False},
]


def _ctx_with_teams():
    ctx = {k: [dict(r) for r in v] for k, v in CONTEXT.items()}
    ctx["teams"] = [dict(t) for t in TEAMS]
    return ctx


class TeamChoicesFromTeamsTest(unittest.TestCase):
    def test_district_scoped(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({"incident": "pompe principale", "today": TODAY},
                      _ctx_with_teams())
        self.assertNotIn("error", obs)
        self.assertEqual(obs["team_choices"],
                         ["Équipe Wouri Nord", "Équipe Wouri Sud"])

    def test_question_suggests_teams(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({"incident": "pompe principale",
                       "date_text": "lendemain",
                       "budget": "100 000 XAF",
                       "school": "Bonanjo", "today": TODAY},
                      _ctx_with_teams())
        self.assertEqual(obs["missing"], ["team"])
        self.assertEqual(len(obs["questions"]), 1)
        self.assertIn("Équipe Wouri Nord", obs["questions"][0])

    def test_no_district_all_teams(self) -> None:
        from app.tools.prepare_intervention import execute
        ctx = {"incidents": [], "schools": [],
               "teams": [dict(t) for t in TEAMS]}
        obs = execute({"today": TODAY}, ctx)
        self.assertNotIn("error", obs)
        self.assertEqual(obs["team_choices"],
                         ["Équipe Wouri Nord", "Équipe Wouri Sud",
                          "Équipe Mvila Rurale"])

    def test_no_teams_falls_back_to_assignees(self) -> None:
        from app.tools.prepare_intervention import execute
        ctx = {k: [dict(r) for r in v] for k, v in CONTEXT.items()}
        ctx["incidents"][0]["assignee"] = "Amina la technicienne"
        obs = execute({"incident": "pompe principale", "today": TODAY}, ctx)
        self.assertIn("Amina la technicienne", obs.get("team_choices", []))

    def test_other_district_falls_back_to_all_teams(self) -> None:
        from app.tools.prepare_intervention import execute
        ctx = _ctx_with_teams()
        ctx["incidents"] = [{**PUMP, "school_name": "EP Inconnue",
                             "district": "Dja-et-Lobo"}]
        ctx["schools"] = []
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


def _req_history(message, history):
    return AgentChatRequest(
        message=message,
        context=AgentContext(schools=[dict(SCHOOL)],
                             incidents=[dict(PUMP), dict(LATRINES)]),
        history=history,
    )


class PrepMissingPieceTest(unittest.IsolatedAsyncioTestCase):
    """Prépa sans lieu : sujet hérité ou question guidée, JAMAIS un listing."""

    MESSAGE = ("Ok prépare une intervention pour la réparation du robinet "
               "et des toilettes budget 100 000 francs")

    HISTORY_BONANJO = [
        {"role": "user", "content": "Donne moi les signalements d'aujourd'hui stp"},
        {"role": "assistant",
         "content": ("Pour aujourd'hui, je compte 1 signalement. "
                     "Il concerne l'École Publique de Bonanjo.")},
    ]

    def test_hint_strips_orphan_budget(self) -> None:
        from app.agent_loop import _intervention_hint
        hint = _intervention_hint(self.MESSAGE, CONTEXT)
        self.assertNotIn("budget", hint)
        self.assertIn("robinet", hint)
        self.assertIn("toilettes", hint)

    async def test_followup_inherits_school_never_lists(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(
            _req_history(self.MESSAGE, self.HISTORY_BONANJO))
        self.assertEqual(stub.chat_calls, 0)
        self.assertIn("prepare_intervention", res.tools_executed)
        self.assertNotIn("list_incidents", res.tools_executed)
        self.assertNotIn("list_maintenance_logs", res.tools_executed)
        types = [c.type for c in res.cards]
        self.assertIn("intervention_prep", types)
        self.assertNotIn("incident_list", types)
        self.assertIn("Bonanjo", res.answer)

    async def test_cold_without_school_asks_school(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(_req(self.MESSAGE))
        self.assertEqual(stub.chat_calls, 0)
        self.assertIn("De quelle école s'agit-il ?", res.answer)
        self.assertTrue(any("Bonanjo" in chip for chip in res.follow_ups))
        self.assertNotIn("list_incidents", res.tools_executed)

    async def test_school_known_offers_incident_picker(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(
            _req_history(self.MESSAGE, self.HISTORY_BONANJO))
        types = [c.type for c in res.cards]
        self.assertIn("incident_picker", types)
        picker = next(c for c in res.cards if c.type == "incident_picker")
        refs = [c.get("reference_code") for c in picker.data.get("candidates", [])]
        self.assertIn("WASH-2026-PUMP", refs)
        self.assertIn("WASH-2026-LAT", refs)


if __name__ == "__main__":
    unittest.main()
