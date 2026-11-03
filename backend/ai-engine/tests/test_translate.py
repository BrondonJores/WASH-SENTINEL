"""Traduction d'affichage : 1 appel LLM par lot, alignement, replis sûrs."""
from __future__ import annotations

import unittest

from app.translator import (
    TRANSLATE_MAX_CHARS,
    TRANSLATE_MAX_TEXTS,
    WashTranslator,
    _parse,
)


class FakeLLM:
    def __init__(self, content: str, fail: bool = False):
        self.content = content
        self.fail = fail
        self.calls = 0

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls += 1
        if self.fail:
            raise RuntimeError("cloud down")
        return {"content": self.content, "tool_calls": []}


class ParseTest(unittest.TestCase):
    def test_aligned(self) -> None:
        self.assertEqual(_parse("1. Pump broken\n2. Flooded yard.", ["a", "b"]),
                         ["Pump broken", "Flooded yard."])

    def test_missing_line_falls_back_to_original(self) -> None:
        self.assertEqual(_parse("2. Flooded yard.", ["Pompe cassée", "Cour inondée"]),
                         ["Pompe cassée", "Flooded yard."])

    def test_garbage_falls_back(self) -> None:
        self.assertEqual(_parse("n'importe quoi", ["Pompe cassée"]), ["Pompe cassée"])

    def test_out_of_range_ignored(self) -> None:
        self.assertEqual(_parse("9. X\n1. Pump broken", ["Pompe cassée"]), ["Pump broken"])


class TranslateTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_single_call(self) -> None:
        llm = FakeLLM("1. Broken pump\n2. Flooded courtyard")
        out = await WashTranslator(llm).translate(["Pompe cassée", "Cour inondée"], "en")
        self.assertEqual(out, ["Broken pump", "Flooded courtyard"])
        self.assertEqual(llm.calls, 1)

    async def test_llm_failure_returns_originals(self) -> None:
        llm = FakeLLM("", fail=True)
        self.assertEqual(await WashTranslator(llm).translate(["Pompe cassée"], "en"),
                         ["Pompe cassée"])

    async def test_unknown_target_no_call(self) -> None:
        llm = FakeLLM("1. X")
        self.assertEqual(await WashTranslator(llm).translate(["Pompe"], "xx"), ["Pompe"])
        self.assertEqual(llm.calls, 0)

    async def test_empty_no_call(self) -> None:
        llm = FakeLLM("1. X")
        self.assertEqual(await WashTranslator(llm).translate(["", "  "], "en"), ["", "  "])
        self.assertEqual(llm.calls, 0)

    async def test_caps_respected(self) -> None:
        many = ["a"] * (TRANSLATE_MAX_TEXTS + 5)
        llm = FakeLLM("\n".join(f"{i + 1}. b" for i in range(TRANSLATE_MAX_TEXTS)))
        out = await WashTranslator(llm).translate(many, "en")
        self.assertEqual(len(out), len(many))
        self.assertEqual(out[TRANSLATE_MAX_TEXTS:], ["a"] * 5)
        long = "x" * (TRANSLATE_MAX_CHARS + 100)
        llm2 = FakeLLM("1. y")
        out2 = await WashTranslator(llm2).translate([long], "en")
        self.assertEqual(out2, ["y"])


if __name__ == "__main__":
    unittest.main()
