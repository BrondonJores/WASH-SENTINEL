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


# --- Ajouts robustesse : retry exponentiel borné + warmup (mock transport uniquement) ---
from unittest import mock as _mock

from app import providers as _providers
from app.providers import OllamaProvider, OpenAICompatibleProvider


def _mock_provider(provider_cls, handler, **kwargs):
    """Provider dont le HTTP passe par un httpx.MockTransport (aucun réseau réel)."""
    provider = provider_cls(base_url="http://llm-test:11434", model="test-model", **kwargs)
    provider._transport = httpx.MockTransport(handler)
    return provider


def _no_sleep():
    """Neutralise le backoff (vitesse des tests) sans toucher au comptage des appels."""
    return _mock.patch("app.providers.asyncio.sleep", new=_mock.AsyncMock())


class RetryConstantsTest(unittest.TestCase):
    def test_politique_bornee_3_essais(self) -> None:
        self.assertEqual(_providers.RETRY_MAX_ATTEMPTS, 3)
        self.assertEqual(tuple(_providers.RETRY_BACKOFF_SECONDS[:2]), (1.0, 2.0))
        for status in (408, 429, 500, 502, 503, 504):
            self.assertIn(status, _providers.RETRYABLE_STATUS_CODES)
        for status in (400, 401, 403, 404):
            self.assertNotIn(status, _providers.RETRYABLE_STATUS_CODES)


class RetryTransientThenSuccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_429_puis_succes_2_appels(self) -> None:
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, json={"error": "rate limited"}, request=request)
            return httpx.Response(200, json={"response": '{"status": "ok"}'}, request=request)

        provider = _mock_provider(OllamaProvider, handler)
        with _no_sleep():
            data = await provider.generate_json('Reponds {"status": "ok"}')
        self.assertEqual(data, {"status": "ok"})
        self.assertEqual(len(calls), 2)

    async def test_500_puis_succes_openai(self) -> None:
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(500, json={"error": "boom"}, request=request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"status": "ok"}'}}]},
                request=request,
            )

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        with _no_sleep():
            data = await provider.generate_json("ping")
        self.assertEqual(data, {"status": "ok"})
        self.assertEqual(len(calls), 2)


class RetryExhaustedTest(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_persistant_3_tentatives_message_actionnable(self) -> None:
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            raise httpx.ConnectTimeout("mock-timeout", request=request)

        provider = _mock_provider(OllamaProvider, handler)
        with _no_sleep():
            with self.assertRaises(RuntimeError) as ctx:
                await provider.generate_json("ping")
        self.assertEqual(len(calls), 3)
        message = str(ctx.exception)
        self.assertIn("3 tentatives", message)
        self.assertIn("warmup", message)


class NoRetryOnBusinessErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_400_metier_un_seul_appel_ollama(self) -> None:
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(400, json={"error": "no tools"}, request=request)

        provider = _mock_provider(OllamaProvider, handler)
        with _no_sleep() as sleep_mock:
            with self.assertRaises(httpx.HTTPStatusError):
                await provider.generate_json("ping")
        self.assertEqual(len(calls), 1)
        sleep_mock.assert_not_called()

    async def test_400_metier_un_seul_appel_openai(self) -> None:
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(400, json={"error": {"message": "bad request"}}, request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        with _no_sleep() as sleep_mock:
            with self.assertRaises(httpx.HTTPStatusError):
                await provider.generate_json("ping")
        self.assertEqual(len(calls), 1)
        sleep_mock.assert_not_called()


class WarmupTest(unittest.IsolatedAsyncioTestCase):
    async def test_warmup_ok_ollama(self) -> None:
        seen: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"models": []}, request=request)

        provider = _mock_provider(OllamaProvider, handler)
        result = await provider.warmup()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])
        self.assertEqual(seen[0].url.path, "/api/tags")

    async def test_warmup_ko_connexion_ollama(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("mock-down", request=request)

        provider = _mock_provider(OllamaProvider, handler)
        result = await provider.warmup()
        self.assertFalse(result["ok"])
        self.assertIn("Connexion impossible", result["error"])

    async def test_warmup_ok_openai(self) -> None:
        seen: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": []}, request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        result = await provider.warmup()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])
        self.assertEqual(seen[0].url.path, "/models")

    async def test_warmup_ko_timeout_openai(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("mock-timeout", request=request)

        provider = _mock_provider(OpenAICompatibleProvider, handler)
        result = await provider.warmup()
        self.assertFalse(result["ok"])
        self.assertIn("Délai dépassé", result["error"])
