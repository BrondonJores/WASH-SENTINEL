"""Vision honnête : les providers lèvent, jamais de score 75.0 inventé.

MockTransport uniquement, aucun réseau. VISION_FALLBACK a été supprimé :
404/timeout/non-200/JSON-invalide lèvent une erreur FR actionnable.
"""
from __future__ import annotations

import unittest
from unittest import mock as _mock

import httpx

from app import providers as _providers
from app.providers import OllamaProvider, OpenAICompatibleProvider


def _mock_provider(provider_cls, handler, **kwargs):
    provider = provider_cls(base_url="http://llm-test:11434", model="test-model", **kwargs)
    provider._transport = httpx.MockTransport(handler)
    return provider


def _no_sleep():
    return _mock.patch("app.providers.asyncio.sleep", new=_mock.AsyncMock())


OLLAMA_VISION_OK = {"response": '{"is_wash_related": true, "visual_severity_score": 42.0}'}
OPENAI_VISION_OK = {"choices": [{"message": {"content": '{"is_wash_related": true}'}}]}


class VisionFallbackGoneTest(unittest.TestCase):
    def test_no_vision_fallback_symbol(self) -> None:
        self.assertFalse(hasattr(_providers, "VISION_FALLBACK"))


class OllamaVisionRaiseTest(unittest.IsolatedAsyncioTestCase):
    async def test_200_returns_parsed_json(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=OLLAMA_VISION_OK, request=request)

        provider = _mock_provider(OllamaProvider, handler, vision_model="moondream")
        data = await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        self.assertEqual(data["visual_severity_score"], 42.0)

    async def test_404_raises_with_pull_hint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"}, request=request)

        provider = _mock_provider(OllamaProvider, handler, vision_model="moondream")
        with self.assertRaises(RuntimeError) as ctx:
            await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        message = str(ctx.exception)
        self.assertIn("moondream", message)
        self.assertIn("ollama pull moondream", message)

    async def test_400_raises_not_fallback(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad request"}, request=request)

        provider = _mock_provider(OllamaProvider, handler, vision_model="moondream")
        with _no_sleep():
            with self.assertRaises(Exception):
                await provider.generate_vision_json("Analyse.", "aGVsbG8=")

    async def test_timeout_retries_then_raises(self) -> None:
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            raise httpx.ConnectTimeout("mock-timeout", request=request)

        provider = _mock_provider(OllamaProvider, handler, vision_model="moondream")
        with _no_sleep():
            with self.assertRaises(RuntimeError) as ctx:
                await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        self.assertEqual(len(calls), 3)
        self.assertIn("warmup", str(ctx.exception))

    async def test_invalid_json_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"response": "pas du json {{{"}, request=request)

        provider = _mock_provider(OllamaProvider, handler, vision_model="moondream")
        with self.assertRaises(RuntimeError) as ctx:
            await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        self.assertIn("moondream", str(ctx.exception))


class OpenAIVisionRaiseTest(unittest.IsolatedAsyncioTestCase):
    async def test_200_returns_parsed_json(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=OPENAI_VISION_OK, request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        data = await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        self.assertTrue(data["is_wash_related"])

    async def test_non_200_raises_with_model_and_hint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "bad key"}, request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler, vision_model="gpt-4o-mini")
        with _no_sleep():
            with self.assertRaises(RuntimeError) as ctx:
                await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        message = str(ctx.exception)
        self.assertIn("gpt-4o-mini", message)
        self.assertIn("401", message)

    async def test_timeout_retries_then_raises(self) -> None:
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            raise httpx.ConnectError("mock-down", request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        with _no_sleep():
            with self.assertRaises(RuntimeError):
                await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        self.assertEqual(len(calls), 3)

    async def test_malformed_200_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []}, request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler, vision_model="gpt-4o-mini")
        with self.assertRaises(RuntimeError) as ctx:
            await provider.generate_vision_json("Analyse.", "aGVsbG8=")
        self.assertIn("gpt-4o-mini", str(ctx.exception))


class EmbeddingExplicitTest(unittest.IsolatedAsyncioTestCase):
    async def test_ollama_success_returns_vector(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"embedding": [0.1, 0.2]}, request=request)

        provider = _mock_provider(OllamaProvider, handler)
        self.assertEqual(await provider.get_embedding("bonjour"), [0.1, 0.2])

    async def test_ollama_failure_raises_not_silent_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("mock-down", request=request)

        provider = _mock_provider(OllamaProvider, handler)
        with self.assertRaises(RuntimeError) as ctx:
            await provider.get_embedding("bonjour")
        self.assertIn("Embeddings indisponibles", str(ctx.exception))

    async def test_openai_success_returns_vector(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"embedding": [0.3]}]}, request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        self.assertEqual(await provider.get_embedding("bonjour"), [0.3])

    async def test_openai_failure_raises_not_silent_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"}, request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        with self.assertRaises(RuntimeError) as ctx:
            await provider.get_embedding("bonjour")
        self.assertIn("Embeddings indisponibles", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
