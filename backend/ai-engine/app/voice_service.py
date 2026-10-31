from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
from .schemas import VoiceSynthesisResponse, VoiceTranscriptionResponse
from .stt_providers import BaseSTTProvider, default_stt


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

        Lève l'erreur du provider telle quelle : main.py la convertit en HTTP 500
        explicite. Ne JAMAIS fabriquer de transcription de repli (elle alimenterait
        le triage et la création d'incidents avec un faux signalement).
        """
        provider = stt or self._default_stt or default_stt()
        result = provider.transcribe(audio_bytes, filename, language)
        return VoiceTranscriptionResponse(
            transcript=result.get("transcript", ""),
            language=result.get("language", language),
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

        Lève une erreur actionnable si Piper ou la voix est absent (main.py répond
        HTTP 500 explicite, le lecteur vocal l'affiche). Ne JAMAIS renvoyer un
        faux WAV silencieux.
        """
        if not os.path.isfile(self.piper_bin):
            raise RuntimeError(
                f"Piper TTS introuvable ({self.piper_bin}) : ajoutez piper-tts aux dépendances "
                "ou réglez VOICE_TTS_BINARY."
            )
        model = self._resolve_voice_model(voice)
        if not os.path.isfile(model):
            raise RuntimeError(
                f"Voix Piper introuvable ({model}) : téléchargez "
                "fr_FR-upmc-medium.onnx (+ .onnx.json) dans models/piper/."
            )

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

            return VoiceSynthesisResponse(
                audio_base64=base64.b64encode(audio_data).decode("utf-8"),
                mime_type="audio/wav",
                text=text,
            )
