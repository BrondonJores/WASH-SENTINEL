"""Plafond 12 Mo POST /v1/voice/transcribe : 413 FR + lecture par chunks."""
from __future__ import annotations

import asyncio
import io
import sys
import types
import unittest
from unittest.mock import patch

# Stub FastAPI minimal : le venv de test n'a pas fastapi (suite 662 sans main).
try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ModuleNotFoundError:
    HAS_FASTAPI = False

if not HAS_FASTAPI:
    _fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str | None = None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Request:  # pragma: no cover - seulement pour l'import main
        pass

    class UploadFile:  # pragma: no cover
        pass

    def File(*args, **kwargs):  # noqa: N802
        return None

    def Form(*args, **kwargs):  # noqa: N802
        return None

    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def add_middleware(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def post(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

    _fastapi.FastAPI = FastAPI
    _fastapi.File = File
    _fastapi.Form = Form
    _fastapi.HTTPException = HTTPException
    _fastapi.Request = Request
    _fastapi.UploadFile = UploadFile
    sys.modules["fastapi"] = _fastapi
    _mw = types.ModuleType("fastapi.middleware")
    _cors = types.ModuleType("fastapi.middleware.cors")
    _cors.CORSMiddleware = object
    sys.modules["fastapi.middleware"] = _mw
    sys.modules["fastapi.middleware.cors"] = _cors

from app.main import transcribe_audio  # noqa: E402
from app.schemas import VoiceTranscriptionResponse  # noqa: E402
from app.voice_service import (  # noqa: E402
    MAX_VOICE_AUDIO_BYTES,
    VOICE_AUDIO_CHUNK_BYTES,
)


class FakeUploadFile:
    def __init__(self, data: bytes, filename: str = "audio.webm"):
        self._buf = io.BytesIO(data)
        self.filename = filename
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._buf.read(size if size != -1 else -1)


class FakeRequest:
    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}


class TranscribeLimitTest(unittest.TestCase):
    def test_over_12mo_rejected_413_fr(self) -> None:
        from fastapi import HTTPException

        data = b"a" * (MAX_VOICE_AUDIO_BYTES + 1024)
        audio = FakeUploadFile(data)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(transcribe_audio(FakeRequest(), audio, None))
        self.assertEqual(ctx.exception.status_code, 413)
        detail = str(ctx.exception.detail)
        self.assertIn("Note vocale trop lourde", detail)
        self.assertIn("max 12 Mo", detail)
        self.assertIn("Mo", detail)
        # Lecture par chunks : jamais un seul read() sans taille.
        self.assertTrue(audio.read_sizes)
        self.assertTrue(all(s == VOICE_AUDIO_CHUNK_BYTES for s in audio.read_sizes))

    def test_just_under_limit_ok(self) -> None:
        data = b"b" * (MAX_VOICE_AUDIO_BYTES - 1024)
        audio = FakeUploadFile(data)
        fake_res = VoiceTranscriptionResponse(
            transcript="bonjour", language="fr", language_effective="fr", driver="test",
        )
        with patch("app.main.voice_service.transcribe", return_value=fake_res) as m:
            res = asyncio.run(transcribe_audio(FakeRequest(), audio, None))
        self.assertEqual(res.transcript, "bonjour")
        sent = m.call_args.kwargs.get("audio_bytes", b"")
        self.assertEqual(len(sent), len(data))
        # Plusieurs chunks de 1 Mo pour ~12 Mo, jamais tout d'un coup.
        self.assertGreater(len(audio.read_sizes), 1)
        self.assertTrue(all(s == VOICE_AUDIO_CHUNK_BYTES for s in audio.read_sizes))


if __name__ == "__main__":
    unittest.main()
