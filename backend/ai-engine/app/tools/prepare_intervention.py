"""Plugin : dossier de PRÉPARATION d'intervention à venir (sans écriture).

Prépare une intervention FUTURE sur un incident EXISTANT : incident ciblé,
date, budget XAF, équipe, verdict réparer/remplacer + verdict budget.
SANS RIEN ÉCRIRE — la confirmation humaine reste exigée en aval.

Le kit réparation (outils/pièces/sécurité/durée) est ajouté par la boucle
agent (LLM, repli hors ligne sinon) ; en appel direct modèle, la carte
reste partielle mais valide.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from ..schemas import AgentCard
from ..tool_consts import INCIDENT_FUZZY_MIN_RATIO
from .copilot_answer import execute as copilot_execute

TOOL_NAME = "prepare_intervention"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Prépare une INTERVENTION À VENIR sur un incident EXISTANT (date, "
        "budget XAF, équipe, verdict réparer/remplacer) sans RIEN écrire. "
        "UNIQUEMENT quand l'utilisateur veut PLANIFIER ou ORGANISER une "
        "réparation future (« prépare une intervention pour demain avec un "
        "budget de 100 000 XAF pour la pompe »). "
        "Ne JAMAIS utiliser pour : une NOUVELLE panne à signaler (voir "
        "prepare_incident), consigner un AVANCEMENT de chantier (voir "
        "prepare_chantier_update), une ANALYSE large d'école (voir "
        "analyze_school), un briefing/rapport/affiche (voir build_briefing). "
        "Accepte tout sous-ensemble d'arguments et retourne fields + "
        "missing + questions courtes (2 max)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "incident": {
                "type": "string",
                "description": "Incident existant ciblé : id, référence WASH-... ou mots du titre",
            },
            "date_text": {
                "type": "string",
                "description": "Date prévue : « demain », « lendemain », « après-demain », JJ/MM/AAAA",
            },
            "budget": {
                "type": "string",
                "description": "Budget alloué : « 100 000 XAF », « 100k », 100000",
            },
            "team": {
                "type": "string",
                "description": "Équipe/technicien pressenti (optionnel, proposé sinon)",
            },
            "school": {
                "type": "string",
                "description": "École concernée (optionnel si l'incident est unique)",
            },
        },
    },
}

READ_ONLY = True

# Indices de PLANIFICATION future (formes longues : pas de collision avec
# « crée une intervention » / « consigne » / « équipe » des plugins frères).
INTENT_HINTS = frozenset({
    "prépare une intervention",
    "prepare une intervention",
    "préparer une intervention",
    "planifie une intervention",
    "planifier une intervention",
    "organise une intervention",
    "organiser une intervention",
    "prépare la réparation",
    "prepare la reparation",
    "planifie la réparation",
    "intervention pour demain",
    "intervention pour le lendemain",
})

_REQUIRED = ("incident", "date", "budget_xaf", "team")

_SLOT_LABELS = {
    "incident": "l'incident existant ciblé (titre ou référence)",
    "date": "la date prévue (demain, lendemain, JJ/MM/AAAA)",
    "budget_xaf": "le budget alloué en XAF",
    "team": "l'équipe qui interviendra",
}

_SLOT_QUESTIONS = {
    "incident": "Quel incident existant faut-il réparer (titre ou référence) ?",
    "date": "Pour quelle date prévoir l'intervention ?",
    "budget_xaf": "Quel budget allouez-vous (en XAF) ?",
    "team": "Quelle équipe doit intervenir ?",
}

_MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
)

_BUDGET_CURRENCY_RE = re.compile(
    r"(\d[\d\s\u00a0.,]*)\s*(XAF|FCFA|francs?)", re.IGNORECASE)
_BUDGET_K_RE = re.compile(r"(\d[\d\s\u00a0.,]*)\s*k\b", re.IGNORECASE)
_BUDGET_OF_RE = re.compile(r"budget(?:\s+de)?\s+(\d[\d\s\u00a0.,]*)",
                            re.IGNORECASE)
_DATE_NUM_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_DATE_DAY_RE = re.compile(r"\ble\s+(\d{1,2})\b")

_ASSIGNEE_KEYS = ("assignee", "assignee_name", "assigned_to",
                  "technician", "technicien")

_CLOSED = ("resolved", "closed")


def _norm(text: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    return raw.encode("ascii", "ignore").decode("ascii").lower()


def _today(args: dict[str, Any]) -> date:
    raw = str(args.get("today") or "").strip()
    if raw:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def parse_budget(raw: Any) -> int | None:
    """Budget XAF depuis un nombre ou un texte (« 100 000 XAF », « 100k »).

    Dans un texte libre, seules les formes explicites comptent (devise,
    suffixe k, ou « budget de N ») : un nombre nu (« le 3 », « 6 pannes »)
    n'est JAMAIS pris pour un budget.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if raw >= 0 else None
    text = str(raw or "")
    if not text.strip():
        return None
    match = (_BUDGET_CURRENCY_RE.search(text) or _BUDGET_K_RE.search(text)
             or _BUDGET_OF_RE.search(text))
    if match is None:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    if not digits:
        return None
    amount = int(digits)
    tail = match.group(0)[match.group(0).rindex(match.group(1)) + len(match.group(1)):]
    if tail.strip().lower().startswith("k"):
        amount *= 1000
    return amount


def parse_date(raw: Any, today: date) -> date | None:
    """Date prévue depuis un texte libre (relatif ou JJ/MM[/AAAA])."""
    text = _norm(raw)
    if not text:
        return None
    if "apres-demain" in text or "apres demain" in text:
        return today + timedelta(days=2)
    if "demain" in text or "lendemain" in text:
        return today + timedelta(days=1)
    if "aujourd" in text:
        return today
    match = _DATE_NUM_RE.search(str(raw or ""))
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year_raw = match.group(3)
        year = today.year if year_raw is None else int(year_raw)
        if year < 100:
            year += 2000
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
        if year_raw is None and parsed < today:
            try:
                parsed = date(year + 1, month, day)
            except ValueError:
                return None
        return parsed
    match = _DATE_DAY_RE.search(text)
    if match:
        day = int(match.group(1))
        try:
            parsed = date(today.year, today.month, day)
        except ValueError:
            return None
        if parsed < today:
            month = today.month + 1 if today.month < 12 else 1
            year = today.year if today.month < 12 else today.year + 1
            try:
                parsed = date(year, month, day)
            except ValueError:
                return None
        return parsed
    return None


def date_label_fr(day: date) -> str:
    return f"{day.day} {_MONTHS_FR[day.month - 1]} {day.year}"


def _fmt_xaf(value: Any) -> str:
    try:
        return f"{int(float(value or 0)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _open_incidents(context: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for row in context.get("incidents", []) or []:
        if isinstance(row, dict) and str(row.get("status") or "").lower() not in _CLOSED:
            out.append(row)
    return out


def _match_incidents(pool: list[dict[str, Any]], ref: Any) -> list[dict[str, Any]]:
    """Candidats par force décroissante : id, réf exacte, puis flou."""
    if ref is None or str(ref).strip() == "":
        return []
    try:
        wanted = int(ref)  # type: ignore[arg-type]
        if not isinstance(ref, bool):
            return [i for i in pool
                    if isinstance(i, dict) and i.get("id") == wanted][:1]
    except (TypeError, ValueError):
        pass
    hint = str(ref).strip().lower()
    for incident in pool:
        if str(incident.get("reference_code", "")).lower() == hint:
            return [incident]
    # Référence noyée dans une phrase (« ... pour WASH-2026-PUMP à ... ») :
    # l'égalité stricte ne suffit pas, on l'extrait avant le flou.
    buried = re.search(r"wash-\d{4}-[a-z0-9]+", hint)
    if buried:
        for incident in pool:
            if str(incident.get("reference_code", "")).lower() == buried.group(0):
                return [incident]
    scored: list[tuple[int, dict[str, Any]]] = []
    tokens = [t for t in hint.split() if len(t) >= 3]
    for incident in pool:
        code = str(incident.get("reference_code", "")).lower()
        title = str(incident.get("title", "")).lower()
        if hint in code or hint in title:
            scored.append((3, incident))
        elif tokens and all(t in title for t in tokens):
            scored.append((2, incident))
    if not scored and len(hint) >= 4:
        for incident in pool:
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


def _incident_choices(pool: list[dict[str, Any]], limit: int = 5) -> str:
    choices = []
    for incident in pool[:limit]:
        choices.append(
            f"{incident.get('reference_code', '?')} — "
            f"{incident.get('title', '?')} (id {incident.get('id')})")
    return ", ".join(choices) if choices else "aucun incident dans le contexte"


def _assignee_of(row: dict[str, Any]) -> str | None:
    for key in _ASSIGNEE_KEYS:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if int(value) > 0:
                return f"agent #{int(value)}"
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _active_teams(context: dict[str, Any],
                district: str | None) -> list[str]:
    """Noms des équipes actives, restreintes au district si connu.

    Repli géographique : aucun match dans le district mais des équipes
    ailleurs -> toutes les équipes (mieux que rien proposer).
    """
    teams = [t for t in context.get("teams", []) or []
             if isinstance(t, dict) and t.get("is_active", True)
             and str(t.get("name") or "").strip()]
    if district:
        scoped = [t for t in teams
                  if str(t.get("district") or "").strip().lower()
                  == district.strip().lower()]
        if scoped:
            teams = scoped
    seen: list[str] = []
    for team in teams:
        name = str(team.get("name")).strip()
        if name not in seen:
            seen.append(name)
    return seen


def _team_choices(context: dict[str, Any], pool: list[dict[str, Any]],
                  district: str | None) -> list[str]:
    """Équipes proposées : vraies équipes du contexte, sinon assignés."""
    teams = _active_teams(context, district)
    if teams:
        return teams
    seen: list[str] = []
    for row in pool:
        who = _assignee_of(row)
        if who and who not in seen:
            seen.append(who)
    return seen


def _school_of(context: dict[str, Any], school_hint: Any,
               incident: dict[str, Any] | None) -> dict[str, Any] | None:
    schools = [s for s in context.get("schools", []) or [] if isinstance(s, dict)]
    if incident is not None:
        sid = incident.get("school_id")
        sname = str(incident.get("school_name") or "").strip().lower()
        for school in schools:
            if sid is not None and school.get("school_id") == sid:
                return school
            if sname and str(school.get("school_name") or "").strip().lower() == sname:
                return school
    hint = _norm(school_hint)
    if hint:
        tokens = [t for t in hint.replace("-", " ").split() if len(t) >= 3]
        for school in schools:
            name = _norm(school.get("school_name"))
            if hint in name or (tokens and all(t in name for t in tokens)):
                return school
    return None


def _candidate_card(incident: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "reference_code", "title", "school_name", "district",
            "category", "urgency", "status", "affected_students",
            "priority_score", "reported_at")
    return {key: incident.get(key) for key in keys}


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Dossier de préparation d'intervention (déterministe, sans écriture)."""
    try:
        if not isinstance(args, dict):
            args = {}
        if not isinstance(context, dict):
            context = {}
        today = _today(args)
        pool = _open_incidents(context)

        school_hint = str(args.get("school") or "").strip()
        hint = str(args.get("incident") or "").strip()
        scoped = pool
        if school_hint:
            wanted = _norm(school_hint)
            tokens = [t for t in wanted.replace("-", " ").split() if len(t) >= 3]
            filtered = [i for i in pool
                        if wanted in _norm(i.get("school_name"))
                        or (tokens and all(t in _norm(i.get("school_name")) for t in tokens))]
            if filtered:
                scoped = filtered
        candidates = _match_incidents(scoped, hint)
        incident = candidates[0] if len(candidates) == 1 else None

        planned = parse_date(args.get("date_text"), today)
        budget = parse_budget(args.get("budget"))
        team = str(args.get("team") or "").strip() or None

        school = _school_of(context, school_hint, incident)
        school_name = (str(school.get("school_name")) if school
                       else (str(incident.get("school_name") or "") if incident else None))
        district = (str(school.get("district") or "") if school
                    else (str(incident.get("district") or "") if incident else None))

        verdict: dict[str, Any] | None = None
        if school_name:
            copilot = copilot_execute(
                {"question": f"Faut-il réparer ou remplacer le matériel à {school_name} ?"},
                context)
            if isinstance(copilot, dict) and not copilot.get("error"):
                verdict = {
                    "recommendation": copilot.get("recommendation"),
                    "recommendation_label": copilot.get("recommendation_label"),
                    "figures": copilot.get("figures", {}),
                    "insight": copilot.get("insight"),
                }

        budget_verdict: str | None = None
        figures = (verdict or {}).get("figures", {}) or {}
        replacement = figures.get("estimated_replacement_cost") or 0
        try:
            replacement = float(replacement)
        except (TypeError, ValueError):
            replacement = 0.0
        if budget is not None:
            if replacement > 0:
                if budget >= replacement:
                    budget_verdict = (
                        f"Budget {_fmt_xaf(budget)} XAF : couvre même un remplacement "
                        f"(~{_fmt_xaf(replacement)} XAF).")
                elif (verdict or {}).get("recommendation") == "REPLACE":
                    budget_verdict = (
                        f"Budget {_fmt_xaf(budget)} XAF insuffisant pour le remplacement "
                        f"recommandé (~{_fmt_xaf(replacement)} XAF) : couvre une réparation "
                        "d'attente, pas le neuf.")
                else:
                    budget_verdict = (
                        f"Budget {_fmt_xaf(budget)} XAF enregistré pour la réparation.")
            else:
                budget_verdict = f"Budget {_fmt_xaf(budget)} XAF enregistré."

        label = None
        if incident is not None:
            label = (f"{incident.get('reference_code') or incident.get('id')}"
                     f" — {incident.get('title', '?')}")

        fields: dict[str, Any] = {
            "incident_id": incident.get("id") if incident else None,
            "incident_ref": incident.get("reference_code") if incident else None,
            "incident_label": label,
            "school_name": school_name,
            "district": district,
            "date": planned.isoformat() if planned else None,
            "date_label": date_label_fr(planned) if planned else None,
            "budget_xaf": budget,
            "team": team,
        }
        missing = [slot for slot in _REQUIRED
                   if (slot == "incident" and incident is None)
                   or (slot == "date" and planned is None)
                   or (slot == "budget_xaf" and budget is None)
                   or (slot == "team" and not team)]
        labels = [_SLOT_LABELS[m] for m in missing]
        questions = [_SLOT_QUESTIONS[m] for m in missing[:2]]
        ready = not missing

        team_pool = [i for i in pool
                     if school_name and str(i.get("school_name") or "") == school_name] or pool
        team_choices = _team_choices(context, team_pool, district)
        if team_choices and "team" in missing:
            # La question propose les équipes au lieu de rester vide.
            suggest = (f"Quelle équipe doit intervenir "
                       f"({', '.join(team_choices[:3])}) ?")
            questions = [suggest if q == _SLOT_QUESTIONS["team"] else q
                         for q in questions]

        rows = [f"{k} : {v}" for k, v in
                (("Incident", label), ("École", school_name),
                 ("Date", fields["date_label"]), ("Budget (XAF)", budget),
                 ("Équipe", team)) if v is not None]
        recap = "Préparation d'intervention\n" + "\n".join(rows)
        if labels:
            recap += "\nManquant : " + ", ".join(labels) + "."

        if ready:
            insight = (f"Intervention prête : {label}, le {fields['date_label']}, "
                       f"budget {_fmt_xaf(budget)} XAF, équipe {team}.")
        else:
            insight = ("Préparation partielle (rien n'est enregistré) — "
                       f"manque : {', '.join(labels)}.")
        if budget_verdict:
            insight += f" {budget_verdict}"

        obs: dict[str, Any] = {
            "insight": insight,
            "action": "prepare_intervention",
            "complete": ready,
            "fields": fields,
            "missing": missing,
            "missing_labels": labels,
            "questions": questions,
            "ready": ready,
            "recap": recap,
            "verdict": verdict,
            "budget_verdict": budget_verdict,
            "team_choices": team_choices,
        }
        if hint and incident is None:
            obs["hint_unmatched"] = hint
            obs["incident_choices"] = _incident_choices(
                candidates if candidates else scoped)
            if len(candidates) > 1:
                obs["candidates"] = [_candidate_card(c) for c in candidates[:5]]
        return obs
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _build_intervention_prep_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict):
        return None
    if obs.get("error"):
        return None
    fields = obs.get("fields")
    if not isinstance(fields, dict):
        return None
    has_value = any(v is not None and v != "" for v in fields.values())
    if not has_value and not obs.get("missing") and not obs.get("questions"):
        return None
    title = "Préparation d'intervention"
    if fields.get("incident_label"):
        title = f"Intervention — {fields['incident_label']}"
    return AgentCard(type="intervention_prep", title=title, data=obs)


CARD_BUILDERS = {"intervention_prep": _build_intervention_prep_card}
