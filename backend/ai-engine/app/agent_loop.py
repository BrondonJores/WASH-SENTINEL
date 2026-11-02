from __future__ import annotations

import base64
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Literal

from .agent_tools import AGENT_TOOLS, PLUGIN_CARDS, PLUGIN_HINTS, PLUGIN_READ_ONLY, TOOL_EXECUTORS
from .guidance import build_guidance_card
from .guided_voice import guided_turn, resolve_guided_lang
from .image_analyzer import ImageAnalyzer, decode_chat_image, is_vision_unavailable
from .place_suggest import suggest_places
from .prompts import SMALL_MODEL_RE, render_agent_prompt


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
from .providers import BaseLLMProvider
from .router import is_data_question
from .router import route as router_route
from .schemas import (
    CHAT_IMAGE_DEFAULT_MIME,
    AgentCard,
    AgentChatRequest,
    AgentChatResponse,
    ImageAnalysisResponse,
)

#: Prompt système : rendu neutre des sections prompts.agent_sections()
#: (mêmes règles comportementales, une phrase par règle).
SYSTEM_PROMPT = render_agent_prompt()

#: Garde-fou boucle agent (hérité, cf. app/thresholds.py inventaire AXE 8).
#: Override ENV : AGENT_MAX_ITERATIONS (défaut historique 5).
MAX_ITERATIONS = _env_int("AGENT_MAX_ITERATIONS", 5)
# Budget wall-clock d'un run (surtout CPU local) : au-delà, on conclut
# avec le résumé déterministe plutôt que de laisser l'UI pendre.
# Override ENV : AGENT_RUN_BUDGET_S (défaut historique 100.0).
RUN_BUDGET_S = _env_float("AGENT_RUN_BUDGET_S", 100.0)
# Budget total d'appels LLM par run (boucle + recadrages force/absence) :
# sans lui, le pire cas monte à 11 appels (5 + 2 + 2 + 2), rédhibitoire
# sur CPU froid. Au-delà, résumé déterministe honnête (jamais d'invention).
# Override ENV : AGENT_MAX_LLM_CALLS (défaut historique 6).
MAX_LLM_CALLS = _env_int("AGENT_MAX_LLM_CALLS", 6)
# Payload scoping : l'historique et les observations sont bornés pour ne pas
# noyer les petits modèles (chaque token ajouté ralentit chaque appel).
#: Override ENV : AGENT_HISTORY_TURNS (défaut historique 6).
HISTORY_TURNS = _env_int("AGENT_HISTORY_TURNS", 6)
#: Override ENV : AGENT_HISTORY_TURN_MAX_CHARS (défaut historique 1200).
HISTORY_TURN_MAX_CHARS = _env_int("AGENT_HISTORY_TURN_MAX_CHARS", 1200)
#: Override ENV : AGENT_HISTORY_MAX_CHARS (défaut historique 4000).
HISTORY_MAX_CHARS = _env_int("AGENT_HISTORY_MAX_CHARS", 4000)
#: Override ENV : AGENT_OBS_LIST_MAX_ITEMS (défaut historique 12).
OBS_LIST_MAX_ITEMS = _env_int("AGENT_OBS_LIST_MAX_ITEMS", 12)
#: Override ENV : AGENT_OBS_STR_MAX_CHARS (défaut historique 2000).
OBS_STR_MAX_CHARS = _env_int("AGENT_OBS_STR_MAX_CHARS", 2000)
# Petits modèles locaux : descriptions d'outils compactées (le prompt
# complet à 24 outils les noie et ralentit chaque appel).
# SMALL_MODEL_RE : source unique prompts.py (importé plus haut, fini le duplicata).
FOLLOWUP_RE = re.compile(
    r"(je parle d[e']|il s'agit d[e']|et (?:pour|à|au|en)|celui (?:de|du)|"
    r"dans (?:le |la |les )?|concernant|pour)\s+(.+)",
    re.IGNORECASE,
)

REPEAT_NUDGE = (
    "Tu as déjà appelé cet outil avec ces mêmes arguments : le résultat est plus haut. "
    "N'appelle plus aucun outil et réponds maintenant à l'utilisateur en français."
)

NO_TOOL_NUDGE = (
    "Tu as répondu à une question de données sans appeler d'outil : "
    "appelle l'outil adapté maintenant "
    "(rank_schools_by_need, summarize_district, analyze_school, repair_trends, "
    "explain_incident, territory_overview, build_briefing, list_maintenance_logs"
    + "".join(f", {n}" for n in sorted(PLUGIN_READ_ONLY)) +
    "). N'écris aucun texte, appelle juste l'outil."
)


def route_intent(question: str) -> Literal["list", "create", "other"]:
    """Route la question : consultation du passé, création, ou autre (fonction pure).

    Fine couche de compatibilité : délégation au routeur calibré (app.router) avec les
    indices plugins. « create » seulement sans indice de liste ; « list » dès
    qu'un indice de liste est présent ; sinon « other » (jeu complet).
    """
    return router_route(question or "", PLUGIN_HINTS)["intent"]


def tools_for_intent(intent: str) -> list[dict[str, Any]]:
    """Jeu d'outils exposé : en consultation, les prepare_* (création) sont masqués."""
    if intent == "list":
        return [t for t in AGENT_TOOLS
                if not t.get("function", {}).get("name", "").startswith("prepare_")]
    return list(AGENT_TOOLS)


def compact_tools(tools: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    """Descriptions raccourcies pour les petits modèles (prompt allégé).

    Prend short_description quand l'outil en porte une, sinon repli sur la
    coupe historique (avant "Exemple :" / "Ne JAMAIS").
    Modèles non reconnus comme petits : jeu inchangé.
    """
    if not SMALL_MODEL_RE.search(model or ""):
        return tools
    out: list[dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function", {})
        desc = str(fn.get("description", ""))
        short = str(fn.get("short_description") or "").strip()
        if not short:
            short = re.split(r"Exemple\s*:|Ne JAMAIS", desc)[0].strip()
        out.append({**tool, "function": {**fn, "description": short or desc}})
    return out


def _norm(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(c))


def known_places(context: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(écoles, districts) connus — délégation au canonique textnorm (AXE 3)."""
    from .textnorm import known_places as _canonical_known_places
    return _canonical_known_places(context or {})


def resolve_place(message: str, context: dict[str, Any]) -> tuple[str, str] | None:
    """Lieu connu cité dans le message : ("school"|"district", libellé).

    Plus longue correspondance (nom complet ou mot significatif, >= 4
    lettres, insensible casse/accents). None si rien de reconnu.
    """
    lowered = _norm(message)
    schools, districts = known_places(context)
    candidates: list[tuple[str, str, str]] = [
        ("district", d, _norm(d)) for d in districts]
    for school in schools:
        candidates.append(("school", school, _norm(school)))
        for token in _norm(school).split():
            if len(token) >= 4:
                candidates.append(("school", school, token))
    best: tuple[str, str] | None = None
    best_len = 0
    for kind, label, normed in candidates:
        if len(normed) >= 4 and normed in lowered and len(normed) > best_len:
            best, best_len = (kind, label), len(normed)
    return best


def followup_hint(message: str, context: dict[str, Any]) -> str:
    """Précision déterministe pour les suivis vagues ("je parle de X").

    Chaîne vide si le message n'est pas un suivi avec lieu reconnu.
    """
    if not FOLLOWUP_RE.search(message):
        return ""
    place = resolve_place(message, context)
    if place is None:
        return ""
    kind_fr = "le district" if place[0] == "district" else "l'école"
    return (f"\n(Précision de suivi : {kind_fr} {place[1]}. "
            "Reprends ma demande précédente pour ce lieu.)")


# Garde-fou abstention : outils de lecture dont l'observation autorise un constat.
READ_TOOLS = frozenset({
    "list_maintenance_logs", "summarize_district", "rank_schools_by_need",
    "repair_trends", "explain_incident", "territory_overview",
    "analyze_school", "build_briefing",
}) | PLUGIN_READ_ONLY

ABSENCE_RE = re.compile(r"aucun|aucune|pas d|rien|zéro|zero", re.IGNORECASE)

ABSENCE_CORRECTION_NUDGE = (
    "Tu viens d'affirmer une absence (aucun/aucune/rien/zéro) sans avoir "
    "observé un outil de lecture : appelle maintenant "
    "l'outil de liste adapté (list_maintenance_logs pour les interventions passées, "
    "sinon summarize_district, rank_schools_by_need, repair_trends, explain_incident, "
    "territory_overview, analyze_school ou build_briefing) puis réponds à partir de "
    "son observation. N'écris aucun texte, appelle juste l'outil."
)

UNVERIFIED_HONEST_ANSWER = (
    "Je ne peux pas vérifier les interventions pour cette question, car il me "
    "manque une précision : la date exacte (par exemple 2026-10-15) ou le nom "
    "de l'école. Par exemple, demandez-moi : « Quelles interventions ont été "
    "réalisées le 2026-10-15 ? ». Demandez par exemple : « Montrez les "
    "interventions d'hier » ou « Quels travaux cette semaine à Bonanjo ? », "
    "et je consulterai le journal avec plaisir."
)


def _claims_absence(answer: str) -> bool:
    """La réponse affirme-t-elle une absence (aucun, rien, zéro...) ?"""
    return bool(answer and ABSENCE_RE.search(answer))


def _has_read_tool(executed: list[tuple[str, dict[str, Any]]]) -> bool:
    """Au moins un outil de lecture a-t-il été appelé ce tour-ci ?"""
    return any(name in READ_TOOLS for name, _ in executed)


WASH_REF_RE = re.compile(r"WASH-\d{4}-[A-Z0-9]+")

CONTRADICTION_CORRECTION_NUDGE = (
    "Tu cites une référence précise puis affirmes une absence "
    "(aucun/aucune/rien/zéro) alors que ton observation de liste adossée a "
    "un total de 0 : c'est contradictoire. Relis tes observations : si une "
    "référence WASH-AAAA-XXXX existe vraiment, décris-la sans affirmer "
    "d'absence ; si le total est vraiment 0, ne cite aucune référence. "
    "Rappelle maintenant l'outil de liste adapté (list_maintenance_logs pour "
    "les interventions passées) sans filtre école parasite, puis réponds de "
    "façon cohérente à partir de son observation. N'écris aucun texte, "
    "appelle juste l'outil."
)


def _cites_reference(answer: str) -> bool:
    """La réponse cite-t-elle une référence WASH-AAAA-XXXX concrète ?"""
    return bool(answer and WASH_REF_RE.search(answer))


def _has_empty_list_obs(executed: list[tuple[str, dict[str, Any]]]) -> bool:
    """Une observation de liste adossée a-t-elle un total de 0 ?"""
    return any(
        name in READ_TOOLS and isinstance(obs, dict) and obs.get("total") == 0
        for name, obs in executed
    )


REFUSAL_PATTERNS = (
    "je suis désolé",
    "je ne peux pas vous aider",
    "je ne peux pas répondre",
    "désolé, mais je ne peux",
    "impossible de vous aider",
)


# Détection de langue FR/EN : heuristique déterministe à base de mots-outils.
# Les mots identiques ou ambigus dans les deux langues (« on », « un », « a »,
# « or », « plus », « resume », « me ») sont exclus des deux listes.
_EN_TOOL_WORDS = frozenset(
    "the and is are was were be been being of to in at for with from "
    "that this these those what which who where when how why there their "
    "your you we our my will would can could should have has had do does did "
    "show list need needs help please hello hi thanks thank give "
    "school schools water".split()
)

_FR_TOOL_WORDS = frozenset(
    "le la les des du de une est sont était etait été ete être etre ont "
    "et ou mais si alors que qui quoi quel quelle quels quelles "
    "comment pourquoi où quand combien avec pour dans sur par moins "
    "cette ces cela ça votre vos notre nos nous vous ils elles "
    "bonjour salut merci affiche montre liste listes panne pannes "
    "école ecole écoles ecoles eau résume état etat besoin aide".split()
)

_TOKEN_RE = re.compile(r"[a-zàâäéèêëîïôöùûüç]+")

#: Mots-outils normalisés (sans accents, cf. _norm) pour la détection de langue.
_EN_TOOL_WORDS_NORM = frozenset(
    "".join(c for c in unicodedata.normalize("NFKD", w) if not unicodedata.combining(c))
    for w in _EN_TOOL_WORDS
)
_FR_TOOL_WORDS_NORM = frozenset(
    "".join(c for c in unicodedata.normalize("NFKD", w) if not unicodedata.combining(c))
    for w in _FR_TOOL_WORDS
)

#: Preuve minimale : 2 mots-outils ou 4 tokens, sinon français par défaut.
#: Overrides ENV : AGENT_LANG_MIN_HITS / AGENT_LANG_MIN_TOKENS.
_LANG_MIN_HITS = _env_int("AGENT_LANG_MIN_HITS", 2)
_LANG_MIN_TOKENS = _env_int("AGENT_LANG_MIN_TOKENS", 4)


def detect_lang_details(message: str) -> dict[str, Any]:
    """Scores de détection FR/EN : {lang, en, fr, tokens, defaulted}.

    Tokens normalisés (accents repliés), mots de 1-2 lettres ignorés.
    Sans preuve suffisante (>= 2 mots-outils ou >= 4 tokens) : 'fr'.
    Sinon le score le plus élevé gagne, égalité -> 'fr'.
    """
    tokens = [t for t in _TOKEN_RE.findall(_norm(message or "")) if len(t) > 2]
    en_score = sum(1 for token in tokens if token in _EN_TOOL_WORDS_NORM)
    fr_score = sum(1 for token in tokens if token in _FR_TOOL_WORDS_NORM)
    if en_score + fr_score < _LANG_MIN_HITS and len(tokens) < _LANG_MIN_TOKENS:
        return {"lang": "fr", "en": en_score, "fr": fr_score,
                "tokens": len(tokens), "defaulted": True}
    lang = "en" if en_score > fr_score else "fr"
    return {"lang": lang, "en": en_score, "fr": fr_score,
            "tokens": len(tokens), "defaulted": False}


def _detect_lang(message: str) -> Literal["fr", "en"]:
    """Détecte la langue du message : 'fr' ou 'en'.

    Heuristique déterministe : on compte les mots-outils anglais puis français
    (scores indépendants, un mot ne vote que pour sa langue). Le score le plus
    élevé gagne ; égalité ou message vide (ou sans mot-outil) → 'fr' par défaut.
    Les langues locales (douala, etc.) ne sont PAS détectées par mots : elles
    arrivent via le contexte école (transcription STT) et restent acceptées en
    entrée — le prompt demande alors une réponse en français simple.
    """
    return detect_lang_details(message)["lang"]


def _normalize_lang(value: Any) -> Literal["fr", "en"] | None:
    """Normalise un code langue explicite ('en', 'en-US', 'fr_FR'...)."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("_", "-")
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("fr"):
        return "fr"
    return None


def _resolve_lang(req: AgentChatRequest) -> Literal["fr", "en"]:
    """Langue de réponse : langue explicite (requête/contexte) puis détection."""
    for candidate in (getattr(req, "language", None), getattr(req, "lang", None)):
        lang = _normalize_lang(candidate)
        if lang is not None:
            return lang
    try:
        context = req.context.model_dump()
    except (AttributeError, ValueError):
        context = {}
    if isinstance(context, dict):
        for key in ("language", "lang", "locale"):
            lang = _normalize_lang(context.get(key))
            if lang is not None:
                return lang
    return _detect_lang(req.message)


def _build_system_prompt(lang: str) -> str:
    """Prompt système + langue de réponse explicite transmise au provider (en tête : primauté)."""
    head = "REPLY ONLY IN ENGLISH. Never use French." if lang == "en" else "Réponds en français."
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        f"{head}\n{SYSTEM_PROMPT}\nLangue de réponse : {lang}.\n"
        f"Aujourd'hui : {today} (date du jour — utilise-la pour 'aujourd'hui' ; "
        "'hier' = la veille, 'cette semaine' = les 7 derniers jours)."
    )


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _fmt_1(value: Any) -> str:
    try:
        return f"{float(value):.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0,0"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or singular + "s")


def _summarize_district(obs: dict[str, Any]) -> str:
    n = int(obs.get("open_incidents", 0) or 0)
    pupils = _fmt_int(obs.get("total_affected_students", 0))
    schools = obs.get("schools_involved", []) or []
    critical = int((obs.get("by_urgency", {}) or {}).get("critical", 0) or 0)
    text = (
        f"{n} {_plural(n, 'incident ouvert', 'incidents ouverts')} "
        f"{_plural(n, 'touche', 'touchent')} "
        f"{pupils} élèves dans {len(schools)} {_plural(len(schools), 'école')}"
    )
    if critical:
        text += f", dont {critical} {_plural(critical, 'critique')}"
    return text + ". Le détail est dans la carte ci-dessous."


def _summarize_trends(obs: dict[str, Any]) -> str:
    figures = obs.get("figures", {}) or {}
    trend = {"up": "en hausse", "down": "en baisse"}.get(
        str(figures.get("trend_direction", "")), "stable"
    )
    n = int(figures.get("total_incidents", 0) or 0)
    text = (
        f"À {obs.get('school_name', '?')} sur {obs.get('months', 3)} mois : "
        f"{n} {_plural(n, 'panne')}, "
        f"{_fmt_int(figures.get('total_cost', 0))} {figures.get('currency', 'XAF')} de réparations, "
        f"tendance {trend}."
    )
    try:
        disruption = int(figures.get("service_disruption_days", 0) or 0)
        logged = int(figures.get("total_days_lost", 0) or 0)
    except (TypeError, ValueError):
        disruption, logged = 0, 0
    if disruption > logged:
        text += f" Privation réelle en cours depuis {disruption} jours."
    return text + " Le graphique est dans la carte ci-dessous."


def _summarize_ranking(obs: dict[str, Any]) -> str:
    ranking = obs.get("ranking", []) or []
    if not ranking:
        return "Aucune école avec panne ouverte pour le moment."
    top = ranking[0]
    total = int(obs.get("total", len(ranking)) or 0)
    return (
        f"{total} {_plural(total, 'école a', 'écoles ont')} besoin d'aide, en tête : "
        f"{top.get('school_name', '?')} (score {_fmt_1(top.get('need_score', 0))}). "
        "Le classement complet est dans la carte ci-dessous."
    )


def _truncate_value(value: Any, depth: int = 0) -> Any:
    """Troncature générique (copie, jamais de mutation) : listes > 12 items
    et chaînes > 2000 caractères, avec note explicite. Profondeur ≤ 2."""
    if isinstance(value, str) and len(value) > OBS_STR_MAX_CHARS:
        return value[:OBS_STR_MAX_CHARS] + f"…[tronqué, {len(value)} caractères au total]"
    if isinstance(value, list) and len(value) > OBS_LIST_MAX_ITEMS:
        head = [_truncate_value(v, depth + 1) for v in value[:OBS_LIST_MAX_ITEMS]]
        return head + [f"[+{len(value) - OBS_LIST_MAX_ITEMS} autres, voir la carte]"]
    if isinstance(value, list):
        return [_truncate_value(v, depth + 1) for v in value] if depth < 2 else list(value)
    if isinstance(value, dict):
        if depth >= 2:
            return dict(value)
        return {k: _truncate_value(v, depth + 1) for k, v in value.items()}
    return value


def _scoped_history(history: Any) -> list[dict[str, str]]:
    """Historique borné : 6 derniers tours, 1200 car/tour, 4000 au total.

    Au-delà du total, on abandonne les tours les plus anciens (le message
    courant, hors historique, n'est jamais touché).
    """
    turns = [{"role": t.role, "content": t.content or ""}
             for t in (history or [])[-HISTORY_TURNS:]]
    scoped: list[dict[str, str]] = []
    for turn in turns:
        content = turn["content"]
        if len(content) > HISTORY_TURN_MAX_CHARS:
            content = content[:HISTORY_TURN_MAX_CHARS] + "…[tour tronqué]"
        scoped.append({"role": turn["role"], "content": content})
    total = sum(len(t["content"]) for t in scoped)
    while len(scoped) > 1 and total > HISTORY_MAX_CHARS:
        total -= len(scoped.pop(0)["content"])
    return scoped


def _compact_observation(name: str, obs: Any) -> Any:
    """Version allégée d'une observation pour le LLM.

    Les gros tableaux (90 jours heatmap, top écoles) vivent dans les cartes UI ;
    le modèle ne reçoit que les totaux + le jour max, sinon les petits modèles
    saturent et décrochent (réponse en anglais, mode 'description de JSON').
    L'observation complète reste dans `executed` pour _build_cards.
    """
    if not isinstance(obs, dict):
        return obs
    slim = dict(obs)
    hm = slim.get("calendar_heatmap")
    if isinstance(hm, dict):
        days = hm.get("days") or []
        hot = max(days, key=lambda d: d.get("pannes", 0) or 0, default=None) or {}
        slim["calendar_heatmap"] = {
            "total_pannes": hm.get("total_pannes"),
            "start": hm.get("start"),
            "end": hm.get("end"),
            "jour_max": hot.get("date"),
            "pannes_jour_max": hot.get("pannes", 0),
            "note": "Détail jour par jour dans la carte.",
        }
    bc = slim.get("budget_compare")
    if isinstance(bc, dict):
        top = (bc.get("ecoles") or [{}])[0] or {}
        slim["budget_compare"] = {
            "total_XAF": bc.get("total_XAF"),
            "top_ecole": top.get("nom"),
            "top_cout_XAF": top.get("cumul_reparations_XAF"),
            "note": "Détail par école dans la carte.",
        }
    # Troncature générique en dernier (copie) : les compactions spécifiques
    # ci-dessus travaillent sur les données complètes (ex. jour max réel).
    return {k: _truncate_value(v) for k, v in slim.items()}


def _summarize_analysis(obs: dict[str, Any]) -> str:
    verdict = {
        "REPLACE_EQUIPMENT": "remplacer l'équipement",
        "CONTINUE_REPAIR": "continuer les réparations",
        "MONITOR_CLOSELY": "renforcer la surveillance",
    }.get(str(obs.get("recommendation", "")), "étudier le dossier")
    n = len(obs.get("open_incidents", []) or [])
    return (
        f"À {obs.get('school_name', '?')} : {n} {_plural(n, 'panne ouverte', 'pannes ouvertes')}, "
        f"ratio réparations/neuf de {_fmt_1(obs.get('repair_ratio_percent', 0))} %. "
        f"Verdict : {verdict}. L'analyse complète est dans la carte ci-dessous."
    )


def _summarize_incident(obs: dict[str, Any]) -> str:
    ref = obs.get("reference_code") or f"#{obs.get('id', '?')}"
    return (
        f"Incident {ref} à {obs.get('school_name', '?')} : {obs.get('title', '?')} "
        f"(urgence {obs.get('urgency', '?')}, "
        f"{_fmt_int(obs.get('affected_students', 0))} élèves). "
        "Le détail est dans la carte ci-dessous."
    )


def _summarize_report(obs: dict[str, Any]) -> str:
    missing = obs.get("missing_labels", []) or []
    if missing:
        return f"Signalement incomplet : il manque {', '.join(missing)}. Précisez pour continuer."
    school = (obs.get("slots", {}) or {}).get("school_name", "?")
    return (
        f"Signalement préparé pour {school}. "
        "Vérifiez le récapitulatif et confirmez dans la carte ci-dessous."
    )


def _summarize_proposal(obs: dict[str, Any]) -> str:
    title = {"create_incident": "Intervention",
             "create_maintenance_log": "Journal d'intervention"}.get(
                 str(obs.get("action", "")), "Proposition")
    missing = obs.get("missing_labels", []) or []
    if missing:
        text = f"{title} incomplet : il manque {', '.join(missing)}. Précisez pour continuer."
        if obs.get("incident_choices"):
            text += f" Incidents possibles : {obs['incident_choices']}."
        return text
    return (
        f"{title} préparé. Vérifiez le récapitulatif et confirmez dans la carte ci-dessous."
    )


def _summarize_maintenance_logs(obs: dict[str, Any]) -> str:
    items = obs.get("items", []) or []
    date = obs.get("date", "?")
    n = int(obs.get("total", len(items)) or 0)
    if not items and n == 0:
        return f"Aucune intervention journalisée le {date}."
    names = [str(i.get("school_name", "?")) for i in items[:3]]
    suffix = f" : {', '.join(names)}" if names else ""
    return (
        f"{n} {_plural(n, 'intervention journalisée', 'interventions journalisées')} "
        f"le {date}{suffix}. Le détail est dans la carte ci-dessous."
    )


def _summarize_territory(obs: dict[str, Any]) -> str:
    total = int(obs.get("total", 0) or 0)
    n = int(obs.get("open_incidents", 0) or 0)
    missing = len(obs.get("missing_gps", []) or [])
    text = (
        f"{total} {_plural(total, 'école géolocalisée', 'écoles géolocalisées')}, "
        f"{n} {_plural(n, 'incident ouvert', 'incidents ouverts')}. "
        "La carte interactive est ci-dessous."
    )
    if missing:
        text += f" ({missing} {_plural(missing, 'école sans', 'écoles sans')} GPS.)"
    return text


FALLBACK_SUMMARIES = {
    "list_maintenance_logs": _summarize_maintenance_logs,
    "summarize_district": _summarize_district,
    "repair_trends": _summarize_trends,
    "rank_schools_by_need": _summarize_ranking,
    "analyze_school": _summarize_analysis,
    "explain_incident": _summarize_incident,
    "prepare_report": _summarize_report,
    "prepare_incident": _summarize_proposal,
    "prepare_maintenance_log": _summarize_proposal,
    "territory_overview": _summarize_territory,
    "build_briefing": lambda obs: (
        f"Briefing prêt : {int(obs.get('total', 0) or 0)} slides "
        f"({(obs.get('slides', [{}])[0].get('stats', [{}])[0].get('value', '?'))} "
        "incidents ouverts). La présentation est dans la carte ci-dessous."
    ),
}

_STARTER_RE = re.compile(
    r"\b(bonjour|salut|coucou|hello|bonsoir|aide|aider|help|démarrer|commencer|"
    r"que (peux|sais)-tu|tu sais faire)\b", re.IGNORECASE)

STARTER_CHIPS = ["Résumer mon district",
                 "Quelles écoles ont le plus besoin d'aide ?",
                 "Voir la carte du territoire"]
CATEGORY_CHIPS = ["Point d'eau", "Latrines", "Lavage des mains", "Évacuation"]
URGENCY_CHIPS = ["Basse", "Moyenne", "Haute", "Critique"]


def _follow_ups(message: str, executed: list[tuple[str, dict[str, Any]]],
                context: dict[str, Any]) -> list[str]:
    """Relances cliquables : démarrage, ou réponses rapides au premier slot manquant."""
    if not executed:
        return list(STARTER_CHIPS) if _STARTER_RE.search(message or "") else []
    name, obs = executed[-1]
    if name not in ("prepare_report", "prepare_incident", "prepare_maintenance_log"):
        return []
    if obs.get("complete") or obs.get("candidates"):
        return []
    missing = obs.get("missing", []) or []
    first = missing[0] if missing else ""
    if first == "category":
        return list(CATEGORY_CHIPS)
    if first == "urgency":
        return list(URGENCY_CHIPS)
    if first == "school":
        names = [s.get("school_name") for s in context.get("schools", [])[:3]]
        return [n for n in names if n]
    return []


# ---------------------------------------------------------------------------
# Réparations heuristiques déterministes (anti-hallucination petit LLM).
# Le petit modèle (Qwen 3B) produit parfois en synthèse : des puces de liste
# vides ("* * *"), des placeholders entre crochets ("[Carte interactive...]")
# ou des annonces de carte sans carte construite. Les fonctions ci-dessous
# sont pures et testables : elles corrigent la réponse finale AVANT envoi,
# uniquement à partir des observations d'outils (jamais d'invention).
# ---------------------------------------------------------------------------

#: Puce en début de ligne : "-", "*", "•" ou "1."/"1)".
_LINE_BULLET_RE = re.compile(
    r"^(?P<indent>\s*)(?P<marker>(?:[-*•]|\d{1,3}[.)]))(?P<content>.*)$"
)

#: Marqueur de puce isolé dans une ligne (cas réel : "sont : * * * Ces...").
#: Tiret exclu : "X - Y" est une ponctuation légitime, pas une puce vide.
_INLINE_BULLET_RE = re.compile(r"(?<![\w*•])(?P<marker>[*•])(?![\w*•])")

#: Placeholder entre crochets à supprimer : [carte...], [map...], [graphique...],
#: [chart...], [voir...], [image...], [figure...]. Les notes de troncature
#: ("[tronqué...]", "[+N autres...]") sont préservées (garde dans le code).
_BRACKET_PLACEHOLDER_RE = re.compile(
    r"\[[^\[\]\n]{0,120}?(?:carte|carte interactive|map|graphique|chart|graph|"
    r"voir\s|image|figure)[^\[\]\n]{0,120}?\](?:\([^)\n]*\))?",
    re.IGNORECASE,
)

#: Annonce d'une carte dans le texte (FR + EN).
_MAP_ANNOUNCE_RE = re.compile(
    r"voici la carte|carte interactive|carte (?:est |ci-dessous|du territoire)|"
    r"interactive map|here (?:is|are) the map|map below",
    re.IGNORECASE,
)

#: Clés d'observations contenant des listes d'écoles/incidents.
_REPAIR_LIST_KEYS = (
    "schools_involved", "ranking", "schools", "items", "incidents",
    "open_incidents", "candidates",
)


def _useful_chars(text: str) -> int:
    """Nombre de caractères alphanumériques (markdown ignoré)."""
    return sum(1 for c in text if c.isalnum())


def _entry_label(entry: Any) -> str | None:
    """Libellé citable d'une entrée d'observation (fonction pure)."""
    if isinstance(entry, str):
        label = entry.strip()
        return label or None
    if not isinstance(entry, dict):
        return None
    school = str(entry.get("school_name") or entry.get("nom") or "").strip()
    title = str(entry.get("title") or "").strip()
    ref = str(entry.get("reference_code") or entry.get("reference") or "").strip()
    if school and title and title.lower() not in school.lower():
        return f"{school} — {title}"
    return school or title or ref or None


def collect_repair_names(executed: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Noms réellement observés (écoles/incidents/références), sans doublon.

    Ordre préservé : dernière observation d'abord (la plus pertinente),
    puis les précédentes. Fonction pure.
    """
    names: list[str] = []
    seen: set[str] = set()
    for _name, obs in reversed(executed or []):
        if not isinstance(obs, dict) or "error" in obs:
            continue
        candidates: list[Any] = [
            obs.get("school_name"), obs.get("title"), obs.get("reference_code"),
        ]
        for key in _REPAIR_LIST_KEYS:
            values = obs.get(key)
            if isinstance(values, list):
                candidates.extend(values)
        for candidate in candidates:
            label = _entry_label(candidate)
            if label and label not in ("?", "-") and _norm(label) not in seen:
                seen.add(_norm(label))
                names.append(label)
    return names


def strip_bracket_placeholders(text: str) -> str:
    """Supprime les placeholders entre crochets ([Carte...], [graphique...]).

    Les notes de troncature déterministes ([tronqué...], "[+N autres...]")
    sont préservées. Fonction pure.
    """
    if not text or "[" not in text:
        return text

    def _drop(match: re.Match[str]) -> str:
        raw = match.group(0)
        lowered = raw.lower()
        if "tronqu" in lowered or raw.startswith("[+"):
            return raw
        return ""

    stripped = _BRACKET_PLACEHOLDER_RE.sub(_drop, text)
    if stripped == text:
        return text
    cleaned = re.sub(r"[ \t]{2,}", " ", stripped)
    lines = [line for line in cleaned.split("\n") if line.strip()]
    return "\n".join(lines)


def repair_empty_bullets(text: str, names: list[str]) -> str:
    """Remplit les puces vides depuis `names`, ou les supprime sans données.

    Vide = sans contenu ou contenu < 3 caractères alphanumériques.
    Couvre les puces en début de ligne ("-", "*", "•", "1.") et les marqueurs
    isolés dans une ligne ("sont : * * * Ces..."). Fonction pure.
    """
    if not text:
        return text
    pool = [str(n).strip() for n in (names or []) if str(n).strip()]
    idx = 0

    lines = text.split("\n")
    kept: list[str] = []
    for line in lines:
        match = _LINE_BULLET_RE.match(line)
        if match and _useful_chars(match.group("content")) < 3:
            if idx < len(pool):
                kept.append(f"{match.group('indent')}{match.group('marker')} {pool[idx]}")
                idx += 1
            # Sinon : puce supprimée (aucune donnée pour la remplir).
        else:
            kept.append(line)
    text = "\n".join(kept)

    # Marqueurs isolés dans une ligne : regroupés par plages (séparés par de
    # simples espaces), en ignorant les multiplications ("2 * 3").
    matches = list(_INLINE_BULLET_RE.finditer(text))
    if not matches:
        return text
    groups: list[list[re.Match[str]]] = []
    for match in matches:
        if groups and text[groups[-1][-1].end():match.start()].strip() == "":
            groups[-1].append(match)
        else:
            groups.append([match])

    def _neighbors_are_alnum(start: int, end: int) -> bool:
        before = text[:start].rstrip()[-1:] or ""
        after = text[end:].lstrip()[:1] or ""
        return bool(before and after and before.isalnum() and after.isalnum())

    for group in reversed(groups):
        start, end = group[0].start(), group[-1].end()
        if _neighbors_are_alnum(start, end):
            continue
        available = len(pool) - idx
        if available <= 0:
            text = text[:start] + text[end:]
            continue
        take = min(len(group), available)
        fill = ", ".join(pool[idx:idx + take])
        idx += take
        after = text[end:].lstrip()[:1] or ""
        if after and after.isupper() and not fill.endswith((".", "!", "?", ";", ":")):
            fill += "."
        text = text[:start] + fill + text[end:]
    return re.sub(r"[ \t]{2,}", " ", text)


def repair_final_answer(
    answer: str,
    executed: list[tuple[str, dict[str, Any]]] | None = None,
) -> str:
    """Passe de réparation déterministe sur la réponse finale (fonction pure).

    Placeholders entre crochets supprimés, puces vides remplies depuis les
    observations (ou supprimées sans données). Réponse saine inchangée.
    """
    if not answer or not answer.strip():
        return answer
    text = strip_bracket_placeholders(answer)
    names = collect_repair_names(executed or [])
    lowered = _norm(text)
    fresh = [n for n in names if _norm(n) not in lowered]
    return repair_empty_bullets(text, fresh or names)


def announces_map(text: str) -> bool:
    """Le texte annonce-t-il une carte (FR/EN) ? Fonction pure."""
    return bool(text and _MAP_ANNOUNCE_RE.search(text))


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def collect_map_points(
    executed: list[tuple[str, dict[str, Any]]] | None,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Écoles géolocalisées (lat/lng) issues des observations (fonction pure).

    1. Points directs : toute entrée d'observation avec nom + lat/lng.
    2. Enrichissement : noms observés retrouvés dans `context["schools"]`
       avec GPS (cas summarize_district/rank, sans lat/lng dans l'obs).
    """
    points: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, lat: Any, lng: Any, extra: dict[str, Any]) -> None:
        flat_lat, flat_lng = _as_float(lat), _as_float(lng)
        key = _norm(name)
        if flat_lat is None or flat_lng is None or not key or key in seen:
            return
        seen.add(key)
        points.append({
            "school_id": extra.get("school_id"),
            "school_name": name,
            "district": extra.get("district"),
            "lat": flat_lat,
            "lng": flat_lng,
            "open_incidents": int(extra.get("open_incidents", 0) or 0),
            "affected_students": int(extra.get("affected_students", 0) or 0),
            "top_urgency": extra.get("top_urgency"),
        })

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            name = value.get("school_name") or value.get("nom")
            if name:
                _add(str(name), value.get("lat", value.get("latitude")),
                     value.get("lng", value.get("longitude")), value)
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for child in value:
                _walk(child)

    for _name, obs in executed or []:
        if isinstance(obs, dict) and "error" not in obs:
            _walk(obs)

    schools = (context or {}).get("schools") or []
    gps_by_name = {}
    for school in schools:
        if not isinstance(school, dict) or not school.get("school_name"):
            continue
        gps_by_name[_norm(str(school["school_name"]))] = school
    for label in collect_repair_names(executed or []):
        school = gps_by_name.get(_norm(label))
        if school is not None:
            _add(str(school["school_name"]),
                 school.get("lat", school.get("latitude")),
                 school.get("lng", school.get("longitude")), school)
    return points


def build_forced_map_card(
    points: list[dict[str, Any]],
    district: str | None = None,
) -> AgentCard:
    """Carte territory_map de secours (même forme que territory_overview)."""
    if district is None:
        districts = [str(p.get("district")) for p in points if p.get("district")]
        district = max(set(districts), key=districts.count) if districts else None
    total_open = sum(int(p.get("open_incidents", 0) or 0) for p in points)
    return AgentCard(
        type="territory_map",
        title=f"Carte du territoire{f' — {district}' if district else ''}",
        data={
            "district": district,
            "schools": points,
            "missing_gps": [],
            "total": len(points),
            "open_incidents": total_open,
            "insight": f"{len(points)} écoles géolocalisées.",
        },
    )


def maybe_force_map_card(
    answer: str,
    executed: list[tuple[str, dict[str, Any]]] | None,
    cards: list[AgentCard] | None,
    context: dict[str, Any] | None = None,
) -> list[AgentCard]:
    """Force la carte si le texte l'annonce sans qu'elle soit construite.

    Seulement quand des écoles avec lat/lng existent (observations, puis
    contexte). N'ajoute jamais de doublon. Fonction pure (nouvelle liste).
    """
    cards = list(cards or [])
    if not announces_map(answer):
        return cards
    if any("map" in (card.type or "") for card in cards):
        return cards
    points = collect_map_points(executed, context)
    if not points:
        return cards
    cards.append(build_forced_map_card(points))
    return cards


#: Marqueur d'injection du résumé photo dans le message user (le LLM
#: commente l'analyse, il ne devine rien).
PHOTO_CONTEXT_PREFIX = (
    "[Photo jointe — analyse automatique, commente-la sans rien inventer : "
)


def summarize_photo_analysis(photo: ImageAnalysisResponse) -> str:
    """Résumé FR déterministe d'une analyse photo (fonction pure).

    Injecté dans le contexte de conclusion : le LLM commente ce résumé
    (et voit la photo au premier tour) au lieu de deviner. Vision en
    panne -> consigne explicite de ne pas décrire la photo.
    """
    if is_vision_unavailable(photo):
        reason = photo.vision_error or "raison inconnue"
        return (
            f"Photo fournie mais analyse vision indisponible ({reason}). "
            "Ne décris pas la photo, propose de renvoyer une photo nette."
        )
    if not photo.is_wash_related:
        return (
            "La photo fournie ne montre pas d'infrastructure WASH "
            "(hors sujet, sévérité 0/100). Signale-le poliment, "
            "sans décrire de panne."
        )
    try:
        severity = int(round(float(photo.visual_severity_score)))
    except (TypeError, ValueError):
        severity = 0
    severity = max(0, min(100, severity))
    hazard = "oui" if photo.health_hazard_detected else "non"
    return (
        f"Photo analysée : {photo.infrastructure_detected} — "
        f"{photo.visible_damage} "
        f"Sévérité visuelle : {severity}/100. "
        f"Danger sanitaire visible : {hazard}. "
        f"Note technicien : {photo.technician_notes}"
    )


class AgentLoop:
    """Boucle agentique réelle : le LLM choisit ses outils, Python les exécute."""

    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def chat(self, req: AgentChatRequest) -> AgentChatResponse:
        context = req.context.model_dump()
        # CANAL 3 : dialogue guidé vocal (opt-in). Hors signalement, guided_turn
        # retourne None et le flux normal ci-dessous est strictement inchangé.
        if getattr(req, "guided", False):
            turn = guided_turn(
                req.message, req.history, context, resolve_guided_lang(req))
            if turn is not None and turn.get("status") == "ask":
                return AgentChatResponse(
                    answer=turn["question"],
                    tools_executed=[],
                    cards=[],
                    model_used=self.llm.model,
                    follow_ups=turn.get("chips", []),
                )
            if turn is not None and turn.get("status") == "confirmed":
                # Bascule sur le flux normal avec le signalement reconstitué.
                req = req.model_copy(update={"message": turn["report_text"]})
        # VISION : photo jointe -> analyse (ImageAnalyzer, sans duplication)
        # + résumé déterministe injecté en contexte. Sans image, photo vaut
        # None et tout le flux ci-dessous est strictement inchangé.
        photo: ImageAnalysisResponse | None = None
        photo_summary = ""
        photo_send: str | None = None
        photo_b64 = (req.image_base64 or "").strip() or None
        if photo_b64 is not None:
            photo_mime = req.image_mime or CHAT_IMAGE_DEFAULT_MIME
            photo = await ImageAnalyzer(self.llm).analyze_base64(photo_b64, photo_mime)
            photo_summary = summarize_photo_analysis(photo)
            try:
                photo_send = (
                    base64.b64encode(decode_chat_image(photo_b64)).decode("ascii")
                    or None
                )
            except ValueError:
                photo_send = None
        else:
            photo_mime = CHAT_IMAGE_DEFAULT_MIME
        lang = _resolve_lang(req)
        intent = route_intent(req.message)
        active_tools = compact_tools(tools_for_intent(intent), self.llm.model)
        messages: list[dict[str, Any]] = [{"role": "system", "content": _build_system_prompt(lang)}]
        messages.extend(_scoped_history(req.history))
        user_content = req.message
        if req.history and intent == "other":
            user_content += followup_hint(req.message, context)
        if photo_summary:
            user_content += f"\n\n{PHOTO_CONTEXT_PREFIX}{photo_summary}]"
        messages.append({"role": "user", "content": user_content})

        started = time.monotonic()
        executed: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        nudged = False
        answer = ""
        used_iterations = 0
        budget = {"llm_calls": 0}
        vision_sent = False
        for _ in range(MAX_ITERATIONS):
            if time.monotonic() - started > RUN_BUDGET_S:
                break
            if budget["llm_calls"] >= MAX_LLM_CALLS:
                break
            used_iterations += 1
            budget["llm_calls"] += 1
            if photo_send is not None and not vision_sent:
                vision_sent = True
                reply = await self._vision_first_turn(
                    messages, active_tools, photo_send, photo_mime)
            else:
                reply = await self.llm.chat(messages, active_tools)
            messages.append(reply["raw"])
            calls = reply.get("tool_calls", [])
            if not calls:
                answer = reply.get("content", "")
                break
            fresh = False
            for call in calls:
                name = call.get("name", "")
                arguments = call.get("arguments", {}) or {}
                key = (name, json.dumps(arguments, sort_keys=True, default=str))
                if key in seen:
                    messages.append(self.llm.format_tool_result(name, {"note": REPEAT_NUDGE}, call.get("id")))
                    continue
                seen.add(key)
                fresh = True
                observation = self._execute_tool(name, arguments, context)
                executed.append((name, observation))
                messages.append(self.llm.format_tool_result(name, _compact_observation(name, observation), call.get("id")))
            if not fresh:
                if nudged:
                    break
                nudged = True
        else:
            answer = self._fallback_answer(executed, context, photo)

        over_budget = time.monotonic() - started > RUN_BUDGET_S
        if (not executed and answer.strip()
                and self._looks_like_data_question(req.message)
                and not over_budget):
            answer = await self._force_tool_pass(
                messages, context, executed, active_tools, budget, photo=photo)

        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            answer = self._fallback_answer(executed, context, photo)

        if answer.strip() and _claims_absence(answer) and not _has_read_tool(executed):
            if not over_budget and used_iterations < MAX_ITERATIONS:
                answer = await self._absence_correction_pass(
                    messages, context, executed, seen, active_tools, budget,
                    photo=photo)
            else:
                answer = UNVERIFIED_HONEST_ANSWER

        if (answer.strip() and _cites_reference(answer) and _claims_absence(answer)
                and _has_empty_list_obs(executed)):
            if not over_budget and used_iterations < MAX_ITERATIONS:
                answer = await self._absence_correction_pass(
                    messages, context, executed, seen, active_tools, budget,
                    nudge=CONTRADICTION_CORRECTION_NUDGE, photo=photo)
            else:
                answer = self._fallback_answer(executed, context, photo)

        # Réparation déterministe AVANT envoi : puces vides remplies depuis
        # les observations, placeholders [...] supprimés (fonctions pures).
        answer = repair_final_answer(answer, executed)
        cards = self._build_cards(executed, context, photo=photo)
        # Annonce-carte sans carte construite : force la carte si des écoles
        # avec lat/lng existent (petit LLM : CAS "voici la carte..." seul).
        cards = maybe_force_map_card(answer, executed, cards, context)
        if not cards:
            # Aucune carte (échec ou lieu inconnu) : suggestions cliquables.
            suggest = suggest_places(req.message, context)
            if suggest.get("suggestions") or (
                    suggest.get("fragment") and suggest.get("from_marker")):
                cards.append(AgentCard(
                    type="place_suggestions",
                    title="Quel lieu vouliez-vous dire ?",
                    data=suggest,
                ))
        return AgentChatResponse(
            answer=answer.strip(),
            tools_executed=[name for name, _ in executed],
            cards=cards,
            model_used=self.llm.model,
            follow_ups=_follow_ups(req.message, executed, context),
        )

    def _execute_tool(self, name: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        executor = TOOL_EXECUTORS.get(name)
        if executor is None:
            return {"error": f"Outil inconnu : {name}."}
        try:
            return executor(arguments, context)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    async def _vision_first_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        image_base64: str,
        image_mime: str,
    ) -> dict[str, Any]:
        """Premier tour avec photo : le LLM voit l'image si possible.

        Provider sans support (méthode absente, NotImplementedError) ou
        appel vision en échec -> repli texte immédiat sur le même contexte
        (qui contient déjà le résumé déterministe) : jamais de crash.
        """
        chat_with_image = getattr(self.llm, "chat_with_image", None)
        if chat_with_image is None:
            return await self.llm.chat(messages, tools)
        try:
            return await chat_with_image(messages, image_base64, image_mime, tools)
        except Exception as exc:
            print(f"[agent] chat vision indisponible ({type(exc).__name__}), repli texte.")
            return await self.llm.chat(messages, tools)

    @staticmethod
    def _looks_like_data_question(message: str) -> bool:
        """Heuristique large : en cas de doute on exige un outil.

        Les salutations, remerciements et confirmations (« oui », « merci »)
        ne correspondent à aucun indice et passent sans recadrage.
        Score calibré du routeur (intent list/create ou vocabulaire données).
        """
        return is_data_question(message or "", PLUGIN_HINTS)

    async def _force_tool_pass(
        self,
        messages: list[dict[str, Any]],
        context: dict[str, Any],
        executed: list[tuple[str, dict[str, Any]]],
        tools: list[dict[str, Any]] | None = None,
        budget: dict[str, int] | None = None,
        photo: ImageAnalysisResponse | None = None,
    ) -> str:
        """Dernier recadrage : réponse directe à une question de données.

        On exige un appel d'outil immédiat. S'il obéit, on le laisse conclure
        sur les observations ; sinon, réponse honnête (jamais d'invention).
        Chaque appel LLM consomme le budget partagé (MAX_LLM_CALLS).
        """
        tools = AGENT_TOOLS if tools is None else tools
        budget = {"llm_calls": 0} if budget is None else budget
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo)
        messages.append({"role": "user", "content": NO_TOOL_NUDGE})
        budget["llm_calls"] += 1
        retry = await self.llm.chat(messages, tools)
        messages.append(retry["raw"])
        for call in retry.get("tool_calls", []):
            name = call.get("name", "")
            arguments = call.get("arguments", {}) or {}
            observation = self._execute_tool(name, arguments, context)
            executed.append((name, observation))
            messages.append(self.llm.format_tool_result(name, _compact_observation(name, observation), call.get("id")))
        if not executed:
            return self._fallback_answer(executed, context, photo)
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo)
        budget["llm_calls"] += 1
        final = await self.llm.chat(messages, tools)
        messages.append(final["raw"])
        answer = final.get("content", "")
        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            return self._fallback_answer(executed, context, photo)
        return answer

    async def _absence_correction_pass(
        self,
        messages: list[dict[str, Any]],
        context: dict[str, Any],
        executed: list[tuple[str, dict[str, Any]]],
        seen: set[tuple[str, str]],
        tools: list[dict[str, Any]],
        budget: dict[str, int] | None = None,
        nudge: str = ABSENCE_CORRECTION_NUDGE,
        photo: ImageAnalysisResponse | None = None,
    ) -> str:
        """Recadrage anti-hallucination : absence affirmée sans lecture
        (ou contradiction référence + absence, via un nudge adapté).

        Une seule tentative (bornée par MAX_ITERATIONS à l'appel) : on exige un
        outil de lecture puis on conclut ; si le modèle persiste sans observer,
        réponse honnête (jamais d'invention).
        Chaque appel LLM consomme le budget partagé (MAX_LLM_CALLS).
        """
        budget = {"llm_calls": 0} if budget is None else budget
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo)
        messages.append({"role": "user", "content": nudge})
        budget["llm_calls"] += 1
        retry = await self.llm.chat(messages, tools)
        messages.append(retry["raw"])
        for call in retry.get("tool_calls", []):
            name = call.get("name", "")
            arguments = call.get("arguments", {}) or {}
            key = (name, json.dumps(arguments, sort_keys=True, default=str))
            if key in seen:
                messages.append(self.llm.format_tool_result(
                    name, {"note": REPEAT_NUDGE}, call.get("id")))
                continue
            seen.add(key)
            observation = self._execute_tool(name, arguments, context)
            executed.append((name, observation))
            messages.append(self.llm.format_tool_result(name, _compact_observation(name, observation), call.get("id")))
        if not _has_read_tool(executed):
            return UNVERIFIED_HONEST_ANSWER
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo)
        budget["llm_calls"] += 1
        final = await self.llm.chat(messages, tools)
        messages.append(final["raw"])
        answer = final.get("content", "")
        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            return self._fallback_answer(executed, context, photo)
        return answer

    def _is_bogus_refusal(self, answer: str, executed: list[tuple[str, dict[str, Any]]]) -> bool:
        """Un refus poli alors qu'un outil a réussi = bug du petit modèle.

        On le remplace par le résumé déterministe. Un refus sans donnée
        réussie (hors sujet, école introuvable) est conservé tel quel.
        """
        lowered = answer.lower()
        if not any(p in lowered for p in REFUSAL_PATTERNS):
            return False
        return any("error" not in observation for _, observation in executed)

    def _fallback_answer(
        self,
        executed: list[tuple[str, dict[str, Any]]],
        context: dict[str, Any] | None = None,
        photo: ImageAnalysisResponse | None = None,
    ) -> str:
        """Résumé humain déterministe quand le modèle ne conclut pas.

        Prend la dernière observation réussie et la raconte en une phrase
        chiffrée qui pointe vers la carte (pas de jargon robotique).
        Sans observation d'outil mais avec photo : le résumé photo
        déterministe (le LLM commente, ne devine pas — y compris ici).
        """
        for name, observation in reversed(executed):
            if "error" in observation:
                continue
            summarizer = FALLBACK_SUMMARIES.get(name)
            if summarizer:
                try:
                    return summarizer(observation)
                except (TypeError, ValueError, KeyError, IndexError, AttributeError):
                    continue
            return (
                "Bonne nouvelle, j'ai trouvé vos données : le détail (chiffres "
                "clés, écoles et incidents concernés) est dans la carte juste "
                "en dessous. S'il vous manque un détail, dites-moi quelle école "
                "ou quel district vous intéresse, par exemple : « Résumez le "
                "district de Wouri ». Demandez par exemple : « Quelles écoles "
                "ont le plus besoin d'aide ? » ou « Montrez la carte du "
                "territoire »."
            )
        if photo is not None:
            return (
                f"{summarize_photo_analysis(photo)} "
                "Le détail est dans la carte ci-dessous."
            )
        districts = known_places(context or {})[1] if context else []
        if districts:
            examples = ", ".join(districts[:4])
            return (
                "Je n'ai pas pu récupérer de données pour cette question, car il "
                "me manque le nom de l'école ou du district qui vous intéresse. "
                f"Je connais par exemple : {examples}. "
                "Par exemple, demandez-moi : « Résumez mon district ». Demandez "
                "par exemple : « Quelles écoles ont le plus besoin d'aide ? » "
                "ou « Montrez la carte du territoire »."
            )
        return (
            "Je n'ai pas pu récupérer de données pour cette question, car il me "
            "manque le nom de l'école ou du district qui vous intéresse. "
            "Dites-moi par exemple : « Résumez le district de Wouri ». Demandez "
            "par exemple : « Quelles écoles ont le plus besoin d'aide ? » "
            "ou « Montrez la carte du territoire », et je m'en occupe avec plaisir."
        )

    def _build_cards(self, executed: list[tuple[str, dict[str, Any]]],
                     context: dict[str, Any] | None = None,
                     photo: ImageAnalysisResponse | dict[str, Any] | None = None,
                     ) -> list[AgentCard]:
        cards: list[AgentCard] = []
        if photo is not None:
            obs = photo.model_dump() if hasattr(photo, "model_dump") else dict(photo)
            if obs.get("vision_unavailable"):
                title = "Analyse photo — vision indisponible"
            else:
                title = f"Analyse photo — {obs.get('infrastructure_detected', '?')}"
            cards.append(AgentCard(
                type="photo_analysis",
                title=title,
                data=obs,
            ))
        district_examples: str | None = None
        if context:
            try:
                districts = known_places(context)[1]
            except (AttributeError, TypeError, ValueError):
                districts = []
            if districts:
                district_examples = ", ".join(districts[:4])
        for name, observation in executed:
            if "error" in observation:
                guide = build_guidance_card(
                    name, observation, district_examples=district_examples)
                if guide is not None:
                    cards.append(guide)
                continue
            if name == "analyze_school":
                cards.append(AgentCard(
                    type="school_analysis",
                    title=f"Analyse — {observation.get('school_name', '?')}",
                    data=observation,
                ))
            elif name == "rank_schools_by_need":
                cards.append(AgentCard(
                    type="school_ranking",
                    title="Classement des écoles par besoin",
                    data=observation,
                ))
            elif name == "summarize_district":
                cards.append(AgentCard(
                    type="district_summary",
                    title="Synthèse du district",
                    data=observation,
                ))
            elif name == "explain_incident":
                cards.append(AgentCard(
                    type="incident_detail",
                    title=f"Incident {observation.get('reference_code') or observation.get('id', '?')}",
                    data=observation,
                ))
                if observation.get("timeline"):
                    cards.append(AgentCard(
                        type="incident_timeline",
                        title=f"Suivi — {observation.get('reference_code') or observation.get('id', '?')}",
                        data={"timeline": observation["timeline"],
                              "incident_id": observation.get("id"),
                              "reference_code": observation.get("reference_code"),
                              "status": observation.get("status")},
                    ))
            elif name in ("prepare_report", "prepare_incident", "prepare_maintenance_log"):
                if observation.get("candidates"):
                    cards.append(AgentCard(
                        type="incident_picker",
                        title="Quel incident ?",
                        data={"candidates": observation["candidates"],
                              "hint": observation.get("hint_unmatched"),
                              "action": observation.get("action")},
                    ))
                    continue
                if not observation.get("complete"):
                    continue
                titles = {"prepare_report": "Confirmer le signalement",
                          "prepare_incident": "Confirmer l'intervention",
                          "prepare_maintenance_log": "Confirmer le journal"}
                cards.append(AgentCard(
                    type="action_confirmation",
                    title=titles[name],
                    data=observation,
                ))
            elif name == "build_briefing":
                district = observation.get("district")
                cards.append(AgentCard(
                    type="briefing_deck",
                    title=f"Briefing{f' — {district}' if district else ''}",
                    data=observation,
                ))
            elif name == "territory_overview":
                district = observation.get("district")
                cards.append(AgentCard(
                    type="territory_map",
                    title=f"Carte du territoire{f' — {district}' if district else ''}",
                    data=observation,
                ))
            elif name == "repair_trends":
                cards.append(AgentCard(
                    type="trend_chart",
                    title=f"Tendances — {observation.get('school_name', '?')} ({observation.get('months', 3)} mois)",
                    data=observation,
                ))
                if observation.get("calendar_heatmap"):
                    cards.append(AgentCard(
                        type="calendar_heatmap",
                        title=f"Calendrier des pannes — {observation.get('school_name', '?')}",
                        data=observation["calendar_heatmap"],
                    ))
                if observation.get("budget_compare"):
                    cards.append(AgentCard(
                        type="budget_compare",
                        title="Comparaison des budgets réparations",
                        data=observation["budget_compare"],
                    ))
            elif name == "list_maintenance_logs":
                cards.append(AgentCard(
                    type="maintenance_logs",
                    title=f"Interventions journalisées — {observation.get('date', '?')}",
                    data=observation,
                ))
            elif name in PLUGIN_CARDS:
                for builder in PLUGIN_CARDS[name].values():
                    card = builder(observation)
                    if card is not None:
                        cards.append(card)
        unique: list[AgentCard] = []
        fingerprints: set[str] = set()
        for card in cards:
            fingerprint = f"{card.type}|{card.title}|{json.dumps(card.data, sort_keys=True, default=str)}"
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(card)
        return unique
