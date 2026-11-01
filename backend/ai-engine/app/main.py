from __future__ import annotations

from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .agent_loop import AgentLoop
from .ai_metrics import summary as ai_metrics_summary, timed
from .decision_agent import DecisionAgent
from .duplicate_detector import DuplicateDetector
from .epidemic_detector import EpidemicDetector
from .equity_dispatcher import EquityDispatcher
from .extractor import WashExtractor
from .image_analyzer import ImageAnalyzer, is_vision_unavailable, visual_boost, visual_severity
from .providers import PROVIDER_TYPES, OllamaProvider, llm_from_headers, provider_from_profile
from .stt_providers import STT_PROVIDER_TYPES, stt_from_headers, stt_from_profile
from .tts_providers import TTS_PROVIDER_TYPES, tts_from_headers
from .rag_store import RAGStore
from .recurrence_watch import watch_recurrence
from .repair_advisor import RepairAdvisor
from .schemas import (
    SCORE_MAX,
    DecisionCopilotRequest,
    DecisionCopilotResponse,
    AgentChatRequest,
    AgentChatResponse,
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    EpidemicClusterRequest,
    EpidemicClusterResponse,
    FairnessDispatchPlan,
    FairnessDispatchRequest,
    ImageAnalysisResponse,
    ProviderTestRequest,
    ProviderTestResponse,
    RagAskRequest,
    RagAskResponse,
    RecurrenceWatchRequest,
    RecurrenceWatchResponse,
    SttTestRequest,
    SttTestResponse,
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

#: Troncature des détails d'erreur renvoyés au relais (triage vision).
ERROR_DETAIL_MAX_CHARS = 200
from .voice_service import (
    MAX_VOICE_AUDIO_BYTES,
    VOICE_AUDIO_CHUNK_BYTES,
    VoiceService,
    voice_too_heavy_message,
)

app = FastAPI(
    title="WASH Sentinel AI Engine",
    description="Moteur IA complet pour la priorisation équitable, la détection multimodale, l'aide à la décision stratégique (Réparer vs Remplacer) et l'optimisation logistique anti-favoritisme.",
    version="1.4.0",
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
        "stt_drivers": [d["id"] for d in STT_PROVIDER_TYPES],
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
        llm = _llm(request)
        with timed("extract", model=llm.model, provider=llm.provider_name):
            return await WashExtractor(llm).extract(payload.raw_text, payload.school_name)
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
        llm = _llm(request)
        with timed("check_duplicates", model=llm.model, provider=llm.provider_name):
            return await DuplicateDetector(llm).check(payload)
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
    """Analyse visuellement une photo de panne d'infrastructure via le modèle vision configuré."""
    try:
        image_bytes = await photo.read()
        llm = _llm(request)
        with timed("analyze_image", model=llm.vision_model, provider=llm.provider_name):
            result = await ImageAnalyzer(llm).analyze(image_bytes)
        if is_vision_unavailable(result):
            result.vision_unavailable = True
        return result
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
    request: Request,
    audio: UploadFile = File(...),
    language: str | None = Form(None),
) -> VoiceTranscriptionResponse:
    """Transcrit une note vocale via le provider STT actif (Whisper, Omnilingual ou cloud).

    Précédence de langue : requête explicite > profil (header X-STT-Language) > fr.
    Plafond 12 Mo mesuré par chunks AVANT de tout charger (anti-DoS direct).
    """
    try:
        size = 0
        chunks: list[bytes] = []
        while True:
            chunk = await audio.read(VOICE_AUDIO_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_VOICE_AUDIO_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=voice_too_heavy_message(size),
                )
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)
        stt_language = language or request.headers.get("x-stt-language") or "fr"
        return voice_service.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.wav",
            language=stt_language,
            stt=stt_from_headers(request.headers),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de transcription audio : {str(exc)}"
        ) from exc

@app.post("/v1/voice/synthesize", response_model=VoiceSynthesisResponse)
def synthesize_voice(request: Request, payload: VoiceSynthesisRequest) -> VoiceSynthesisResponse:
    """Génère un message audio de confirmation (Piper FR par défaut, MMS si X-TTS-Driver: mms)."""
    try:
        return voice_service.synthesize(
            payload.text, payload.voice, payload.language, tts=tts_from_headers(request.headers)
        )
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
    photo: UploadFile | None = File(None),
    school_name: str | None = Form(None),
) -> dict[str, Any]:
    """
    Endpoint Commando Unifié :
    Accepte du texte, un enregistrement audio ou une photo, transcrit/analyse si besoin,
    puis extrait, priorise (bonus visuel éventuel) et renvoie les données complètes pour Laravel.
    """
    raw_content = text or ""
    transcription_meta = None

    if audio is not None:
        audio_bytes = await audio.read()
        transcription_res = voice_service.transcribe(audio_bytes, audio.filename or "audio.wav", request.headers.get("x-stt-language") or "fr", stt_from_headers(request.headers))
        raw_content = transcription_res.transcript
        transcription_meta = transcription_res.dict()

    if not raw_content.strip():
        raise HTTPException(status_code=422, detail="Aucun contenu textuel ou audio exploitable fourni.")

    extracted = await WashExtractor(_llm(request)).extract(raw_content, school_name)

    visual_meta: dict[str, Any] | None = None
    boost = 0.0
    if photo is not None:
        try:
            vision = await ImageAnalyzer(_llm(request)).analyze(await photo.read())
            severity = visual_severity(vision)
            boost = visual_boost(severity)
            visual_meta = {**vision.dict(), "visual_severity": severity, "visual_boost": boost,
                           "vision_unavailable": is_vision_unavailable(vision)}
        except Exception as exc:  # ceinture + bretelles (analyze() ne lève déjà jamais)
            visual_meta = {"vision_error": f"{type(exc).__name__}: {str(exc)[:ERROR_DETAIL_MAX_CHARS]}"}

    base_score = extracted.data.recommended_priority_score
    return {
        "raw_text": raw_content,
        "is_voice": audio is not None,
        "voice_details": transcription_meta,
        "extraction": extracted.dict(),
        "unknowns": extracted.unknowns,
        "next_action": extracted.next_action,
        "visual": visual_meta,
        "priority_score_with_vision": round(min(SCORE_MAX, base_score + boost), 1),
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

@app.post("/v1/admin/warmup")
async def warmup_provider(request: Request) -> dict[str, Any]:
    """Pré-chauffe le provider LLM actif (Ollama froid) via un appel léger."""
    try:
        return await _llm(request).warmup()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur au réchauffement du provider : {str(exc)}"
        ) from exc
# ==========================================
# 11. Administration des Providers STT (page Settings)
# ==========================================
@app.get("/v1/admin/stt-types")
def list_stt_types() -> dict[str, Any]:
    """Descripteurs des moteurs de transcription : pilote le formulaire dynamique de la page Settings."""
    return {"drivers": STT_PROVIDER_TYPES}

@app.post("/v1/admin/test-stt", response_model=SttTestResponse)
async def test_stt(payload: SttTestRequest) -> SttTestResponse:
    """Teste un profil STT sur un échantillon audio (bouton Tester de la page Settings)."""
    import base64 as _base64
    import binascii as _binascii

    try:
        audio_bytes = _base64.b64decode(payload.audio_base64)
    except _binascii.Error as exc:
        raise HTTPException(status_code=422, detail="audio_base64 invalide.") from exc
    try:
        provider = stt_from_profile(payload.model_dump())
        result = provider.test(audio_bytes, payload.filename, payload.language)
        return SttTestResponse(
            ok=result["ok"],
            latency_ms=result["latency_ms"],
            transcript=result["transcript"],
            error=result["error"],
            driver=provider.driver_name,
            language=result["language"],
        )
    except Exception as exc:
        return SttTestResponse(ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}", language=payload.language)

@app.get("/v1/admin/tts-types")
def list_tts_types() -> dict[str, Any]:
    """Descripteurs des moteurs de synthèse : pilote le formulaire dynamique de la page Settings."""
    return {"drivers": TTS_PROVIDER_TYPES}
# ==========================================
# 12. Q&R Documentaire Sourcée (RAG)
# ==========================================
@app.post("/v1/wash/rag/ask", response_model=RagAskResponse)
async def rag_ask(request: Request, payload: RagAskRequest) -> RagAskResponse:
    """Q&R documentaire sourcée : répond UNIQUEMENT depuis les manuels app/data, sinon abstention."""
    try:
        llm = _llm(request)
        store = RAGStore(embed_fn=llm.get_embedding)
        result = await store.answer_with_sources(payload.question, llm, k=payload.k)
        return RagAskResponse(answer=result["answer"], sources=result["sources"])
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur RAG documentaire : {str(exc)}"
        ) from exc

# ==========================================
# 13. Veille Prédictive des Pannes Récurrentes
# ==========================================
@app.post("/v1/wash/recurrence-watch", response_model=RecurrenceWatchResponse)
def recurrence_watch(payload: RecurrenceWatchRequest) -> RecurrenceWatchResponse:
    """Veille prédictive : risque de récidive + plan préventif (déterministe, sans LLM)."""
    history = [i.model_dump() for i in payload.history] or payload.school
    result = watch_recurrence(history)
    return RecurrenceWatchResponse(risk=result["risk"], plan=result["plan"])

# ==========================================
# 14. Observabilité IA (latences/tokens)
# ==========================================
@app.get("/v1/admin/ai-metrics")
def get_ai_metrics() -> dict[str, Any]:
    """Observabilité IA : latences (avg/p95) et tokens par opération LLM."""
    return ai_metrics_summary()

# ==========================================
# 15. Agent Conversationnel Unifié (Dashboardless)
# ==========================================
@app.post("/v1/agent/chat", response_model=AgentChatResponse)
async def agent_chat(request: Request, payload: AgentChatRequest) -> AgentChatResponse:
    """Boucle agentique réelle : le LLM choisit ses outils (function-calling natif),
    Python les exécute sur les données Laravel, et des cartes structurées sont
    renvoyées pour le widget omniprésent."""
    try:
        llm = _llm(request)
        with timed("agent_chat", model=llm.model, provider=llm.provider_name):
            return await AgentLoop(llm).chat(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de l'agent conversationnel : {str(exc)}"
        ) from exc

