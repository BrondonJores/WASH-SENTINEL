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
    MetaTranscribeProvider,
    stt_from_headers,
    stt_from_profile,
)
from app.voice_service import VoiceService

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
        self.assertIsInstance(provider, MetaTranscribeProvider)
        self.assertEqual(provider.driver_name, "meta_transcribe")
        self.assertEqual(provider.base_url, META_BASE)
        self.assertEqual(provider.model, META_MODEL)

    def test_meta_defaults_without_mapping(self) -> None:
        provider = MetaTranscribeProvider(api_key="K")
        self.assertEqual(provider.base_url, MetaTranscribeProvider.META_BASE_URL)
        self.assertEqual(provider.model, MetaTranscribeProvider.META_MODEL)
        self.assertEqual(provider.driver_name, "meta_transcribe")

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


class FakeMetaCloud(MetaTranscribeProvider):
    """Faux cloud Meta : canned, aucun réseau (sous-classe pour isinstance)."""

    def __init__(self, transcript="", detected=None, exc=None):
        super().__init__(api_key="K")
        self._transcript = transcript
        self._detected = detected
        self._exc = exc
        self.calls = 0

    def transcribe(self, audio_bytes, filename, language):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        res = {"transcript": self._transcript, "language": language,
               "language_effective": "auto"}
        if self._detected is not None:
            res["detected_language"] = self._detected
        return res


def _transcribe(provider, language):
    with patch("app.voice_service._probe_duration", return_value=None):
        return VoiceService().transcribe(b"RIFFfake", "a.ogg", language, stt=provider)


class MetaWiringTest(unittest.TestCase):
    def test_direct_path_honors_detected_language(self) -> None:
        res = _transcribe(FakeMetaCloud("water leak", detected="en"), "fr")
        self.assertEqual(res.transcript, "water leak")
        self.assertEqual(res.language_detected, "en")
        self.assertEqual(res.driver, "meta_transcribe")

    def test_direct_path_falls_back_to_requested_language(self) -> None:
        res = _transcribe(FakeMetaCloud("fuite robinet"), "fr")
        self.assertEqual(res.language_detected, "fr")

    def test_cascade_tries_cloud_first(self) -> None:
        cloud = FakeMetaCloud("plus d'eau", detected="fr")
        with patch("app.voice_service._local_whisper_provider") as w, \
                patch("app.voice_service._local_omni_provider") as o:
            res = _transcribe(cloud, "dua_Latn")
        self.assertEqual(res.transcript, "plus d'eau")
        self.assertEqual(res.driver, "meta_transcribe")
        self.assertEqual(res.detection.get("reason"), "cloud-first")
        w.assert_not_called()
        o.assert_not_called()

    def test_cascade_falls_back_to_locals_when_cloud_fails(self) -> None:
        class FakeOmni:
            driver_name = "omnilingual_onnx"

            def __init__(self, transcript=""):
                self.transcript = transcript

            def transcribe(self, audio_bytes, filename, language):
                return {"transcript": self.transcript, "language": language,
                        "language_effective": language}

        cloud = FakeMetaCloud(exc=RuntimeError("réseau coupé (simulé)"))
        omni = FakeOmni(transcript="transcript local")
        with patch("app.voice_service._local_whisper_provider", return_value=None), \
                patch("app.voice_service._local_omni_provider", return_value=omni):
            res = _transcribe(cloud, "dua_Latn")
        self.assertEqual(res.transcript, "transcript local")
        self.assertNotEqual(res.detection.get("reason"), "cloud-first")


if __name__ == "__main__":
    unittest.main()
