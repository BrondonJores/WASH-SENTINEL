"""Robustesse boucle : budget temps, abstention guidée, suivis, outils compacts."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.agent_loop import (
    AgentLoop,
    compact_tools,
    followup_hint,
    resolve_place,
)
from app.agent_tools import AGENT_TOOLS
from app.schemas import AgentChatRequest, AgentContext, ChatTurn

CONTEXT = AgentContext(
    schools=[
        {"school_id": 1, "school_name": "École Publique de Bonanjo",
         "district": "Wouri"},
        {"school_id": 2, "school_name": "École de Nkol", "district": "Mvila"},
    ],
    incidents=[
        {"id": 1, "school_name": "École de Nkol", "district": "Mvila",
         "urgency": "high"},
    ],
)

EMPTY = {"raw": {"role": "assistant", "content": ""}, "content": "",
         "tool_calls": []}
FINAL_OK = {"raw": {"role": "assistant", "content": "ok"}, "content": "ok",
            "tool_calls": []}


class RecordingLLM:
    def __init__(self, model: str, script: list[dict]):
        self.model = model
        self.script = list(script)
        self.calls = 0
        self.seen_messages = None
        self.seen_tools = None

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls += 1
        self.seen_messages = list(messages)
        self.seen_tools = list(tools or [])
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        return {"role": "tool",
                "content": json.dumps(result, ensure_ascii=False)}


def _req(message: str, history=None) -> AgentChatRequest:
    return AgentChatRequest(message=message, history=history or [],
                            context=CONTEXT)


class BudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_over_budget_returns_fallback_without_llm(self) -> None:
        llm = RecordingLLM("llama3.2:3b", [FINAL_OK])
        with patch("app.agent_loop.RUN_BUDGET_S", -1.0):
            res = await AgentLoop(llm).chat(_req("résume"))
        self.assertEqual(llm.calls, 0)
        self.assertTrue(res.answer.startswith("Je n'ai pas pu récupérer"))


class AbstentionDistrictsTest(unittest.IsolatedAsyncioTestCase):
    async def test_abstention_lists_known_districts(self) -> None:
        llm = RecordingLLM("stub", [EMPTY])
        res = await AgentLoop(llm).chat(_req("résume le district"))
        self.assertIn("Mvila", res.answer)
        self.assertIn("Wouri", res.answer)


class FollowupHintTest(unittest.TestCase):
    def test_resolve_place_district(self) -> None:
        ctx = CONTEXT.model_dump()
        self.assertEqual(resolve_place("Je parle de la Mvila", ctx),
                         ("district", "Mvila"))

    def test_resolve_place_school_token(self) -> None:
        ctx = CONTEXT.model_dump()
        kind, label = resolve_place("et pour Nkol ?", ctx)
        self.assertEqual(kind, "school")
        self.assertIn("Nkol", label)

    def test_resolve_place_unknown(self) -> None:
        self.assertIsNone(
            resolve_place("et demain ?", CONTEXT.model_dump()))

    def test_hint_only_for_followup_with_place(self) -> None:
        ctx = CONTEXT.model_dump()
        hint = followup_hint("Je parle de la Mvila", ctx)
        self.assertIn("Mvila", hint)
        self.assertIn("Reprends ma demande", hint)
        self.assertEqual(followup_hint("et demain ?", ctx), "")
        self.assertEqual(followup_hint("Résume le district Mvila", ctx), "")


class FollowupIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_hint_injected_on_vague_followup(self) -> None:
        llm = RecordingLLM("stub", [FINAL_OK])
        history = [ChatTurn(role="user", content="Résume en briefing"),
                   ChatTurn(role="assistant", content="Lequel ?")]
        await AgentLoop(llm).chat(_req("Je parle de la Mvila", history))
        user_msg = llm.seen_messages[-1]["content"]
        self.assertIn("Précision de suivi", user_msg)
        self.assertIn("Mvila", user_msg)

    async def test_no_hint_without_history(self) -> None:
        llm = RecordingLLM("stub", [FINAL_OK])
        await AgentLoop(llm).chat(_req("Je parle de la Mvila"))
        self.assertNotIn("Précision de suivi",
                         llm.seen_messages[-1]["content"])


class CompactToolsTest(unittest.TestCase):
    def test_small_model_gets_shorter_descriptions(self) -> None:
        compacted = compact_tools(AGENT_TOOLS, "llama3.2:3b")
        self.assertEqual(len(compacted), len(AGENT_TOOLS))
        orig = [t["function"]["description"] for t in AGENT_TOOLS]
        short = [t["function"]["description"] for t in compacted]
        self.assertLess(sum(map(len, short)), sum(map(len, orig)))
        self.assertTrue(any(s < o for s, o in zip(short, orig)))
        names_o = [t["function"]["name"] for t in AGENT_TOOLS]
        names_s = [t["function"]["name"] for t in compacted]
        self.assertEqual(names_o, names_s)

    def test_big_model_unchanged(self) -> None:
        self.assertIs(compact_tools(AGENT_TOOLS, "llama3.1:70b"), AGENT_TOOLS)


class CompactIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_loop_sends_compact_tools_to_small_model(self) -> None:
        llm = RecordingLLM("qwen2.5-coder:3b", [FINAL_OK])
        await AgentLoop(llm).chat(_req("bonjour"))
        total_short = sum(len(t["function"]["description"])
                          for t in llm.seen_tools)
        total_full = sum(len(t["function"]["description"]) for t in AGENT_TOOLS)
        # "bonjour" ne route pas "list" : jeu complet, mais compacté.
        self.assertEqual(len(llm.seen_tools), len(AGENT_TOOLS))
        self.assertLess(total_short, total_full)


if __name__ == "__main__":
    unittest.main()
