"""Plugin outil : observatoire — chiffres clés du territoire.

Vue chiffrée d'ensemble : totaux, répartitions (district, urgence,
catégorie) et mini-tendance sur 6 mois. PAS de classement d'écoles,
PAS de résumé narratif, PAS d'alertes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..schemas import AgentCard
from ..tool_consts import TREND_MONTHS

TOOL_NAME = "observatoire"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Donne les CHIFFRES CLÉS du territoire (observatoire) : totaux "
        "(incidents ouverts, écoles, élèves affectés, critiques), répartition "
        "par district, par urgence et par catégorie, plus une mini-tendance "
        "sur les 6 derniers mois. À utiliser quand l'utilisateur demande "
        "« l'observatoire », « les statistiques », « les chiffres clés », "
        "« le bilan », « le tableau de bord », « une vue d'ensemble ». "
        "Exemple : « Montre-moi les chiffres clés du territoire » -> "
        "observatoire({}). "
        "Ne JAMAIS utiliser pour classer les écoles par besoin (utiliser "
        "rank_schools_by_need), pour le résumé narratif d'un district "
        "(utiliser summarize_district), ni pour les alertes actionnables "
        "(utiliser district_alerts) : cet outil ne renvoie que des agrégats "
        "chiffrés, pas un classement, pas un récit, pas des alertes."
    ),
    "parameters": {"type": "object", "properties": {}},
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "observatoire",
    "statistiques", "stats",
    "chiffres clés", "chiffres cles",
    "bilan",
    "tableau de bord",
    "vue d'ensemble", "vue densemble",
    "panorama",
    "synthèse chiffrée", "synthese chiffree",
})

_CLOSED = frozenset({"resolved", "closed"})

#: Alias partagé (source unique : app.tool_consts).
_TREND_MONTHS = TREND_MONTHS


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


def _to_int(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(value, 0)


def _is_open(incident: dict[str, Any]) -> bool:
    return str(incident.get("status") or "").strip().lower() not in _CLOSED


def _last_months(count: int, now: datetime) -> list[str]:
    months: list[str] = []
    year, month = now.year, now.month
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    months.reverse()
    return months


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Agrège les chiffres clés du territoire (déterministe, sans réseau)."""
    try:
        args = args or {}
        context = context or {}
        del args

        raw_incidents = context.get("incidents")
        if not isinstance(raw_incidents, list) or not raw_incidents:
            return {"total": 0,
                    "error": "Aucune donnée d'incident disponible pour l'observatoire."}
        incidents = [i for i in raw_incidents if isinstance(i, dict)]
        if not incidents:
            return {"total": 0,
                    "error": "Aucune donnée d'incident disponible pour l'observatoire."}

        schools = context.get("schools", []) or []
        school_count = len([s for s in schools if isinstance(s, dict)]) if isinstance(schools, list) else 0

        open_incs = [i for i in incidents if _is_open(i)]
        critical = sum(1 for i in open_incs
                       if str(i.get("urgency") or "").strip().lower() == "critical")
        affected = sum(_to_int(i.get("affected_students")) for i in open_incs)
        # Sémantique unifiée : somme des max par école (sans double-compte).
        school_best: dict[Any, int] = {}
        for incident in open_incs:
            sid = incident.get("school_id")
            key = ("id", sid) if sid is not None else (
                "nom", str(incident.get("school_name") or "").strip().lower())
            school_best[key] = max(school_best.get(key, 0),
                                   _to_int(incident.get("affected_students")))

        totals = {
            "incidents_open": len(open_incs),
            "schools": school_count,
            "affected_students": affected,
            "affected_students_max": sum(school_best.values()),
            "critical": critical,
        }

        by_district_map: dict[str, dict[str, Any]] = {}
        for incident in open_incs:
            district = str(incident.get("district") or "").strip() or "non renseigné"
            slot = by_district_map.setdefault(district, {"district": district, "open": 0, "critical": 0})
            slot["open"] += 1
            if str(incident.get("urgency") or "").strip().lower() == "critical":
                slot["critical"] += 1
        by_district = sorted(by_district_map.values(),
                             key=lambda s: (-int(s["open"]), str(s["district"])))

        by_urgency_map: dict[str, int] = {}
        for incident in open_incs:
            urgency = str(incident.get("urgency") or "").strip().lower() or "non renseignée"
            by_urgency_map[urgency] = by_urgency_map.get(urgency, 0) + 1
        by_urgency = [{"urgency": u, "count": c}
                      for u, c in sorted(by_urgency_map.items(), key=lambda kv: (-kv[1], kv[0]))]

        by_category_map: dict[str, int] = {}
        for incident in open_incs:
            category = (str(incident.get("category") or "").strip()
                        or str(incident.get("issue_type") or "").strip()
                        or "non renseignée")
            by_category_map[category] = by_category_map.get(category, 0) + 1
        by_category = [{"category": c, "count": n}
                       for c, n in sorted(by_category_map.items(), key=lambda kv: (-kv[1], kv[0]))]

        now = datetime.now(timezone.utc)
        month_keys = _last_months(_TREND_MONTHS, now)
        per_month: dict[str, int] = {m: 0 for m in month_keys}
        for incident in incidents:
            parsed = _parse_dt(incident.get("reported_at"))
            if parsed is None:
                continue
            key = f"{parsed.year:04d}-{parsed.month:02d}"
            if key in per_month:
                per_month[key] += 1
        trend = [{"month": m, "count": per_month[m]} for m in month_keys]

        n = len(open_incs)
        plur_n = "s" if n != 1 else ""
        plur_m = "s" if school_count != 1 else ""
        plur_c = "s" if critical != 1 else ""
        first = (f"{n} incident{plur_n} ouvert{plur_n} dans {school_count} école{plur_m}, "
                 f"dont {critical} critique{plur_c} et {affected} élèves affectés.")
        if by_district:
            top = by_district[0]
            second = (f"Le district {top['district']} concentre le plus d'incidents "
                      f"ouverts ({top['open']}).")
        else:
            second = "Aucun incident ouvert : situation stable sur le territoire."
        insight = f"{first} {second}"

        return {
            "insight": insight,
            "total": n,
            "totals": totals,
            "by_district": by_district,
            "by_urgency": by_urgency,
            "by_category": by_category,
            "trend": trend,
        }
    except Exception as exc:  # contrat : jamais d'exception vers la boucle
        return {"total": 0, "error": f"Observatoire indisponible : {exc}"}


def _build_observatoire_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict) or obs.get("error"):
        return None
    totals = obs.get("totals")
    if not isinstance(totals, dict):
        return None
    n = totals.get("incidents_open", 0)
    try:
        n_int = int(n)
    except (TypeError, ValueError):
        n_int = 0
    plur = "s" if n_int != 1 else ""
    return AgentCard(
        type="observatoire",
        title=f"Observatoire : {n_int} incident{plur} ouvert{plur}",
        data=obs,
    )


CARD_BUILDERS = {"observatoire": _build_observatoire_card}
