"""Tests STT Omnilingual CTC (bbj_Latn / ghomala') : fabrique, mocks, erreurs.

Conventions reprises de test_voice_local_languages.py : unittest, backends
réels moqués (patch sherpa/transformers), aucun modèle requis, aucun accès
réseau. Couvre : enregistrement du driver omnilingual_ctc dans la fabrique,
transcription mockée (sherpa + transformers), erreur explicite si driver ou
modèle absent, mapping Whisper bbj->auto documenté.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
import unittest
import wave
from unittest.mock import patch

from app.stt_omnilingual import OmnilingualCTCProvider
from app.stt_providers import (
    STT_PROVIDER_TYPES,
    STT_REGISTRY,
    SUPPORTED_VOICE_LANGUAGES,
    WHISPER_LANG_MAP,
    WhisperCppProvider,
    stt_from_headers,
    stt_from_profile,
)


class _FakeResult:
    def __init__(self, text: str):
        self.text = text


class _FakeStream:
    def __init__(self, text: str):
        self.result = _FakeResult(text)

    def accept_waveform(self, sample_rate: int, samples) -> None:
        return None


class _FakeRecognizer:
    """Faux recognizer sherpa-onnx : jamais de modèle, texte scripté."""

    def __init__(self, text: str = "mə̀ nə́ mbú"):
        self._text = text

    def create_stream(self) -> _FakeStream:
        return _FakeStream(self._text)

    def decode_stream(self, stream: _FakeStream) -> None:
        return None


def _write_test_wav(path: str, n_frames: int = 1600) -> None:
    """Petit WAV 16 kHz mono 16 bits lisible par _read_wav_samples."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x10" * n_frames)


class OmnilingualCtcTest(unittest.TestCase):
    # -- Fabrique : le bon driver pour bbj_Latn -------------------------------

    def test_registry_exposes_ctc_driver(self) -> None:
        self.assertIn("omnilingual_ctc", STT_REGISTRY)
        self.assertIs(STT_REGISTRY["omnilingual_ctc"], OmnilingualCTCProvider)
        self.assertEqual(OmnilingualCTCProvider.driver_name, "omnilingual_ctc")

    def test_factory_from_profile_returns_ctc(self) -> None:
        provider = stt_from_profile({"driver": "omnilingual_ctc"})
        self.assertIsInstance(provider, OmnilingualCTCProvider)
        self.assertEqual(provider.driver_name, "omnilingual_ctc")

    def test_factory_from_headers_returns_ctc(self) -> None:
        provider = stt_from_headers({"x-stt-driver": "omnilingual_ctc"})
        self.assertIsInstance(provider, OmnilingualCTCProvider)

    def test_factory_from_mapping_fields(self) -> None:
        provider = OmnilingualCTCProvider.from_mapping(
            {"model": "/m/model.onnx", "tokens": "/m/tokens.txt",
             "hf_model": "org/ckpt", "backend": "transformers", "threads": 4}
        )
        self.assertEqual(provider.model, "/m/model.onnx")
        self.assertEqual(provider.tokens, "/m/tokens.txt")
        self.assertEqual(provider.hf_model, "org/ckpt")
        self.assertEqual(provider.backend, "transformers")
        self.assertEqual(provider.num_threads, 4)

    def test_unknown_backend_rejected_loudly(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            OmnilingualCTCProvider(backend="whisper")
        self.assertIn("transformers", str(ctx.exception))

    def test_provider_types_flag_ctc_local_languages(self) -> None:
        flags = {d["id"]: d.get("local_languages") for d in STT_PROVIDER_TYPES}
        self.assertIs(flags["omnilingual_ctc"], True)

    # -- Transcription mockée : sherpa-onnx -----------------------------------

    def test_transcribe_sherpa_mock_returns_bbj(self) -> None:
        provider = OmnilingualCTCProvider()
        with tempfile.TemporaryDirectory(prefix="wash-test-ctc-") as tmpdir:
            wav_path = os.path.join(tmpdir, "t.wav")
            _write_test_wav(wav_path)
            with patch("app.stt_omnilingual.normalize_to_wav", return_value=wav_path), \
                    patch.object(
                        OmnilingualCTCProvider, "_load",
                        return_value=("sherpa_onnx", _FakeRecognizer("mə̀ nə́ mbú")),
                    ):
                res = provider.transcribe(b"fake-audio", "a.wav", "bbj_Latn")
        self.assertEqual(res["transcript"], "mə̀ nə́ mbú")
        self.assertEqual(res["text"], "mə̀ nə́ mbú")
        self.assertEqual(res["language"], "bbj_Latn")
        # Natif CTC : pas de mapping "auto", la langue effective est bbj.
        self.assertEqual(res["language_effective"], "bbj_Latn")
        self.assertEqual(res["engine"], "omnilingual_ctc")
        self.assertEqual(res["backend"], "sherpa_onnx")

    # -- Transcription mockée : transformers ----------------------------------

    def test_transcribe_transformers_mock_returns_bbj(self) -> None:
        provider = OmnilingualCTCProvider(backend="transformers")
        fake_handle = (object(), object())
        with tempfile.TemporaryDirectory(prefix="wash-test-ctc-") as tmpdir:
            wav_path = os.path.join(tmpdir, "t.wav")
            _write_test_wav(wav_path)
            with patch("app.stt_omnilingual.normalize_to_wav", return_value=wav_path), \
                    patch.object(
                        OmnilingualCTCProvider, "_load",
                        return_value=("transformers", fake_handle),
                    ), \
                    patch.object(
                        OmnilingualCTCProvider, "_decode_transformers",
                        return_value="mbɔ́ɔ",
                    ) as mock_decode:
                res = provider.transcribe(b"fake-audio", "a.wav", "bbj_Latn")
        mock_decode.assert_called_once()
        self.assertEqual(mock_decode.call_args.args[0], fake_handle)
        self.assertEqual(res["transcript"], "mbɔ́ɔ")
        self.assertEqual(res["language_effective"], "bbj_Latn")
        self.assertEqual(res["engine"], "omnilingual_ctc")
        self.assertEqual(res["backend"], "transformers")

    # -- Driver / modèle absent : erreur explicite ----------------------------

    def test_no_backend_raises_explicit_error(self) -> None:
        provider = OmnilingualCTCProvider()
        # sys.modules à None => « import X » lève ImportError (sondes à None).
        blocked = {"sherpa_onnx": None, "transformers": None, "torch": None}
        with patch.dict(sys.modules, blocked):
            with self.assertRaises(RuntimeError) as ctx:
                provider.transcribe(b"fake-audio", "a.wav", "bbj_Latn")
        msg = str(ctx.exception)
        self.assertIn("Omnilingual CTC indisponible", msg)
        self.assertIn("sherpa-onnx", msg)
        self.assertIn("transformers", msg)
        # Jamais de transcription vide déguisée en succès : ça lève.

    def test_missing_onnx_model_raises_explicit_error(self) -> None:
        fake_sherpa = types.ModuleType("sherpa_onnx")
        provider = OmnilingualCTCProvider(
            model="/nonexistent/model.int8.onnx",
            tokens="/nonexistent/tokens.txt",
            backend="sherpa",
        )
        with patch.dict(sys.modules, {"sherpa_onnx": fake_sherpa}):
            with self.assertRaises(RuntimeError) as ctx:
                provider.transcribe(b"fake-audio", "a.wav", "bbj_Latn")
        msg = str(ctx.exception)
        self.assertIn("/nonexistent/model.int8.onnx", msg)
        self.assertIn("huggingface-cli download", msg)

    def test_unknown_language_rejected_before_load(self) -> None:
        provider = OmnilingualCTCProvider()
        with patch.object(
            OmnilingualCTCProvider, "_load",
            side_effect=AssertionError("_load ne doit pas être appelé"),
        ):
            with self.assertRaises(ValueError) as ctx:
                provider.transcribe(b"fake-audio", "a.wav", "klingon")
        self.assertIn("klingon", str(ctx.exception))

    # -- Chargement lazy : import et constructeur sans modèle -----------------

    def test_import_and_init_never_load_model(self) -> None:
        provider = OmnilingualCTCProvider()
        self.assertIsNone(provider._sherpa_recognizer)
        self.assertIsNone(provider._hf)
        # Ces modules lourds ne doivent pas être exigés à l'import.
        self.assertNotIn("sherpa_onnx", sys.modules)
        info = provider.describe()
        self.assertEqual(info["driver"], "omnilingual_ctc")

    # -- Whisper : bbj->auto documenté (Omnilingual est le driver réel) -------

    def test_bbj_supported_and_whisper_maps_to_auto(self) -> None:
        self.assertIn("bbj_Latn", SUPPORTED_VOICE_LANGUAGES)
        self.assertEqual(WHISPER_LANG_MAP["bbj_Latn"], "auto")

    def test_whisper_sends_auto_for_bbj(self) -> None:
        seen_argv: list = []
        fake_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="x")

        def fake_run(argv, **kwargs):
            seen_argv.extend(argv)
            return fake_completed

        provider = WhisperCppProvider(binary="/bin/whisper", model="/models/x.bin")
        with patch("app.stt_providers.os.path.isfile", side_effect=lambda p: p in ("/bin/whisper", "/models/x.bin")), \
                patch("app.stt_providers.normalize_to_wav", return_value="/tmp/n.wav"), \
                patch("app.stt_providers.subprocess.run", side_effect=fake_run):
            res = provider.transcribe(b"xx", "a.webm", "bbj_Latn")
        lang_idx = seen_argv.index("-l")
        self.assertEqual(seen_argv[lang_idx + 1], "auto")
        self.assertEqual(res["language"], "bbj_Latn")
        self.assertEqual(res["language_effective"], "auto")


if __name__ == "__main__":
    unittest.main()
