from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


# ==========================================
# 1. Extraction & Triage Textuel / Vocal
# ==========================================

class WashExtractionRequest(BaseModel):
    raw_text: str = Field(..., description="Texte brut du signalement ou transcription vocale")
    school_name: str | None = Field(None, description="Nom de l'école (optionnel si mentionné dans le texte)")


class ExtractedWashIncident(BaseModel):
    school_detected: str | None = Field(None, description="Nom de l'établissement scolaire identifié")
    infrastructure_type: Literal[
        "water_point",
        "toilets_latrines",
        "handwashing",
        "sewage_drainage",
        "other"
    ] = Field(..., description="Type d'infrastructure WASH")
    issue_type: Literal[
        "leak",
        "total_breakdown",
        "contamination",
        "blockage",
        "dry_well",
        "vandalism",
        "other"
    ] = Field(..., description="Nature de la panne")
    urgency_level: Literal["low", "medium", "high", "critical"] = Field(..., description="Niveau d'urgence")
    estimated_affected_students: int = Field(0, description="Nombre d'élèves impactés")
    health_hazard_risk: Literal["low", "medium", "high", "severe"] = Field(..., description="Risque sanitaire immédiat")
    short_summary: str = Field(..., description="Résumé concis et factuel en français (1 à 2 phrases max)")
    recommended_priority_score: float = Field(..., ge=0.0, le=100.0, description="Score de priorité de 0 à 100")


class WashExtractionResponse(BaseModel):
    data: ExtractedWashIncident
    model_used: str
    confidence_score: float = 0.90


# ==========================================
# 2. Détection Sémantique de Doublons
# ==========================================

class IncidentItem(BaseModel):
    id: int
    summary: str
    category: str


class DuplicateCheckRequest(BaseModel):
    incoming_summary: str
    active_incidents: list[IncidentItem]
    similarity_threshold: float = 0.80


class DuplicateMatch(BaseModel):
    incident_id: int
    similarity: float
    confidence: str


class DuplicateCheckResponse(BaseModel):
    is_duplicate: bool
    matched_incident_id: int | None = None
    similarity_score: float = 0.0
    matches: list[DuplicateMatch] = []


# ==========================================
# 3. Analyse Visuelle Multimodale (Photos)
# ==========================================

class ImageAnalysisResponse(BaseModel):
    is_wash_related: bool = Field(..., description="Indique si l'image représente bien une infrastructure sanitaire/hydraulique")
    infrastructure_detected: str = Field(..., description="Type d'élément identifié visuellement (ex: Pompe manuelle, Latrine VIP, Tuyau PVC)")
    visible_damage: str = Field(..., description="Description technique du dommage visible")
    visual_severity_score: float = Field(..., ge=0.0, le=100.0, description="Score de sévérité basé sur l'état visuel (0-100)")
    health_hazard_detected: bool = Field(..., description="Présence d'eau stagnante, déversement fécal ou danger biologique visible")
    technician_notes: str = Field(..., description="Note d'orientation pour le réparateur")


# ==========================================
# 4. Fiche d'Intervention & Plan de Réparation
# ==========================================

class RepairPlanRequest(BaseModel):
    incident_summary: str
    infrastructure_type: str
    issue_type: str
    urgency_level: str


class RepairPlanResponse(BaseModel):
    required_tools: list[str] = Field(..., description="Outils nécessaires (ex: clé à griffe, pelle, chalumeau)")
    spare_parts_needed: list[str] = Field(..., description="Pièces de rechange suggérées (ex: joint torique, tuyau PEHD 32mm)")
    estimated_intervention_time: str = Field(..., description="Temps estimé pour la réparation (ex: 1h30 - 3h)")
    immediate_safety_measures: list[str] = Field(..., description="Mesures conservatoires pour protéger les élèves avant la réparation")
    estimated_cost_tier: Literal["low", "medium", "high", "critical_budget"] = Field(..., description="Ordre de grandeur du coût des réparations")


# ==========================================
# 5. Détecteur d'Alerte Épidémique (Cluster)
# ==========================================

class DistrictIncidentRecord(BaseModel):
    id: int
    school_name: str
    district: str
    category: str
    summary: str
    reported_at: str


class EpidemicClusterRequest(BaseModel):
    district: str
    recent_incidents: list[DistrictIncidentRecord]


class EpidemicClusterResponse(BaseModel):
    district: str
    incident_count: int
    risk_level: Literal["normal", "moderate", "high", "outbreak_warning"]
    alert_triggered: bool
    epidemic_syndrome: str | None = Field(None, description="ex: Risque d'épidémie de choléra ou contamination de nappe")
    recommended_health_actions: list[str] = Field(default_factory=list, description="Mesures d'urgence pour le ministère ou l'ONG")


# ==========================================
# 6. Aide à la Décision & Copilot (Replace vs Repair)
# ==========================================

class SchoolMaintenanceHistory(BaseModel):
    school_id: int
    school_name: str
    district: str
    equipment_type: str = "pompe_manuelle"
    installation_year: int | None = 2021
    estimated_replacement_cost: float = Field(1500000.0, description="Coût d'un remplacement à neuf (ex: en FCFA ou USD)")
    incident_count: int = Field(0, description="Nombre de pannes enregistrées")
    total_repair_cost: float = Field(0.0, description="Somme totale des factures de réparations passées")
    total_days_without_service: int = Field(0, description="Nombre cumulé de jours où l'école a été privée d'eau")


class ReplaceVsRepairAnalysis(BaseModel):
    school_name: str
    equipment_type: str
    recommendation: Literal["REPLACE_EQUIPMENT", "CONTINUE_REPAIR", "MONITOR_CLOSELY"]
    repair_to_replacement_ratio_percent: float = Field(..., description="Pourcentage du coût d'un équipement neuf déjà dépensé en réparations")
    annualized_failure_rate: float = Field(..., description="Fréquence moyenne de pannes par an")
    total_days_lost: int
    financial_saving_potential: str
    justification: str = Field(..., description="Raisonnement économique et opérationnel détaillé")
    suggested_modernization: str = Field(..., description="Alternative moderne conseillée (ex: Forage solaire au lieu de pompe manuelle)")


class DecisionCopilotRequest(BaseModel):
    user_query: str = Field(..., description="Question stratégique posée par l'opérateur ou décideur")
    district: str | None = Field(None, description="District ciblé")
    schools_data: list[SchoolMaintenanceHistory] = Field(default_factory=list, description="Données d'historiques fournies par Laravel")


class DecisionCopilotResponse(BaseModel):
    answer: str = Field(..., description="Réponse exécutive complète et claire de l'IA")
    tools_executed: list[str] = Field(default_factory=list, description="Outils analytiques appelés par l'agent")
    replace_recommendations: list[ReplaceVsRepairAnalysis] = Field(default_factory=list, description="Analyses de remplacement générées")
    strategic_action_plan: list[str] = Field(default_factory=list, description="Plan d'action prioritaire recommandé pour le budget")


# ==========================================
# 7. Équité Territoriale & Optimisation de Tournées
# ==========================================

class SchoolEquityProfile(BaseModel):
    school_id: int
    school_name: str
    district: str
    distance_from_center_km: float = Field(10.0, description="Distance en km depuis le centre technique communal")
    days_without_water: int = Field(0, description="Nombre de jours consécutifs sans eau potable")
    total_students: int = Field(300, description="Effectif total d'élèves")
    female_students: int = Field(150, description="Nombre de jeunes filles scolarisées")
    broken_toilets: int = Field(0, description="Nombre de latrines hors d'usage")
    months_since_last_intervention: int = Field(6, description="Mois écoulés depuis la dernière aide publique")
    urgency_level: Literal["low", "medium", "high", "critical"] = "medium"
    issue_summary: str = Field("", description="Description succincte de la panne")
    lat: float | None = None
    lng: float | None = None


class FairnessRankingItem(BaseModel):
    school_id: int
    school_name: str
    equity_score: float = Field(..., description="Score d'équité et de vulnérabilité de 0 à 100")
    rank: int
    primary_vulnerability_reason: str
    days_deprived: int
    distance_km: float


class GroupedMission(BaseModel):
    route_name: str = Field(..., description="Axe routier de la tournée mutualisée")
    primary_emergency_school: str = Field(..., description="École en urgence critique justifiant le déplacement du camion")
    piggybacked_schools: list[str] = Field(default_factory=list, description="Écoles dépannées sur le même trajet pour rentabiliser le carburant")
    total_schools_served: int
    estimated_kilometers_saved: float = Field(..., description="Kilomètres et carburant économisés")
    technician_mission_brief: str = Field(..., description="Feuille de route logistique pour l'équipe")


class FairnessDispatchPlan(BaseModel):
    district: str
    total_schools_evaluated: int
    ranked_schools: list[FairnessRankingItem]
    grouped_routes: list[GroupedMission]
    public_transparency_note: str = Field(..., description="Note officielle d'opposabilité anti-favoritisme opposable aux pressions politiques")


class FairnessDispatchRequest(BaseModel):
    district: str
    schools: list[SchoolEquityProfile] = Field(default_factory=list)


# ==========================================
# 8. Audio (STT & TTS)
# ==========================================

class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    language: str = "fr"
    duration_seconds: float | None = None


class VoiceSynthesisRequest(BaseModel):
    text: str
    voice: str = "fr_FR-upmc-medium"


class VoiceSynthesisResponse(BaseModel):
    audio_base64: str
    mime_type: str = "audio/wav"
    text: str


# ==========================================
# 9. Administration des Providers LLM
# ==========================================

class ProviderTestRequest(BaseModel):
    provider: str = Field("ollama", description="ollama ou openai_compatible")
    base_url: str = Field(..., description="URL de base du provider")
    model: str = Field(..., description="Modèle texte à tester")
    vision_model: str | None = None
    embed_model: str | None = None
    api_key: str | None = None
    timeout: float = 30.0


class ProviderTestResponse(BaseModel):
    ok: bool
    latency_ms: int = 0
    sample: str = ""
    error: str | None = None
    provider: str = ""
    model: str = ""


# ==========================================
# 10. Administration des Providers STT
# ==========================================

class SttTestRequest(BaseModel):
    driver: str = Field("whisper_cpp", description="whisper_cpp, omnilingual_onnx ou cloud_whisper")
    base_url: str | None = None
    model: str | None = None
    tokens: str | None = None
    api_key: str | None = None
    language: str = Field("fr", description="Code langue (fr, dua_Latn, ...)")
    audio_base64: str = Field(..., description="Échantillon audio encodé en base64")
    filename: str = "test.wav"
    timeout: float = 60.0


class SttTestResponse(BaseModel):
    ok: bool
    latency_ms: int = 0
    transcript: str = ""
    error: str | None = None
    driver: str = ""
    language: str = ""


# ==========================================
# 11. Agent Conversationnel Unifié
# ==========================================

class ChatTurn(BaseModel):
    role: str = Field(..., description="user, assistant ou tool")
    content: str


class AgentContext(BaseModel):
    schools: list[dict[str, Any]] = Field(default_factory=list, description="Écoles avec agrégats de maintenance")
    incidents: list[dict[str, Any]] = Field(default_factory=list, description="Incidents avec école, urgence et dates")


class AgentChatRequest(BaseModel):
    message: str = Field(..., description="Message de l'utilisateur")
    history: list[ChatTurn] = Field(default_factory=list, description="Historique court de conversation")
    context: AgentContext = Field(default_factory=AgentContext, description="Données factuelles fournies par Laravel")


class AgentCard(BaseModel):
    type: str = Field(..., description="school_analysis, school_ranking, district_summary, incident_detail, report_confirmation")
    title: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentChatResponse(BaseModel):
    answer: str
    tools_executed: list[str] = Field(default_factory=list)
    cards: list[AgentCard] = Field(default_factory=list)
    model_used: str = ""
