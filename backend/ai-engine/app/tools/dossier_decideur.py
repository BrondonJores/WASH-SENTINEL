"""Dossier décideur : rapport structuré + affiche + diaporama (sans LLM direct).

Ce module N'EST PAS un plugin auto-découvert (ni TOOL_NAME ni execute) :
aucun endpoint ni branchement loop ici, le parent câble `run_dossier`.
`build_dossier` est pur (données du contexte uniquement, zéro invention) ;
`run_dossier` ajoute l'image cloud via le provider fourni.

CÂBLAGE PARENT (5 lignes) :
1. appeler `await run_dossier(llm, scope_type, scope_name, context)` depuis la boucle ou l'endpoint.
2. renvoyer `run["cards"]` (AgentCard poster + dossier_report) dans la réponse agent.
3. Laravel persiste `poster.image_base64` puis réécrit `poster.image_url`.
4. frontend : ajouter les cases 'poster' et 'dossier_report' dans AgentCards.tsx.
5. sortir "poster"/"dossier_report" de FRONTEND_RESERVED quand émis + rendus.
"""
from __future__ import annotations

import base64
import unicodedata
from datetime import datetime, timezone
from typing import Any

from ..schemas import (
    AgentCard,
    DossierReportCardData,
    DossierReportSection,
    PosterCardData,
)
from ..tool_consts import STALE_AFTER_DAYS
from .document_briefing import execute as _briefing_execute

#: Taille d'affiche par défaut (format OpenAI).
POSTER_SIZE_DEFAULT = "1024x1024"

#: Lignes max du résumé exécutif (corps markdown, lignes non vides).
EXEC_SUMMARY_MAX_LINES = 5

#: Mention honnête quand le contexte ne fournit pas la donnée (jamais d'invention).
NOT_COMMUNICATED = "non communiqué"

#: Ordre exact des 6 sections décideur du rapport.
SECTION_HEADINGS = (
    "Résumé exécutif",
    "Faits et chiffres vérifiés",
    "Analyse",
    "Recommandations chiffrées",
    "Budget",
    "Annexes",
)

_OPEN_EXCLUDED = ("resolved", "closed")

_URGENCY_FR = {"critical": "critique", "high": "haute",
               "medium": "moyenne", "low": "basse"}

_URGENCY_ORDER = ("critical", "high", "medium", "low")


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
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float | None:
    """Flottant ou None (None = pas un coût : jamais compté comme 0 inventé)."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_int(n: Any) -> str:
    return f"{_to_int(n):,}".replace(",", " ")


def _fmt_xaf(amount: float) -> str:
    return f"{int(round(amount)):,} XAF".replace(",", " ")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _open_incidents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in items if i.get("status") not in _OPEN_EXCLUDED]


def _resolve_scope(
    scope_type: str | None,
    scope_id: Any,
    scope_name: str | None,
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Filtre écoles/incidents/journaux selon le périmètre (fonction pure).

    Retourne (libellé, écoles, incidents ouverts, journaux). Filtre vide =
    périmètre sans donnée (jamais d'erreur : le rapport le dit honnêtement).
    """
    schools = [s for s in _as_list(context.get("schools")) if isinstance(s, dict)]
    incidents = _open_incidents(
        [i for i in _as_list(context.get("incidents")) if isinstance(i, dict)])
    logs = [lo for lo in _as_list(context.get("maintenance_logs"))
            if isinstance(lo, dict)]
    name = (scope_name or "").strip()
    kind = (scope_type or "").strip().lower()
    if scope_id is not None:
        matched = [s for s in schools if s.get("school_id") == scope_id]
        label = str(matched[0].get("school_name") or name or f"école #{scope_id}")
        kids = [i for i in incidents
                if i.get("school_id") == scope_id or _matches(label, i.get("school_name"))]
        klods = [lo for lo in logs
                 if lo.get("school_id") == scope_id or _matches(label, lo.get("school_name"))]
        return label, matched, kids, klods
    if name:
        if kind == "school":
            incident_keys: tuple[str, ...] = ("school_name",)
            log_keys: tuple[str, ...] = ("school_name",)
        elif kind == "district":
            incident_keys = ("district",)
            log_keys = ("district", "school_name")
        else:
            incident_keys = ("school_name", "district")
            log_keys = ("school_name", "district")
        kids = [i for i in incidents
                if any(_matches(name, i.get(k)) for k in incident_keys)]
        kschools = [s for s in schools
                    if _matches(name, s.get("school_name")) or _matches(name, s.get("district"))]
        sids = {s.get("school_id") for s in kschools if s.get("school_id") is not None}
        klods = [lo for lo in logs
                 if any(_matches(name, lo.get(k)) for k in log_keys)
                 or lo.get("school_id") in sids]
        return name, kschools, kids, klods
    return "tout le territoire", schools, incidents, logs


def _period(incidents: list[dict[str, Any]], logs: list[dict[str, Any]]) -> str:
    """Période ISO min→max lue dans les données, sinon 'non communiqué'."""
    stamps: list[str] = []
    for row in incidents:
        if row.get("reported_at"):
            stamps.append(str(row["reported_at"]))
    for row in logs:
        for key in ("created_at", "date", "repaired_at"):
            if row.get(key):
                stamps.append(str(row[key]))
    parsed = sorted(d for s in stamps if (d := _parse_dt(s)) is not None)
    if not parsed:
        return f"{NOT_COMMUNICATED} (aucune date dans le contexte)"
    start = parsed[0].date().isoformat()
    end = parsed[-1].date().isoformat()
    span = start if start == end else f"du {start} au {end}"
    return f"{span} (dates des données transmises)"


def _costs(logs: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Coûts (école, montant) lus dans les journaux ; montants invalides ignorés."""
    rows: list[tuple[str, float]] = []
    for log in logs:
        amount = _to_float(log.get("cost_amount"))
        if amount is None:
            amount = _to_float(log.get("cost"))
        if amount is None:
            continue
        rows.append((str(log.get("school_name") or log.get("school") or "?"), amount))
    return rows


def _top_incident(incidents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Incident prioritaire : urgence max puis élèves max (déterministe)."""
    weights = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    if not incidents:
        return None
    return sorted(
        incidents,
        key=lambda i: (weights.get(str(i.get("urgency") or "").strip().lower(), 0),
                       _to_int(i.get("affected_students")),
                       str(i.get("school_name") or "")),
        reverse=True,
    )[0]


def _stale_count(incidents: list[dict[str, Any]], now: datetime) -> int:
    """Incidents ouverts depuis plus de STALE_AFTER_DAYS (source unique partagée)."""
    total = 0
    for incident in incidents:
        parsed = _parse_dt(incident.get("reported_at"))
        if parsed is not None and (now - parsed).days > STALE_AFTER_DAYS:
            total += 1
    return total


def _urgency_counts(incidents: list[dict[str, Any]]) -> dict[str, int]:
    counts = {level: 0 for level in _URGENCY_ORDER}
    for incident in incidents:
        level = str(incident.get("urgency") or "").strip().lower()
        if level in counts:
            counts[level] += 1
    return counts


def _top_title(incidents: list[dict[str, Any]]) -> tuple[str, int] | None:
    """Titre d'incident le plus fréquent (déterministe : ex aequo alphabétique)."""
    freq: dict[str, int] = {}
    for incident in incidents:
        title = str(incident.get("title") or incident.get("summary") or "?").strip()
        freq[title] = freq.get(title, 0) + 1
    if not freq:
        return None
    best = max(freq.values())
    return sorted(t for t, n in freq.items() if n == best)[0], best


def _photo_refs(context: dict[str, Any], incidents: list[dict[str, Any]]) -> list[str]:
    """Références photo lues dans le contexte (titres/URLs, jamais le contenu)."""
    refs: list[str] = []
    for photo in _as_list(context.get("photos")):
        if isinstance(photo, str) and photo.strip():
            refs.append(photo.strip()[:80])
        elif isinstance(photo, dict):
            label = photo.get("title") or photo.get("caption") or photo.get("url") or photo.get("id")
            if label:
                refs.append(str(label)[:80])
    for incident in incidents:
        for key in ("photo_url", "photo", "image_url", "image"):
            if incident.get(key):
                refs.append(f"{incident.get('school_name', '?')} ({key})")
                break
    return refs


def _build_sections(
    label: str,
    schools: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    photo_refs: list[str],
    context_sizes: dict[str, int],
) -> list[dict[str, Any]]:
    """6 sections décideur : chiffres calculés depuis le périmètre uniquement."""
    now = datetime.now(timezone.utc)
    n_open = len(incidents)
    affected = sum(_to_int(i.get("affected_students")) for i in incidents)
    urg = _urgency_counts(incidents)
    stale = _stale_count(incidents, now)
    costs = _costs(logs)
    total_cost = sum(amount for _, amount in costs)
    top = _top_incident(incidents)
    top_freq = _top_title(incidents)
    empty = not schools and not incidents and not logs
    budget_line = (f"Budget journalisé : {_fmt_xaf(total_cost)}."
                   if costs else f"Budget : {NOT_COMMUNICATED}.")

    if empty:
        summary = [
            f"Périmètre : {label}.",
            "Aucune donnée vérifiée pour ce périmètre.",
            f"Budget : {NOT_COMMUNICATED}.",
        ]
    else:
        third = (f"{urg['critical']} incidents critiques, "
                 f"{stale} ouverts depuis plus de {STALE_AFTER_DAYS} jours.")
        if top is not None:
            fifth = (f"Priorité : {top.get('school_name', '?')} "
                     f"({top.get('title', '?')}).")
        else:
            fifth = "Priorité : maintenir la surveillance."
        summary = [
            f"Périmètre : {label}.",
            (f"{n_open} {_plural(n_open, 'incident ouvert', 'incidents ouverts')}, "
             f"{_fmt_int(affected)} {_plural(affected, 'élève affecté', 'élèves affectés')}, "
             f"{len(schools)} {_plural(len(schools), 'école suivie', 'écoles suivies')}."),
            third,
            budget_line,
            fifth,
        ]
    sections: list[dict[str, Any]] = [{
        "heading": "Résumé exécutif",
        "body_md": "\n".join(summary[:EXEC_SUMMARY_MAX_LINES]),
        "figures": [],
    }]

    facts = [
        f"Incidents ouverts : {n_open}",
        f"Élèves affectés : {_fmt_int(affected)}",
        f"Écoles suivies : {len(schools)}",
        f"Incidents critiques : {urg['critical']}",
        f"Incidents anciens (> {STALE_AFTER_DAYS} j) : {stale}",
        f"Interventions journalisées : {len(logs)}",
    ]
    figures = [
        {"label": "Incidents ouverts", "value": str(n_open)},
        {"label": "Élèves affectés", "value": _fmt_int(affected)},
        {"label": "Écoles suivies", "value": str(len(schools))},
        {"label": "Incidents critiques", "value": str(urg["critical"])},
        {"label": f"Incidents anciens (> {STALE_AFTER_DAYS} j)", "value": str(stale)},
        {"label": "Interventions journalisées", "value": str(len(logs))},
    ]
    if costs:
        facts.append(f"Coût total journalisé : {_fmt_xaf(total_cost)}")
        figures.append({"label": "Coût total journalisé", "value": _fmt_xaf(total_cost)})
    sections.append({
        "heading": "Faits et chiffres vérifiés",
        "body_md": "\n".join(f"- {line}" for line in facts),
        "figures": figures,
    })

    if empty:
        analysis = ["Aucune donnée à analyser pour ce périmètre."]
    else:
        breakdown = ", ".join(
            f"{_URGENCY_FR[level]} : {urg[level]}" for level in _URGENCY_ORDER)
        analysis = [f"Urgences — {breakdown}."]
        if top_freq is not None:
            title, count = top_freq
            analysis.append(f"Panne la plus fréquente : « {title} » ({count} cas).")
        analysis.append(f"Ancienneté : {stale} "
                        f"{_plural(stale, 'incident ouvert', 'incidents ouverts')} "
                        f"depuis plus de {STALE_AFTER_DAYS} jours.")
    sections.append({
        "heading": "Analyse",
        "body_md": "\n".join(f"- {line}" for line in analysis),
        "figures": [{"label": f"Urgence {_URGENCY_FR[level]}", "value": str(urg[level])}
                    for level in _URGENCY_ORDER] if not empty else [],
    })

    if empty:
        recos = ["Aucune recommandation : aucune donnée vérifiée pour ce périmètre."]
    else:
        recos = []
        if urg["critical"]:
            names = ", ".join(sorted({str(i.get("school_name", "?"))
                                      for i in incidents
                                      if str(i.get("urgency") or "").strip().lower() == "critical"}))
            recos.append(f"Traiter en premier les {urg['critical']} "
                         f"{_plural(urg['critical'], 'incident critique', 'incidents critiques')} : {names}.")
        if stale:
            recos.append(f"Relancer les {stale} "
                         f"{_plural(stale, 'incident ouvert', 'incidents ouverts')} "
                         f"depuis plus de {STALE_AFTER_DAYS} jours.")
        by_district: dict[str, int] = {}
        for incident in incidents:
            by_district[str(incident.get("district", "?"))] = by_district.get(
                str(incident.get("district", "?")), 0) + 1
        grouped = sorted(d for d, n in by_district.items() if n >= 2)
        if grouped:
            recos.append(f"Grouper la tournée : {', '.join(grouped)} "
                         f"({sum(by_district[d] for d in grouped)} incidents sur place).")
        if costs:
            recos.append(f"Débloquer {_fmt_xaf(total_cost)} (montant journalisé) "
                         f"pour solder les {len(costs)} interventions chiffrées.")
        else:
            recos.append("Chiffrer le budget avec les équipes terrain "
                         f"(aucun coût transmis : {NOT_COMMUNICATED}).")
        if not recos:
            recos.append("Aucune action urgente : maintenir la surveillance.")
    sections.append({
        "heading": "Recommandations chiffrées",
        "body_md": "\n".join(f"{rank}. {line}" for rank, line in enumerate(recos, 1)),
        "figures": [],
    })

    if costs:
        per_school: dict[str, float] = {}
        for school, amount in costs:
            per_school[school] = per_school.get(school, 0.0) + amount
        budget = [f"Total journalisé : {_fmt_xaf(total_cost)} "
                  f"({len(costs)} {_plural(len(costs), 'intervention chiffrée', 'interventions chiffrées')})."]
        budget.extend(f"{school} : {_fmt_xaf(amount)}."
                      for school, amount in sorted(per_school.items(),
                                                  key=lambda kv: (-kv[1], kv[0])))
        budget_figures = [
            {"label": "Coût total journalisé", "value": _fmt_xaf(total_cost)},
            {"label": "Interventions chiffrées", "value": str(len(costs))},
        ]
    else:
        budget = [f"Budget : {NOT_COMMUNICATED} "
                  "(aucun coût dans le contexte transmis, aucune estimation)."]
        budget_figures = []
    sections.append({
        "heading": "Budget",
        "body_md": "\n".join(f"- {line}" for line in budget),
        "figures": budget_figures,
    })

    if photo_refs:
        annex_photos = (f"Photos disponibles : {len(photo_refs)} "
                        f"({'; '.join(photo_refs[:10])}"
                        f"{'...' if len(photo_refs) > 10 else ''}).")
    else:
        annex_photos = "Photos : aucune photo dans le contexte."
    annexes = [
        annex_photos,
        (f"Sources transmises : {context_sizes.get('schools', 0)} écoles, "
         f"{context_sizes.get('incidents', 0)} incidents, "
         f"{context_sizes.get('logs', 0)} journaux."),
        "Provenance : chiffres calculés uniquement depuis le contexte transmis, aucune estimation.",
    ]
    sections.append({
        "heading": "Annexes",
        "body_md": "\n".join(f"- {line}" for line in annexes),
        "figures": [{"label": "Photos disponibles", "value": str(len(photo_refs))}],
    })
    return sections


def _poster_prompt(
    label: str,
    schools: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
) -> tuple[str, str]:
    """Prompt FR vendeur mais factuel + légende (école, panne, chiffres vérifiés)."""
    n_open = len(incidents)
    affected = sum(_to_int(i.get("affected_students")) for i in incidents)
    if not schools and not incidents:
        prompt = (
            f"Affiche de mobilisation WASH pour {label} : l'eau potable pour "
            "chaque école. Slogan : « L'eau pour tous, maintenant ! ». Style : "
            "affiche humanitaire vibrante, enfants souriants autour d'une pompe "
            "à eau bleue, soleil levant, texte français bien lisible."
        )
        return prompt, f"{label} : dossier décideur WASH (aucune donnée vérifiée)."
    top = _top_incident(incidents)
    detail = ""
    if top is not None:
        detail = (f" ({top.get('title', '?')} à "
                  f"{top.get('school_name', '?')})")
    prompt = (
        f"Affiche de mobilisation WASH pour {label} : "
        f"{_fmt_int(affected)} élèves privés d'eau potable, "
        f"{n_open} {_plural(n_open, 'incident ouvert', 'incidents ouverts')}"
        f"{detail}. Slogan : « L'eau pour {label}, maintenant ! ». Style : "
        "affiche humanitaire vibrante, enfants souriants autour d'une pompe "
        "à eau bleue, soleil levant, texte français bien lisible."
    )
    caption = (f"{label} : {_fmt_int(affected)} élèves affectés, "
               f"{n_open} {_plural(n_open, 'incident ouvert', 'incidents ouverts')} "
               "— dossier décideur WASH.")
    return prompt, caption


def _deck_ref(label: str, context: dict[str, Any]) -> dict[str, Any]:
    """Diaporama : réutilise le briefing existant en lecture seule (jamais modifié)."""
    topic = "" if label == "tout le territoire" else label
    try:
        deck = _briefing_execute({"topic": topic, "format": "diaporama"}, context)
    except Exception as exc:  # contrat : build_dossier ne lève jamais
        return {"source": None, "reason": f"Diaporama indisponible : {exc}"}
    slides = deck.get("slides") or []
    if deck.get("error") or not slides:
        return {"source": None,
                "reason": str(deck.get("error") or "aucune slide pour ce périmètre")}
    return {"source": "document_briefing", "topic": topic or None,
            "format": "diaporama", "slides_count": len(slides),
            "slides": slides, "insight": str(deck.get("insight", ""))}


def build_dossier(
    scope_type: str | None = None,
    scope_id: Any = None,
    scope_name: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble le dossier décideur (pur : données du contexte uniquement, sans LLM).

    Retourne {"report", "poster_prompt", "poster_caption", "deck_ref"} où
    report = {subject, period, sections[{heading, body_md, figures[]}]}.
    Ne lève jamais : périmètre vide ou contexte absent = sections honnêtes.
    """
    try:
        context = context if isinstance(context, dict) else {}
        label, schools, incidents, logs = _resolve_scope(
            scope_type, scope_id, scope_name, context)
        sizes = {"schools": len(_as_list(context.get("schools"))),
                 "incidents": len(_as_list(context.get("incidents"))),
                 "logs": len(_as_list(context.get("maintenance_logs")))}
        sections = _build_sections(
            label, schools, incidents, logs,
            _photo_refs(context, incidents), sizes)
        report = {"subject": f"Dossier décideur — {label}",
                  "period": _period(incidents, logs),
                  "sections": sections}
        prompt, caption = _poster_prompt(label, schools, incidents)
        deck_context = {"schools": schools, "incidents": incidents,
                        "maintenance_logs": logs}
        return {"report": report, "poster_prompt": prompt,
                "poster_caption": caption,
                "deck_ref": _deck_ref(label, deck_context)}
    except Exception as exc:  # contrat : jamais d'exception vers l'appelant
        report = {"subject": "Dossier décideur",
                  "period": NOT_COMMUNICATED,
                  "sections": [{"heading": h, "body_md": f"Dossier indisponible : {exc}",
                                "figures": []} for h in SECTION_HEADINGS]}
        return {"report": report,
                "poster_prompt": "Affiche de mobilisation WASH.",
                "poster_caption": "Dossier décideur WASH.",
                "deck_ref": {"source": None, "reason": f"Dossier indisponible : {exc}"}}


def build_poster_card(poster: dict[str, Any]) -> AgentCard | None:
    """Carte `poster` {image_base64|image_url, prompt, caption} (None si vide)."""
    if not isinstance(poster, dict):
        return None
    if not poster.get("image_base64") and not poster.get("image_url"):
        return None
    try:
        data = PosterCardData(
            image_base64=poster.get("image_base64"),
            image_url=poster.get("image_url"),
            prompt=str(poster.get("prompt") or ""),
            caption=str(poster.get("caption") or ""),
        )
    except Exception:
        return None
    if not data.prompt or not data.caption:
        return None
    return AgentCard(type="poster", title="Affiche WASH",
                     data=data.model_dump())


def build_dossier_report_card(report: dict[str, Any]) -> AgentCard | None:
    """Carte `dossier_report` {subject, period, sections[]} (None si vide)."""
    if not isinstance(report, dict):
        return None
    if not report.get("subject") or not report.get("sections"):
        return None
    try:
        sections = [DossierReportSection(
            heading=str(s.get("heading") or ""),
            body_md=str(s.get("body_md") or ""),
            figures=[{str(k): str(v) for k, v in f.items()}
                     if isinstance(f, dict) else {}
                     for f in (s.get("figures") or [])],
        ) for s in report["sections"]]
        data = DossierReportCardData(
            subject=str(report.get("subject") or ""),
            period=str(report.get("period") or ""),
            sections=sections,
        )
    except Exception:
        return None
    if any(not s.heading or not s.body_md for s in data.sections):
        return None
    return AgentCard(type="dossier_report", title=data.subject,
                     data=data.model_dump())


#: Builders prêts pour le câblage parent (inertes : module non auto-découvert).
CARD_BUILDERS = {
    "poster": build_poster_card,
    "dossier_report": build_dossier_report_card,
}


async def run_dossier(
    llm: Any,
    scope_type: str | None = None,
    scope_name: str | None = None,
    context: dict[str, Any] | None = None,
    scope_id: Any = None,
    size: str = POSTER_SIZE_DEFAULT,
) -> dict[str, Any]:
    """Dossier complet : rapport pur + affiche cloud + diaporama (câblé par le parent).

    `llm` = provider exposant generate_image(prompt, size) -> bytes.
    Retourne {"report", "poster", "poster_error", "deck_ref", "cards"} :
    report/poster aux clés exactes du contrat, cards = AgentCards prêtes.
    L'échec image n'échoue jamais le dossier (poster_error explicite).
    """
    built = build_dossier(scope_type, scope_id, scope_name, context)
    report = built["report"]
    poster: dict[str, Any] = {"image_base64": None, "image_url": None,
                              "prompt": built["poster_prompt"],
                              "caption": built["poster_caption"]}
    poster_error: str | None = None
    try:
        image_bytes = await llm.generate_image(built["poster_prompt"], size)
    except Exception as exc:  # noqa: BLE001 - échec image explicite, dossier gardé
        poster_error = (f"Affiche indisponible : {exc}")
    else:
        if isinstance(image_bytes, (bytes, bytearray)) and bytes(image_bytes):
            poster["image_base64"] = base64.b64encode(bytes(image_bytes)).decode("ascii")
        else:
            poster_error = ("Affiche indisponible : le fournisseur a renvoyé "
                            "une image vide.")
    cards: list[AgentCard] = []
    poster_card = build_poster_card(poster)
    if poster_card is not None:
        cards.append(poster_card)
    report_card = build_dossier_report_card(report)
    if report_card is not None:
        cards.append(report_card)
    return {"report": report, "poster": poster, "poster_error": poster_error,
            "deck_ref": built["deck_ref"], "cards": cards}
