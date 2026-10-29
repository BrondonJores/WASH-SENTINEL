from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Any

import httpx


def normalize_to_wav(audio_bytes: bytes, filename: str, workdir: str) -> str:
    """Normalise n'importe quel audio en WAV PCM 16kHz mono via FFmpeg."""
    input_file = os.path.join(workdir, filename)
    with open(input_file, "wb") as f:
        f.write(audio_bytes)
    wav_file = os.path.join(workdir, "normalized.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_file, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_file],
        capture_output=True, check=False,
    )
    if not os.path.isfile(wav_file):
        raise RuntimeError("FFmpeg introuvable ou audio illisible (normalisation 16kHz impossible).")
    return wav_file


class BaseSTTProvider:
    """Contrat commun : tout moteur de transcription (local ou cloud) l'implémente."""

    driver_name = "base"

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "BaseSTTProvider":
        raise NotImplementedError

    def test(self, audio_bytes: bytes, filename: str, language: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = self.transcribe(audio_bytes, filename, language)
            return {
                "ok": True,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "transcript": result.get("transcript", ""),
                "language": result.get("language", language),
                "error": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "transcript": "",
                "language": language,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }

    def describe(self) -> dict[str, Any]:
        return {"driver": self.driver_name}


class WhisperCppProvider(BaseSTTProvider):
    """Transcription locale via Whisper.cpp (rapide, idéal français)."""

    driver_name = "whisper_cpp"

    def __init__(self, binary: str | None = None, model: str | None = None, timeout: float = 120.0):
        self.binary = binary or os.getenv("VOICE_STT_BINARY", "/opt/voice/bin/whisper-cli")
        self.model = model or os.getenv("VOICE_STT_MODEL", "/models/whisper/ggml-base.bin")
        self.timeout = timeout

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "WhisperCppProvider":
        return cls(
            binary=mapping.get("binary") or None,
            model=mapping.get("model") or None,
            timeout=float(mapping.get("timeout") or 120.0),
        )

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict[str, Any]:
        if not os.path.isfile(self.binary) or not os.path.isfile(self.model):
            raise RuntimeError(f"Whisper indisponible (binaire ou modèle introuvable : {self.model}).")
        with tempfile.TemporaryDirectory(prefix="wash-stt-") as tmpdir:
            wav_file = normalize_to_wav(audio_bytes, filename, tmpdir)
            out_base = os.path.join(tmpdir, "output")
            res = subprocess.run(
                [self.binary, "-m", self.model, "-f", wav_file,
                 "-l", language if len(language) <= 3 else "auto",
                 "-otxt", "-of", out_base],
                capture_output=True, text=True, check=False, timeout=self.timeout,
            )
            transcript = ""
            txt_file = out_base + ".txt"
            if os.path.isfile(txt_file):
                with open(txt_file, encoding="utf-8") as tf:
                    transcript = tf.read().strip()
            return {"transcript": transcript or res.stdout.strip(), "language": language}


class OmnilingualOnnxProvider(BaseSTTProvider):
    """Transcription locale Meta Omnilingual ASR via sherpa-onnx (1600+ langues, CPU OK)."""

    driver_name = "omnilingual_onnx"

    def __init__(
        self,
        model: str | None = None,
        tokens: str | None = None,
        num_threads: int = 2,
        provider: str = "cpu",
        timeout: float = 180.0,
    ):
        self.model = model or os.getenv("OMNI_STT_MODEL", "/models/omnilingual/model.int8.onnx")
        self.tokens = tokens or os.getenv("OMNI_STT_TOKENS", "/models/omnilingual/tokens.txt")
        self.num_threads = num_threads
        self.provider = provider
        self.timeout = timeout
        self._recognizer: Any = None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "OmnilingualOnnxProvider":
        return cls(
            model=mapping.get("model") or None,
            tokens=mapping.get("tokens") or None,
            num_threads=int(mapping.get("threads") or 2),
            provider=mapping.get("provider") or "cpu",
            timeout=float(mapping.get("timeout") or 180.0),
        )

    def _load(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx non installé (ajoutez-le aux dépendances).") from exc
        if not os.path.isfile(self.model):
            raise RuntimeError(f"Modèle Omnilingual introuvable : {self.model} (téléchargez model.int8.onnx).")
        if not os.path.isfile(self.tokens):
            raise RuntimeError(f"Fichier tokens introuvable : {self.tokens}.")
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_omnilingual_asr_ctc(
            model=self.model, tokens=self.tokens,
            num_threads=self.num_threads, provider=self.provider,
        )
        return self._recognizer

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict[str, Any]:
        import wave

        import numpy as np

        recognizer = self._load()
        with tempfile.TemporaryDirectory(prefix="wash-omni-") as tmpdir:
            wav_file = normalize_to_wav(audio_bytes, filename, tmpdir)
            with wave.open(wav_file, "rb") as w:
                if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
                    raise RuntimeError("Format WAV inattendu après normalisation (16kHz mono requis).")
                samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        return {"transcript": (stream.result.text or "").strip(), "language": language}


class CloudWhisperProvider(BaseSTTProvider):
    """Transcription cloud via API compatible OpenAI /audio/transcriptions (OpenAI, Groq...)."""

    driver_name = "cloud_whisper"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ):
        self.base_url = (base_url or os.getenv("CLOUD_STT_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("CLOUD_STT_MODEL", "whisper-1")
        self.api_key = api_key or os.getenv("CLOUD_STT_API_KEY")
        self.timeout = timeout

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "CloudWhisperProvider":
        return cls(
            base_url=mapping.get("base_url") or None,
            model=mapping.get("model") or None,
            api_key=mapping.get("api_key") or None,
            timeout=float(mapping.get("timeout") or 120.0),
        )

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data: dict[str, str] = {"model": self.model, "response_format": "json"}
        if len(language) == 2:
            data["language"] = language
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/audio/transcriptions",
                headers=headers,
                files={"file": (filename, audio_bytes, "audio/wav")},
                data=data,
            )
            response.raise_for_status()
            return {"transcript": response.json().get("text", ""), "language": language}


STT_REGISTRY: dict[str, type[BaseSTTProvider]] = {
    "whisper_cpp": WhisperCppProvider,
    "whisper": WhisperCppProvider,
    "omnilingual_onnx": OmnilingualOnnxProvider,
    "omnilingual": OmnilingualOnnxProvider,
    "cloud_whisper": CloudWhisperProvider,
    "cloud": CloudWhisperProvider,
}


def _mapping_from_headers(headers: Any) -> dict[str, Any]:
    get = headers.get
    return {
        "driver": get("x-stt-driver") or os.getenv("STT_DRIVER", "whisper_cpp"),
        "model": get("x-stt-model") or None,
        "tokens": get("x-stt-tokens") or None,
        "base_url": get("x-stt-base-url") or None,
        "api_key": get("x-stt-api-key") or None,
        "threads": get("x-stt-threads") or None,
        "timeout": get("x-stt-timeout") or None,
    }


def stt_from_headers(headers: Any) -> BaseSTTProvider:
    mapping = _mapping_from_headers(headers)
    driver = (mapping.get("driver") or "whisper_cpp").lower()
    provider_cls = STT_REGISTRY.get(driver, WhisperCppProvider)
    return provider_cls.from_mapping(mapping)


def stt_from_profile(profile: dict[str, Any]) -> BaseSTTProvider:
    driver = (profile.get("driver") or "whisper_cpp").lower()
    provider_cls = STT_REGISTRY.get(driver, WhisperCppProvider)
    return provider_cls.from_mapping(profile)


def default_stt() -> BaseSTTProvider:
    return stt_from_headers({})


STT_PROVIDER_TYPES: list[dict[str, Any]] = [
    {
        "id": "whisper_cpp",
        "label": "Whisper local (français)",
        "description": "Whisper.cpp sur CPU : rapide et léger, idéal pour le français.",
        "api_key_required": False,
        "fields": [
            {"name": "model", "label": "Modèle Whisper (.bin)", "type": "text", "default": "/models/whisper/ggml-base.bin", "required": True},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "120", "required": False},
        ],
    },
    {
        "id": "omnilingual_onnx",
        "label": "Omnilingual Meta (langues locales)",
        "description": "Meta Omnilingual ASR en ONNX int8 : 1600+ langues dont douala (dua_Latn), bassa, ewondo. CPU OK.",
        "api_key_required": False,
        "fields": [
            {"name": "model", "label": "Modèle ONNX (.onnx)", "type": "text", "default": "/models/omnilingual/model.int8.onnx", "required": True},
            {"name": "tokens", "label": "Fichier tokens (tokens.txt)", "type": "text", "default": "/models/omnilingual/tokens.txt", "required": True},
            {"name": "threads", "label": "Threads CPU", "type": "number", "default": "2", "required": False},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "180", "required": False},
        ],
    },
    {
        "id": "cloud_whisper",
        "label": "API cloud (OpenAI / Groq)",
        "description": "Endpoint /audio/transcriptions compatible OpenAI. Nécessite une clé API.",
        "api_key_required": True,
        "fields": [
            {"name": "base_url", "label": "URL de base (/v1)", "type": "url", "default": "https://api.openai.com/v1", "required": True},
            {"name": "model", "label": "Modèle (ex: whisper-1)", "type": "text", "default": "whisper-1", "required": True},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "120", "required": False},
        ],
    },
]
