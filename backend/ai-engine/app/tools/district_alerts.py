"""Plugin outil : alertes actionnables d'un district.

Alertes = situations exigeant une action (critiques >7j, écoles sans eau,
pics d'incidents récents), PAS un résumé général.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..schemas import AgentCard
from ..textnorm import dedup_incidents, district_match, fold, parse_dt
from ..tool_consts import (
    ALERT_WINDOW_DAYS_DEFAULT,
    ALERT_WINDOW_DAYS_MAX,
    ALERT_WINDOW_DAYS_MIN,
    STALE_AFTER_DAYS,
)

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
                "default": ALERT_WINDOW_DAYS_DEFAULT,
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

#: Alias partagé (source unique : app.tool_consts).
_STALE_DAYS = STALE_AFTER_DAYS
_SPIKE_THRESHOLD = 3


def _parse_days(value: Any, default: int = ALERT_WINDOW_DAYS_DEFAULT) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(days, ALERT_WINDOW_DAYS_MIN), ALERT_WINDOW_DAYS_MAX)


def _age_days(reported_at: Any, now: datetime) -> int | None:
    parsed = parse_dt(reported_at)
    if parsed is None:
        return None
    return max((now - parsed).days, 0)


def _is_no_water(incident: dict[str, Any]) -> bool:
    if fold(incident.get("issue_type")).strip() in _NO_WATER_ISSUES:
        return True
    # Famille absence-d'eau : NON niable ("pas d'eau" EST l'incident).
    text = fold(f"{incident.get('title') or ''} "
                f"{incident.get('summary') or ''}")
    return any(fold(kw) in text for kw in _NO_WATER_KEYWORDS)


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
        days = _parse_days(args.get("days", ALERT_WINDOW_DAYS_DEFAULT))
        now = datetime.now(timezone.utc)

        incidents = [i for i in (context.get("incidents", []) or [])
                     if isinstance(i, dict)
                     and district_match(i.get("district"), district)]
        if context.get("incidents") is None:
            # Cas "unknown" : clé manquante -> erreur (guidance). Une liste
            # présente mais vide est un vide valide -> carte typée vide.
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
            if urgency == "critical" and (age is None or age > _STALE_DAYS):
                # Sans date = conservé, prudent (même politique qu'epidemic_alerts).
                if age is None:
                    action = (f"Intervenir en priorité à {school} : incident critique "
                              "sans date connue — vérifier l'ancienneté.")
                else:
                    action = (f"Intervenir en priorité à {school} : incident critique "
                              f"ouvert depuis {age} jours.")
                alerts.append({
                    "kind": "critical_stale",
                    "severity": "critical",
                    "school_name": school,
                    "reference_code": ref,
                    "title": title,
                    "urgency": urgency,
                    "age_days": age,
                    "affected_students": affected,
                    "action": action,
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
        # Les deux flux Laravel fusionnés (dédupliqués) : un pic se détecte
        # quel que soit le flux peuplé. Les sans-date du district sont
        # comptés à part (prudent, traçable dans le titre).
        pool = dedup_incidents(context.get("incidents"),
                               context.get("recent_incidents"))
        recent_count = 0
        undated_count = 0
        for recent in pool:
            item_district = (recent.get("district")
                             or sid_district.get(recent.get("school_id")))
            if not district_match(item_district, district):
                continue
            age = _age_days(recent.get("reported_at"), now)
            if age is None:
                undated_count += 1
            elif age < days:
                recent_count += 1
        spike_total = recent_count + undated_count
        if spike_total >= _SPIKE_THRESHOLD:
            scope = f" à {district}" if district else ""
            undated_suffix = (f" (dont {undated_count} sans date)"
                              if undated_count else "")
            title = (f"Pic de {spike_total} incidents en {days} jours{scope}"
                     f"{undated_suffix}")
            alerts.append({
                "kind": "spike",
                "severity": "high",
                "school_name": None,
                "reference_code": None,
                "title": title,
                "urgency": None,
                "age_days": None,
                "affected_students": None,
                "undated_count": undated_count,
                "action": f"Analyser la cause du pic ({title}) et planifier une tournée.",
            })

        if not alerts:
            # Vide valide -> carte typée vide (pas d'erreur) : l'état vide
            # frontend devient atteignable (politique AXE 7 / P1b).
            scope = f" pour {district}" if district else ""
            return {"alerts": [], "total": 0, "district": district or None,
                    "days": days,
                    "insight": f"Aucune alerte actionnable{scope} sur la période."}

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
    if not isinstance(obs, dict) or obs.get("error"):
        return None
    alerts = obs.get("alerts")
    if not isinstance(alerts, list):
        return None
    total = obs.get("total") or len(alerts)
    district = obs.get("district")
    scope = f" — {district}" if district else ""
    if not alerts:
        return AgentCard(
            type="district_alerts",
            title=f"Aucune alerte actionnable{scope}",
            data=obs,
        )
    return AgentCard(
        type="district_alerts",
        title=f"{total} alerte(s) actionnable(s){scope}",
        data=obs,
    )


CARD_BUILDERS = {"district_alerts": _build_district_alerts_card}
