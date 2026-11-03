from __future__ import annotations

import base64
import binascii
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

from .thresholds import DUPLICATE_DECISION_THRESHOLD


# --- LOT 2 : constantes de schémas centralisées (valeurs inchangées) ---

#: Bornes des scores /100 (priorité recommandée, sévérité visuelle).
SCORE_MIN = 0.0
SCORE_MAX = 100.0

#: RAG : nombre d'extraits remontés par défaut + bornes acceptées.
RAG_K_DEFAULT = 3
RAG_K_MIN = 1
RAG_K_MAX = 10

#: Année d'installation supposée quand l'historique est muet (copilote).
DEFAULT_INSTALLATION_YEAR = 2021

#: Coût d'un remplacement à neuf quand Laravel ne le fournit pas (FCFA/USD).
DEFAULT_REPLACEMENT_COST = 1500000.0

#: Défauts du profil d'équité territoriale (école "moyenne" supposée).
DEFAULT_EQUITY_DISTANCE_KM = 10.0
DEFAULT_EQUITY_DAYS_WITHOUT_WATER = 0
DEFAULT_EQUITY_TOTAL_STUDENTS = 300
DEFAULT_EQUITY_FEMALE_STUDENTS = 150
DEFAULT_EQUITY_BROKEN_TOILETS = 0
DEFAULT_EQUITY_MONTHS_SINCE_INTERVENTION = 6
DEFAULT_EQUITY_URGENCY = "medium"
DEFAULT_EQUITY_ISSUE_SUMMARY = ""

#: Langue de travail par défaut (transcription, synthèse, tests STT).
DEFAULT_LANGUAGE = "fr"

#: Voix TTS FR par défaut (Mimic3 / MMS selon driver).
DEFAULT_TTS_VOICE = "fr_FR-upmc-medium"

#: Conteneur audio renvoyé par la synthèse vocale.
DEFAULT_TTS_MIME_TYPE = "audio/wav"

#: Provider LLM interrogé par défaut par l'outil de test provider.
DEFAULT_LLM_PROVIDER = "ollama"

#: Timeouts de l'outil de test (LLM texte vs STT audio, plus lent).
DEFAULT_PROVIDER_TEST_TIMEOUT = 30.0
DEFAULT_STT_TEST_TIMEOUT = 60.0

#: Driver STT interrogé par défaut par l'outil de test STT.
DEFAULT_STT_DRIVER = "whisper_cpp"

#: Nom de fichier de l'échantillon audio de test STT.
DEFAULT_STT_TEST_FILENAME = "test.wav"

#: Taille max d'une photo envoyée au chat agent (base64 décodé, en octets).
#: Au-delà, la requête est rejetée (422) avant tout appel LLM.
CHAT_IMAGE_MAX_BYTES = 10 * 1024 * 1024

#: MIME supposé quand Laravel envoie une image sans type explicite.
CHAT_IMAGE_DEFAULT_MIME = "image/jpeg"


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
    students_unknown: bool = Field(False, description="True si le nombre d'élèves est un défaut (50), non confirmé")
    is_wash_related: bool | None = Field(None, description="None=non évalué, False=hors-sujet suspecté, True=WASH")
    health_hazard_risk: Literal["low", "medium", "high", "severe"] = Field(..., description="Risque sanitaire immédiat")
    short_summary: str = Field(..., description="Résumé concis et factuel en français (1 à 2 phrases max)")
    recommended_priority_score: float = Field(..., ge=SCORE_MIN, le=SCORE_MAX, description="Score de priorité de 0 à 100")


class WashExtractionResponse(BaseModel):
    data: ExtractedWashIncident
    model_used: str
    confidence_score: float = 0.0
    unknowns: list[str] = Field(default_factory=list, description="Champs non confirmés (codes stables)")
    next_action: str = Field("", description="Prochaine action opérateur pour fiabiliser le signalement")
    field_provenance: dict[str, str] = Field(default_factory=dict, description="Provenance par champ (llm|keyword|default|declared|unknown)")


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
    # Source unique app.thresholds (AXE 8) : pas de duplication du défaut.
    similarity_threshold: float = DUPLICATE_DECISION_THRESHOLD


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
    visual_severity_score: float = Field(..., ge=SCORE_MIN, le=SCORE_MAX, description="Score de sévérité basé sur l'état visuel (0-100)")
    health_hazard_detected: bool = Field(..., description="Présence d'eau stagnante, déversement fécal ou danger biologique visible")
    technician_notes: str = Field(..., description="Note d'orientation pour le réparateur")
    vision_unavailable: bool = Field(False, description="True si la vision a échoué : ne pas croire le score")
    vision_error: str | None = Field(None, description="Raison brute de la panne vision (None si vision OK)")
    next_action: str = Field("", description="Prochaine action opérateur (reprendre la photo, réveiller le modèle...)")


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
    installation_year: int | None = DEFAULT_INSTALLATION_YEAR
    estimated_replacement_cost: float = Field(DEFAULT_REPLACEMENT_COST, description="Coût d'un remplacement à neuf (ex: en FCFA ou USD)")
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
    data_source: Literal["real", "empty"] = Field("real", description="real=données Laravel, empty=abstention sans données")
    warnings: list[str] = Field(default_factory=list, description="Avertissements (abstention, secours sans LLM...)")
    next_action: str = Field("", description="Prochaine action opérateur pour obtenir une analyse")


# ==========================================
# 7. Équité Territoriale & Optimisation de Tournées
# ==========================================

class SchoolEquityProfile(BaseModel):
    school_id: int
    school_name: str
    district: str
    distance_from_center_km: float = Field(DEFAULT_EQUITY_DISTANCE_KM, description="Distance en km depuis le centre technique communal")
    days_without_water: int = Field(DEFAULT_EQUITY_DAYS_WITHOUT_WATER, description="Nombre de jours consécutifs sans eau potable")
    total_students: int = Field(DEFAULT_EQUITY_TOTAL_STUDENTS, description="Effectif total d'élèves")
    female_students: int = Field(DEFAULT_EQUITY_FEMALE_STUDENTS, description="Nombre de jeunes filles scolarisées")
    broken_toilets: int = Field(DEFAULT_EQUITY_BROKEN_TOILETS, description="Nombre de latrines hors d'usage")
    months_since_last_intervention: int = Field(DEFAULT_EQUITY_MONTHS_SINCE_INTERVENTION, description="Mois écoulés depuis la dernière aide publique")
    urgency_level: Literal["low", "medium", "high", "critical"] = DEFAULT_EQUITY_URGENCY
    issue_summary: str = Field(DEFAULT_EQUITY_ISSUE_SUMMARY, description="Description succincte de la panne")
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
    language: str = DEFAULT_LANGUAGE
    language_effective: str = DEFAULT_LANGUAGE
    language_detected: str | None = None
    detection: dict[str, Any] = Field(default_factory=dict)
    driver: str | None = None
    duration_seconds: float | None = None
    # Pivot FR déterministe (pont bbj) quand la langue est ghomala' :
    # l'extraction/triage travaille sur le pivot, le transcript reste
    # l'original (audit + validation par le locuteur natif).
    french_pivot: str | None = None
    bridge: dict[str, Any] | None = None


class VoiceSynthesisRequest(BaseModel):
    text: str
    voice: str = DEFAULT_TTS_VOICE
    language: str = DEFAULT_LANGUAGE


class VoiceSynthesisResponse(BaseModel):
    audio_base64: str
    mime_type: str = DEFAULT_TTS_MIME_TYPE
    text: str
    driver: str | None = None
    language_effective: str = DEFAULT_LANGUAGE
    fallback: bool = False
    notice: str | None = None


# ==========================================
# 9. Administration des Providers LLM
# ==========================================

class ProviderTestRequest(BaseModel):
    provider: str = Field(DEFAULT_LLM_PROVIDER, description="ollama ou openai_compatible")
    base_url: str = Field(..., description="URL de base du provider")
    model: str = Field(..., description="Modèle texte à tester")
    vision_model: str | None = None
    embed_model: str | None = None
    api_key: str | None = None
    timeout: float = DEFAULT_PROVIDER_TEST_TIMEOUT


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
    driver: str = Field(DEFAULT_STT_DRIVER, description="whisper_cpp, omnilingual_onnx ou cloud_whisper")
    base_url: str | None = None
    model: str | None = None
    tokens: str | None = None
    api_key: str | None = None
    language: str = Field(DEFAULT_LANGUAGE, description="Code langue (fr, dua_Latn, ...)")
    audio_base64: str = Field(..., description="Échantillon audio encodé en base64")
    filename: str = DEFAULT_STT_TEST_FILENAME
    timeout: float = DEFAULT_STT_TEST_TIMEOUT


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
    recent_incidents: list[dict[str, Any]] = Field(default_factory=list, description="Historique 12 mois pour tendances")
    maintenance_logs: list[dict[str, Any]] = Field(default_factory=list, description="Coûts de réparation pour tendances")
    teams: list[dict[str, Any]] = Field(default_factory=list, description="Équipes maintenance actives (dispatch IA)")
    equipment_costs: list[dict[str, Any]] = Field(default_factory=list, description="Référentiel prix sourcés (verdict neuf)")


class AgentChatRequest(BaseModel):
    message: str = Field(..., description="Message de l'utilisateur")
    history: list[ChatTurn] = Field(default_factory=list, description="Historique court de conversation")
    context: AgentContext = Field(default_factory=AgentContext, description="Données factuelles fournies par Laravel")
    guided: bool = Field(False, description="CANAL 3 : dialogue guidé vocal par slots pour les signalements")
    image_base64: str | None = Field(None, description="Photo jointe encodée en base64 (base64 décodé ≤ 10 Mo)")
    image_mime: str | None = Field(None, description="Type MIME de la photo (ex. 'image/jpeg')")

    @field_validator("image_base64")
    @classmethod
    def _check_image_size(cls, value: str | None) -> str | None:
        """Rejette les photos > 10 Mo (base64 décodé) ou au base64 invalide.

        Lève ValueError -> FastAPI répond 422, avant tout appel LLM.
        Un éventuel préfixe data-URL et les blancs sont ignorés pour la mesure.
        """
        if value is None:
            return None
        raw = value.strip()
        if raw.startswith("data:") and ";base64," in raw:
            raw = raw.split(";base64,", 1)[1]
        raw = "".join(raw.split())
        try:
            decoded_size = len(base64.b64decode(raw, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image_base64 invalide : base64 illisible") from exc
        if decoded_size > CHAT_IMAGE_MAX_BYTES:
            raise ValueError(
                f"image trop lourde : {decoded_size} octets décodés "
                f"(max {CHAT_IMAGE_MAX_BYTES}, soit 10 Mo)"
            )
        return value


# Source unique de vérité des types de cartes (AXE 7) : tout type émis
# par agent_loop.py, guidance.py ou un CARD_BUILDERS de app/tools/*
# DOIT figurer ici ; tout membre non émis DOIT figurer dans
# FRONTEND_RESERVED. Voir tests/test_card_contracts.py.
CardType = Literal[
    # Historiques documentés.
    "school_analysis",
    "school_ranking",
    "district_summary",
    "incident_detail",
    "report_confirmation",
    "action_confirmation",
    # Plugins (un par CARD_BUILDERS).
    "compare_schools",
    "epidemic_alerts",
    "document_briefing",
    "district_alerts",
    "saisie_assistee",
    "maintenance_team",
    "observatoire",
    "relances",
    "chantier_dossier",
    "mission_timeline",
    "capabilities_list",
    "offline_queue",
    "copilot_answer",
    "intervention_prep",
    # Codés en dur dans agent_loop._build_cards.
    "photo_analysis",
    "incident_timeline",
    "incident_picker",
    "briefing_deck",
    "territory_map",
    "trend_chart",
    "calendar_heatmap",
    "budget_compare",
    "maintenance_logs",
    # Divers.
    "guidance",
    "place_suggestions",
    # Dossier décideur (contrat inter-agents : Laravel persiste le base64
    # du poster et réécrit l'URL ; builds dans app/tools/dossier_decideur.py).
    "poster",
    "dossier_report",
    # Réservé frontend (accepté, jamais émis par le backend).
    "action_result",
]

# Membres de CardType acceptés mais jamais émis par le backend
# (rendus frontend existants, conservés pour compatibilité).
FRONTEND_RESERVED = frozenset({
    "report_confirmation", "action_result",
})


class PosterCardData(BaseModel):
    """Contrat inter-agents carte `poster` : affiche générée du dossier.

    Laravel persiste `image_base64` et réécrit l'URL ; un seul des deux
    champs image est renseigné (jamais inventé : None si génération en échec).
    """

    image_base64: str | None = Field(None, description="Affiche encodée en base64 (persistée par Laravel)")
    image_url: str | None = Field(None, description="URL réécrite par Laravel (None côté IA)")
    prompt: str = Field(..., description="Prompt FR factuel ayant généré l'affiche")
    caption: str = Field(..., description="Légende FR courte et factuelle")


class DossierReportSection(BaseModel):
    """Une section du rapport décideur : titre + corps markdown + chiffres."""

    heading: str = Field(..., description="Titre de la section")
    body_md: str = Field(..., description="Corps en markdown (chiffres vérifiés uniquement)")
    figures: list[dict[str, str]] = Field(default_factory=list, description="Chiffres [{label, value}]")


class DossierReportCardData(BaseModel):
    """Contrat inter-agents carte `dossier_report` : rapport structuré."""

    subject: str = Field(..., description="Sujet du dossier (périmètre)")
    period: str = Field(..., description="Période couverte (ou 'non communiqué')")
    sections: list[DossierReportSection] = Field(..., description="Sections décideur")


class AgentCard(BaseModel):
    type: str = Field(..., description="Type de carte, voir CardType (contrat verrouillé AXE 7)")
    title: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentChatResponse(BaseModel):
    answer: str
    tools_executed: list[str] = Field(default_factory=list)
    cards: list[AgentCard] = Field(default_factory=list)
    model_used: str = ""
    follow_ups: list[str] = Field(default_factory=list)


# ==========================================
# 12. Q&R Documentaire Sourcée (RAG)
# ==========================================
class RagAskRequest(BaseModel):
    question: str = Field(..., description="Question en langage naturel")
    k: int = Field(RAG_K_DEFAULT, ge=RAG_K_MIN, le=RAG_K_MAX, description="Nombre d'extraits à remonter")


class RagAskResponse(BaseModel):
    answer: str = Field(..., description="Réponse citant les manuels, ou abstention")
    sources: list[str] = Field(default_factory=list, description="Noms des .md cités")


# ==========================================
# 13. Veille Prédictive des Pannes Récurrentes
# ==========================================
class RecurrenceIncidentInput(BaseModel):
    issue_type: str = Field("other", description="Nature de la panne (leak, blockage, ...)")
    occurred_at: str | None = Field(None, description="Date ISO de la panne (ex: 2026-10-15)")


class RecurrenceWatchRequest(BaseModel):
    history: list[RecurrenceIncidentInput] = Field(default_factory=list)
    school: SchoolMaintenanceHistory | None = Field(
        None, description="Historique agrégé Laravel (repli si pas de détail)"
    )


class RecurrenceWatchResponse(BaseModel):
    risk: dict[str, Any]
    plan: dict[str, Any]
