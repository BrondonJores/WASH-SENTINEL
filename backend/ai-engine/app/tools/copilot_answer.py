"""Plugin conseil stratégique générique (copilote) : budget, priorités, que faire.

Outil de CONSEIL, pas de lecture brute : heuristique déterministe (zéro LLM,
zéro réseau) qui détecte l'école citée (correspondance floue sur les noms
connus) et le sujet (budget / pannes récurrentes / général), puis produit
une synthèse chiffrée avec une recommandation.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from ..decision_agent import (
    DECISION_MONITOR_MIN_INCIDENTS,
    DECISION_MONITOR_MIN_RATIO_PCT,
    DECISION_REPLACE_MIN_DAYS_OFF,
    DECISION_REPLACE_MIN_INCIDENTS,
    DECISION_REPLACE_MIN_RATIO_PCT,
)
from ..schemas import AgentCard

TOOL_NAME = "copilot_answer"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Donne un CONSEIL stratégique générique : budget à prévoir, priorités "
        "d'action, que faire face à des pannes. À utiliser quand l'utilisateur "
        "demande un avis, une recommandation ou une orientation et qu'AUCUN "
        "autre outil ne correspond. "
        "Exemple : 'Quel budget prévoir pour l'eau des écoles ?' -> copilot_answer. "
        "Ne JAMAIS utiliser pour lister, résumer ou comparer des données brutes "
        "(écoles, incidents, journaux : utiliser les outils de lecture)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Question de conseil de l'utilisateur (budget, priorités, que faire).",
            },
        },
        "required": ["question"],
    },
}

READ_ONLY = True

# Indices minuscules, formes sans-accent doublées (comparaison par sous-chaîne
# dans route_intent). Exempts de tout phrasé legacy ("faut-il", "réparer",
# "remplacer", ...) pour ne jamais détourner les questions analyze_school.
INTENT_HINTS = frozenset({
    "conseil", "conseille", "conseiller",
    "recommandation", "recommande",
    "avis",
    "ton avis", "votre avis", "quel avis",
    "que faire", "quoi faire",
    "dois-je", "dois je", "doit-on", "doit on",
    "strategie", "stratégie",
    "budget",
    "priorite", "priorité",
    "par ou commencer", "par où commencer",
    "suggere", "suggère", "suggestion",
    "opinion",
})

_BUDGET_KEYS = (
    "budget", "cout", "depens", "financ", "xaf", "fcfa",
    "enveloppe", "argent", "credit",
)

_RECURRENCE_KEYS = (
    "recurrent", "recidiv", "frequent", "panne", "souvent", "repetition",
)

# Mots génériques ignorés pour la détection d'école (le nom distinctif compte).
_SCHOOL_STOPWORDS = frozenset({
    "ecole", "lycee", "college", "groupe", "scolaire", "primaire",
    "maternel", "municipal", "public", "prive", "bilingue", "de", "la",
    "le", "les", "du", "des", "d", "l",
})

_RECO_LABELS = {
    "REPLACE": "prévoir le changement de l'équipement",
    "MONITOR": "renforcer la surveillance de l'équipement",
    "MAINTAIN": "poursuivre la maintenance courante",
    "PRIORITIZE": "traiter l'école la plus touchée en priorité",
}

# --- LOT 3 : constantes locales (valeurs historiques inchangées) ---
# Les seuils d'arbitrage (_recommend) sont IMPORTÉS de decision_agent
# (source unique, zéro recopie) ; ci-dessous les réglages propres au plugin.

#: Longueur min d'un token distinctif pour citer une école (anti-bruit).
SCHOOL_TOKEN_MIN_LEN = 4

#: Enveloppe budget : remplacement = coût ×1.2 (marge), sinon coût ×0.5
#: avec plancher 100 000 XAF (maintenance préventive minimale).
BUDGET_REPLACE_MARGIN = 1.2
BUDGET_MAINTAIN_FRACTION = 0.5
BUDGET_MIN_ENVELOPE_XAF = 100000.0

#: Catégorie du catalogue prix utilisée pour le coût de remplacement d'une
#: école (son point d'eau). Repli : médiane toutes catégories confondues.
CATALOGUE_REPLACEMENT_CATEGORY = "water_point"

#: Origines possibles du coût de remplacement (figures["replacement_source"]).
REPLACEMENT_SOURCE_ECOLE = "ecole"
REPLACEMENT_SOURCE_REFERENTIEL = "referentiel"
REPLACEMENT_SOURCE_DEFAUT = "defaut"


def _norm(text: Any) -> str:
    """Minuscules sans accents (comparaisons floues déterministes)."""
    raw = unicodedata.normalize("NFKD", str(text or ""))
    return raw.encode("ascii", "ignore").decode("ascii").lower()


def _fmt_xaf(value: Any) -> str:
    try:
        return f"{int(float(value or 0)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _detect_school(question_norm: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """École du contexte citée dans la question (nom complet ou mot distinctif).

    Duplique localement la correspondance floue des exécuteurs historiques
    (contrat plugin : pas d'import de app.agent_tools).
    """
    schools = context.get("schools", [])
    if not isinstance(schools, list):
        return None
    best: dict[str, Any] | None = None
    best_len = 0
    for school in schools:
        if not isinstance(school, dict):
            continue
        name_norm = _norm(school.get("school_name")).strip()
        if not name_norm:
            continue
        if name_norm in question_norm and len(name_norm) > best_len:
            best, best_len = school, len(name_norm)
            continue
        for token in name_norm.replace("-", " ").split():
            if len(token) >= SCHOOL_TOKEN_MIN_LEN and token not in _SCHOOL_STOPWORDS:
                if token in question_norm and len(token) > best_len:
                    best, best_len = school, len(token)
    return best


def _detect_topic(question_norm: str) -> str:
    if any(key in question_norm for key in _BUDGET_KEYS):
        return "budget"
    if any(key in question_norm for key in _RECURRENCE_KEYS):
        return "recurrence"
    return "general"


def _recommend(incident_count: int, ratio: float, days: int) -> str:
    """Arbitrage calqué sur la règle DecisionAgent : >= 4 pannes -> REPLACE.

    Seuils IMPORTÉS de decision_agent (source unique, zéro recopie).
    """
    if incident_count >= DECISION_REPLACE_MIN_INCIDENTS or ratio >= DECISION_REPLACE_MIN_RATIO_PCT or days >= DECISION_REPLACE_MIN_DAYS_OFF:
        return "REPLACE"
    if incident_count >= DECISION_MONITOR_MIN_INCIDENTS or ratio >= DECISION_MONITOR_MIN_RATIO_PCT:
        return "MONITOR"
    return "MAINTAIN"


def _catalogue_median(
    catalogue: Any, category: str | None,
) -> tuple[float, list[str]]:
    """Médiane des milieux de fourchette + noms de sources (déterministe).

    Ne lit que le contexte (zéro réseau) : chaque ligne porte category,
    min_xaf, max_xaf et source_name. category=None = toutes catégories.
    """
    midpoints: list[float] = []
    sources: list[str] = []
    if not isinstance(catalogue, list):
        return 0.0, []
    for row in catalogue:
        if not isinstance(row, dict):
            continue
        if category is not None and row.get("category") != category:
            continue
        lo, hi = _as_float(row.get("min_xaf")), _as_float(row.get("max_xaf"))
        if lo <= 0 or hi <= 0:
            continue
        midpoints.append((lo + hi) / 2.0)
        name = str(row.get("source_name") or "").strip()
        if name and name not in sources:
            sources.append(name)
    if not midpoints:
        return 0.0, []
    ordered = sorted(midpoints)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
    return median, sources


def _replacement_with_source(
    school: dict[str, Any], context: dict[str, Any],
) -> tuple[float, str, list[str]]:
    """Coût de remplacement effectif + son origine (ecole/referentiel/defaut).

    Coût école inchangé dès qu'il est renseigné (> 0). À 0, médiane du
    catalogue (catégorie point d'eau, sinon toutes catégories) fournie par
    le parent dans context["equipment_costs"] ; sans catalogue : défaut.
    """
    school_cost = _as_float(school.get("estimated_replacement_cost"))
    if school_cost > 0:
        return school_cost, REPLACEMENT_SOURCE_ECOLE, []
    catalogue = context.get("equipment_costs", [])
    median, sources = _catalogue_median(catalogue, CATALOGUE_REPLACEMENT_CATEGORY)
    if median <= 0:
        median, sources = _catalogue_median(catalogue, None)
    if median > 0:
        return median, REPLACEMENT_SOURCE_REFERENTIEL, sources
    return 0.0, REPLACEMENT_SOURCE_DEFAUT, []


def _open_count_for(context: dict[str, Any], school_id: Any) -> int:
    incidents = context.get("incidents", [])
    if not isinstance(incidents, list):
        return 0
    return sum(
        1 for i in incidents
        if isinstance(i, dict)
        and i.get("school_id") == school_id
        and i.get("status") not in ("resolved", "closed")
    )


def _advise_school(
    school: dict[str, Any], topic: str, context: dict[str, Any],
) -> dict[str, Any]:
    name = str(school.get("school_name") or "cette école")
    count = _as_int(school.get("incident_count"))
    cost = _as_float(school.get("total_repair_cost"))
    days = _as_int(school.get("total_days_without_service"))
    replacement, replacement_source, replacement_names = _replacement_with_source(school, context)
    ratio = round(cost / replacement * 100.0, 1) if replacement > 0 else 0.0
    opened = _open_count_for(context, school.get("school_id"))
    reco = _recommend(count, ratio, days)
    label = _RECO_LABELS[reco]

    if topic == "budget":
        envelope = max(replacement, cost * BUDGET_REPLACE_MARGIN) if reco == "REPLACE" else max(cost * BUDGET_MAINTAIN_FRACTION, BUDGET_MIN_ENVELOPE_XAF)
        insight = (
            f"{name} cumule {_fmt_xaf(cost)} XAF de dépenses pour {count} pannes, "
            f"soit {ratio} % du coût d'un équipement neuf ({_fmt_xaf(replacement)} XAF). "
            f"Je conseille de provisionner environ {_fmt_xaf(envelope)} XAF pour ce site. "
            f"Recommandation : {label}."
        )
    elif topic == "recurrence":
        insight = (
            f"{name} subit des pannes à répétition : {count} pannes et {days} jours "
            f"sans service au total, dont {opened} incidents encore ouverts. "
            f"Avec {count} pannes (seuil de {DECISION_REPLACE_MIN_INCIDENTS} atteint : {('oui' if count >= DECISION_REPLACE_MIN_INCIDENTS else 'non')}), "
            f"les dépannages répétés coûtent plus cher qu'une solution durable. "
            f"Recommandation : {label}."
        )
    else:
        insight = (
            f"{name} : {count} pannes, {_fmt_xaf(cost)} XAF dépensés et {days} jours "
            f"sans service, avec {opened} incidents encore ouverts. "
            f"Le ratio dépenses / équipement neuf atteint {ratio} %. "
            f"Recommandation : {label}."
        )
    if replacement_source == REPLACEMENT_SOURCE_REFERENTIEL:
        cited = ", ".join(replacement_names[:2]) if replacement_names else "référentiel national"
        insight += (
            f" Coût d'un équipement neuf estimé via le référentiel national "
            f"(médiane {_fmt_xaf(replacement)} XAF, sources : {cited})."
        )
    return {
        "insight": insight,
        "recommendation": reco,
        "recommendation_label": label,
        "topic": topic,
        "school_id": school.get("school_id"),
        "school_name": school.get("school_name"),
        "figures": {
            "incident_count": count,
            "total_repair_cost": cost,
            "total_days_without_service": days,
            "estimated_replacement_cost": replacement,
            "replacement_source": replacement_source,
            "repair_ratio_percent": ratio,
            "open_incidents": opened,
        },
    }


def _advise_global(question_norm: str, context: dict[str, Any]) -> dict[str, Any]:
    schools = [s for s in context.get("schools", []) if isinstance(s, dict)]
    incidents = [i for i in context.get("incidents", []) if isinstance(i, dict)]
    opened = [i for i in incidents if i.get("status") not in ("resolved", "closed")]
    total_cost = sum(_as_float(s.get("total_repair_cost")) for s in schools)
    total_days = sum(_as_int(s.get("total_days_without_service")) for s in schools)
    top = max(schools, key=lambda s: _as_int(s.get("incident_count")), default=None)
    top_name = str(top.get("school_name")) if top else None
    topic = _detect_topic(question_norm)

    first = (
        f"Sur {len(schools)} écoles suivies, {len(opened)} incidents restent ouverts "
        f"pour {_fmt_xaf(total_cost)} XAF de dépenses cumulées et {total_days} jours sans service."
    )
    if top is not None and _as_int(top.get("incident_count")) > 0:
        second = (
            f"Le site le plus touché est {top_name} "
            f"({_as_int(top.get('incident_count'))} pannes, "
            f"{_fmt_xaf(_as_float(top.get('total_repair_cost')))} XAF)."
        )
    else:
        second = "Aucun site ne concentre les pannes pour le moment."
    third = (
        "Je conseille de flécher le prochain budget vers ce site avant tout."
        if top_name
        else "Je conseille de garder une enveloppe de maintenance préventive."
    )
    return {
        "insight": f"{first} {second} {third}",
        "recommendation": "PRIORITIZE",
        "recommendation_label": _RECO_LABELS["PRIORITIZE"],
        "topic": topic,
        "school_id": None,
        "school_name": None,
        "focus_school": top_name,
        "figures": {
            "schools": len(schools),
            "open_incidents": len(opened),
            "total_repair_cost": total_cost,
            "total_days_without_service": total_days,
        },
    }


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Conseil stratégique déterministe : école citée + sujet + chiffres."""
    try:
        if not isinstance(args, dict) or not isinstance(context, dict):
            return {"error": "Arguments ou contexte invalide."}
        question = str((args or {}).get("question") or "").strip()
        if not question:
            return {
                "error": (
                    "Question manquante : précisez votre besoin "
                    "(ex. « Quel budget prévoir pour les écoles de Douala ? »)."
                ),
            }
        question_norm = _norm(question)
        school = _detect_school(question_norm, context)
        if school is not None:
            return _advise_school(school, _detect_topic(question_norm), context)
        return _advise_global(question_norm, context)
    except Exception as exc:  # contrat : jamais d'exception vers la boucle
        return {"error": f"copilot_answer indisponible : {exc}"}


def _build_copilot_answer_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict):
        return None
    if obs.get("error"):
        return None
    if not obs.get("insight") or not obs.get("recommendation"):
        return None
    title = "Conseil Copilote"
    if obs.get("school_name"):
        title = f"Conseil — {obs.get('school_name')}"
    return AgentCard(
        type="copilot_answer",
        title=title,
        data=obs,
    )


CARD_BUILDERS = {"copilot_answer": _build_copilot_answer_card}
