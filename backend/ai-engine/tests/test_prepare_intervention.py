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


SLOT_TEAMS = [
    {"name": "Équipe Wouri Nord", "district": "Wouri", "is_active": True},
    {"name": "Équipe Wouri Sud", "district": "Wouri", "is_active": True},
]

SLOT_PREP_TURN = (
    "Intervention « WASH-2026-PUMP — Pompe principale hors service » "
    "à École Publique de Bonanjo, budget 100 000 XAF. "
    "Pour quelle date prévoir l'intervention ? "
    "Quelle équipe doit intervenir (Équipe Wouri Nord, Équipe Wouri Sud) ?"
)


def _req_teams(message, history):
    return AgentChatRequest(
        message=message,
        context=AgentContext(schools=[dict(SCHOOL)],
                             incidents=[dict(PUMP), dict(LATRINES)],
                             teams=[dict(t) for t in SLOT_TEAMS]),
        history=history,
    )


def _prep_history():
    return [
        {"role": "user", "content": "Prépare une intervention pour la pompe"},
        {"role": "assistant", "content": SLOT_PREP_TURN},
    ]


class PrepSlotFollowupTest(unittest.IsolatedAsyncioTestCase):
    """Suite de prépa (« Confier à… », « demain ») complète le dossier, sans LLM."""

    def test_buried_reference_matches(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({"incident": "crypto WASH-2026-PUMP bonanjo",
                       "date_text": "demain", "budget": "100000",
                       "school": "", "today": "2026-11-03"}, CONTEXT)
        self.assertEqual((obs.get("fields") or {}).get("incident_id"), 10)

    def test_team_answer_rewritten(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        rewritten = resolve_prep_slot_followup(
            "Confier à Équipe Wouri Nord", _prep_history(),
            {**CONTEXT, "teams": SLOT_TEAMS})
        self.assertIn("WASH-2026-PUMP", rewritten)
        self.assertIn("Bonanjo", rewritten)
        self.assertIn("100000", rewritten.replace(" ", ""))
        self.assertIn("Wouri Nord", rewritten)

    def test_date_answer_rewritten(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        rewritten = resolve_prep_slot_followup(
            "demain", _prep_history(), {**CONTEXT, "teams": SLOT_TEAMS})
        self.assertIn("WASH-2026-PUMP", rewritten)
        self.assertIn("demain", rewritten)

    def test_unrelated_message_unchanged(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        self.assertEqual(
            resolve_prep_slot_followup(
                "Quels sont les incidents ouverts ?", _prep_history(),
                {**CONTEXT, "teams": SLOT_TEAMS}),
            "Quels sont les incidents ouverts ?")

    def test_other_school_unchanged(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        ctx = {"schools": [dict(SCHOOL),
                           {"school_id": 2, "school_name": "École de Ngok",
                            "district": "Mvila"}],
               "incidents": [], "teams": SLOT_TEAMS}
        self.assertEqual(
            resolve_prep_slot_followup("Et pour Ngok ?", _prep_history(), ctx),
            "Et pour Ngok ?")
        # Même avec un slot équipe : autre école = changement de sujet.
        self.assertEqual(
            resolve_prep_slot_followup(
                "Confier à Équipe Wouri Nord pour Ngok",
                _prep_history(), ctx),
            "Confier à Équipe Wouri Nord pour Ngok")

    async def test_team_followup_completes_team_slot(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(
            _req_teams("Confier à Équipe Wouri Nord", _prep_history()))
        self.assertEqual(stub.chat_calls, 0)
        self.assertIn("prepare_intervention", res.tools_executed)
        self.assertNotIn("school_analysis", [c.type for c in res.cards])
        prep = next(c for c in res.cards if c.type == "intervention_prep")
        fields = prep.data.get("fields") or {}
        self.assertEqual(fields.get("incident_id"), 10)
        self.assertEqual(fields.get("team"), "Équipe Wouri Nord")
        self.assertIn("Bonanjo", res.answer)

    async def test_date_followup_completes_dossier(self) -> None:
        from datetime import date as _date
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(
            _req_teams("demain", _prep_history()), today=_date(2026, 11, 3))
        self.assertEqual(stub.chat_calls, 0)
        prep = next(c for c in res.cards if c.type == "intervention_prep")
        fields = prep.data.get("fields") or {}
        self.assertEqual(fields.get("incident_id"), 10)
        self.assertEqual(str(fields.get("date")), "2026-11-04")


REAL_PREP_TURN = (
    "Intervention « l'intervention », prévue le 3 novembre 2026, budget "
    "100 000 XAF, équipe Équipe Wouri Nord. Budget 100 000 XAF enregistré. "
    "Quel incident existant faut-il réparer (titre ou référence) ? "
    "De quelle école s'agit-il ?"
)


def _real_history():
    return [
        {"role": "assistant", "content":
            "10 incidents ouverts dans 1 district : Wouri (10). Tournée "
            "suggérée : École Publique de Bonanjo, Collège Libermann."},
        {"role": "user", "content":
            "Prépare une intervention pour ce signalement, equipe wouri "
            "nord, aujourd'hui budget 100 000XAF"},
        {"role": "assistant", "content": REAL_PREP_TURN},
    ]


class PrepSlotRobustnessTest(unittest.TestCase):
    """Réponses courtes réelles : marqueurs ponctués, slots sans école."""

    def test_markers_match_real_questions(self) -> None:
        from app.agent_loop import _PREP_QUESTION_MARKERS, _norm_marker_text
        from app.tools.prepare_intervention import (
            _SLOT_QUESTIONS, _SLOT_QUESTIONS_EN)
        questions = [*_SLOT_QUESTIONS.values(),
                     *_SLOT_QUESTIONS_EN.values(),
                     "De quelle école s'agit-il ?",
                     "Which school do you mean?"]
        for question in questions:
            normed = _norm_marker_text(question)
            self.assertTrue(
                any(m in normed for m in _PREP_QUESTION_MARKERS),
                f"aucun marqueur pour {question!r}")

    def test_team_only_rebuilt_without_school(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        rewritten = resolve_prep_slot_followup(
            "Confier à Équipe Wouri Nord", _real_history(),
            {**CONTEXT, "teams": SLOT_TEAMS}, date(2026, 11, 3))
        self.assertIn("100000", rewritten.replace(" ", ""))
        self.assertIn("Équipe Wouri Nord", rewritten)
        self.assertIn("03/11/2026", rewritten)

    def test_proposed_teams_never_guessed(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        rewritten = resolve_prep_slot_followup(
            "demain", _prep_history(), {**CONTEXT, "teams": SLOT_TEAMS})
        self.assertNotIn("équipe", rewritten)
        self.assertIn("WASH-2026-PUMP", rewritten)

    def test_lone_school_answers_school_question(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        rewritten = resolve_prep_slot_followup(
            "Bonanjo", _real_history(), {**CONTEXT, "teams": SLOT_TEAMS},
            date(2026, 11, 3))
        self.assertIn("Bonanjo", rewritten)
        self.assertIn("100000", rewritten.replace(" ", ""))
        self.assertIn("Équipe Wouri Nord", rewritten)

    def test_bare_reference_answers_incident_question(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        rewritten = resolve_prep_slot_followup(
            "WASH-2026-PUMP", _real_history(),
            {**CONTEXT, "teams": SLOT_TEAMS}, date(2026, 11, 3))
        self.assertIn("WASH-2026-PUMP", rewritten)
        self.assertIn("100000", rewritten.replace(" ", ""))

    def test_budget_only_answer_rebuilt(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        history = [
            {"role": "user",
             "content": "Prépare une intervention à Bonanjo"},
            {"role": "assistant", "content":
                "Intervention en préparation à École Publique de Bonanjo. "
                "Quel budget allouez-vous (en XAF) ?"},
        ]
        rewritten = resolve_prep_slot_followup(
            "100 000 XAF", history, {**CONTEXT, "teams": SLOT_TEAMS})
        self.assertIn("Bonanjo", rewritten)
        self.assertIn("budget 100000 XAF", rewritten)

    def test_bare_number_never_budget(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        history = [
            {"role": "assistant", "content":
                "Quel budget allouez-vous (en XAF) ?"},
        ]
        self.assertEqual(
            resolve_prep_slot_followup(
                "100000", history, {**CONTEXT, "teams": SLOT_TEAMS}),
            "100000")

    def test_literal_date_wins_over_day_only(self) -> None:
        from app.agent_loop import _prep_asserted_date
        self.assertEqual(
            _prep_asserted_date("Intervention prévue le 15 décembre 2026.",
                                date(2026, 11, 3)),
            date(2026, 12, 15))
        self.assertEqual(
            _prep_asserted_date("Pour demain.", date(2026, 11, 3)),
            date(2026, 11, 4))

    def test_prep_questions_en(self) -> None:
        from app.tools.prepare_intervention import execute
        obs = execute({"today": "2026-11-03"},
                      {**CONTEXT, "lang": "en"})
        self.assertTrue(all("?" in q for q in obs["questions"]))
        self.assertIn("Which existing incident should be repaired",
                      " ".join(obs["questions"]))
        self.assertIn("the targeted existing incident",
                      " ".join(obs["missing_labels"]))

    def test_parse_date_english(self) -> None:
        from datetime import date as _date
        from app.tools.prepare_intervention import parse_date
        ref = _date(2026, 11, 3)
        self.assertEqual(parse_date("tomorrow", ref), _date(2026, 11, 4))
        self.assertEqual(parse_date("today", ref), ref)
        self.assertEqual(parse_date("day after tomorrow", ref),
                         _date(2026, 11, 5))

    def test_english_team_answer_rebuilt(self) -> None:
        from app.agent_loop import resolve_prep_slot_followup
        history = [
            {"role": "assistant", "content":
                "Partial preparation (nothing recorded). "
                "Which team should intervene?"},
        ]
        rewritten = resolve_prep_slot_followup(
            "Assign to Team Wouri Nord", history,
            {"schools": [], "incidents": [],
             "teams": [{"name": "Team Wouri Nord", "is_active": True}]},
            date(2026, 11, 3))
        self.assertIn("Team Wouri Nord", rewritten)
        self.assertTrue(rewritten.startswith("Prépare une intervention"))

    def test_anaphora_inherits_school_and_ref(self) -> None:
        from app.agent_loop import resolve_prep_followup
        history = [{"role": "assistant", "content":
            "1 signalement le 3 nov. 2026 : École Publique de Bonanjo, "
            "WASH-2026-IVMOCT."}]
        rewritten = resolve_prep_followup(
            "Prépare une intervention pour ce signalement, aujourd'hui "
            "budget 100000 XAF", history, CONTEXT)
        self.assertIn("Bonanjo", rewritten)
        self.assertIn("WASH-2026-IVMOCT", rewritten)

    def test_anaphora_ambiguous_ref_not_guessed(self) -> None:
        from app.agent_loop import resolve_prep_followup
        history = [{"role": "assistant", "content":
            "2 signalements : WASH-2026-PUMP et WASH-2026-LAT à Bonanjo."}]
        rewritten = resolve_prep_followup(
            "Prépare une intervention pour cet incident, budget 50000 XAF",
            history, CONTEXT)
        self.assertIn("Bonanjo", rewritten)
        self.assertNotIn("WASH-2026-PUMP", rewritten)
        self.assertNotIn("WASH-2026-LAT", rewritten)


class PrepSlotRobustnessE2ETest(unittest.IsolatedAsyncioTestCase):
    """Cas réel 11:30 : jamais de listing, questions ciblées, sans LLM."""

    async def test_team_only_asks_school_never_lists(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(
            _req_teams("Confier à Équipe Wouri Nord", _real_history()),
            today=date(2026, 11, 3))
        self.assertEqual(stub.chat_calls, 0)
        self.assertIn("prepare_intervention", res.tools_executed)
        self.assertNotIn("list_incidents", res.tools_executed)
        self.assertNotIn("dispatch_maintenance", res.tools_executed)
        self.assertIn("De quelle école s'agit-il ?", res.answer)

    async def test_lone_school_asks_incident_never_lists(self) -> None:
        stub = PrepStubLLM()
        res = await AgentLoop(stub).chat(
            _req_teams("Bonanjo", _real_history()), today=date(2026, 11, 3))
        self.assertEqual(stub.chat_calls, 0)
        self.assertIn("prepare_intervention", res.tools_executed)
        self.assertNotIn("list_incidents", res.tools_executed)
        self.assertNotIn("incident_list", [c.type for c in res.cards])
        self.assertIn("Quel incident existant faut-il réparer", res.answer)


if __name__ == "__main__":
    unittest.main()
