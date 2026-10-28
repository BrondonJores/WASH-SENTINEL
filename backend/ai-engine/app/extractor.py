from __future__ import annotations

from typing import Any
from .providers import BaseLLMProvider
from .schemas import ExtractedWashIncident, WashExtractionResponse

WASH_SYSTEM_PROMPT = """
Tu es l'analyste expert de WASH Sentinel, une plateforme de surveillance et priorisation des pannes d'eau, hygiène et assainissement (WASH) dans les écoles.

Ta mission est d'analyser le signalement brut fourni par un enseignant, directeur ou citoyen (texte ou transcription vocale), et d'en extraire un objet JSON STRICT respectant scrupuleusement la structure suivante :

{
  "school_detected": "string ou null",
  "infrastructure_type": "water_point | toilets_latrines | handwashing | sewage_drainage | other",
  "issue_type": "leak | total_breakdown | contamination | blockage | dry_well | vandalism | other",
  "urgency_level": "low | medium | high | critical",
  "estimated_affected_students": integer (ex: 350, défaut 50 si non précisé),
  "health_hazard_risk": "low | medium | high | severe",
  "short_summary": "Résumé concis et factuel en français (1 à 2 phrases max)"
}

Règles impératives :
1. "critical" pour urgence si les latrines débordent ou absence totale d'eau pour toute l'école.
2. "severe" pour risque sanitaire si risque direct de choléra, contamination fécale ou eau polluée bue par les élèves.
3. Ne réponds RIEN d'autre que l'objet JSON. Pas d'introduction, pas de markdown.
"""


class WashExtractor:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def extract(self, raw_text: str, school_name: str | None = None) -> WashExtractionResponse:
        user_prompt = f"Signalement brut :\n\"\"\"\n{raw_text}\n\"\"\""
        if school_name:
            user_prompt += f"\nÉcole déclarée : {school_name}"

        raw_json = await self.llm.generate_json(user_prompt, WASH_SYSTEM_PROMPT)

        # Calcul automatique du score de priorité standardisé (0 à 100)
        priority_score = self.calculate_priority_score(raw_json)

        # Normalisation des données
        incident = ExtractedWashIncident(
            school_detected=raw_json.get("school_detected") or school_name,
            infrastructure_type=self._normalize_choice(
                raw_json.get("infrastructure_type"),
                ["water_point", "toilets_latrines", "handwashing", "sewage_drainage", "other"],
                "other"
            ),
            issue_type=self._normalize_choice(
                raw_json.get("issue_type"),
                ["leak", "total_breakdown", "contamination", "blockage", "dry_well", "vandalism", "other"],
                "total_breakdown"
            ),
            urgency_level=self._normalize_choice(
                raw_json.get("urgency_level"),
                ["low", "medium", "high", "critical"],
                "medium"
            ),
            estimated_affected_students=int(raw_json.get("estimated_affected_students") or 50),
            health_hazard_risk=self._normalize_choice(
                raw_json.get("health_hazard_risk"),
                ["low", "medium", "high", "severe"],
                "medium"
            ),
            short_summary=raw_json.get("short_summary") or raw_text[:120],
            recommended_priority_score=priority_score,
        )

        return WashExtractionResponse(
            data=incident,
            model_used=self.llm.model,
            confidence_score=0.92,
        )

    def calculate_priority_score(self, data: dict[str, Any]) -> float:
        """
        Formule multicritère déterministe (0 à 100) :
        - Urgence (Poids 35%)
        - Risque Sanitaire (Poids 35%)
        - Population scolaire impactée (Poids 30%)
        """
        urgency_weights = {"low": 10.0, "medium": 45.0, "high": 75.0, "critical": 100.0}
        hazard_weights = {"low": 10.0, "medium": 40.0, "high": 75.0, "severe": 100.0}

        urgency = str(data.get("urgency_level", "medium")).lower()
        hazard = str(data.get("health_hazard_risk", "medium")).lower()
        students = min(int(data.get("estimated_affected_students") or 50), 1000)

        u_score = urgency_weights.get(urgency, 45.0)
        h_score = hazard_weights.get(hazard, 40.0)
        s_score = (students / 1000.0) * 100.0

        score = (u_score * 0.35) + (h_score * 0.35) + (s_score * 0.30)
        return round(score, 1)

    def _normalize_choice(self, val: Any, allowed: list[str], fallback: str) -> str:
        s = str(val or "").strip().lower()
        return s if s in allowed else fallback
