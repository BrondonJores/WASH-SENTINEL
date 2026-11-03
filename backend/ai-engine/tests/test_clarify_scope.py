"""Clarification guidée : périmètre manquant = demander, pas deviner.

Non-régression prod : face à « Compare un district ? » (sans district), le
modèle devinait au lieu de guider et les relances restaient génériques.
Désormais la réponse repose LA question en une phrase et les relances
deviennent des choix cliquables tirés du contexte réel (jamais inventés) ;
un lieu seul au tour suivant (« Mvila ») reprend la question en attente.

Lancer depuis backend/ai-engine : ./.venv/bin/python -m unittest
"""
from __future__ import annotations

import unittest

from app.agent_loop import (
    AgentLoop,
    clarify_follow_ups,
    needs_clarification,
    resolve_bare_place_followup,
)
from app.guidance import clarify_choices, clarify_question, short_school_name
from app.schemas import AgentChatRequest, AgentContext, ChatTurn

NGOK = "École Rurale de Ngok"
BONANJO = "École Publique de Bonanjo"
LOLODORF = "École de Lolodorf"

CONTEXT = AgentContext(
    schools=[
        {"school_id": 1, "school_name": NGOK, "district": "Mvila",
         "lat": 3.5, "lng": 11.5},
        {"school_id": 2, "school_name": BONANJO, "district": "Wouri",
         "lat": 4.0, "lng": 9.7},
        {"school_id": 3, "school_name": LOLODORF,
         "district": "Sanaga-Maritime", "lat": 3.2, "lng": 10.7},
    ],
    incidents=[
        {"id": 1, "school_id": 1, "school_name": NGOK, "district": "Mvila",
         "title": "Pompe cassée", "urgency": "high",
         "affected_students": 120, "status": "open"},
    ],
)
CTX = CONTEXT.model_dump()
SCHOOLS = [NGOK, BONANJO, LOLODORF]
DISTRICTS = ["Mvila", "Sanaga-Maritime", "Wouri"]


def _say(text: str) -> dict:
    return {"raw": {"role": "assistant", "content": text},
            "content": text, "tool_calls": []}


class StubLLM:
    """Provider scripté : rejoue les réponses puis répète la dernière."""

    def __init__(self, script: list[dict]):
        self.model = "stub"
        self.script = list(script)

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        import json
        return {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}


class RecordingLLM(StubLLM):
    def __init__(self, script: list[dict]):
        super().__init__(script)
        self.seen_messages: list[dict] = []

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        if not self.seen_messages:
            self.seen_messages = list(messages)
        return await super().chat(messages, tools)


class NeedsClarificationTest(unittest.TestCase):
    def test_district_missing_detected(self) -> None:
        for message in ("Compare un district ?",
                        "Résume mon district",
                        "résume le district",
                        "Tendances de mon district ?"):
            with self.subTest(message=message):
                self.assertEqual(needs_clarification(message, CTX), "district")

    def test_school_missing_detected(self) -> None:
        for message in ("Tendances de l'école ?",
                        "Budget réparations de l'école ?",
                        "Que se passe-t-il dans la classe ?",
                        "Analyse une école ?"):
            with self.subTest(message=message):
                self.assertEqual(needs_clarification(message, CTX), "school")

    def test_global_questions_not_intercepted(self) -> None:
        for message in ("Combien d'incidents ouverts ?",
                        "Qui envoyer sur place ?",
                        "Quelles écoles ont le plus besoin d'aide ?",
                        "Voir la carte du territoire",
                        "Compare les écoles",
                        "Bonjour",
                        "résume"):
            with self.subTest(message=message):
                self.assertIsNone(needs_clarification(message, CTX))

    def test_singular_need_help_not_intercepted(self) -> None:
        for message in ("Quelle école a besoin d'aide ?",
                        "Quelle école a besoin d’aide ?"):
            with self.subTest(message=message):
                self.assertIsNone(needs_clarification(message, CTX))

    def test_resolved_scope_not_intercepted(self) -> None:
        for message in ("Compare Ngok et Bonanjo",
                        "Résume le district de Mvila",
                        "Tendances de Ngok ?",
                        "Faut-il réparer à Ngok ?"):
            with self.subTest(message=message):
                self.assertIsNone(needs_clarification(message, CTX))


class ClarifyQuestionTest(unittest.TestCase):
    def test_question_fr_and_en(self) -> None:
        self.assertEqual(clarify_question("district", "fr"),
                         "De quel district s'agit-il ?")
        self.assertEqual(clarify_question("school", "fr"),
                         "De quelle école s'agit-il ?")
        self.assertEqual(clarify_question("district", "en"),
                         "Which district do you mean?")
        self.assertEqual(clarify_question("school", "en"),
                         "Which school do you mean?")


class ClarifyChoicesTest(unittest.TestCase):
    def test_district_choices_from_context(self) -> None:
        self.assertEqual(
            clarify_choices("district", "compare", SCHOOLS, DISTRICTS),
            ["Comparer le district Mvila",
             "Comparer le district Sanaga-Maritime",
             "Comparer le district Wouri"])

    def test_school_choices_use_short_names(self) -> None:
        self.assertEqual(short_school_name(NGOK), "Ngok")
        self.assertEqual(short_school_name(BONANJO), "Bonanjo")
        self.assertEqual(
            clarify_choices("school", "trends", SCHOOLS, DISTRICTS),
            ["Tendances de Ngok ?",
             "Tendances de Bonanjo ?",
             "Tendances de Lolodorf ?"])

    def test_school_compare_proposes_real_pairs(self) -> None:
        self.assertEqual(
            clarify_choices("school", "compare", SCHOOLS, DISTRICTS),
            ["Comparer Ngok et Bonanjo",
             "Comparer Ngok et Lolodorf",
             "Comparer Bonanjo et Lolodorf"])

    def test_choices_never_invented_never_crash(self) -> None:
        # Contexte partiel : que les lieux connus, rien d'inventé.
        choices = clarify_choices("district", "compare", [], ["Mvila"])
        self.assertEqual(choices, ["Comparer le district Mvila"])
        joined = " ".join(choices)
        self.assertNotIn("Yaoundé", joined)
        self.assertNotIn("Douala", joined)
        # Sans lieu : vide (l'appelant replie), jamais d'erreur.
        self.assertEqual(clarify_choices("district", "compare", [], []), [])
        self.assertEqual(clarify_choices("school", "trends", [], []), [])
        self.assertEqual(clarify_choices("unknown", "recap", SCHOOLS, DISTRICTS), [])
        self.assertEqual(clarify_choices("district", "compare", None, None), [])


class BarePlaceMemoTest(unittest.TestCase):
    def test_bare_district_reattached(self) -> None:
        history = [ChatTurn(role="user", content="Compare un district ?"),
                   ChatTurn(role="assistant",
                            content="De quel district s'agit-il ?")]
        self.assertEqual(resolve_bare_place_followup("Mvila", history, CTX),
                         "Compare un district Mvila")

    def test_bare_school_reattached(self) -> None:
        history = [{"role": "user", "content": "Tendances de l'école ?"},
                   {"role": "assistant",
                    "content": "De quelle école s'agit-il ?"}]
        self.assertEqual(resolve_bare_place_followup("Ngok", history, CTX),
                         "Tendances de l'école Ngok")

    def test_bare_place_ignored_without_pending_question(self) -> None:
        # Question précédente globale : pas de rattachement.
        history = [ChatTurn(role="user", content="Bonjour"),
                   ChatTurn(role="assistant", content="Bonjour !")]
        self.assertEqual(resolve_bare_place_followup("Mvila", history, CTX),
                         "Mvila")
        # Sans historique : inchangé.
        self.assertEqual(resolve_bare_place_followup("Mvila", [], CTX), "Mvila")
        # Question déjà complète (« résume Mvila ») : inchangée.
        history = [ChatTurn(role="user", content="Compare un district ?")]
        self.assertEqual(
            resolve_bare_place_followup("résume Mvila", history, CTX),
            "résume Mvila")
        # Lieu inconnu : inchangé.
        self.assertEqual(
            resolve_bare_place_followup("Zzzzz", history, CTX), "Zzzzz")


class PromptRuleTest(unittest.TestCase):
    def test_prompt_asks_with_context_choices_fr_and_en(self) -> None:
        from app.prompts import render_agent_prompt
        prompt = render_agent_prompt()
        self.assertIn("sans inventer aucun nom de lieu", prompt)
        self.assertIn("never invent a place name", prompt)


class ClarifyChatIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_district_asks_with_district_choices(self) -> None:
        loop = AgentLoop(StubLLM([_say("Panorama global : 1 incident ouvert.")]))
        res = await loop.chat(AgentChatRequest(
            message="Compare un district ?", context=CONTEXT))
        self.assertIn("De quel district s'agit-il ?", res.answer)
        self.assertEqual(res.follow_ups,
                         ["Comparer le district Mvila",
                          "Comparer le district Sanaga-Maritime",
                          "Comparer le district Wouri"])

    async def test_missing_school_asks_with_school_choices(self) -> None:
        loop = AgentLoop(StubLLM([_say("Panorama global : 1 incident ouvert.")]))
        res = await loop.chat(AgentChatRequest(
            message="Tendances de l'école ?", context=CONTEXT))
        self.assertIn("De quelle école s'agit-il ?", res.answer)
        self.assertEqual(res.follow_ups,
                         ["Tendances de Ngok ?",
                          "Tendances de Bonanjo ?",
                          "Tendances de Lolodorf ?"])

    async def test_global_question_untouched(self) -> None:
        loop = AgentLoop(StubLLM([_say("Il y a 1 incident ouvert.")]))
        res = await loop.chat(AgentChatRequest(
            message="Combien d'incidents ouverts ?", context=CONTEXT))
        self.assertNotIn("s'agit-il", res.answer)
        self.assertEqual(res.follow_ups, [])

    async def test_explicit_district_scope_unchanged(self) -> None:
        loop = AgentLoop(StubLLM([_say("Mvila : 1 incident ouvert.")]))
        res = await loop.chat(AgentChatRequest(
            message="Résume le district de Mvila", context=CONTEXT))
        self.assertNotIn("s'agit-il", res.answer)
        self.assertEqual(res.follow_ups, [])

    async def test_bare_place_reattached_in_chat(self) -> None:
        llm = RecordingLLM([_say("ok")])
        history = [ChatTurn(role="user", content="Compare un district ?"),
                   ChatTurn(role="assistant",
                            content="De quel district s'agit-il ?")]
        res = await AgentLoop(llm).chat(AgentChatRequest(
            message="Mvila", history=history, context=CONTEXT))
        user_msg = llm.seen_messages[-1]["content"]
        self.assertIn("Compare un district Mvila", user_msg)
        # Périmètre résolu : plus de question de clarification.
        self.assertNotIn("s'agit-il", res.answer)

    async def test_empty_context_falls_back(self) -> None:
        loop = AgentLoop(StubLLM([_say("Je ne sais pas.")]))
        res = await loop.chat(AgentChatRequest(
            message="Compare un district ?", context=AgentContext()))
        self.assertIn("De quel district s'agit-il ?", res.answer)
        self.assertTrue(res.follow_ups)
        self.assertIn("Voir la carte du territoire", res.follow_ups)

    async def test_english_clarification(self) -> None:
        loop = AgentLoop(StubLLM([_say("Global overview.")]))
        res = await loop.chat(AgentChatRequest(
            message="Which district should I compare?", context=CONTEXT))
        self.assertIn("Which district do you mean?", res.answer)
        self.assertEqual(res.follow_ups,
                         ["Compare district Mvila",
                          "Compare district Sanaga-Maritime",
                          "Compare district Wouri"])

    async def test_clarify_follow_ups_pure_helper(self) -> None:
        self.assertEqual(
            clarify_follow_ups("district", "Compare un district ?", CTX),
            ["Comparer le district Mvila",
             "Comparer le district Sanaga-Maritime",
             "Comparer le district Wouri"])
        self.assertEqual(clarify_follow_ups("district", "Compare ?", {}), [])


if __name__ == "__main__":
    unittest.main()
