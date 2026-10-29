"""Ollama : les erreurs HTTP doivent exposer la vraie raison (corps réponse)."""
from __future__ import annotations

import unittest

import httpx

from app.providers import raise_for_ollama


def _resp(status: int, body: str = "") -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        request=httpx.Request("POST", "http://ollama:11434/api/chat"),
    )


class RaiseForOllamaTest(unittest.TestCase):
    def test_ok_passes(self) -> None:
        raise_for_ollama(_resp(200, '{"ok": true}'), "qwen2.5-coder:3b")

    def test_404_actionable(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            raise_for_ollama(_resp(404), "llama3.2:3b")
        self.assertIn("llama3.2:3b", str(ctx.exception))

    def test_500_surfaces_body(self) -> None:
        with self.assertRaises(httpx.HTTPStatusError) as ctx:
            raise_for_ollama(_resp(500, '{"error": "boom-moteur"}'), "qwen2.5-coder:3b")
        self.assertIn("boom-moteur", str(ctx.exception))
        self.assertIn("500", str(ctx.exception))

    def test_400_keeps_status_for_tools_fallback(self) -> None:
        with self.assertRaises(httpx.HTTPStatusError) as ctx:
            raise_for_ollama(_resp(400, '{"error": "no tools"}'), "gemma3:1b")
        self.assertEqual(ctx.exception.response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
