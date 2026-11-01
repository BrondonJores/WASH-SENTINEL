from __future__ import annotations

import base64
import io
import os
import re
import struct
import subprocess
import tempfile
import wave
from .schemas import VoiceSynthesisResponse, VoiceTranscriptionResponse
from .stt_providers import BaseSTTProvider, default_stt


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
STT_NOISY = "STT_NOISY"
STT_INAUDIBLE = "STT_INAUDIBLE"
STT_UNAVAILABLE = "STT_UNAVAILABLE"
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
#: Énergie RMS normalisée sous laquelle un WAV est considéré comme du silence.
SILENCE_RMS_THRESHOLD = 0.02
#: Énergie RMS normalisée au-delà de laquelle un son incompris est
#: probablement masqué par du bruit (il y a du son, mais rien d'intelligible).
NOISE_RMS_THRESHOLD = 0.15


def guided_error(code: str) -> RuntimeError:
    """Construit l'erreur guidée FR pour un code stable."""
    return RuntimeError(f"[{code}] {GUIDANCE[code]}")


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
            max_frames = min(n_frames, 16000 * 5)
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
        stats = _wav_stats(audio_bytes)
        duration: float | None = None
        if stats is not None:
            duration, rms = stats
            if duration < MIN_AUDIO_SECONDS:
                raise guided_error(STT_TOO_SHORT)
            if rms < SILENCE_RMS_THRESHOLD:
                raise guided_error(STT_SILENCE)
        else:
            rms = -1.0  # énergie inconnue (format compressé) : on laisse passer.

        provider = stt or self._default_stt or default_stt()
        try:
            result = provider.transcribe(audio_bytes, filename, language)
        except Exception:
            # Panne moteur (modèle/binaire absent, FFmpeg, réseau cloud...) :
            # message guidé, sans détail technique.
            raise guided_error(STT_UNAVAILABLE) from None
        transcript = (result.get("transcript", "") or "").strip()
        if not transcript:
            # Rien d'intelligible : le niveau sonore dit pourquoi.
            if rms >= 0 and rms < SILENCE_RMS_THRESHOLD:
                raise guided_error(STT_SILENCE)
            if rms >= NOISE_RMS_THRESHOLD:
                raise guided_error(STT_NOISY)
            raise guided_error(STT_INAUDIBLE)
        return VoiceTranscriptionResponse(
            transcript=transcript,
            language=result.get("language", language),
            duration_seconds=duration,
        )

    def _resolve_voice_model(self, voice: str) -> str:
        """Voix demandée -> fichier .onnx du même dossier (nom strict, anti path-traversal)."""
        if voice and re.fullmatch(r"[A-Za-z0-9_.-]+", voice):
            candidate = os.path.join(os.path.dirname(self.piper_model), f"{voice}.onnx")
            if os.path.isfile(candidate):
                return candidate
        return self.piper_model

    def synthesize(self, text: str, voice: str = "fr_FR-upmc-medium") -> VoiceSynthesisResponse:
        """Synthétise un texte en audio via Piper TTS pour confirmation vocale.

        Chaque panne lève un RuntimeError guidé en français ([CODE] + conseil).
        Ne JAMAIS renvoyer un faux WAV silencieux.
        """
        if not text or not text.strip():
            raise guided_error(TTS_EMPTY_TEXT)
        if not os.path.isfile(self.piper_bin):
            raise guided_error(TTS_UNAVAILABLE)
        model = self._resolve_voice_model(voice)
        if not os.path.isfile(model):
            raise guided_error(TTS_VOICE_UNAVAILABLE)

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
            process.communicate(input=text)

            audio_data = b""
            if os.path.isfile(out_wav):
                with open(out_wav, "rb") as f:
                    audio_data = f.read()

            if not audio_data:
                raise guided_error(TTS_UNAVAILABLE)

            return VoiceSynthesisResponse(
                audio_base64=base64.b64encode(audio_data).decode("utf-8"),
                mime_type="audio/wav",
                text=text,
            )
