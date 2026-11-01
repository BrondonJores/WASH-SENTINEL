"""Plugin outil : timeline passée des missions terrain.

TIMELINE PASSÉE uniquement (qu'a fait l'équipe, où sont-ils allés,
chronologie des visites) — jamais de dispatch futur ni de journal d'un
seul jour précis (voir list_maintenance_logs pour ça).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..schemas import AgentCard
from ..tool_consts import (
    MISSION_WINDOW_DAYS_DEFAULT,
    MISSION_WINDOW_DAYS_MAX,
    MISSION_WINDOW_DAYS_MIN,
)

TOOL_NAME = "interventoils_mission"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Chronologie des missions terrain DÉJÀ réalisées (timeline passée : "
        "qu'a fait l'équipe, où sont-ils allés, quelles écoles visitées et "
        "à quel coût, sur une fenêtre de jours glissants). À utiliser quand "
        "l'utilisateur demande l'historique des déplacements, les visites "
        "passées ou la timeline des missions sur plusieurs jours. "
        "Exemple : 'Où sont allées les équipes ce mois-ci ?' -> "
        "interventoils_mission({\"days\": 30}). "
        "Ne JAMAIS utiliser pour planifier ou dispatcher les futures tournées "
        "des équipes (outil futur, pas cet outil), ni pour le journal détaillé "
        "d'un seul jour précis (voir list_maintenance_logs)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "district": {
                "type": "string",
                "description": "District filtré (optionnel, ex : Mvila)",
            },
            "school": {
                "type": "string",
                "description": "Nom (ou fragment) ou identifiant de l'école (optionnel)",
            },
            "days": {
                "type": "integer",
                "description": "Fenêtre en jours glissants (défaut 30, 1 à 365)",
                "default": MISSION_WINDOW_DAYS_DEFAULT,
            },
        },
    },
}

READ_ONLY = True

# Indices minuscules (formes sans accent doublées). Chacun a été vérifié
# ABSENT (sous-chaîne) de tous les phrasés legacy create/other de
# tests/test_prompt_eval.py et tests/test_agent_loop.py : le bare "journal"
# et "le journal" sont VOLONTAIREMENT exclus (ils collident avec
# "Journalise..." / "mets a jour le journal" -> create).
INTENT_HINTS = frozenset({
    "historique",
    "timeline",
    "chronologie",
    "visite",
    "visites",
    "passage",
    "passages",
    "terrain",
    "terrains",
    "déplacement",
    "deplacement",
    "déplacements",
    "deplacements",
    "ont-ils fait",
    "ont ils fait",
    "sont-ils allés",
    "sont-ils alles",
    "sont ils allés",
    "sont ils alles",
    "où sont-ils allés",
    "ou sont-ils alles",
    "où sont ils allés",
    "ou sont ils alles",
    "journal des interventions",
    "journal des visites",
    "qu'a fait l'équipe",
    "qu'a fait l'equipe",
})


def _log_date(log: dict[str, Any]) -> str:
    """Date AAAA-MM-JJ d'un journal : created_at, repli repaired_at/reported_at."""
    for key in ("created_at", "repaired_at", "reported_at"):
        value = log.get(key)
        if value and len(str(value).strip()) >= 10:
            candidate = str(value).strip()[:10]
            try:
                return datetime.strptime(candidate, "%Y-%m-%d").date().isoformat()
            except ValueError:
                continue
    return ""


def _float_cost(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _matches_school(log: dict[str, Any], hint: str, schools: list[Any]) -> bool:
    """Filtre école : id exact ou fragment de nom (insensible à la casse)."""
    if not hint:
        return True
    try:
        if log.get("school_id") == int(hint):
            return True
    except (TypeError, ValueError):
        pass
    low = hint.lower()
    resolved_names: list[str] = []
    for school in schools:
        if not isinstance(school, dict):
            continue
        if low in str(school.get("school_name", "")).lower():
            if log.get("school_id") == school.get("school_id"):
                return True
            resolved_names.append(str(school.get("school_name", "")).lower())
    name = str(log.get("school_name") or "").lower()
    if low in name:
        return True
    return any(r and r in name for r in resolved_names)


def _log_district(log: dict[str, Any], schools: list[Any]) -> str:
    """District d'un journal : champ direct, sinon résolu via les écoles."""
    direct = str(log.get("district") or "").strip()
    if direct:
        return direct
    sid = log.get("school_id")
    lname = str(log.get("school_name") or "").strip().lower()
    for school in schools:
        if not isinstance(school, dict):
            continue
        if sid is not None and school.get("school_id") == sid:
            return str(school.get("district") or "")
        if lname and lname == str(school.get("school_name") or "").strip().lower():
            return str(school.get("district") or "")
    return ""


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _fmt_cost(total: float) -> str:
    if total == int(total):
        return str(int(total))
    return f"{total:.2f}"


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Construit la timeline passée des missions depuis les journaux (pur)."""
    try:
        args = args if isinstance(args, dict) else {}
        context = context if isinstance(context, dict) else {}
        district = str(args.get("district") or "").strip()
        school = str(args.get("school") or "").strip()
        try:
            days = int(args.get("days", MISSION_WINDOW_DAYS_DEFAULT)
                       or MISSION_WINDOW_DAYS_DEFAULT)
        except (TypeError, ValueError):
            days = MISSION_WINDOW_DAYS_DEFAULT
        days = min(max(days, MISSION_WINDOW_DAYS_MIN), MISSION_WINDOW_DAYS_MAX)

        raw_logs = context.get("maintenance_logs", [])
        if raw_logs is None:
            raw_logs = []
        if not isinstance(raw_logs, list):
            return {"error": "Contexte maintenance_logs invalide."}
        schools = context.get("schools", [])
        if not isinstance(schools, list):
            schools = []

        today = datetime.now(timezone.utc).date()
        cutoff = today - timedelta(days=days)

        items: list[dict[str, Any]] = []
        for log in raw_logs:
            if not isinstance(log, dict):
                continue
            day = _log_date(log)
            if not day:
                continue
            try:
                log_day = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                continue
            if log_day < cutoff:
                continue
            if school and not _matches_school(log, school, schools):
                continue
            if district:
                log_district = _log_district(log, schools)
                if not log_district or district.lower() not in log_district.lower():
                    continue
            action = (
                str(log.get("incident_title") or "").strip()
                or str(log.get("title") or "").strip()
                or str(log.get("notes") or "").strip()
                or str(log.get("incident_ref") or "").strip()
                or "Intervention"
            )
            school_name = str(log.get("school_name") or "").strip() or "École inconnue"
            items.append({
                "date": day,
                "school": school_name,
                "action": action,
                "cost": _float_cost(log.get("cost_amount")),
                "incident_ref": log.get("incident_ref"),
                "id": log.get("id"),
            })

        items.sort(key=lambda i: (i["date"], str(i["school"]).lower(), str(i["action"]).lower()))
        total_cost = round(sum(float(i["cost"]) for i in items), 2)
        totals = {
            "missions": len(items),
            "schools_visited": len({str(i["school"]) for i in items}),
            "total_cost": total_cost,
        }

        scope = f"sur les {days} derniers jours"
        if district:
            scope += f" dans le district de {district}"
        if school:
            scope += f" à {school}"
        if not items:
            insight = f"Aucune mission terrain trouvée {scope}."
        else:
            insight = (
                f"{totals['missions']} {_plural(totals['missions'], 'mission', 'missions')} "
                f"sur {totals['schools_visited']} "
                f"{_plural(totals['schools_visited'], 'école visitée', 'écoles visitées')} "
                f"({_fmt_cost(total_cost)} XAF au total) {scope}."
            )
        return {
            "insight": insight,
            "items": items,
            "totals": totals,
            "applied_filters": {"district": district or None, "school": school or None, "days": days},
        }
    except Exception as exc:
        return {"error": f"interventoils_mission : {exc}"}


def _build_mission_timeline_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict) or obs.get("error"):
        return None
    if not obs.get("items"):
        return None
    return AgentCard(
        type="mission_timeline",
        title="Timeline des missions terrain",
        data=obs,
    )


CARD_BUILDERS = {"mission_timeline": _build_mission_timeline_card}
