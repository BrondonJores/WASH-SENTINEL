"""Tests VoiceService : erreurs honnêtes, jamais de transcription/silence fabriqué."""
from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

from app.stt_providers import BaseSTTProvider
from app.voice_service import VoiceService


class OkStt(BaseSTTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict:
        return {"transcript": "bonjour école", "language": language}


class BoomStt(BaseSTTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict:
        raise RuntimeError("Whisper indisponible (binaire ou modèle introuvable).")


class VoiceServiceTest(unittest.TestCase):
    def test_transcribe_passthrough(self) -> None:
        res = VoiceService().transcribe(b"RIFFfake", "t.wav", "fr", stt=OkStt())
        self.assertEqual(res.transcript, "bonjour école")
        self.assertEqual(res.language, "fr")

    def test_transcribe_propagates_error_never_fabricates(self) -> None:
        """Non-régression : plus jamais de faux '[Transcription locale : Fuite...]'."""
        with self.assertRaises(RuntimeError):
            VoiceService().transcribe(b"RIFFfake", "t.wav", "fr", stt=BoomStt())

    def test_synthesize_raises_when_piper_missing(self) -> None:
        svc = VoiceService()
        svc.piper_bin = "/introuvable/piper"
        with self.assertRaises(RuntimeError):
            svc.synthesize("bonjour")

    def test_synthesize_ok_when_piper_present(self) -> None:
        real_isfile = os.path.isfile
        wav = b"RIFF$\x00\x00\x00WAVEfmt fake-audio-payload"

        def fake_isfile(path: str) -> bool:
            if path in ("/bin/piper", "/models/voice.onnx"):
                return True
            return real_isfile(path)

        class FakeProc:
            def __init__(self, cmd: list, **kwargs) -> None:
                out = cmd[cmd.index("--output_file") + 1]
                with open(out, "wb") as f:
                    f.write(wav)

            def communicate(self, input: str | None = None) -> tuple:
                return ("", "")

        svc = VoiceService()
        svc.piper_bin = "/bin/piper"
        svc.piper_model = "/models/voice.onnx"
        with patch("app.voice_service.os.path.isfile", side_effect=fake_isfile):
            with patch("app.voice_service.subprocess.Popen", FakeProc):
                res = svc.synthesize("bonjour")
        self.assertEqual(res.audio_base64, base64.b64encode(wav).decode("utf-8"))
        self.assertEqual(res.mime_type, "audio/wav")


if __name__ == "__main__":
    unittest.main()
