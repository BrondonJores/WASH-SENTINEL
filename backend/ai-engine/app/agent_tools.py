from __future__ import annotations

import difflib
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
    _DOUALA_TZ = ZoneInfo("Africa/Douala")
    _DOUALA_TZ_NAME = "Africa/Douala"
except Exception:
    # Repli documenté : journées civiles UTC (voir payload calendar_heatmap).
    _DOUALA_TZ = timezone.utc
    _DOUALA_TZ_NAME = "UTC (repli, base Afrique/Douala indisponible)"

from .decision_agent import DecisionAgent
from .replacement_cost import resolve_replacement_cost
from .schemas import SchoolMaintenanceHistory
from .textnorm import (
    PLACE_CUTOFF,
    dedup_incidents as _dedup_incidents,
    fold,
    parse_dt as _parse_dt,
    score_place,
)
from .tool_consts import INCIDENT_FUZZY_MIN_RATIO, tool_lang


def _env_float(name: str, default: float) -> float:
    """Override ENV typé ; défaut historique inchangé si absent/invalide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    """Override ENV typé ; défaut historique inchangé si absent/invalide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


#: Fenêtre du calendrier des pannes (jours ; hérité, cf. thresholds.py AXE 8).
#: Override ENV : AGENT_TOOLS_HEATMAP_WINDOW_DAYS (défaut historique 90).
HEATMAP_WINDOW_DAYS = _env_int("AGENT_TOOLS_HEATMAP_WINDOW_DAYS", 90)
#: Noms d'écoles proposés en retry ("Écoles valides : ...").
#: Override ENV : AGENT_TOOLS_SCHOOL_CHOICES_LIMIT (défaut historique 10).
SCHOOL_CHOICES_LIMIT = _env_int("AGENT_TOOLS_SCHOOL_CHOICES_LIMIT", 10)
#: Références d'incidents proposées en retry + cartes de choix cliquables.
#: Override ENV : AGENT_TOOLS_INCIDENT_CHOICES_LIMIT (défaut historique 5).
INCIDENT_CHOICES_LIMIT = _env_int("AGENT_TOOLS_INCIDENT_CHOICES_LIMIT", 5)
#: Top écoles du comparatif budgétaire.
#: Override ENV : AGENT_TOOLS_BUDGET_COMPARE_TOP (défaut historique 5).
BUDGET_COMPARE_TOP = _env_int("AGENT_TOOLS_BUDGET_COMPARE_TOP", 5)
#: Lignes per_school du payload repair_trends.
#: Override ENV : AGENT_TOOLS_TRENDS_PER_SCHOOL_TOP (défaut historique 5).
TRENDS_PER_SCHOOL_TOP = _env_int("AGENT_TOOLS_TRENDS_PER_SCHOOL_TOP", 5)
#: Limite par défaut de list_maintenance_logs.
#: Override ENV : AGENT_TOOLS_MAINTENANCE_LOGS_LIMIT (défaut historique 10).
MAINTENANCE_LOGS_DEFAULT_LIMIT = _env_int("AGENT_TOOLS_MAINTENANCE_LOGS_LIMIT", 10)
#: Bornes de clamp de cette limite.
#: Overrides ENV : AGENT_TOOLS_MAINTENANCE_LOGS_MIN/MAX (défauts 1/50).
MAINTENANCE_LOGS_LIMIT_MIN = _env_int("AGENT_TOOLS_MAINTENANCE_LOGS_MIN", 1)
MAINTENANCE_LOGS_LIMIT_MAX = _env_int("AGENT_TOOLS_MAINTENANCE_LOGS_MAX", 50)
#: Limite par défaut de list_incidents (signalements déclarés).
#: Override ENV : AGENT_TOOLS_LIST_INCIDENTS_LIMIT (défaut 10).
LIST_INCIDENTS_DEFAULT_LIMIT = _env_int("AGENT_TOOLS_LIST_INCIDENTS_LIMIT", 10)
#: Bornes de clamp de cette limite.
#: Overrides ENV : AGENT_TOOLS_LIST_INCIDENTS_MIN/MAX (défauts 1/50).
LIST_INCIDENTS_LIMIT_MIN = _env_int("AGENT_TOOLS_LIST_INCIDENTS_MIN", 1)
LIST_INCIDENTS_LIMIT_MAX = _env_int("AGENT_TOOLS_LIST_INCIDENTS_MAX", 50)
#: Seuil de tendance des coûts (ratio mois courant vs moyenne passée).
#: Override ENV : AGENT_TOOLS_TREND_RATIO_THRESHOLD (défaut historique 0.15).
TREND_RATIO_THRESHOLD = _env_float("AGENT_TOOLS_TREND_RATIO_THRESHOLD", 0.15)


def _open_incidents(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in context.get("incidents", []) if i.get("status") not in ("resolved", "closed")]


# ---------------------------------------------------------------------------
# PÉRIMÈTRE TEMPOREL : filtrage déterministe incidents/logs par période.
# Quand le chat détecte une période exprimée (parse_time_window, agent_loop),
# le contexte d'exécution est restreint aux lignes de la période : les outils
# gardent leur sémantique (ouverts, etc.) sur ce sous-ensemble. Comparaison
# en date civile (pas datetime), bornes incluses ; une ligne sans date
# prouvée dans la période est exclue (on ne prétend jamais « signalé
# aujourd'hui » sans date). Sans période : scope_context_to_window retourne
# le contexte inchangé (même objet, comportement historique).
# ---------------------------------------------------------------------------

#: Clés de date d'un incident, par priorité (signalement).
INCIDENT_WINDOW_KEYS = ("reported_at",)
#: Clés de date d'un journal, par priorité (réparation puis replis).
LOG_WINDOW_KEYS = ("repaired_at", "created_at", "reported_at")


def row_window_day(row: dict[str, Any], keys: tuple[str, ...] = INCIDENT_WINDOW_KEYS) -> date | None:
    """Jour civil d'une ligne (première clé horodatée valide), None sinon."""
    if not isinstance(row, dict):
        return None
    for key in keys:
        dt = _parse_dt(row.get(key))
        if dt is not None:
            return dt.date()
    return None


def incident_window_day(incident: dict[str, Any]) -> date | None:
    """Jour civil de signalement d'un incident (reported_at), None sinon."""
    return row_window_day(incident, INCIDENT_WINDOW_KEYS)


def log_window_day(log: dict[str, Any]) -> date | None:
    """Jour civil d'un journal (repaired_at, replis created_at/reported_at)."""
    return row_window_day(log, LOG_WINDOW_KEYS)


def in_time_window(day: date | None, start: date | None, end: date | None) -> bool:
    """Jour dans [start, end] (inclusif) ; None ou bornes absentes = False."""
    if day is None or start is None or end is None:
        return False
    return start <= day <= end


def _as_window_date(value: Any) -> date | None:
    """Normalise une borne de fenêtre (date|datetime|str ISO) en date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    dt = _parse_dt(value)
    return dt.date() if dt is not None else None


def filter_incidents_by_window(rows: list[dict[str, Any]] | None,
                               start: date | None, end: date | None) -> list[dict[str, Any]]:
    """Incidents signalés dans [start, end] (inclusif, dates civiles)."""
    return [r for r in (rows or [])
            if in_time_window(incident_window_day(r), start, end)]


def filter_logs_by_window(rows: list[dict[str, Any]] | None,
                          start: date | None, end: date | None) -> list[dict[str, Any]]:
    """Journaux réparés dans [start, end] (inclusif, dates civiles)."""
    return [r for r in (rows or [])
            if in_time_window(log_window_day(r), start, end)]


def scope_context_to_window(context: dict[str, Any], window: dict[str, Any] | None) -> dict[str, Any]:
    """Contexte restreint à la période (copie légère, listes filtrées).

    Incidents + recent_incidents par reported_at, journaux par repaired_at
    (replis created_at/reported_at). Fenêtre absente ou sans preset/bornes :
    contexte retourné tel quel (même objet, comportement historique).
    """
    if not window or not window.get("preset"):
        return context
    start = _as_window_date(window.get("start"))
    end = _as_window_date(window.get("end"))
    if start is None or end is None:
        return context
    scoped = dict(context)
    scoped["incidents"] = filter_incidents_by_window(context.get("incidents"), start, end)
    scoped["recent_incidents"] = filter_incidents_by_window(context.get("recent_incidents"), start, end)
    scoped["maintenance_logs"] = filter_logs_by_window(context.get("maintenance_logs"), start, end)
    return scoped


def _scope_place_predicate(scope: dict[str, Any] | None):  # noqa: ANN202
    """Prédicat lieu du périmètre (école(s) ou district), None si global."""
    if not scope:
        return None
    if scope.get("scope") == "school":
        schools = [s for s in (scope.get("schools") or []) if s] or (
            [scope["school"]] if scope.get("school") else [])
        folded = [fold(s) for s in schools if fold(s)]
        if not folded:
            return None

        def _match_school(row: dict[str, Any]) -> bool:
            candidate = fold(row.get("school_name", ""))
            return bool(candidate) and any(
                want == candidate or want in candidate or candidate in want
                for want in folded)
        return _match_school
    if scope.get("scope") == "district" and scope.get("district"):
        want = fold(scope.get("district"))

        def _match_district(row: dict[str, Any]) -> bool:
            candidate = fold(row.get("district", ""))
            return bool(want and candidate) and (
                want == candidate or want in candidate or candidate in want)
        return _match_district
    return None


def open_incidents_in_scope(context: dict[str, Any],
                            scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Incidents ouverts du lieu demandé (stock général, sans filtre date)."""
    predicate = _scope_place_predicate(scope)
    rows = _open_incidents(context or {})
    return [r for r in rows if predicate is None or predicate(r)]


def open_incidents_in_window(context: dict[str, Any], window: dict[str, Any] | None,
                             scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Incidents ouverts du lieu, signalés dans la période (sous-ensemble strict)."""
    if not window or not window.get("preset"):
        return open_incidents_in_scope(context, scope)
    start = _as_window_date(window.get("start"))
    end = _as_window_date(window.get("end"))
    if start is None or end is None:
        return []
    return [r for r in open_incidents_in_scope(context, scope)
            if in_time_window(incident_window_day(r), start, end)]


# ---------------------------------------------------------------------------
# SÉMANTIQUE UNIFIÉE « ÉLÈVES AFFECTÉS » (cohérence graphiques).
# Constat réel : le dispatch (maintenance_team, tournée par école) affichait
# la SOMME des affected_students des incidents ouverts de l'école (ex.
# Bonanjo « 5 incidents · 600 élèves ») tandis que la synthèse citait UN
# incident (450 élèves). La somme double-compte les mêmes élèves quand
# plusieurs pannes touchent une école.
# Règle unifiée : par école = MAX des incidents ouverts (proxy « élèves
# distincts exposés », sans double-compte) ; territoire/district = SOMME des
# max par école (jamais somme des incidents).
# Compat : les clés legacy (affected_students, total_affected_students)
# gardent la somme historique ; les clés *_max portent la valeur unifiée.
# Affiché où : dispatch/tournée, synthèse district, classement, carte,
# comparaison, observatoire, analyse école et briefings exposent les deux
# (voir chaque outil) ; le frontend lit aujourd'hui les clés legacy.
# ---------------------------------------------------------------------------

def _affected_int(value: Any) -> int:
    """Élèves d'un incident : entier >= 0, 0 si absent/invalide."""
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _affected_max(rows: list[dict[str, Any]]) -> int:
    """Max des élèves sur des incidents (0 si aucun) : proxy sans double-compte."""
    return max((_affected_int(r.get("affected_students")) for r in rows), default=0)


def _school_key(row: dict[str, Any]) -> Any:
    """Clé de regroupement école : id exact, sinon nom replié."""
    sid = row.get("school_id")
    if sid is not None:
        return ("id", sid)
    return ("nom", fold(row.get("school_name", "")))


def _affected_unified_total(open_incs: list[dict[str, Any]]) -> int:
    """Somme des max par école (règle unifiée, sans double-compte)."""
    best: dict[Any, int] = {}
    for incident in open_incs:
        key = _school_key(incident)
        best[key] = max(best.get(key, 0),
                        _affected_int(incident.get("affected_students")))
    return sum(best.values())


FRENCH_MONTHS = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                 "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
ENGLISH_MONTHS = ["", "January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]


def _resolve_school(context: dict[str, Any], ref: Any) -> dict[str, Any] | None:
    """Id exact, puis nom exact replié, puis meilleur flou (seuil balayé).

    Égalité de score en tête = ambiguïté -> None (l'appelant fait choisir
    l'utilisateur, même contrat que _resolve_incident).
    """
    schools = [s for s in context.get("schools", []) if isinstance(s, dict)]
    try:
        wanted = int(ref)
        for school in schools:
            if school.get("school_id") == wanted:
                return school
    except (TypeError, ValueError):
        pass
    hint = fold(ref)
    if not hint:
        return None
    for school in schools:
        if fold(school.get("school_name", "")) == hint:
            return school
    scored = sorted(
        ((score_place(hint, school.get("school_name", "")), i, school)
         for i, school in enumerate(schools)),
        key=lambda t: (-t[0], t[1]),
    )
    if not scored or scored[0][0] < PLACE_CUTOFF:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][2]


def _school_choices(context: dict[str, Any], limit: int = SCHOOL_CHOICES_LIMIT) -> str:
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


def _float_cost(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_calendar_heatmap(pool: list[dict[str, Any]] | None,
                           schools: list[dict[str, Any]] | None = None,
                           now: datetime | None = None,
                           days: int = HEATMAP_WINDOW_DAYS,
                           scope: str | None = None) -> dict[str, Any]:
    """Calendrier des pannes sur les `days` derniers jours (déterministe, pur).

    Journées civiles Afrique/Douala (UTC+1, sans heure d'été) ; repli UTC
    documenté dans la clé "timezone" si la base tz est indisponible.
    Chaque jour est présent même sans panne (pannes=0, liste vide).
    Unité : incidents signalés uniques (tous statuts, pool dédupliqué
    incidents+recent_incidents) ; `scope` nomme le périmètre filtré en
    amont (école ou district) quand l'appelant le connaît.
    """
    tz = _DOUALA_TZ
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    today = moment.astimezone(tz).date()
    start = today - timedelta(days=days - 1)
    names = {s.get("school_id"): s.get("school_name") for s in (schools or [])
             if isinstance(s, dict)}
    buckets: dict[str, dict[str, Any]] = {}
    for offset in range(days):
        buckets[(start + timedelta(days=offset)).isoformat()] = {"pannes": 0, "ecoles": set()}
    for incident in pool or []:
        if not isinstance(incident, dict):
            continue
        dt = _parse_dt(incident.get("reported_at"))
        if dt is None:
            continue
        day = dt.astimezone(tz).date().isoformat()
        if day not in buckets:
            continue
        buckets[day]["pannes"] += 1
        label = incident.get("school_name") or names.get(incident.get("school_id")) or "?"
        buckets[day]["ecoles"].add(str(label))
    day_rows = [
        {"date": day, "pannes": cell["pannes"], "incidents": cell["pannes"],
         "ecoles_touchees": sorted(cell["ecoles"]), "schools": sorted(cell["ecoles"])}
        for day, cell in sorted(buckets.items())
    ]
    total = sum(cell["pannes"] for cell in buckets.values())
    payload: dict[str, Any] = {
        "timezone": _DOUALA_TZ_NAME,
        "window_days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "days": day_rows,
        "total_pannes": total,
        "total_incidents": total,
        "unit": "incidents signalés (uniques, tous statuts)",
    }
    if scope:
        payload["scope"] = scope
    return payload


TIMELINE_STEPS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("signale", "Signalé", frozenset({"reported", "reporte", "signale", "new", "open", "ouvert"})),
    ("triage", "Trié", frozenset({"triaged", "triage"})),
    ("assigne", "Assigné", frozenset({"assigned", "assigne"})),
    ("en_cours", "En cours", frozenset({"in_progress", "en_cours", "ongoing"})),
    ("resolu", "Résolu", frozenset({"resolved", "closed", "resolu", "clos", "ferme"})),
)


def build_incident_timeline(incident: dict[str, Any]) -> list[dict[str, Any]]:
    """Étapes ordonnées dérivées du statut (déterministe, pur).

    Statut inconnu → niveau 0 (seul « signalé » fait). Seule l'étape
    « signalé » porte une date (reported_at), les autres None (non fourni).
    """
    status = str((incident or {}).get("status") or "").strip().lower()
    level = 0
    for index, (_, _, aliases) in enumerate(TIMELINE_STEPS):
        if status in aliases:
            level = index
            break
    reported = (incident or {}).get("reported_at")
    steps = []
    for index, (code, label, _) in enumerate(TIMELINE_STEPS):
        done = index <= level
        steps.append({
            "etape": code, "step": code, "label": label,
            "date": reported if index == 0 else None,
            "fait": done, "done": done,
        })
    return steps


WASH_BUDGET_CATEGORIES = ("water_point", "toilets_latrines", "handwashing", "sewage_drainage")


def build_budget_compare(context: dict[str, Any], district: Any = None,
                         top: int = BUDGET_COMPARE_TOP) -> dict[str, Any]:
    """Comparaison budgétaire : top écoles par cumul réparations + parts WASH.

    Cumuls = somme brute des cost_amount (XAF supposé) de maintenance_logs,
    sans filtre de date. Catégorie d'un coût, par priorité : map
    incident_categories du contexte (Laravel : incidents liés aux logs, même
    résolus/clos ou hors fenêtre — comble les trous du pool), puis incident
    lié (incident_id → incidents/recent_incidents dédupliqués), puis champ
    category du log, sinon bucket "unknown". nb_pannes = incidents +
    recent_incidents dédupliqués.
    """
    dlow = fold(district or "")
    schools = [s for s in context.get("schools", [])
               if not dlow or fold(s.get("district", "")) == dlow]
    scope_sids = {s.get("school_id") for s in schools}
    logs = [log for log in context.get("maintenance_logs", [])
            if isinstance(log, dict) and log.get("school_id") in scope_sids]
    pool = [i for i in _dedup_incidents(context.get("incidents"),
                                        context.get("recent_incidents"))
            if i.get("school_id") in scope_sids]
    cat_by_id: dict[Any, str] = {}
    for incident in pool:
        if incident.get("id") is not None and incident.get("category"):
            cat_by_id[incident["id"]] = str(incident["category"])
    # Map Laravel incident_id -> categorie (incidents liés aux logs, même
    # résolus/clos) : comble le pool quand celui-ci ne porte pas la
    # catégorie (recent_incidents minimal) ou ne contient pas l'incident.
    # Clés JSON = chaînes : on stocke les deux formes (int + brute).
    raw_map = context.get("incident_categories")
    if isinstance(raw_map, dict):
        for raw_key, category in raw_map.items():
            if not category:
                continue
            text = str(category)
            cat_by_id[raw_key] = text
            try:
                cat_by_id[int(str(raw_key))] = text
            except (TypeError, ValueError):
                pass
    rows: dict[Any, dict[str, Any]] = {}
    for school in schools:
        sid = school.get("school_id")
        rows[sid] = {
            "school_id": sid,
            "nom": school.get("school_name"),
            "school_name": school.get("school_name"),
            "cumul_reparations_XAF": 0.0,
            "total_cost_XAF": 0.0,
            "nb_pannes": 0,
            "incidents": 0,
        }
    for log in logs:
        row = rows.get(log.get("school_id"))
        if row is not None:
            cumul = round(row["cumul_reparations_XAF"] + _float_cost(log.get("cost_amount")), 2)
            row["cumul_reparations_XAF"] = cumul
            row["total_cost_XAF"] = cumul
    for incident in pool:
        row = rows.get(incident.get("school_id"))
        if row is not None:
            row["nb_pannes"] += 1
            row["incidents"] += 1
    ecoles = sorted(rows.values(),
                    key=lambda r: r["cumul_reparations_XAF"], reverse=True)[:top]
    by_category: dict[str, float] = {cat: 0.0 for cat in WASH_BUDGET_CATEGORIES}
    unknown = 0.0
    for log in logs:
        category = cat_by_id.get(log.get("incident_id")) or log.get("category")
        cost = _float_cost(log.get("cost_amount"))
        if category in by_category:
            by_category[category] = round(by_category[category] + cost, 2)
        else:
            unknown = round(unknown + cost, 2)
    if unknown:
        by_category["unknown"] = unknown
    total = round(sum(by_category.values()), 2)
    shares = {cat: (round(cost / total * 100, 1) if total > 0 else 0.0)
              for cat, cost in by_category.items()}
    return {
        "ecoles": ecoles,
        "top": top,
        "district": district or None,
        "par_categorie_XAF": dict(by_category),
        "by_category_XAF": dict(by_category),
        "parts_pct": dict(shares),
        "shares_pct": dict(shares),
        "total_XAF": total,
        "total_cost_XAF": total,
        "currency": "XAF",
    }


def tool_analyze_school(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Analyse complète d'une école : pannes ouvertes, coûts, arbitrage réparer/remplacer."""
    lang = tool_lang(context)
    use_en = lang == "en"
    school = _resolve_school(context, args.get("school", args.get("school_id")))
    if not school:
        err = ((f"School '{args.get('school', args.get('school_id'))}' not found. Valid schools: {_school_choices(context)}. Retry with an exact name or id.")
               if use_en else
               (f"École '{args.get('school', args.get('school_id'))}' introuvable. Écoles valides : {_school_choices(context)}. Réessaie avec un nom ou un id exact."))
        return {"error": err}
    school_id = school["school_id"]
    open_incs = [i for i in _open_incidents(context) if i.get("school_id") == school_id]
    # Coût sourcé (fiche école > référentiel > inconnu) : jamais de 1 500 000
    # silencieux ; à None, le verdict se passe du ratio (fréquence/jours).
    resolved = resolve_replacement_cost(school, context)
    history = SchoolMaintenanceHistory(
        school_id=school["school_id"],
        school_name=school.get("school_name", "?"),
        district=school.get("district", "?"),
        equipment_type=school.get("equipment_type", "pompe_manuelle"),
        installation_year=school.get("installation_year"),
        estimated_replacement_cost=resolved.cost if resolved.cost is not None else 0.0,
        incident_count=int(school.get("incident_count", len(open_incs))),
        total_repair_cost=float(school.get("total_repair_cost", 0.0)),
        total_days_without_service=int(school.get("total_days_without_service", 0)),
    )
    analysis = DecisionAgent.evaluate_school_equipment(history, lang)
    return {
        "school_id": school["school_id"],
        "school_name": school.get("school_name"),
        "district": school.get("district"),
        "estimated_replacement_cost": resolved.cost,
        "replacement_source": resolved.source,
        "replacement_source_names": resolved.source_names,
        "replacement_source_urls": resolved.source_urls,
        "open_incidents": [
            {"id": i.get("id"), "title": i.get("title"), "urgency": i.get("urgency"),
             "category": i.get("category"), "affected_students": i.get("affected_students", 0)}
            for i in open_incs
        ],
        # Sémantique unifiée : max par école (sans double-compte).
        "affected_students_max": _affected_max(open_incs),
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
            # Sémantique unifiée : max par école (sans double-compte).
            "affected_students_max": _affected_max(open_incs),
            "oldest_days": oldest_days,
            "top_urgency": max((str(i.get("urgency", "low")) for i in open_incs),
                               key=lambda u: weights.get(u, 0.0)),
        })
    ranking.sort(key=lambda r: r["need_score"], reverse=True)
    for position, row in enumerate(ranking, start=1):
        row["rank"] = position
    lang = tool_lang(context)
    use_en = lang == "en"
    if len(ranking) >= 2:
        gap = ranking[0]["need_score"] - ranking[1]["need_score"]
        if use_en:
            insight = (f"{ranking[0]['school_name']} leads {ranking[1]['school_name']} "
                       f"by {_fmt_1(gap, lang)} points.")
        else:
            insight = (f"{ranking[0]['school_name']} devance {ranking[1]['school_name']} "
                       f"de {_fmt_1(gap, lang)} points.")
    elif ranking:
        insight = (f"{ranking[0]['school_name']} is the only school in difficulty."
                   if use_en else
                   f"{ranking[0]['school_name']} est la seule école en difficulté.")
    else:
        insight = ("No school in difficulty for now."
                   if use_en else "Aucune école en difficulté pour le moment.")
    return {"ranking": ranking, "total": len(ranking), "insight": insight}


def tool_summarize_district(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Synthèse chiffrée : urgences, catégories, élèves affectés.

    total_affected_students = somme historique (double-compte à l'école) ;
    total_affected_students_max = somme des max par école (règle unifiée,
    même valeur que le dispatch maintenance_team par école).
    """
    open_incs = _open_incidents(context)
    by_urgency: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for i in open_incs:
        by_urgency[str(i.get("urgency", "?"))] = by_urgency.get(str(i.get("urgency", "?")), 0) + 1
        by_category[str(i.get("category", "?"))] = by_category.get(str(i.get("category", "?")), 0) + 1
    lang = tool_lang(context)
    use_en = lang == "en"
    if by_category and open_incs:
        top_cat = max(by_category, key=lambda k: by_category[k])
        n = int(by_category[top_cat])
        total = len(open_incs)
        label = (CAT_EN if use_en else CAT_FR).get(top_cat, top_cat)
        if n == total:
            if use_en:
                insight = (f"All {total} {_plural(total, 'open incident', 'open incidents')} "
                           f"concern \u00ab {label} \u00bb.")
            else:
                insight = (f"Tous les {total} {_plural(total, 'incident ouvert', 'incidents ouverts')} "
                           f"concernent « {label} ».")
        else:
            if use_en:
                insight = (f"Leading: {n} {_plural(n, 'incident', 'incidents')} "
                           f"\u00ab {label} \u00bb out of {total} total.")
            else:
                insight = (f"En tête : {n} {_plural(n, 'incident', 'incidents')} "
                           f"« {label} » sur {total} au total.")
    else:
        insight = ("No open incidents in this territory."
                   if use_en else "Aucun incident ouvert sur ce territoire.")
    return {
        "open_incidents": len(open_incs),
        "by_urgency": by_urgency,
        "by_category": by_category,
        "total_affected_students": sum(int(i.get("affected_students", 0) or 0) for i in open_incs),
        # Sémantique unifiée : somme des max par école (sans double-compte).
        "total_affected_students_max": _affected_unified_total(open_incs),
        "schools_involved": sorted({str(i.get("school_name", "?")) for i in open_incs}),
        "insight": insight,
    }


def tool_explain_incident(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Détail factuel d'un incident pour l'expliquer en langage clair."""
    incident_id = args.get("incident_id")
    incident = next((i for i in context.get("incidents", []) if i.get("id") == incident_id), None)
    if not incident:
        # L'utilisateur donne une référence (WASH-2026-XXXX), pas un id numérique.
        incident = _resolve_incident(context, incident_id)
    lang = tool_lang(context)
    use_en = lang == "en"
    if not incident:
        err = ((f"Incident {incident_id} not found. Choices: {_incident_choices(context.get('incidents', []))}")
               if use_en else
               (f"Incident {incident_id} introuvable. Choix : {_incident_choices(context.get('incidents', []))}"))
        return {"error": err}
    dt = _parse_dt(incident.get("reported_at"))
    months = ENGLISH_MONTHS if use_en else FRENCH_MONTHS
    since = (f", reported on {months[dt.month]} {dt.day}" if dt and use_en
             else f", signalé le {dt.day} {months[dt.month]}" if dt else "")
    if use_en:
        insight = (f"Priority {_fmt_1(incident.get('priority_score', 0), lang)}/100: "
                   f"{_fmt_int(incident.get('affected_students', 0))} pupils affected{since}.")
    else:
        insight = (f"Priorité {_fmt_1(incident.get('priority_score', 0), lang)}/100 : "
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
        "timeline": build_incident_timeline(incident),
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

SLOT_LABELS_EN = {
    "school": "the school concerned",
    "description": "the breakdown description",
    "title": "the intervention title",
    "category": "the category (water point, latrines, handwashing, drainage)",
    "urgency": "the urgency level (low, medium, high, critical)",
    "affected_students": "the number of pupils affected",
    "incident": "the incident concerned (title, number or reference)",
    "cost_amount": "the intervention cost in XAF",
}

SLOT_QUESTIONS_EN = {
    "school": "Which school is concerned?",
    "description": "Describe the breakdown in a few words?",
    "title": "Which title for the intervention?",
    "category": "Which category (water point, latrines, handwashing, drainage)?",
    "urgency": "Which urgency level (low, medium, high, critical)?",
    "affected_students": "How many pupils are affected?",
    "incident": "Which incident is concerned (title or reference)?",
    "cost_amount": "What is the intervention cost in XAF?",
}

ACTION_TITLES_EN = {
    "create_report": "New report",
    "create_incident": "New intervention",
    "create_maintenance_log": "Log an intervention",
}

_SLOT_ROW_LABELS = {
    "school_name": "École", "description": "Description", "title": "Titre",
    "category": "Catégorie", "urgency": "Urgence",
    "affected_students": "Élèves affectés", "cost_amount": "Coût (XAF)",
    "notes": "Notes", "days_without_service": "Jours sans service",
    "incident_label": "Incident",
}

_SLOT_ROW_LABELS_EN = {
    "school_name": "School", "description": "Description", "title": "Title",
    "category": "Category", "urgency": "Urgency",
    "affected_students": "Pupils affected", "cost_amount": "Cost (XAF)",
    "notes": "Notes", "days_without_service": "Days without service",
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


def _resolve_incident(context: dict[str, Any], ref: Any) -> dict[str, Any] | None:
    """Un seul candidat → résolu ; zéro ou ambigu → None (l'appelant fait choisir)."""
    matches = _match_incidents(context, ref)
    return matches[0] if len(matches) == 1 else None


def _incident_choices(incidents: list[dict[str, Any]], limit: int = INCIDENT_CHOICES_LIMIT) -> str:
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


def _recap(action: str, slots: dict[str, Any], missing_labels: list[str],
         lang: str = "fr") -> str:
    use_en = str(lang or "fr").lower().startswith("en")
    row_labels = _SLOT_ROW_LABELS_EN if use_en else _SLOT_ROW_LABELS
    rows = []
    for key, value in slots.items():
        if value is None or value == "" or key in ("school_id", "incident_id"):
            continue
        sep = ": " if use_en else " : "
        rows.append(f"{row_labels.get(key, key)}{sep}{value}")
    titles = ACTION_TITLES_EN if use_en else ACTION_TITLES
    text = titles.get(action, action) + "\n" + "\n".join(rows)
    if missing_labels:
        missing_word = "Missing" if use_en else "Manquant"
        text += f"\n{missing_word}{': ' if use_en else ' : '}" + ", ".join(missing_labels) + "."
    return text


def _proposal(action: str, slots: dict[str, Any], missing: list[str],
              lang: str = "fr") -> dict[str, Any]:
    use_en = str(lang or "fr").lower().startswith("en")
    slot_labels = SLOT_LABELS_EN if use_en else SLOT_LABELS
    slot_questions = SLOT_QUESTIONS_EN if use_en else SLOT_QUESTIONS
    labels = [slot_labels[m] for m in missing]
    questions = [slot_questions[m] for m in missing[:2] if m in slot_questions]
    return {
        "action": action,
        "complete": not missing,
        "slots": slots,
        "missing": missing,
        "missing_labels": labels,
        "questions": questions,
        "recap": _recap(action, slots, labels, lang),
    }


def _prepare_creation(kind: str, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Coeur commun report/incident : slots partagés + slot distinctif.

    kind="report" : signalement (description libre, school_hint accepté).
    kind="incident" : intervention directe (titre court). Observations
    identiques aux anciennes implémentations séparées.
    """
    if kind == "report":
        school = _resolve_school(context, args.get("school", args.get("school_hint")))
        hint = str(args.get("school", args.get("school_hint")) or "").strip()
        action, slot = "create_report", "description"
    else:
        school = _resolve_school(context, args.get("school"))
        hint = str(args.get("school") or "").strip()
        action, slot = "create_incident", "title"
    text = str(args.get(slot) or "").strip()
    category = _norm_enum(args.get("category"), CATEGORY_ALIASES)
    urgency = _norm_enum(args.get("urgency"), URGENCY_ALIASES)
    affected = _norm_int(args.get("affected_students"))
    missing = []
    if not school:
        missing.append("school")
    if not text:
        missing.append(slot)
    if not category:
        missing.append("category")
    if not urgency:
        missing.append("urgency")
    if affected is None:
        missing.append("affected_students")
    obs = _proposal(action, {
        "school_id": school["school_id"] if school else None,
        "school_name": school.get("school_name") if school else None,
        slot: text or None,
        "category": category,
        "urgency": urgency,
        "affected_students": affected,
    }, missing, tool_lang(context))
    if hint and not school:
        obs["hint_unmatched"] = hint
        obs["school_choices"] = _school_choices(context)
    return obs


def tool_prepare_report(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Prépare un signalement COMPLET (sans rien écrire) : école, description, catégorie, urgence, élèves."""
    return _prepare_creation("report", args, context)


def tool_prepare_incident(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Prépare une intervention directe COMPLETE (sans rien écrire) : école, titre, catégorie, urgence, élèves."""
    return _prepare_creation("incident", args, context)


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
    }, missing, tool_lang(context))
    if hint and not incident:
        obs["hint_unmatched"] = hint
        pool = candidates if candidates else _open_incidents(context)
        obs["incident_choices"] = _incident_choices(pool)
        if len(candidates) > 1:
            obs["candidates"] = [_candidate_card(c) for c in candidates[:INCIDENT_CHOICES_LIMIT]]
    return obs


URGENCY_FR = {"critical": "critique", "high": "haute", "medium": "moyenne", "low": "basse"}
URGENCY_EN = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _fmt_1(value: Any, lang: str = "fr") -> str:
    """Une décimale : virgule FR (« 14,5 »), point EN (« 14.5 »)."""
    try:
        text = f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "0.0" if str(lang or "fr").lower().startswith("en") else "0,0"
    return text if str(lang or "fr").lower().startswith("en") else text.replace(".", ",")


CAT_FR = {"water_point": "point d'eau", "toilets_latrines": "latrines",
          "handwashing": "lavage des mains", "sewage_drainage": "évacuation"}
CAT_EN = {"water_point": "water point", "toilets_latrines": "latrines",
          "handwashing": "handwashing", "sewage_drainage": "drainage"}


def tool_build_briefing(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Assemble un mini-dossier de briefing (diaporama) déterministe."""
    district = str(args.get("district") or "").strip()
    dlow = fold(district)
    schools = [s for s in context.get("schools", [])
               if not dlow or fold(s.get("district", "")) == dlow]
    sids = {s.get("school_id") for s in schools}
    open_incs = [i for i in _open_incidents(context) if i.get("school_id") in sids]
    weights = {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 0.5}
    # Sémantique unifiée : somme des max par école (le texte dit la même
    # chose que les cartes, jamais le vieux total sommé double-compté).
    affected = _affected_unified_total(open_incs)
    now = datetime.now(timezone.utc)

    lang = tool_lang(context)
    use_en = lang == "en"
    urg_labels = URGENCY_EN if use_en else URGENCY_FR
    top = sorted(open_incs,
                 key=lambda i: (weights.get(str(i.get("urgency", "low")), 0.0),
                                int(i.get("affected_students", 0) or 0)),
                 reverse=True)[:3]
    if use_en:
        priorities = [
            f"{i.get('school_name', '?')} — {i.get('title', '?')} "
            f"({urg_labels.get(str(i.get('urgency')), str(i.get('urgency')))}, "
            f"{_fmt_int(i.get('affected_students', 0))} pupils)"
            for i in top
        ] or ["No priorities: all quiet in this territory."]
    else:
        priorities = [
            f"{i.get('school_name', '?')} — {i.get('title', '?')} "
            f"({urg_labels.get(str(i.get('urgency')), str(i.get('urgency')))}, "
            f"{_fmt_int(i.get('affected_students', 0))} élèves)"
            for i in top
        ] or ["Aucune priorité : calme plat sur ce territoire."]

    actions: list[str] = []
    crit = [i for i in open_incs if str(i.get("urgency")) == "critical"]
    if crit:
        names = ", ".join(sorted({str(i.get("school_name", "?")) for i in crit}))
        if use_en:
            actions.append(
                f"Intervene first on "
                f"{_plural(len(crit), '1 critical incident', f'{len(crit)} critical incidents')}: {names}."
            )
        else:
            actions.append(
                f"Intervenir en priorité sur "
                f"{_plural(len(crit), '1 incident critique', f'{len(crit)} incidents critiques')} : {names}."
            )
    old = [i for i in open_incs
           if (dt := _parse_dt(i.get("reported_at"))) is not None and (now - dt).days > 7]
    if old:
        if use_en:
            actions.append(
                f"{_plural(len(old), '1 open incident', f'{len(old)} open incidents')} "
                "for over 7 days: schedule a follow-up."
            )
        else:
            actions.append(
                f"{_plural(len(old), '1 incident ouvert', f'{len(old)} incidents ouverts')} "
                "depuis plus de 7 jours : planifier la relance."
            )
    by_district: dict[str, int] = {}
    for i in open_incs:
        by_district[str(i.get("district", "?"))] = by_district.get(str(i.get("district", "?")), 0) + 1
    grouped = [d for d, n in by_district.items() if n >= 2]
    if grouped:
        if use_en:
            actions.append(f"Grouped tour possible: {', '.join(sorted(grouped))}.")
        else:
            actions.append(f"Tournée groupée possible : {', '.join(sorted(grouped))}.")
    if not actions:
        actions.append("No urgent action: maintain monitoring."
                       if use_en else
                       "Aucune action urgente : maintenir la surveillance.")

    months = ENGLISH_MONTHS if use_en else FRENCH_MONTHS
    if use_en:
        slides = [
            {"kind": "cover",
             "title": f"WASH Briefing — {district or 'Territory'}",
             "subtitle": f"{months[now.month]} {now.day}, {now.year} · {district or 'all districts'}",
             "lines": [],
             "stats": [
                 {"label": "Open incidents", "value": str(len(open_incs))},
                 {"label": "Pupils affected", "value": _fmt_int(affected)},
                 {"label": "Tracked schools", "value": str(len(schools))},
             ]},
            {"kind": "bullets", "title": "Priorities", "lines": priorities, "stats": []},
            {"kind": "bullets", "title": "Recommended actions", "lines": actions, "stats": []},
        ]
    else:
        slides = [
            {"kind": "cover",
             "title": f"Briefing WASH — {district or 'Territoire'}",
             "subtitle": f"{now.day} {months[now.month]} {now.year} · {district or 'tous districts'}",
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
        # Sémantique unifiée : somme des max par école (sans double-compte).
        "affected_students_max": _affected_unified_total(open_incs),
    }


def tool_territory_overview(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Vue géographique du territoire : écoles géolocalisées + urgences ouvertes."""
    district = fold(str(args.get("district") or ""))
    weights = {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 0.5}
    points: list[dict[str, Any]] = []
    missing: list[str] = []
    for school in context.get("schools", []):
        if district and fold(str(school.get("district", ""))) != district:
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
            # Sémantique unifiée : max par école (sans double-compte).
            "affected_students_max": _affected_max(open_incs),
            "top_urgency": top,
        })
    crit = sum(1 for s in points if s["top_urgency"] == "critical")
    lang = tool_lang(context)
    use_en = lang == "en"
    if crit:
        if use_en:
            insight = (f"{crit} {_plural(crit, 'critical emergency', 'critical emergencies')} "
                       f"across {len(points)} geolocated schools.")
        else:
            insight = (f"{crit} {_plural(crit, 'urgence critique', 'urgences critiques')} "
                       f"sur {len(points)} écoles géolocalisées.")
    elif points:
        insight = (f"{len(points)} geolocated schools, no critical emergency."
                   if use_en else
                   f"{len(points)} écoles géolocalisées, aucune urgence critique.")
    else:
        insight = ("No geolocated school in this territory."
                   if use_en else "Aucune école géolocalisée sur ce territoire.")
    return {
        "district": args.get("district"),
        "schools": points,
        "missing_gps": missing,
        "total": len(points),
        "open_incidents": sum(s["open_incidents"] for s in points),
        "insight": insight,
    }


def tool_repair_trends(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Tendances mensuelles d'une école : pannes, coûts de réparation, jours sans service.

    Unités (alignées) : « pannes » = incidents signalés uniques (pool
    dédupliqué incidents+recent_incidents, tous statuts) sur les N mois
    calendaires (tendances) / 90 derniers jours (heatmap) — les deux
    périmètres couvrent la même école ou le même district. « Jours sans
    service (consignés) » = somme des days_without_service des journaux ;
    la privation réelle en cours (ancienneté max des incidents ouverts,
    figures.service_disruption_days) est exposée à part, sans invention.
    """
    district = str(args.get("district") or "").strip()
    dlow = fold(district)
    school = _resolve_school(context, args.get("school"))
    district_sids = {s.get("school_id") for s in context.get("schools", [])
                     if dlow and fold(s.get("district", "")) == dlow}
    use_en = tool_lang(context) == "en"
    if not school and not district_sids:
        err = ((f"School '{args.get('school')}' not found. Valid schools: {_school_choices(context)}. Retry with an exact name or id.")
               if use_en else
               (f"École '{args.get('school')}' introuvable. Écoles valides : {_school_choices(context)}. Réessaie avec un nom ou un id exact."))
        return {"error": err}
    months = min(max(int(args.get("months", 3) or 3), 1), 12)
    if school:
        school_id: Any = school["school_id"]
        school_name = school.get("school_name")
        trend_sids = {school_id}
        trend_schools = [school]
        logs = [l for l in context.get("maintenance_logs", []) if l.get("school_id") == school_id]
    else:
        # Mode district : agrégation de toutes les écoles du district.
        school_id = None
        school_name = f"District {district}"
        trend_sids = set(district_sids)
        trend_schools = [s for s in context.get("schools", [])
                         if s.get("school_id") in district_sids]
        logs = [l for l in context.get("maintenance_logs", []) if l.get("school_id") in district_sids]
    # Pool unique dédupliqué (ouverts d'abord : leurs champs riches —
    # urgence, catégorie — gagnent sur les snapshots récents minimaux),
    # filtré au périmètre de la tendance (école OU district).
    trend_pool = [i for i in _dedup_incidents(context.get("incidents"),
                                             context.get("recent_incidents"))
                  if i.get("school_id") in trend_sids]
    now = datetime.now(timezone.utc)

    def month_key(value: Any) -> tuple[int, int] | None:
        dt = _parse_dt(value)
        return (dt.year, dt.month) if dt else None

    buckets = _month_buckets(months, now)
    labels, incident_counts, costs, days_lost = [], [], [], []
    trend_months = ENGLISH_MONTHS if use_en else FRENCH_MONTHS
    for year, month in buckets:
        labels.append(f"{trend_months[month]} {year}")
        incident_counts.append(sum(1 for i in trend_pool if month_key(i.get("reported_at")) == (year, month)))
        month_logs = [l for l in logs if month_key(l.get("repaired_at")) == (year, month)]
        costs.append(round(sum(float(l.get("cost_amount", 0) or 0) for l in month_logs), 2))
        days_lost.append(sum(int(l.get("days_without_service", 0) or 0) for l in month_logs))

    total_cost = round(sum(costs), 2)
    total_incidents = sum(incident_counts)
    total_days = sum(days_lost)
    # Privation réelle en cours : ancienneté max des incidents OUVERTS du
    # périmètre (depuis reported_at, donnée réelle — pas les journaux).
    disruption_days = 0
    disruption_since: Any = None
    disruption_title: Any = None
    for incident in trend_pool:
        if incident.get("status") in ("resolved", "closed"):
            continue
        dt = _parse_dt(incident.get("reported_at"))
        if dt is None:
            continue
        age = max((now - dt).days, 0)
        if age > disruption_days:
            disruption_days = age
            disruption_since = incident.get("reported_at")
            disruption_title = incident.get("title") or incident.get("summary")
    avg_cost = round(total_cost / months, 2)
    previous = costs[:-1]
    avg_previous = sum(previous) / len(previous) if previous else 0.0
    if avg_previous <= 0:
        trend = "stable" if costs[-1] <= 0 else "up"
    else:
        ratio = (costs[-1] - avg_previous) / avg_previous
        trend = "up" if ratio > TREND_RATIO_THRESHOLD else (
            "down" if ratio < -TREND_RATIO_THRESHOLD else "stable")
    currency = next((str(l.get("currency") or "XAF") for l in logs if l.get("currency")), "XAF")

    if total_cost > 0 and costs:
        peak = max(range(len(costs)), key=lambda i: costs[i])
        share = round(costs[peak] / total_cost * 100)
        if use_en:
            insight = f"{share}% of costs concentrated in {labels[peak]}."
        else:
            insight = f"{share} % des coûts concentrés en {labels[peak].lower()}."
    else:
        insight = ("No repair costs over the period."
                   if use_en else "Aucun coût de réparation sur la période.")
    if disruption_days > total_days:
        if use_en:
            what = f"\u201c{disruption_title}\u201d" if disruption_title else "The ongoing breakdown"
            jour_cons = f"{total_days} {_plural(total_days, 'logged day', 'logged days')}"
            insight += (f" Real deprivation: {what} has lasted {disruption_days} days "
                        f"({jour_cons} in the journal).")
        else:
            what = f"« {disruption_title} »" if disruption_title else "La panne en cours"
            jour_cons = f"{total_days} {_plural(total_days, 'jour consigné', 'jours consignés')}"
            insight += (f" Privation réelle : {what} dure depuis {disruption_days} jours "
                        f"({jour_cons} au journal).")

    # --- Enrichissement graphes (défensif, optionnel à la lecture) : portée
    # district si un district est passé, sinon échelle du contexte entier. ---
    scope_schools = [s for s in context.get("schools", [])
                     if not dlow or fold(s.get("district", "")) == dlow]
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
    # Même pool unique qu'au-dessus, au périmètre d'enrichissement
    # (district si passé, sinon contexte entier) : les onglets Écoles /
    # Urgences / totaux comptent les mêmes incidents uniques que la courbe.
    scope_pool = [i for i in _dedup_incidents(context.get("incidents"),
                                             context.get("recent_incidents"))
                  if i.get("school_id") in scope_sids]
    per_rows: dict[Any, dict[str, Any]] = {}
    for scope_school in scope_schools:
        sid = scope_school.get("school_id")
        per_rows[sid] = {
            "school_id": sid,
            "school_name": scope_school.get("school_name"),
            "nom": scope_school.get("school_name"),
            "cost": 0.0, "cout": 0.0, "incidents": 0, "pannes": 0,
            "disruption_days": 0,
        }
    for log in scope_logs:
        row = per_rows.get(log.get("school_id"))
        if row is not None:
            row["cost"] = round(row["cost"] + _safe_cost(log.get("cost_amount")), 2)
            row["cout"] = row["cost"]
    windowed_scope = [i for i in scope_pool if _in_window(i.get("reported_at"))]
    for incident in windowed_scope:
        row = per_rows.get(incident.get("school_id"))
        if row is not None:
            row["incidents"] += 1
            row["pannes"] += 1
    # Privation réelle par école (ancienneté max des incidents ouverts).
    for incident in scope_pool:
        if incident.get("status") in ("resolved", "closed"):
            continue
        row = per_rows.get(incident.get("school_id"))
        if row is None:
            continue
        dt = _parse_dt(incident.get("reported_at"))
        if dt is None:
            continue
        row["disruption_days"] = max(row["disruption_days"], max((now - dt).days, 0))
    per_school = sorted(per_rows.values(), key=lambda r: r["cost"], reverse=True)[:TRENDS_PER_SCHOOL_TOP]
    urgency_fr = {"critical": "critique", "high": "haute",
                  "medium": "moyenne", "low": "basse"}
    by_urgency = {"critique": 0, "haute": 0, "moyenne": 0, "basse": 0}
    for incident in windowed_scope:
        fr = urgency_fr.get(str(incident.get("urgency", "")).lower())
        if fr:
            by_urgency[fr] += 1
    scope_cost = round(sum(_safe_cost(l.get("cost_amount")) for l in scope_logs), 2)
    scope_days = sum(_safe_days(l.get("days_without_service")) for l in scope_logs)
    scope_disruption = max((r["disruption_days"] for r in per_rows.values()), default=0)
    totals = {
        "cost": scope_cost, "cout": scope_cost,
        "incidents": len(windowed_scope), "pannes": len(windowed_scope),
        "days": scope_days, "jours": scope_days,
        "disruption_days": scope_disruption,
    }
    return {
        "school_id": school_id,
        "school_name": school_name,
        "months": months,
        "insight": insight,
        "labels": labels,
        "datasets": ([
            {"label": f"Repair costs ({currency})", "data": costs, "kind": "bar"},
            {"label": "Reported breakdowns (incidents)", "data": incident_counts, "kind": "line"},
            {"label": "Days without service (logged)", "data": days_lost, "kind": "line"},
        ] if use_en else [
            {"label": f"Coût réparations ({currency})", "data": costs, "kind": "bar"},
            {"label": "Pannes signalées (incidents)", "data": incident_counts, "kind": "line"},
            {"label": "Jours sans service (consignés)", "data": days_lost, "kind": "line"},
        ]),
        "figures": {
            "total_cost": total_cost,
            "currency": currency,
            "total_incidents": total_incidents,
            "total_days_lost": total_days,
            "days_without_service_logged": total_days,
            "service_disruption_days": disruption_days,
            "service_disruption_since": disruption_since,
            "avg_cost_per_month": avg_cost,
            "trend_direction": trend,
        },
        "district": district or None,
        "per_school": per_school,
        "by_urgency": by_urgency,
        "totals": totals,
        "calendar_heatmap": build_calendar_heatmap(
            trend_pool, trend_schools, scope=school_name),
        "budget_compare": build_budget_compare(context, district or None),
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
        limit = int(args.get("limit", MAINTENANCE_LOGS_DEFAULT_LIMIT)
                    or MAINTENANCE_LOGS_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = MAINTENANCE_LOGS_DEFAULT_LIMIT
    limit = min(max(limit, MAINTENANCE_LOGS_LIMIT_MIN), MAINTENANCE_LOGS_LIMIT_MAX)

    filtered = [
        log for log in context.get("maintenance_logs", [])
        if _log_day(log) == date and _log_matches_school(log, effective_hint, context)
    ]
    total = len(filtered)
    applied_filters = {"date": date, "school_raw": hint, "school_matched": matched}
    lang_en = tool_lang(context) == "en"
    prefix = ""
    if not matched:
        prefix = (f"School {str(hint).strip()} not recognized — filter ignored. "
                  if lang_en else
                  f"École {str(hint).strip()} non reconnue — filtre ignoré. ")
    if not filtered:
        empty = (f"No logged interventions on {date}." if lang_en
                 else f"Aucune intervention journalisée le {date}.")
        return {"date": date, "items": [], "total": 0,
                "insight": f"{prefix}{empty}",
                "applied_filters": applied_filters, "is_empty": True}
    names: list[str] = []
    for log in filtered:
        name = str(log.get("school_name") or "").strip()
        if name and name not in names:
            names.append(name)
    if lang_en:
        head = (f"{total} {_plural(total, 'logged intervention', 'logged interventions')} "
                f"on {date}")
    else:
        head = (f"{total} {_plural(total, 'intervention journalisée', 'interventions journalisées')} "
                f"le {date}")
    if names:
        shown = ", ".join(names[:3])
        extra = f" (+{len(names) - 3})" if len(names) > 3 else ""
        sep = ": " if lang_en else " : "
        insight = f"{head}{sep}{shown}{extra}."
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


def tool_list_incidents(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Liste les SIGNALEMENTS déclarés par les écoles (lecture seule).

    Jour civil via reported_at (défaut : aujourd'hui), filtres école
    (fragment ou id), urgence, statut, limite. Ne confondre avec
    list_maintenance_logs (travaux RÉALISÉS par les techniciens).
    """
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
    urgency = str(args.get("urgency") or "").strip().lower() or None
    status = str(args.get("status") or "").strip().lower() or None
    try:
        limit = int(args.get("limit", LIST_INCIDENTS_DEFAULT_LIMIT)
                    or LIST_INCIDENTS_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = LIST_INCIDENTS_DEFAULT_LIMIT
    limit = min(max(limit, LIST_INCIDENTS_LIMIT_MIN), LIST_INCIDENTS_LIMIT_MAX)

    filtered = []
    for incident in context.get("incidents", []):
        day = incident_window_day(incident)
        if day is None or day.isoformat() != date:
            continue
        if not _log_matches_school(incident, effective_hint, context):
            continue
        if urgency and str(incident.get("urgency") or "").lower() != urgency:
            continue
        if status and str(incident.get("status") or "").lower() != status:
            continue
        filtered.append(incident)
    total = len(filtered)
    applied_filters = {"date": date, "school_raw": hint, "school_matched": matched,
                       "urgency": urgency, "status": status}
    lang_en = tool_lang(context) == "en"
    prefix = ""
    if not matched:
        prefix = (f"School {str(hint).strip()} not recognized — filter ignored. "
                  if lang_en else
                  f"École {str(hint).strip()} non reconnue — filtre ignoré. ")
    if not filtered:
        empty = (f"No reports on {date}." if lang_en
                 else f"Aucun signalement le {date}.")
        return {"date": date, "items": [], "total": 0,
                "insight": f"{prefix}{empty}",
                "applied_filters": applied_filters, "is_empty": True}
    names: list[str] = []
    for incident in filtered:
        name = str(incident.get("school_name") or "").strip()
        if name and name not in names:
            names.append(name)
    if lang_en:
        head = f"{total} {_plural(total, 'report', 'reports')} on {date}"
    else:
        head = (f"{total} {_plural(total, 'signalement', 'signalements')} le {date}")
    if names:
        shown = ", ".join(names[:3])
        extra = f" (+{len(names) - 3})" if len(names) > 3 else ""
        sep = ": " if lang_en else " : "
        insight = f"{head}{sep}{shown}{extra}."
    else:
        insight = f"{head}."
    items = [{
        "id": incident.get("id"),
        "reference_code": incident.get("reference_code"),
        "title": incident.get("title"),
        "school_name": incident.get("school_name"),
        "district": incident.get("district"),
        "category": incident.get("category"),
        "urgency": incident.get("urgency"),
        "status": incident.get("status"),
        "affected_students": incident.get("affected_students"),
        "reported_at": incident.get("reported_at"),
    } for incident in filtered[:limit]]
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
    "list_incidents": tool_list_incidents,
}

AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_school",
            "description": "Analyse complète d'une école (nom approximatif accepté) : pannes ouvertes, coûts de maintenance et arbitrage réparer-remplacer. Ne JAMAIS utiliser pour PLANIFIER une intervention à venir (voir prepare_intervention).",
            "short_description": "Analyse une école : pannes ouvertes, coûts, arbitrage réparer-remplacer.",
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
            "short_description": "Classe les écoles par besoin (urgences, élèves, ancienneté).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_district",
            "description": "Synthèse chiffrée des incidents ouverts : urgences, catégories, élèves affectés.",
            "short_description": "Synthèse chiffrée : urgences, catégories, élèves affectés.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_incident",
            "description": "Récupère le détail factuel d'un incident pour l'expliquer simplement.",
            "short_description": "Détail factuel d'un incident (id, référence ou titre).",
            "parameters": {
                "type": "object",
                "properties": {"incident_id": {"description": "Id numérique OU référence (WASH-2026-XXXX) OU fragment du titre"}},
                "required": ["incident_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_maintenance_logs",
            "description": "Liste les interventions DEJA réalisées et journalisées par les TECHNICIENS (travaux finis, lecture seule). Pour toute question sur les interventions passées : filtres date AAAA-MM-JJ défaut aujourd'hui, école, limite. Ne crée rien. Exemple : « donne-moi les interventions réalisées aujourd'hui » → list_maintenance_logs. Si l'usager demande les SIGNALEMENTS ou pannes DÉCLARÉES par les écoles (pas les travaux réalisés), utilise list_incidents, jamais cet outil.",
            "short_description": "Liste les interventions réalisées (lecture seule) : date, école, limite.",
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
            "name": "list_incidents",
            "description": "Liste les SIGNALEMENTS et pannes DÉCLARÉS par les écoles (lecture seule) : filtres date AAAA-MM-JJ défaut aujourd'hui, école, urgence, statut, limite. Pour toute question « signalements / pannes déclarées / incidents du jour ». Ne crée rien. Exemple : « donne-moi les signalements d'aujourd'hui » → list_incidents avec la date du jour. Si l'usager demande les travaux/interventions RÉALISÉS par les techniciens, utilise list_maintenance_logs, jamais cet outil.",
            "short_description": "Liste les signalements déclarés (lecture seule) : date, école, urgence, statut, limite.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Jour filtré au format AAAA-MM-JJ (défaut : aujourd'hui)"},
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école (optionnel)"},
                    "urgency": {"type": "string", "description": "Filtre urgence : low, medium, high, critical (optionnel)"},
                    "status": {"type": "string", "description": "Filtre statut (optionnel)"},
                    "limit": {"type": "integer", "description": "Nombre max de signalements (défaut 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repair_trends",
            "description": "Tendances mensuelles sur N mois : pannes, coûts de réparation, jours sans service, heatmap 90 jours, comparatif budget. Avec school : une école. Avec district seul (ex: Mvila) : TOUT le district agrégé. À utiliser pour tout historique, tendance ou graphique.",
            "short_description": "Tendances mensuelles : pannes, coûts, jours sans service (école ou district).",
            "parameters": {
                "type": "object",
                "properties": {
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école (optionnel si district)"},
                    "months": {"type": "integer", "description": "Nombre de mois d'historique (1 à 12, défaut 3)"},
                    "district": {"type": "string", "description": "District à agréger quand aucune école n'est donnée (ex: Mvila, Wouri)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_briefing",
            "description": "Génère un mini-dossier de briefing (diaporama) : couverture chiffrée, priorités, actions recommandées.",
            "short_description": "Génère un briefing (diaporama) : chiffres, priorités, actions.",
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
            "short_description": "Vue carte du territoire : écoles géolocalisées et urgences.",
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
            "description": "Prépare la création d'un signalement (nouvelle panne signalée par un usager), dossier complet ou partiel sans rien écrire.",
            "short_description": "Prépare un signalement (création) : école, description, catégorie, urgence, élèves.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"const": "report", "description": "Discriminant : toujours 'report' pour cet outil"},
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école"},
                    "description": {"type": "string", "description": "Description libre de la panne"},
                    "category": {"type": "string", "enum": ["water_point", "toilets_latrines", "handwashing", "sewage_drainage"]},
                    "urgency": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "affected_students": {"type": "integer", "description": "Nombre d'élèves affectés"},
                },
                "required": ["kind", "description"],
                "not": {"required": ["title"]},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_incident",
            "description": "Prépare la création d'une intervention directe (nouvelle panne prise en charge), dossier complet ou partiel sans rien écrire.",
            "short_description": "Prépare une intervention (création) : école, titre, catégorie, urgence, élèves.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"const": "incident", "description": "Discriminant : toujours 'incident' pour cet outil"},
                    "school": {"type": "string", "description": "Nom (ou fragment) ou identifiant de l'école"},
                    "title": {"type": "string", "description": "Titre court de l'intervention"},
                    "category": {"type": "string", "enum": ["water_point", "toilets_latrines", "handwashing", "sewage_drainage"]},
                    "urgency": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "affected_students": {"type": "integer", "description": "Nombre d'élèves affectés"},
                },
                "required": ["kind", "title"],
                "not": {"required": ["description"]},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_maintenance_log",
            "description": "Prépare la création d'un journal d'intervention (travaux à consigner), dossier complet ou partiel sans rien écrire.",
            "short_description": "Prépare un journal d'intervention (création) : incident, coût XAF, notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident": {"type": "string", "description": "Incident concerné : titre (même approximatif), identifiant ou référence (WASH-...) — l'un des trois suffit"},
                    "cost_amount": {"type": "number", "minimum": 0, "description": "Coût de l'intervention en XAF"},
                    "notes": {"type": "string", "description": "Notes sur les travaux effectués"},
                    "days_without_service": {"type": "integer", "description": "Jours sans service comptabilisés"},
                },
            },
        },
    },
]


# --- Tools plugins auto-découverts (app/tools/*.py) : fusion, legacy intact ---
from .tools import discover_tools as _discover_tools

_PLUGIN_BUNDLES = _discover_tools()
for _bundle in _PLUGIN_BUNDLES:
    AGENT_TOOLS.append({"function": _bundle["def"]})
    TOOL_EXECUTORS[_bundle["name"]] = _bundle["execute"]
PLUGIN_HINTS: dict[str, frozenset[str]] = {b["name"]: b["hints"] for b in _PLUGIN_BUNDLES}
PLUGIN_CARDS: dict[str, dict[str, Any]] = {b["name"]: b["cards"] for b in _PLUGIN_BUNDLES}
PLUGIN_READ_ONLY: frozenset[str] = frozenset(b["name"] for b in _PLUGIN_BUNDLES if b["read_only"])
