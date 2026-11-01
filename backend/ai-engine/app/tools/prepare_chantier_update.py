"""Plugin écriture : dossier de suivi de chantier/intervention (SANS écriture).

PRÉPARE un dossier de suivi de chantier — avancement %, étape, photos
annoncées (via notes), coût, notes — SANS RIEN ÉCRIRE. L'enregistrement
réel n'a lieu qu'après confirmation humaine (carte Confirmer).
"""
from __future__ import annotations

import difflib
from typing import Any

from ..schemas import AgentCard
from ..tool_consts import INCIDENT_FUZZY_MIN_RATIO

TOOL_NAME = "prepare_chantier_update"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Prépare un DOSSIER DE SUIVI DE CHANTIER (avancement %, étape, "
        "photos annoncées, coût, notes) sans RIEN écrire — l'écriture réelle "
        "n'a lieu qu'après confirmation humaine. UNIQUEMENT quand "
        "l'utilisateur veut CONSIGNER ou mettre à jour l'avancement d'une "
        "intervention en cours. "
        "Ne JAMAIS utiliser pour lister/consulter les interventions passées "
        "(voir list_maintenance_logs). Accepte tout sous-ensemble "
        "d'arguments, même vide, et retourne fields + missing + questions "
        "courtes (2 max). "
        "Exemple : « consigne un avancement de 50 % pour WASH-001 » -> "
        "prepare_chantier_update ; « quelles interventions réalisées ? » -> "
        "list_maintenance_logs, pas cet outil."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "incident": {
                "type": "string",
                "description": "Incident/chantiers concerné : id, référence ou titre (approximatif accepté)",
            },
            "progress_percent": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Avancement du chantier en % (0-100)",
            },
            "step": {
                "type": "string",
                "description": "Étape actuelle du chantier (ex : terrassement, maçonnerie, finitions)",
            },
            "cost_amount": {
                "type": "number",
                "description": "Coût annoncé des travaux en XAF (optionnel)",
            },
            "notes": {
                "type": "string",
                "description": "Notes libres : photos annoncées, observations terrain (optionnel)",
            },
        },
    },
}

READ_ONLY = False

# Indices de création CONSIGNER un avancement (verbes multi-mots + noms).
# Vérifiés un par un contre TOUS les phrasés legacy (routage create/other
# de tests/test_prompt_eval.py, tests/test_agent_loop.py et des plugins
# frères) : aucun n'est une sous-chaîne d'un phrasé legacy — sinon le
# routeur (has_list gagne) casserait le legacy. Ne pas ajouter de forme
# courte ("enregistre", "journalise", "crée une intervention"...) : collision.
INTENT_HINTS = frozenset({
    "consigne une intervention",
    "ajoute une intervention",
    "journalise l'avancement",
    "enregistre l'avancement",
    "avancement",
    "pourcentage",
    "etape du chantier",
    "étape du chantier",
    "suivi de chantier",
    "suivi du chantier",
    "travaux termines",
    "travaux terminés",
})

# Slots REQUIS pour un dossier prêt ; coût et notes restent optionnels.
_REQUIRED = ("incident", "progress_percent", "step")

_SLOT_LABELS = {
    "incident": "l'incident concerné (titre, numéro ou référence)",
    "progress_percent": "l'avancement en % (0-100)",
    "step": "l'étape actuelle du chantier",
}

_SLOT_QUESTIONS = {
    "incident": "Quel incident est concerné (titre ou référence) ?",
    "progress_percent": "Quel avancement en % (0-100) ?",
    "step": "Quelle est l'étape actuelle du chantier ?",
}

_ROW_LABELS = {
    "incident_label": "Incident",
    "progress_percent": "Avancement (%)",
    "step": "Étape",
    "cost_amount": "Coût (XAF)",
    "notes": "Notes",
}

_CANDIDATE_KEYS = ("id", "reference_code", "title", "school_name", "district",
                   "category", "urgency", "status", "affected_students",
                   "priority_score", "reported_at")


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _norm_percent(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 100 else None


def _norm_cost(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _match_incidents(context: dict[str, Any], ref: Any) -> list[dict[str, Any]]:
    """Candidats par force décroissante : id, réf exacte, puis flou."""
    incidents = context.get("incidents", [])
    if not isinstance(incidents, list):
        return []
    if ref is None or str(ref).strip() == "":
        return []
    try:
        wanted = int(ref)  # type: ignore[arg-type]
        if not isinstance(ref, bool):
            return [i for i in incidents
                    if isinstance(i, dict) and i.get("id") == wanted][:1]
    except (TypeError, ValueError):
        pass
    hint = str(ref).strip().lower()
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        if str(incident.get("reference_code", "")).lower() == hint:
            return [incident]
    scored: list[tuple[int, dict[str, Any]]] = []
    tokens = [t for t in hint.split() if len(t) >= 3]
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        code = str(incident.get("reference_code", "")).lower()
        title = str(incident.get("title", "")).lower()
        if hint in code or hint in title:
            scored.append((3, incident))
        elif tokens and all(t in title for t in tokens):
            scored.append((2, incident))
    if not scored and len(hint) >= 4:
        for incident in incidents:
            if not isinstance(incident, dict):
                continue
            title = str(incident.get("title", "")).lower()
            if difflib.SequenceMatcher(None, hint, title).ratio() >= INCIDENT_FUZZY_MIN_RATIO:
                scored.append((1, incident))
    scored.sort(key=lambda s: -s[0])
    seen: set[Any] = set()
    ordered: list[dict[str, Any]] = []
    for _, incident in scored:
        key = incident.get("id", id(incident))
        if key not in seen:
            seen.add(key)
            ordered.append(incident)
    return ordered


def _open_incidents(context: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for row in context.get("incidents", []) or []:
        if isinstance(row, dict) and str(row.get("status") or "").lower() not in ("resolved", "closed"):
            out.append(row)
    return out


def _incident_choices(incidents: list[dict[str, Any]], limit: int = 5) -> str:
    choices = []
    for incident in incidents[:limit]:
        choices.append(
            f"{incident.get('reference_code', '?')} — "
            f"{incident.get('title', '?')} (id {incident.get('id')})")
    return ", ".join(choices) if choices else "aucun incident dans le contexte"


def _candidate_card(incident: dict[str, Any]) -> dict[str, Any]:
    return {key: incident.get(key) for key in _CANDIDATE_KEYS}


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Prépare un dossier de suivi chantier (déterministe, offline, sans écriture)."""
    try:
        if not isinstance(args, dict):
            args = {}
        if not isinstance(context, dict):
            context = {}

        raw_incident = args.get("incident")
        hint = str(raw_incident or "").strip()
        candidates = _match_incidents(context, raw_incident)
        incident = candidates[0] if len(candidates) == 1 else None

        raw_percent = args.get("progress_percent")
        percent = _norm_percent(raw_percent)
        percent_invalid = raw_percent is not None and str(raw_percent).strip() != "" and percent is None
        step = _clean_text(args.get("step"))
        cost = _norm_cost(args.get("cost_amount"))
        notes = _clean_text(args.get("notes"))

        label = None
        if incident is not None:
            label = (f"{incident.get('reference_code') or incident.get('id')}"
                     f" — {incident.get('title', '?')}")

        fields: dict[str, Any] = {
            "incident_id": incident.get("id") if incident else None,
            "incident_label": label,
            "progress_percent": percent,
            "step": step,
            "cost_amount": cost,
            "notes": notes,
        }

        missing = [slot for slot in _REQUIRED
                   if (slot == "incident" and incident is None)
                   or (slot == "progress_percent" and percent is None)
                   or (slot == "step" and not step)]
        labels = [_SLOT_LABELS[m] for m in missing]
        questions = [_SLOT_QUESTIONS[m] for m in missing[:2]]
        ready = not missing

        rows = [f"{_ROW_LABELS[k]} : {v}" for k, v in
                (("incident_label", label), ("progress_percent", percent),
                 ("step", step), ("cost_amount", cost), ("notes", notes))
                if v is not None and v != ""]
        recap = "Suivi de chantier\n" + "\n".join(rows)
        if labels:
            recap += "\nManquant : " + ", ".join(labels) + "."

        if ready:
            insight = (f"Dossier chantier prêt : {label}, {percent} %, "
                       f"étape « {step} »")
            if cost is not None:
                insight += f", coût {cost:g} XAF"
            insight += ". À confirmer par un humain avant tout enregistrement."
        else:
            insight = ("Dossier chantier partiel (rien n'est enregistré) — "
                       f"manque : {', '.join(labels)}.")
            if percent_invalid:
                insight += " Pourcentage invalide (0-100 attendu)."

        obs: dict[str, Any] = {
            "insight": insight,
            "action": "update_chantier",
            "complete": ready,
            "fields": fields,
            "missing": missing,
            "missing_labels": labels,
            "questions": questions,
            "ready": ready,
            "recap": recap,
        }
        if hint and incident is None:
            obs["hint_unmatched"] = hint
            pool = candidates if candidates else _open_incidents(context)
            obs["incident_choices"] = _incident_choices(pool)
            if len(candidates) > 1:
                obs["candidates"] = [_candidate_card(c) for c in candidates[:5]]
        return obs
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _build_chantier_dossier_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict):
        return None
    if obs.get("error"):
        return None
    fields = obs.get("fields")
    if not isinstance(fields, dict):
        return None
    has_value = any(v is not None and v != "" for v in fields.values())
    if not has_value and not obs.get("missing") and not obs.get("questions"):
        return None
    title = "Dossier — suivi de chantier"
    label = fields.get("incident_label")
    if label:
        title = f"Dossier chantier — {label}"
    return AgentCard(type="chantier_dossier", title=title, data=obs)


CARD_BUILDERS = {"chantier_dossier": _build_chantier_dossier_card}
