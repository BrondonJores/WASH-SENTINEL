"""Plugin outil : alertes actionnables d'un district.

Alertes = situations exigeant une action (critiques >7j, écoles sans eau,
pics d'incidents récents), PAS un résumé général.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..schemas import AgentCard

TOOL_NAME = "district_alerts"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Signale les alertes ACTIONNABLES d'un district : incidents critiques "
        "ouverts depuis plus de 7 jours, écoles sans eau (forage à sec, panne "
        "totale), et pics d'incidents sur les derniers jours. À utiliser quand "
        "l'utilisateur demande « y a-t-il des alertes », « qu'est-ce qui est "
        "critique », « quelles urgences dans mon district ». "
        "Exemple : « Y a-t-il des alertes à Douala ? » -> district_alerts("
        "{district: 'Douala'}). "
        "Ne JAMAIS utiliser pour un résumé général du district (utiliser "
        "summarize_district) ni pour classer les écoles par besoin (utiliser "
        "rank_schools_by_need) : cet outil ne renvoie que les situations "
        "urgentes exigeant une action, pas un panorama."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "district": {
                "type": "string",
                "description": "District filtré (insensible à la casse, optionnel)",
            },
            "days": {
                "type": "integer",
                "description": "Fenêtre en jours pour les pics récents (défaut : 7)",
                "default": 7,
            },
        },
    },
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "alerte", "alertes",
    "alerte critique", "alertes critiques",
    "alerte du district", "alertes du district",
    "quelles sont les alertes", "quelles alertes",
    "y a-t-il des alertes", "y a t il des alertes",
})

_NO_WATER_ISSUES = frozenset({"dry_well", "total_breakdown"})

_NO_WATER_KEYWORDS = ("sans eau", "à sec", "a sec", "plus d'eau", "pas d'eau")

_STALE_DAYS = 7
_SPIKE_THRESHOLD = 3


def _parse_days(value: Any, default: int = 7) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(days, 1), 90)


def _parse_dt(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_days(reported_at: Any, now: datetime) -> int | None:
    parsed = _parse_dt(reported_at)
    if parsed is None:
        return None
    return max((now - parsed).days, 0)


def _district_matches(item_district: Any, wanted: str) -> bool:
    if not wanted:
        return True
    low = str(item_district or "").strip().lower()
    if not low:
        return False
    return wanted in low or low in wanted


def _is_no_water(incident: dict[str, Any]) -> bool:
    if str(incident.get("issue_type") or "").strip().lower() in _NO_WATER_ISSUES:
        return True
    text = f"{incident.get('title') or ''} {incident.get('summary') or ''}".lower()
    return any(kw in text for kw in _NO_WATER_KEYWORDS)


def _school_districts(context: dict[str, Any]) -> dict[Any, str]:
    mapping: dict[Any, str] = {}
    for school in context.get("schools", []) or []:
        if isinstance(school, dict) and school.get("school_id") is not None:
            mapping[school["school_id"]] = str(school.get("district") or "")
    for incident in context.get("incidents", []) or []:
        if isinstance(incident, dict) and incident.get("school_id") is not None:
            mapping.setdefault(incident["school_id"], str(incident.get("district") or ""))
    return mapping


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Détecte les alertes actionnables (déterministe, synchrone, sans réseau)."""
    try:
        args = args or {}
        context = context or {}
        district = str(args.get("district") or "").strip()
        district_low = district.lower()
        days = _parse_days(args.get("days", 7))
        now = datetime.now(timezone.utc)

        incidents = [i for i in (context.get("incidents", []) or [])
                     if isinstance(i, dict) and _district_matches(i.get("district"), district_low)]
        if not incidents and not (context.get("incidents", None)):
            base: dict[str, Any] = {"alerts": [], "total": 0,
                                    "district": district or None, "days": days}
            base["error"] = "Aucune donnée d'incident disponible pour détecter des alertes."
            return base

        alerts: list[dict[str, Any]] = []
        for incident in incidents:
            age = _age_days(incident.get("reported_at"), now)
            urgency = str(incident.get("urgency") or "").strip().lower()
            school = str(incident.get("school_name") or "École inconnue")
            ref = incident.get("reference_code")
            title = str(incident.get("title") or incident.get("summary") or "Incident sans titre")
            affected = incident.get("affected_students")
            if urgency == "critical" and age is not None and age > _STALE_DAYS:
                alerts.append({
                    "kind": "critical_stale",
                    "severity": "critical",
                    "school_name": school,
                    "reference_code": ref,
                    "title": title,
                    "urgency": urgency,
                    "age_days": age,
                    "affected_students": affected,
                    "action": f"Intervenir en priorité à {school} : incident critique ouvert depuis {age} jours.",
                })
            elif _is_no_water(incident):
                alerts.append({
                    "kind": "no_water",
                    "severity": "critical",
                    "school_name": school,
                    "reference_code": ref,
                    "title": title,
                    "urgency": urgency or None,
                    "age_days": age,
                    "affected_students": affected,
                    "action": f"Rétablir l'eau en urgence à {school} (apport temporaire puis réparation).",
                })

        sid_district = _school_districts(context)
        recent_count = 0
        for recent in context.get("recent_incidents", []) or []:
            if not isinstance(recent, dict):
                continue
            age = _age_days(recent.get("reported_at"), now)
            if age is None or age >= days:
                continue
            if district_low and not _district_matches(sid_district.get(recent.get("school_id")), district_low):
                continue
            recent_count += 1
        if recent_count >= _SPIKE_THRESHOLD:
            scope = f" à {district}" if district else ""
            alerts.append({
                "kind": "spike",
                "severity": "high",
                "school_name": None,
                "reference_code": None,
                "title": f"Pic de {recent_count} incidents en {days} jours{scope}",
                "urgency": None,
                "age_days": None,
                "affected_students": None,
                "action": f"Analyser la cause du pic ({recent_count} incidents en {days} jours{scope}) et planifier une tournée.",
            })

        if not alerts:
            scope = f" pour {district}" if district else ""
            return {"alerts": [], "total": 0, "district": district or None,
                    "days": days,
                    "error": f"Aucune alerte actionnable{scope} sur la période."}

        severity_rank = {"critical": 0, "high": 1}
        alerts.sort(key=lambda a: (severity_rank.get(str(a.get("severity")), 9),
                                   -(a.get("age_days") if isinstance(a.get("age_days"), int) else -1)))
        kinds = [str(a.get("kind")) for a in alerts]
        parts = []
        if "critical_stale" in kinds:
            parts.append(f"{kinds.count('critical_stale')} critique(s) ancienne(s)")
        if "no_water" in kinds:
            parts.append(f"{kinds.count('no_water')} école(s) sans eau")
        if "spike" in kinds:
            parts.append("1 pic d'incidents")
        scope = f" à {district}" if district else ""
        total = len(alerts)
        insight = (f"{total} alerte(s) actionnable(s){scope} : "
                   f"{', '.join(parts)}. Intervention recommandée.")
        return {"insight": insight, "alerts": alerts, "total": total,
                "district": district or None, "days": days}
    except Exception as exc:  # contrat : jamais d'exception vers la boucle
        return {"alerts": [], "total": 0, "error": f"Alertes indisponibles : {exc}"}


def _build_district_alerts_card(obs: dict[str, Any]) -> AgentCard | None:
    alerts = obs.get("alerts") or []
    if not alerts:
        return None
    total = obs.get("total") or len(alerts)
    district = obs.get("district")
    scope = f" — {district}" if district else ""
    return AgentCard(
        type="district_alerts",
        title=f"{total} alerte(s) actionnable(s){scope}",
        data=obs,
    )


CARD_BUILDERS = {"district_alerts": _build_district_alerts_card}
