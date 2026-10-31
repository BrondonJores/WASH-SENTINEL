"""Plugin outil : document de briefing structuré (rapport / diaporama / présentation).

Assemble un DOCUMENT multi-sections (résumé, chiffres clés, priorités, actions
recommandées, détail par école en format rapport) et, quand format=diaporama,
un deck de slides. 100 % déterministe, synchrone, sans réseau ni LLM.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Any

from ..schemas import AgentCard

TOOL_NAME = "document_briefing"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Assemble un DOCUMENT structuré multi-sections (résumé, chiffres clés, "
        "priorités, actions recommandées) ou un deck de slides quand "
        "format=diaporama, pour un district ou une école. À utiliser quand "
        "l'utilisateur demande un rapport, un diaporama, une présentation ou "
        "un dossier avec chiffres et actions. "
        "Exemple : « Fais-moi un diaporama du district Mvila » -> "
        "document_briefing avec topic=Mvila, format=diaporama. "
        "Ne JAMAIS utiliser pour un mini-briefing d'actions courtes ou un "
        "simple résumé en une phrase (répondre directement), ni pour créer "
        "un signalement (outils prepare_*)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "District ou école ciblé(e), nom approximatif accepté (optionnel, sinon tout le territoire)",
            },
            "format": {
                "type": "string",
                "enum": ["briefing", "diaporama", "rapport"],
                "default": "briefing",
                "description": "briefing = sections texte, diaporama = sections + deck de slides, rapport = sections + détail par école",
            },
        },
    },
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "diaporama", "diaporamas",
    "presentation", "présentation",
    "presentations", "présentations",
    "slide", "slides",
    "briefing", "briefings",
    "rapport", "rapports",
    "document", "documents",
    "dossier de briefing", "dossier wash",
    "synthese executive", "synthèse exécutive",
    "rapport executif", "rapport exécutif",
    "genere un rapport", "génère un rapport",
    "redige un rapport", "rédige un rapport",
})

_OPEN_EXCLUDED = ("resolved", "closed")

_URGENCY_WEIGHTS = {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 0.5}

URGENCY_FR = {"critical": "critique", "high": "haute",
              "medium": "moyenne", "low": "basse"}

FRENCH_MONTHS = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                 "juillet", "août", "septembre", "octobre", "novembre",
                 "décembre"]

_VALID_FORMATS = ("briefing", "diaporama", "rapport")

_STALE_DAYS = 7
_LOG_WINDOW_DAYS = 30


def _fold(text: Any) -> str:
    """Minuscules + sans accents pour le filtre flou."""
    raw = str(text or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", raw)
                   if not unicodedata.combining(c))


def _matches(topic: str, candidate: Any) -> bool:
    folded_topic = _fold(topic)
    folded_candidate = _fold(candidate)
    if not folded_topic or not folded_candidate:
        return False
    return folded_topic in folded_candidate or folded_candidate in folded_topic


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt_int(n: Any) -> str:
    return f"{_to_int(n):,}".replace(",", " ")


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _open_incidents(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in _as_list(context.get("incidents"))
            if isinstance(i, dict) and i.get("status") not in _OPEN_EXCLUDED]


def _parse_format(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in _VALID_FORMATS else "briefing"


def _log_within_days(log: dict[str, Any], now: datetime, days: int) -> bool:
    parsed = _parse_dt(log.get("created_at")) or _parse_dt(log.get("repaired_at"))
    if parsed is None:
        return True
    return (now - parsed).days <= days


def _age_days(reported_at: Any, now: datetime) -> int | None:
    parsed = _parse_dt(reported_at)
    if parsed is None:
        return None
    return max((now - parsed).days, 0)


def _filter_by_topic(items: list[dict[str, Any]], topic: str,
                     keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [i for i in items
            if any(_matches(topic, i.get(k)) for k in keys)]


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Assemble le document de briefing (déterministe, synchrone, sans réseau)."""
    try:
        args = args or {}
        context = context or {}
        topic = str(args.get("topic") or "").strip()
        format_ = _parse_format(args.get("format"))

        schools = [s for s in _as_list(context.get("schools"))
                   if isinstance(s, dict)]
        incidents = _open_incidents(context)
        logs = [lo for lo in _as_list(context.get("maintenance_logs"))
                if isinstance(lo, dict)]

        if topic:
            schools = _filter_by_topic(schools, topic, ("school_name", "district"))
            incidents = _filter_by_topic(
                incidents, topic,
                ("school_name", "district", "title", "summary"))
            sids = {s.get("school_id") for s in schools
                    if s.get("school_id") is not None}
            logs = [lo for lo in logs
                    if _matches(topic, lo.get("school_name"))
                    or _matches(topic, lo.get("incident_title"))
                    or (lo.get("school_id") in sids)]
            if not schools and not incidents and not logs:
                return {"topic": topic, "format": format_,
                        "sections": [], "slides": [], "total": 0,
                        "error": (f"Aucune donnée pour « {topic} » : district "
                                  "ou école introuvable dans le contexte.")}
        elif not schools and not incidents and not logs:
            return {"topic": None, "format": format_,
                    "sections": [], "slides": [], "total": 0,
                    "error": "Aucune donnée disponible pour assembler le document."}

        now = datetime.now(timezone.utc)
        n_open = len(incidents)
        affected = sum(_to_int(i.get("affected_students")) for i in incidents)
        crit = [i for i in incidents
                if str(i.get("urgency") or "").strip().lower() == "critical"]
        recent_logs = [lo for lo in logs
                       if _log_within_days(lo, now, _LOG_WINDOW_DAYS)]
        cost_total = sum(_to_float(lo.get("cost_amount")) for lo in recent_logs)

        scope = topic or "tout le territoire"
        summary: list[str] = [
            f"Périmètre : {scope}.",
            (f"{n_open} {_plural(n_open, 'incident ouvert', 'incidents ouverts')}, "
             f"{_fmt_int(affected)} {_plural(affected, 'élève affecté', 'élèves affectés')}, "
             f"{len(schools)} {_plural(len(schools), 'école suivie', 'écoles suivies')}."),
        ]
        if crit:
            summary.append(f"{len(crit)} {_plural(len(crit), 'incident critique exige', 'incidents critiques exigent')} "
                           "une intervention immédiate.")
        elif n_open:
            summary.append("Aucun incident critique : situation sous contrôle.")
        else:
            summary.append("Aucun incident ouvert : calme plat.")

        figures: list[str] = [
            f"Incidents ouverts : {n_open}",
            f"Dont critiques : {len(crit)}",
            f"Élèves affectés : {_fmt_int(affected)}",
            f"Écoles suivies : {len(schools)}",
            (f"Interventions journalisées ({_LOG_WINDOW_DAYS} j) : "
             f"{len(recent_logs)}"),
        ]
        if recent_logs:
            figures.append(f"Coût total journalisé : {_fmt_int(cost_total)} XAF")

        top = sorted(
            incidents,
            key=lambda i: (_URGENCY_WEIGHTS.get(
                str(i.get("urgency", "low")).strip().lower(), 0.0),
                _to_int(i.get("affected_students"))),
            reverse=True)[:3]
        priorities = [
            (f"{i.get('school_name', '?')} — {i.get('title', '?')} "
             f"({URGENCY_FR.get(str(i.get('urgency', '')).strip().lower(), str(i.get('urgency', '?')))}, "
             f"{_fmt_int(i.get('affected_students', 0))} élèves)")
            for i in top
        ] or ["Aucune priorité : calme plat sur ce périmètre."]

        actions: list[str] = []
        if crit:
            names = ", ".join(sorted({str(i.get("school_name", "?")) for i in crit}))
            actions.append(
                f"Intervenir en priorité sur "
                f"{_plural(len(crit), '1 incident critique', f'{len(crit)} incidents critiques')} : {names}."
            )
        old = [i for i in incidents
               if (age := _age_days(i.get("reported_at"), now)) is not None
               and age > _STALE_DAYS]
        if old:
            actions.append(
                f"{_plural(len(old), '1 incident ouvert', f'{len(old)} incidents ouverts')} "
                "depuis plus de 7 jours : planifier la relance."
            )
        by_district: dict[str, int] = {}
        for i in incidents:
            by_district[str(i.get("district", "?"))] = by_district.get(
                str(i.get("district", "?")), 0) + 1
        grouped = sorted(d for d, n in by_district.items() if n >= 2)
        if grouped:
            actions.append(f"Tournée groupée possible : {', '.join(grouped)}.")
        if recent_logs:
            actions.append(
                f"{len(recent_logs)} {_plural(len(recent_logs), 'intervention journalisée', 'interventions journalisées')} "
                f"sur {_LOG_WINDOW_DAYS} jours ({_fmt_int(cost_total)} XAF) : poursuivre le rythme."
            )
        if not actions:
            actions.append("Aucune action urgente : maintenir la surveillance.")

        sections = [
            {"title": "Résumé", "bullets": summary},
            {"title": "Chiffres clés", "bullets": figures},
            {"title": "Priorités", "bullets": priorities},
            {"title": "Actions recommandées", "bullets": actions},
        ]
        if format_ == "rapport":
            detail: list[str] = []
            for school in sorted(schools,
                                 key=lambda s: str(s.get("school_name", "")))[:10]:
                sid = school.get("school_id")
                sname = str(school.get("school_name", "?"))
                s_open = [i for i in incidents
                          if sid is not None and i.get("school_id") == sid
                          or _matches(sname, i.get("school_name"))]
                s_cost = sum(_to_float(lo.get("cost_amount")) for lo in recent_logs
                             if (sid is not None and lo.get("school_id") == sid)
                             or _matches(sname, lo.get("school_name")))
                s_aff = sum(_to_int(i.get("affected_students")) for i in s_open)
                detail.append(
                    f"{sname} ({school.get('district', '?')}) : "
                    f"{len(s_open)} {_plural(len(s_open), 'incident ouvert', 'incidents ouverts')}, "
                    f"{_fmt_int(s_aff)} élèves affectés, {_fmt_int(s_cost)} XAF de réparations."
                )
            sections.append({"title": "Détail par école",
                             "bullets": detail or ["Aucune école suivie sur ce périmètre."]})

        slides: list[dict[str, Any]] = []
        if format_ == "diaporama":
            slides.append({
                "kind": "cover",
                "title": f"Document WASH — {topic or 'Territoire'}",
                "subtitle": (f"{now.day} {FRENCH_MONTHS[now.month]} {now.year} · "
                             f"{topic or 'tous districts'}"),
                "lines": [],
                "stats": [
                    {"label": "Incidents ouverts", "value": str(n_open)},
                    {"label": "Élèves affectés", "value": _fmt_int(affected)},
                    {"label": "Écoles suivies", "value": str(len(schools))},
                ],
            })
            for section in sections:
                slides.append({"kind": "bullets", "title": section["title"],
                               "lines": list(section["bullets"]), "stats": []})

        insight = (
            f"Document « {format_} » pour {scope} : {n_open} "
            f"{_plural(n_open, 'incident ouvert', 'incidents ouverts')}"
            + (f" dont {len(crit)} critique(s)" if crit else "")
            + (f", {_fmt_int(affected)} élèves affectés"
               f", {len(schools)} école(s) suivie(s)"
               f", {len(actions)} action(s) recommandée(s).")
        )
        if format_ == "diaporama":
            insight += f" Deck de {len(slides)} slides généré."
        return {"insight": insight, "topic": topic or None, "format": format_,
                "sections": sections, "slides": slides, "total": len(sections)}
    except Exception as exc:  # contrat : jamais d'exception vers la boucle
        return {"sections": [], "slides": [], "total": 0,
                "error": f"Document indisponible : {exc}"}


def _build_document_briefing_card(obs: dict[str, Any]) -> AgentCard | None:
    sections = obs.get("sections") or []
    if not isinstance(sections, list) or not sections:
        return None
    topic = obs.get("topic")
    scope = f" — {topic}" if topic else ""
    return AgentCard(
        type="document_briefing",
        title=f"Document briefing{scope}",
        data=obs,
    )


CARD_BUILDERS = {"document_briefing": _build_document_briefing_card}
