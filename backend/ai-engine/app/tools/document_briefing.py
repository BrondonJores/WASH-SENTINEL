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
from ..tool_consts import LOG_WINDOW_DAYS, STALE_AFTER_DAYS, tool_lang

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
                "description": "District ou école ciblé(e), nom approximatif accepté (optionnel, sinon tout le territoire ; obligatoire quand la question porte sur une école précise, sinon l'appel est refusé)",
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

ENGLISH_MONTHS = ["", "January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November",
                  "December"]

_VALID_FORMATS = ("briefing", "diaporama", "rapport")

#: Alias partagés (source unique : app.tool_consts).
_STALE_DAYS = STALE_AFTER_DAYS
_LOG_WINDOW_DAYS = LOG_WINDOW_DAYS


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
        use_en = tool_lang(context) == "en"
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
                err = (f"No data for \u00ab {topic} \u00bb: district "
                       "or school not found in the context.") if use_en else (
                           f"Aucune donnée pour « {topic} » : district "
                           "ou école introuvable dans le contexte.")
                return {"topic": topic, "format": format_,
                        "sections": [], "slides": [], "total": 0,
                        "error": err}
        elif not schools and not incidents and not logs:
            err = ("No data available to assemble the document." if use_en
                   else "Aucune donnée disponible pour assembler le document.")
            return {"topic": None, "format": format_,
                    "sections": [], "slides": [], "total": 0,
                    "error": err}

        now = datetime.now(timezone.utc)
        n_open = len(incidents)
        affected = sum(_to_int(i.get("affected_students")) for i in incidents)
        crit = [i for i in incidents
                if str(i.get("urgency") or "").strip().lower() == "critical"]
        recent_logs = [lo for lo in logs
                       if _log_within_days(lo, now, _LOG_WINDOW_DAYS)]
        cost_total = sum(_to_float(lo.get("cost_amount")) for lo in recent_logs)

        scope = topic or ("the whole territory" if use_en else "tout le territoire")
        open_w = ("open incident", "open incidents") if use_en else ("incident ouvert", "incidents ouverts")
        if use_en:
            summary: list[str] = [
                f"Scope: {scope}.",
                (f"{n_open} {_plural(n_open, *open_w)}, "
                 f"{_fmt_int(affected)} {_plural(affected, 'affected pupil', 'affected pupils')}, "
                 f"{len(schools)} {_plural(len(schools), 'monitored school', 'monitored schools')}."),
            ]
        else:
            summary = [
                f"Périmètre : {scope}.",
                (f"{n_open} {_plural(n_open, *open_w)}, "
                 f"{_fmt_int(affected)} {_plural(affected, 'élève affecté', 'élèves affectés')}, "
                 f"{len(schools)} {_plural(len(schools), 'école suivie', 'écoles suivies')}."),
            ]
        if crit:
            if use_en:
                summary.append(f"{len(crit)} {_plural(len(crit), 'critical incident requires', 'critical incidents require')} "
                               "immediate intervention.")
            else:
                summary.append(f"{len(crit)} {_plural(len(crit), 'incident critique exige', 'incidents critiques exigent')} "
                               "une intervention immédiate.")
        elif n_open:
            summary.append("No critical incident: situation under control." if use_en
                           else "Aucun incident critique : situation sous contrôle.")
        else:
            summary.append("No open incident: all quiet." if use_en
                           else "Aucun incident ouvert : calme plat.")

        if use_en:
            figures: list[str] = [
                f"Open incidents: {n_open}",
                f"Of which critical: {len(crit)}",
                f"Affected pupils: {_fmt_int(affected)}",
                f"Monitored schools: {len(schools)}",
                (f"Logged interventions ({_LOG_WINDOW_DAYS} d): "
                 f"{len(recent_logs)}"),
            ]
        else:
            figures = [
                f"Incidents ouverts : {n_open}",
                f"Dont critiques : {len(crit)}",
                f"Élèves affectés : {_fmt_int(affected)}",
                f"Écoles suivies : {len(schools)}",
                (f"Interventions journalisées ({_LOG_WINDOW_DAYS} j) : "
                 f"{len(recent_logs)}"),
            ]
        if recent_logs:
            figures.append(f"Total logged cost: {_fmt_int(cost_total)} XAF" if use_en
                           else f"Coût total journalisé : {_fmt_int(cost_total)} XAF")

        top = sorted(
            incidents,
            key=lambda i: (_URGENCY_WEIGHTS.get(
                str(i.get("urgency", "low")).strip().lower(), 0.0),
                _to_int(i.get("affected_students"))),
            reverse=True)[:3]
        urg_map = URGENCY_FR
        if use_en:
            priorities = [
                (f"{i.get('school_name', '?')} — {i.get('title', '?')} "
                 f"({str(i.get('urgency', '?')).strip().lower()}, "
                 f"{_fmt_int(i.get('affected_students', 0))} pupils)")
                for i in top
            ] or ["No priorities: all quiet in this scope."]
        else:
            priorities = [
                (f"{i.get('school_name', '?')} — {i.get('title', '?')} "
                 f"({urg_map.get(str(i.get('urgency', '')).strip().lower(), str(i.get('urgency', '?')))}, "
                 f"{_fmt_int(i.get('affected_students', 0))} élèves)")
                for i in top
            ] or ["Aucune priorité : calme plat sur ce périmètre."]

        actions: list[str] = []
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
        old = [i for i in incidents
               if (age := _age_days(i.get("reported_at"), now)) is not None
               and age > _STALE_DAYS]
        if old:
            if use_en:
                actions.append(
                    f"{_plural(len(old), '1 incident open', f'{len(old)} incidents open')} "
                    "for more than 7 days: schedule a follow-up."
                )
            else:
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
            if use_en:
                actions.append(f"Combined tour possible: {', '.join(grouped)}.")
            else:
                actions.append(f"Tournée groupée possible : {', '.join(grouped)}.")
        if recent_logs:
            if use_en:
                actions.append(
                    f"{len(recent_logs)} {_plural(len(recent_logs), 'logged intervention', 'logged interventions')} "
                    f"over {_LOG_WINDOW_DAYS} days ({_fmt_int(cost_total)} XAF): keep up the pace."
                )
            else:
                actions.append(
                    f"{len(recent_logs)} {_plural(len(recent_logs), 'intervention journalisée', 'interventions journalisées')} "
                    f"sur {_LOG_WINDOW_DAYS} jours ({_fmt_int(cost_total)} XAF) : poursuivre le rythme."
                )
        if not actions:
            actions.append("No urgent action: maintain monitoring." if use_en
                           else "Aucune action urgente : maintenir la surveillance.")

        if use_en:
            sections = [
                {"title": "Summary", "bullets": summary},
                {"title": "Key figures", "bullets": figures},
                {"title": "Priorities", "bullets": priorities},
                {"title": "Recommended actions", "bullets": actions},
            ]
        else:
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
                if use_en:
                    detail.append(
                        f"{sname} ({school.get('district', '?')}): "
                        f"{len(s_open)} {_plural(len(s_open), 'open incident', 'open incidents')}, "
                        f"{_fmt_int(s_aff)} affected pupils, {_fmt_int(s_cost)} XAF in repairs."
                    )
                else:
                    detail.append(
                        f"{sname} ({school.get('district', '?')}) : "
                        f"{len(s_open)} {_plural(len(s_open), 'incident ouvert', 'incidents ouverts')}, "
                        f"{_fmt_int(s_aff)} élèves affectés, {_fmt_int(s_cost)} XAF de réparations."
                    )
            empty_detail = ("No monitored school in this scope." if use_en
                            else "Aucune école suivie sur ce périmètre.")
            sections.append({"title": ("School detail" if use_en else "Détail par école"),
                             "bullets": detail or [empty_detail]})

        slides: list[dict[str, Any]] = []
        if format_ == "diaporama":
            months = ENGLISH_MONTHS if use_en else FRENCH_MONTHS
            slides.append({
                "kind": "cover",
                "title": (f"WASH brief — {topic or 'Territory'}" if use_en
                          else f"Document WASH — {topic or 'Territoire'}"),
                "subtitle": ((f"{months[now.month]} {now.day}, {now.year} · "
                              f"{topic or 'all districts'}") if use_en else
                             (f"{now.day} {months[now.month]} {now.year} · "
                              f"{topic or 'tous districts'}")),
                "lines": [],
                "stats": [
                    {"label": ("Open incidents" if use_en else "Incidents ouverts"),
                     "value": str(n_open)},
                    {"label": ("Affected pupils" if use_en else "Élèves affectés"),
                     "value": _fmt_int(affected)},
                    {"label": ("Monitored schools" if use_en else "Écoles suivies"),
                     "value": str(len(schools))},
                ],
            })
            for section in sections:
                slides.append({"kind": "bullets", "title": section["title"],
                               "lines": list(section["bullets"]), "stats": []})

        if use_en:
            insight = (
                f"Document \u00ab {format_} \u00bb for {scope}: {n_open} "
                f"{_plural(n_open, 'open incident', 'open incidents')}"
                + (f" of which {len(crit)} critical" if crit else "")
                + (f", {_fmt_int(affected)} affected pupils"
                   f", {len(schools)} monitored school(s)"
                   f", {len(actions)} recommended action(s).")
            )
        else:
            insight = (
                f"Document « {format_} » pour {scope} : {n_open} "
                f"{_plural(n_open, 'incident ouvert', 'incidents ouverts')}"
                + (f" dont {len(crit)} critique(s)" if crit else "")
                + (f", {_fmt_int(affected)} élèves affectés"
                   f", {len(schools)} école(s) suivie(s)"
                   f", {len(actions)} action(s) recommandée(s).")
            )
        if format_ == "diaporama":
            insight += (f" Deck of {len(slides)} slides generated." if use_en
                        else f" Deck de {len(slides)} slides généré.")
        return {"insight": insight, "topic": topic or None, "format": format_,
                "sections": sections, "slides": slides, "total": len(sections),
                "lang": "en" if use_en else "fr"}
    except Exception as exc:  # contrat : jamais d'exception vers la boucle
        err = f"Document unavailable: {exc}" if use_en else f"Document indisponible : {exc}"
        return {"sections": [], "slides": [], "total": 0,
                "error": err}


def _build_document_briefing_card(obs: dict[str, Any]) -> AgentCard | None:
    sections = obs.get("sections") or []
    if not isinstance(sections, list) or not sections:
        return None
    topic = obs.get("topic")
    use_en = str(obs.get("lang") or "fr").lower().startswith("en")
    scope = f" — {topic}" if topic else ""
    return AgentCard(
        type="document_briefing",
        title=f"Briefing document{scope}" if use_en else f"Document briefing{scope}",
        data=obs,
    )


CARD_BUILDERS = {"document_briefing": _build_document_briefing_card}
