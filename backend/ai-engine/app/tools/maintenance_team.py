"""Plugin dispatch futur : qui envoyer où (charge + tournée groupée).

Lecture seule sur les incidents ouverts du contexte Laravel.
"""
from __future__ import annotations

from typing import Any

from ..schemas import AgentCard

TOOL_NAME = "maintenance_team"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Prépare le DISPATCH futur de l'équipe maintenance : charge de travail "
        "par district (incidents ouverts + assignés) et tournée groupée suggérée "
        "(écoles à visiter par urgence). À utiliser quand l'utilisateur demande "
        "qui envoyer où, la charge de l'équipe, les techniciens à déplacer ou "
        "une tournée. "
        "Exemple : 'Quelle tournée pour l'équipe cette semaine ?' -> "
        "maintenance_team({}). "
        "Ne JAMAIS utiliser pour l'historique passé des missions ni le journal "
        "des interventions déjà réalisées (utiliser list_maintenance_logs)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "district": {
                "type": "string",
                "description": "Filtrer sur un district (optionnel)",
            },
        },
    },
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "equipe", "équipe",
    "technicien", "techniciens",
    "tournee", "tournée",
    "tournee groupee", "tournée groupée",
    "qui envoyer", "envoyer qui", "envoyer",
    "ou envoyer", "où envoyer",
    "deplacer", "déplacer",
    "deplacement", "déplacement",
    "dispatch",
    "charge de travail", "charge par district",
})

_URGENCY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
_CLOSED = ("resolved", "closed")
_ASSIGNEE_KEYS = (
    "assignee", "assignee_name", "assigned_to",
    "assigned_to_user_id", "technician", "technicien",
)


def _urgency_of(row: dict[str, Any]) -> str:
    raw = str(row.get("urgency") or row.get("urgency_level") or "").strip().lower()
    return raw if raw in _URGENCY_RANK else "medium"


def _assignee_of(row: dict[str, Any]) -> str | None:
    for key in _ASSIGNEE_KEYS:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if int(value) > 0:
                return f"agent #{int(value)}"
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _float_of(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_of(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Charge par district + tournée groupée suggérée (déterministe, offline)."""
    try:
        if not isinstance(args, dict):
            args = {}
        if not isinstance(context, dict):
            context = {}
        district_filter = str(args.get("district") or "").strip()
        raw_incidents = context.get("incidents", [])
        if not isinstance(raw_incidents, list):
            raw_incidents = []

        open_inc: list[dict[str, Any]] = []
        for row in raw_incidents:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status in _CLOSED:
                continue
            if district_filter and str(row.get("district") or "").strip().lower() != district_filter.lower():
                continue
            open_inc.append(row)

        if not open_inc:
            scope = f" pour {district_filter}" if district_filter else ""
            return {
                "insight": f"Aucun incident ouvert{scope} — équipe disponible, pas de tournée à planifier.",
                "workload": [],
                "suggested_tour": [],
            }

        # --- Charge par district ---
        by_district: dict[str, list[dict[str, Any]]] = {}
        for row in open_inc:
            district = str(row.get("district") or "").strip() or "Sans district"
            by_district.setdefault(district, []).append(row)

        workload: list[dict[str, Any]] = []
        for district in sorted(by_district, key=str.lower):
            rows = by_district[district]
            by_urgency = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            by_assignee: dict[str, int] = {}
            assigned = 0
            affected = 0
            school_keys: set[str] = set()
            school_best: dict[str, int] = {}
            for row in rows:
                by_urgency[_urgency_of(row)] += 1
                who = _assignee_of(row)
                if who:
                    assigned += 1
                    by_assignee[who] = by_assignee.get(who, 0) + 1
                affected += _int_of(row.get("affected_students", row.get("estimated_affected_students")))
                sid = row.get("school_id")
                sname = str(row.get("school_name") or "").strip().lower()
                skey = f"id:{sid}" if sid is not None else f"n:{sname}"
                school_keys.add(skey)
                school_best[skey] = max(
                    school_best.get(skey, 0),
                    _int_of(row.get("affected_students", row.get("estimated_affected_students"))),
                )
            workload.append({
                "district": district,
                "open_incidents": len(rows),
                "schools": len(school_keys),
                "by_urgency": by_urgency,
                "assigned": assigned,
                "unassigned": len(rows) - assigned,
                "by_assignee": {k: by_assignee[k] for k in sorted(by_assignee, key=str.lower)},
                "affected_students": affected,
                # Sémantique unifiée : somme des max par école (sans
                # double-compte ; même règle que summarize_district).
                "affected_students_max": sum(school_best.values()),
            })
        workload.sort(key=lambda w: (-int(w["open_incidents"]), str(w["district"]).lower()))

        # --- Tournée : écoles groupées par district, triées par urgence ---
        by_school: dict[tuple[str, str], dict[str, Any]] = {}
        for row in open_inc:
            district = str(row.get("district") or "").strip() or "Sans district"
            sid = row.get("school_id")
            sname = str(row.get("school_name") or "").strip() or "École inconnue"
            key = (district.lower(), f"id:{sid}" if sid is not None else f"n:{sname.lower()}")
            entry = by_school.get(key)
            if entry is None:
                entry = {
                    "district": district,
                    "school_id": sid,
                    "school_name": sname,
                    "open_incidents": 0,
                    "max_urgency": "low",
                    "affected_students": 0,
                    "affected_students_max": 0,
                    "incidents": [],
                }
                by_school[key] = entry
            urgency = _urgency_of(row)
            if _URGENCY_RANK[urgency] > _URGENCY_RANK[str(entry["max_urgency"])]:
                entry["max_urgency"] = urgency
            entry["open_incidents"] = int(entry["open_incidents"]) + 1
            entry["affected_students"] = int(entry["affected_students"]) + _int_of(
                row.get("affected_students", row.get("estimated_affected_students")))
            # Sémantique unifiée : max par école (sans double-compte).
            entry["affected_students_max"] = max(
                int(entry["affected_students_max"]),
                _int_of(row.get("affected_students", row.get("estimated_affected_students"))),
            )
            incidents_list = entry["incidents"]
            assert isinstance(incidents_list, list)
            incidents_list.append({
                "id": row.get("id"),
                "reference_code": row.get("reference_code"),
                "title": row.get("title") or row.get("summary"),
                "urgency": urgency,
                "priority_score": _float_of(row.get("priority_score")),
            })
        tour = list(by_school.values())
        for entry in tour:
            incidents_list = entry["incidents"]
            assert isinstance(incidents_list, list)
            incidents_list.sort(
                key=lambda r: (-_URGENCY_RANK.get(str(r.get("urgency")), 1),
                               -_float_of(r.get("priority_score")),
                               str(r.get("reference_code") or r.get("id") or "")))
        tour.sort(key=lambda e: (
            str(e["district"]).lower(),
            -_URGENCY_RANK.get(str(e["max_urgency"]), 1),
            -int(e["affected_students"]),
            str(e["school_name"]).lower(),
        ))
        suggested_tour = [{
            "district": e["district"],
            "school_id": e["school_id"],
            "school_name": e["school_name"],
            "open_incidents": e["open_incidents"],
            "max_urgency": e["max_urgency"],
            "affected_students": e["affected_students"],
            "affected_students_max": e["affected_students_max"],
            "incidents": e["incidents"],
        } for e in tour]

        total = len(open_inc)
        assigned_total = sum(int(w["assigned"]) for w in workload)
        head = ", ".join(f"{w['district']} ({w['open_incidents']})" for w in workload[:4])
        extra = f" (+{len(workload) - 4})" if len(workload) > 4 else ""
        stops = " → ".join(
            f"{s['school_name']} ({s['max_urgency']})" for s in suggested_tour[:3])
        insight = (
            f"{total} incident{'s' if total > 1 else ''} ouvert{'s' if total > 1 else ''} "
            f"dans {len(workload)} district{'s' if len(workload) > 1 else ''} : {head}{extra}. "
            f"Charge : {assigned_total} assigné{'s' if assigned_total > 1 else ''}, "
            f"{total - assigned_total} sans assigné. "
            f"Tournée suggérée : {stops}."
        )
        return {"insight": insight, "workload": workload, "suggested_tour": suggested_tour}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _build_maintenance_team_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict):
        return None
    if obs.get("error"):
        return None
    workload = obs.get("workload")
    tour = obs.get("suggested_tour")
    if not workload and not tour:
        return None
    return AgentCard(
        type="maintenance_team",
        title="Dispatch — équipe maintenance",
        data=obs,
    )


CARD_BUILDERS = {"maintenance_team": _build_maintenance_team_card}
