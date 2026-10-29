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


FRENCH_MONTHS = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                 "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _resolve_school(context: dict[str, Any], ref: Any) -> dict[str, Any] | None:
    schools = context.get("schools", [])
    try:
        wanted = int(ref)
        for school in schools:
            if school.get("school_id") == wanted:
                return school
    except (TypeError, ValueError):
        pass
    hint = str(ref or "").strip().lower()
    if hint:
        for school in schools:
            if hint in str(school.get("school_name", "")).lower():
                return school
    return None


def _month_buckets(months: int, now: datetime) -> list[tuple[int, int]]:
    buckets = []
    year, month = now.year, now.month
    for _ in range(months):
        buckets.append((year, month))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    buckets.reverse()
    return buckets


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


def tool_repair_trends(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Tendances mensuelles d'une école : pannes, coûts de réparation, jours sans service."""
    school = _resolve_school(context, args.get("school"))
    if not school:
        return {"error": f"École '{args.get('school')}' introuvable. Précisez son nom ou son identifiant."}
    months = min(max(int(args.get("months", 3) or 3), 1), 12)
    school_id = school["school_id"]
    now = datetime.now(timezone.utc)

    logs = [l for l in context.get("maintenance_logs", []) if l.get("school_id") == school_id]
    recent = [i for i in context.get("recent_incidents", []) if i.get("school_id") == school_id]

    def month_key(value: Any) -> tuple[int, int] | None:
        dt = _parse_dt(value)
        return (dt.year, dt.month) if dt else None

    buckets = _month_buckets(months, now)
    labels, incident_counts, costs, days_lost = [], [], [], []
    for year, month in buckets:
        labels.append(f"{FRENCH_MONTHS[month]} {year}")
        incident_counts.append(sum(1 for i in recent if month_key(i.get("reported_at")) == (year, month)))
        month_logs = [l for l in logs if month_key(l.get("repaired_at")) == (year, month)]
        costs.append(round(sum(float(l.get("cost_amount", 0) or 0) for l in month_logs), 2))
        days_lost.append(sum(int(l.get("days_without_service", 0) or 0) for l in month_logs))

    total_cost = round(sum(costs), 2)
    total_incidents = sum(incident_counts)
    total_days = sum(days_lost)
    avg_cost = round(total_cost / months, 2)
    previous = costs[:-1]
    avg_previous = sum(previous) / len(previous) if previous else 0.0
    if avg_previous <= 0:
        trend = "stable" if costs[-1] <= 0 else "up"
    else:
        ratio = (costs[-1] - avg_previous) / avg_previous
        trend = "up" if ratio > 0.15 else ("down" if ratio < -0.15 else "stable")
    currency = next((str(l.get("currency") or "XAF") for l in logs if l.get("currency")), "XAF")

    return {
        "school_id": school_id,
        "school_name": school.get("school_name"),
        "months": months,
        "labels": labels,
        "datasets": [
            {"label": f"Coût réparations ({currency})", "data": costs, "kind": "bar"},
            {"label": "Pannes signalées", "data": incident_counts, "kind": "line"},
            {"label": "Jours sans service", "data": days_lost, "kind": "line"},
        ],
        "figures": {
            "total_cost": total_cost,
            "currency": currency,
            "total_incidents": total_incidents,
            "total_days_lost": total_days,
            "avg_cost_per_month": avg_cost,
            "trend_direction": trend,
        },
    }


TOOL_EXECUTORS = {
    "analyze_school": tool_analyze_school,
    "rank_schools_by_need": tool_rank_schools_by_need,
    "summarize_district": tool_summarize_district,
    "explain_incident": tool_explain_incident,
    "prepare_report": tool_prepare_report,
    "repair_trends": tool_repair_trends,
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
            "name": "repair_trends",
            "description": "Tendances mensuelles d'une école sur N mois : pannes, coûts de réparation, jours sans service. À utiliser pour tout historique, tendance ou graphique.",
            "parameters": {
                "type": "object",
                "properties": {
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école"},
                    "months": {"type": "integer", "description": "Nombre de mois d'historique (1 à 12, défaut 3)"},
                },
                "required": ["school"],
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
