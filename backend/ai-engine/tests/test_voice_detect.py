"""Auto-détection de langue vocale : cascade Whisper-auto + moteur local.

Cas réel : vocal ghomala' transcrit "da cas bolilam dmla" (Whisper FR forcé)
-> incident poubelle. La cascade détecte la langue parlée au lieu de croire
la langue demandée sur parole ; l'arbitrage est piloté par WHISPER_LANG_MAP
(zéro langue en dur). Fakes uniquement (aucun binaire/modèle requis) ; le
vrai audio golden (tests/fixtures/voice_bbj_brother_01.ogg) est transcrit
côté conteneur via accept_voice.py (sherpa + whisper présents).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.stt_providers import parse_whisper_confidence, parse_whisper_detection
from app.voice_detect import arbitrate, whisper_native_languages
from app.voice_service import STT_DETECT_MIN_PROB, VoiceService


class FakeWhisper:
    driver_name = "whisper_cpp"

    def __init__(self, auto=None, exc=None):
        self.auto = auto
        self.exc = exc
        self.calls = 0

    def transcribe_auto(self, audio_bytes, filename):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return dict(self.auto or {})


class FakeOmni:
    driver_name = "omnilingual_onnx"

    def __init__(self, transcript="", exc=None):
        self.transcript = transcript
        self.exc = exc
        self.calls = 0

    def transcribe(self, audio_bytes, filename, language):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return {"transcript": self.transcript, "language": language,
                "language_effective": language}


class FakeActive:
    driver_name = "stub_active"

    def __init__(self, transcript="", exc=None, confidence=None):
        self.transcript = transcript
        self.exc = exc
        self.confidence = confidence
        self.calls = 0

    def transcribe(self, audio_bytes, filename, language):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        out = {"transcript": self.transcript, "language": language,
               "language_effective": language}
        if self.confidence is not None:
            out["confidence"] = self.confidence
        return out


def _transcribe(language, active, whisper=None, omni=None):
    with patch("app.voice_service._local_whisper_provider", return_value=whisper), \
            patch("app.voice_service._local_omni_provider", return_value=omni):
        return VoiceService().transcribe(b"RIFFfake", "t.wav", language, stt=active)


class ParseWhisperDetectionTest(unittest.TestCase):
    def test_full_log(self) -> None:
        lang, prob = parse_whisper_detection(
            "whisper_full: auto-detected language: fr (p = 0.97)", "")
        self.assertEqual((lang, prob), ("fr", 0.97))

    def test_missing_is_none(self) -> None:
        self.assertEqual(parse_whisper_detection("transcript only", ""), (None, None))


class NativeSetTest(unittest.TestCase):
    def test_derived_from_map(self) -> None:
        native = whisper_native_languages()
        self.assertIn("fr", native)
        self.assertIn("en", native)
        self.assertNotIn("bbj_Latn", native)
        self.assertNotIn("dua_Latn", native)


class ArbitrateTest(unittest.TestCase):
    def test_whisper_native_confident_wins(self) -> None:
        out = arbitrate("bbj_Latn",
                        {"transcript": "la pompe fuit", "detected_language": "fr",
                         "detection_prob": 0.9},
                        {"transcript": "da cas bolilam", "driver": "omnilingual_onnx"},
                        min_prob=STT_DETECT_MIN_PROB)
        assert out is not None
        self.assertEqual(out["transcript"], "la pompe fuit")
        self.assertEqual(out["language_detected"], "fr")

    def test_low_prob_falls_to_local(self) -> None:
        out = arbitrate("bbj_Latn",
                        {"transcript": "da cas", "detected_language": "fr",
                         "detection_prob": 0.2},
                        {"transcript": "pou tshi", "driver": "omnilingual_onnx"},
                        min_prob=STT_DETECT_MIN_PROB)
        assert out is not None
        self.assertEqual(out["transcript"], "pou tshi")
        self.assertEqual(out["language_detected"], "bbj_Latn")

    def test_unknown_detected_falls_to_local(self) -> None:
        out = arbitrate("bbj_Latn",
                        {"transcript": "da cas", "detected_language": "yo",
                         "detection_prob": 0.99},
                        {"transcript": "pou tshi", "driver": "omnilingual_onnx"},
                        min_prob=STT_DETECT_MIN_PROB)
        assert out is not None
        self.assertEqual(out["driver"], "omnilingual_onnx")

    def test_empty_everywhere_is_none(self) -> None:
        self.assertIsNone(arbitrate(
            "bbj_Latn", {"transcript": ""}, {"transcript": ""},
            min_prob=STT_DETECT_MIN_PROB))


class CascadeTest(unittest.TestCase):
    def test_requested_french_stays_direct(self) -> None:
        active = FakeActive("robinet cassé")
        res = _transcribe("fr", active)
        self.assertEqual(res.transcript, "robinet cassé")
        self.assertEqual(res.language_detected, "fr")
        self.assertEqual(res.detection.get("mode"), "direct")
        self.assertEqual(active.calls, 1)

    def test_bbj_french_speech_detected(self) -> None:
        whisper = FakeWhisper({"transcript": "la pompe fuit",
                               "detected_language": "fr", "detection_prob": 0.92})
        omni = FakeOmni("da cas bolilam")
        res = _transcribe("bbj_Latn", FakeActive(""), whisper, omni)
        self.assertEqual(res.transcript, "la pompe fuit")
        self.assertEqual(res.language_detected, "fr")
        self.assertEqual(res.driver, "whisper_cpp")

    def test_bbj_speech_keeps_omni(self) -> None:
        whisper = FakeWhisper({"transcript": "da cas", "detected_language": "yo",
                               "detection_prob": 0.8})
        omni = FakeOmni("pou tshi lepom")
        res = _transcribe("bbj_Latn", FakeActive(""), whisper, omni)
        self.assertEqual(res.transcript, "pou tshi lepom")
        self.assertEqual(res.language_detected, "bbj_Latn")
        self.assertEqual(res.driver, "omnilingual_onnx")

    def test_no_local_engine_falls_back_to_active(self) -> None:
        res = _transcribe("bbj_Latn", FakeActive("repli actif"))
        self.assertEqual(res.transcript, "repli actif")
        self.assertEqual(res.detection.get("mode"), "fallback-direct")

    def test_all_down_raises_guided(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            _transcribe("bbj_Latn", FakeActive(exc=RuntimeError("down")))
        self.assertIn("STT_UNAVAILABLE", str(ctx.exception))


class ParseWhisperConfidenceTest(unittest.TestCase):
    def test_no_speech_shape(self) -> None:
        payload = {"result": {"transcription": [
            {"text": "a", "no_speech_prob": 0.9},
            {"text": "b", "no_speech_prob": 0.7}]}}
        self.assertAlmostEqual(parse_whisper_confidence(payload), 0.2)

    def test_logprob_shape(self) -> None:
        payload = {"segments": [{"text": "a", "avg_logprob": -0.1}]}
        conf = parse_whisper_confidence(payload)
        assert conf is not None
        self.assertGreater(conf, 0.9)

    def test_garbage_is_none(self) -> None:
        self.assertIsNone(parse_whisper_confidence({}))
        self.assertIsNone(parse_whisper_confidence({"transcription": []}))
        self.assertIsNone(parse_whisper_confidence(None))


class EscalationTest(unittest.TestCase):
    def test_low_confidence_escalates_to_omni(self) -> None:
        active = FakeActive("da cas bolilam", confidence=0.2)
        whisper = FakeWhisper({"transcript": "", "detected_language": None,
                               "detection_prob": None})
        omni = FakeOmni("pou tshi lepom")
        res = _transcribe("fr", active, whisper, omni)
        self.assertEqual(res.transcript, "pou tshi lepom")
        self.assertIsNone(res.language_detected)
        self.assertEqual(res.detection.get("escalated_from"),
                         "low-confidence-direct")

    def test_high_confidence_no_escalation(self) -> None:
        active = FakeActive("robinet cassé", confidence=0.95)
        omni = FakeOmni("intrus")
        res = _transcribe("fr", active, None, omni)
        self.assertEqual(res.transcript, "robinet cassé")
        self.assertEqual(omni.calls, 0)
        self.assertEqual(res.detection.get("mode"), "direct")

    def test_no_confidence_no_escalation(self) -> None:
        active = FakeActive("robinet cassé")
        omni = FakeOmni("intrus")
        res = _transcribe("fr", active, None, omni)
        self.assertEqual(res.transcript, "robinet cassé")
        self.assertEqual(omni.calls, 0)

    def test_escalation_empty_keeps_direct(self) -> None:
        active = FakeActive("da cas", confidence=0.1)
        res = _transcribe("fr", active, None, None)
        self.assertEqual(res.transcript, "da cas")
        self.assertEqual(res.detection.get("low_confidence"), 0.1)


class GoldenFixtureTest(unittest.TestCase):
    def test_brother_fixture_present(self) -> None:
        fixture = (Path(__file__).resolve().parent / "fixtures"
                   / "voice_bbj_brother_01.ogg")
        self.assertTrue(fixture.is_file())
        self.assertGreater(fixture.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
