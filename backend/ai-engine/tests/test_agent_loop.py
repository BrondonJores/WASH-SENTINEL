"""Boucle agent : un outil déjà appelé ne doit jamais être ré-exécuté.

Contexte : les petits modèles rappellent parfois le même outil au lieu de
conclure (5x summarize_district -> 5 cartes identiques). La boucle doit
détecter la répétition, recadrer le modèle, puis s'arrêter proprement.

Lancer depuis backend/ai-engine : python3 -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import unittest

from app.agent_loop import AgentLoop, _follow_ups
from app.schemas import AgentChatRequest, AgentContext

CONTEXT = AgentContext(
    schools=[],
    incidents=[
        {"id": 1, "school_name": "E1", "urgency": "critical",
         "category": "water_point", "affected_students": 100},
        {"id": 2, "school_name": "E2", "urgency": "high",
         "category": "toilets_latrines", "affected_students": 50},
    ],
)

CALL_DISTRICT = {
    "raw": {"role": "assistant", "content": ""},
    "content": "",
    "tool_calls": [{"id": "1", "name": "summarize_district", "arguments": {}}],
}


FULL_CONTEXT = AgentContext(
    schools=[
        {"school_id": 1, "school_name": "E1", "district": "Wouri"},
        {"school_id": 2, "school_name": "E2", "district": "Mvila"},
    ],
    incidents=list(CONTEXT.incidents),
)


def _call(name: str, args: dict) -> dict:
    return {"raw": {"role": "assistant", "content": ""}, "content": "",
            "tool_calls": [{"id": "1", "name": name, "arguments": args}]}


class StubLLM:
    """Provider scripté : rejoue les réponses puis répète la dernière."""

    def __init__(self, script: list[dict]):
        self.model = "stub"
        self.script = list(script)
        self.calls = 0

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls += 1
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        return {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}


class AgentLoopRepeatTest(unittest.IsolatedAsyncioTestCase):
    async def test_stubborn_model_executes_once(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertEqual(res.tools_executed, ["summarize_district"])
        self.assertEqual(len(res.cards), 1)
        self.assertEqual(res.cards[0].type, "district_summary")

    async def test_reasonable_model_keeps_answer(self) -> None:
        loop = AgentLoop(StubLLM([
            CALL_DISTRICT,
            {"raw": {"role": "assistant", "content": "2 incidents ouverts."},
             "content": "2 incidents ouverts.", "tool_calls": []},
        ]))
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertEqual(res.answer, "2 incidents ouverts.")
        self.assertEqual(len(res.cards), 1)

    def test_identical_cards_deduplicated(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        obs = {"open_incidents": 2, "by_urgency": {}, "by_category": {},
               "total_affected_students": 150, "schools_involved": ["E1"]}
        cards = loop._build_cards([("summarize_district", obs), ("summarize_district", obs)])
        self.assertEqual(len(cards), 1)


if __name__ == "__main__":
    unittest.main()


class TerritoryCardTest(unittest.TestCase):
    def test_territory_card_type(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        cards = loop._build_cards([("territory_overview", {
            "district": None, "schools": [], "missing_gps": [], "total": 0,
            "open_incidents": 0})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "territory_map")


class FallbackSummaryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.loop = AgentLoop(StubLLM([CALL_DISTRICT]))

    def test_district(self) -> None:
        text = self.loop._fallback_answer([("summarize_district", {
            "open_incidents": 3, "by_urgency": {"critical": 1, "high": 1, "medium": 1},
            "by_category": {"water_point": 3}, "total_affected_students": 645,
            "schools_involved": ["A", "B", "C"]})])
        self.assertIn("3 incidents ouverts", text)
        self.assertIn("645", text)
        self.assertIn("1 critique", text)
        self.assertIn("carte", text)

    def test_ambiguous_incident_lists_choices(self) -> None:
        text = self.loop._fallback_answer([("prepare_maintenance_log", {
            "action": "create_maintenance_log", "complete": False,
            "missing": ["incident"], "missing_labels": ["l'incident concerné"],
            "incident_choices": "WASH-2026-ZQNU8W — Fuite sur le robinet (id 8), "
                                "WASH-2026-AAAAAA — Fuite au château d'eau (id 9)",
        })])
        self.assertIn("ZQNU8W", text)
        self.assertIn("AAAAAA", text)

    def test_trends(self) -> None:
        text = self.loop._fallback_answer([("repair_trends", {
            "school_name": "École Publique de Bonanjo", "months": 3,
            "figures": {"total_cost": 0, "currency": "XAF", "total_incidents": 1,
                        "total_days_lost": 0, "trend_direction": "stable"}})])
        self.assertIn("Bonanjo", text)
        self.assertIn("1 panne", text)
        self.assertIn("carte", text)

    def test_ranking(self) -> None:
        text = self.loop._fallback_answer([("rank_schools_by_need", {
            "ranking": [{"school_name": "École Publique de Bonanjo", "need_score": 14.5}],
            "total": 3})])
        self.assertIn("Bonanjo", text)
        self.assertIn("14,5", text)
        self.assertIn("carte", text)

    def test_ranking_empty(self) -> None:
        text = self.loop._fallback_answer([("rank_schools_by_need", {"ranking": [], "total": 0})])
        self.assertIn("Aucune école", text)

    def test_analysis(self) -> None:
        text = self.loop._fallback_answer([("analyze_school", {
            "school_name": "École Rurale de Ngok", "open_incidents": [{}, {}],
            "recommendation": "REPLACE_EQUIPMENT", "repair_ratio_percent": 60.0})])
        self.assertIn("Ngok", text)
        self.assertIn("remplacer", text)
        self.assertIn("60,0", text)
        self.assertIn("carte", text)

    def test_incident(self) -> None:
        text = self.loop._fallback_answer([("explain_incident", {
            "reference_code": "WASH-2026-0042", "school_name": "E", "title": "Pompe cassée",
            "urgency": "critical", "affected_students": 450})])
        self.assertIn("WASH-2026-0042", text)
        self.assertIn("450", text)
        self.assertIn("carte", text)

    def test_report(self) -> None:
        text = self.loop._fallback_answer([("prepare_report", {
            "complete": True, "missing_labels": [],
            "slots": {"school_name": "Ecole X", "description": "Fuite"}})])
        self.assertIn("Ecole X", text)
        self.assertIn("carte", text)

    def test_report_incomplete_names_missing(self) -> None:
        text = self.loop._fallback_answer([("prepare_report", {
            "complete": False, "missing_labels": ["l'école concernée"], "slots": {}})])
        self.assertIn("l'école concernée", text)

    def test_proposal(self) -> None:
        text = self.loop._fallback_answer([("prepare_incident", {
            "complete": True, "missing_labels": [], "action": "create_incident", "slots": {}})])
        self.assertIn("Intervention", text)
        self.assertIn("carte", text)

    def test_territory(self) -> None:
        text = self.loop._fallback_answer([("territory_overview", {
            "district": None, "schools": [{}, {}], "missing_gps": ["E3"],
            "total": 2, "open_incidents": 3})])
        self.assertIn("2 écoles géolocalisées", text)
        self.assertIn("3 incidents", text)
        self.assertIn("carte", text)

    def test_no_success_is_honest(self) -> None:
        text = self.loop._fallback_answer([("analyze_school", {"error": "introuvable"})])
        self.assertNotIn("Voici ce que j'ai trouvé", text)
        self.assertNotIn("Reformulez", text)
        self.assertIn("Demandez par exemple", text)
        self.assertEqual(self.loop._fallback_answer([]), text)

    async def test_stubborn_gets_human_summary(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertNotIn("Voici ce que j'ai trouvé", res.answer)
        self.assertIn("carte", res.answer)


class BriefingCardTest(unittest.TestCase):
    def test_briefing_card_type(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        cards = loop._build_cards([("build_briefing", {
            "district": "Mvila", "slides": [], "total": 0})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "briefing_deck")

    def test_briefing_fallback(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        text = loop._fallback_answer([("build_briefing", {
            "district": None, "total": 3,
            "slides": [{"stats": [{"value": "2"}]}]})])
        self.assertIn("3 slides", text)
        self.assertIn("carte", text)


class BogusRefusalTest(unittest.IsolatedAsyncioTestCase):
    REFUSAL = ("Je suis désolé, mais je ne peux pas vous aider davantage "
               "avec cette demande.")

    def _refusal_reply(self) -> dict:
        return {"raw": {"role": "assistant", "content": self.REFUSAL},
                "content": self.REFUSAL, "tool_calls": []}

    async def test_refusal_after_success_replaced(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT, self._refusal_reply()]))
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertNotIn("ne peux pas vous aider", res.answer)
        self.assertIn("carte", res.answer)
        self.assertIn("incidents ouverts", res.answer)

    async def test_refusal_without_success_kept(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("analyze_school", {"school": "XYZ"}),
            self._refusal_reply(),
        ]))
        res = await loop.chat(AgentChatRequest(message="analyse XYZ", context=FULL_CONTEXT))
        self.assertIn("ne peux pas vous aider", res.answer)


def _say(text: str) -> dict:
    return {"raw": {"role": "assistant", "content": text}, "content": text, "tool_calls": []}


class NoToolGuardTest(unittest.IsolatedAsyncioTestCase):
    """Un modèle qui répond aux données sans outil est recadré, jamais cru."""

    async def test_direct_data_answer_forces_tool_retry(self) -> None:
        loop = AgentLoop(StubLLM([
            _say("Les écoles avec le plus de pannes sont : Ecole A et Ecole B."),
            _call("rank_schools_by_need", {}),
            _say("Bonanjo en tête."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="Quelles écoles ont le plus besoin d'aide ?", context=FULL_CONTEXT))
        self.assertEqual(res.tools_executed, ["rank_schools_by_need"])
        self.assertEqual(res.answer, "Bonanjo en tête.")
        self.assertEqual(len(res.cards), 1)

    async def test_greeting_without_tool_passes_through(self) -> None:
        stub = StubLLM([_say("Bonjour !")])
        loop = AgentLoop(stub)
        res = await loop.chat(AgentChatRequest(message="Bonjour", context=CONTEXT))
        self.assertEqual(res.answer, "Bonjour !")
        self.assertEqual(res.tools_executed, [])
        self.assertEqual(stub.calls, 1)

    async def test_stubborn_no_tool_falls_back_honestly(self) -> None:
        loop = AgentLoop(StubLLM([
            _say("Il y a 3 écoles sans eau."),
            _say("Toujours 3 écoles, promis."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="Combien d'écoles sont sans eau ?", context=CONTEXT))
        self.assertEqual(res.tools_executed, [])
        self.assertIn("pas pu récupérer de données", res.answer)


class FollowUpsTest(unittest.TestCase):
    CTX = {"schools": [
        {"school_id": 3, "school_name": "École Publique de Bonanjo"},
        {"school_id": 6, "school_name": "École Rurale de Ngok"},
        {"school_id": 7, "school_name": "École de Nkol"},
    ]}

    def test_greeting_starters(self) -> None:
        chips = _follow_ups("Bonjour Sentinel", [], self.CTX)
        self.assertEqual(len(chips), 3)
        self.assertIn("Voir la carte du territoire", chips)

    def test_plain_answer_no_chips(self) -> None:
        self.assertEqual(_follow_ups("merci beaucoup", [], self.CTX), [])

    def test_missing_category_values(self) -> None:
        chips = _follow_ups("signale une panne", [("prepare_report", {
            "complete": False, "missing": ["category", "urgency"]})], self.CTX)
        self.assertEqual(chips, ["Point d'eau", "Latrines", "Lavage des mains", "Évacuation"])

    def test_missing_urgency_values(self) -> None:
        chips = _follow_ups("x", [("prepare_report", {
            "complete": False, "missing": ["urgency"]})], self.CTX)
        self.assertEqual(chips, ["Basse", "Moyenne", "Haute", "Critique"])

    def test_missing_school_names(self) -> None:
        chips = _follow_ups("x", [("prepare_report", {
            "complete": False, "missing": ["school", "description"]})], self.CTX)
        self.assertEqual(chips, ["École Publique de Bonanjo", "École Rurale de Ngok", "École de Nkol"])

    def test_missing_freetext_no_chips(self) -> None:
        chips = _follow_ups("x", [("prepare_report", {
            "complete": False, "missing": ["description"]})], self.CTX)
        self.assertEqual(chips, [])

    def test_complete_or_picker_no_chips(self) -> None:
        self.assertEqual(_follow_ups("x", [("prepare_report", {
            "complete": True, "missing": []})], self.CTX), [])
        self.assertEqual(_follow_ups("x", [("prepare_maintenance_log", {
            "complete": False, "missing": ["incident"],
            "candidates": [{"id": 1}]})], self.CTX), [])

    def test_data_tool_no_chips(self) -> None:
        self.assertEqual(_follow_ups("x", [("rank_schools_by_need", {"ranking": []})], self.CTX), [])


# ---------------------------------------------------------------------------
# Multilingue (ajouts) : détection FR/EN + langue transmise au provider.
# ---------------------------------------------------------------------------
from app.agent_loop import SYSTEM_PROMPT, _build_system_prompt, _detect_lang


class DetectLangTest(unittest.TestCase):
    def test_french_sentence(self) -> None:
        self.assertEqual(_detect_lang("Quelles écoles ont le plus besoin d'aide ?"), "fr")

    def test_french_short_defaults_fr(self) -> None:
        self.assertEqual(_detect_lang("résume"), "fr")
        self.assertEqual(_detect_lang("Bonjour"), "fr")

    def test_english_sentence(self) -> None:
        self.assertEqual(_detect_lang("Which schools need the most help?"), "en")
        self.assertEqual(_detect_lang("Show me the water points"), "en")

    def test_empty_is_french(self) -> None:
        self.assertEqual(_detect_lang(""), "fr")
        self.assertEqual(_detect_lang("   "), "fr")
        self.assertEqual(_detect_lang("123 !?"), "fr")

    def test_tie_is_french(self) -> None:
        self.assertEqual(_detect_lang("show montre"), "fr")
        self.assertEqual(_detect_lang("the le"), "fr")


class LangClauseTest(unittest.TestCase):
    CLAUSE = "Réponds toujours dans la langue du dernier message"

    def test_system_prompt_contains_clause(self) -> None:
        self.assertIn(self.CLAUSE, SYSTEM_PROMPT)
        self.assertIn("français par défaut", SYSTEM_PROMPT)
        self.assertIn("références/codes inchangés", SYSTEM_PROMPT)
        self.assertIn("langue locale", SYSTEM_PROMPT)

    def test_french_only_rule_removed_for_multilingual(self) -> None:
        self.assertNotIn("Réponds UNIQUEMENT en français", SYSTEM_PROMPT)
        self.assertIn("2 à 4 phrases", SYSTEM_PROMPT)

    def test_built_prompt_carries_clause_and_lang(self) -> None:
        self.assertIn(self.CLAUSE, _build_system_prompt("en"))
        self.assertIn("Langue de réponse : en.", _build_system_prompt("en"))


class RecordingLLM(StubLLM):
    """Stub enregistreur : rejoue le script et capture les messages envoyés."""

    def __init__(self, script: list[dict]):
        super().__init__(script)
        self.seen_messages: list[dict] = []

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        self.seen_messages = list(messages)
        return await super().chat(messages, tools)


class LangWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_english_message_sends_en(self) -> None:
        stub = RecordingLLM([_say("Hello! Here is the summary.")])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="Which schools need the most help?", context=CONTEXT))
        self.assertEqual(res.answer, "Hello! Here is the summary.")
        self.assertEqual(stub.seen_messages[0]["role"], "system")
        self.assertIn("Langue de réponse : en.", stub.seen_messages[0]["content"])

    async def test_french_message_sends_fr(self) -> None:
        stub = RecordingLLM([_say("Bonjour !")])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="Bonjour", context=CONTEXT))
        self.assertEqual(res.answer, "Bonjour !")
        self.assertIn("Langue de réponse : fr.", stub.seen_messages[0]["content"])


class RouteIntentTest(unittest.TestCase):
    """Routeur déterministe : consultation du passé vs création vs autre."""

    CASES = [
        ("donne-moi les interventions réalisées aujourd'hui", "list"),
        ("Liste les interventions d'hier", "list"),
        ("Combien d'interventions ce mois-ci ?", "list"),
        ("Montre-moi l'historique des travaux", "list"),
        ("Quelles interventions passées à Bonanjo ?", "list"),
        ("Affiche les travaux réalisés cette semaine", "list"),
        ("Crée une intervention pour l'école de Ngok", "create"),
        ("Journalise des travaux pour 50000 XAF", "create"),
        ("Signale une panne de pompe à Nkol", "create"),
        ("Prépare un dossier pour une nouvelle fuite", "create"),
        ("Bonjour Sentinel", "other"),
        ("Résume mon district", "other"),
        ("Signale une panne et montre-moi la liste", "list"),
    ]

    def test_routing_table(self) -> None:
        from app.agent_loop import route_intent
        for question, expected in self.CASES:
            with self.subTest(question=question):
                self.assertEqual(route_intent(question), expected)

    def test_exact_failure_question_routes_to_list(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(
            route_intent("donne-moi les interventions réalisées aujourd'hui"), "list")

    def test_list_hides_prepare_tools(self) -> None:
        from app.agent_loop import tools_for_intent
        names = [t["function"]["name"] for t in tools_for_intent("list")]
        self.assertIn("list_maintenance_logs", names)
        self.assertTrue(all(not n.startswith("prepare_") for n in names))

    def test_create_and_other_keep_full_set(self) -> None:
        from app.agent_loop import tools_for_intent
        from app.agent_tools import AGENT_TOOLS
        for intent in ("create", "other"):
            names = [t["function"]["name"] for t in tools_for_intent(intent)]
            self.assertEqual(len(names), len(AGENT_TOOLS))
            self.assertIn("prepare_incident", names)

    def test_no_tool_nudge_names_list_tool(self) -> None:
        from app.agent_loop import NO_TOOL_NUDGE
        self.assertIn("list_maintenance_logs", NO_TOOL_NUDGE)

    def test_system_prompt_bans_unverified_absence(self) -> None:
        from app.agent_loop import SYSTEM_PROMPT
        self.assertIn("tool de liste", SYSTEM_PROMPT)
        self.assertIn("propose tes capacités", SYSTEM_PROMPT)


class AbsenceGuardUnitTest(unittest.TestCase):
    """Garde-fou abstention : déclenche / ne déclenche pas."""

    def test_claims_absence_triggers(self) -> None:
        from app.agent_loop import _claims_absence
        for text in ("Aucune intervention aujourd'hui.",
                     "Il n'y a rien à signaler.",
                     "Zéro incident ouvert.",
                     "Pas d'école concernée."):
            with self.subTest(text=text):
                self.assertTrue(_claims_absence(text))

    def test_claims_absence_quiet(self) -> None:
        from app.agent_loop import _claims_absence
        for text in ("2 interventions journalisées le 2026-10-31.",
                     "Voici le résumé du district.",
                     "Bonjour !"):
            with self.subTest(text=text):
                self.assertFalse(_claims_absence(text))

    def test_has_read_tool(self) -> None:
        from app.agent_loop import _has_read_tool
        self.assertTrue(_has_read_tool([("list_maintenance_logs", {})]))
        self.assertTrue(_has_read_tool([("prepare_incident", {}), ("summarize_district", {})]))
        self.assertFalse(_has_read_tool([]))
        self.assertFalse(_has_read_tool([("prepare_incident", {})]))


class AbsenceGuardLoopTest(unittest.IsolatedAsyncioTestCase):
    """Bug reproduit : prepare_incident appelé puis 'Aucune intervention' sans lecture."""

    def _log_context(self) -> AgentContext:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        return AgentContext(
            schools=[{"school_id": 1, "school_name": "E1", "district": "Wouri"}],
            incidents=[],
            maintenance_logs=[
                {"id": 1, "school_name": "E1", "incident_title": "Pompe",
                 "created_at": f"{today}T08:00:00+00:00"},
                {"id": 2, "school_name": "E1", "incident_title": "Fuite",
                 "created_at": f"{today}T09:00:00+00:00"},
            ],
        )

    async def test_unverified_absence_triggers_correction(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("prepare_incident", {"school": "E1"}),
            _say("Aucune intervention réalisée aujourd'hui."),
            _call("list_maintenance_logs", {}),
            _say("2 interventions journalisées aujourd'hui à E1."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="donne-moi les interventions réalisées aujourd'hui",
            context=self._log_context()))
        self.assertIn("list_maintenance_logs", res.tools_executed)
        self.assertEqual(res.answer, "2 interventions journalisées aujourd'hui à E1.")
        self.assertTrue(any(c.type == "maintenance_logs" for c in res.cards))

    async def test_verified_absence_passes_through(self) -> None:
        stub = StubLLM([
            _call("list_maintenance_logs", {"date": "2000-01-01"}),
            _say("Aucune intervention journalisée le 2000-01-01."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="donne-moi les interventions réalisées aujourd'hui",
            context=self._log_context()))
        self.assertEqual(res.tools_executed, ["list_maintenance_logs"])
        self.assertIn("Aucune intervention", res.answer)
        self.assertEqual(stub.calls, 2)

    async def test_stubborn_absence_ends_honest(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("prepare_incident", {"school": "E1"}),
            _say("Aucune intervention réalisée aujourd'hui."),
            _say("Toujours aucune intervention, promis."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="donne-moi les interventions réalisées aujourd'hui",
            context=self._log_context()))
        self.assertIn("je ne peux pas vérifier", res.answer.lower())


class MaintenanceLogsCardTest(unittest.TestCase):
    """Carte + résumé déterministe pour list_maintenance_logs."""

    def test_card_type(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        cards = loop._build_cards([("list_maintenance_logs", {
            "date": "2026-10-31", "items": [{"id": 1}], "total": 1,
            "insight": "1 intervention journalisée le 2026-10-31."})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "maintenance_logs")

    def test_fallback_summary(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        text = loop._fallback_answer([("list_maintenance_logs", {
            "date": "2026-10-31",
            "items": [{"school_name": "E1"}, {"school_name": "E2"}], "total": 2})])
        self.assertIn("2 interventions journalisées", text)
        self.assertIn("carte", text)

    def test_fallback_empty_is_honest(self) -> None:
        loop = AgentLoop(StubLLM([CALL_DISTRICT]))
        text = loop._fallback_answer([("list_maintenance_logs", {
            "date": "2026-10-31", "items": [], "total": 0})])
        self.assertIn("Aucune intervention journalisée le 2026-10-31", text)


class SystemPromptDateTest(unittest.TestCase):
    """Non-régression E2E : le modèle recevait une date périmée (2024-02-20)
    faute de repère temporel. La date du jour est injectée dans le prompt."""

    def test_today_injected_fr_and_en(self) -> None:
        from datetime import datetime, timezone

        from app.agent_loop import _build_system_prompt

        today = datetime.now(timezone.utc).date().isoformat()
        self.assertIn(f"Aujourd'hui : {today}", _build_system_prompt("fr"))
        self.assertIn(today, _build_system_prompt("en"))


class ContradictionGuardUnitTest(unittest.TestCase):
    """Garde contradiction : référence WASH-* + absence + liste vide."""

    def test_cites_reference_triggers(self) -> None:
        from app.agent_loop import _cites_reference
        self.assertTrue(_cites_reference(
            "Récapitulatif : WASH-2026-0005 — Pompe cassée."))
        self.assertTrue(_cites_reference("Voir WASH-2024-ZQNU8W pour le détail."))

    def test_cites_reference_quiet(self) -> None:
        from app.agent_loop import _cites_reference
        self.assertFalse(_cites_reference("2 interventions journalisées."))
        self.assertFalse(_cites_reference("Aucune intervention aujourd'hui."))
        self.assertFalse(_cites_reference(""))

    def test_has_empty_list_obs(self) -> None:
        from app.agent_loop import _has_empty_list_obs
        self.assertTrue(_has_empty_list_obs([("list_maintenance_logs", {"total": 0})]))
        self.assertFalse(_has_empty_list_obs([("list_maintenance_logs", {"total": 2})]))
        self.assertFalse(_has_empty_list_obs([]))
        self.assertFalse(_has_empty_list_obs([("prepare_incident", {"total": 0})]))

    def test_nudge_wording(self) -> None:
        from app.agent_loop import CONTRADICTION_CORRECTION_NUDGE
        self.assertIn("Tu cites une référence précise puis affirmes une absence",
                      CONTRADICTION_CORRECTION_NUDGE)


class ContradictionGuardLoopTest(unittest.IsolatedAsyncioTestCase):
    """Bug reproduit : 'Récapitulatif WASH-* ... aucune intervention' avec liste vide."""

    def _log_context(self) -> AgentContext:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        return AgentContext(
            schools=[{"school_id": 1, "school_name": "E1", "district": "Wouri"}],
            incidents=[],
            maintenance_logs=[
                {"id": 1, "school_name": "E1", "incident_title": "Pompe",
                 "created_at": f"{today}T08:00:00+00:00"},
            ],
        )

    async def test_contradiction_triggers_correction(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("list_maintenance_logs", {"date": "2000-01-01"}),
            _say("Récapitulatif : WASH-2026-0005 — Pompe cassée. "
                 "Aucune intervention réalisée aujourd'hui."),
            _call("list_maintenance_logs", {}),
            _say("1 intervention journalisée aujourd'hui à E1."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="donne-moi les interventions réalisées aujourd'hui",
            context=self._log_context()))
        self.assertEqual(res.tools_executed,
                         ["list_maintenance_logs", "list_maintenance_logs"])
        self.assertEqual(res.answer, "1 intervention journalisée aujourd'hui à E1.")

    async def test_absence_without_ref_passes_through(self) -> None:
        stub = StubLLM([
            _call("list_maintenance_logs", {"date": "2000-01-01"}),
            _say("Aucune intervention journalisée le 2000-01-01."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="donne-moi les interventions réalisées aujourd'hui",
            context=self._log_context()))
        self.assertIn("Aucune intervention", res.answer)
        self.assertEqual(stub.calls, 2)

    async def test_ref_with_non_empty_list_passes_through(self) -> None:
        stub = StubLLM([
            _call("list_maintenance_logs", {}),
            _say("WASH-2026-0001 : pompe réparée, aucune autre intervention."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="donne-moi les interventions réalisées aujourd'hui",
            context=self._log_context()))
        self.assertIn("WASH-2026-0001", res.answer)
        self.assertEqual(stub.calls, 2)

    async def test_ref_without_absence_passes_through(self) -> None:
        stub = StubLLM([
            _call("list_maintenance_logs", {"date": "2000-01-01"}),
            _say("Voir WASH-2026-0005 pour le détail de l'intervention."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="donne-moi les interventions réalisées aujourd'hui",
            context=self._log_context()))
        self.assertIn("WASH-2026-0005", res.answer)
        self.assertEqual(stub.calls, 2)


class CreateRoutingVoiceTest(unittest.TestCase):
    """TACHE 1 : formulations vocales naturelles -> create (imperatifs nus)."""

    def test_create_enregistre_intervention(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(route_intent("enregistre une intervention"), "create")

    def test_create_enregistre_reparation_capitalized(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(
            route_intent("Enregistre une réparation de pompe à Ngok"), "create")

    def test_create_note_travaux(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(route_intent("note les travaux"), "create")

    def test_create_note_reparation_cout(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(route_intent("note une réparation à 20000 XAF"), "create")

    def test_create_ajoute_reparation(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(route_intent("ajoute une réparation"), "create")

    def test_create_mets_journal(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(route_intent("mets a jour le journal"), "create")


class ListNonRegressionVoiceTest(unittest.TestCase):
    """TACHE 1 : non-regression consultation du passe -> list."""

    def test_list_interventions_realisees_aujourdhui(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(
            route_intent("interventions realisees aujourd hui"), "list")

    def test_list_travaux_realises_semaine(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(
            route_intent("quels travaux réalisés cette semaine ?"), "list")


class FollowUpDateRoutingTest(unittest.TestCase):
    """Non-régression : le bouton 'autre date' routait 'other' -> création."""

    def test_old_button_query_routes_list(self) -> None:
        from app.agent_loop import route_intent
        self.assertEqual(
            route_intent("Voir les interventions à une autre date"), "list")

    def test_create_forms_unaffected(self) -> None:
        from app.agent_loop import route_intent
        for q in ("enregistre une intervention", "note une panne",
                  "journalise les travaux", "mets à jour le journal"):
            self.assertEqual(route_intent(q), "create")


class LlmBudgetTest(unittest.IsolatedAsyncioTestCase):
    """Budget MAX_LLM_CALLS : le pire cas ne dépasse jamais 6 appels."""

    async def test_stubborn_model_capped_at_six_calls(self) -> None:
        from app.agent_loop import MAX_LLM_CALLS

        stub = StubLLM([_call("summarize_district", {})])
        loop = AgentLoop(stub)
        res = await loop.chat(AgentChatRequest(message="résume", context=CONTEXT))
        self.assertLessEqual(stub.calls, MAX_LLM_CALLS)
        self.assertEqual(res.tools_executed, ["summarize_district"])

    async def test_chatterbox_correction_path_capped(self) -> None:
        from app.agent_loop import MAX_LLM_CALLS

        # Modèle bavard : affirme une absence sans outil, persiste, contredit.
        script = [
            {"raw": {"role": "assistant", "content": "aucune école sans eau."},
             "content": "aucune école sans eau.", "tool_calls": []},
        ]
        stub = StubLLM(script)
        loop = AgentLoop(stub)
        res = await loop.chat(AgentChatRequest(
            message="quelles écoles n'ont pas d'eau ?", context=CONTEXT))
        self.assertLessEqual(stub.calls, MAX_LLM_CALLS)
        self.assertTrue(res.answer.strip())


class PayloadScopingTest(unittest.TestCase):
    """Historique et observations bornés, originaux intacts."""

    def test_history_capped_per_turn_and_total(self) -> None:
        from app.agent_loop import _scoped_history
        from app.schemas import ChatTurn

        turns = [ChatTurn(role="user", content=f"m{i} " + "x" * 1500) for i in range(8)]
        scoped = _scoped_history(turns)
        self.assertLessEqual(len(scoped), 6)
        for turn in scoped:
            self.assertLessEqual(len(turn["content"]), 1200 + len("…[tour tronqué]"))
        self.assertLessEqual(sum(len(t["content"]) for t in scoped), 4000)
        # Les tours conservés sont les plus récents.
        self.assertTrue(scoped[-1]["content"].startswith("m7"))

    def test_history_short_passthrough(self) -> None:
        from app.agent_loop import _scoped_history
        from app.schemas import ChatTurn

        turns = [ChatTurn(role="user", content="bonjour")]
        self.assertEqual(_scoped_history(turns), [{"role": "user", "content": "bonjour"}])
        self.assertEqual(_scoped_history([]), [])

    def test_long_list_truncated_with_note(self) -> None:
        from app.agent_loop import _compact_observation

        obs = {"incidents": [{"id": i} for i in range(30)], "total": 30}
        slim = _compact_observation("list_incidents", obs)
        self.assertEqual(len(slim["incidents"]), 13)
        self.assertIn("+18 autres", slim["incidents"][-1])
        self.assertEqual(slim["total"], 30)
        self.assertEqual(len(obs["incidents"]), 30)

    def test_long_string_truncated_with_note(self) -> None:
        from app.agent_loop import _compact_observation

        obs = {"briefing": "y" * 2500}
        slim = _compact_observation("build_briefing", obs)
        self.assertLess(len(slim["briefing"]), 2500)
        self.assertIn("tronqué", slim["briefing"])
        self.assertEqual(len(obs["briefing"]), 2500)


class CompactObservationTest(unittest.TestCase):
    """Le LLM reçoit un résumé, les cartes gardent le détail complet."""

    def test_heatmap_days_stripped_but_totals_kept(self) -> None:
        from app.agent_loop import _compact_observation
        obs = {"insight": "x",
               "calendar_heatmap": {"total_pannes": 5, "start": "s", "end": "e",
                                    "days": [{"date": "d1", "pannes": 2},
                                             {"date": "d2", "pannes": 3}]},
               "budget_compare": {"total_XAF": 100,
                                  "ecoles": [{"nom": "E1", "cumul_reparations_XAF": 100}]}}
        slim = _compact_observation("repair_trends", obs)
        self.assertEqual(slim["calendar_heatmap"]["total_pannes"], 5)
        self.assertEqual(slim["calendar_heatmap"]["jour_max"], "d2")
        self.assertNotIn("days", slim["calendar_heatmap"])
        self.assertEqual(slim["budget_compare"]["top_ecole"], "E1")
        self.assertNotIn("ecoles", slim["budget_compare"])
        # Original intact pour les cartes.
        self.assertEqual(len(obs["calendar_heatmap"]["days"]), 2)

    def test_non_dict_passthrough(self) -> None:
        from app.agent_loop import _compact_observation
        self.assertEqual(_compact_observation("x", "brut"), "brut")
