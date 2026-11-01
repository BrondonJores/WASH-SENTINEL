"""Extraction WASH : appel LLM + filets de mots-clés de repli (fallback).

Les filets `_INFRA_KEYWORDS` / `_ISSUE_KEYWORDS` (français) et `_LOCAL_KEYWORDS`
(pidgin camerounais + douala, conservateur) ne servent qu'à normaliser les
réponses LLM hors-liste vers des catégories valides. Ils ne modifient ni le
prompt ni la formule de priorité `calculate_priority_score` (inchangée).
"""
from __future__ import annotations

import re
from typing import Any
from .prompts import is_small_model, render_extractor_prompt
from .providers import BaseLLMProvider
from .schemas import ExtractedWashIncident, WashExtractionResponse

#: Alias historique : rendu neutre du builder prompts.extractor_sections()
#: (sans few-shots par défaut, taille stable).
WASH_SYSTEM_PROMPT = render_extractor_prompt()


class WashExtractor:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm
        self.last_meta: dict[str, bool] = {"fallback_infra": False, "fallback_issue": False}

    async def extract(
        self,
        raw_text: str,
        school_name: str | None = None,
        meta: dict[str, bool] | None = None,
    ) -> WashExtractionResponse:
        user_prompt = f"Signalement brut :\n\"\"\"\n{raw_text}\n\"\"\""
        if school_name:
            user_prompt += f"\nÉcole déclarée : {school_name}"

        # Few-shots réservés aux petits modèles ; JSON réparé quand le
        # provider l'offre (repli generate_json brut sinon, ex. stubs).
        system_prompt = render_extractor_prompt(
            include_few_shots=is_small_model(getattr(self.llm, "model", "")))
        repaired = getattr(self.llm, "generate_json_repaired", None)
        if repaired is None:
            raw_json = await self.llm.generate_json(user_prompt, system_prompt)
        else:
            raw_json = await repaired(user_prompt, system_prompt)

        # Télémétrie (evals/métriques) : le LLM a-t-il répondu dans la liste,
        # ou le filet mots-clés a-t-il pris le relais ? Miroir exact de la
        # condition de _normalize_choice, sans toucher au scoring.
        fallback_infra = (
            str(raw_json.get("infrastructure_type") or "").strip().lower()
            not in ("water_point", "toilets_latrines", "handwashing", "sewage_drainage")
        )
        fallback_issue = (
            str(raw_json.get("issue_type") or "").strip().lower()
            not in ("leak", "total_breakdown", "contamination", "blockage", "dry_well", "vandalism")
        )
        self.last_meta = {"fallback_infra": fallback_infra, "fallback_issue": fallback_issue}
        if meta is not None:
            meta.update(self.last_meta)

        # Calcul automatique du score de priorité standardisé (0 à 100)
        priority_score = self.calculate_priority_score(raw_json)

        # --- Abstention honnête : provenance, unknowns, confiance calculée ---
        # Les valeurs normalisées ci-dessous sont STRICTEMENT inchangées
        # (mêmes filets, mêmes défauts) ; seule l'honnêteté affichée change.
        infra_valid = not fallback_infra
        issue_valid = not fallback_issue
        urgency_defaulted = (
            str(raw_json.get("urgency_level") or "").strip().lower()
            not in ("low", "medium", "high", "critical")
        )
        hazard_defaulted = (
            str(raw_json.get("health_hazard_risk") or "").strip().lower()
            not in ("low", "medium", "high", "severe")
        )
        students_raw = raw_json.get("estimated_affected_students")
        students_defaulted = not students_raw  # 0/None/manquant -> 50 (valeur inchangée)
        school_raw = raw_json.get("school_detected")
        school_missing = not (school_raw or school_name)
        infra_hit = self._infra_keyword_hit(raw_text)
        issue_hit = self._issue_keyword_hit(raw_text)
        blank = not raw_text.strip()
        off_topic = (
            not blank and not infra_hit and not issue_hit
            and not self._wash_cue_hit(raw_text)
        )

        unknowns: list[str] = []
        if not infra_valid:
            unknowns.append("infrastructure_guess")
        if not issue_valid:
            unknowns.append("issue_guess")
        if urgency_defaulted:
            unknowns.append("urgency_default")
        if students_defaulted:
            unknowns.append("affected_students_unknown")
        if school_missing:
            unknowns.append("school_unknown")
        if hazard_defaulted:
            unknowns.append("health_hazard_default")
        if blank:
            unknowns.append("empty_report")
        if off_topic:
            unknowns.append("off_topic_suspected")

        confidence = 0.90
        if not infra_valid:
            confidence -= 0.15
        if not issue_valid:
            confidence -= 0.15
        if urgency_defaulted:
            confidence -= 0.10
        if students_defaulted:
            confidence -= 0.10
        if blank or off_topic:
            confidence -= 0.20
        confidence = round(max(0.05, min(0.95, confidence)), 2)

        if blank:
            next_action = (
                "Fournissez un signalement (texte ou audio) : "
                "infrastructure, panne, école, nombre d'élèves."
            )
        elif off_topic:
            next_action = (
                "Le texte semble hors-sujet WASH : précisez infrastructure, "
                "panne, nombre d'élèves, école."
            )
        elif unknowns:
            labels = {
                "infrastructure_guess": "l'infrastructure concernée",
                "issue_guess": "la nature de la panne",
                "urgency_default": "le niveau d'urgence",
                "affected_students_unknown": "le nombre d'élèves impactés",
                "school_unknown": "l'école concernée",
                "health_hazard_default": "le risque sanitaire",
            }
            parts = [labels[u] for u in unknowns if u in labels]
            next_action = f"Précisez {', '.join(parts)} pour fiabiliser le diagnostic."
        else:
            next_action = ""

        provenance = {
            "school_detected": "llm" if school_raw else ("declared" if school_name else "unknown"),
            "infrastructure_type": "llm" if infra_valid else ("keyword" if infra_hit else "default"),
            "issue_type": "llm" if issue_valid else ("keyword" if issue_hit else "default"),
            "urgency_level": "default" if urgency_defaulted else "llm",
            "estimated_affected_students": "default" if students_defaulted else "llm",
            "health_hazard_risk": "default" if hazard_defaulted else "llm",
            "short_summary": "llm" if raw_json.get("short_summary") else "default",
        }

        # Normalisation des données (valeurs inchangées, cf. goldens)
        incident = ExtractedWashIncident(
            school_detected=raw_json.get("school_detected") or school_name,
            infrastructure_type=self._normalize_choice(
                raw_json.get("infrastructure_type"),
                ["water_point", "toilets_latrines", "handwashing", "sewage_drainage"],
                self._guess_infrastructure(raw_text)
            ),
            issue_type=self._normalize_choice(
                raw_json.get("issue_type"),
                ["leak", "total_breakdown", "contamination", "blockage", "dry_well", "vandalism"],
                self._guess_issue(raw_text)
            ),
            urgency_level=self._normalize_choice(
                raw_json.get("urgency_level"),
                ["low", "medium", "high", "critical"],
                "medium"
            ),
            estimated_affected_students=int(raw_json.get("estimated_affected_students") or 50),
            students_unknown=students_defaulted,
            is_wash_related=None if blank else (False if off_topic else True),
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
            confidence_score=confidence,
            unknowns=unknowns,
            next_action=next_action,
            field_provenance=provenance,
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

    _INFRA_KEYWORDS = (
        (("latrine", "wc", "toilette"), "toilets_latrines"),
        (("lave-main", "lavage des mains", "lave mains"), "handwashing"),
        (("égout", "egout", "drain", "caniveau", "évacuation", "evacuation", "fosse"), "sewage_drainage"),
    )
    _ISSUE_KEYWORDS = (
        (("bouch", "déborde", "deborde", "engorg"), "blockage"),
        (("plus d'eau", "pas d'eau", "coupure", "coupé", "coupe", "à sec", "a sec", "tari", "asséch"), "dry_well"),
        (("cass", "panne", "hors service", "ne marche", "ne fonctionne", "ne coule"), "total_breakdown"),
        (("fuit", "coule", "goutte", "perce", "percé"), "leak"),
        (("volé", "volée", "vandalis", "saccag", "détruit", "disparu"), "vandalism"),
        (("eau jaune", "eau sale", "saleté", "contamin", "choléra", "cholera", "pollu", "trouble", "couleur"), "contamination"),
    )
    # Filet langues locales — CONSERVATEUR : uniquement des termes haute-confiance.
    # Règle : en cas de doute sur un mot, NE PAS l'ajouter. Chaque entrée indique
    # langue + confiance. Consulté APRÈS le filet français (priorité au français).
    _LOCAL_KEYWORDS = (
        # Pidgin camerounais — confiance HAUTE : « toilet » = toilettes/latrines.
        (("toilet",), "toilets_latrines"),
        # Pidgin camerounais — confiance HAUTE : « wata » = eau → point d'eau.
        (("wata",), "water_point"),
        # Douala — terme NOTOIRE pour l'eau → point d'eau.
        # AVERTISSEMENT : validation par locuteur recommandée avant élargissement.
        (("madiba",), "water_point"),
    )

    def _guess_infrastructure(self, raw_text: str) -> str:
        """Filet FR d'abord, puis filet local conservateur, sinon « water_point ».

        L'ordre du filet français est inchangé (non-régression) : le filet
        local ne s'applique qu'aux textes sans mot-clé français reconnu.
        """
        t = raw_text.lower()
        for keywords, value in self._INFRA_KEYWORDS:
            if any(k in t for k in keywords):
                return value
        for keywords, value in self._LOCAL_KEYWORDS:
            if any(k in t for k in keywords):
                return value
        return "water_point"

    def _guess_issue(self, raw_text: str) -> str:
        t = raw_text.lower()
        for keywords, value in self._ISSUE_KEYWORDS:
            if any(k in t for k in keywords):
                return value
        return "total_breakdown"

    def _normalize_choice(self, val: Any, allowed: list[str], fallback: str) -> str:
        s = str(val or "").strip().lower()
        return s if s in allowed else fallback

    # Indices WASH larges (hors-sujet uniquement) : ne servent NI au filet
    # (tables et ordre ci-dessus inchangés) NI aux valeurs, seulement au
    # drapeau off_topic_suspected. « eau » est testé en mot entier (regex)
    # pour ne pas matcher « tableau », « beau »...
    _WASH_CUES = (
        "wata", "madiba", "sanitaire", "hygiène", "hygiene", "robinet",
        "pompe", "forage", "puits", "fontaine", "château", "chateau",
        "douche", "savon", "tuyau", "conduit", "cuve", "nappe",
        "choléra", "cholera", "diarrhée", "diarrhee", "latrine",
        "toilette", "égout", "egout", "caniveau", "fosse", "fuite",
        "boue", "lavage", "évacuation", "evacuation", "assainissement",
        "eaux", "water", "borehole", "sanitation",
    )

    def _infra_keyword_hit(self, raw_text: str) -> bool:
        """True si le filet infra aurait matché (lecture seule des tables)."""
        t = raw_text.lower()
        tables = (*self._INFRA_KEYWORDS, *self._LOCAL_KEYWORDS)
        return any(k in t for keywords, _ in tables for k in keywords)

    def _issue_keyword_hit(self, raw_text: str) -> bool:
        """True si le filet panne aurait matché (lecture seule des tables)."""
        t = raw_text.lower()
        return any(k in t for keywords, _ in self._ISSUE_KEYWORDS for k in keywords)

    def _wash_cue_hit(self, raw_text: str) -> bool:
        """True si un indice WASH large est présent (anti-faux-hors-sujet)."""
        t = raw_text.lower()
        if re.search(r"\beau\b", t):
            return True
        return any(k in t for k in self._WASH_CUES)
