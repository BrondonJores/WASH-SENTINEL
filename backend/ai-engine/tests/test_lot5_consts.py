"""LOT 5 anti-valeurs-en-dur : voix/vision — défauts, overrides ENV, unification.

Vérifie que les valeurs métier centralisées gardent leurs défauts historiques,
que chaque nouvelle variable ENV les surcharge (reload), et que le défaut
vision est UNIQUE (moondream, provider + analyseur + UI). Ne modifie aucun
comportement métier : la faute 'anglaise' est corrigée dans le dictionnaire
de libellés, l'accord féminin restant assuré dans le message rendu.
"""
from __future__ import annotations

import importlib
import os
import unittest
from unittest.mock import patch


def _reload_with_env(module_name: str, env: dict[str, str]):
    """Recharge un module avec des ENV posées ; restaure tout après."""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return importlib.reload(importlib.import_module(module_name))
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


class _ReloadMixin:
    def _check_override(self, module_name: str, env_name: str,
                        attr: str, override: str, expected) -> None:
        self.addCleanup(importlib.reload, importlib.import_module(module_name))
        mod = _reload_with_env(module_name, {env_name: override})
        self.assertEqual(getattr(mod, attr), expected)


class Lot5RetryDefaultsTest(unittest.TestCase):
    """Défauts historiques robustesse LLM inchangés."""

    def test_retry_policy(self) -> None:
        from app import providers
        self.assertEqual(providers.RETRY_MAX_ATTEMPTS, 3)
        self.assertEqual(providers.RETRY_BACKOFF_SECONDS, (1.0, 2.0, 4.0))
        self.assertEqual(providers.RETRYABLE_STATUS_CODES,
                         frozenset({408, 429, 500, 502, 503, 504}))
        self.assertEqual(providers.EMBED_BATCH_CONCURRENCY, 4)
        self.assertEqual(providers.WARMUP_TIMEOUT_SECONDS_DEFAULT, 15.0)

    def test_temperature_and_timeouts(self) -> None:
        from app import providers
        self.assertEqual(providers.LLM_TEMPERATURE, 0.1)
        self.assertEqual(providers.LLM_DEFAULT_TIMEOUT_SECONDS, 120.0)
        self.assertEqual(providers.LLM_EMBED_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(providers.PROVIDER_TEST_TIMEOUT_DEFAULT, 30.0)


class Lot5RetryEnvTest(unittest.TestCase, _ReloadMixin):
    """Overrides ENV robustesse + repli sur défaut si invalide."""

    def test_overrides(self) -> None:
        self._check_override("app.providers", "LLM_RETRY_MAX_ATTEMPTS",
                             "RETRY_MAX_ATTEMPTS", "5", 5)
        self._check_override("app.providers", "LLM_RETRY_BACKOFF_SECONDS",
                             "RETRY_BACKOFF_SECONDS", "0.5,1.5", (0.5, 1.5))
        self._check_override("app.providers", "LLM_RETRYABLE_STATUS_CODES",
                             "RETRYABLE_STATUS_CODES", "429,503",
                             frozenset({429, 503}))
        self._check_override("app.providers", "LLM_EMBED_CONCURRENCY",
                             "EMBED_BATCH_CONCURRENCY", "8", 8)

    def test_invalid_falls_back_to_defaults(self) -> None:
        self._check_override("app.providers", "LLM_RETRY_MAX_ATTEMPTS",
                             "RETRY_MAX_ATTEMPTS", "pas-un-nombre", 3)
        self._check_override("app.providers", "LLM_RETRY_BACKOFF_SECONDS",
                             "RETRY_BACKOFF_SECONDS", "nope", (1.0, 2.0, 4.0))
        self._check_override("app.providers", "LLM_RETRYABLE_STATUS_CODES",
                             "RETRYABLE_STATUS_CODES", "",
                             frozenset({408, 429, 500, 502, 503, 504}))


class Lot5VisionUnificationTest(unittest.TestCase):
    """UN SEUL défaut vision (moondream) : provider + analyseur + UI."""

    def test_shared_default_is_moondream(self) -> None:
        from app import image_analyzer, providers
        self.assertEqual(providers.DEFAULT_VISION_MODEL, "moondream")
        self.assertEqual(image_analyzer.DEFAULT_VISION_MODEL, "moondream")
        self.assertEqual(providers.VISION_MODEL_ENV_VAR, "OLLAMA_VISION_MODEL")
        self.assertEqual(image_analyzer.VISION_MODEL_ENV_VAR, "OLLAMA_VISION_MODEL")

    def test_provider_default_and_env_override(self) -> None:
        from app.providers import OllamaProvider
        saved = os.environ.pop("OLLAMA_VISION_MODEL", None)
        try:
            self.assertEqual(OllamaProvider().vision_model, "moondream")
        finally:
            if saved is not None:
                os.environ["OLLAMA_VISION_MODEL"] = saved
        with patch.dict(os.environ, {"OLLAMA_VISION_MODEL": "llama3.2-vision:11b"}):
            self.assertEqual(OllamaProvider().vision_model, "llama3.2-vision:11b")

    def _ui_default(self, providers_mod, provider_id: str, field: str) -> str:
        for entry in providers_mod.PROVIDER_TYPES:
            if entry["id"] == provider_id:
                for f in entry["fields"]:
                    if f["name"] == field:
                        return f["default"]
        raise AssertionError(f"champ UI {provider_id}.{field} introuvable")

    def test_ui_defaults_derive_from_same_env(self) -> None:
        names = ("OLLAMA_URL", "OLLAMA_MODEL", "OLLAMA_VISION_MODEL",
                 "OLLAMA_EMBED_MODEL", "OPENAI_BASE_URL", "OPENAI_MODEL",
                 "OPENAI_VISION_MODEL", "OPENAI_EMBED_MODEL")
        saved = {k: os.environ.get(k) for k in names}
        for k in names:
            os.environ.pop(k, None)
        self.addCleanup(importlib.reload, importlib.import_module("app.providers"))
        try:
            mod = importlib.reload(importlib.import_module("app.providers"))
            self.assertEqual(self._ui_default(mod, "ollama", "vision_model"), "moondream")
            self.assertEqual(self._ui_default(mod, "ollama", "model"), "llama3.2:3b")
            self.assertEqual(self._ui_default(mod, "openai_compatible", "model"), "gpt-4o-mini")
            os.environ["OLLAMA_VISION_MODEL"] = "llava:7b"
            mod2 = importlib.reload(mod)
            self.assertEqual(self._ui_default(mod2, "ollama", "vision_model"), "llava:7b")
        finally:
            for key, old in saved.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old
            importlib.reload(importlib.import_module("app.providers"))


class Lot5VoiceConstsTest(unittest.TestCase):
    """Plafonds et formats voix centralisés, valeurs inchangées."""

    def test_12mo_single_reference(self) -> None:
        from app import stt_providers, voice_service
        self.assertEqual(stt_providers.STT_MAX_INPUT_MB, 12)
        self.assertEqual(stt_providers.MAX_STT_INPUT_BYTES, 12 * 1024 * 1024)
        self.assertEqual(voice_service.MAX_VOICE_AUDIO_BYTES,
                         stt_providers.MAX_STT_INPUT_BYTES)
        self.assertIn("max 12 Mo", voice_service.voice_too_heavy_message(13 * 1024 * 1024))

    def test_audio_format_and_timeouts(self) -> None:
        from app import stt_providers, voice_service
        self.assertEqual(stt_providers.STT_SAMPLE_RATE_HZ, 16000)
        self.assertEqual(stt_providers.STT_CHANNELS, 1)
        self.assertEqual(stt_providers.FFMPEG_NORMALIZE_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(voice_service.FFPROBE_TIMEOUT_SECONDS, 10.0)
        self.assertEqual(voice_service.MIN_AUDIO_SECONDS, 0.5)
        self.assertEqual(voice_service.MAX_AUDIO_SECONDS, 300.0)
        self.assertEqual(voice_service.SILENCE_RMS_THRESHOLD, 0.02)
        self.assertEqual(voice_service.NOISE_RMS_THRESHOLD, 0.15)
        self.assertEqual(voice_service.MAX_TTS_CHARS, 1000)
        self.assertEqual(voice_service.VOICE_AUDIO_CHUNK_BYTES, 1024 * 1024)
        self.assertEqual(voice_service.TTS_SYNTHESIS_TIMEOUT, 60.0)

    def test_anglais_label_with_feminine_agreement(self) -> None:
        from app.voice_service import VOICE_LANGUAGE_LABELS, mms_fallback_notice
        self.assertEqual(VOICE_LANGUAGE_LABELS["en"], "anglais")
        notice = mms_fallback_notice("en")
        self.assertIn("anglaise", notice)  # « voix anglaise » reste correct
        self.assertIn("français standard", notice)
        self.assertIn("douala", mms_fallback_notice("dua_Latn"))


class Lot5OmniReposTest(unittest.TestCase):
    """Repos HF en CONST + override ENV, 16 kHz partagé."""

    def test_repos_defaults(self) -> None:
        from app import stt_omnilingual, stt_providers
        self.assertEqual(stt_omnilingual.OMNI_CTC_HF_REPO, "facebook/omniASR-CTC-300M")
        self.assertTrue(stt_omnilingual.OMNI_CTC_ONNX_REPO_FULL.startswith("csukuangfj/"))
        self.assertEqual(stt_providers.STT_SAMPLE_RATE_HZ, 16000)

    def test_onnx_repo_env_override(self) -> None:
        # Sous-processus hermétique : aucun reload in-process (le registre
        # STT partagé garderait l'ancienne classe du module rechargé).
        import subprocess
        import sys
        env = dict(os.environ, OMNI_CTC_ONNX_REPO="miroir-local/modele")
        code = (
            "from app.stt_omnilingual import OMNI_CTC_ONNX_REPO_FULL;"
            "print(OMNI_CTC_ONNX_REPO_FULL)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            check=False, timeout=120, env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "miroir-local/modele")


class Lot5GuidedConstsTest(unittest.TestCase):
    """Dicts QUESTIONS[lang], troncature école, verdicts, pastilles."""

    def test_questions_dicts(self) -> None:
        from app import guided_voice as gv
        self.assertIs(gv.QUESTIONS["fr"], gv.QUESTIONS_FR)
        self.assertIs(gv.QUESTIONS["dua"], gv.QUESTIONS_DUA)
        self.assertEqual(gv.QUESTIONS["fr"][gv.SCHOOL], gv.Q_SCHOOL_FR)
        self.assertEqual(gv.QUESTIONS["dua"][gv.PROBLEM], gv.Q_PROBLEM_DUA)
        self.assertEqual(gv.CONFIRM_TAILS["fr"], gv.Q_CONFIRM_TAIL_FR)
        self.assertEqual(gv.CONFIRM_TAILS["dua"], gv.Q_CONFIRM_TAIL_DUA)
        self.assertEqual(gv.ask(gv.SCHOOL, None, "dua"), gv.Q_SCHOOL_DUA)

    def test_truncation_verdicts_chips(self) -> None:
        from app import guided_voice as gv
        self.assertEqual(gv.SCHOOL_LABEL_MAX_CHARS, 80)
        self.assertEqual((gv.CONFIRM_YES, gv.CONFIRM_NO,
                          gv.CONFIRM_REPEAT, gv.CONFIRM_UNKNOWN),
                         ("yes", "no", "repeat", "unknown"))
        self.assertEqual(gv.PROBLEM_CHIPS, ["Eau", "Toilettes", "Fuite"])
        self.assertEqual(gv.CONFIRM_CHIPS, ["Oui", "Non"])
        self.assertEqual(gv.MAX_GUIDED_CHIPS, 3)
        chips = gv.guided_chips(gv.PROBLEM)
        chips.append("X")
        self.assertEqual(gv.PROBLEM_CHIPS, ["Eau", "Toilettes", "Fuite"])


class Lot5RagEnvTest(unittest.TestCase, _ReloadMixin):
    """Chunk/overlap/K/seuil RAG : défauts + overrides ENV."""

    def test_defaults(self) -> None:
        from app import rag_store
        self.assertEqual(rag_store.CHUNK_SIZE, 500)
        self.assertEqual(rag_store.CHUNK_OVERLAP, 50)
        self.assertEqual(rag_store.DEFAULT_K, 3)
        self.assertEqual(rag_store.MIN_SIMILARITY, 0.30)

    def test_overrides_and_invalid_fallback(self) -> None:
        self._check_override("app.rag_store", "RAG_CHUNK_SIZE",
                             "CHUNK_SIZE", "100", 100)
        self._check_override("app.rag_store", "RAG_CHUNK_OVERLAP",
                             "CHUNK_OVERLAP", "10", 10)
        self._check_override("app.rag_store", "RAG_TOP_K", "DEFAULT_K", "5", 5)
        self._check_override("app.rag_store", "RAG_MIN_SIMILARITY",
                             "MIN_SIMILARITY", "0.5", 0.5)
        self._check_override("app.rag_store", "RAG_CHUNK_SIZE",
                             "CHUNK_SIZE", "nope", 500)


class Lot5MetricsEnvTest(unittest.TestCase, _ReloadMixin):
    """Buffer métriques + tarifs : défauts + overrides ENV."""

    def test_defaults(self) -> None:
        from app import ai_metrics
        self.assertEqual(ai_metrics.MAX_ENTRIES, 500)
        self.assertEqual(ai_metrics.COST_PER_1K["llama3.2:3b"], 0.0)
        self.assertEqual(ai_metrics.COST_PER_1K["gpt-4o-mini"], 0.30)

    def test_overrides_and_invalid_fallback(self) -> None:
        self._check_override("app.ai_metrics", "AI_METRICS_MAX_ENTRIES",
                             "MAX_ENTRIES", "50", 50)
        self._check_override("app.ai_metrics", "AI_METRICS_MAX_ENTRIES",
                             "MAX_ENTRIES", "nope", 500)
        mod = _reload_with_env("app.ai_metrics",
                               {"AI_METRICS_COSTS_JSON": '{"gpt-4o-mini": 0.99}'})
        self.assertEqual(mod.COST_PER_1K["gpt-4o-mini"], 0.99)
        self.assertEqual(mod.COST_PER_1K["gpt-4o"], 3.00)
        importlib.reload(mod)
        mod2 = _reload_with_env("app.ai_metrics",
                                {"AI_METRICS_COSTS_JSON": "pas-du-json"})
        self.assertEqual(mod2.COST_PER_1K["gpt-4o-mini"], 0.30)
        importlib.reload(mod2)


class Lot5RepairMainConstsTest(unittest.TestCase):
    """Replis réparateur + troncature triage en CONST."""

    def test_repair_fallbacks(self) -> None:
        from app import repair_advisor as ra
        self.assertIn("Clé à griffe", ra.FALLBACK_REQUIRED_TOOLS)
        self.assertIn("Joints d'étanchéité", ra.FALLBACK_SPARE_PARTS)
        self.assertEqual(len(ra.FALLBACK_SAFETY_MEASURES), 3)
        self.assertEqual(ra.DEFAULT_COST_TIER, "medium")
        self.assertIn("critical_budget", ra.VALID_COST_TIERS)
        self.assertEqual(ra.DEFAULT_INTERVENTION_TIME, "2 heures")

    def test_main_error_truncation(self) -> None:
        # AST, sans import (fastapi hors venv) : CONST définie, utilisée pour
        # la troncature d'erreur, et score borné par SCORE_MAX partagé.
        import ast
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "app", "main.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        assigns: dict[str, object] = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                try:
                    assigns[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue
        self.assertEqual(assigns.get("ERROR_DETAIL_MAX_CHARS"), 200)
        with open(os.path.join(here, "..", "app", "main.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertIn("str(exc)[:ERROR_DETAIL_MAX_CHARS]", source)
        self.assertIn("min(SCORE_MAX, base_score + boost)", source)


if __name__ == "__main__":
    unittest.main()
