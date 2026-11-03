"""Plugin outil : relances proactives des incidents dormants.

Detecte les incidents ouverts sans activite depuis plus de N jours et
propose pour chacun un message de relance pret a envoyer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..schemas import AgentCard
from ..tool_consts import (
    ALERT_WINDOW_DAYS_DEFAULT,
    ALERT_WINDOW_DAYS_MAX,
    ALERT_WINDOW_DAYS_MIN,
    tool_lang,
)

TOOL_NAME = "relances_proactives"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Detecte les incidents DORMANTS : ouverts mais sans aucune activite "
        "(ni mise a jour ni journal) depuis plus de N jours (defaut 7), et "
        "propose pour chacun un message de relance pret a envoyer. A utiliser "
        "quand l'utilisateur demande quels incidents relancer, s'il y a des "
        "dossiers dormants, oublies ou sans nouvelles depuis longtemps. "
        "Exemple : Quels incidents sont en retard a Douala ? -> "
        "relances_proactives({days: 7, district: 'Douala'}). "
        "Ne JAMAIS utiliser pour lister tous les incidents (sans filtre de "
        "dormance), ni pour les alertes critiques fraiches (utiliser "
        "district_alerts), ni pour resumer un district (utiliser "
        "summarize_district) : cet outil ne renvoie que les dossiers "
        "oublies avec leurs brouillons de relance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Seuil d'inactivite en jours (defaut : 7)",
                "default": ALERT_WINDOW_DAYS_DEFAULT,
            },
            "district": {
                "type": "string",
                "description": "District filtre (insensible a la casse, optionnel)",
            },
        },
    },
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "relance", "relances", "relancer", "relancez",
    "a relancer", "à relancer",
    "dormant", "dormants", "dormante", "dormantes",
    "oublie", "oublié", "oublies", "oubliés",
    "oubliee", "oubliée", "oubliees", "oubliées",
    "sans nouvelle", "sans nouvelles",
    "en retard",
    "stagne", "stagnent",
    "stagnant", "stagnants", "stagnante", "stagnantes",
    "inactif", "inactifs", "inactive", "inactives",
    "inactivite", "inactivité",
    "abandonne", "abandonné", "abandonnes", "abandonnés",
    "abandonnee", "abandonnée", "abandonnees", "abandonnées",
})

_CLOSED = ("resolved", "closed")


def _parse_days(value: Any, default: int = ALERT_WINDOW_DAYS_DEFAULT) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(days, ALERT_WINDOW_DAYS_MIN), ALERT_WINDOW_DAYS_MAX)


def _parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _district_matches(item_district: Any, wanted: str) -> bool:
    if not wanted:
        return True
    low = str(item_district or "").strip().lower()
    if not low:
        return False
    return wanted in low or low in wanted


def _is_open(incident: dict[str, Any]) -> bool:
    status = str(incident.get("status") or "").strip().lower()
    if not status:
        return True
    return status not in _CLOSED


def _log_dates(log: dict[str, Any]) -> list[datetime]:
    dates: list[datetime] = []
    for key in ("created_at", "repaired_at", "reported_at"):
        parsed = _parse_dt(log.get(key))
        if parsed is not None:
            dates.append(parsed)
    return dates


def _logs_by_incident(context: dict[str, Any]) -> dict[str, list[datetime]]:
    """Indexe les dates d'activite des journaux par incident (id et ref)."""
    index: dict[str, list[datetime]] = {}
    logs = context.get("maintenance_logs", []) or []
    for log in logs:
        if not isinstance(log, dict):
            continue
        dates = _log_dates(log)
        if not dates:
            continue
        keys: list[str] = []
        if log.get("incident_id") is not None:
            keys.append(f"id:{log.get('incident_id')}")
        for ref_key in ("incident_ref", "reference_code"):
            ref = log.get(ref_key)
            if ref:
                keys.append(f"ref:{str(ref).strip()}")
        for key in keys:
            index.setdefault(key, []).extend(dates)
    return index


def _last_activity(incident: dict[str, Any],
                   log_index: dict[str, list[datetime]]) -> datetime | None:
    moments: list[datetime] = []
    for key in ("reported_at", "updated_at"):
        parsed = _parse_dt(incident.get(key))
        if parsed is not None:
            moments.append(parsed)
    lookup = [f"id:{incident.get('id')}"] if incident.get("id") is not None else []
    if incident.get("reference_code"):
        lookup.append(f"ref:{str(incident.get('reference_code')).strip()}")
    for key in lookup:
        moments.extend(log_index.get(key, []))
    return max(moments) if moments else None


def _draft_message(school: str, title: str, ref: Any, days_idle: int,
                   en: bool = False) -> str:
    code = f" ({ref})" if ref else ""
    if en:
        return (
            f"Hello, following up on case {title}{code} at {school}: "
            f"no news for {days_idle} days. "
            "Can you confirm the progress? Thank you."
        )
    return (
        f"Bonjour, suivi du dossier {title}{code} a {school} : "
        f"sans nouvelles depuis {days_idle} jours. "
        "Pouvez-vous confirmer l'avancement ? Merci."
    )


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Detecte les incidents dormants (deterministe, synchrone, sans reseau)."""
    try:
        args = args or {}
        context = context or {}
        use_en = tool_lang(context) == "en"
        district = str(args.get("district") or "").strip()
        district_low = district.lower()
        days = _parse_days(args.get("days", ALERT_WINDOW_DAYS_DEFAULT))
        now = datetime.now(timezone.utc)

        if context.get("incidents", None) is None:
            err = ("No incident data available "
                   "to detect dormant cases.") if use_en else (
                       "Aucune donnee d'incident disponible "
                       "pour detecter les dossiers dormants.")
            return {"items": [], "total": 0, "days": days,
                    "district": district or None, "error": err}

        log_index = _logs_by_incident(context)
        items: list[dict[str, Any]] = []
        for incident in context.get("incidents", []) or []:
            if not isinstance(incident, dict):
                continue
            if not _is_open(incident):
                continue
            if not _district_matches(incident.get("district"), district_low):
                continue
            last = _last_activity(incident, log_index)
            if last is None:
                continue
            idle = max((now - last).days, 0)
            if idle <= days:
                continue
            school = str(incident.get("school_name")
                         or ("Unknown school" if use_en else "École inconnue"))
            title = str(incident.get("title") or incident.get("summary")
                        or ("Untitled incident" if use_en else "Incident sans titre"))
            ref = incident.get("reference_code")
            items.append({
                "school_name": school,
                "incident_title": title,
                "reference_code": ref,
                "days_idle": idle,
                "draft_message": _draft_message(school, title, ref, idle, en=use_en),
            })

        scope = ((f" in {district}" if district else "") if use_en
                 else (f" à {district}" if district else ""))
        if not items:
            err = (f"No dormant incident for more than {days} "
                   f"days{scope}.") if use_en else (
                       f"Aucun incident dormant depuis plus de {days} "
                       f"jours{scope}.")
            return {"items": [], "total": 0, "days": days,
                    "district": district or None, "error": err}

        items.sort(key=lambda i: int(i.get("days_idle", 0) or 0), reverse=True)
        total = len(items)
        plural = "s" if total > 1 else ""
        if use_en:
            insight = (f"{total} dormant incident{plural} for more than "
                       f"{days} days{scope}: follow-up drafts ready.")
        else:
            insight = (f"{total} incident{plural} dormant{plural} depuis plus de "
                       f"{days} jours{scope} : brouillons de relance prêts.")
        return {"insight": insight, "items": items, "total": total,
                "days": days, "district": district or None,
                "lang": "en" if use_en else "fr"}
    except Exception as exc:  # contrat : jamais d'exception vers la boucle
        err = f"Follow-ups unavailable: {exc}" if use_en else f"Relances indisponibles : {exc}"
        return {"items": [], "total": 0, "error": err}


def _build_relances_card(obs: dict[str, Any]) -> AgentCard | None:
    items = obs.get("items") or []
    if not items:
        return None
    total = obs.get("total") or len(items)
    district = obs.get("district")
    use_en = str(obs.get("lang") or "fr").lower().startswith("en")
    scope = f" — {district}" if district else ""
    title = (f"{total} suggested follow-up(s){scope}" if use_en
             else f"{total} relance(s) proposée(s){scope}")
    return AgentCard(type="relances", title=title, data=obs)


CARD_BUILDERS = {"relances": _build_relances_card}
