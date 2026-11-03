"""Plugin outil : comparer 2 écoles ou plus côte à côte, avec verdict.

Lecture seule : agrège le contexte Laravel (schools, incidents,
maintenance_logs) sans réseau ni LLM. Résolution floue maison des noms
d'écoles (minuscules, sans accents, sous-chaîne).
"""
from __future__ import annotations

import unicodedata
from typing import Any

from ..schemas import AgentCard
from ..tool_consts import tool_lang

TOOL_NAME = "compare_schools"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Compare 2 écoles ou plus côte à côte : incidents ouverts, élèves "
        "affectés, interventions, coûts, jours sans service — avec un verdict "
        "indiquant laquelle a le plus besoin d'aide et pourquoi. À utiliser "
        "quand l'utilisateur nomme plusieurs écoles à mettre en regard. "
        "Exemple : 'Compare l'école de Ngok et celle de Mendong' -> "
        "compare_schools({'schools': ['Ngok', 'Mendong']}). "
        "Ne JAMAIS utiliser pour classer tout le territoire "
        "(rank_schools_by_need), analyser une seule école (analyze_school), "
        "ni créer un signalement (outils prepare_*)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "schools": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "description": "Noms (même approximatifs) ou ids des 2+ écoles à comparer",
            },
        },
        "required": ["schools"],
    },
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "compare", "comparer", "comparez", "comparons",
    "comparaison", "comparaisons", "comparatif", "comparatifs",
    "versus",
    "difference", "differences", "différence", "différences",
    "laquelle", "lequel",
    "cote a cote", "côte à côte", "cote à côte", "côte a cote",
    "entre ces ecoles", "entre ces écoles",
    "laquelle a le plus besoin", "laquelle choisir",
})

_OPEN_EXCLUDED = ("resolved", "closed")


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _norm(value: Any) -> str:
    return _strip_accents(str(value or "").strip().lower())


def _resolve_school(schools: list[dict[str, Any]], ref: Any) -> dict[str, Any] | None:
    """Résolution floue : id exact, puis sous-chaîne normalisée sur les noms."""
    try:
        wanted = int(str(ref).strip())
        for school in schools:
            if isinstance(school, dict) and school.get("school_id") == wanted:
                return school
    except (TypeError, ValueError):
        pass
    hint = _norm(ref)
    if not hint:
        return None
    for school in schools:
        if not isinstance(school, dict):
            continue
        name = _norm(school.get("school_name"))
        if name and (hint in name or name in hint):
            return school
    return None


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _need_score(open_incidents: int, critical: int, affected: int,
               cost: float, days: int) -> float:
    return round(
        3 * open_incidents + 2 * critical + affected / 50.0
        + cost / 50000.0 + float(days),
        2,
    )


def _why(column: dict[str, Any], lang: str = "fr") -> str:
    """Raison du verdict : 2 premiers facteurs non nuls (défaut français)."""
    use_en = str(lang or "fr").lower().startswith("en")
    parts: list[str] = []
    n_open = int(column.get("open_incidents", 0) or 0)
    n_crit = int(column.get("critical_incidents", 0) or 0)
    if n_open:
        if use_en:
            part = f"{n_open} open incident{'s' if n_open > 1 else ''}"
            if n_crit:
                part += f" including {n_crit} critical"
        else:
            part = f"{n_open} incident{'s' if n_open > 1 else ''} ouvert{'s' if n_open > 1 else ''}"
            if n_crit:
                part += f" dont {n_crit} critique{'s' if n_crit > 1 else ''}"
        parts.append(part)
    affected = int(column.get("affected_students", 0) or 0)
    if affected:
        parts.append(f"{affected} pupils affected" if use_en else f"{affected} élèves affectés")
    cost = float(column.get("total_cost_XAF", 0) or 0)
    if cost:
        if use_en:
            parts.append(f"{cost:,.0f} XAF in repairs")
        else:
            parts.append(f"{cost:,.0f} XAF de réparations".replace(",", " "))
    days = int(column.get("days_without_service", 0) or 0)
    if days:
        parts.append(f"{days} day{'s' if days > 1 else ''} without service"
                     if use_en else
                     f"{days} jour{'s' if days > 1 else ''} sans service")
    if not parts:
        return "no open breakdown or reported cost" if use_en else "aucune panne ouverte ni coût signalé"
    return ", ".join(parts[:2])


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        return _execute(args or {}, context or {})
    except Exception as exc:  # contrat plugin : jamais d'exception vers la boucle
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    use_en = tool_lang(context) == "en"
    raw = args.get("schools")
    if not isinstance(raw, list):
        err = ("Name at least 2 schools to compare: {'schools': ['School A', 'School B']}."
               if use_en else
               "Précisez au moins 2 écoles à comparer : {'schools': ['École A', 'École B']}.")
        return {"error": err}
    queries = [q for q in (str(r).strip() for r in raw) if q]
    if len(queries) < 2:
        err = ("Name at least 2 schools to compare: {'schools': ['School A', 'School B']}."
               if use_en else
               "Précisez au moins 2 écoles à comparer : {'schools': ['École A', 'École B']}.")
        return {"error": err}

    schools = [s for s in context.get("schools", []) if isinstance(s, dict)]
    incidents = [i for i in context.get("incidents", []) if isinstance(i, dict)]
    logs = [l for l in context.get("maintenance_logs", []) if isinstance(l, dict)]

    columns: list[dict[str, Any]] = []
    unresolved: list[str] = []
    seen_ids: set[Any] = set()
    for query in queries:
        school = _resolve_school(schools, query)
        if school is None:
            unresolved.append(query)
            continue
        sid = school.get("school_id")
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        name = str(school.get("school_name") or query)
        open_incs = [i for i in incidents
                     if i.get("school_id") == sid
                     and i.get("status") not in _OPEN_EXCLUDED]
        critical = sum(1 for i in open_incs if str(i.get("urgency") or "").lower() == "critical")
        affected = sum(_as_int(i.get("affected_students")) for i in open_incs)
        affected_max = max((_as_int(i.get("affected_students")) for i in open_incs), default=0)
        school_logs = [l for l in logs if l.get("school_id") == sid]
        cost = round(sum(_as_float(l.get("cost_amount")) for l in school_logs), 2)
        days = sum(_as_int(l.get("days_without_service")) for l in school_logs)
        columns.append({
            "school_id": sid,
            "school_name": name,
            "open_incidents": len(open_incs),
            "critical_incidents": critical,
            "affected_students": affected,
            # Sémantique unifiée : max par école (sans double-compte).
            "affected_students_max": affected_max,
            "interventions": len(school_logs),
            "total_cost_XAF": cost,
            "days_without_service": days,
            "need_score": _need_score(len(open_incs), critical, affected, cost, days),
        })

    if len(columns) < 2:
        known = ", ".join(str(s.get("school_name", "?")) for s in schools[:10])
        if use_en:
            err = (
                f"Comparison impossible: {len(columns)} school(s) recognized, 2 needed. "
                f"Not found: {', '.join(unresolved) or '—'}. "
                f"Valid schools: {known or 'no school in context'}."
            )
        else:
            err = (
                f"Comparaison impossible : {len(columns)} école(s) reconnue(s), il en faut 2. "
                f"Introuvables : {', '.join(unresolved) or '—'}. "
                f"Écoles valides : {known or 'aucune école dans le contexte'}."
            )
        return {"error": err, "unresolved": unresolved}

    winner = max(range(len(columns)), key=lambda k: columns[k]["need_score"])
    top = columns[winner]
    lang = "en" if use_en else "fr"
    names = " vs ".join(c["school_name"] for c in columns)
    verdict = f"{top['school_name']} — {_why(top, lang)}."
    if use_en:
        suffix = f" (not found: {', '.join(unresolved)})" if unresolved else ""
        insight = f"Comparing {names}: {verdict}{suffix}"
    else:
        suffix = f" (introuvables : {', '.join(unresolved)})" if unresolved else ""
        insight = f"Comparaison {names} : {verdict}{suffix}"
    return {
        "insight": insight,
        "columns": columns,
        "verdict": verdict,
        "unresolved": unresolved,
    }


def _build_compare_schools_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict) or obs.get("error"):
        return None
    columns = obs.get("columns")
    if not isinstance(columns, list) or not columns:
        return None
    use_en = str(obs.get("lang") or "fr").lower().startswith("en")
    return AgentCard(
        type="compare_schools",
        title="School comparison" if use_en else "Comparaison des écoles",
        data=obs,
    )


CARD_BUILDERS = {"compare_schools": _build_compare_schools_card}
