from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


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
    short_summary: str = Field(..., description="Résumé concis et factuel en français (1 à 2 phrases)")
    recommended_priority_score: float = Field(..., ge=0.0, le=100.0, description="Score de priorité de 0 à 100")


class WashExtractionResponse(BaseModel):
    data: ExtractedWashIncident
    model_used: str
    confidence_score: float = 0.90


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


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    language: str = "fr"
    duration_seconds: float | None = None
