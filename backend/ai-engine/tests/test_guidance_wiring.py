"""Câblage guidage : erreurs -> carte guidance, lieu flou -> suggestions."""
from __future__ import annotations

import unittest

from app.agent_loop import AgentLoop
from app.schemas import AgentChatRequest, AgentContext

CONTEXT = AgentContext(
    schools=[
        {"school_id": 1, "school_name": "École Publique de Bonanjo",
         "district": "Wouri"},
        {"school_id": 2, "school_name": "École de Nkol", "district": "Mvila"},
    ],
    incidents=[],
)

EMPTY = {"raw": {"role": "assistant", "content": ""}, "content": "",
         "tool_calls": []}


class SilentLLM:
    model = "stub"

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        return dict(EMPTY)

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        return {"role": "tool", "content": "{}"}


class GuidanceWiringTest(unittest.TestCase):
    def test_error_observation_yields_guidance_card(self) -> None:
        loop = AgentLoop.__new__(AgentLoop)
        cards = AgentLoop._build_cards(
            loop, [("district_alerts", {"error": "district inconnu"})])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "guidance")
        self.assertTrue(cards[0].data.get("actions"))


class PlaceSuggestionsWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_place_yields_suggestions_card(self) -> None:
        req = AgentChatRequest(message="Analyse l'école de Nkole",
                               context=CONTEXT)
        res = await AgentLoop(SilentLLM()).chat(req)
        types = [c.type for c in res.cards]
        self.assertIn("place_suggestions", types)

    async def test_plain_greeting_yields_no_place_card(self) -> None:
        req = AgentChatRequest(message="bonjour", context=CONTEXT)
        res = await AgentLoop(SilentLLM()).chat(req)
        types = [c.type for c in res.cards]
        self.assertNotIn("place_suggestions", types)

    async def test_unknown_marked_place_yields_samples_card(self) -> None:
        req = AgentChatRequest(message="Analyser l'école de Zzzzz",
                               context=CONTEXT)
        res = await AgentLoop(SilentLLM()).chat(req)
        cards = [c for c in res.cards if c.type == "place_suggestions"]
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0].data.get("ecoles_sample"))


if __name__ == "__main__":
    unittest.main()
