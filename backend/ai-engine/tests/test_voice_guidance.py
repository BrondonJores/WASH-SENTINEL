"""Tests du guidage vocal : chaque panne lève un RuntimeError FR guidé + conseil.

Codes stables attendus : STT_SILENCE, STT_TOO_SHORT, STT_NOISY, STT_INAUDIBLE,
STT_UNAVAILABLE, TTS_EMPTY_TEXT, TTS_VOICE_UNAVAILABLE, TTS_UNAVAILABLE.
Jamais de message technique brut, jamais le mot « échec ».
"""
from __future__ import annotations

import io
import math
import struct
import unittest
import wave
from unittest.mock import patch

from app.stt_providers import BaseSTTProvider
from app.voice_service import GUIDANCE, VoiceService


def _make_wav(seconds: float, amplitude: float = 0.0, framerate: int = 16000) -> bytes:
    """WAV PCM 16 bits mono : silence (amplitude 0) ou sinusoïde 440 Hz."""
    n = int(seconds * framerate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        frames = bytearray()
        for i in range(n):
            sample = math.sin(2 * math.pi * 440 * i / framerate) * amplitude
            frames += struct.pack("<h", int(sample * 32767))
        w.writeframes(bytes(frames))
    return buf.getvalue()


class OkStt(BaseSTTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict:
        return {"transcript": "le forage est en panne", "language": language}


class EmptyStt(BaseSTTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict:
        return {"transcript": "   ", "language": language}


class BoomStt(BaseSTTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict:
        raise RuntimeError("Whisper indisponible (binaire ou modèle introuvable : /models/x.bin).")


class VoiceGuidanceTest(unittest.TestCase):
    def test_silence_wav_guided(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().transcribe(_make_wav(1.0), "s.wav", "fr", stt=OkStt())
        msg = str(ctx.exception)
        self.assertIn("[STT_SILENCE]", msg)
        self.assertIn("rien entendu", msg)
        self.assertIn("réessayez", msg)

    def test_too_short_wav_guided(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().transcribe(_make_wav(0.2, amplitude=0.3), "s.wav", "fr", stt=OkStt())
        msg = str(ctx.exception)
        self.assertIn("[STT_TOO_SHORT]", msg)
        self.assertIn("trop court", msg)

    def test_noisy_unintelligible_guided(self) -> None:
        """Son fort mais rien d'intelligible -> bruit, pas silence."""
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().transcribe(_make_wav(1.5, amplitude=0.5), "s.wav", "fr", stt=EmptyStt())
        msg = str(ctx.exception)
        self.assertIn("[STT_NOISY]", msg)
        self.assertIn("bruit", msg)

    def test_inaudible_medium_level_guided(self) -> None:
        """Niveau moyen incompris -> inaudible avec conseil de diction."""
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().transcribe(_make_wav(1.5, amplitude=0.1), "s.wav", "fr", stt=EmptyStt())
        msg = str(ctx.exception)
        self.assertIn("[STT_INAUDIBLE]", msg)
        self.assertIn("pas bien compris", msg)

    def test_inaudible_compressed_format_guided(self) -> None:
        """Format compressé (énergie inconnue) vide de sens -> inaudible."""
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().transcribe(b"RIFFfake-opus-payload", "s.webm", "fr", stt=EmptyStt())
        self.assertIn("[STT_INAUDIBLE]", str(ctx.exception))

    def test_model_unavailable_hides_technical_detail(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().transcribe(b"RIFFfake-opus-payload", "s.webm", "fr", stt=BoomStt())
        msg = str(ctx.exception)
        self.assertIn("[STT_UNAVAILABLE]", msg)
        self.assertIn("momentanément indisponible", msg)
        self.assertIn("écrivez votre message", msg)
        self.assertNotIn("/models/x.bin", msg)
        self.assertNotIn("Whisper", msg)

    def test_healthy_audio_still_passes_with_duration(self) -> None:
        res = VoiceService().transcribe(_make_wav(1.5, amplitude=0.1), "s.wav", "fr", stt=OkStt())
        self.assertEqual(res.transcript, "le forage est en panne")
        self.assertIsNotNone(res.duration_seconds)
        assert res.duration_seconds is not None
        self.assertAlmostEqual(res.duration_seconds, 1.5, places=1)
        self.assertEqual(res.language_effective, "fr")
        self.assertEqual(res.driver, "base")

    def test_tts_empty_text_guided(self) -> None:
        for text in ("", "   "):
            with self.assertRaises(RuntimeError) as ctx:
                VoiceService().synthesize(text)
            msg = str(ctx.exception)
            self.assertIn("[TTS_EMPTY_TEXT]", msg)
            self.assertIn("Rien à lire", msg)

    def test_tts_voice_unavailable_guided(self) -> None:
        svc = VoiceService()
        svc.piper_bin = "/bin/piper"
        svc.piper_model = "/models/piper/fr_FR-upmc-medium.onnx"
        with patch("app.voice_service.os.path.isfile", side_effect=lambda p: p == "/bin/piper"):
            with self.assertRaises(RuntimeError) as ctx:
                svc.synthesize("bonjour")
        msg = str(ctx.exception)
        self.assertIn("[TTS_VOICE_UNAVAILABLE]", msg)
        self.assertIn("voix", msg)
        self.assertNotIn("/models/piper", msg)

    def test_tts_engine_unavailable_guided(self) -> None:
        svc = VoiceService()
        svc.piper_bin = "/introuvable/piper"
        with self.assertRaises(RuntimeError) as ctx:
            svc.synthesize("bonjour")
        msg = str(ctx.exception)
        self.assertIn("[TTS_UNAVAILABLE]", msg)
        self.assertIn("lecture vocale", msg)
        self.assertNotIn("/introuvable/piper", msg)

    def test_guidance_never_says_echec_and_always_guides(self) -> None:
        for code, msg in GUIDANCE.items():
            self.assertNotIn("échec", msg.lower(), code)
            self.assertNotIn("echec", msg.lower(), code)
            # Chaque message se termine par un conseil d'action.
            lowered = msg.lower()
            self.assertTrue(
                "réessayez" in lowered or "écrivez" in lowered,
                f"{code} sans conseil : {msg}",
            )


if __name__ == "__main__":
    unittest.main()
