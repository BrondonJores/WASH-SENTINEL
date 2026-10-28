from __future__ import annotations

from typing import Literal
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
# 6. Audio (STT & TTS)
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
