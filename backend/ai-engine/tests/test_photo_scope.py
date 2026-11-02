"""Périmètre photo + cohérence texte/cartes (non-régression prod).

BUG 1 : « Qu'est-ce que tu vois ? » + photo (même hors sujet WASH)
déclenchait une carte district/synthèse non demandée (« 11 incidents
ouverts... »). Image jointe + question portant sur l'image seule ->
périmètre PHOTO : carte photo_analysis UNIQUEMENT, aucun outil, synthèse
= commentaire de la photo seule. Question mixte explicite (« analyse
cette photo et résume Mvila ») : les deux périmètres restent autorisés.

BUG 2 : la synthèse disait « 1 295 élèves » (vieux total sommé) alors que
la carte affichait « 1 145 » (max unifié). Les résumés textuels utilisent
les valeurs unifiées *_max (repli legacy si absent).

Lancer depuis backend/ai-engine : ./.venv/bin/python -m unittest
"""
from __future__ import annotations

import base64
import json
import unittest

from app.agent_loop import (
    AgentLoop,
    _summarize_district,
    is_photo_only_scope,
    is_photo_question,
)
from app.agent_tools import TOOL_EXECUTORS
from app.schemas import AgentChatRequest, AgentContext

NGOK = "École Rurale de Ngok"
KRIBI = "École de Kribi Centre"

CONTEXT = AgentContext(
    schools=[
        {"school_id": 1, "school_name": NGOK, "district": "Mvila"},
        {"school_id": 2, "school_name": KRIBI, "district": "Océan"},
    ],
    incidents=[
        {"id": 1, "school_id": 1, "school_name": NGOK, "district": "Mvila",
         "title": "Pompe cassée", "urgency": "high",
         "affected_students": 120, "status": "open"},
        {"id": 2, "school_id": 2, "school_name": KRIBI, "district": "Océan",
         "title": "Fuite robinet", "urgency": "critical",
         "affected_students": 300, "status": "open"},
    ],
)
CTX = CONTEXT.model_dump()

SMALL_B64 = base64.b64encode(b"fake-image-bytes").decode("ascii")

VISION_DICT = {
    "is_wash_related": True,
    "infrastructure_detected": "Pompe manuelle India Mark II",
    "visible_damage": "Fissure nette sur le conduit",
    "visual_severity_score": 72.0,
    "health_hazard_detected": True,
    "technician_notes": "Isoler la pompe et purger le circuit.",
}

OFFTOPIC_VISION_DICT = {"is_wash_related": False}


def _call(name: str, args: dict | None = None) -> dict:
    return {"raw": {"role": "assistant", "content": ""}, "content": "",
            "tool_calls": [{"id": "1", "name": name,
                            "arguments": args or {}}]}


def _text(content: str) -> dict:
    return {"raw": {"role": "assistant", "content": content},
            "content": content, "tool_calls": []}


class ScriptVisionStub:
    """Stub vision scriptée + réponses chat scriptées (texte seul)."""

    def __init__(self, vision_dict: dict, replies: list[dict]):
        self.model = "stub"
        self.vision_dict = vision_dict
        self.replies = list(replies)
        self.vision_calls = 0
        self.chat_calls = 0
        self.seen_messages = None
        self.seen_tools = None

    async def generate_vision_json(self, prompt, image_base64, system=""):
        self.vision_calls += 1
        return dict(self.vision_dict)

    async def chat(self, messages, tools=None):
        self.chat_calls += 1
        self.seen_messages = list(messages)
        self.seen_tools = tools
        if len(self.replies) > 1:
            return dict(self.replies.pop(0))
        return dict(self.replies[0])

    def format_tool_result(self, name, result, call_id=None):
        return {"role": "tool",
                "content": json.dumps(result, ensure_ascii=False)}


class PhotoOnlyDetectionTest(unittest.TestCase):
    def test_photo_questions_fr(self) -> None:
        for message in ("Qu'est-ce que tu vois ?", "que vois-tu ?",
                        "analyse cette photo", "c'est quoi ?",
                        "décris cette image", "tu en penses quoi ?",
                        "montre-moi ce que tu vois sur cette photo",
                        "", "?", "et ça ?"):
            with self.subTest(message=message):
                self.assertTrue(is_photo_question(message), message)
                self.assertTrue(
                    is_photo_only_scope(message, CTX, has_image=True),
                    message)

    def test_photo_questions_en(self) -> None:
        for message in ("what do you see?", "what is this?",
                        "what's that?", "describe this photo"):
            with self.subTest(message=message):
                self.assertTrue(is_photo_question(message), message)
                self.assertTrue(
                    is_photo_only_scope(message, CTX, has_image=True),
                    message)

    def test_mixed_or_data_questions_not_photo_only(self) -> None:
        for message in ("Analyse cette photo et résume Mvila",
                        "résume Mvila",
                        "Résume le district de Mvila",
                        "compare Ngok et Kribi",
                        "décris les interventions d'hier"):
            with self.subTest(message=message):
                self.assertFalse(
                    is_photo_only_scope(message, CTX, has_image=True),
                    message)

    def test_same_question_without_image_is_not_photo_only(self) -> None:
        self.assertFalse(
            is_photo_only_scope("Qu'est-ce que tu vois ?", CTX,
                                has_image=False))


class PhotoOnlyChatTest(unittest.IsolatedAsyncioTestCase):
    async def test_bare_photo_gives_single_photo_card(self) -> None:
        stub = ScriptVisionStub(VISION_DICT, [
            _call("summarize_district"),
            _text("Pompe fissurée sur la photo."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="", context=CONTEXT, image_base64=SMALL_B64))
        self.assertEqual(res.tools_executed, [])
        self.assertEqual([c.type for c in res.cards], ["photo_analysis"])
        self.assertEqual(res.answer, "Pompe fissurée sur la photo.")

    async def test_what_do_you_see_has_no_district_card(self) -> None:
        stub = ScriptVisionStub(VISION_DICT, [
            _call("summarize_district"),
            _text("Je vois une pompe fissurée."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="Qu'est-ce que tu vois ?", context=CONTEXT,
            image_base64=SMALL_B64))
        self.assertEqual(stub.seen_tools, [])
        self.assertEqual(res.tools_executed, [])
        self.assertEqual([c.type for c in res.cards], ["photo_analysis"])
        self.assertEqual(res.answer, "Je vois une pompe fissurée.")

    async def test_english_photo_only(self) -> None:
        stub = ScriptVisionStub(VISION_DICT, [
            _call("territory_overview", {"district": "Mvila"}),
            _text("I see a cracked pump."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="What do you see?", context=CONTEXT,
            image_base64=SMALL_B64))
        self.assertEqual(res.tools_executed, [])
        self.assertEqual([c.type for c in res.cards], ["photo_analysis"])
        self.assertEqual(res.answer, "I see a cracked pump.")

    async def test_mixed_explicit_allows_both_perimeters(self) -> None:
        stub = ScriptVisionStub(VISION_DICT, [
            _call("summarize_district"),
            _text("Voici Mvila et le commentaire photo."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="Analyse cette photo et résume Mvila",
            context=CONTEXT, image_base64=SMALL_B64))
        self.assertEqual(res.tools_executed, ["summarize_district"])
        self.assertEqual([c.type for c in res.cards],
                         ["photo_analysis", "district_summary"])

    async def test_offtopic_photo_only_with_guidance(self) -> None:
        stub = ScriptVisionStub(OFFTOPIC_VISION_DICT, [
            _text("Je ne vois aucun équipement WASH."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="Qu'est-ce que tu vois ?", context=CONTEXT,
            image_base64=SMALL_B64))
        self.assertEqual(res.tools_executed, [])
        self.assertEqual([c.type for c in res.cards], ["photo_analysis"])
        self.assertFalse(res.cards[0].data["is_wash_related"])
        # Un seul appel chat : le « aucun » du commentaire photo ne
        # déclenche pas de recadrage vers les outils de données.
        self.assertEqual(stub.chat_calls, 1)
        user_msg = stub.seen_messages[-1]["content"]
        self.assertIn("hors sujet", user_msg)

    async def test_district_without_photo_unchanged(self) -> None:
        stub = ScriptVisionStub(VISION_DICT, [
            _call("summarize_district"),
            _text("Voici le district de Mvila."),
        ])
        res = await AgentLoop(stub).chat(AgentChatRequest(
            message="Résume le district de Mvila", context=CONTEXT))
        self.assertEqual(res.tools_executed, ["summarize_district"])
        self.assertEqual([c.type for c in res.cards], ["district_summary"])


class UnifiedPupilsTextTest(unittest.TestCase):
    def test_district_summary_uses_unified_max(self) -> None:
        text = _summarize_district({
            "open_incidents": 11, "by_urgency": {"critical": 2},
            "by_category": {"water_point": 11},
            "total_affected_students": 1295,
            "total_affected_students_max": 1145,
            "schools_involved": ["A", "B"]})
        self.assertIn("1 145", text)
        self.assertNotIn("1 295", text)
        self.assertNotIn("1295", text)

    def test_district_summary_legacy_fallback(self) -> None:
        text = _summarize_district({
            "open_incidents": 3, "by_urgency": {}, "by_category": {},
            "total_affected_students": 645,
            "schools_involved": ["A"]})
        self.assertIn("645", text)

    def test_briefing_cover_uses_unified_max(self) -> None:
        ctx = {
            "schools": [{"school_id": 1, "school_name": "E1",
                         "district": "Wouri"}],
            "incidents": [
                {"id": 1, "school_id": 1, "school_name": "E1",
                 "district": "Wouri", "title": "Pompe cassée",
                 "status": "reported", "urgency": "critical",
                 "affected_students": 450,
                 "reported_at": "2026-09-01T00:00:00Z"},
                {"id": 2, "school_id": 1, "school_name": "E1",
                 "district": "Wouri", "title": "Fuite",
                 "status": "in_progress", "urgency": "medium",
                 "affected_students": 50,
                 "reported_at": "2026-10-28T00:00:00Z"},
            ],
        }
        cover = TOOL_EXECUTORS["build_briefing"]({}, ctx)["slides"][0]
        pupils = next(s for s in cover["stats"]
                      if s["label"] == "Élèves affectés")
        # Max unifié (450), pas la somme legacy (500).
        self.assertEqual(pupils["value"], "450")


if __name__ == "__main__":
    unittest.main()
