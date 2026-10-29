from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .decision_agent import DecisionAgent
from .schemas import SchoolMaintenanceHistory


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _open_incidents(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in context.get("incidents", []) if i.get("status") not in ("resolved", "closed")]


def tool_analyze_school(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Analyse complète d'une école : pannes ouvertes, coûts, arbitrage réparer/remplacer."""
    school_id = args.get("school_id")
    school = next((s for s in context.get("schools", []) if s.get("school_id") == school_id), None)
    if not school:
        return {"error": f"École {school_id} introuvable dans le contexte."}
    open_incs = [i for i in _open_incidents(context) if i.get("school_id") == school_id]
    history = SchoolMaintenanceHistory(
        school_id=school["school_id"],
        school_name=school.get("school_name", "?"),
        district=school.get("district", "?"),
        equipment_type=school.get("equipment_type", "pompe_manuelle"),
        installation_year=school.get("installation_year"),
        estimated_replacement_cost=float(school.get("estimated_replacement_cost", 1500000.0)),
        incident_count=int(school.get("incident_count", len(open_incs))),
        total_repair_cost=float(school.get("total_repair_cost", 0.0)),
        total_days_without_service=int(school.get("total_days_without_service", 0)),
    )
    analysis = DecisionAgent.evaluate_school_equipment(history)
    return {
        "school_id": school["school_id"],
        "school_name": school.get("school_name"),
        "district": school.get("district"),
        "open_incidents": [
            {"id": i.get("id"), "title": i.get("title"), "urgency": i.get("urgency"),
             "category": i.get("category"), "affected_students": i.get("affected_students", 0)}
            for i in open_incs
        ],
        "recommendation": analysis.recommendation,
        "repair_ratio_percent": analysis.repair_to_replacement_ratio_percent,
        "annualized_failure_rate": analysis.annualized_failure_rate,
        "financial_saving_potential": analysis.financial_saving_potential,
        "justification": analysis.justification,
        "suggested_modernization": analysis.suggested_modernization,
    }


def tool_rank_schools_by_need(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Classe les écoles par besoin objectif (urgences ouvertes, élèves affectés, ancienneté)."""
    weights = {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 0.5}
    now = datetime.now(timezone.utc)
    ranking = []
    for school in context.get("schools", []):
        open_incs = [i for i in _open_incidents(context) if i.get("school_id") == school.get("school_id")]
        if not open_incs:
            continue
        score = sum(weights.get(str(i.get("urgency", "low")), 0.5) for i in open_incs)
        affected = sum(int(i.get("affected_students", 0) or 0) for i in open_incs)
        score += min(affected / 100.0, 10.0)
        ages = [now - dt for i in open_incs if (dt := _parse_dt(i.get("reported_at"))) is not None]
        oldest_days = max((a.days for a in ages), default=0)
        score += min(oldest_days / 7.0, 8.0)
        ranking.append({
            "school_id": school.get("school_id"),
            "school_name": school.get("school_name"),
            "district": school.get("district"),
            "need_score": round(score, 1),
            "open_incidents": len(open_incs),
            "affected_students": affected,
            "oldest_days": oldest_days,
            "top_urgency": max((str(i.get("urgency", "low")) for i in open_incs),
                               key=lambda u: weights.get(u, 0.0)),
        })
    ranking.sort(key=lambda r: r["need_score"], reverse=True)
    for position, row in enumerate(ranking, start=1):
        row["rank"] = position
    return {"ranking": ranking, "total": len(ranking)}


def tool_summarize_district(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Synthèse chiffrée : urgences, catégories, élèves affectés."""
    open_incs = _open_incidents(context)
    by_urgency: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for i in open_incs:
        by_urgency[str(i.get("urgency", "?"))] = by_urgency.get(str(i.get("urgency", "?")), 0) + 1
        by_category[str(i.get("category", "?"))] = by_category.get(str(i.get("category", "?")), 0) + 1
    return {
        "open_incidents": len(open_incs),
        "by_urgency": by_urgency,
        "by_category": by_category,
        "total_affected_students": sum(int(i.get("affected_students", 0) or 0) for i in open_incs),
        "schools_involved": sorted({str(i.get("school_name", "?")) for i in open_incs}),
    }


def tool_explain_incident(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Détail factuel d'un incident pour l'expliquer en langage clair."""
    incident_id = args.get("incident_id")
    incident = next((i for i in context.get("incidents", []) if i.get("id") == incident_id), None)
    if not incident:
        return {"error": f"Incident {incident_id} introuvable dans le contexte."}
    return {
        "id": incident.get("id"),
        "reference_code": incident.get("reference_code"),
        "school_name": incident.get("school_name"),
        "district": incident.get("district"),
        "title": incident.get("title"),
        "category": incident.get("category"),
        "issue_type": incident.get("issue_type"),
        "urgency": incident.get("urgency"),
        "status": incident.get("status"),
        "priority_score": incident.get("priority_score"),
        "affected_students": incident.get("affected_students"),
        "summary": incident.get("summary"),
        "reported_at": incident.get("reported_at"),
    }


def tool_prepare_report(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Prépare un signalement structuré (sans rien écrire) à partir d'une description libre."""
    description = (args.get("description") or "").strip()
    hint = (args.get("school_hint") or "").strip().lower()
    matched = None
    if hint:
        for school in context.get("schools", []):
            if hint in str(school.get("school_name", "")).lower():
                matched = {"school_id": school.get("school_id"), "school_name": school.get("school_name")}
                break
    return {
        "action": "create_report",
        "description": description,
        "matched_school": matched,
        "needs_confirmation": True,
    }


TOOL_EXECUTORS = {
    "analyze_school": tool_analyze_school,
    "rank_schools_by_need": tool_rank_schools_by_need,
    "summarize_district": tool_summarize_district,
    "explain_incident": tool_explain_incident,
    "prepare_report": tool_prepare_report,
}

AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_school",
            "description": "Analyse complète d'une école : pannes ouvertes, coûts de maintenance et arbitrage réparer-remplacer.",
            "parameters": {
                "type": "object",
                "properties": {"school_id": {"type": "integer", "description": "Identifiant de l'école"}},
                "required": ["school_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_schools_by_need",
            "description": "Classe les écoles avec pannes ouvertes par besoin objectif (urgences, élèves affectés, ancienneté).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_district",
            "description": "Synthèse chiffrée des incidents ouverts : urgences, catégories, élèves affectés.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_incident",
            "description": "Récupère le détail factuel d'un incident pour l'expliquer simplement.",
            "parameters": {
                "type": "object",
                "properties": {"incident_id": {"type": "integer", "description": "Identifiant de l'incident"}},
                "required": ["incident_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_report",
            "description": "Prépare un signalement structuré depuis une description libre. N'écrit rien : propose une carte de confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Description libre de la panne"},
                    "school_hint": {"type": "string", "description": "Nom ou fragment du nom de l'école si mentionné"},
                },
                "required": ["description"],
            },
        },
    },
]
