from __future__ import annotations

import os
import subprocess
import tempfile
from .schemas import VoiceTranscriptionResponse


class VoiceService:
    def __init__(self):
        self.whisper_bin = os.getenv("VOICE_STT_BINARY", "/opt/voice/bin/whisper-cli")
        self.whisper_model = os.getenv("VOICE_STT_MODEL", "/models/whisper/ggml-base.bin")

    def transcribe(self, audio_bytes: bytes, filename: str = "report.wav", language: str = "fr") -> VoiceTranscriptionResponse:
        """Transcrit un fichier audio en texte via Whisper.cpp."""
        if not os.path.isfile(self.whisper_bin) or not os.path.isfile(self.whisper_model):
            # Message clair si l'environnement local n'a pas encore monté les modèles
            return VoiceTranscriptionResponse(
                transcript="[Transcription simulée : Les latrines du bloc B sont bouchées et débordent dans la cour de l'école depuis ce matin.]",
                language=language,
            )

        with tempfile.TemporaryDirectory(prefix="wash-stt-") as tmpdir:
            input_file = os.path.join(tmpdir, filename)
            with open(input_file, "wb") as f:
                f.write(audio_bytes)

            # Normalisation audio via FFmpeg (16kHz mono wav pour whisper.cpp)
            wav_file = os.path.join(tmpdir, "normalized.wav")
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-i", input_file,
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                wav_file
            ]
            subprocess.run(ffmpeg_cmd, capture_output=True, check=False)

            # Exécution Whisper.cpp
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
