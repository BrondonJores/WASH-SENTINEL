"""Acceptance vocale RÉELLE (à lancer DANS le conteneur ai-engine).

Transcrit un fichier audio avec la cascade auto-détection et affiche le
JSON (transcript, langue demandée/détectée, driver, détail). Usage :

  docker cp backend/ai-engine/tests/fixtures/voice_bbj_brother_01.ogg \\
      wash-sentinel-ai-engine-1:/tmp/voice.ogg
  docker compose exec -T ai-engine python /app/accept_voice.py /tmp/voice.ogg bbj_Latn

Zéro dépendance réseau : whisper.cpp + sherpa-onnx + modèles du conteneur.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: accept_voice.py <audio> <langue_demandée>")
        return 2
    path, language = sys.argv[1], sys.argv[2]
    with open(path, "rb") as handle:
        audio = handle.read()
    from app.voice_service import VoiceService
    try:
        res = VoiceService().transcribe(audio, path.rsplit("/", 1)[-1], language)
    except Exception as exc:  # guidage métier affiché tel quel
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(res.model_dump(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
