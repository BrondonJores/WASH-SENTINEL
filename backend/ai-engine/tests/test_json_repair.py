"""Réparation JSON : syntaxe tolérée, erreurs honnêtes, réessai unique."""
from __future__ import annotations

import json
import unittest

import httpx
from pydantic import BaseModel

from app.providers import (
    OllamaProvider,
    OpenAICompatibleProvider,
    parse_json_response,
    repair_json_response,
)


class Ping(BaseModel):
    status: str


def _mock_provider(provider_cls, handler, **kwargs):
    provider = provider_cls(base_url="http://llm-test:11434",
                            model="test-model", **kwargs)
    provider._transport = httpx.MockTransport(handler)
    return provider


def _ollama_json(payload: str) -> httpx.Response:
    return httpx.Response(
        200, json={"response": payload},
        request=httpx.Request("POST", "http://llm-test:11434/api/generate"),
    )


def _openai_json(payload: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": payload}}]},
        request=httpx.Request("POST", "http://llm-test:11434/chat/completions"),
    )


class RepairJsonResponseTest(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(repair_json_response('{"a": 1}'), {"a": 1})

    def test_markdown_fenced(self) -> None:
        raw = '```json\n{"status": "ok"}\n```'
        self.assertEqual(repair_json_response(raw), {"status": "ok"})

    def test_fence_without_language(self) -> None:
        raw = '```\n{"status": "ok"}\n```'
        self.assertEqual(repair_json_response(raw), {"status": "ok"})

    def test_leading_prose(self) -> None:
        raw = 'Voici le résultat : {"status": "ok"}'
        self.assertEqual(repair_json_response(raw), {"status": "ok"})

    def test_trailing_prose(self) -> None:
        raw = '{"status": "ok"} merci, à bientôt.'
        self.assertEqual(repair_json_response(raw), {"status": "ok"})

    def test_trailing_comma(self) -> None:
        raw = '{"status": "ok", "n": 3,}'
        self.assertEqual(repair_json_response(raw), {"status": "ok", "n": 3})

    def test_garbage_raises_original(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            repair_json_response("pas du json du tout {{{")

    def test_truncated_raises(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            repair_json_response('{"status": "ok"')


class ParseLegacyTest(unittest.TestCase):
    """parse_json_response() : comportement historique inchangé."""

    def test_plain(self) -> None:
        self.assertEqual(parse_json_response('{"a": 1}'), {"a": 1})

    def test_fenced(self) -> None:
        self.assertEqual(
            parse_json_response('```json\n{"a": 1}\n```'), {"a": 1})

    def test_trailing_prose_still_raises(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            parse_json_response('{"a": 1} et du texte')


class GenerateJsonRepairedTest(unittest.IsolatedAsyncioTestCase):
    async def test_noisy_answer_repaired_without_retry(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _ollama_json('Voici : {"status": "ok"}, merci.')

        provider = _mock_provider(OllamaProvider, handler)
        # generate_json brut échoue sur la prose autour...
        with self.assertRaises(json.JSONDecodeError):
            await provider.generate_json("ping", "")
        # ...mais la variante réparée récupère le JSON sans réessai.
        data = await provider.generate_json_repaired("ping", "")
        self.assertEqual(data, {"status": "ok"})
        self.assertEqual(len(calls), 2)

    async def test_trailing_prose_repaired(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _openai_json('{"status": "ok"} voilà.')

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        data = await provider.generate_json_repaired("ping", "")
        self.assertEqual(data, {"status": "ok"})

    async def test_truncated_then_retry_with_suffix(self) -> None:
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content.decode()))
            if len(bodies) == 1:
                return _ollama_json('{"status": "o')
            return _ollama_json('{"status": "ok"}')

        provider = _mock_provider(OllamaProvider, handler)
        data = await provider.generate_json_repaired("ping", "")
        self.assertEqual(data, {"status": "ok"})
        self.assertEqual(len(bodies), 2)
        self.assertIn("JSON only", bodies[1]["prompt"])

    async def test_persistent_garbage_raises_after_single_retry(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _ollama_json("pas du json {{{")

        provider = _mock_provider(OllamaProvider, handler)
        with self.assertRaises(json.JSONDecodeError):
            await provider.generate_json_repaired("ping", "")
        self.assertEqual(len(calls), 2)

    async def test_validator_rejection_retries_then_honest_error(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _ollama_json('{"wrong": "shape"}')

        provider = _mock_provider(OllamaProvider, handler)
        with self.assertRaises(RuntimeError) as ctx:
            await provider.generate_json_repaired("ping", "", validator=Ping)
        self.assertIn("inexploitable", str(ctx.exception))
        self.assertEqual(len(calls), 2)

    async def test_validator_accepts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _ollama_json('{"status": "ok"}')

        provider = _mock_provider(OllamaProvider, handler)
        data = await provider.generate_json_repaired(
            "ping", "", validator=lambda d: d.get("status") == "ok")
        self.assertEqual(data, {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
