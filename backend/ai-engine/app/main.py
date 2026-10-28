from __future__ import annotations

from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .decision_agent import DecisionAgent
from .duplicate_detector import DuplicateDetector
from .epidemic_detector import EpidemicDetector
from .equity_dispatcher import EquityDispatcher
from .extractor import WashExtractor
from .image_analyzer import ImageAnalyzer
from .providers import PROVIDER_TYPES, OllamaProvider, llm_from_headers, provider_from_profile
from .repair_advisor import RepairAdvisor
from .schemas import (
    DecisionCopilotRequest,
    DecisionCopilotResponse,
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    EpidemicClusterRequest,
    EpidemicClusterResponse,
    FairnessDispatchPlan,
    FairnessDispatchRequest,
    ImageAnalysisResponse,
    ProviderTestRequest,
    ProviderTestResponse,
    RepairPlanRequest,
    RepairPlanResponse,
    ReplaceVsRepairAnalysis,
    SchoolMaintenanceHistory,
    VoiceSynthesisRequest,
    VoiceSynthesisResponse,
    VoiceTranscriptionResponse,
    WashExtractionRequest,
    WashExtractionResponse,
)
from .voice_service import VoiceService

app = FastAPI(
    title="WASH Sentinel AI Engine",
    description="Moteur IA complet pour la priorisation équitable, la détection multimodale, l'aide à la décision stratégique (Réparer vs Remplacer) et l'optimisation logistique anti-favoritisme.",
    version="1.3.0",
)

# CORS pour autoriser Laravel et le frontend React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialisation des composants IA
default_llm = OllamaProvider()
voice_service = VoiceService()


def _llm(request: Request):
    """Résout le provider LLM actif depuis les headers envoyés par Laravel.

    Sans headers : retombe sur la configuration d'environnement (Ollama local).
    Chaque requête a son propre client : aucun état global mutable.
    """
    return llm_from_headers(request.headers)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "WASH Sentinel AI Engine",
        "models": {
            "llm": default_llm.model,
            "vision": default_llm.vision_model,
            "embeddings": default_llm.embed_model,
        },
        "providers": [p["id"] for p in PROVIDER_TYPES],
        "capabilities": [
            "text_extraction",
            "voice_transcription",
            "voice_synthesis",
            "multimodal_vision",
            "duplicate_detection",
            "repair_planning",
            "epidemic_early_warning",
            "decision_copilot_tool_calling",
            "repair_vs_replace_matrix",
            "equity_dispatcher_anti_favoritism",
            "route_clustering_optimizer",
        ],
    }


# ==========================================
# 1. Extraction et Structuration Textuelle
# ==========================================
@app.post("/v1/wash/extract", response_model=WashExtractionResponse)
async def extract_wash_data(request: Request, payload: WashExtractionRequest) -> WashExtractionResponse:
    """Extrait et structure un signalement en JSON strict via Meta Llama 3.2."""
    try:
        return await WashExtractor(_llm(request)).extract(payload.raw_text, payload.school_name)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur d'extraction IA : {str(exc)}"
        ) from exc


# ==========================================
# 2. Détection de Doublons Sémantiques
# ==========================================
@app.post("/v1/wash/check-duplicates", response_model=DuplicateCheckResponse)
async def check_duplicates(request: Request, payload: DuplicateCheckRequest) -> DuplicateCheckResponse:
    """Compare un signalement aux incidents existants pour détecter les doublons par similarité vectorielle."""
    try:
        return await DuplicateDetector(_llm(request)).check(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la détection de doublons : {str(exc)}"
        ) from exc


# ==========================================
# 3. Vision Multimodale (Analyse de Photos)
# ==========================================
@app.post("/v1/wash/analyze-image", response_model=ImageAnalysisResponse)
async def analyze_photo(request: Request, photo: UploadFile = File(...)) -> ImageAnalysisResponse:
    """Analyse visuellement une photo de panne d'infrastructure via Llama 3.2 Vision."""
    try:
        image_bytes = await photo.read()
        return await ImageAnalyzer(_llm(request)).analyze(image_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur d'analyse visuelle : {str(exc)}"
        ) from exc


# ==========================================
# 4. Fiche Technique de Réparation (Techniciens)
# ==========================================
@app.post("/v1/wash/generate-repair-plan", response_model=RepairPlanResponse)
async def generate_repair_plan(request: Request, payload: RepairPlanRequest) -> RepairPlanResponse:
    """Génère le matériel requis, outils, temps d'intervention et mesures de sécurité pour le réparateur."""
    try:
        return await RepairAdvisor(_llm(request)).generate_plan(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la génération du plan technique : {str(exc)}"
        ) from exc


# ==========================================
# 5. Détecteur de Grappe & Alerte Épidémique
# ==========================================
@app.post("/v1/wash/detect-epidemic-risk", response_model=EpidemicClusterResponse)
async def detect_epidemic_risk(request: Request, payload: EpidemicClusterRequest) -> EpidemicClusterResponse:
    """Analyse les incidents récents d'un district pour déclencher une alerte épidémique précoce (ex: Choléra)."""
    try:
        return await EpidemicDetector(_llm(request)).detect_cluster(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'évaluation épidémique : {str(exc)}"
        ) from exc


# ==========================================
# 6. Équité Territoriale & Tournées Groupées (Anti-Favoritisme)
# ==========================================
@app.post("/v1/wash/equity/dispatch-plan", response_model=FairnessDispatchPlan)
async def generate_equity_dispatch_plan(request: Request, payload: FairnessDispatchRequest) -> FairnessDispatchPlan:
    """
    Le Gardien de l'Équité Territoriale :
    1. Classe les écoles selon une formule d'équité transparente (jours sans eau, filles, isolement).
    2. Regroupe les pannes sur le même axe pour économiser les kilomètres du camion communal.
    3. Rédige la note officielle de transparence opposable aux pressions politiques.
    """
    try:
        return await EquityDispatcher(_llm(request)).generate_fairness_plan(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du calcul du plan d'équité : {str(exc)}"
        ) from exc


# ==========================================
# 7. Aide à la Décision Stratégique & Copilot (Tool-Calling)
# ==========================================
@app.post("/v1/wash/copilot/chat", response_model=DecisionCopilotResponse)
async def decision_copilot_chat(request: Request, payload: DecisionCopilotRequest) -> DecisionCopilotResponse:
    """
    Agent conversationnel d'aide à la décision :
    Interroge les historiques d'interventions, exécute les tools d'arbitrage
    et conseille les décideurs sur les investissements prioritaires (Réparer vs Remplacer).
    """
    try:
        return await DecisionAgent(_llm(request)).answer_decision_query(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur du Copilot Décisionnel : {str(exc)}"
        ) from exc


@app.post("/v1/wash/copilot/replace-vs-repair", response_model=ReplaceVsRepairAnalysis)
def evaluate_replace_vs_repair(request: Request, school: SchoolMaintenanceHistory) -> ReplaceVsRepairAnalysis:
    """Évalue mathématiquement et financièrement si un équipement doit être remplacé à neuf ou encore réparé."""
    try:
        return DecisionAgent(_llm(request)).evaluate_school_equipment(school)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'analyse Réparer vs Remplacer : {str(exc)}"
        ) from exc


# ==========================================
# 8. Audio (Transcription STT & Synthèse TTS)
# ==========================================
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


@app.post("/v1/voice/synthesize", response_model=VoiceSynthesisResponse)
def synthesize_voice(payload: VoiceSynthesisRequest) -> VoiceSynthesisResponse:
    """Génère un message audio de confirmation via Piper TTS."""
    try:
        return voice_service.synthesize(payload.text, payload.voice)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de synthèse vocale : {str(exc)}"
        ) from exc


# ==========================================
# 9. Pipeline Unifié Commando (Texte ou Voix)
# ==========================================
@app.post("/v1/wash/triage")
async def triage_report(
    request: Request,
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
    school_name: str | None = Form(None),
) -> dict[str, Any]:
    """
    Endpoint Commando Unifié :
    Accepte du texte ou un enregistrement audio, transcrit si besoin,
    puis extrait, priorise et renvoie les données complètes pour Laravel.
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

    extracted = await WashExtractor(_llm(request)).extract(raw_content, school_name)

    return {
        "raw_text": raw_content,
        "is_voice": audio is not None,
        "voice_details": transcription_meta,
        "extraction": extracted.dict(),
    }
# ==========================================
# 10. Administration des Providers (page Settings)
# ==========================================
@app.get("/v1/admin/provider-types")
def list_provider_types() -> dict[str, Any]:
    """Descripteurs des providers supportés : pilote le formulaire dynamique de la page Settings."""
    return {"providers": PROVIDER_TYPES}


@app.post("/v1/admin/test-provider", response_model=ProviderTestResponse)
async def test_provider(payload: ProviderTestRequest) -> ProviderTestResponse:
    """Teste un profil modèle (bouton Tester de la page Settings)."""
    try:
        provider = provider_from_profile(payload.model_dump())
        result = await provider.test()
        return ProviderTestResponse(
            ok=result["ok"],
            latency_ms=result["latency_ms"],
            sample=result["sample"],
            error=result["error"],
            provider=provider.provider_name,
            model=provider.model,
        )
    except Exception as exc:
        return ProviderTestResponse(ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}")
