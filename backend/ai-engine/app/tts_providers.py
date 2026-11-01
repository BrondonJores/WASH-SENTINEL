from __future__ import annotations

import hashlib
import os
import tempfile
import time
from typing import Any

from .stt_providers import SUPPORTED_VOICE_LANGUAGES

# NOTE — AUCUNE dépendance lourde au top-level : transformers/torch sont
# importés paresseusement dans MMSTTSProvider._load() uniquement. Sans eux,
# le provider lève un RuntimeError explicite et VoiceService replie
# automatiquement vers Piper FR (jamais de crash, jamais de silence).
# requirements.txt reste donc verrouillé : rien à y ajouter.


#: Langue console -> code ISO 639-3 MMS-TTS.
#: "en" -> "eng" : Meta publie facebook/mms-tts-eng (checkpoint réel,
#: PAS dans MMS_MISSING_PRETRAINED). Synthèse anglaise via MMS, repli
#: Piper FR explicite si indisponible (jamais de FR déguisé en EN).
MMS_LANGUAGE_MAP: dict[str, str] = {
    "fr": "fra",
    "en": "eng",
    "dua_Latn": "dua",
    "bassa": "bas",
    "ewondo": "ewo",
}

#: Gabarit des checkpoints monolingues Meta MMS-TTS sur le Hub.
MMS_MODEL_ID_TEMPLATE = "facebook/mms-tts-{code}"

#: Couverture réelle vérifiée le 2026-11-01 (liste officielle Meta, 1137 codes :
#: https://dl.fbaipublicfiles.com/mms/tts/all-tts-languages.html — corroborée
#: par l'API HuggingFace : facebook/mms-tts-{dua,ewo,bas} inexistants) :
#: AUCUN checkpoint pré-entraîné pour dua (douala), ewo (ewondo) et bas
#: (basaa du Cameroun). `bsq` existe mais c'est le bassa du LIBERIA, une
#: autre langue : aucune substitution silencieuse. Quand Meta publiera
#: facebook/mms-tts-dua (ou un fine-tune local), ce provider fonctionne sans
#: changement de code : il suffit de poser le modèle dans MMS_TTS_MODEL_DIR.
MMS_MISSING_PRETRAINED: frozenset[str] = frozenset({"dua", "ewo", "bas"})

#: Fichiers de poids acceptés pour un modèle local MMS_TTS_MODEL_DIR/<code>/.
MMS_LOCAL_WEIGHT_FILENAMES: tuple[str, ...] = ("model.safetensors", "pytorch_model.bin")


def mms_model_source(code: str, model_dir: str) -> str:
    """Checkpoint MMS pour un code langue : dossier local ou identifiant Hub.

    Priorité au modèle local (<model_dir>/<code>/ avec config + poids) :
    aucun téléchargement surprise. Sans modèle local et sans checkpoint
    pré-entraîné connu (dua/ewo/bas), échec explicite. Sinon identifiant Hub
    (téléchargement au premier usage réel, jamais pendant les tests).
    """
    local = os.path.join(model_dir, code)
    if os.path.isdir(local) and os.path.isfile(os.path.join(local, "config.json")) and any(
        os.path.isfile(os.path.join(local, name)) for name in MMS_LOCAL_WEIGHT_FILENAMES
    ):
        return local
    if code in MMS_MISSING_PRETRAINED:
        raise RuntimeError(
            f"Pas de voix MMS pré-entraînée pour le code {code!r} "
            f"(ni checkpoint Meta, ni modèle local dans {local})."
        )
    return MMS_MODEL_ID_TEMPLATE.format(code=code)


class BaseTTSProvider:
    """Contrat commun : tout moteur de synthèse vocale l'implémente."""

    driver_name = "base"

    def synthesize(self, text: str, voice: str, language: str) -> bytes:
        """Synthétise un texte (déjà validé/non vide) et renvoie un WAV brut."""
        raise NotImplementedError

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "BaseTTSProvider":
        raise NotImplementedError

    def test(self, text: str = "bonjour", language: str = "fr") -> dict[str, Any]:
        started = time.perf_counter()
        try:
            audio = self.synthesize(text, "", language)
            return {
                "ok": True,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "audio_bytes": len(audio),
                "language": language,
                "error": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "audio_bytes": 0,
                "language": language,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }

    def describe(self) -> dict[str, Any]:
        return {"driver": self.driver_name}


class PiperTTSProvider(BaseTTSProvider):
    """Synthèse locale via Piper (français standard, voix par défaut)."""

    driver_name = "piper"

    def __init__(self, binary: str | None = None, model: str | None = None):
        self.binary = binary or os.getenv("VOICE_TTS_BINARY", "/opt/voice/bin/piper")
        self.model = model or os.getenv("VOICE_TTS_MODEL", "/models/piper/fr_FR-upmc-medium.onnx")

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "PiperTTSProvider":
        return cls(
            binary=mapping.get("binary") or None,
            model=mapping.get("model") or None,
        )

    def describe(self) -> dict[str, Any]:
        return {"driver": self.driver_name, "binary": self.binary, "model": self.model}

    def synthesize(self, text: str, voice: str, language: str) -> bytes:
        # Import tardif : voice_service importe ce module au top-level.
        from .voice_service import VoiceService

        svc = VoiceService()
        svc.piper_bin = self.binary
        svc.piper_model = self.model
        return svc._synthesize_piper_bytes(text, voice, language)


class MMSTTSProvider(BaseTTSProvider):
    """Synthèse Meta MMS-TTS (VITS monolingue, CPU OK) pour les langues locales.

    Exemple d'usage réel (hors tests) : TTS_DRIVER=mms +
    MMS_TTS_MODEL_DIR=/models/mms-tts contenant dua/, bas/, ewo/.
    """

    driver_name = "mms"

    def __init__(
        self,
        model_dir: str | None = None,
        cache_dir: str | None = None,
    ):
        self.model_dir = model_dir or os.getenv("MMS_TTS_MODEL_DIR", "/models/mms-tts")
        self.cache_dir = cache_dir or os.getenv(
            "MMS_TTS_CACHE_DIR", os.path.join(tempfile.gettempdir(), "wash-mms-tts")
        )
        self._loaded: dict[str, Any] = {}

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "MMSTTSProvider":
        return cls(
            model_dir=mapping.get("model_dir") or mapping.get("model") or None,
            cache_dir=mapping.get("cache_dir") or None,
        )

    def describe(self) -> dict[str, Any]:
        return {"driver": self.driver_name, "model_dir": self.model_dir, "cache_dir": self.cache_dir}

    def _cache_path(self, code: str, text: str) -> str:
        digest = hashlib.sha1(f"{code}\0{text}".encode("utf-8")).hexdigest()[:32]
        return os.path.join(self.cache_dir, code, f"{digest}.wav")

    def _load(self, code: str) -> Any:
        """Charge (une fois par langue) le couple tokenizer + modèle VITS.

        Import paresseux obligatoire : transformers/torch ne sont PAS des
        dépendances dures. Absents -> RuntimeError explicite (repli Piper FR).
        """
        if code in self._loaded:
            return self._loaded[code]
        try:
            import torch  # noqa: F401
            from transformers import AutoTokenizer, VitsModel
        except ImportError as exc:
            raise RuntimeError(
                "Voix Meta MMS indisponible : transformers/torch ne sont pas "
                "installés (dépendances optionnelles, repli français standard)."
            ) from exc
        source = mms_model_source(code, self.model_dir)
        tokenizer = AutoTokenizer.from_pretrained(source)
        model = VitsModel.from_pretrained(source)
        loaded = (tokenizer, model)
        self._loaded[code] = loaded
        return loaded

    def _synthesize_uncached(self, text: str, code: str) -> bytes:
        """Synthèse VITS brute -> WAV PCM 16 bits (stdlib wave uniquement)."""
        import struct
        import wave

        tokenizer, model = self._load(code)
        inputs = tokenizer(text, return_tensors="pt")
        waveform = model(**inputs).waveform[0]
        try:
            samples = waveform.detach().cpu().tolist()
        except Exception:
            samples = [float(v) for v in waveform[0]]
        if samples and isinstance(samples[0], (list, tuple)):
            samples = samples[0]
        clipped = [int(max(-32768, min(32767, round(float(v) * 32767)))) for v in samples]
        pcm = struct.pack(f"<{len(clipped)}h", *clipped)
        sample_rate = int(getattr(getattr(model, "config", None), "sampling_rate", 16000) or 16000)
        import io as _io

        buf = _io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm)
        return buf.getvalue()

    def synthesize(self, text: str, voice: str, language: str) -> bytes:
        if language not in SUPPORTED_VOICE_LANGUAGES:
            raise ValueError(f"Langue vocale non prise en charge : {language!r}.")
        code = MMS_LANGUAGE_MAP.get(language)
        if code is None:
            raise ValueError(f"Pas de code MMS documenté pour : {language!r}.")
        cache_path = self._cache_path(code, text)
        if os.path.isfile(cache_path):
            with open(cache_path, "rb") as f:
                cached = f.read()
            if cached:
                return cached
        audio = self._synthesize_uncached(text, code)
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(audio)
        except OSError:
            pass  # cache best-effort : l'audio reste renvoyé.
        return audio


TTS_REGISTRY: dict[str, type[BaseTTSProvider]] = {
    "piper": PiperTTSProvider,
    "mms": MMSTTSProvider,
    "meta": MMSTTSProvider,
}


def _mapping_from_headers(headers: Any) -> dict[str, Any]:
    get = headers.get
    return {
        "driver": get("x-tts-driver") or os.getenv("TTS_DRIVER", "piper"),
        "model": get("x-tts-model") or None,
        "model_dir": get("x-tts-model-dir") or None,
        "cache_dir": get("x-tts-cache-dir") or None,
    }


def tts_from_headers(headers: Any) -> BaseTTSProvider:
    mapping = _mapping_from_headers(headers)
    driver = (mapping.get("driver") or "piper").lower()
    provider_cls = TTS_REGISTRY.get(driver, PiperTTSProvider)
    return provider_cls.from_mapping(mapping)


def tts_from_profile(profile: dict[str, Any]) -> BaseTTSProvider:
    driver = (profile.get("driver") or "piper").lower()
    provider_cls = TTS_REGISTRY.get(driver, PiperTTSProvider)
    return provider_cls.from_mapping(profile)


def default_tts() -> BaseTTSProvider:
    return tts_from_headers({})


TTS_PROVIDER_TYPES: list[dict[str, Any]] = [
    {
        "id": "piper",
        "label": "Piper local (français)",
        "description": "Piper TTS sur CPU : voix française standard, rapide et légère.",
        "api_key_required": False,
        "local_languages": False,
        "fields": [
            {"name": "model", "label": "Modèle Piper (.onnx)", "type": "text", "default": "/models/piper/fr_FR-upmc-medium.onnx", "required": True},
        ],
    },
    {
        "id": "mms",
        "label": "Meta MMS (langues locales)",
        "description": "Meta MMS-TTS (VITS monolingue) : anglais (eng), douala (dua), bassa (bas), ewondo (ewo). Repli français Piper automatique + notice explicite si indisponible.",
        "api_key_required": False,
        "local_languages": True,
        "fields": [
            {"name": "model_dir", "label": "Dossier modèles MMS", "type": "text", "default": "/models/mms-tts", "required": True},
            {"name": "cache_dir", "label": "Dossier cache audio", "type": "text", "default": "/tmp/wash-mms-tts", "required": False},
        ],
    },
]
