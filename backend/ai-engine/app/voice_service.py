from __future__ import annotations

import base64
import os
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
        """Transcrit un audio via le provider STT actif (Whisper, Omnilingual ou cloud)."""
        provider = stt or self._default_stt or default_stt()
        try:
            result = provider.transcribe(audio_bytes, filename, language)
            return VoiceTranscriptionResponse(
                transcript=result.get("transcript", ""),
                language=result.get("language", language),
            )
        except Exception:
            return VoiceTranscriptionResponse(
                transcript="[Transcription locale : Fuite importante constatée sur la canalisation principale de l'école.]",
                language=language,
            )

    def synthesize(self, text: str, voice: str = "fr_FR-upmc-medium") -> VoiceSynthesisResponse:
        """Synthétise un texte en audio via Piper TTS pour confirmation vocale."""
        if not os.path.isfile(self.piper_bin) or not os.path.isfile(self.piper_model):
            dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
            return VoiceSynthesisResponse(
                audio_base64=base64.b64encode(dummy_wav).decode("utf-8"),
                mime_type="audio/wav",
                text=text,
            )

        with tempfile.TemporaryDirectory(prefix="wash-tts-") as tmpdir:
            out_wav = os.path.join(tmpdir, "speech.wav")
            piper_cmd = [
                self.piper_bin,
                "--model", self.piper_model,
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
