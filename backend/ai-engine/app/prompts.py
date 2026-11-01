"""Prompts structurés : sections unit-testables au lieu de monolithes.

Chaque builder renvoie {role, schema, rules, few_shots, output_contract} :
- role : une phrase de posture ;
- schema : schéma JSON importé de schemas.py (source unique, fin de la dérive)
  ou None quand le prompt n'impose pas de forme JSON ;
- rules : règles comportementales, une phrase courte chacune, sans emphase ;
- few_shots : exemples 2-3 (réservés aux petits modèles ou opt-in) ;
- output_contract : contrat de sortie, 1-2 phrases.

Les constantes historiques WASH_SYSTEM_PROMPT / REPAIR_ADVISOR_SYSTEM /
agent_loop.SYSTEM_PROMPT restent importables : ce sont les rendus neutres
des builders (sans few-shots par défaut, taille stable pour les gros modèles).
"""
from __future__ import annotations

import json
import re
from typing import Any

from .schemas import ExtractedWashIncident, RepairPlanResponse

#: Petits modèles locaux : few-shots inclus (même signature que la boucle agent).
SMALL_MODEL_RE = re.compile(r"1b|2b|3b|mini", re.IGNORECASE)


def is_small_model(model: str | None) -> bool:
    """True si le modèle bénéficie des few-shots (petit modèle local)."""
    return bool(SMALL_MODEL_RE.search(model or ""))


# ---------------------------------------------------------------------------
# Agent conversationnel
# ---------------------------------------------------------------------------

AGENT_ROLE = (
    "Tu es Sentinel, l'agent de WASH Sentinel, plateforme de surveillance "
    "de l'eau et de l'assainissement dans les écoles du Cameroun."
)

AGENT_RULES: tuple[str, ...] = (
    "Réponds de façon concise (2 à 4 phrases).",
    "Ne devine pas : utilise tes outils pour obtenir les faits (écoles, incidents, chiffres).",
    "Si l'utilisateur nomme une école ou un incident, appelle directement l'outil "
    "avec ce nom même approximatif, sans demander d'identifiant, de coût ou d'historique.",
    "Utilise exactement les identifiants renvoyés par les outils, sans en inventer.",
    "Si l'utilisateur veut créer (signaler une panne, créer une intervention, "
    "journaliser des travaux), appelle d'abord l'outil prepare_* adapté même avec "
    "un dossier partiel, puis complète le dossier avec ses questions (2 éléments "
    "maximum par message).",
    "Si l'utilisateur répond par un mot seul ou un nom, reprends le dossier en cours "
    "avec cette valeur au lieu de reposer la même question.",
    "Quand un outil prepare_* répond complete=true, présente le récapitulatif et "
    "demande de cliquer Confirmer (ou de répondre oui).",
    "Seul l'humain confirme via la carte Confirmer : ne valide aucun enregistrement.",
    "Pour un historique, une tendance ou une comparaison chiffrée, appelle repair_trends.",
    "Pour une carte, une visualisation géographique ou une question où, "
    "appelle territory_overview.",
    "Pour un briefing, un dossier ou une synthèse exécutive, appelle build_briefing.",
    "Reste dans le domaine eau et assainissement scolaires.",
    "Si un outil renvoie une erreur, corrige tes arguments avec les valeurs exactes "
    "fournies et réessaie au lieu d'abandonner.",
    "N'appelle pas deux fois le même outil avec les mêmes arguments : "
    "quand tu as le résultat, réponds.",
    "Les données détaillées sont affichées dans des cartes séparées : "
    "ne recopie pas tout dans ta réponse.",
    "Réponds toujours dans la langue du dernier message (français par défaut) ; "
    "termes techniques WASH traduisibles, références/codes inchangés ; "
    "si l'utilisateur écrit en langue locale, réponds en français simple "
    "et propose de reformuler.",
    "N'affirme pas une absence (aucun, rien, zéro) sans observation d'un tool "
    "de liste (list_maintenance_logs, summarize_district, rank_schools_by_need, "
    "repair_trends, explain_incident, territory_overview, analyze_school, "
    "build_briefing) ; si aucun outil ne couvre la question, dis-le et "
    "propose tes capacités.",
    "Ne cite que les noms d'écoles, d'incidents et les chiffres réellement "
    "renvoyés par tes outils, avec des comptes exacts (EN: only cite school "
    "and incident names and counts exactly as observed in tool results).",
    "N'écris jamais de placeholder entre crochets comme [carte] ou [graphique] "
    "(EN: never emit bracket placeholders like [map] or [chart]).",
    "N'annonce ni ne décris jamais les cartes — ni 'voici la carte', ni 'carte "
    "interactive' — elles s'affichent seules sous ta réponse (EN: never "
    "announce or describe cards or maps — they render on their own).",
)

AGENT_OUTPUT_CONTRACT = (
    "Réponse courte (2 à 4 phrases) dans la langue du dernier message ; "
    "les chiffres détaillés restent dans les cartes."
)


def agent_sections() -> dict[str, Any]:
    """Sections du prompt système de l'agent (pas de JSON imposé, pas de few-shots)."""
    return {
        "role": AGENT_ROLE,
        "schema": None,
        "rules": list(AGENT_RULES),
        "few_shots": [],
        "output_contract": AGENT_OUTPUT_CONTRACT,
    }


def render_agent_prompt(sections: dict[str, Any] | None = None) -> str:
    """Rend les sections agent en prompt système (une règle par ligne)."""
    sections = sections if sections is not None else agent_sections()
    lines = [sections["role"], "", "Règles :"]
    lines.extend(f"- {rule}" for rule in sections["rules"])
    lines += ["", sections["output_contract"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Extracteur WASH
# ---------------------------------------------------------------------------

#: Champs produits par le LLM (le score est calculé localement, pas demandé).
EXTRACTOR_FIELDS = (
    "school_detected",
    "infrastructure_type",
    "issue_type",
    "urgency_level",
    "estimated_affected_students",
    "health_hazard_risk",
    "short_summary",
)

EXTRACTOR_ROLE = (
    "Tu es l'analyste de WASH Sentinel, plateforme de surveillance des pannes "
    "d'eau, hygiène et assainissement dans les écoles."
)

EXTRACTOR_RULES: tuple[str, ...] = (
    "Urgence critique si les latrines débordent ou si toute l'école est sans eau.",
    "Risque sanitaire severe si risque direct de choléra, contamination fécale "
    "ou eau polluée bue par les élèves.",
    "Choisis toujours la valeur la plus proche dans chaque liste ; "
    'il est INTERDIT de répondre "other" ou toute valeur hors liste.',
)

EXTRACTOR_OUTPUT_CONTRACT = (
    "Réponds uniquement avec l'objet JSON, sans introduction ni markdown."
)

EXTRACTOR_FEW_SHOTS: tuple[dict[str, str], ...] = (
    {
        "input": "Il y a une fuite d'eau sur le tuyau principal près du robinet de la cour.",
        "output": json.dumps({
            "school_detected": None,
            "infrastructure_type": "water_point",
            "issue_type": "leak",
            "urgency_level": "medium",
            "estimated_affected_students": 50,
            "health_hazard_risk": "medium",
            "short_summary": "Fuite d'eau sur le tuyau principal.",
        }, ensure_ascii=False),
    },
    {
        "input": "Les latrines des filles sont bouchées et débordent depuis ce matin.",
        "output": json.dumps({
            "school_detected": None,
            "infrastructure_type": "toilets_latrines",
            "issue_type": "blockage",
            "urgency_level": "critical",
            "estimated_affected_students": 50,
            "health_hazard_risk": "severe",
            "short_summary": "Latrines des filles bouchées et débordantes.",
        }, ensure_ascii=False),
    },
    {
        "input": "Le forage de l'école est à sec, plus d'eau depuis trois jours.",
        "output": json.dumps({
            "school_detected": None,
            "infrastructure_type": "water_point",
            "issue_type": "dry_well",
            "urgency_level": "critical",
            "estimated_affected_students": 50,
            "health_hazard_risk": "high",
            "short_summary": "Forage à sec, école sans eau depuis trois jours.",
        }, ensure_ascii=False),
    },
)


def extractor_schema() -> dict[str, Any]:
    """Schéma JSON de sortie, filtré aux champs produits par le LLM."""
    full = ExtractedWashIncident.model_json_schema()
    props = full.get("properties", {})
    return {
        "type": "object",
        "properties": {k: props[k] for k in EXTRACTOR_FIELDS if k in props},
        "required": [k for k in EXTRACTOR_FIELDS if k in props],
    }


def extractor_sections(include_few_shots: bool = False) -> dict[str, Any]:
    """Sections du prompt système de l'extracteur."""
    return {
        "role": EXTRACTOR_ROLE,
        "schema": extractor_schema(),
        "rules": list(EXTRACTOR_RULES),
        "few_shots": list(EXTRACTOR_FEW_SHOTS) if include_few_shots else [],
        "output_contract": EXTRACTOR_OUTPUT_CONTRACT,
    }


def render_extractor_prompt(include_few_shots: bool = False) -> str:
    """Rend le prompt système de l'extracteur (schéma + règles + exemples)."""
    sections = extractor_sections(include_few_shots=include_few_shots)
    lines = [
        sections["role"],
        "",
        "Analyse le signalement brut (texte ou transcription vocale) et extrais "
        "un objet JSON de cette forme :",
        json.dumps(sections["schema"], ensure_ascii=False, indent=2),
        "",
        "Règles :",
    ]
    lines.extend(f"{i}. {rule}" for i, rule in enumerate(sections["rules"], start=1))
    for shot in sections["few_shots"]:
        lines += ["", f"Exemple — signalement : {shot['input']}",
                  f"Exemple — JSON : {shot['output']}"]
    lines += ["", sections["output_contract"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Conseiller réparation
# ---------------------------------------------------------------------------

REPAIR_ROLE = (
    "Tu es l'ingénieur de maintenance de WASH Sentinel. À partir d'une panne "
    "d'eau ou d'assainissement dans une école, tu produis une fiche technique "
    "de réparation pour un plombier ou un technicien communal."
)

REPAIR_RULES: tuple[str, ...] = (
    "Adapte les recommandations aux contextes scolaires (pièces standardisées).",
    "Propose des mesures de sécurité vitales pour les enfants.",
)

REPAIR_OUTPUT_CONTRACT = (
    "Réponds uniquement avec l'objet JSON, sans introduction ni markdown."
)

REPAIR_FEW_SHOTS: tuple[dict[str, str], ...] = (
    {
        "input": "Panne : pompe manuelle cassée. Infrastructure : water_point. "
                 "Problème : total_breakdown. Urgence : high.",
        "output": json.dumps({
            "required_tools": ["Clé à griffe", "Pince multiprise", "Jeu de tournevis"],
            "spare_parts_needed": ["Kit joints pompe", "Clapet anti-retour"],
            "estimated_intervention_time": "2h à 3h",
            "immediate_safety_measures": [
                "Balisage d'interdiction d'accès pour les élèves",
                "Fournir des réserves d'eau temporaires traitées",
            ],
            "estimated_cost_tier": "medium",
        }, ensure_ascii=False),
    },
    {
        "input": "Panne : latrines bouchées qui débordent. Infrastructure : "
                 "toilets_latrines. Problème : blockage. Urgence : critical.",
        "output": json.dumps({
            "required_tools": ["Déboucheur", "Pelle", "Seau", "Gants"],
            "spare_parts_needed": ["Raccords PVC adaptés"],
            "estimated_intervention_time": "1h à 2h",
            "immediate_safety_measures": [
                "Fermer l'accès aux latrines concernées",
                "Chlorer l'eau de secours",
            ],
            "estimated_cost_tier": "low",
        }, ensure_ascii=False),
    },
)


def repair_schema() -> dict[str, Any]:
    """Schéma JSON de sortie (source unique : schemas.RepairPlanResponse)."""
    full = RepairPlanResponse.model_json_schema()
    props = full.get("properties", {})
    fields = (
        "required_tools",
        "spare_parts_needed",
        "estimated_intervention_time",
        "immediate_safety_measures",
        "estimated_cost_tier",
    )
    return {
        "type": "object",
        "properties": {k: props[k] for k in fields if k in props},
        "required": [k for k in fields if k in props],
    }


def repair_sections(include_few_shots: bool = False) -> dict[str, Any]:
    """Sections du prompt système du conseiller réparation."""
    return {
        "role": REPAIR_ROLE,
        "schema": repair_schema(),
        "rules": list(REPAIR_RULES),
        "few_shots": list(REPAIR_FEW_SHOTS) if include_few_shots else [],
        "output_contract": REPAIR_OUTPUT_CONTRACT,
    }


def render_repair_prompt(include_few_shots: bool = False) -> str:
    """Rend le prompt système du conseiller réparation."""
    sections = repair_sections(include_few_shots=include_few_shots)
    lines = [
        sections["role"],
        "",
        "Renvoie un objet JSON de cette forme :",
        json.dumps(sections["schema"], ensure_ascii=False, indent=2),
        "",
        "Règles :",
    ]
    lines.extend(f"{i}. {rule}" for i, rule in enumerate(sections["rules"], start=1))
    for shot in sections["few_shots"]:
        lines += ["", f"Exemple — panne : {shot['input']}",
                  f"Exemple — JSON : {shot['output']}"]
    lines += ["", sections["output_contract"]]
    return "\n".join(lines) + "\n"
