from __future__ import annotations

import difflib
import re
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


def _school_choices(context: dict[str, Any], limit: int = 10) -> str:
    """Noms + ids valides, pour guider le retry du modèle en cas d'erreur."""
    choices = []
    for school in context.get("schools", [])[:limit]:
        choices.append(f"{school.get('school_name', '?')} (id {school.get('school_id')})")
    return ", ".join(choices) if choices else "aucune école dans le contexte"


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
    school = _resolve_school(context, args.get("school", args.get("school_id")))
    if not school:
        return {"error": f"École '{args.get('school', args.get('school_id'))}' introuvable. Écoles valides : {_school_choices(context)}. Réessaie avec un nom ou un id exact."}
    school_id = school["school_id"]
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
    if len(ranking) >= 2:
        gap = ranking[0]["need_score"] - ranking[1]["need_score"]
        insight = (f"{ranking[0]['school_name']} devance {ranking[1]['school_name']} "
                   f"de {_fmt_1(gap)} points.")
    elif ranking:
        insight = f"{ranking[0]['school_name']} est la seule école en difficulté."
    else:
        insight = "Aucune école en difficulté pour le moment."
    return {"ranking": ranking, "total": len(ranking), "insight": insight}


def tool_summarize_district(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Synthèse chiffrée : urgences, catégories, élèves affectés."""
    open_incs = _open_incidents(context)
    by_urgency: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for i in open_incs:
        by_urgency[str(i.get("urgency", "?"))] = by_urgency.get(str(i.get("urgency", "?")), 0) + 1
        by_category[str(i.get("category", "?"))] = by_category.get(str(i.get("category", "?")), 0) + 1
    if by_category and open_incs:
        top_cat = max(by_category, key=lambda k: by_category[k])
        n = int(by_category[top_cat])
        total = len(open_incs)
        label = CAT_FR.get(top_cat, top_cat)
        if n == total:
            insight = (f"Tous les {total} {_plural(total, 'incident ouvert', 'incidents ouverts')} "
                       f"concernent « {label} ».")
        else:
            insight = (f"En tête : {n} {_plural(n, 'incident', 'incidents')} "
                       f"« {label} » sur {total} au total.")
    else:
        insight = "Aucun incident ouvert sur ce territoire."
    return {
        "open_incidents": len(open_incs),
        "by_urgency": by_urgency,
        "by_category": by_category,
        "total_affected_students": sum(int(i.get("affected_students", 0) or 0) for i in open_incs),
        "schools_involved": sorted({str(i.get("school_name", "?")) for i in open_incs}),
        "insight": insight,
    }


def tool_explain_incident(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Détail factuel d'un incident pour l'expliquer en langage clair."""
    incident_id = args.get("incident_id")
    incident = next((i for i in context.get("incidents", []) if i.get("id") == incident_id), None)
    if not incident:
        return {"error": f"Incident {incident_id} introuvable dans le contexte."}
    dt = _parse_dt(incident.get("reported_at"))
    since = f", signalé le {dt.day} {FRENCH_MONTHS[dt.month]}" if dt else ""
    insight = (f"Priorité {_fmt_1(incident.get('priority_score', 0))}/100 : "
               f"{_fmt_int(incident.get('affected_students', 0))} élèves affectés{since}.")
    return {
        "insight": insight,
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


URGENCY_ALIASES = {
    "critical": "critical", "critique": "critical",
    "high": "high", "haute": "high", "haut": "high",
    "medium": "medium", "moyenne": "medium", "moyen": "medium",
    "low": "low", "basse": "low", "bas": "low",
}

CATEGORY_ALIASES = {
    "water_point": "water_point", "point d'eau": "water_point", "point d eau": "water_point",
    "eau": "water_point", "pompe": "water_point", "forage": "water_point", "robinet": "water_point",
    "toilets_latrines": "toilets_latrines", "latrines": "toilets_latrines",
    "toilettes": "toilets_latrines", "wc": "toilets_latrines", "sanitaires": "toilets_latrines",
    "handwashing": "handwashing", "lavage des mains": "handwashing",
    "lave-mains": "handwashing", "lave mains": "handwashing", "mains": "handwashing",
    "sewage_drainage": "sewage_drainage", "égout": "sewage_drainage", "egout": "sewage_drainage",
    "évacuation": "sewage_drainage", "evacuation": "sewage_drainage",
    "drainage": "sewage_drainage", "caniveau": "sewage_drainage",
}

SLOT_LABELS = {
    "school": "l'école concernée",
    "description": "la description de la panne",
    "title": "le titre de l'intervention",
    "category": "la catégorie (point d'eau, latrines, lavage des mains, évacuation)",
    "urgency": "le niveau d'urgence (basse, moyenne, haute, critique)",
    "affected_students": "le nombre d'élèves affectés",
    "incident": "l'incident concerné (titre, numéro ou référence)",
    "cost_amount": "le coût de l'intervention en XAF",
}

SLOT_QUESTIONS = {
    "school": "Quelle école est concernée ?",
    "description": "Décrivez la panne en quelques mots ?",
    "title": "Quel titre pour l'intervention ?",
    "category": "Quelle catégorie (point d'eau, latrines, lavage des mains, évacuation) ?",
    "urgency": "Quel niveau d'urgence (basse, moyenne, haute, critique) ?",
    "affected_students": "Combien d'élèves sont affectés ?",
    "incident": "Quel incident est concerné (titre ou référence) ?",
    "cost_amount": "Quel est le coût de l'intervention en XAF ?",
}

ACTION_TITLES = {
    "create_report": "Nouveau signalement",
    "create_incident": "Nouvelle intervention",
    "create_maintenance_log": "Journaliser une intervention",
}

_SLOT_ROW_LABELS = {
    "school_name": "École", "description": "Description", "title": "Titre",
    "category": "Catégorie", "urgency": "Urgence",
    "affected_students": "Élèves affectés", "cost_amount": "Coût (XAF)",
    "notes": "Notes", "days_without_service": "Jours sans service",
    "incident_label": "Incident",
}


def _norm_enum(value: Any, aliases: dict[str, str]) -> str | None:
    return aliases.get(str(value or "").strip().lower())


def _norm_int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _norm_cost(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _match_incidents(context: dict[str, Any], ref: Any) -> list[dict[str, Any]]:
    """Candidats par force décroissante : id exact, référence exacte, puis flou (réf/titre)."""
    incidents = context.get("incidents", [])
    if ref is None or str(ref).strip() == "":
        return []
    try:
        wanted = int(ref)
        return [i for i in incidents if i.get("id") == wanted][:1]
    except (TypeError, ValueError):
        pass
    hint = str(ref).strip().lower()
    for incident in incidents:
        if str(incident.get("reference_code", "")).lower() == hint:
            return [incident]
    scored: list[tuple[int, dict[str, Any]]] = []
    tokens = [t for t in hint.split() if len(t) >= 3]
    for incident in incidents:
        code = str(incident.get("reference_code", "")).lower()
        title = str(incident.get("title", "")).lower()
        if hint in code or hint in title:
            scored.append((3, incident))
        elif tokens and all(t in title for t in tokens):
            scored.append((2, incident))
    if not scored and len(hint) >= 4:
        for incident in incidents:
            title = str(incident.get("title", "")).lower()
            if difflib.SequenceMatcher(None, hint, title).ratio() >= 0.6:
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


def _resolve_incident(context: dict[str, Any], ref: Any) -> dict[str, Any] | None:
    """Un seul candidat → résolu ; zéro ou ambigu → None (l'appelant fait choisir)."""
    matches = _match_incidents(context, ref)
    return matches[0] if len(matches) == 1 else None


def _incident_choices(incidents: list[dict[str, Any]], limit: int = 5) -> str:
    """Références + titres valides, pour faire choisir l'utilisateur en cas d'ambiguïté."""
    choices = []
    for incident in incidents[:limit]:
        choices.append(f"{incident.get('reference_code', '?')} — {incident.get('title', '?')} (id {incident.get('id')})")
    return ", ".join(choices) if choices else "aucun incident dans le contexte"


_CANDIDATE_KEYS = ("id", "reference_code", "title", "school_name", "district",
                   "category", "urgency", "status", "affected_students",
                   "priority_score", "reported_at")


def _candidate_card(incident: dict[str, Any]) -> dict[str, Any]:
    """Vue compacte d'un incident pour la carte de choix cliquable."""
    return {key: incident.get(key) for key in _CANDIDATE_KEYS}


def _recap(action: str, slots: dict[str, Any], missing_labels: list[str]) -> str:
    rows = []
    for key, value in slots.items():
        if value is None or value == "" or key in ("school_id", "incident_id"):
            continue
        rows.append(f"{_SLOT_ROW_LABELS.get(key, key)} : {value}")
    text = ACTION_TITLES.get(action, action) + "\n" + "\n".join(rows)
    if missing_labels:
        text += "\nManquant : " + ", ".join(missing_labels) + "."
    return text


def _proposal(action: str, slots: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    labels = [SLOT_LABELS[m] for m in missing]
    questions = [SLOT_QUESTIONS[m] for m in missing[:2] if m in SLOT_QUESTIONS]
    return {
        "action": action,
        "complete": not missing,
        "slots": slots,
        "missing": missing,
        "missing_labels": labels,
        "questions": questions,
        "recap": _recap(action, slots, labels),
    }


def tool_prepare_report(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Prépare un signalement COMPLET (sans rien écrire) : école, description, catégorie, urgence, élèves."""
    school = _resolve_school(context, args.get("school", args.get("school_hint")))
    hint = str(args.get("school", args.get("school_hint")) or "").strip()
    description = str(args.get("description") or "").strip()
    category = _norm_enum(args.get("category"), CATEGORY_ALIASES)
    urgency = _norm_enum(args.get("urgency"), URGENCY_ALIASES)
    affected = _norm_int(args.get("affected_students"))
    missing = []
    if not school:
        missing.append("school")
    if not description:
        missing.append("description")
    if not category:
        missing.append("category")
    if not urgency:
        missing.append("urgency")
    if affected is None:
        missing.append("affected_students")
    obs = _proposal("create_report", {
        "school_id": school["school_id"] if school else None,
        "school_name": school.get("school_name") if school else None,
        "description": description or None,
        "category": category,
        "urgency": urgency,
        "affected_students": affected,
    }, missing)
    if hint and not school:
        obs["hint_unmatched"] = hint
        obs["school_choices"] = _school_choices(context)
    return obs


def tool_prepare_incident(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Prépare une intervention directe COMPLETE (sans rien écrire) : école, titre, catégorie, urgence, élèves."""
    school = _resolve_school(context, args.get("school"))
    hint = str(args.get("school") or "").strip()
    title = str(args.get("title") or "").strip()
    category = _norm_enum(args.get("category"), CATEGORY_ALIASES)
    urgency = _norm_enum(args.get("urgency"), URGENCY_ALIASES)
    affected = _norm_int(args.get("affected_students"))
    missing = []
    if not school:
        missing.append("school")
    if not title:
        missing.append("title")
    if not category:
        missing.append("category")
    if not urgency:
        missing.append("urgency")
    if affected is None:
        missing.append("affected_students")
    obs = _proposal("create_incident", {
        "school_id": school["school_id"] if school else None,
        "school_name": school.get("school_name") if school else None,
        "title": title or None,
        "category": category,
        "urgency": urgency,
        "affected_students": affected,
    }, missing)
    if hint and not school:
        obs["hint_unmatched"] = hint
        obs["school_choices"] = _school_choices(context)
    return obs


def tool_prepare_maintenance_log(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Prépare un journal d'intervention COMPLET (sans rien écrire) : incident, coût, notes."""
    raw = args.get("incident")
    hint = str(raw or "").strip()
    candidates = _match_incidents(context, raw)
    incident = candidates[0] if len(candidates) == 1 else None
    cost = _norm_cost(args.get("cost_amount"))
    notes = str(args.get("notes") or "").strip() or None
    days = _norm_int(args.get("days_without_service"))
    missing = []
    if not incident:
        missing.append("incident")
    if cost is None:
        missing.append("cost_amount")
    label = None
    if incident:
        label = f"{incident.get('reference_code') or incident.get('id')} — {incident.get('title', '?')}"
    obs = _proposal("create_maintenance_log", {
        "incident_id": incident.get("id") if incident else None,
        "incident_ref": None if incident else (raw if hint else None),
        "incident_label": label,
        "cost_amount": cost,
        "notes": notes,
        "days_without_service": days,
    }, missing)
    if hint and not incident:
        obs["hint_unmatched"] = hint
        pool = candidates if candidates else _open_incidents(context)
        obs["incident_choices"] = _incident_choices(pool)
        if len(candidates) > 1:
            obs["candidates"] = [_candidate_card(c) for c in candidates[:5]]
    return obs


URGENCY_FR = {"critical": "critique", "high": "haute", "medium": "moyenne", "low": "basse"}


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _fmt_1(value: Any) -> str:
    try:
        return f"{float(value):.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0,0"


CAT_FR = {"water_point": "point d'eau", "toilets_latrines": "latrines",
          "handwashing": "lavage des mains", "sewage_drainage": "évacuation"}


def tool_build_briefing(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Assemble un mini-dossier de briefing (diaporama) déterministe."""
    district = str(args.get("district") or "").strip()
    dlow = district.lower()
    schools = [s for s in context.get("schools", [])
               if not dlow or str(s.get("district", "")).lower() == dlow]
    sids = {s.get("school_id") for s in schools}
    open_incs = [i for i in _open_incidents(context) if i.get("school_id") in sids]
    weights = {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 0.5}
    affected = sum(int(i.get("affected_students", 0) or 0) for i in open_incs)
    now = datetime.now(timezone.utc)

    top = sorted(open_incs,
                 key=lambda i: (weights.get(str(i.get("urgency", "low")), 0.0),
                                int(i.get("affected_students", 0) or 0)),
                 reverse=True)[:3]
    priorities = [
        f"{i.get('school_name', '?')} — {i.get('title', '?')} "
        f"({URGENCY_FR.get(str(i.get('urgency')), str(i.get('urgency')))}, "
        f"{_fmt_int(i.get('affected_students', 0))} élèves)"
        for i in top
    ] or ["Aucune priorité : calme plat sur ce territoire."]

    actions: list[str] = []
    crit = [i for i in open_incs if str(i.get("urgency")) == "critical"]
    if crit:
        names = ", ".join(sorted({str(i.get("school_name", "?")) for i in crit}))
        actions.append(
            f"Intervenir en priorité sur "
            f"{_plural(len(crit), '1 incident critique', f'{len(crit)} incidents critiques')} : {names}."
        )
    old = [i for i in open_incs
           if (dt := _parse_dt(i.get("reported_at"))) is not None and (now - dt).days > 7]
    if old:
        actions.append(
            f"{_plural(len(old), '1 incident ouvert', f'{len(old)} incidents ouverts')} "
            "depuis plus de 7 jours : planifier la relance."
        )
    by_district: dict[str, int] = {}
    for i in open_incs:
        by_district[str(i.get("district", "?"))] = by_district.get(str(i.get("district", "?")), 0) + 1
    grouped = [d for d, n in by_district.items() if n >= 2]
    if grouped:
        actions.append(f"Tournée groupée possible : {', '.join(sorted(grouped))}.")
    if not actions:
        actions.append("Aucune action urgente : maintenir la surveillance.")

    slides = [
        {"kind": "cover",
         "title": f"Briefing WASH — {district or 'Territoire'}",
         "subtitle": f"{now.day} {FRENCH_MONTHS[now.month]} {now.year} · {district or 'tous districts'}",
         "lines": [],
         "stats": [
             {"label": "Incidents ouverts", "value": str(len(open_incs))},
             {"label": "Élèves affectés", "value": _fmt_int(affected)},
             {"label": "Écoles suivies", "value": str(len(schools))},
         ]},
        {"kind": "bullets", "title": "Priorités", "lines": priorities, "stats": []},
        {"kind": "bullets", "title": "Actions recommandées", "lines": actions, "stats": []},
    ]
    return {
        "district": district or None,
        "slides": slides,
        "total": len(slides),
        "generated_at": now.isoformat(),
    }


def tool_territory_overview(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Vue géographique du territoire : écoles géolocalisées + urgences ouvertes."""
    district = str(args.get("district") or "").strip().lower()
    weights = {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 0.5}
    points: list[dict[str, Any]] = []
    missing: list[str] = []
    for school in context.get("schools", []):
        if district and str(school.get("district", "")).lower() != district:
            continue
        open_incs = [i for i in _open_incidents(context) if i.get("school_id") == school.get("school_id")]
        affected = sum(int(i.get("affected_students", 0) or 0) for i in open_incs)
        top = max(
            (str(i.get("urgency", "low")) for i in open_incs),
            key=lambda u: weights.get(u, 0.0),
            default=None,
        )
        lat = school.get("latitude", school.get("lat"))
        lng = school.get("longitude", school.get("lng"))
        try:
            lat = float(lat) if lat is not None else None
            lng = float(lng) if lng is not None else None
        except (TypeError, ValueError):
            lat, lng = None, None
        if lat is None or lng is None:
            missing.append(str(school.get("school_name", "?")))
            continue
        points.append({
            "school_id": school.get("school_id"),
            "school_name": school.get("school_name"),
            "district": school.get("district"),
            "lat": lat,
            "lng": lng,
            "open_incidents": len(open_incs),
            "affected_students": affected,
            "top_urgency": top,
        })
    crit = sum(1 for s in points if s["top_urgency"] == "critical")
    if crit:
        insight = (f"{crit} {_plural(crit, 'urgence critique', 'urgences critiques')} "
                   f"sur {len(points)} écoles géolocalisées.")
    elif points:
        insight = f"{len(points)} écoles géolocalisées, aucune urgence critique."
    else:
        insight = "Aucune école géolocalisée sur ce territoire."
    return {
        "district": args.get("district"),
        "schools": points,
        "missing_gps": missing,
        "total": len(points),
        "open_incidents": sum(s["open_incidents"] for s in points),
        "insight": insight,
    }


def tool_repair_trends(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Tendances mensuelles d'une école : pannes, coûts de réparation, jours sans service."""
    district = str(args.get("district") or "").strip()
    dlow = district.lower()
    school = _resolve_school(context, args.get("school"))
    if not school:
        return {"error": f"École '{args.get('school')}' introuvable. Écoles valides : {_school_choices(context)}. Réessaie avec un nom ou un id exact."}
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

    if total_cost > 0 and costs:
        peak = max(range(len(costs)), key=lambda i: costs[i])
        share = round(costs[peak] / total_cost * 100)
        insight = f"{share} % des coûts concentrés en {labels[peak].lower()}."
    else:
        insight = "Aucun coût de réparation sur la période."

    # --- Enrichissement graphes (défensif, optionnel à la lecture) : portée
    # district si un district est passé, sinon échelle du contexte entier. ---
    scope_schools = [s for s in context.get("schools", [])
                     if not dlow or str(s.get("district", "")).lower() == dlow]
    scope_sids = {s.get("school_id") for s in scope_schools}
    bucket_set = set(buckets)

    def _in_window(value: Any) -> bool:
        key = month_key(value)
        return key in bucket_set if key else False

    def _safe_cost(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _safe_days(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    scope_logs = [l for l in context.get("maintenance_logs", [])
                  if l.get("school_id") in scope_sids and _in_window(l.get("repaired_at"))]
    scope_recent = [i for i in context.get("recent_incidents", [])
                    if i.get("school_id") in scope_sids]
    per_rows: dict[Any, dict[str, Any]] = {}
    for scope_school in scope_schools:
        sid = scope_school.get("school_id")
        per_rows[sid] = {
            "school_id": sid,
            "school_name": scope_school.get("school_name"),
            "nom": scope_school.get("school_name"),
            "cost": 0.0, "cout": 0.0, "incidents": 0, "pannes": 0,
        }
    for log in scope_logs:
        row = per_rows.get(log.get("school_id"))
        if row is not None:
            row["cost"] = round(row["cost"] + _safe_cost(log.get("cost_amount")), 2)
            row["cout"] = row["cost"]
    windowed_recent = [i for i in scope_recent if _in_window(i.get("reported_at"))]
    for incident in windowed_recent:
        row = per_rows.get(incident.get("school_id"))
        if row is not None:
            row["incidents"] += 1
            row["pannes"] += 1
    per_school = sorted(per_rows.values(), key=lambda r: r["cost"], reverse=True)[:5]
    urgency_fr = {"critical": "critique", "high": "haute",
                  "medium": "moyenne", "low": "basse"}
    by_urgency = {"critique": 0, "haute": 0, "moyenne": 0, "basse": 0}
    for incident in scope_recent:
        fr = urgency_fr.get(str(incident.get("urgency", "")).lower())
        if fr:
            by_urgency[fr] += 1
    scope_cost = round(sum(_safe_cost(l.get("cost_amount")) for l in scope_logs), 2)
    scope_days = sum(_safe_days(l.get("days_without_service")) for l in scope_logs)
    totals = {
        "cost": scope_cost, "cout": scope_cost,
        "incidents": len(windowed_recent), "pannes": len(windowed_recent),
        "days": scope_days, "jours": scope_days,
    }
    return {
        "school_id": school_id,
        "school_name": school.get("school_name"),
        "months": months,
        "insight": insight,
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
        "district": district or None,
        "per_school": per_school,
        "by_urgency": by_urgency,
        "totals": totals,
    }


def _log_day(log: dict[str, Any]) -> str:
    """Jour AAAA-MM-JJ d'un journal : created_at, repli repaired_at/reported_at."""
    for key in ("created_at", "repaired_at", "reported_at"):
        value = log.get(key)
        if value and len(str(value).strip()) >= 10:
            return str(value).strip()[:10]
    return ""


def _log_matches_school(log: dict[str, Any], hint: Any, context: dict[str, Any]) -> bool:
    """Filtre école : id exact ou fragment de nom (insensible à la casse)."""
    if hint is None or str(hint).strip() == "":
        return True
    try:
        if log.get("school_id") == int(hint):
            return True
    except (TypeError, ValueError):
        pass
    resolved = _resolve_school(context, hint)
    if resolved and log.get("school_id") == resolved.get("school_id"):
        return True
    name = str(log.get("school_name") or "").lower()
    candidates = {str(hint).strip().lower()}
    if resolved:
        candidates.add(str(resolved.get("school_name", "")).lower())
    return any(c and c in name for c in candidates)


def _school_hint_matches_known(hint: Any, context: dict[str, Any]) -> bool:
    """Le hint école désigne-t-il au moins une école connue du contexte ?

    Comparaison insensible à la casse, sous-chaîne dans les deux sens, sur
    les school_name des écoles du contexte, des journaux et des incidents.
    Un hint vide (pas de filtre) ou un id exact connu → True.
    """
    if hint is None or str(hint).strip() == "":
        return True
    raw = str(hint).strip()
    try:
        wanted = int(raw)
    except (TypeError, ValueError):
        wanted = None
    if wanted is not None:
        for pool in (context.get("schools", []), context.get("maintenance_logs", []),
                     context.get("incidents", [])):
            for row in pool:
                if isinstance(row, dict) and row.get("school_id") == wanted:
                    return True
        return False
    low = raw.lower()
    names: list[str] = []
    for pool in (context.get("schools", []), context.get("maintenance_logs", []),
                 context.get("incidents", [])):
        for row in pool:
            if isinstance(row, dict):
                names.append(str(row.get("school_name") or ""))
    for name in names:
        nlow = name.strip().lower()
        if not nlow:
            continue
        if low in nlow or nlow in low:
            return True
    return False


def tool_list_maintenance_logs(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Liste les interventions DÉJÀ réalisées et journalisées (lecture seule)."""
    today = datetime.now(timezone.utc).date().isoformat()
    raw_date = str(args.get("date") or "").strip()
    candidate = raw_date[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", raw_date) else ""
    try:
        date = datetime.strptime(candidate, "%Y-%m-%d").date().isoformat() if candidate else today
    except ValueError:
        date = today
    hint = args.get("school")
    matched = _school_hint_matches_known(hint, context)
    effective_hint = hint if matched else None
    try:
        limit = int(args.get("limit", 10) or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = min(max(limit, 1), 50)

    filtered = [
        log for log in context.get("maintenance_logs", [])
        if _log_day(log) == date and _log_matches_school(log, effective_hint, context)
    ]
    total = len(filtered)
    applied_filters = {"date": date, "school_raw": hint, "school_matched": matched}
    prefix = ""
    if not matched:
        prefix = f"École {str(hint).strip()} non reconnue — filtre ignoré. "
    if not filtered:
        return {"date": date, "items": [], "total": 0,
                "insight": f"{prefix}Aucune intervention journalisée le {date}.",
                "applied_filters": applied_filters, "is_empty": True}
    names: list[str] = []
    for log in filtered:
        name = str(log.get("school_name") or "").strip()
        if name and name not in names:
            names.append(name)
    head = (f"{total} {_plural(total, 'intervention journalisée', 'interventions journalisées')} "
            f"le {date}")
    if names:
        shown = ", ".join(names[:3])
        extra = f" (+{len(names) - 3})" if len(names) > 3 else ""
        insight = f"{head} : {shown}{extra}."
    else:
        insight = f"{head}."
    items = [{
        "id": log.get("id"),
        "incident_id": log.get("incident_id"),
        "incident_ref": log.get("incident_ref") or log.get("reference_code"),
        "incident_title": log.get("incident_title") or log.get("title"),
        "school_name": log.get("school_name"),
        "cost_amount": log.get("cost_amount"),
        "notes": log.get("notes"),
        "created_at": log.get("created_at") or log.get("repaired_at"),
    } for log in filtered[:limit]]
    return {"date": date, "items": items, "total": total, "insight": f"{prefix}{insight}",
            "applied_filters": applied_filters, "is_empty": False}


TOOL_EXECUTORS = {
    "analyze_school": tool_analyze_school,
    "rank_schools_by_need": tool_rank_schools_by_need,
    "summarize_district": tool_summarize_district,
    "explain_incident": tool_explain_incident,
    "prepare_report": tool_prepare_report,
    "prepare_incident": tool_prepare_incident,
    "prepare_maintenance_log": tool_prepare_maintenance_log,
    "repair_trends": tool_repair_trends,
    "territory_overview": tool_territory_overview,
    "build_briefing": tool_build_briefing,
    "list_maintenance_logs": tool_list_maintenance_logs,
}

AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_school",
            "description": "Analyse complète d'une école (nom approximatif accepté) : pannes ouvertes, coûts de maintenance et arbitrage réparer-remplacer.",
            "parameters": {
                "type": "object",
                "properties": {"school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école"}},
                "required": ["school"],
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
            "name": "list_maintenance_logs",
            "description": "Liste les interventions DEJA réalisées et journalisées (lecture seule) : filtres date AAAA-MM-JJ défaut aujourd'hui, école, limite. Pour toute question sur les interventions passées. Ne crée rien. Exemple : « donne-moi les interventions réalisées aujourd'hui » → list_maintenance_logs avec la date du jour.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Jour filtré au format AAAA-MM-JJ (défaut : aujourd'hui)"},
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école (optionnel)"},
                    "limit": {"type": "integer", "description": "Nombre max d'interventions (défaut 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repair_trends",
            "description": "Tendances mensuelles d'une école sur N mois : pannes, coûts de réparation, jours sans service. À utiliser pour tout historique, tendance ou graphique. Option district pour comparer les écoles (top 5, urgences, totaux).",
            "parameters": {
                "type": "object",
                "properties": {
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école"},
                    "months": {"type": "integer", "description": "Nombre de mois d'historique (1 à 12, défaut 3)"},
                    "district": {"type": "string", "description": "Filtrer la comparaison inter-écoles sur un district (optionnel)"},
                },
                "required": ["school"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_briefing",
            "description": "Génère un mini-dossier de briefing (diaporama) : couverture chiffrée, priorités, actions recommandées.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {"type": "string", "description": "Filtrer sur un district (optionnel)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "territory_overview",
            "description": "Vue géographique du territoire : écoles géolocalisées avec urgences et incidents ouverts. À utiliser pour toute carte ou question 'où'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {"type": "string", "description": "Filtrer sur un district (optionnel)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_report",
            "description": "Prépare la CREATION d'un SIGNALEMENT (nouvelle panne signalée), dossier (complet ou partiel) sans rien écrire. UNIQUEMENT quand l'utilisateur veut CREER. Ne JAMAIS utiliser pour lister/consulter/résumer (voir list_maintenance_logs, explain_incident, summarize_district). Accepte tout sous-ensemble d'arguments, même vide, et retourne missing + questions courtes (2 max). Exemple : « je signale une fuite aux latrines » → prepare_report ; « liste les signalements » → outils de lecture, pas cet outil.",
            "parameters": {
                "type": "object",
                "properties": {
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école"},
                    "description": {"type": "string", "description": "Description libre de la panne"},
                    "category": {"type": "string", "description": "water_point, toilets_latrines, handwashing ou sewage_drainage"},
                    "urgency": {"type": "string", "description": "low, medium, high ou critical"},
                    "affected_students": {"type": "integer", "description": "Nombre d'élèves affectés"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_incident",
            "description": "Prépare la CREATION d'un INCIDENT (nouvelle panne), dossier (complet ou partiel) sans rien écrire. UNIQUEMENT quand l'utilisateur veut CREER. Ne JAMAIS utiliser pour lister/consulter/résumer (voir list_maintenance_logs, explain_incident, summarize_district). Accepte tout sous-ensemble d'arguments, même vide, et retourne missing + questions courtes (2 max). Exemple : « signale une panne de pompe à Ngok » → prepare_incident ; « montre les interventions réalisées » → list_maintenance_logs, pas cet outil.",
            "parameters": {
                "type": "object",
                "properties": {
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école"},
                    "title": {"type": "string", "description": "Titre court de l'intervention"},
                    "category": {"type": "string", "description": "water_point, toilets_latrines, handwashing ou sewage_drainage"},
                    "urgency": {"type": "string", "description": "low, medium, high ou critical"},
                    "affected_students": {"type": "integer", "description": "Nombre d'élèves affectés"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_maintenance_log",
            "description": "Prépare la CREATION d'un JOURNAL d'intervention (travaux à consigner), dossier (complet ou partiel) sans rien écrire. UNIQUEMENT quand l'utilisateur veut CREER ou journaliser. Ne JAMAIS utiliser pour lister/consulter/résumer (voir list_maintenance_logs, explain_incident, summarize_district). Accepte tout sous-ensemble d'arguments, même vide (incident seul, coût seul, notes seules), et retourne missing + questions courtes (2 max). Exemple : « journalise des travaux à 50000 XAF » → prepare_maintenance_log ; « quelles interventions réalisées ? » → list_maintenance_logs, pas cet outil.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident": {"type": "string", "description": "Titre même approximatif, identifiant ou référence (WASH-...) de l'incident"},
                    "cost_amount": {"type": "number", "description": "Coût de l'intervention en XAF"},
                    "notes": {"type": "string", "description": "Notes sur les travaux effectués"},
                    "days_without_service": {"type": "integer", "description": "Jours sans service comptabilisés"},
                },
            },
        },
    },
]
