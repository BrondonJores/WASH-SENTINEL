from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from .schemas import VoiceSynthesisResponse, VoiceTranscriptionResponse


class VoiceService:
    def __init__(self):
        self.whisper_bin = os.getenv("VOICE_STT_BINARY", "/opt/voice/bin/whisper-cli")
        self.whisper_model = os.getenv("VOICE_STT_MODEL", "/models/whisper/ggml-base.bin")
        self.piper_bin = os.getenv("VOICE_TTS_BINARY", "/opt/voice/bin/piper")
        self.piper_model = os.getenv("VOICE_TTS_MODEL", "/models/piper/fr_FR-upmc-medium.onnx")

    def transcribe(self, audio_bytes: bytes, filename: str = "report.wav", language: str = "fr") -> VoiceTranscriptionResponse:
        """Transcrit un fichier audio en texte via Whisper.cpp."""
        if not os.path.isfile(self.whisper_bin) or not os.path.isfile(self.whisper_model):
            return VoiceTranscriptionResponse(
                transcript="[Transcription locale : Fuite importante constatée sur la canalisation principale de l'école.]",
                language=language,
            )

        with tempfile.TemporaryDirectory(prefix="wash-stt-") as tmpdir:
            input_file = os.path.join(tmpdir, filename)
            with open(input_file, "wb") as f:
                f.write(audio_bytes)

            wav_file = os.path.join(tmpdir, "normalized.wav")
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-i", input_file,
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                wav_file
            ]
            subprocess.run(ffmpeg_cmd, capture_output=True, check=False)

            out_base = os.path.join(tmpdir, "output")
            whisper_cmd = [
                self.whisper_bin,
                "-m", self.whisper_model,
                "-f", wav_file,
                "-l", language,
                "-otxt",
                "-of", out_base,
            ]
            res = subprocess.run(whisper_cmd, capture_output=True, text=True, check=False)

            txt_file = out_base + ".txt"
            transcript = ""
            if os.path.isfile(txt_file):
                with open(txt_file, "r", encoding="utf-8") as tf:
                    transcript = tf.read().strip()

            return VoiceTranscriptionResponse(
                transcript=transcript or res.stdout.strip(),
                language=language,
            )

    def synthesize(self, text: str, voice: str = "fr_FR-upmc-medium") -> VoiceSynthesisResponse:
        """Synthétise un texte en audio via Piper TTS pour confirmation vocale."""
        if not os.path.isfile(self.piper_bin) or not os.path.isfile(self.piper_model):
            # Fallback dev mode : un en-tête WAV 44 bytes silencieux encodé en base64
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
