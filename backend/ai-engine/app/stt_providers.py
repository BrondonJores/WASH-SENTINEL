from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from typing import Any

import httpx


#: Langues vocales prises en charge de bout en bout (console -> relais -> moteur).
#: Le Cameroun est bilingue FR/EN : "en" est accepté partout (STT -l en,
#: TTS MMS eng, validation Laravel, schools.default_language='en').
#: "bbj_Latn" (ghomala') : couvert nativement par Meta Omnilingual ASR
#: (driver omnilingual_ctc, cf. app/stt_omnilingual.py).
SUPPORTED_VOICE_LANGUAGES: set[str] = {"fr", "en", "dua_Latn", "bassa", "ewondo", "bbj_Latn"}

#: Code langue réellement envoyé au binaire whisper.cpp (-l). Whisper.cpp ne
#: fournit aucun modèle dua/bassa/ewondo/bbj : "auto" est un choix délibéré et
#: documenté (pas une substitution silencieuse), exposé via language_effective.
#: Pour bbj_Latn (ghomala'), Whisper ne connaît pas la langue : le driver
#: réel est Omnilingual CTC (Meta Omnilingual ASR couvre bbj_Latn nativement).
WHISPER_LANG_MAP: dict[str, str] = {
    "fr": "fr",
    "en": "en",
    "dua_Latn": "auto",
    "bassa": "auto",
    "ewondo": "auto",
    "bbj_Latn": "auto",
}

#: Prompt métier WASH injecté à Whisper (initial_prompt : --prompt côté
#: whisper.cpp, champ "prompt" côté API /audio/transcriptions). Il guide la
#: reconnaissance des noms propres seedés (Bonanjo, Libermann, Bali, Ngok,
#: Nkol, Édéa, Pouuma, Nyo — cf. WashDemoSeeder) et du vocabulaire eau /
#: assainissement FR + EN ("Bonanjo" ne doit plus devenir "bon anjon").
WASH_WHISPER_PROMPT_FR = (
    "Signalement WASH école : École Publique de Bonanjo, Collège Libermann, "
    "École Publique de Bali, École Rurale de Ngok, École de Nkol, "
    "École Publique d'Édéa, École Rurale de Pouuma, École de Nyo. "
    "Robinet, fuite, panne d'eau, forage, pompe, puits, latrines, "
    "toilettes, château d'eau, bloc A, bidons, élèves sans eau."
)
WASH_WHISPER_PROMPT_EN = (
    "WASH school report: Bonanjo Public School, Libermann College, "
    "Bali Public School, Ngok Rural School, Nkol School, Edea Public "
    "School, Pouuma Rural School, Nyo School. Leak, tap, water outage, "
    "borehole, pump, well, latrines, toilets, water tower, block A, "
    "jerrycans, pupils without water."
)


def wash_whisper_prompt(language: str) -> str:
    """Prompt métier WASH adapté à la langue demandée (EN si "en", FR sinon)."""
    if (language or "").strip().lower() == "en":
        return WASH_WHISPER_PROMPT_EN
    return WASH_WHISPER_PROMPT_FR

#: Valeur renvoyée quand un driver ne peut pas honorer la langue demandée.
LANGUAGE_AUTO_EFFECTIVE = "auto"

#: Log whisper.cpp exploité pour l'auto-détection (best-effort) :
#: "whisper_full: auto-detected language: fr (p = 0.97)". Absent des vieux
#: binaires -> détection None (jamais d'exception, jamais inventé).
_WHISPER_DETECTED_RE = re.compile(
    r"auto[-\s]?detected language:\s*([A-Za-z_]+)"
    r"(?:\s*\(p\s*=\s*([\d.]+))?")


#: Cache du support JSON par binaire (sniffé via --help, jamais supposé).
_WHISPER_JSON_FLAGS: dict[str, list[str]] = {}


def whisper_json_flags(binary: str, timeout: float = 15.0) -> list[str]:
    """Flags JSON du binaire whisper.cpp (sniffés, cache par chemin).

    Les vieux binaires ne connaissent ni -oj ni -ojson : on n'ajoute le
    flag que s'il apparaît dans --help (sinon la transcription casserait).
    """
    if binary in _WHISPER_JSON_FLAGS:
        return _WHISPER_JSON_FLAGS[binary]
    flags: list[str] = []
    try:
        res = subprocess.run(
            [binary, "--help"], capture_output=True, text=True,
            check=False, timeout=timeout)
        help_text = f"{res.stdout}\n{res.stderr}"
        if "-ojson" in help_text or "output-json" in help_text:
            flags = ["-ojson"]
        elif re.search(r"(?<!o)-oj\b", help_text):
            flags = ["-oj"]
    except Exception:
        flags = []
    _WHISPER_JSON_FLAGS[binary] = flags
    return flags


def parse_whisper_confidence(payload: Any) -> float | None:
    """Confiance 0..1 depuis le JSON whisper.cpp (pur, best-effort).

    Formes tolérées : {"result": {"transcription": [...]}} ou
    {"transcription": [...]} ou {"segments": [...]}, probas "no_speech_prob"
    (confiance = 1 - moyenne) ou "avg_logprob" (confiance = exp, bornée).
    None si inexploitable (vieux binaire, JSON absent).
    """
    import math
    segments: Any = None
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            segments = result.get("transcription", result.get("segments"))
        segments = segments if segments is not None else payload.get(
            "transcription", payload.get("segments"))
    if not isinstance(segments, list) or not segments:
        return None
    no_speech: list[float] = []
    logprobs: list[float] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            if seg.get("no_speech_prob") is not None:
                no_speech.append(float(seg["no_speech_prob"]))
        except (TypeError, ValueError):
            pass
        try:
            if seg.get("avg_logprob") is not None:
                logprobs.append(float(seg["avg_logprob"]))
        except (TypeError, ValueError):
            pass
    if no_speech:
        return min(1.0, max(0.0, 1.0 - sum(no_speech) / len(no_speech)))
    if logprobs:
        mean_lp = sum(logprobs) / len(logprobs)
        try:
            return min(1.0, max(0.0, math.exp(mean_lp)))
        except (OverflowError, ValueError):
            return None
    return None


def parse_whisper_detection(stdout: str, stderr: str) -> tuple[str | None, float | None]:
    """Langue + proba auto-détectées depuis les logs whisper.cpp (pur)."""
    match = _WHISPER_DETECTED_RE.search(f"{stdout or ''}\n{stderr or ''}")
    if match is None:
        return None, None
    prob: float | None = None
    if match.group(2):
        try:
            prob = float(match.group(2))
        except ValueError:
            prob = None
    return match.group(1).strip().lower(), prob

#: Plafond anti-DoS des notes vocales, en Mo.
#: LA RÉFÉRENCE documentée (LOT 5) : voice_service.MAX_VOICE_AUDIO_BYTES en
#: dérive, et les lots Laravel suivants s'aligneront sur ces 12 Mo.
STT_MAX_INPUT_MB = 12
#: Garde-fou avant écriture disque : refuse les blobs démesurés sans lancer FFmpeg.
MAX_STT_INPUT_BYTES = STT_MAX_INPUT_MB * 1024 * 1024

#: Délai maximal de la normalisation FFmpeg (secondes).
FFMPEG_NORMALIZE_TIMEOUT_SECONDS = 30.0
#: Format pivot imposé à tous les moteurs STT : WAV PCM 16 kHz mono 16 bits.
STT_SAMPLE_RATE_HZ = 16000
STT_CHANNELS = 1
STT_SAMPLE_WIDTH_BYTES = 2


def normalize_to_wav(
    audio_bytes: bytes,
    filename: str,
    workdir: str,
    timeout: float = FFMPEG_NORMALIZE_TIMEOUT_SECONDS,
) -> str:
    """Normalise n'importe quel audio en WAV PCM 16kHz mono via FFmpeg."""
    if len(audio_bytes) > MAX_STT_INPUT_BYTES:
        raise RuntimeError(
            f"Audio trop volumineux pour la normalisation (limite {STT_MAX_INPUT_MB} Mo).")
    input_file = os.path.join(workdir, filename)
    with open(input_file, "wb") as f:
        f.write(audio_bytes)
    wav_file = os.path.join(workdir, "normalized.wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_file, "-ar", str(STT_SAMPLE_RATE_HZ),
             "-ac", str(STT_CHANNELS), "-c:a", "pcm_s16le", wav_file],
            capture_output=True, check=False, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Normalisation audio trop lente (délai FFmpeg dépassé).") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"FFmpeg introuvable (normalisation {STT_SAMPLE_RATE_HZ // 1000}kHz impossible).") from exc
    if not os.path.isfile(wav_file):
        raise RuntimeError(
            f"FFmpeg introuvable ou audio illisible (normalisation {STT_SAMPLE_RATE_HZ // 1000}kHz impossible).")
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

    def __init__(
        self,
        binary: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        prompt: str | None = None,
    ):
        self.binary = binary or os.getenv("VOICE_STT_BINARY", "/opt/voice/bin/whisper-cli")
        self.model = model or os.getenv("VOICE_STT_MODEL", "/models/whisper/ggml-base.bin")
        self.timeout = timeout
        # Prompt initial métier : mapping > env VOICE_STT_PROMPT > défaut WASH
        # (FR/EN selon langue). Vide = prompt métier auto (jamais désactivé
        # par accident depuis un champ console laissé vide).
        self.prompt = prompt or os.getenv("VOICE_STT_PROMPT") or None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "WhisperCppProvider":
        return cls(
            binary=mapping.get("binary") or None,
            model=mapping.get("model") or None,
            timeout=float(mapping.get("timeout") or 120.0),
            prompt=mapping.get("prompt") or None,
        )

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict[str, Any]:
        if not os.path.isfile(self.binary) or not os.path.isfile(self.model):
            raise RuntimeError(f"Whisper indisponible (binaire ou modèle introuvable : {self.model}).")
        effective = WHISPER_LANG_MAP.get(language, LANGUAGE_AUTO_EFFECTIVE)
        prompt_text = self.prompt if self.prompt is not None else wash_whisper_prompt(language)
        with tempfile.TemporaryDirectory(prefix="wash-stt-") as tmpdir:
            wav_file = normalize_to_wav(audio_bytes, filename, tmpdir)
            out_base = os.path.join(tmpdir, "output")
            argv = [self.binary, "-m", self.model, "-f", wav_file,
                   "-l", effective,
                   "-otxt", "-of", out_base]
            argv += whisper_json_flags(self.binary, self.timeout)
            if prompt_text:
                # whisper.cpp : -p / --prompt = initial_prompt (noms propres WASH).
                argv += ["--prompt", prompt_text]
            res = subprocess.run(
                argv,
                capture_output=True, text=True, check=False, timeout=self.timeout,
            )
            transcript = ""
            txt_file = out_base + ".txt"
            if os.path.isfile(txt_file):
                with open(txt_file, encoding="utf-8") as tf:
                    transcript = tf.read().strip()
            confidence: float | None = None
            json_file = out_base + ".json"
            if os.path.isfile(json_file):
                try:
                    with open(json_file, encoding="utf-8") as jf:
                        confidence = parse_whisper_confidence(json.load(jf))
                except (OSError, ValueError):
                    confidence = None
            return {
                "transcript": transcript or res.stdout.strip(),
                "language": language,
                "language_effective": effective,
                "confidence": confidence,
            }

    def transcribe_auto(self, audio_bytes: bytes, filename: str) -> dict[str, Any]:
        """Passe de détection : langue auto native (-l omis), SANS prompt.

        Sans prompt métier pour rester neutre (un prompt FR biaiserait la
        détection vers le français). Retourne transcript + detected_language
        + detection_prob (None si le binaire ne les expose pas).
        """
        if not os.path.isfile(self.binary) or not os.path.isfile(self.model):
            raise RuntimeError(f"Whisper indisponible (binaire ou modèle introuvable : {self.model}).")
        with tempfile.TemporaryDirectory(prefix="wash-stt-detect-") as tmpdir:
            wav_file = normalize_to_wav(audio_bytes, filename, tmpdir)
            out_base = os.path.join(tmpdir, "output")
            res = subprocess.run(
                [self.binary, "-m", self.model, "-f", wav_file,
                 "-otxt", "-of", out_base],
                capture_output=True, text=True, check=False, timeout=self.timeout,
            )
            transcript = ""
            txt_file = out_base + ".txt"
            if os.path.isfile(txt_file):
                with open(txt_file, encoding="utf-8") as tf:
                    transcript = tf.read().strip()
            detected, prob = parse_whisper_detection(res.stdout, res.stderr)
            return {
                "transcript": transcript or res.stdout.strip(),
                "detected_language": detected,
                "detection_prob": prob,
                "language_effective": LANGUAGE_AUTO_EFFECTIVE,
            }


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

        # Le modèle CTC est agnostique à la langue, mais un code inconnu est
        # un typo : échouer bruyamment plutôt que transcrire en langue mystère.
        if language not in SUPPORTED_VOICE_LANGUAGES:
            raise ValueError(f"Langue vocale non prise en charge : {language!r}.")
        recognizer = self._load()
        with tempfile.TemporaryDirectory(prefix="wash-omni-") as tmpdir:
            wav_file = normalize_to_wav(audio_bytes, filename, tmpdir)
            with wave.open(wav_file, "rb") as w:
                if (w.getnchannels() != STT_CHANNELS
                        or w.getsampwidth() != STT_SAMPLE_WIDTH_BYTES
                        or w.getframerate() != STT_SAMPLE_RATE_HZ):
                    raise RuntimeError(
                        f"Format WAV inattendu après normalisation "
                        f"({STT_SAMPLE_RATE_HZ // 1000}kHz mono requis).")
                samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        stream = recognizer.create_stream()
        stream.accept_waveform(STT_SAMPLE_RATE_HZ, samples)
        recognizer.decode_stream(stream)
        return {
            "transcript": (stream.result.text or "").strip(),
            "language": language,
            "language_effective": language,
        }


class CloudWhisperProvider(BaseSTTProvider):
    """Transcription cloud via API compatible OpenAI /audio/transcriptions (OpenAI, Groq...)."""

    driver_name = "cloud_whisper"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        prompt: str | None = None,
    ):
        self.base_url = (base_url or os.getenv("CLOUD_STT_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("CLOUD_STT_MODEL", "whisper-1")
        self.api_key = api_key or os.getenv("CLOUD_STT_API_KEY")
        self.timeout = timeout
        # Prompt initial métier : mapping > env VOICE_STT_PROMPT > défaut WASH
        # (FR/EN selon langue). Vide = prompt métier auto (jamais désactivé
        # par accident depuis un champ console laissé vide).
        self.prompt = prompt or os.getenv("VOICE_STT_PROMPT") or None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "CloudWhisperProvider":
        return cls(
            base_url=mapping.get("base_url") or None,
            model=mapping.get("model") or None,
            api_key=mapping.get("api_key") or None,
            timeout=float(mapping.get("timeout") or 120.0),
            prompt=mapping.get("prompt") or None,
        )

    def transcribe(self, audio_bytes: bytes, filename: str, language: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data: dict[str, str] = {"model": self.model, "response_format": "json"}
        # L'API cloud n'accepte que des ISO-639-1 : pour dua_Latn/bassa/ewondo
        # on omet le champ (défaut provider) et on l'expose honnêtement.
        if re.fullmatch(r"[a-z]{2}", language or ""):
            data["language"] = language
            effective = language
        else:
            effective = LANGUAGE_AUTO_EFFECTIVE
        prompt_text = self.prompt if self.prompt is not None else wash_whisper_prompt(language)
        if prompt_text:
            # API /audio/transcriptions : champ "prompt" = initial_prompt.
            data["prompt"] = prompt_text
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/audio/transcriptions",
                headers=headers,
                files={"file": (filename, audio_bytes, "audio/wav")},
                data=data,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                payload = {}
            result: dict[str, Any] = {
                # OpenAI renvoie "text" ; des endpoints compatibles
                # (Meta...) peuvent renvoyer "transcript" : on tolère.
                "transcript": payload.get("text") or payload.get("transcript") or "",
                "language": language,
                "language_effective": effective,
            }
            # Langue détectée renvoyée par l'endpoint (verbose_json
            # "language", variantes) : propagée honnêtement, jamais
            # inventée (absente = clé absente).
            detected = (
                payload.get("language")
                or payload.get("detected_language")
                or payload.get("language_detected")
            )
            if isinstance(detected, str) and detected.strip():
                result["detected_language"] = detected.strip()
            return result


STT_REGISTRY: dict[str, type[BaseSTTProvider]] = {
    "whisper_cpp": WhisperCppProvider,
    "whisper": WhisperCppProvider,
    "omnilingual_onnx": OmnilingualOnnxProvider,
    "omnilingual": OmnilingualOnnxProvider,
    "cloud_whisper": CloudWhisperProvider,
    "cloud": CloudWhisperProvider,
    # Meta Muse Transcribe : même contrat OpenAI-compatible
    # (/audio/transcriptions), défauts Meta (cf. STT_PROVIDER_TYPES).
    "meta_transcribe": CloudWhisperProvider,
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
        "prompt": get("x-stt-prompt") or None,
    }


def _ensure_ctc_registered() -> bool:
    """Enregistre OmnilingualCTCProvider (bbj_Latn) dans STT_REGISTRY.

    Import paresseux : app/stt_omnilingual.py importe ce module, un import
    direct au sommet bouclerait. Retourne True si le driver est joignable.
    """
    if "omnilingual_ctc" in STT_REGISTRY:
        return True
    provider_cls: type[BaseSTTProvider] | None = None
    try:
        from app.stt_omnilingual import OmnilingualCTCProvider as provider_cls
    except ImportError:
        try:
            from .stt_omnilingual import OmnilingualCTCProvider as provider_cls
        except ImportError:
            return False
    if provider_cls is None:
        return False
    STT_REGISTRY["omnilingual_ctc"] = provider_cls
    return True


def _ctc_from_mapping(mapping: dict[str, Any]) -> BaseSTTProvider:
    """Instancie le driver omnilingual_ctc, ou erreur explicite.

    Jamais de repli silencieux vers Whisper : un driver explicitement
    demandé mais injoignable est une panne franche, pas un "auto".
    """
    if not _ensure_ctc_registered():
        raise RuntimeError(
            "Driver omnilingual_ctc indisponible "
            "(module app/stt_omnilingual.py introuvable)."
        )
    return STT_REGISTRY["omnilingual_ctc"].from_mapping(mapping)


def stt_from_headers(headers: Any) -> BaseSTTProvider:
    mapping = _mapping_from_headers(headers)
    driver = (mapping.get("driver") or "whisper_cpp").lower()
    if driver == "omnilingual_ctc":
        return _ctc_from_mapping(mapping)
    provider_cls = STT_REGISTRY.get(driver, WhisperCppProvider)
    return provider_cls.from_mapping(mapping)


def stt_from_profile(profile: dict[str, Any]) -> BaseSTTProvider:
    driver = (profile.get("driver") or "whisper_cpp").lower()
    if driver == "omnilingual_ctc":
        return _ctc_from_mapping(profile)
    provider_cls = STT_REGISTRY.get(driver, WhisperCppProvider)
    return provider_cls.from_mapping(profile)


def default_stt() -> BaseSTTProvider:
    return stt_from_headers({})


STT_PROVIDER_TYPES: list[dict[str, Any]] = [
    {
        "id": "whisper_cpp",
        "label": "Whisper local (français, anglais)",
        "description": "Whisper.cpp sur CPU : rapide et léger, idéal pour le français et l'anglais (prompt métier WASH : noms d'écoles + vocabulaire eau/assainissement).",
        "api_key_required": False,
        "local_languages": False,
        "fields": [
            {"name": "model", "label": "Modèle Whisper (.bin)", "type": "text", "default": "/models/whisper/ggml-base.bin", "required": True},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "120", "required": False},
            {"name": "prompt", "label": "Prompt initial Whisper (vide = prompt métier WASH auto FR/EN)", "type": "text", "default": "", "required": False},
        ],
    },
    {
        "id": "omnilingual_onnx",
        "label": "Omnilingual Meta (langues locales)",
        "description": "Meta Omnilingual ASR en ONNX int8 : 1600+ langues dont douala (dua_Latn), bassa, ewondo. CPU OK.",
        "api_key_required": False,
        "local_languages": True,
        "fields": [
            {"name": "model", "label": "Modèle ONNX (.onnx)", "type": "text", "default": "/models/omnilingual/model.int8.onnx", "required": True},
            {"name": "tokens", "label": "Fichier tokens (tokens.txt)", "type": "text", "default": "/models/omnilingual/tokens.txt", "required": True},
            {"name": "threads", "label": "Threads CPU", "type": "number", "default": "2", "required": False},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "180", "required": False},
        ],
    },
    {
        "id": "omnilingual_ctc",
        "label": "Omnilingual CTC (ghomala', 1600+ langues)",
        "description": "Meta Omnilingual ASR CTC : ghomala' (bbj_Latn) natif, 1600+ langues, 100 % CPU. ONNX int8 via sherpa-onnx si installé, sinon checkpoint transformers.",
        "api_key_required": False,
        "local_languages": True,
        "fields": [
            {"name": "model", "label": "Modèle ONNX (.onnx)", "type": "text", "default": "/models/omnilingual/model.int8.onnx", "required": True},
            {"name": "tokens", "label": "Fichier tokens (tokens.txt)", "type": "text", "default": "/models/omnilingual/tokens.txt", "required": True},
            {"name": "hf_model", "label": "Checkpoint HF (repli transformers)", "type": "text", "default": "facebook/omniASR-CTC-300M", "required": False},
            {"name": "backend", "label": "Backend (auto/sherpa/transformers)", "type": "text", "default": "auto", "required": False},
            {"name": "threads", "label": "Threads CPU", "type": "number", "default": "2", "required": False},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "180", "required": False},
        ],
    },
    {
        "id": "cloud_whisper",
        "label": "API cloud (OpenAI / Groq)",
        "description": "Endpoint /audio/transcriptions compatible OpenAI. Nécessite une clé API.",
        "api_key_required": True,
        "local_languages": False,
        "fields": [
            {"name": "base_url", "label": "URL de base (/v1)", "type": "url", "default": "https://api.openai.com/v1", "required": True},
            {"name": "model", "label": "Modèle (ex: whisper-1)", "type": "text", "default": "whisper-1", "required": True},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "120", "required": False},
            {"name": "prompt", "label": "Prompt initial Whisper (vide = prompt métier WASH auto FR/EN)", "type": "text", "default": "", "required": False},
        ],
    },
    {
        "id": "meta_transcribe",
        "label": "Meta Muse Transcribe (cloud)",
        "description": "Transcription cloud Meta (endpoint OpenAI-compatible) : modèle muse-voice-transcribe-1.0. Collez votre clé api.meta.ai. Couverture langues locales selon Meta, non vérifiée — testez depuis Réglages avec un vrai vocal.",
        "api_key_required": True,
        "local_languages": False,
        "fields": [
            {"name": "base_url", "label": "URL de base (/v1)", "type": "url", "default": "https://api.meta.ai/v1", "required": True},
            {"name": "model", "label": "Modèle", "type": "text", "default": "muse-voice-transcribe-1.0", "required": True},
            {"name": "timeout", "label": "Timeout (s)", "type": "number", "default": "120", "required": False},
            {"name": "prompt", "label": "Prompt initial (vide = prompt métier WASH auto FR/EN)", "type": "text", "default": "", "required": False},
        ],
    },
]


# Enregistrement eager du driver CTC (bbj_Latn) : best-effort. En cas
# d'import circulaire partiel (stt_omnilingual importe ce module), le lazy
# _ensure_ctc_registered() des fabriques prend le relais au premier usage.
try:
    from app.stt_omnilingual import OmnilingualCTCProvider as _OmnilingualCTC

    STT_REGISTRY.setdefault("omnilingual_ctc", _OmnilingualCTC)
except ImportError:
    try:
        from .stt_omnilingual import OmnilingualCTCProvider as _OmnilingualCTC

        STT_REGISTRY.setdefault("omnilingual_ctc", _OmnilingualCTC)
    except ImportError:
        pass
