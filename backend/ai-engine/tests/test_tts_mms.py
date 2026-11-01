"""Tests MMS-TTS (langues locales) : repli Piper FR, sélection douala, cache.

Aucun modèle téléchargé, aucun transformers/torch requis : le provider réel
n'est exercé que sur ses chemins sans poids (résolution, cache, erreurs),
la synthèse est toujours fakée ou simulée (sys.modules).
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.tts_providers import (
    MMS_LANGUAGE_MAP,
    MMS_MISSING_PRETRAINED,
    TTS_PROVIDER_TYPES,
    BaseTTSProvider,
    MMSTTSProvider,
    PiperTTSProvider,
    default_tts,
    mms_model_source,
    tts_from_headers,
    tts_from_profile,
)
from app.voice_service import VoiceService

WAV_FR = b"RIFF$\x00\x00\x00WAVEfmt fake-piper-fr"
WAV_DUA = b"RIFF$\x00\x00\x00WAVEfmt fake-mms-dua"


class FakeMMSDown(BaseTTSProvider):
    """MMS indisponible (dépendances/modèle absents) : lève, jamais de silence."""

    driver_name = "mms"

    def synthesize(self, text: str, voice: str, language: str) -> bytes:
        raise RuntimeError("transformers/torch non installés (simulé).")


class FakeMMSOk(BaseTTSProvider):
    """MMS disponible : rend un WAV douala et mémorise la langue demandée."""

    driver_name = "mms"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def synthesize(self, text: str, voice: str, language: str) -> bytes:
        self.seen.append(language)
        return WAV_DUA


class FakeProc:
    """Faux binaire Piper : écrit WAV_FR dans --output_file."""

    def __init__(self, cmd: list, **kwargs) -> None:
        out = cmd[cmd.index("--output_file") + 1]
        with open(out, "wb") as f:
            f.write(WAV_FR)

    def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple:
        return ("", "")


def _piper_service() -> VoiceService:
    svc = VoiceService()
    svc.piper_bin = "/bin/piper"
    svc.piper_model = "/models/piper/fr_FR-upmc-medium.onnx"
    return svc


_real_isfile = os.path.isfile


def _piper_isfile(path: str) -> bool:
    if path in ("/bin/piper", "/models/piper/fr_FR-upmc-medium.onnx"):
        return True
    return _real_isfile(path)


class TtsMmsTest(unittest.TestCase):
    # -- Codes MMS documentés -----------------------------------------------

    def test_mms_language_map_covers_voice_languages(self) -> None:
        self.assertEqual(
            MMS_LANGUAGE_MAP,
            {"fr": "fra", "dua_Latn": "dua", "bassa": "bas", "ewondo": "ewo"},
        )

    def test_missing_pretrained_documents_meta_gap(self) -> None:
        # Vérifié 2026-11-01 : liste officielle Meta (1137 codes) + API Hub.
        self.assertEqual(MMS_MISSING_PRETRAINED, frozenset({"dua", "ewo", "bas"}))
        with self.assertRaises(RuntimeError) as ctx:
            mms_model_source("dua", "/modeles-absents")
        self.assertIn("dua", str(ctx.exception))

    def test_local_finetune_wins_over_hub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dua = os.path.join(tmp, "dua")
            os.makedirs(dua)
            open(os.path.join(dua, "config.json"), "w").write("{}")
            open(os.path.join(dua, "model.safetensors"), "w").write("poids")
            self.assertEqual(mms_model_source("dua", tmp), dua)
            self.assertEqual(
                mms_model_source("fra", tmp), "facebook/mms-tts-fra"
            )

    # -- Repli Piper FR automatique + message explicite ----------------------

    def test_mms_down_falls_back_to_piper_fr_with_notice(self) -> None:
        svc = _piper_service()
        with patch("app.voice_service.os.path.isfile", side_effect=_piper_isfile), \
                patch("app.voice_service.subprocess.Popen", FakeProc):
            res = svc.synthesize("mbolo", language="douala", tts=FakeMMSDown())
        self.assertEqual(res.audio_base64, base64.b64encode(WAV_FR).decode("utf-8"))
        self.assertEqual(res.mime_type, "audio/wav")
        self.assertEqual(res.driver, "mms")
        self.assertEqual(res.language_effective, "fr")
        self.assertTrue(res.fallback)
        assert res.notice is not None
        self.assertIn("douala", res.notice)
        self.assertIn("français standard", res.notice)
        self.assertNotIn("échec", res.notice.lower())

    def test_mms_down_notice_names_meta_gap_for_dua(self) -> None:
        svc = _piper_service()
        with patch("app.voice_service.os.path.isfile", side_effect=_piper_isfile), \
                patch("app.voice_service.subprocess.Popen", FakeProc):
            res = svc.synthesize("mbolo", language="dua_Latn", tts=FakeMMSDown())
        assert res.notice is not None
        self.assertIn("Meta MMS", res.notice)

    def test_real_mms_provider_down_falls_back(self) -> None:
        """Provider RÉEL sans poids ni dépendances -> repli, pas de crash."""
        svc = _piper_service()
        provider = MMSTTSProvider(model_dir="/modeles-absents", cache_dir=tempfile.mkdtemp())
        with patch("app.voice_service.os.path.isfile", side_effect=_piper_isfile), \
                patch("app.voice_service.subprocess.Popen", FakeProc):
            res = svc.synthesize("mbolo", language="dua_Latn", tts=provider)
        self.assertTrue(res.fallback)
        self.assertEqual(res.language_effective, "fr")
        self.assertTrue(res.audio_base64)

    def test_mms_and_piper_down_raises_guided_not_crash(self) -> None:
        svc = VoiceService()
        svc.piper_bin = "/introuvable/piper"
        with self.assertRaises(RuntimeError) as ctx:
            svc.synthesize("mbolo", language="dua_Latn", tts=FakeMMSDown())
        self.assertIn("[TTS_UNAVAILABLE]", str(ctx.exception))

    def test_missing_transformers_raises_explicit_runtime_error(self) -> None:
        """Import lazy : sans transformers/torch, erreur explicite, pas d'ImportError brut."""
        provider = MMSTTSProvider(model_dir="/modeles-absents", cache_dir=tempfile.mkdtemp())
        with patch.dict(sys.modules, {"transformers": None, "torch": None}):
            with self.assertRaises(RuntimeError) as ctx:
                provider._load("fra")
        self.assertIn("transformers/torch", str(ctx.exception))

    # -- Profil douala sélectionné quand MMS disponible ----------------------

    def test_dua_profile_selected_when_mms_available(self) -> None:
        svc = _piper_service()
        fake = FakeMMSOk()
        res = svc.synthesize("mbolo na wase", language="douala", tts=fake)
        self.assertEqual(res.audio_base64, base64.b64encode(WAV_DUA).decode("utf-8"))
        self.assertEqual(res.driver, "mms")
        self.assertEqual(res.language_effective, "dua_Latn")
        self.assertFalse(res.fallback)
        self.assertIsNone(res.notice)
        self.assertEqual(fake.seen, ["dua_Latn"])  # alias normalisé avant appel.

    def test_mms_driver_keeps_fr_on_piper(self) -> None:
        svc = _piper_service()
        fake = FakeMMSOk()
        with patch("app.voice_service.os.path.isfile", side_effect=_piper_isfile), \
                patch("app.voice_service.subprocess.Popen", FakeProc):
            res = svc.synthesize("bonjour", language="fr", tts=fake)
        self.assertEqual(res.audio_base64, base64.b64encode(WAV_FR).decode("utf-8"))
        self.assertEqual(res.language_effective, "fr")
        self.assertFalse(res.fallback)
        self.assertEqual(fake.seen, [])  # FR ne passe jamais par MMS.

    def test_mms_empty_text_stays_guided(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            VoiceService().synthesize("   ", language="dua_Latn", tts=FakeMMSOk())
        self.assertIn("[TTS_EMPTY_TEXT]", str(ctx.exception))

    # -- Registre / profils switchables, FR par défaut ------------------------

    def test_default_driver_is_piper_fr(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "TTS_DRIVER"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsInstance(default_tts(), PiperTTSProvider)

    def test_profiles_switch_drivers(self) -> None:
        self.assertIsInstance(tts_from_profile({"driver": "mms"}), MMSTTSProvider)
        self.assertIsInstance(tts_from_profile({"driver": "piper"}), PiperTTSProvider)
        self.assertIsInstance(tts_from_profile({"driver": "inconnu"}), PiperTTSProvider)
        self.assertIsInstance(tts_from_headers({"x-tts-driver": "mms"}), MMSTTSProvider)
        with patch.dict(os.environ, {"TTS_DRIVER": "mms"}, clear=False):
            self.assertIsInstance(default_tts(), MMSTTSProvider)

    def test_provider_types_flag_local_languages(self) -> None:
        flags = {d["id"]: d.get("local_languages") for d in TTS_PROVIDER_TYPES}
        self.assertIs(flags["mms"], True)
        self.assertIs(flags["piper"], False)

    # -- Cache disque ----------------------------------------------------------

    def test_cache_hit_avoids_resynthesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = MMSTTSProvider(model_dir="/modeles-absents", cache_dir=tmp)
            calls: list[str] = []

            def fake_uncached(text: str, code: str) -> bytes:
                calls.append(f"{code}:{text}")
                return WAV_DUA

            with patch.object(MMSTTSProvider, "_synthesize_uncached", side_effect=fake_uncached):
                first = provider.synthesize("mbolo", "v", "dua_Latn")
                second = provider.synthesize("mbolo", "v", "dua_Latn")
                third = provider.synthesize("mbolo na wase", "v", "dua_Latn")
            self.assertEqual(first, WAV_DUA)
            self.assertEqual(second, WAV_DUA)
            self.assertEqual(third, WAV_DUA)
            self.assertEqual(len(calls), 2)  # 1 miss + 1 hit + 1 miss.
            cached_files = [
                f for _, _, files in os.walk(tmp) for f in files if f.endswith(".wav")
            ]
            self.assertEqual(len(cached_files), 2)

    def test_cache_is_per_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = MMSTTSProvider(model_dir="/modeles-absents", cache_dir=tmp)
            with patch.object(
                MMSTTSProvider, "_synthesize_uncached",
                side_effect=lambda text, code: f"WAV-{code}".encode(),
            ):
                dua = provider.synthesize("mbolo", "v", "dua_Latn")
                bas = provider.synthesize("mbolo", "v", "bassa")
            self.assertNotEqual(dua, bas)


if __name__ == "__main__":
    unittest.main()
