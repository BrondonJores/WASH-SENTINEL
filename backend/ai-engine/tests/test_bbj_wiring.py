"""Câblage du pont bbj : transcription ghomala' -> pivot FR -> extraction.

Avant ce câblage, bridge_bbj_to_french n'était appelé NULLE PART : le
transcript bbj partait brut au LLM (charabia, incidents poubelles).
Ici : transcript original conservé (audit), pivot FR pour travailler,
needs_human_check toujours vrai (validation locuteur natif).
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

# Stub FastAPI minimal : le venv de test n'a pas fastapi (même pattern
# que tests/test_transcribe_limit.py) — requis pour importer app.main.
try:
    import fastapi  # noqa: F401
except ModuleNotFoundError:
    _f = types.ModuleType("fastapi")

    class _HTTPException(Exception):
        def __init__(self, status_code: int, detail: str | None = None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class _FastAPI:
        def __init__(self, *a, **k):
            pass

        def add_middleware(self, *a, **k):
            pass

        def get(self, *a, **k):
            return lambda fn: fn

        def post(self, *a, **k):
            return lambda fn: fn

    _f.FastAPI = _FastAPI
    _f.File = lambda *a, **k: None
    _f.Form = lambda *a, **k: None
    _f.HTTPException = _HTTPException
    _f.Request = object
    _f.UploadFile = object
    sys.modules["fastapi"] = _f
    _mw = types.ModuleType("fastapi.middleware")
    _cors = types.ModuleType("fastapi.middleware.cors")
    _cors.CORSMiddleware = object
    sys.modules["fastapi.middleware"] = _mw
    sys.modules["fastapi.middleware.cors"] = _cors

from app.main import _extract_text  # noqa: E402
from app.voice_service import VoiceService  # noqa: E402


class FakeOmni:
    driver_name = "omnilingual_onnx"

    def __init__(self, transcript: str):
        self._transcript = transcript

    def transcribe(self, audio_bytes, filename, language):
        return {
            "transcript": self._transcript,
            "language": language,
            "language_effective": language,
        }


class FakeFr:
    driver_name = "stub_fr"

    def transcribe(self, audio_bytes, filename, language):
        return {"transcript": "fuite robinet bloc A", "language": language}


class BbjWiringTest(unittest.TestCase):
    def test_bbj_transcription_keeps_original_and_builds_pivot(self) -> None:
        with patch("app.voice_service._probe_duration", return_value=None), \
                patch("app.voice_service._local_whisper_provider", return_value=None):
            res = VoiceService().transcribe(
                b"RIFFfake", "a.ogg", "bbj_Latn",
                stt=FakeOmni("da cas bolilam dmla"))
        self.assertEqual(res.transcript, "da cas bolilam dmla")
        self.assertIsNotNone(res.french_pivot)
        self.assertIn("ghomala'", res.french_pivot)
        self.assertIsNotNone(res.bridge)
        self.assertTrue(res.bridge["needs_human_check"])

    def test_french_transcription_has_no_pivot(self) -> None:
        with patch("app.voice_service._probe_duration", return_value=None):
            res = VoiceService().transcribe(
                b"RIFFfake", "a.ogg", "fr", stt=FakeFr())
        self.assertIsNone(res.french_pivot)
        self.assertIsNone(res.bridge)

    def test_extract_text_prefers_voice_pivot(self) -> None:
        out = _extract_text(
            "da cas bolilam dmla",
            {"french_pivot": "PIVOT FR"},
            "fr",
            has_audio=True)
        self.assertEqual(out, "PIVOT FR")

    def test_extract_text_bridges_text_when_session_bbj(self) -> None:
        out = _extract_text("da cas bolilam dmla", None, "bbj_Latn", has_audio=False)
        self.assertIn("ghomala'", out)

    def test_extract_text_passthrough_french(self) -> None:
        self.assertEqual(
            _extract_text("fuite robinet", None, "fr", has_audio=False),
            "fuite robinet")
        self.assertEqual(
            _extract_text("fuite robinet", {"french_pivot": None}, "fr", has_audio=True),
            "fuite robinet")


if __name__ == "__main__":
    unittest.main()
