"""Tests pack bilingue EN + prompt Whisper métier WASH.

Couvre : "en" accepté (STT -l en, TTS MMS eng), prompt métier injecté au
binaire whisper.cpp (--prompt) et à l'API cloud (champ "prompt"), surcharge
mapping/env, et replis intacts (MMS down -> Piper FR + notice explicite).
Providers réels moqués : aucun modèle ni binaire requis.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.stt_providers import (
    SUPPORTED_VOICE_LANGUAGES,
    WHISPER_LANG_MAP,
    WASH_WHISPER_PROMPT_EN,
    WASH_WHISPER_PROMPT_FR,
    CloudWhisperProvider,
    WhisperCppProvider,
    wash_whisper_prompt,
)
from app.tts_providers import MMS_LANGUAGE_MAP, MMS_MISSING_PRETRAINED, BaseTTSProvider
from app.voice_service import GUIDANCE, VoiceService

WAV_FR = b"RIFF$\x00\x00\x00WAVEfmt fake-piper-fr"
WAV_EN = b"RIFF$\x00\x00\x00WAVEfmt fake-mms-eng"


class EchoStt:
    driver_name = "echo_test"

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict:
        return {"transcript": "water leak", "language": language}


class FakeMMSDown(BaseTTSProvider):
    driver_name = "mms"

    def synthesize(self, text: str, voice: str, language: str) -> bytes:
        raise RuntimeError("MMS indisponible (simulé).")


class FakeMMSOk(BaseTTSProvider):
    driver_name = "mms"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def synthesize(self, text: str, voice: str, language: str) -> bytes:
        self.seen.append(language)
        return WAV_EN


class FakeProc:
    def __init__(self, cmd: list, **kwargs) -> None:
        out = cmd[cmd.index("--output_file") + 1]
        with open(out, "wb") as f:
            f.write(WAV_FR)

    def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple:
        return ("", "")


_real_isfile = os.path.isfile


def _piper_isfile(path: str) -> bool:
    if path in ("/bin/piper", "/models/piper/fr_FR-upmc-medium.onnx"):
        return True
    return _real_isfile(path)


def _piper_service() -> VoiceService:
    svc = VoiceService()
    svc.piper_bin = "/bin/piper"
    svc.piper_model = "/models/piper/fr_FR-upmc-medium.onnx"
    return svc


def _whisper_transcribe(provider: WhisperCppProvider, language: str):
    seen_argv: list = []
    fake_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="water leak")

    def fake_run(argv, **kwargs):
        seen_argv.extend(argv)
        return fake_completed

    with patch("app.stt_providers.os.path.isfile", side_effect=lambda p: p in ("/bin/whisper", "/models/x.bin")), \
            patch("app.stt_providers.normalize_to_wav", return_value="/tmp/n.wav"), \
            patch("app.stt_providers.subprocess.run", side_effect=fake_run):
        res = provider.transcribe(b"xx", "a.webm", language)
    return res, seen_argv


def _cloud_transcribe(provider: CloudWhisperProvider, language: str):
    posted: dict = {}
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "water leak"}
    mock_resp.raise_for_status.return_value = None

    def fake_post(url, headers=None, files=None, data=None):
        posted.update(data or {})
        return mock_resp

    mock_client.post.side_effect = fake_post
    with patch("app.stt_providers.httpx.Client", return_value=mock_client):
        res = provider.transcribe(b"xx", "a.wav", language)
    return res, posted


class VoiceEnglishTest(unittest.TestCase):
    # -- "en" accepté partout ---------------------------------------------

    def test_en_supported_and_mapped(self) -> None:
        self.assertIn("en", SUPPORTED_VOICE_LANGUAGES)
        self.assertEqual(WHISPER_LANG_MAP["en"], "en")
        self.assertEqual(MMS_LANGUAGE_MAP["en"], "eng")
        self.assertNotIn("eng", MMS_MISSING_PRETRAINED)

    def test_transcribe_accepts_en_and_aliases(self) -> None:
        for code in ("en", "anglais", "english"):
            with self.subTest(code=code), patch("app.voice_service._probe_duration", return_value=None):
                res = VoiceService().transcribe(b"RIFFfake", "t.wav", code, stt=EchoStt())
            self.assertEqual(res.language, "en")
            self.assertEqual(res.language_effective, "en")

    def test_guidance_lists_english(self) -> None:
        self.assertIn("anglais", GUIDANCE["STT_LANGUAGE"])

    def test_whisper_sends_en_with_prompt(self) -> None:
        provider = WhisperCppProvider(binary="/bin/whisper", model="/models/x.bin")
        res, argv = _whisper_transcribe(provider, "en")
        self.assertEqual(argv[argv.index("-l") + 1], "en")
        self.assertEqual(res["language_effective"], "en")
        # Prompt métier EN passé au binaire.
        prompt = argv[argv.index("--prompt") + 1]
        self.assertIn("Bonanjo", prompt)
        self.assertIn("borehole", prompt)

    def test_cloud_forwards_en_with_prompt(self) -> None:
        provider = CloudWhisperProvider(base_url="https://x/v1", model="whisper-1")
        res, posted = _cloud_transcribe(provider, "en")
        self.assertEqual(posted.get("language"), "en")
        self.assertEqual(res["language_effective"], "en")
        self.assertIn("Bonanjo", posted.get("prompt", ""))
        self.assertIn("borehole", posted.get("prompt", ""))

    # -- Prompt métier FR/EN ------------------------------------------------

    def test_prompt_helper_selects_language(self) -> None:
        self.assertIs(wash_whisper_prompt("en"), WASH_WHISPER_PROMPT_EN)
        self.assertIs(wash_whisper_prompt("fr"), WASH_WHISPER_PROMPT_FR)
        self.assertIs(wash_whisper_prompt("dua_Latn"), WASH_WHISPER_PROMPT_FR)

    def test_prompts_cover_schools_and_vocab(self) -> None:
        fr = WASH_WHISPER_PROMPT_FR.lower()
        en = WASH_WHISPER_PROMPT_EN.lower()
        for school in ("bonanjo", "libermann", "bali", "ngok", "nkol", "pouuma", "nyo"):
            self.assertIn(school, fr)
            self.assertIn(school, en)
        for word in ("robinet", "fuite", "panne d'eau", "forage", "latrines", "château d'eau", "bloc a"):
            self.assertIn(word, fr)
        for word in ("leak", "tap", "borehole", "toilets", "water tower"):
            self.assertIn(word, en)

    def test_whisper_fr_gets_french_prompt(self) -> None:
        provider = WhisperCppProvider(binary="/bin/whisper", model="/models/x.bin")
        _, argv = _whisper_transcribe(provider, "fr")
        prompt = argv[argv.index("--prompt") + 1]
        self.assertIn("fuite", prompt)
        self.assertIn("Bonanjo", prompt)

    def test_mapping_prompt_overrides_default(self) -> None:
        provider = WhisperCppProvider.from_mapping(
            {"binary": "/bin/whisper", "model": "/models/x.bin", "prompt": "custom vocab"}
        )
        _, argv = _whisper_transcribe(provider, "fr")
        self.assertEqual(argv[argv.index("--prompt") + 1], "custom vocab")
        cloud = CloudWhisperProvider.from_mapping(
            {"base_url": "https://x/v1", "prompt": "custom vocab"}
        )
        _, posted = _cloud_transcribe(cloud, "fr")
        self.assertEqual(posted.get("prompt"), "custom vocab")

    def test_env_prompt_overrides_default(self) -> None:
        with patch.dict(os.environ, {"VOICE_STT_PROMPT": "env vocab"}, clear=False):
            provider = WhisperCppProvider(binary="/bin/whisper", model="/models/x.bin")
            _, argv = _whisper_transcribe(provider, "fr")
            self.assertEqual(argv[argv.index("--prompt") + 1], "env vocab")

    def test_empty_mapping_prompt_falls_back_to_default(self) -> None:
        provider = WhisperCppProvider.from_mapping(
            {"binary": "/bin/whisper", "model": "/models/x.bin", "prompt": ""}
        )
        _, argv = _whisper_transcribe(provider, "fr")
        self.assertIn("Bonanjo", argv[argv.index("--prompt") + 1])

    # -- TTS anglais : MMS eng, repli intact --------------------------------

    def test_mms_en_uses_eng_code(self) -> None:
        from app.tts_providers import MMSTTSProvider

        with tempfile.TemporaryDirectory() as tmp:
            provider = MMSTTSProvider(model_dir="/modeles-absents", cache_dir=tmp)
            seen: list[str] = []

            def fake_uncached(text: str, code: str) -> bytes:
                seen.append(code)
                return WAV_EN

            with patch.object(MMSTTSProvider, "_synthesize_uncached", side_effect=fake_uncached):
                audio = provider.synthesize("water leak", "v", "en")
        self.assertEqual(audio, WAV_EN)
        self.assertEqual(seen, ["eng"])

    def test_mms_en_success_reports_en_no_fallback(self) -> None:
        fake = FakeMMSOk()
        res = VoiceService().synthesize("water leak", language="en", tts=fake)
        self.assertEqual(res.audio_base64, base64.b64encode(WAV_EN).decode("utf-8"))
        self.assertEqual(res.driver, "mms")
        self.assertEqual(res.language_effective, "en")
        self.assertFalse(res.fallback)
        self.assertIsNone(res.notice)
        self.assertEqual(fake.seen, ["en"])

    def test_mms_en_down_falls_back_to_piper_fr_with_notice(self) -> None:
        svc = _piper_service()
        with patch("app.voice_service.os.path.isfile", side_effect=_piper_isfile), \
                patch("app.voice_service.subprocess.Popen", FakeProc):
            res = svc.synthesize("water leak", language="en", tts=FakeMMSDown())
        self.assertEqual(res.audio_base64, base64.b64encode(WAV_FR).decode("utf-8"))
        self.assertEqual(res.language_effective, "fr")
        self.assertTrue(res.fallback)
        assert res.notice is not None
        self.assertIn("anglaise", res.notice)
        self.assertIn("français standard", res.notice)
        self.assertNotIn("échec", res.notice.lower())

    def test_piper_only_en_fails_loudly_never_french_disguised(self) -> None:
        svc = _piper_service()
        with patch("app.voice_service.os.path.isfile", side_effect=_piper_isfile):
            with self.assertRaises(RuntimeError) as ctx:
                svc.synthesize("water leak", language="en")
        self.assertIn("[TTS_VOICE_UNAVAILABLE]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
