from __future__ import annotations

import os
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .duplicate_detector import DuplicateDetector
from .extractor import WashExtractor
from .ollama_client import OllamaClient
from .schemas import (
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    VoiceTranscriptionResponse,
    WashExtractionRequest,
    WashExtractionResponse,
)
from .voice_service import VoiceService

app = FastAPI(
    title="WASH Sentinel AI Engine",
    description="Microservice d'Intelligence Artificielle pour la priorisation et le suivi des urgences WASH en milieu scolaire.",
    version="1.0.0",
)

# CORS pour autoriser Laravel et le frontend React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialisation des composants
ollama_client = OllamaClient()
extractor = WashExtractor(ollama_client)
duplicate_detector = DuplicateDetector(ollama_client)
voice_service = VoiceService()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "WASH Sentinel AI Engine",
        "model": ollama_client.model,
        "ollama_url": ollama_client.base_url,
    }


@app.post("/v1/wash/extract", response_model=WashExtractionResponse)
async def extract_wash_data(payload: WashExtractionRequest) -> WashExtractionResponse:
    """Extrait et structure un signalement en JSON strict via Meta Llama 3.2."""
    try:
        return await extractor.extract(payload.raw_text, payload.school_name)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur d'extraction IA : {str(exc)}"
        ) from exc


@app.post("/v1/wash/check-duplicates", response_model=DuplicateCheckResponse)
async def check_duplicates(payload: DuplicateCheckRequest) -> DuplicateCheckResponse:
    """Compare un signalement aux incidents existants pour détecter les doublons par similarité vectorielle."""
    try:
        return await duplicate_detector.check(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la détection de doublons : {str(exc)}"
        ) from exc


@app.post("/v1/voice/transcribe", response_model=VoiceTranscriptionResponse)
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("fr"),
) -> VoiceTranscriptionResponse:
    """Transcrit une note vocale d'urgence via Whisper.cpp."""
    try:
        audio_bytes = await audio.read()
        return voice_service.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.wav",
            language=language,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de transcription audio : {str(exc)}"
        ) from exc


@app.post("/v1/wash/triage")
async def triage_report(
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
    school_name: str | None = Form(None),
) -> dict[str, Any]:
    """
    Endpoint Commando Unifié :
    Accepte soit du texte, soit une note vocale, transcrit si nécessaire,
    puis extrait et priorise la panne dans un format immédiatement exploitable par Laravel.
    """
    raw_content = text or ""
    transcription_meta = None

    if audio is not None:
        audio_bytes = await audio.read()
        transcription_res = voice_service.transcribe(audio_bytes, audio.filename or "audio.wav", "fr")
        raw_content = transcription_res.transcript
        transcription_meta = transcription_res.dict()

    if not raw_content.strip():
        raise HTTPException(status_code=422, detail="Aucun contenu textuel ou audio exploitable fourni.")

    extracted = await extractor.extract(raw_content, school_name)

    return {
        "raw_text": raw_content,
        "is_voice": audio is not None,
        "voice_details": transcription_meta,
        "extraction": extracted.dict(),
    }
