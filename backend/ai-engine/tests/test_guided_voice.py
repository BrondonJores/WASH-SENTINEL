"""Dialogue guide vocal partage (CANAL 3) : slots, oui/non, integration.

Lancer depuis backend/ai-engine : python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import unittest

from app.agent_loop import AgentLoop
from app.guided_voice import (
    CONFIRM,
    PROBLEM,
    Q_CONFIRM_TAIL_FR,
    Q_PROBLEM_FR,
    Q_SCHOOL_FR,
    Q_SEVERITY_FR,
    ask,
    build_report_text,
    guided_chips,
    guided_turn,
    is_report_message,
    parse_confirmation,
    parse_problem,
    parse_severity,
)
from app.schemas import AgentChatRequest, AgentContext, ChatTurn

CONTEXT = AgentContext(
    schools=[
        {"school_id": 1, "school_name": "École de Bonanjo", "district": "Wouri"},
        {"school_id": 2, "school_name": "École de Deido", "district": "Wouri"},
    ],
    incidents=[],
)
CTX = CONTEXT.model_dump()


def _hist(*texts: str) -> list[ChatTurn]:
    """Historique user/assistant alterne depuis des textes bruts."""
    turns = []
    for i, text in enumerate(texts):
        turns.append(ChatTurn(role="user" if i % 2 == 0 else "assistant",
                              content=text))
    return turns


class ParseConfirmationTest(unittest.TestCase):
    def test_yes_fr(self) -> None:
        for text in ("oui", "Oui !", "ouais", "d'accord", "OK"):
            self.assertEqual(parse_confirmation(text), "yes", text)

    def test_yes_douala(self) -> None:
        for text in ("éé", "ÉÉ", "ee"):
            self.assertEqual(parse_confirmation(text), "yes", text)

    def test_yes_english_pidgin(self) -> None:
        for text in ("yeah", "yes"):
            self.assertEqual(parse_confirmation(text), "yes", text)

    def test_no_fr(self) -> None:
        for text in ("non", "Non.", "non merci", "pas du tout", "jamais"):
            self.assertEqual(parse_confirmation(text), "no", text)

    def test_repeat(self) -> None:
        for text in ("répéter", "répète", "redis-moi", "pardon ?", "quoi ?",
                     "encore", "je n'ai pas compris"):
            self.assertEqual(parse_confirmation(text), "repeat", text)

    def test_unknown(self) -> None:
        for text in ("", "   ", "blabla", "peut-être"):
            self.assertEqual(parse_confirmation(text), "unknown", repr(text))

    def test_si_ambiguous_is_unknown(self) -> None:
        # FR "si" (= oui qui contredit) vs douala "si" (= non) : on repose.
        self.assertEqual(parse_confirmation("si"), "unknown")
        self.assertEqual(parse_confirmation("Si !"), "unknown")


class ParseSlotsTest(unittest.TestCase):
    def test_problem_eau(self) -> None:
        for text in ("l'eau ne coule plus", "pas d'eau", "plus d'eau à l'école",
                     "la pompe est cassée", "madiba", "wata sale"):
            self.assertEqual(parse_problem(text), "eau", text)

    def test_problem_toilettes(self) -> None:
        for text in ("les toilettes sont bouchées", "latrines cassées",
                     "les WC débordent"):
            self.assertEqual(parse_problem(text), "toilettes", text)

    def test_problem_fuite(self) -> None:
        for text in ("le tuyau fuit", "grosse fuite", "l'eau coule partout",
                     "fuite d'eau"):
            self.assertEqual(parse_problem(text), "fuite", text)

    def test_problem_unknown(self) -> None:
        for text in ("", "blabla", "bonjour"):
            self.assertIsNone(parse_problem(text), repr(text))

    def test_severity(self) -> None:
        self.assertEqual(parse_severity("oui"), "grave")
        self.assertEqual(parse_severity("c'est grave"), "grave")
        self.assertEqual(parse_severity("non"), "pas grave")
        self.assertEqual(parse_severity("pas grave"), "pas grave")
        self.assertEqual(parse_severity("petite fuite"), "pas grave")
        self.assertIsNone(parse_severity("blabla"))
        self.assertIsNone(parse_severity("si"))  # ambigu -> on repose

    def test_is_report_message(self) -> None:
        self.assertTrue(is_report_message("je veux signaler une panne"))
        self.assertTrue(is_report_message("fuite au robinet"))
        self.assertTrue(is_report_message("pas d'eau à l'école"))
        self.assertFalse(is_report_message("quelles écoles sont suivies ?"))
        self.assertFalse(is_report_message("bonjour"))
        self.assertFalse(is_report_message("Bonanjo"))


class QuestionsContractTest(unittest.TestCase):
    def test_one_question_per_turn(self) -> None:
        slots = {"school": "Bonanjo", "problem": "eau", "severity": "grave"}
        for step in ("school", "problem", "severity", "confirm"):
            for lang in ("fr", "dua"):
                text = ask(step, slots, lang)
                self.assertLessEqual(text.count("?"), 1, f"{step}/{lang}: {text}")
                self.assertTrue(text.strip(), f"{step}/{lang} vide")

    def test_confirm_has_recap_and_yes_no(self) -> None:
        slots = {"school": "Bonanjo", "problem": "fuite", "severity": "grave"}
        text = ask("confirm", slots, "fr")
        self.assertIn("Bonanjo", text)
        self.assertIn("fuite", text)
        self.assertIn("grave", text)
        self.assertIn(Q_CONFIRM_TAIL_FR, text)

    def test_chips_max_three(self) -> None:
        self.assertEqual(guided_chips(PROBLEM), ["Eau", "Toilettes", "Fuite"])
        self.assertEqual(guided_chips("severity"), ["Oui", "Non"])
        self.assertEqual(guided_chips(CONFIRM), ["Oui", "Non"])
        self.assertLessEqual(len(guided_chips("school", CTX)), 3)


class GuidedNominalTest(unittest.TestCase):
    def test_full_path_to_confirmation(self) -> None:
        t1 = guided_turn("je veux signaler une panne", None, CTX)
        assert t1 is not None
        self.assertEqual(t1["status"], "ask")
        self.assertEqual(t1["question"], Q_SCHOOL_FR)

        t2 = guided_turn("Bonanjo",
                         _hist("je veux signaler une panne", t1["question"]),
                         CTX)
        assert t2 is not None
        self.assertEqual(t2["question"], Q_PROBLEM_FR)
        self.assertEqual(t2["chips"], ["Eau", "Toilettes", "Fuite"])

        history = _hist("je veux signaler une panne", t1["question"],
                        "Bonanjo", t2["question"])
        t3 = guided_turn("la pompe fuit", history, CTX)
        assert t3 is not None
        self.assertEqual(t3["question"], Q_SEVERITY_FR)
        self.assertEqual(t3["slots"]["problem"], "fuite")

        history = history + _hist("la pompe fuit", t3["question"])
        t4 = guided_turn("oui", history, CTX)
        assert t4 is not None
        self.assertEqual(t4["step"], "confirm")
        self.assertIn("Bonanjo", t4["question"])
        self.assertIn("fuite", t4["question"])
        self.assertIn("grave", t4["question"])
        self.assertIn("Dites oui ou non", t4["question"])

        history = history + _hist("oui", t4["question"])
        t5 = guided_turn("oui", history, CTX)
        assert t5 is not None
        self.assertEqual(t5["status"], "confirmed")
        self.assertIn("Bonanjo", t5["report_text"])
        self.assertIn("fuite", t5["report_text"])
        self.assertIn("grave", t5["report_text"])

    def test_repeat_reasks_same_question(self) -> None:
        history = _hist("je veux signaler une panne", Q_SCHOOL_FR,
                        "Bonanjo", Q_PROBLEM_FR)
        turn = guided_turn("répète s'il te plaît", history, CTX)
        assert turn is not None
        self.assertEqual(turn["status"], "ask")
        self.assertEqual(turn["question"], Q_PROBLEM_FR)
        self.assertNotIn("problem", turn["slots"])

    def test_missing_slot_reasks_question(self) -> None:
        history = _hist("je veux signaler une panne", Q_SCHOOL_FR,
                        "Bonanjo", Q_PROBLEM_FR)
        turn = guided_turn("blabla", history, CTX)
        assert turn is not None
        self.assertEqual(turn["question"], Q_PROBLEM_FR)
        # ... puis la bonne réponse fait avancer.
        history2 = history + _hist("blabla", Q_PROBLEM_FR)
        turn2 = guided_turn("les toilettes débordent", history2, CTX)
        assert turn2 is not None
        self.assertEqual(turn2["question"], Q_SEVERITY_FR)
        self.assertEqual(turn2["slots"]["problem"], "toilettes")

    def test_ambiguous_si_reasks_confirm(self) -> None:
        slots = {"school": "Bonanjo", "problem": "eau", "severity": "grave"}
        recap = ask("confirm", slots, "fr")
        history = _hist("panne d'eau", recap)
        turn = guided_turn("si", history, CTX)
        assert turn is not None
        self.assertEqual(turn["status"], "ask")
        self.assertEqual(turn["step"], "confirm")

    def test_no_at_confirm_restarts(self) -> None:
        slots = {"school": "Bonanjo", "problem": "eau", "severity": "grave"}
        recap = ask("confirm", slots, "fr")
        history = _hist("panne d'eau", recap)
        turn = guided_turn("non", history, CTX)
        assert turn is not None
        self.assertEqual(turn["status"], "ask")
        self.assertEqual(turn["slots"], {})
        self.assertIn(Q_SCHOOL_FR, turn["question"])

    def test_trigger_prefills_known_school(self) -> None:
        turn = guided_turn("panne à Bonanjo : plus d'eau", None, CTX)
        assert turn is not None
        self.assertEqual(turn["slots"].get("school"), "École de Bonanjo")
        self.assertEqual(turn["slots"].get("problem"), "eau")
        self.assertEqual(turn["question"], Q_SEVERITY_FR)

    def test_non_report_returns_none(self) -> None:
        self.assertIsNone(
            guided_turn("quelles écoles sont suivies ?", None, CTX))

    def test_douala_questions(self) -> None:
        turn = guided_turn("je veux signaler une panne", None, CTX, lang="dua")
        assert turn is not None
        self.assertEqual(turn["question"], "Sukulu njika ?")
        self.assertEqual(ask("problem", None, "dua"),
                         "Probleme njika : madiba, toilettes, to fuite ?")
        slots = {"school": "Bonanjo", "problem": "eau", "severity": "grave"}
        self.assertIn("Na éé to si", ask("confirm", slots, "dua"))

    def test_build_report_text(self) -> None:
        text = build_report_text({"school": "Bonanjo", "problem": "fuite",
                                  "severity": "grave"})
        self.assertIn("Bonanjo", text)
        self.assertIn("fuite", text)
        self.assertIn("grave", text)


class StubLLM:
    """Provider scripté (miroir de test_agent_loop) + enregistrement."""

    def __init__(self, script: list[dict]):
        self.model = "stub"
        self.script = list(script)
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls += 1
        self.seen_messages.append(list(messages))
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        return {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}


def _say(text: str) -> dict:
    return {"raw": {"role": "assistant", "content": text}, "content": text,
            "tool_calls": []}


class GuidedIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_guided_report_never_calls_llm(self) -> None:
        stub = StubLLM([_say("injoignable")])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="je veux signaler une panne", context=CONTEXT, guided=True))
        self.assertEqual(stub.calls, 0)
        self.assertEqual(res.answer, Q_SCHOOL_FR)
        self.assertEqual(res.tools_executed, [])

    async def test_guided_false_is_normal_flow(self) -> None:
        stub = StubLLM([_say("bonjour à vous")])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="bonjour", context=CONTEXT, guided=False))
        self.assertEqual(stub.calls, 1)
        self.assertEqual(res.answer, "bonjour à vous")

    async def test_guided_absent_is_normal_flow(self) -> None:
        stub = StubLLM([_say("bonjour à vous")])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="je veux signaler une panne", context=CONTEXT))
        # guided absent : le LLM est sollicité (jamais le dialogue guidé).
        # Le recadrage force-outil du flux normal peut ajouter un appel.
        self.assertGreaterEqual(stub.calls, 1)
        self.assertTrue(res.answer.strip())
        self.assertNotEqual(res.answer, Q_SCHOOL_FR)

    async def test_guided_non_report_is_normal_flow(self) -> None:
        stub = StubLLM([_say("bonjour à vous")])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="bonjour", context=CONTEXT, guided=True))
        self.assertEqual(stub.calls, 1)
        self.assertEqual(res.answer, "bonjour à vous")

    async def test_guided_confirm_hands_off_to_normal_flow(self) -> None:
        slots = {"school": "Bonanjo", "problem": "fuite", "severity": "grave"}
        recap = ask("confirm", slots, "fr")
        history = _hist("je veux signaler une panne", Q_SCHOOL_FR,
                        "Bonanjo", Q_PROBLEM_FR,
                        "la pompe fuit", Q_SEVERITY_FR,
                        "oui", recap)
        stub = StubLLM([_say("signalement bien pris en compte")])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="oui", history=history, context=CONTEXT, guided=True))
        # Bascule flux normal : le LLM est sollicité (recadrage éventuel OK).
        self.assertGreaterEqual(stub.calls, 1)
        self.assertTrue(res.answer.strip())
        user_texts = [m.get("content", "") for m in stub.seen_messages[0]
                      if m.get("role") == "user"]
        self.assertTrue(any("Signaler une panne" in t for t in user_texts),
                        user_texts)
        self.assertTrue(any("Bonanjo" in t for t in user_texts), user_texts)


if __name__ == "__main__":
    unittest.main()
