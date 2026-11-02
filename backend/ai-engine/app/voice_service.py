from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import wave
from typing import Any
from .schemas import VoiceSynthesisResponse, VoiceTranscriptionResponse
from .stt_providers import (
    LANGUAGE_AUTO_EFFECTIVE,
    MAX_STT_INPUT_BYTES,
    STT_SAMPLE_RATE_HZ,
    SUPPORTED_VOICE_LANGUAGES,
    WHISPER_LANG_MAP,
    BaseSTTProvider,
    OmnilingualOnnxProvider,
    WhisperCppProvider,
    default_stt,
)
from .voice_detect import arbitrate
from .tts_providers import (
    MMS_LANGUAGE_MAP,
    MMS_MISSING_PRETRAINED,
    BaseTTSProvider,
)


# ============================================================================
# Guidage vocal : chaque panne est expliquée en français simple, avec un
# conseil concret pour réessayer. Jamais de message technique brut, jamais
# le mot « échec » : l'utilisateur doit toujours savoir quoi faire ensuite.
#
# Codes stables (préfixés [CODE] dans le message) pour un traitement
# programmatique côté relais Laravel / frontend.
# ============================================================================

STT_SILENCE = "STT_SILENCE"
STT_TOO_SHORT = "STT_TOO_SHORT"
STT_TOO_LONG = "STT_TOO_LONG"
STT_NOISY = "STT_NOISY"
STT_INAUDIBLE = "STT_INAUDIBLE"
STT_UNAVAILABLE = "STT_UNAVAILABLE"
STT_LANGUAGE = "STT_LANGUAGE"
TTS_EMPTY_TEXT = "TTS_EMPTY_TEXT"
TTS_VOICE_UNAVAILABLE = "TTS_VOICE_UNAVAILABLE"
TTS_UNAVAILABLE = "TTS_UNAVAILABLE"

GUIDANCE: dict[str, str] = {
    STT_SILENCE: (
        "On n'a rien entendu. Parlez plus près du micro, dans un endroit "
        "calme, puis réessayez."
    ),
    STT_TOO_SHORT: (
        "Enregistrement trop court : on n'a pas eu le temps d'entendre. "
        "Dictez une phrase complète, puis réessayez."
    ),
    STT_TOO_LONG: (
        "Enregistrement trop long : on ne peut pas tout écouter d'un coup. "
        "Dictez par phrases courtes, puis réessayez."
    ),
    STT_NOISY: (
        "Trop de bruit autour : on n'a pas pu isoler votre voix. "
        "Éloignez-vous du bruit ou rapprochez le micro, puis réessayez."
    ),
    STT_INAUDIBLE: (
        "On n'a pas bien compris. Parlez plus près du micro, lentement et "
        "distinctement, puis réessayez."
    ),
    STT_UNAVAILABLE: (
        "La transcription est momentanément indisponible. Réessayez dans un "
        "instant, ou écrivez votre message à la place."
    ),
    STT_LANGUAGE: (
        "Cette langue n'est pas encore prise en charge. Voix disponibles : "
        "français, anglais, douala, bassa, ewondo — choisissez-en une, "
        "puis réessayez."
    ),
    TTS_EMPTY_TEXT: (
        "Rien à lire pour l'instant. Écrivez ou dictez un message, puis "
        "réessayez."
    ),
    TTS_VOICE_UNAVAILABLE: (
        "Cette voix est indisponible pour le moment. Réessayez dans un "
        "instant, ou avec la voix standard."
    ),
    TTS_UNAVAILABLE: (
        "La lecture vocale est momentanément indisponible. Réessayez dans "
        "un instant."
    ),
}

#: Durée minimale exploitable d'un enregistrement (secondes).
MIN_AUDIO_SECONDS = 0.5
#: Durée maximale acceptée avant guidage (secondes) : dicter par phrases courtes.
MAX_AUDIO_SECONDS = 300.0
#: Énergie RMS normalisée sous laquelle un WAV est considéré comme du silence.
SILENCE_RMS_THRESHOLD = 0.02
#: Énergie RMS normalisée au-delà de laquelle un son incompris est
#: probablement masqué par du bruit (il y a du son, mais rien d'intelligible).
NOISE_RMS_THRESHOLD = 0.15
#: Proba minimale d'auto-détection Whisper pour voler la vedette au moteur
#: local quand une langue locale est demandée (mélange FR/EN au micro).
STT_DETECT_MIN_PROB = 0.60

#: Alias courants vers les codes canoniques (console, profils admin, saisies libres).
VOICE_LANGUAGE_ALIASES: dict[str, str] = {
    "dua": "dua_Latn",
    "douala": "dua_Latn",
    "duala": "dua_Latn",
    "basaa": "bassa",
    "francais": "fr",
    "français": "fr",
    "anglais": "en",
    "english": "en",
}

#: Libellés FR des langues pour le message de repli MMS explicite.
#: Noms de langue canoniques (LOT 5 : "anglais", plus "anglaise") ; l'accord
#: féminin après « voix » est géré dans mms_fallback_notice (« voix anglaise »).
VOICE_LANGUAGE_LABELS: dict[str, str] = {
    "fr": "français",
    "en": "anglais",
    "dua_Latn": "douala",
    "bassa": "bassa",
    "ewondo": "ewondo",
}

#: Voix TTS par défaut (français).
DEFAULT_TTS_VOICE = "fr_FR-upmc-medium"

#: Longueur maximale synthétisée (miroir de la validation Laravel max:1000).
MAX_TTS_CHARS = 1000

#: Plafond anti-DoS des notes vocales (octets), durci au-delà du max Laravel
#: web 10 Mo pour couvrir l'exposition directe du moteur. Dérive de LA
#: référence 12 Mo (stt_providers.MAX_STT_INPUT_BYTES, LOT 5) : une seule
#: valeur, les lots Laravel suivants s'aligneront sur ces 12 Mo.
MAX_VOICE_AUDIO_BYTES = MAX_STT_INPUT_BYTES
#: Taille des chunks de lecture transcribe : mesurer AVANT de tout charger.
VOICE_AUDIO_CHUNK_BYTES = 1024 * 1024


def voice_too_heavy_message(size_bytes: int) -> str:
    """Message FR 413 quand la note vocale dépasse MAX_VOICE_AUDIO_BYTES."""
    size_mb = size_bytes / (1024 * 1024)
    max_mb = MAX_VOICE_AUDIO_BYTES // (1024 * 1024)
    return (
        f"Note vocale trop lourde ({size_mb:.1f} Mo, max {max_mb} Mo) : "
        "dictez par phrases courtes, puis réessayez."
    )

#: Délai maximal d'une synthèse Piper (secondes).
TTS_SYNTHESIS_TIMEOUT = 60.0

#: Voix TTS par langue, en l'absence de VOICE_REGISTRY_JSON. Les voix locales
#: n'existent pas encore sur disque : elles échouent bruyamment
#: (TTS_VOICE_UNAVAILABLE), jamais en français silencieux.
BUILTIN_VOICE_REGISTRY: dict[str, list[str]] = {
    "fr": [DEFAULT_TTS_VOICE],
    # EN : voix MMS "eng" via driver mms ; en Piper seul, échec bruyant
    # (jamais de français déguisé en anglais).
    "en": ["en-medium"],
    "dua_Latn": ["dua_Latn-medium"],
    "bassa": ["bassa-medium"],
    "ewondo": ["ewondo-medium"],
}


def _local_whisper_provider() -> WhisperCppProvider | None:
    """Whisper local dispo (binaire + modèle présents) ou None (patchable tests)."""
    probe = WhisperCppProvider()
    if os.path.isfile(probe.binary) and os.path.isfile(probe.model):
        return probe
    return None


def _local_omni_provider() -> OmnilingualOnnxProvider | None:
    """Omnilingual local dispo (modèle + tokens présents) ou None (patchable tests)."""
    probe = OmnilingualOnnxProvider()
    if os.path.isfile(probe.model) and os.path.isfile(probe.tokens):
        return probe
    return None


def guided_error(code: str) -> RuntimeError:
    """Construit l'erreur guidée FR pour un code stable."""
    return RuntimeError(f"[{code}] {GUIDANCE[code]}")


def _voix_agreement(label: str) -> str:
    """Accorde le nom de langue après « voix » (féminin) : « voix anglaise ».

    Seuls les adjectifs en -ais s'accordent (anglais/français) ; les noms
    invariables (douala, bassa, ewondo) sont inchangés.
    """
    return label + "e" if label in ("anglais", "français") else label


def mms_fallback_notice(language: str) -> str:
    """Message FR explicite joint à l'audio quand MMS replie vers Piper FR.

    Deux cas honnêtes : pas de checkpoint pré-entraîné connu chez Meta pour
    cette langue (dua/ewo/bas), ou modèle MMS non installé. Jamais de
    français déguisé en langue locale : le repli est toujours annoncé.
    """
    label = _voix_agreement(VOICE_LANGUAGE_LABELS.get(language, language))
    if MMS_LANGUAGE_MAP.get(language) in MMS_MISSING_PRETRAINED:
        return (
            f"Pas encore de voix {label} disponible (Meta MMS ne la propose "
            "pas) : lecture en français standard."
        )
    return (
        f"La voix {label} est indisponible pour le moment (modèle Meta MMS "
        "non installé) : lecture en français standard."
    )


def normalize_voice_language(language: str | None) -> str:
    """Alias courant -> code canonique, ou erreur guidée STT_LANGUAGE."""
    raw = (language or "").strip()
    canonical = VOICE_LANGUAGE_ALIASES.get(raw.lower(), raw)
    if canonical not in SUPPORTED_VOICE_LANGUAGES:
        raise guided_error(STT_LANGUAGE)
    return canonical


def voice_registry() -> dict[str, list[str]]:
    """Registre langue -> voix TTS, surchargeable via VOICE_REGISTRY_JSON."""
    registry: dict[str, list[str]] = {k: list(v) for k, v in BUILTIN_VOICE_REGISTRY.items()}
    raw = os.getenv("VOICE_REGISTRY_JSON", "").strip()
    if raw:
        try:
            override = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            override = None
        if isinstance(override, dict):
            for lang, voices in override.items():
                if isinstance(lang, str) and isinstance(voices, list):
                    names = [v for v in voices if isinstance(v, str) and v]
                    if names:
                        registry[lang] = names
    return registry


#: Délai maximal de la sonde de durée ffprobe (secondes).
FFPROBE_TIMEOUT_SECONDS = 10.0

#: Fenêtre d'estimation de l'énergie RMS (secondes à 16 kHz, bornée même long).
VOICE_RMS_SAMPLE_SECONDS = 5


def _probe_duration(audio_bytes: bytes, filename: str) -> float | None:
    """Durée (s) d'un audio compressé via ffprobe, ou None si indisponible.

    Dégrade gracieusement vers None (laisser-passer historique) quand ffprobe
    est absent, trop lent ou ne comprend pas le blob : jamais d'échec dur ici.
    """
    if shutil.which("ffprobe") is None:
        return None
    suffix = os.path.splitext(filename)[1] or ".webm"
    try:
        with tempfile.NamedTemporaryFile(prefix="wash-probe-", suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            res = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", tmp.name],
                capture_output=True, text=True, check=False, timeout=FFPROBE_TIMEOUT_SECONDS,
            )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return float((res.stdout or "").strip())
    except ValueError:
        return None


def _wav_stats(audio_bytes: bytes) -> tuple[float, float] | None:
    """Durée (s) et énergie RMS normalisée d'un WAV PCM, ou None si illisible.

    Les formats compressés (webm/opus envoyés par le navigateur) ne sont pas
    analysés ici : ils passent au provider, qui les normalise via FFmpeg.
    """
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as w:
            n_frames = w.getnframes()
            framerate = w.getframerate() or 1
            sampwidth = w.getsampwidth()
            if n_frames <= 0 or sampwidth not in (1, 2):
                return None
            # Échantillon borné : assez pour estimer l'énergie, même long.
            max_frames = min(n_frames, STT_SAMPLE_RATE_HZ * VOICE_RMS_SAMPLE_SECONDS)
            raw = w.readframes(max_frames)
    except (wave.Error, EOFError, OSError):
        return None
    if not raw:
        return 0.0, 0.0
    if sampwidth == 2:
        count = len(raw) // 2
        samples = struct.unpack(f"<{count}h", raw[: count * 2])
        norm = 32768.0
        values = [s / norm for s in samples]
    else:  # PCM 8 bits non signé, centré sur 128.
        values = [(b - 128) / 128.0 for b in raw]
    energy = sum(v * v for v in values) / max(1, len(values))
    return n_frames / framerate, energy**0.5


class VoiceService:
    def __init__(self, stt: BaseSTTProvider | None = None):
        self._default_stt = stt
        self.piper_bin = os.getenv("VOICE_TTS_BINARY", "/opt/voice/bin/piper")
        self.piper_model = os.getenv("VOICE_TTS_MODEL", "/models/piper/fr_FR-upmc-medium.onnx")

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "report.wav",
        language: str = "fr",
        stt: BaseSTTProvider | None = None,
    ) -> VoiceTranscriptionResponse:
        """Transcrit un audio via le provider STT actif (Whisper, Omnilingual ou cloud).

        Chaque panne lève un RuntimeError guidé en français ([CODE] + conseil),
        jamais un message technique. Ne JAMAIS fabriquer de transcription de
        repli (elle alimenterait le triage et la création d'incidents avec un
        faux signalement).
        """
        language = normalize_voice_language(language)
        stats = _wav_stats(audio_bytes)
        duration: float | None = None
        if stats is not None:
            duration, rms = stats
            if duration < MIN_AUDIO_SECONDS:
                raise guided_error(STT_TOO_SHORT)
            if duration > MAX_AUDIO_SECONDS:
                raise guided_error(STT_TOO_LONG)
            if rms < SILENCE_RMS_THRESHOLD:
                raise guided_error(STT_SILENCE)
        else:
            rms = -1.0  # énergie inconnue (format compressé) : durée sondée si possible.
            probed = _probe_duration(audio_bytes, filename)
            if probed is not None:
                duration = probed
                if probed < MIN_AUDIO_SECONDS:
                    raise guided_error(STT_TOO_SHORT)
                if probed > MAX_AUDIO_SECONDS:
                    raise guided_error(STT_TOO_LONG)

        provider = stt or self._default_stt or default_stt()
        if WHISPER_LANG_MAP.get(language) != LANGUAGE_AUTO_EFFECTIVE:
            # Voie directe (comportement historique, coût unique) : la langue
            # demandée est native Whisper.
            try:
                result = provider.transcribe(audio_bytes, filename, language)
            except Exception:
                # Panne moteur (modèle/binaire absent, FFmpeg, réseau
                # cloud...) : message guidé, sans détail technique.
                raise guided_error(STT_UNAVAILABLE) from None
            transcript = (result.get("transcript", "") or "").strip()
            detected: str | None = language
            driver = provider.driver_name
            effective = result.get("language_effective") or language
            detail: dict[str, Any] = {"mode": "direct"}
        else:
            # Langue locale demandée : cascade auto-détection (Whisper-auto
            # + moteur local, arbitrage pur). Le mélange FR/EN au micro est
            # détecté au lieu d'être transcrit en charabia.
            transcript, detected, driver, effective, detail = self._transcribe_local(
                audio_bytes, filename, language, provider)
        if not transcript:
            # Rien d'intelligible : le niveau sonore dit pourquoi.
            if rms >= 0 and rms < SILENCE_RMS_THRESHOLD:
                raise guided_error(STT_SILENCE)
            if rms >= NOISE_RMS_THRESHOLD:
                raise guided_error(STT_NOISY)
            raise guided_error(STT_INAUDIBLE)
        return VoiceTranscriptionResponse(
            transcript=transcript,
            language=language,
            language_effective=effective,
            language_detected=detected,
            detection=detail,
            driver=driver,
            duration_seconds=duration,
        )

    def _transcribe_local(
        self,
        audio_bytes: bytes,
        filename: str,
        language: str,
        provider: BaseSTTProvider,
    ) -> tuple[str, str | None, str, str, dict[str, Any]]:
        """Cascade langue locale : Whisper-auto + moteur local, arbitrage.

        Retourne (transcript, detected, driver, effective, detail). Moteurs
        indisponibles ignorés silencieusement ; si rien ne répond, repli sur
        le provider actif (comportement historique), sinon STT_UNAVAILABLE.
        """
        whisper_res: dict[str, Any] | None = None
        local_res: dict[str, Any] | None = None
        whisper = _local_whisper_provider()
        omni = (provider if provider.driver_name == "omnilingual_onnx"
                else _local_omni_provider())
        if whisper is not None:
            try:
                whisper_res = whisper.transcribe_auto(audio_bytes, filename)
            except Exception:
                whisper_res = None
        if omni is not None:
            try:
                local_res = omni.transcribe(audio_bytes, filename, language)
                local_res = {**local_res, "driver": omni.driver_name}
            except Exception:
                local_res = None
        decision = arbitrate(
            language, whisper_res, local_res, min_prob=STT_DETECT_MIN_PROB)
        detail = {
            "mode": "cascade",
            "whisper_detected": (whisper_res or {}).get("detected_language"),
            "whisper_prob": (whisper_res or {}).get("detection_prob"),
        }
        if decision is not None:
            detail["reason"] = decision["reason"]
            return (decision["transcript"], decision["language_detected"],
                    decision["driver"], decision["language_detected"], detail)
        # Repli historique : le seul provider actif (ex. cloud), puis panne.
        try:
            result = provider.transcribe(audio_bytes, filename, language)
        except Exception:
            raise guided_error(STT_UNAVAILABLE) from None
        return ((result.get("transcript", "") or "").strip(), language,
                provider.driver_name,
                result.get("language_effective") or language,
                {"mode": "fallback-direct"})

    def _resolve_voice_model(self, voice: str, *, explicit: bool = False) -> str:
        """Voix demandée -> fichier .onnx du même dossier (nom strict, anti path-traversal).

        Voix explicite introuvable (nom ou langue demandés par l'appelant) :
        erreur guidée TTS_VOICE_UNAVAILABLE, jamais de repli français silencieux.
        Le repli vers le modèle par défaut ne vaut que pour l'appel implicite.
        """
        if voice and re.fullmatch(r"[A-Za-z0-9_.-]+", voice):
            candidate = os.path.join(os.path.dirname(self.piper_model), f"{voice}.onnx")
            if os.path.isfile(candidate):
                return candidate
        if explicit:
            raise guided_error(TTS_VOICE_UNAVAILABLE)
        return self.piper_model

    def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_TTS_VOICE,
        language: str = "fr",
        tts: BaseTTSProvider | None = None,
    ) -> VoiceSynthesisResponse:
        """Synthétise un texte en audio pour confirmation vocale.

        Sans provider (défaut) : Piper FR historique, inchangé. Avec un
        provider MMS : langues locales via Meta MMS-TTS, repli Piper FR
        automatique + message explicite si MMS indisponible. Chaque panne
        lève un RuntimeError guidé en français ([CODE] + conseil).
        Ne JAMAIS renvoyer un faux WAV silencieux.
        """
        if tts is not None and tts.driver_name == "mms":
            return self._synthesize_mms(text, voice, language, tts)
        if tts is not None and tts.driver_name != "piper":
            raise guided_error(TTS_VOICE_UNAVAILABLE)
        if tts is not None:
            audio_data = tts.synthesize(text, voice, language)
            try:
                language = normalize_voice_language(language)
            except RuntimeError:
                raise guided_error(TTS_VOICE_UNAVAILABLE) from None
            return VoiceSynthesisResponse(
                audio_base64=base64.b64encode(audio_data).decode("utf-8"),
                mime_type="audio/wav",
                text=text.strip()[:MAX_TTS_CHARS],
                driver="piper",
                language_effective=language,
            )
        try:
            language = normalize_voice_language(language)
        except RuntimeError:
            raise guided_error(TTS_VOICE_UNAVAILABLE) from None
        audio_data = self._synthesize_piper_bytes(text, voice, language)
        return VoiceSynthesisResponse(
            audio_base64=base64.b64encode(audio_data).decode("utf-8"),
            mime_type="audio/wav",
            text=text.strip()[:MAX_TTS_CHARS],
            driver="piper",
            language_effective=language,
        )

    def _synthesize_mms(
        self,
        text: str,
        voice: str,
        language: str,
        provider: BaseTTSProvider,
    ) -> VoiceSynthesisResponse:
        """Voie MMS : anglais (eng) + langues locales via Meta MMS-TTS, FR via Piper.

        MMS indisponible (dépendances, modèle ou synthèse) : repli Piper FR
        automatique + notice FR explicite. Jamais de crash, jamais de silence,
        jamais de français déguisé en langue demandée.
        """
        if not text or not text.strip():
            raise guided_error(TTS_EMPTY_TEXT)
        try:
            language = normalize_voice_language(language)
        except RuntimeError:
            raise guided_error(TTS_VOICE_UNAVAILABLE) from None
        text = text.strip()[:MAX_TTS_CHARS]
        if language == "fr":
            audio_data = self._synthesize_piper_bytes(text, voice, language)
            return VoiceSynthesisResponse(
                audio_base64=base64.b64encode(audio_data).decode("utf-8"),
                mime_type="audio/wav",
                text=text,
                driver="piper",
                language_effective="fr",
            )
        try:
            audio_data = provider.synthesize(text, voice, language)
        except Exception:
            audio_data = self._synthesize_piper_bytes(text, DEFAULT_TTS_VOICE, "fr")
            return VoiceSynthesisResponse(
                audio_base64=base64.b64encode(audio_data).decode("utf-8"),
                mime_type="audio/wav",
                text=text,
                driver="mms",
                language_effective="fr",
                fallback=True,
                notice=mms_fallback_notice(language),
            )
        return VoiceSynthesisResponse(
            audio_base64=base64.b64encode(audio_data).decode("utf-8"),
            mime_type="audio/wav",
            text=text,
            driver="mms",
            language_effective=language,
        )

    def _synthesize_piper_bytes(
        self,
        text: str,
        voice: str,
        language: str,
    ) -> bytes:
        """Invocation Piper historique -> WAV brut.

        Normalise la langue (inconnue -> TTS_VOICE_UNAVAILABLE). Lève les
        erreurs guidées TTS_EMPTY_TEXT / TTS_VOICE_UNAVAILABLE /
        TTS_UNAVAILABLE. Ne JAMAIS renvoyer un faux WAV silencieux.
        """
        if not text or not text.strip():
            raise guided_error(TTS_EMPTY_TEXT)
        try:
            language = normalize_voice_language(language)
        except RuntimeError:
            # Langue inconnue côté TTS : pas de voix à proposer dans cette langue.
            raise guided_error(TTS_VOICE_UNAVAILABLE) from None
        if not os.path.isfile(self.piper_bin):
            raise guided_error(TTS_UNAVAILABLE)
        requested_voice = voice or DEFAULT_TTS_VOICE
        explicit = requested_voice != DEFAULT_TTS_VOICE or language != "fr"
        if requested_voice == DEFAULT_TTS_VOICE and language != "fr":
            # Voix dédiée à la langue (registre) : absente du disque =>
            # erreur bruyante via explicit=True, jamais du français déguisé.
            requested_voice = voice_registry().get(language, [DEFAULT_TTS_VOICE])[0]
        model = self._resolve_voice_model(requested_voice, explicit=explicit)
        if not os.path.isfile(model):
            raise guided_error(TTS_VOICE_UNAVAILABLE)

        text = text.strip()[:MAX_TTS_CHARS]
        with tempfile.TemporaryDirectory(prefix="wash-tts-") as tmpdir:
            out_wav = os.path.join(tmpdir, "speech.wav")
            piper_cmd = [
                self.piper_bin,
                "--model", model,
                "--output_file", out_wav,
            ]

            process = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                process.communicate(input=text, timeout=TTS_SYNTHESIS_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.communicate()
                except Exception:
                    pass
                raise guided_error(TTS_UNAVAILABLE) from None

            audio_data = b""
            if os.path.isfile(out_wav):
                with open(out_wav, "rb") as f:
                    audio_data = f.read()

            if not audio_data:
                raise guided_error(TTS_UNAVAILABLE)

            return audio_data
