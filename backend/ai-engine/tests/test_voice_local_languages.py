"""Tests voix langues locales (AXE 4) : dua_Latn, bassa, ewondo de bout en bout.

Couvre : normalisation d'alias, rejet bruyant des codes inconnus, mapping -l
whisper, omission honnête côté cloud, sondage de durée webm, registre de voix
TTS, timeouts. Les providers réels sont moqués : aucun modèle requis.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from app.stt_providers import (
    STT_PROVIDER_TYPES,
    CloudWhisperProvider,
    OmnilingualOnnxProvider,
    WhisperCppProvider,
    normalize_to_wav,
)
from app.voice_service import GUIDANCE, VoiceService


class EchoStt:
    """Faux provider qui répercute la langue demandée (déjà normalisée)."""

    driver_name = "echo_test"

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict:
        return {"transcript": "mbolo", "language": language}


class VoiceLocalLanguagesTest(unittest.TestCase):
    # -- Normalisation et validation des codes -------------------------------

    def test_aliases_normalize_to_canonical(self) -> None:
        for alias, canonical in (("dua", "dua_Latn"), ("douala", "dua_Latn"), ("basaa", "bassa")):
            with self.subTest(alias=alias), patch("app.voice_service._probe_duration", return_value=None):
                res = VoiceService().transcribe(b"RIFFfake", "t.wav", alias, stt=EchoStt())
            self.assertEqual(res.language, canonical)
            self.assertEqual(res.language_effective, canonical)

    def test_unknown_language_raises_guided_code(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().transcribe(b"RIFFfake", "t.wav", "klingon", stt=EchoStt())
        msg = str(ctx.exception)
        self.assertIn("[STT_LANGUAGE]", msg)
        self.assertIn("douala", msg)
        self.assertIn("réessayez", msg)

    def test_new_guidance_respects_tone_contract(self) -> None:
        for code in ("STT_LANGUAGE", "STT_TOO_LONG"):
            msg = GUIDANCE[code]
            self.assertNotIn("échec", msg.lower(), code)
            lowered = msg.lower()
            self.assertTrue("réessayez" in lowered or "écrivez" in lowered, code)

    # -- Providers : honnêteté sur la langue effective -----------------------

    def test_whisper_sends_auto_for_local_languages(self) -> None:
        seen_argv: list = []
        fake_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="mbolo")

        def fake_run(argv, **kwargs):
            seen_argv.extend(argv)
            return fake_completed

        provider = WhisperCppProvider(binary="/bin/whisper", model="/models/x.bin")
        with patch("app.stt_providers.os.path.isfile", side_effect=lambda p: p in ("/bin/whisper", "/models/x.bin")), \
                patch("app.stt_providers.normalize_to_wav", return_value="/tmp/n.wav"), \
                patch("app.stt_providers.subprocess.run", side_effect=fake_run):
            res = provider.transcribe(b"xx", "a.webm", "dua_Latn")
        lang_idx = seen_argv.index("-l")
        self.assertEqual(seen_argv[lang_idx + 1], "auto")
        self.assertEqual(res["language"], "dua_Latn")
        self.assertEqual(res["language_effective"], "auto")

    def test_whisper_keeps_fr(self) -> None:
        seen_argv: list = []
        fake_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="bonjour")

        def fake_run(argv, **kwargs):
            seen_argv.extend(argv)
            return fake_completed

        provider = WhisperCppProvider(binary="/bin/whisper", model="/models/x.bin")
        with patch("app.stt_providers.os.path.isfile", side_effect=lambda p: p in ("/bin/whisper", "/models/x.bin")), \
                patch("app.stt_providers.normalize_to_wav", return_value="/tmp/n.wav"), \
                patch("app.stt_providers.subprocess.run", side_effect=fake_run):
            res = provider.transcribe(b"xx", "a.webm", "fr")
        lang_idx = seen_argv.index("-l")
        self.assertEqual(seen_argv[lang_idx + 1], "fr")
        self.assertEqual(res["language_effective"], "fr")

    def _cloud_transcribe(self, language: str) -> tuple[dict, dict]:
        posted: dict = {}
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "mbolo"}
        mock_resp.raise_for_status.return_value = None

        def fake_post(url, headers=None, files=None, data=None):
            posted.update(data or {})
            return mock_resp

        mock_client.post.side_effect = fake_post
        with patch("app.stt_providers.httpx.Client", return_value=mock_client):
            res = CloudWhisperProvider(base_url="https://x/v1", model="whisper-1").transcribe(
                b"xx", "a.wav", language
            )
        return res, posted

    def test_cloud_omits_language_for_local_codes(self) -> None:
        res, posted = self._cloud_transcribe("dua_Latn")
        self.assertNotIn("language", posted)
        self.assertEqual(res["language"], "dua_Latn")
        self.assertEqual(res["language_effective"], "auto")

    def test_cloud_forwards_two_letter_codes(self) -> None:
        res, posted = self._cloud_transcribe("fr")
        self.assertEqual(posted.get("language"), "fr")
        self.assertEqual(res["language_effective"], "fr")

    def test_omnilingual_rejects_unknown_code_loudly(self) -> None:
        with self.assertRaises(ValueError):
            OmnilingualOnnxProvider().transcribe(b"xx", "a.wav", "klingon")

    def test_provider_types_flag_local_languages(self) -> None:
        flags = {d["id"]: d.get("local_languages") for d in STT_PROVIDER_TYPES}
        self.assertIs(flags["omnilingual_onnx"], True)
        self.assertIs(flags["whisper_cpp"], False)
        self.assertIs(flags["cloud_whisper"], False)

    # -- Sondage webm : TOO_SHORT / TOO_LONG ---------------------------------

    def _webm_transcribe(self, probe_stdout: str):
        fake_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=probe_stdout)
        with patch("app.voice_service.shutil.which", return_value="/usr/bin/ffprobe"), \
                patch("app.voice_service.subprocess.run", return_value=fake_completed):
            return VoiceService().transcribe(b"fake-opus", "d.webm", "bassa", stt=EchoStt())

    def test_webm_too_short_probed(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._webm_transcribe("0.2\n")
        self.assertIn("[STT_TOO_SHORT]", str(ctx.exception))

    def test_webm_too_long_probed(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._webm_transcribe("400.0\n")
        self.assertIn("[STT_TOO_LONG]", str(ctx.exception))

    def test_webm_probed_duration_returned(self) -> None:
        res = self._webm_transcribe("2.5\n")
        self.assertEqual(res.transcript, "mbolo")
        self.assertEqual(res.language, "bassa")
        assert res.duration_seconds is not None
        self.assertAlmostEqual(res.duration_seconds, 2.5, places=1)

    # -- TTS : voix locales honnêtes ------------------------------------------

    def _tts_service(self) -> VoiceService:
        svc = VoiceService()
        svc.piper_bin = "/bin/piper"
        svc.piper_model = "/models/piper/fr_FR-upmc-medium.onnx"
        return svc

    def test_tts_local_language_without_voice_fails_loudly(self) -> None:
        svc = self._tts_service()

        def fake_isfile(path: str) -> bool:
            return path in ("/bin/piper", "/models/piper/fr_FR-upmc-medium.onnx")

        with patch("app.voice_service.os.path.isfile", side_effect=fake_isfile):
            with self.assertRaises(RuntimeError) as ctx:
                svc.synthesize("mbolo", language="dua_Latn")
        msg = str(ctx.exception)
        self.assertIn("[TTS_VOICE_UNAVAILABLE]", msg)
        self.assertNotIn("dua_Latn-medium", msg)

    def test_tts_registry_override_uses_mapped_voice(self) -> None:
        svc = self._tts_service()
        wav = b"RIFFfake-audio"

        class FakeProc:
            def __init__(self, cmd: list, **kwargs) -> None:
                out = cmd[cmd.index("--output_file") + 1]
                with open(out, "wb") as f:
                    f.write(wav)

            def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple:
                return ("", "")

        real_isfile = os.path.isfile

        def fake_isfile(path: str) -> bool:
            return path in ("/bin/piper", "/models/piper/fr_FR-upmc-medium.onnx") or real_isfile(path)

        env = {"VOICE_REGISTRY_JSON": '{"dua_Latn": ["fr_FR-upmc-medium"]}'}
        with patch("app.voice_service.os.path.isfile", side_effect=fake_isfile), \
                patch("app.voice_service.subprocess.Popen", FakeProc), \
                patch.dict(os.environ, env, clear=False):
            res = svc.synthesize("mbolo", language="dua_Latn")
        self.assertTrue(res.audio_base64)

    def test_tts_timeout_maps_to_unavailable(self) -> None:
        svc = self._tts_service()

        class SlowProc:
            def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple:
                raise subprocess.TimeoutExpired(cmd="piper", timeout=timeout or 0)

            def kill(self) -> None:
                return None

        def fake_isfile(path: str) -> bool:
            return True

        with patch("app.voice_service.os.path.isfile", side_effect=fake_isfile), \
                patch("app.voice_service.subprocess.Popen", return_value=SlowProc()):
            with self.assertRaises(RuntimeError) as ctx:
                svc.synthesize("bonjour")
        self.assertIn("[TTS_UNAVAILABLE]", str(ctx.exception))

    def test_tts_text_capped_server_side(self) -> None:
        svc = self._tts_service()
        seen: dict = {}

        class FakeProc:
            def __init__(self, cmd: list, **kwargs) -> None:
                out = cmd[cmd.index("--output_file") + 1]
                with open(out, "wb") as f:
                    f.write(b"RIFFx")

            def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple:
                seen["input"] = input
                return ("", "")

        with patch("app.voice_service.os.path.isfile", return_value=True), \
                patch("app.voice_service.subprocess.Popen", FakeProc):
            svc.synthesize("x" * 1500)
        self.assertEqual(len(seen["input"] or ""), 1000)

    # -- Garde-fous FFmpeg -----------------------------------------------------

    def test_normalize_rejects_oversize_input(self) -> None:
        with self.assertRaises(RuntimeError):
            normalize_to_wav(b"x" * (13 * 1024 * 1024), "a.webm", "/tmp")


if __name__ == "__main__":
    unittest.main()
