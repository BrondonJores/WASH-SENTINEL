"""Driver meta_transcribe : Meta Muse Transcribe via contrat OpenAI-compatible.

AUCUN appel réseau réel (httpx.Client patché). Modèle :
muse-voice-transcribe-1.0 sur https://api.meta.ai/v1/audio/transcriptions.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.stt_providers import (
    STT_PROVIDER_TYPES,
    CloudWhisperProvider,
    stt_from_headers,
    stt_from_profile,
)

META_BASE = "https://api.meta.ai/v1"
META_MODEL = "muse-voice-transcribe-1.0"


def _run(provider: CloudWhisperProvider, payload: object, language: str = "fr"):
    """Transcrit avec un client HTTP faké ; retourne (résultat, appel)."""
    seen: dict = {}
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status.return_value = None

    def fake_post(url, headers=None, files=None, data=None):
        seen.update({"url": url, "headers": headers, "files": files, "data": data})
        return mock_resp

    mock_client.post.side_effect = fake_post
    with patch("app.stt_providers.httpx.Client", return_value=mock_client):
        res = provider.transcribe(b"xx", "a.ogg", language)
    return res, seen


def _meta_provider(**over) -> CloudWhisperProvider:
    args = {"base_url": META_BASE, "model": META_MODEL, "api_key": "K"}
    args.update(over)
    return CloudWhisperProvider(**args)


class MetaTranscribeTest(unittest.TestCase):
    def test_registry_resolves_alias(self) -> None:
        provider = stt_from_profile({
            "driver": "meta_transcribe", "base_url": META_BASE,
            "model": META_MODEL, "api_key": "K",
        })
        self.assertIsInstance(provider, CloudWhisperProvider)
        self.assertEqual(provider.base_url, META_BASE)
        self.assertEqual(provider.model, META_MODEL)

    def test_headers_resolve_alias(self) -> None:
        provider = stt_from_headers({
            "x-stt-driver": "meta_transcribe",
            "x-stt-base-url": META_BASE,
            "x-stt-model": META_MODEL,
        })
        self.assertIsInstance(provider, CloudWhisperProvider)
        self.assertEqual(provider.model, META_MODEL)

    def test_posts_openai_compatible_payload(self) -> None:
        _, seen = _run(_meta_provider(), {"text": "bonjour"})
        self.assertEqual(seen["url"], f"{META_BASE}/audio/transcriptions")
        self.assertEqual(seen["data"]["model"], META_MODEL)
        self.assertEqual(seen["headers"]["Authorization"], "Bearer K")
        self.assertIn("file", seen["files"])

    def test_parses_text_response(self) -> None:
        res, _ = _run(_meta_provider(), {"text": "fuite robinet"})
        self.assertEqual(res["transcript"], "fuite robinet")
        self.assertNotIn("detected_language", res)

    def test_parses_transcript_fallback(self) -> None:
        res, _ = _run(_meta_provider(), {"transcript": "plus d'eau"})
        self.assertEqual(res["transcript"], "plus d'eau")

    def test_detected_language_passthrough(self) -> None:
        for key in ("language", "detected_language", "language_detected"):
            with self.subTest(key=key):
                res, _ = _run(_meta_provider(), {"text": "x", key: "fr"})
                self.assertEqual(res["detected_language"], "fr")

    def test_non_dict_response_yields_empty_transcript(self) -> None:
        res, _ = _run(_meta_provider(), ["oops"])
        self.assertEqual(res["transcript"], "")

    def test_provider_types_entry_with_meta_defaults(self) -> None:
        entry = next(e for e in STT_PROVIDER_TYPES if e["id"] == "meta_transcribe")
        self.assertTrue(entry["api_key_required"])
        defaults = {f["name"]: f["default"] for f in entry["fields"]}
        self.assertEqual(defaults["base_url"], META_BASE)
        self.assertEqual(defaults["model"], META_MODEL)
        self.assertIn("muse-voice-transcribe-1.0", entry["description"])


if __name__ == "__main__":
    unittest.main()
