from __future__ import annotations

import base64
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from .agent_tools import (
    AGENT_TOOLS,
    PLUGIN_CARDS,
    PLUGIN_HINTS,
    PLUGIN_READ_ONLY,
    TOOL_EXECUTORS,
    open_incidents_in_scope,
    open_incidents_in_window,
    scope_context_to_window,
)
from .guidance import (
    build_guidance_card,
    clarify_choices,
    clarify_question,
    short_school_name,
)
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
from .router import detect_scope_signals, is_data_question
from .router import route as router_route
from .schemas import (
    CHAT_IMAGE_DEFAULT_MIME,
    AgentCard,
    AgentChatRequest,
    AgentChatResponse,
    ImageAnalysisResponse,
    RepairPlanRequest,
)
from .tool_consts import TIME_WINDOW_LAST_7D_DAYS, TIME_WINDOW_LAST_30D_DAYS

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
#: Tours d'historique remontés pour hériter le sujet d'un rapport en suivi.
#: Override ENV : AGENT_REPORT_FOLLOWUP_TURNS (défaut 4).
REPORT_FOLLOWUP_TURNS = _env_int("AGENT_REPORT_FOLLOWUP_TURNS", 4)
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
    "explain_incident, territory_overview, build_briefing, list_maintenance_logs, "
    "list_incidents"
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


def tools_for_intent(intent: str, scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Jeu d'outils exposé : en consultation, les prepare_* (création) sont masqués.

    Périmètre école unique : les outils district/territoire/comparaison sont
    aussi masqués (le garde-fou d'exécution _blocked_by_scope reste premier).
    Périmètre photo : aucun outil exposé (commentaire de la photo seule).
    scope=None (ou périmètre large) = comportement historique.
    """
    if _is_photo_scope(scope):
        return []
    if intent == "list":
        tools = [t for t in AGENT_TOOLS
                 if not t.get("function", {}).get("name", "").startswith("prepare_")]
    else:
        tools = list(AGENT_TOOLS)
    if _single_school_scope(scope) is not None:
        tools = [t for t in tools
                 if t.get("function", {}).get("name", "") not in DISTRICT_SCOPE_TOOLS
                 or t.get("function", {}).get("name", "") in SCHOOL_TOPIC_TOOLS]
    return tools


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


# ---------------------------------------------------------------------------
# Discipline de périmètre : une école demandée = UNIQUEMENT cette école.
# Quand detect_scope() restreint à une seule école (sans demande explicite
# d'élargissement), la boucle : n'exécute aucun outil district/territoire,
# n'émet que les cartes de cette école, et purge les phrases citant une
# autre école connue. Périmètre district/territoire ou comparaison explicite
# (plusieurs écoles nommées) : comportement historique inchangé.
# ---------------------------------------------------------------------------

#: Mots génériques (normalisés, cf. _norm) qui ne désignent aucune école en
#: particulier : exclus de la multi-détection (« l'école Ngok » = Ngok seule).
_GENERIC_PLACE_TOKENS = frozenset({
    "ecole", "ecoles", "lycee", "lycees", "college", "colleges",
})

#: Outils couvrant d'autres écoles (district/territoire/comparaison globale) :
#: jamais exécutés en périmètre école unique (sauf élargissement explicite,
#: qui a déjà élargi le périmètre via detect_scope).
DISTRICT_SCOPE_TOOLS = frozenset({
    "summarize_district",
    "district_alerts",
    "epidemic_alerts",
    "territory_overview",
    "observatoire",
    "rank_schools_by_need",
    "build_briefing",
    "relances_proactives",
    "document_briefing",
    "compare_schools",
})

#: Outils district/territoire capables d'un sujet école (topic ciblé) :
#: visibles en périmètre école unique, le garde-fou exige alors un topic
#: désignant l'école (build_briefing, sans paramètre école, reste masqué).
SCHOOL_TOPIC_TOOLS = frozenset({
    "document_briefing",
})


def _mask_word(text: str, word: str) -> str:
    """Masque un mot (entier, insensible à la casse) par un espace."""
    return re.sub(r"(?i)\b\w*" + re.escape(word) + r"\w*\b", " ", text)


def mentioned_places(message: str, context: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """(écoles, districts) connus cités dans le message (fonction pure).

    Même moteur que resolve_place (répété avec masquage des lieux déjà
    trouvés) : pas de second parseur, même source known_places. Les mots
    génériques (« école », « lycée »...) sont masqués d'abord car ils ne
    désignent aucune école. Ordre de première mention, sans doublon.
    """
    ctx = context or {}
    schools, districts = known_places(ctx)
    if not message or (not schools and not districts):
        return [], []
    work = "".join(
        c for c in unicodedata.normalize("NFKD", message).encode("ascii", "ignore").decode())
    for generic in _GENERIC_PLACE_TOKENS:
        work = _mask_word(work, generic)
    found_schools: list[str] = []
    found_districts: list[str] = []
    for _ in range(len(schools) + len(districts) + 2):
        place = resolve_place(work, ctx)
        if place is None:
            break
        kind, label = place
        if kind == "school":
            if label not in found_schools:
                found_schools.append(label)
            for token in _norm(label).split():
                if len(token) >= 4 and token not in _GENERIC_PLACE_TOKENS:
                    work = _mask_word(work, token)
        else:
            if label not in found_districts:
                found_districts.append(label)
            work = _mask_word(work, _norm(label))
            for token in _norm(label).split():
                if len(token) >= 4:
                    work = _mask_word(work, token)
    lowered = _norm(message)

    def _first_pos(label: str) -> int:
        positions = [lowered.find(token) for token in _norm(label).split()
                     if len(token) >= 4 and token not in _GENERIC_PLACE_TOKENS]
        positions = [p for p in positions if p >= 0]
        full = lowered.find(_norm(label))
        if full >= 0:
            positions.append(full)
        return min(positions) if positions else len(lowered)

    found_schools.sort(key=_first_pos)
    found_districts.sort(key=_first_pos)
    return found_schools, found_districts


def detect_scope(message: str, context: dict[str, Any] | None) -> dict[str, Any]:
    """Périmètre déterministe de la question (fonction pure).

    Retourne {"scope": "school"|"district"|"territory", "school": ?nom,
    "schools": [...], "district": ?nom}. Lieux via mentioned_places
    (moteur resolve_place/known_places) ; élargissement via les signaux
    explicites du routeur (compare, district, territoire, toutes/autres
    écoles). « Compare X et Y » / « X vs Y » = scope "school" multi-écoles
    explicite (liste, pas district). Sans école ni signal : "district"
    (défaut large, comportement historique).
    """
    ctx = context or {}
    signals = detect_scope_signals(message or "")
    schools, districts = mentioned_places(message or "", ctx)
    result = {
        "school": schools[0] if schools else None,
        "schools": list(schools),
        "district": districts[0] if districts else None,
    }
    if signals["territory"]:
        return {"scope": "territory", **result}
    if (signals["district"] or districts or signals["all_schools"]
            or (signals["compare"] and signals["other_school"])):
        return {"scope": "district", **result}
    if not schools:
        return {"scope": "district", **result}
    return {"scope": "school", **result}


# ---------------------------------------------------------------------------
# Périmètre PHOTO : image jointe + question portant sur l'image seule.
# « Qu'est-ce que tu vois ? » + photo (même hors sujet WASH) ne doit ni
# appeler d'outil ni émettre de carte district/territoire/alertes/synthèse :
# carte photo_analysis UNIQUEMENT, synthèse = commentaire de la photo seule.
# Question mixte explicite (« analyse cette photo et résume Mvila ») : les
# deux périmètres restent autorisés (photo + demande explicite).
# ---------------------------------------------------------------------------

#: Mots désignant la photo jointe (texte normalisé, cf. _norm).
_PHOTO_WORDS = frozenset({
    "photo", "photos", "picture", "pictures", "image", "images",
    "pic", "pics", "cliche", "cliches", "snapshot", "snapshots",
    "selfie", "selfies",
})

#: La question porte sur l'image (FR + EN, normalisé, apostrophes -> espace) :
#: vision, description, avis, analyse d'un élément désigné (« ça », « this »).
_PHOTO_ABOUT_RES = (
    re.compile(r"\bvois\b|\bvoyez\b|\bvoient\b|\bvoir\b|do you see|can you see"),
    re.compile(r"\bqu ?est ce\b|\bc ?est quoi\b"
               r"|\bwhat ?s (this|that|these|those|it|here)\b"
               r"|\bwhat is (this|that|these|those|it|here)\b"
               r"|\bwhat are (these|those)\b"),
    re.compile(r"\bdecris\b|\bdecrit\b|\bdecrire\b|\bdescribe\b"),
    re.compile(r"tu en penses|qu en penses|what do you think"
               r"|\bton avis\b|your opinion|que penses tu"),
    re.compile(r"\bcommente\b|\bcomment\b|look at|\bregarde\b"),
    re.compile(r"analys\w*\s+(cette?|ca|cela|ceci|ceux|celles?|\bce\b|"
               r"this|that|these|those|it|them)\b"),
)

#: Mots courts qui cadrent une question photo de 1-2 tokens (« et ça ? »).
_PHOTO_SHORT_WORDS = frozenset({
    "ca", "ceci", "cela", "this", "that", "these", "those", "it",
    "quoi", "que", "hein", "alors", "voila", "voici",
})

#: Verbes de demande retirés du résidu testé pour l'intention mixte
#: (« montre-moi ce que tu vois » : « montre » vise la photo, pas les données).
_PHOTO_PROBE_EXTRA_RES = (
    re.compile(r"\bmontre\b|\bmontrez\b|\baffiche\b|\baffichez\b"
               r"|\bshow\b|\btell\b|\bdis\b|\bdites\b"),
)


def _photo_norm(message: str) -> str:
    """Texte normalisé pour les motifs photo (apostrophes/tirets -> espace)."""
    return re.sub(r"[''’`\-]", " ", _norm(message or ""))


def is_photo_question(message: str) -> bool:
    """La question porte-t-elle sur l'image jointe ? (fonction pure, FR+EN).

    Photo sans texte (blanc), mention de la photo, ou motif vision /
    description / avis / analyse désignée. Sans image jointe, l'appelant
    ignore ce signal (voir is_photo_only_scope).
    """
    normed = _photo_norm(message)
    tokens = re.findall(r"[a-z0-9]+", normed)
    if not tokens:
        return True
    if any(token in _PHOTO_WORDS for token in tokens):
        return True
    if any(rx.search(normed) for rx in _PHOTO_ABOUT_RES):
        return True
    return len(tokens) <= 2 and any(t in _PHOTO_SHORT_WORDS for t in tokens)


def _photo_probe(message: str) -> str:
    """Message privé de ses mentions/demandes photo (intention résiduelle).

    Sert à tester l'intention mixte : si le résidu route encore vers une
    consultation/création ou une question de données, les deux périmètres
    sont autorisés (photo + demande explicite).
    """
    normed = _photo_norm(message)
    for rx in _PHOTO_ABOUT_RES + _PHOTO_PROBE_EXTRA_RES:
        normed = rx.sub(" ", normed)
    return " ".join(t for t in re.findall(r"[a-z0-9]+", normed)
                    if t not in _PHOTO_WORDS)


def is_photo_only_scope(message: str, context: dict[str, Any] | None = None,
                        has_image: bool = False) -> bool:
    """Périmètre PHOTO exclusif (fonction pure).

    Vrai quand une image est jointe ET que la question porte sur l'image
    sans autre intention explicite : aucun lieu nommé (école/district),
    aucun signal d'élargissement (district, territoire, comparaison,
    toutes/autres écoles), et résidu hors-photo sans intent
    liste/création ni question de données. Question mixte explicite
    (« analyse cette photo et résume Mvila ») : faux, les deux
    périmètres restent autorisés.
    """
    if not has_image or not is_photo_question(message):
        return False
    schools, districts = mentioned_places(message or "", context)
    if schools or districts:
        return False
    signals = detect_scope_signals(message or "")
    if (signals["district"] or signals["territory"] or signals["compare"]
            or signals["all_schools"] or signals["other_school"]):
        return False
    probe = _photo_probe(message)
    if router_route(probe, PLUGIN_HINTS)["intent"] in ("list", "create"):
        return False
    return not is_data_question(probe, PLUGIN_HINTS)


def _is_photo_scope(scope: dict[str, Any] | None) -> bool:
    """Scope restreint à la photo jointe (voir is_photo_only_scope)."""
    return bool(scope) and scope.get("scope") == "photo"


# ---------------------------------------------------------------------------
# Périmètre TEMPOREL : une période demandée = UNIQUEMENT cette période.
# « Donne-moi les incidents signalés aujourd'hui à Bonanjo » ne retourne
# QUE ceux du jour (jamais les 6 ouverts au total) : parse_time_window()
# détecte la période (déterministe FR/EN, aucun appel LLM), le contexte
# d'exécution est restreint aux lignes de la période (agent_tools :
# reported_at/repaired_at, dates civiles, bornes incluses), les cartes
# n'affichent que la période (titres suffixés) et la synthèse dit la
# période et le compte. Période vide : message canonique + total général
# + proposition (« Voir les ouverts ? »), jamais de vide sec.
# « Aujourd'hui » = date du serveur (SERVER_DATE_TZ, UTC) : pas de fuseau
# inventé. Sans période exprimée : comportement historique inchangé.
# ---------------------------------------------------------------------------

#: Nombres en toutes lettres (texte normalisé, cf. _norm) : « sept derniers
#: jours », « last seven days ». Clamp de garde 1..365 dans le parseur.
_TIME_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
    "seize": 16, "vingt": 20, "trente": 30,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "seven": 7,  # ("six" déjà ci-dessus, identique en FR/EN)
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "twenty": 20,
    "thirty": 30,
}

#: Jours de semaine (noms complets seuls : les abréviations comme « mon »
#: ou « mar » sont ambiguës en français) -> lundi=0 .. dimanche=6.
_TIME_WEEKDAYS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

#: Mois (normalisés) -> 1..12. « mai » couvre FR « mai » ; EN « may » idem.
_TIME_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

#: Motifs de période (texte normalisé). Gardes anti-faux-positifs :
#: « avant-hier » et « day before yesterday » exclus (ni hier ni géré),
#: « de la semaine dernière » / « ce mois dernier » lus comme semaine/mois
#: derniers (regard négatif), « le 15 du mois » pas un mois entier.
_TIME_TODAY_RES = (
    re.compile(r"aujourd['’ ]?hui\b"),
    re.compile(r"\btoday\b"),
    re.compile(r"\bce\s+jour\b"),
    re.compile(r"\bce\s+matin\b"),
    re.compile(r"\bcet\s+apres-midi\b"),
    re.compile(r"\bce\s+soir\b"),
    re.compile(r"\bthis\s+morning\b"),
    re.compile(r"\btonight\b"),
)
_TIME_YESTERDAY_RES = (
    re.compile(r"(?<!avant[- ])\bhier\b"),
    re.compile(r"(?<!before\s)\byesterday\b"),
    re.compile(r"\blast\s+night\b"),
    re.compile(r"\bnuit\s+derniere\b"),
    re.compile(r"\bderniere\s+nuit\b"),
)
_TIME_THIS_WEEK_RES = (
    re.compile(r"\bcette\s+semaine(?!\s+derniere)\b"),
    re.compile(r"\bde\s+la\s+semaine(?!\s+derniere)\b"),
    re.compile(r"\bthis\s+week\b"),
    re.compile(r"\bof\s+the\s+week\b"),
)
_TIME_THIS_MONTH_RES = (
    re.compile(r"\bce\s+mois(?!\s+dernier)(?:\s*-?\s*ci)?\b"),
    re.compile(r"(?<!\d\s)\bdu\s+mois\b"),
    re.compile(r"\bde\s+ce\s+mois\b"),
    re.compile(r"\bthis\s+month\b"),
    re.compile(r"\bof\s+the\s+month\b"),
)
_TIME_THIS_YEAR_RES = (
    re.compile(r"\bcette\s+annee\b"),
    re.compile(r"\bthis\s+year\b"),
)
_TIME_LAST_WEEK_RES = (
    re.compile(r"\bderniere\s+semaine\b"),
    re.compile(r"\bsemaine\s+derniere\b"),
    re.compile(r"\blast\s+week\b"),
    re.compile(r"\bpast\s+week\b"),
)
_TIME_LAST_MONTH_RES = (
    re.compile(r"\bdernier\s+mois\b"),
    re.compile(r"\bmois\s+dernier\b"),
    re.compile(r"\blast\s+month\b"),
    re.compile(r"\bpast\s+month\b"),
)
_TIME_LAST_N_FR_RE = re.compile(
    r"\b(?:les|ces|des|ses)?\s*(\d{1,3}|[a-z]+)\s+derniers?\s+jours?\b")
_TIME_LAST_N_EN_RE = re.compile(
    r"\b(?:last|past)\s+(\d{1,3}|[a-z]+)\s+days?\b")
_TIME_SINCE_RE = re.compile(r"\bdepuis\b|\bsince\b")
_TIME_LAST_N_RE = re.compile(r"last_(\d+)d")

#: Proposition déterministe quand la période est vide (jamais de vide sec).
EMPTY_PERIOD_FOLLOW_UPS = {"fr": "Voir les ouverts ?", "en": "See open ones?"}


def server_today() -> date:
    """Date du serveur (tool_consts.SERVER_DATE_TZ) : référence de « aujourd'hui ».

    Documentée une fois ici (pas de fuseau inventé) : même source que le
    rappel de date du prompt système et le défaut de list_maintenance_logs.
    """
    return datetime.now(timezone.utc).date()


def _normalize_today(value: Any) -> date:
    """Normalise today (date|datetime|str ISO) ; défaut = date du serveur."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return server_today()


def _parse_time_number(token: str) -> int | None:
    """Chiffres ou nombre en toutes lettres FR/EN -> entier, None sinon."""
    cleaned = (token or "").strip().lower()
    if re.fullmatch(r"\d{1,3}", cleaned):
        return int(cleaned)
    return _TIME_NUMBER_WORDS.get(cleaned)


def _past_year_day(month: int, day: int, ref: date, year: int | None) -> date | None:
    """Jour calendaire explicite : année donnée, sinon année courante (N-1 si future)."""
    try:
        if year is not None:
            return date(year, month, day)
        candidate = date(ref.year, month, day)
    except ValueError:
        return None
    if candidate > ref:
        try:
            return date(ref.year - 1, month, day)
        except ValueError:
            return None
    return candidate


def _parse_since_origin(rest: str, ref: date) -> date | None:
    """Origine d'un « depuis/since ... » (texte normalisé) -> date, None sinon.

    Comprend : ce matin/hier/aujourd'hui (+EN), date ISO, JJ/MM[/AAAA]
    (jour d'abord), « 3 novembre [AAAA] », « November 3 [AAAA] », jour de
    semaine (le plus récent, jour même inclus), « N jours/semaines/mois »
    (mois = 30 j glissants, documenté). Année omise -> courante (N-1 si
    future) ; origine future -> None (l'appelant n'émet aucun candidat).
    """
    text = re.sub(r"^(le|la|les|the|l)\s+", "", (rest or "").strip())
    if not text:
        return None
    if re.match(r"^(ce\s+matin|this\s+morning|cet\s+apres-midi|ce\s+soir|"
                r"tonight|aujourd['’ ]?hui|today|ce\s+jour)\b", text):
        return ref
    if re.match(r"^hier\b", text) or re.match(r"^yesterday\b", text):
        return ref - timedelta(days=1)
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        try:
            candidate = date(int(match.group(1)), int(match.group(2)),
                             int(match.group(3)))
        except ValueError:
            return None
        return candidate if candidate <= ref else None
    match = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        raw_year = match.group(3)
        year = None
        if raw_year is not None:
            year = int(raw_year)
            if year < 100:
                year += 2000
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            return candidate if candidate <= ref else None
        return _past_year_day(month, day, ref, None)
    match = re.match(r"^(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?\b", text)
    if match:
        month = _TIME_MONTHS.get(match.group(2))
        if month is not None:
            year = int(match.group(3)) if match.group(3) else None
            if year is not None:
                try:
                    candidate = date(year, month, int(match.group(1)))
                except ValueError:
                    return None
                return candidate if candidate <= ref else None
            return _past_year_day(month, int(match.group(1)), ref, None)
    match = re.match(r"^([a-z]+)\s+(\d{1,2})(?:\s+(\d{4}))?\b", text)
    if match:
        month = _TIME_MONTHS.get(match.group(1))
        if month is not None:
            year = int(match.group(3)) if match.group(3) else None
            if year is not None:
                try:
                    candidate = date(year, month, int(match.group(2)))
                except ValueError:
                    return None
                return candidate if candidate <= ref else None
            return _past_year_day(month, int(match.group(2)), ref, None)
        weekday = _TIME_WEEKDAYS.get(match.group(1))
        if weekday is not None and match.group(3) is None and int(match.group(2)) <= 31:
            # « lundi 3 » : le jour de semaine prime (le quantième est un
            # rappel redondant dans les rédactions usuelles).
            return ref - timedelta(days=(ref.weekday() - weekday) % 7)
    match = re.match(r"^([a-z]+)\b", text)
    if match:
        weekday = _TIME_WEEKDAYS.get(match.group(1))
        if weekday is not None:
            return ref - timedelta(days=(ref.weekday() - weekday) % 7)
    match = re.match(r"^(\d{1,3}|[a-z]+)\s+(jours?|days?|semaines?|weeks?|"
                     r"mois|months?)\b", text)
    if match:
        count = _parse_time_number(match.group(1))
        if count is not None and count >= 1:
            unit = match.group(2)
            span = count * (7 if unit.startswith(("semaine", "week")) else
                            30 if unit.startswith("moi") or unit.startswith("month") else 1)
            return ref - timedelta(days=min(span, 3650))
    return None


def parse_time_window(message: str, today: Any = None) -> dict[str, Any]:
    """Période exprimée dans le message (fonction pure, déterministe FR/EN).

    Retourne exactement {"preset", "start", "end"} : preset parmi today,
    yesterday, last_7d, last_30d (ou last_{N}d dynamique), this_week
    (lundi -> aujourd'hui), this_month (1er -> aujourd'hui), this_year,
    since (origine -> aujourd'hui), ou None sans période (start/end None).
    today injectable (date|datetime|str ISO, tests) ; défaut = date du
    serveur. En cas de mentions multiples, la première citée gagne.
    Aucun appel LLM.
    """
    ref = _normalize_today(today)
    text = _norm(message or "")
    if not text.strip():
        return {"preset": None, "start": None, "end": None}
    candidates: list[tuple[int, int, str, date, date]] = []

    def _add(patterns: tuple[re.Pattern[str], ...], priority: int,
            preset: str, start: date, end: date) -> None:
        for pattern in patterns:
            found = pattern.search(text)
            if found:
                candidates.append((found.start(), priority, preset, start, end))

    yesterday = ref - timedelta(days=1)
    _add(_TIME_TODAY_RES, 1, "today", ref, ref)
    _add(_TIME_YESTERDAY_RES, 2, "yesterday", yesterday, yesterday)
    for last_rx in (_TIME_LAST_N_FR_RE, _TIME_LAST_N_EN_RE):
        for found in last_rx.finditer(text):
            count = _parse_time_number(found.group(1))
            if count is None:
                continue
            count = min(max(count, 1), 365)
            if count == TIME_WINDOW_LAST_7D_DAYS:
                preset = "last_7d"
            elif count == TIME_WINDOW_LAST_30D_DAYS:
                preset = "last_30d"
            else:
                preset = f"last_{count}d"
            candidates.append((found.start(), 3, preset,
                               ref - timedelta(days=count - 1), ref))
    _add(_TIME_LAST_WEEK_RES, 3, "last_7d",
         ref - timedelta(days=TIME_WINDOW_LAST_7D_DAYS - 1), ref)
    _add(_TIME_LAST_MONTH_RES, 3, "last_30d",
         ref - timedelta(days=TIME_WINDOW_LAST_30D_DAYS - 1), ref)
    _add(_TIME_THIS_WEEK_RES, 4, "this_week",
         ref - timedelta(days=ref.weekday()), ref)
    _add(_TIME_THIS_MONTH_RES, 5, "this_month", ref.replace(day=1), ref)
    _add(_TIME_THIS_YEAR_RES, 6, "this_year", date(ref.year, 1, 1), ref)
    for found in _TIME_SINCE_RE.finditer(text):
        origin = _parse_since_origin(text[found.end():], ref)
        if origin is not None:
            candidates.append((found.start(), 0, "since", origin, ref))
    if not candidates:
        return {"preset": None, "start": None, "end": None}
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, _, preset, start, end = candidates[0]
    return {"preset": preset, "start": start, "end": end}


def time_window_label(window: dict[str, Any] | None, lang: str = "fr") -> str:
    """Libellé court de la période (« aujourd'hui », « hier »...) ; "" si aucune."""
    preset = (window or {}).get("preset") if isinstance(window, dict) else None
    if not preset:
        return ""
    english = str(lang or "").lower().startswith("en")
    labels = {
        "today": ("aujourd'hui", "today"),
        "yesterday": ("hier", "yesterday"),
        "last_7d": ("les 7 derniers jours", "the last 7 days"),
        "last_30d": ("les 30 derniers jours", "the last 30 days"),
        "this_week": ("cette semaine", "this week"),
        "this_month": ("ce mois-ci", "this month"),
        "this_year": ("cette année", "this year"),
    }
    if preset in labels:
        return labels[preset][1] if english else labels[preset][0]
    match = _TIME_LAST_N_RE.fullmatch(str(preset))
    if match:
        count = match.group(1)
        return f"the last {count} days" if english else f"les {count} derniers jours"
    if preset == "since":
        start = (window or {}).get("start")
        if isinstance(start, (datetime, date)):
            start = start.isoformat() if isinstance(start, date) and not isinstance(
                start, datetime) else str(start)[:10]
        if start:
            return f"since {start}" if english else f"depuis le {start}"
        return "recently" if english else "ces derniers temps"
    return ""


def period_place_suffix(scope: dict[str, Any] | None, lang: str = "fr") -> str:
    """Suffixe lieu de la période (« à Bonanjo », « dans le district Mvila »)."""
    english = str(lang or "").lower().startswith("en")
    schools = (scope or {}).get("schools") or []
    if len(schools) == 1 or ((scope or {}).get("scope") == "school"
                             and (scope or {}).get("school") and not schools):
        school = schools[0] if schools else (scope or {}).get("school")
        short = short_school_name(str(school)) or str(school)
        return f" at {short}" if english else f" à {short}"
    district = (scope or {}).get("district")
    if (scope or {}).get("scope") == "district" and district:
        return f" in the {district} district" if english else f" dans le district {district}"
    return ""


def format_empty_period_message(window: dict[str, Any] | None,
                                scope: dict[str, Any] | None,
                                total: int, lang: str = "fr") -> str:
    """Message canonique période vide : absence datée + stock général (jamais de vide sec)."""
    label = time_window_label(window, lang)
    place = period_place_suffix(scope, lang)
    if str(lang or "").lower().startswith("en"):
        return f"No incidents reported {label}{place}. ({total} open in total.)"
    return f"Aucun incident signalé {label}{place}. ({total} ouverts au total.)"


def _annotate_period_obs(name: str, observation: dict[str, Any],
                         window: dict[str, Any] | None,
                         total: int, place: str) -> None:
    """Tamponne une observation réussie (période + stock général), en place.

    Le modèle lit la période, le libellé et le total hors-période ; les
    synthèses déterministes (_summarize_*) et les cartes s'en servent aussi.
    Créations (prepare_*) et erreurs : jamais tamponnées.
    """
    if window is None or not isinstance(observation, dict):
        return
    if "error" in observation or name.startswith("prepare_"):
        return
    start, end = window.get("start"), window.get("end")
    observation["time_window"] = {
        "preset": window.get("preset"),
        "label": time_window_label(window, "fr"),
        "start": start.isoformat() if isinstance(start, date) else start,
        "end": end.isoformat() if isinstance(end, date) else end,
    }
    observation["total_ouverts"] = total
    if place:
        observation["period_place"] = place


#: Outils de lecture « liste d'incidents » : leur succès sur une période
#: vide autorise le message canonique « aucun incident signalé ». Le
#: journal (interventions réalisées), le détail d'un incident
#: (explain_incident) et les plugins (sémantiques propres) ne l'autorisent
#: pas : leur réponse garde son sens même quand le compte période est nul.
PERIOD_EMPTY_TOOLS = frozenset({
    "summarize_district",
    "analyze_school",
    "rank_schools_by_need",
    "repair_trends",
    "territory_overview",
    "build_briefing",
    "list_incidents",
})


def _has_successful_period_list(executed: list[tuple[str, dict[str, Any]]]) -> bool:
    """Au moins un outil liste d'incidents a-t-il réussi ce tour-ci ?"""
    return any(name in PERIOD_EMPTY_TOOLS
               and isinstance(obs, dict) and "error" not in obs
               for name, obs in (executed or []))


def _has_prepare_exec(executed: list[tuple[str, dict[str, Any]]]) -> bool:
    """Une création (prepare_*) a-t-elle été exécutée ce tour-ci ?"""
    return any(name.startswith("prepare_") for name, _ in (executed or []))


#: Types de cartes de données : titres suffixés de la période quand elle est
#: exprimée (« Synthèse du district (aujourd'hui) »). Créations, guidage,
#: photo et suggestions de lieux : jamais suffixés. Cartes plugins en
#: lecture seule : suffixées via le nom d'outil (PLUGIN_READ_ONLY).
PERIOD_TITLE_TYPES = frozenset({
    "school_analysis",
    "school_ranking",
    "district_summary",
    "incident_detail",
    "incident_timeline",
    "briefing_deck",
    "territory_map",
    "trend_chart",
    "calendar_heatmap",
    "budget_compare",
    "maintenance_logs",
    "incident_list",
})


# ---------------------------------------------------------------------------
# Clarification guidée : périmètre manquant (le lieu exigé n'est pas nommé).
# « Compare un district ? » sans district : la réponse repose LA question en
# une phrase et les relances deviennent des choix cliquables tirés du
# contexte réel, au lieu de laisser le modèle deviner. Questions globales
# légitimes (comptes, tout-le-territoire, classements, envois) : jamais
# interceptées. Mémo conversation : un lieu seul (« Mvila ») se rattache à
# la question précédente en attente via l'historique, sans état serveur.
# ---------------------------------------------------------------------------

#: Mots (normalisés) qui cadrent « district » au singulier (« mon district »).
_DISTRICT_PRECEDERS = frozenset({
    "un", "mon", "ton", "son", "ce", "cet", "quel", "quelle",
    "le", "du", "au", "en", "dans", "par", "pour", "sur", "vers",
    "chaque", "de", "d", "notre", "votre",
    "a", "an", "my", "the", "this", "that", "which", "what",
    "each", "per", "in", "for", "of", "our", "your",
})

#: Mots (normalisés) qui cadrent « école »/« school » au singulier.
_SCHOOL_PRECEDERS = frozenset({
    "une", "la", "l", "cette", "quelle", "ma", "ta", "sa",
    "le", "de", "d", "en", "dans", "par", "pour", "sur", "vers",
    "chaque", "mon", "notre", "votre",
    "a", "an", "the", "this", "that", "which", "what", "my",
    "each", "per", "in", "for", "of", "at", "our", "your",
})

#: Questions globales légitimes (texte normalisé) : jamais interceptées.
_GLOBAL_OK_RES = (
    re.compile(r"\bcombien\b|how many|how much"),
    re.compile(r"\ble plus\b|\bla plus\b|\bles plus\b|\bmost\b|\btop\b|"
               r"classement|ranking|priorita|besoin d aide|need help"),
    re.compile(r"\btoutes?\b|\btous\b|\bchaque\b|\ball\b|\bevery\b"),
    re.compile(r"qui envoyer|envoyer|depech|dispatch|\bsend\b"),
)

#: Intention de la question (gabarit des choix), testée dans l'ordre.
_CLARIFY_INTENT_RES = (
    ("compare", re.compile(r"\bcompar|comparison|\bvs\b|versus")),
    ("trends", re.compile(r"\btendanc|\btrend")),
    ("budget", re.compile(r"\bbudget|\bcouts?\b|\bcost")),
    ("map", re.compile(r"\bcartes?\b|\bmaps?\b|\bwhere\b")),
    ("journal", re.compile(r"\binterventions?\b|\bjournal|\blogs?\b|"
                           r"\bhistorique\b|\bhistory\b|\btravaux\b|\brealis")),
    ("recap", re.compile(r"\bresum|\brecap|\bsummary|\bsynthese|\bbriefing|"
                         r"\bbilan|\banalys|\betat\b|\bpoint\b")),
)

#: Mots ignorés autour d'un lieu seul (« le district Mvila », « Mvila »).
_BARE_PLACE_SKIPS = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "au", "aux",
    "a", "mon", "ma", "mes", "ton", "ta", "son", "sa", "ce", "cet",
    "cette", "notre", "votre",
    "ecole", "ecoles", "district", "districts", "classe", "classes",
    "lycee", "lycees", "college", "colleges",
    "the", "an", "my", "this", "that", "school", "schools",
})


def _scope_framing(message: str) -> tuple[bool, bool]:
    """Cadrage explicite du périmètre : (district, école) (fonction pure).

    Singulier cadré (« mon district », « l'école », « which district ») ou
    mot-classe (« classe »). Les pluriels (« les écoles », « districts »)
    désignent tout l'ensemble : pas de cadrage (question globale).
    """
    tokens = re.findall(r"[a-z]+", _norm(message or ""))
    district = school = False
    for i, token in enumerate(tokens):
        prev = tokens[i - 1] if i > 0 else ""
        if token == "district":
            if prev in _DISTRICT_PRECEDERS:
                district = True
        elif token == "ecole" or token == "school":
            if prev in _SCHOOL_PRECEDERS:
                school = True
        elif token in ("classe", "classes", "class"):
            school = True
    return district, school


def needs_clarification(
    message: str,
    context: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> Literal["district", "school"] | None:
    """Périmètre manquant : "district"/"school" si la question exige un lieu
    nommé sans le donner, None sinon (fonction pure).

    Déclencheurs : comparaison, district/école/classe au singulier cadré,
    sans école ni district résolu. Jamais : lieu résolu, question globale
    légitime (comptes, tout-le-territoire, classements, envois), création
    (le dossier prepare_* demande déjà l'école), pluriels d'ensemble.
    """
    text = message or ""
    if not text.strip():
        return None
    resolved = scope if scope is not None else detect_scope(text, context)
    if resolved.get("school") or resolved.get("schools") or resolved.get("district"):
        return None
    normed = _norm(text)
    for global_re in _GLOBAL_OK_RES:
        if global_re.search(normed):
            return None
    if router_route(text, PLUGIN_HINTS)["intent"] == "create":
        return None
    district_framed, school_framed = _scope_framing(text)
    signals = detect_scope_signals(text)
    if signals["territory"] and not (district_framed or school_framed):
        return None
    if signals["compare"]:
        tokens = set(re.findall(r"[a-z]+", normed))
        if tokens & {"ecoles", "schools", "districts"}:
            return None
        if "district" in tokens or district_framed:
            return "district"
        return "school"
    if district_framed:
        return "district"
    if school_framed:
        return "school"
    return None


def _clarify_intent(message: str) -> str:
    """Intention (compare/trends/budget/map/journal/recap) pour les gabarits."""
    normed = _norm(message or "")
    for intent, intent_re in _CLARIFY_INTENT_RES:
        if intent_re.search(normed):
            return intent
    return "recap"


def clarify_follow_ups(
    kind: str,
    message: str,
    context: dict[str, Any] | None = None,
    lang: str = "fr",
    limit: int = 3,
) -> list[str]:
    """Choix cliquables de clarification depuis le contexte réel (fonction pure).

    Questions complètes citant des lieux connus ; [] sans lieu connu
    (l'appelant replie alors sur les relances actuelles). Jamais d'erreur.
    """
    try:
        schools, districts = known_places(context or {})
    except (AttributeError, TypeError, ValueError):
        return []
    return clarify_choices(kind, _clarify_intent(message), schools, districts,
                           lang=lang, limit=limit)


def _with_clarify_question(answer: str, kind: str, lang: str) -> str:
    """Panorama + question de clarification (une phrase, sans doublon)."""
    question = clarify_question(kind, lang)
    if not answer or not answer.strip():
        return question
    normed = _norm(answer)
    for candidate in (question, clarify_question(
            "school" if kind == "district" else "district", lang)):
        if _norm(candidate.rstrip("? ")) in normed:
            return answer
    return f"{answer.strip()} {question}"


def _last_user_turn(history: Any) -> str:
    """Contenu du dernier tour utilisateur (ChatTurn ou dict), "" sinon."""
    for turn in reversed(history or []):
        if isinstance(turn, dict):
            role, content = turn.get("role"), turn.get("content")
        else:
            role, content = getattr(turn, "role", None), getattr(turn, "content", None)
        if role == "user" and content and str(content).strip():
            return str(content)
    return ""


def resolve_bare_place_followup(
    message: str,
    history: Any,
    context: dict[str, Any] | None = None,
) -> str:
    """Rattache un lieu seul à la question précédente en attente (fonction pure).

    « Mvila » après « Compare un district ? » -> « Compare un district
    Mvila » (l'intention compare/tendances/récap reprend). Inchangé si le
    message n'est pas un lieu seul, sans historique, ou si la question
    précédente n'attendait aucun lieu. Sans état serveur : que l'historique.
    """
    text = message or ""
    stripped = text.strip()
    if not stripped or len(stripped) > 40 or len(stripped.split()) > 4:
        return text
    place = resolve_place(stripped, context or {})
    if place is None:
        return text
    label_tokens = set(re.findall(r"[a-z]+", _norm(place[1])))
    leftovers = [t for t in re.findall(r"[a-z]+", _norm(stripped))
                 if len(t) >= 4 and t not in label_tokens
                 and t not in _BARE_PLACE_SKIPS]
    if leftovers:
        return text
    previous = _last_user_turn(history)
    if not previous or needs_clarification(previous, context) is None:
        return text
    base = previous.strip()
    while base and base[-1] in "?!":
        base = base[:-1].rstrip()
    label = short_school_name(place[1]) if place[0] == "school" else place[1]
    return f"{base} {label}"


#: Noms de livrables (texte normalisé) : rapport, diaporama, briefing...
_REPORT_NOUNS_RE = re.compile(
    r"\brapports?\b|\bdiaporamas?\b|\bbriefings?\b|\bdossiers?\b"
    r"|\bpresentations?\b|\bslides?\b|\bdocuments?\b")

#: Verbes de génération (un livrable à PRODUIRE, pas une liste à afficher).
_REPORT_GEN_VERBS_RE = re.compile(
    r"\bprepare\w*|\bgenere\w*|\bfais\b|\bfaites\b|\bcree\w*"
    r"|\bredige\w*|\bconstruis\w*|\bassemble\w*|\becris\b|\becrire\b")

#: Listings exclus (« donne-moi les rapports », « quels dossiers ? ») : le
#: sujet hérité transformerait un inventaire global en inventaire d'école.
_REPORT_LIST_RE = re.compile(
    r"\b(donne\w*|montre\w*|affiche\w*|liste\w*|quels?|combien)\b"
    r".*\b(rapports|dossiers|documents|diaporamas|briefings)\b"
    r"|\b(les|des|mes|ces)\s+(rapports|dossiers|documents|diaporamas|briefings)\b")


def _turn_text(turn: Any) -> str:
    """Contenu texte d'un tour d'historique (ChatTurn ou dict), '' sinon."""
    if isinstance(turn, dict):
        content = turn.get("content")
    else:
        content = getattr(turn, "content", None)
    return str(content) if content and str(content).strip() else ""


def recent_single_place(
    history: Any,
    context: dict[str, Any] | None = None,
) -> tuple[str, str] | None:
    """Sujet lieu unique des tours récents : ("school"|"district", label).

    Premier tour (en remontant, REPORT_FOLLOWUP_TURNS max) qui cite un lieu
    décide : une seule école -> son nom court, un seul district -> son nom.
    2+ lieux (ambigu) ou aucun lieu cité -> None : on ne devine jamais.
    Fonction pure, sans état serveur. Partagée par les mémos rapport et
    préparation d'intervention.
    """
    turns = list(reversed(history or []))[:REPORT_FOLLOWUP_TURNS]
    for turn in turns:
        content = _turn_text(turn)
        if not content:
            continue
        turn_schools, turn_districts = mentioned_places(content, context or {})
        if not turn_schools and not turn_districts:
            continue
        if len(turn_schools) == 1 and not turn_districts:
            return ("school", short_school_name(turn_schools[0]))
        if len(turn_districts) == 1 and not turn_schools:
            return ("district", turn_districts[0])
        return None
    return None


def resolve_report_followup(
    message: str,
    history: Any,
    context: dict[str, Any] | None = None,
) -> str:
    """Rattache un rapport sans lieu au sujet discuté (fonction pure).

    « Prépare un rapport » après un tour ne citant que Bonanjo ->
    « Prépare un rapport Bonanjo » (le périmètre école s'applique, le
    rapport est spécifique au lieu de couvrir tout le territoire).
    Inchangé si : lieu explicite dans le message, listing (« donne-moi
    les rapports »), pas de génération demandée, historique vide, ou
    contexte ambigu (2+ lieux dans le premier tour qui en cite).
    Sans état serveur : que l'historique (REPORT_FOLLOWUP_TURNS tours).
    """
    text = message or ""
    normed = _norm(text)
    if (not normed.strip() or not _REPORT_NOUNS_RE.search(normed)
            or not _REPORT_GEN_VERBS_RE.search(normed)
            or _REPORT_LIST_RE.search(normed)):
        return text
    schools, districts = mentioned_places(text, context or {})
    if schools or districts:
        return text
    place = recent_single_place(history, context)
    if place is None:
        return text
    base = text.strip()
    while base and base[-1] in "?!":
        base = base[:-1].rstrip()
    return f"{base} {place[1]}"


def resolve_prep_followup(
    message: str,
    history: Any,
    context: dict[str, Any] | None = None,
) -> str:
    """Rattache une prépa sans lieu au sujet discuté (fonction pure).

    « Prépare une intervention pour le robinet... » après un tour ne
    citant que Bonanjo -> « ... Bonanjo » (la branche déterministe
    scope le dossier au lieu de rendre la main au listing). Inchangé
    si : lieu explicite, pas une demande de planification, ou sujet
    récent ambigu/absent. Miroir de resolve_report_followup.
    """
    text = message or ""
    if not is_intervention_prep_request(text):
        return text
    schools, districts = mentioned_places(text, context or {})
    if schools or districts:
        return text
    place = recent_single_place(history, context)
    if place is None:
        return text
    base = text.strip()
    while base and base[-1] in "?!":
        base = base[:-1].rstrip()
    return f"{base} {place[1]}"


def _last_assistant_turn(history: Any) -> str:
    """Contenu du dernier tour assistant (ChatTurn ou dict), '' sinon."""
    for turn in reversed(history or []):
        if isinstance(turn, dict):
            role, content = turn.get("role"), turn.get("content")
        else:
            role, content = getattr(turn, "role", None), getattr(turn, "content", None)
        if role == "assistant" and content and str(content).strip():
            return str(content)
    return ""


#: Questions de slots du dossier prépa (miroir normalisé de _SLOT_QUESTIONS
#: de app/tools/prepare_intervention.py) : leur présence dans le dernier
#: tour assistant prouve une prépa en cours d'interrogatoire.
_PREP_QUESTION_MARKERS = (
    "pour quelle date prevoir l intervention",
    "quelle equipe doit intervenir",
    "quel incident existant faut il reparer",
)

#: Budget déjà cadré dans le tour prépa (« budget 100 000 XAF »).
_PREP_BUDGET_RE = re.compile(r"budget\s+(\d[\d\s\u00a0.,]*)\s*xaf", re.IGNORECASE)


def _match_team_name(message: str, context: dict[str, Any] | None) -> str | None:
    """Équipe active du contexte nommée dans le message, sinon None.

    Nom complet contenu (normalisé, insensible casse/accents), plus long
    match gagne : « Confier à Équipe Wouri Nord » -> « Équipe Wouri Nord ».
    Fonction pure.
    """
    normed = _norm(message or "")
    best: str | None = None
    for team in (context or {}).get("teams", []) or []:
        if not isinstance(team, dict) or not team.get("is_active", True):
            continue
        name = str(team.get("name") or "").strip()
        normed_name = _norm(name)
        if normed_name and normed_name in normed and (
                best is None or len(normed_name) > len(_norm(best))):
            best = name
    return best


def resolve_prep_slot_followup(
    message: str,
    history: Any,
    context: dict[str, Any] | None = None,
    today: Any = None,
) -> str:
    """Complète une prépa en cours avec la réponse courte (fonction pure).

    Dernier tour assistant en interrogatoire prépa + « Confier à Équipe
    Wouri Nord » -> « Prépare une intervention pour WASH-… à Bonanjo,
    budget 100 000 XAF, équipe Équipe Wouri Nord » (slots antérieurs
    réextraits du tour : réf, école, budget). « demain » -> même
    reconstitution + date. Inchangé si : pas de prépa en cours, requête
    de planification déjà complète, ni équipe ni date détectée, autre
    école nommée (changement de sujet), ou rien à reconstituer.
    """
    from .tools.prepare_intervention import parse_date
    text = (message or "").strip()
    if not text or is_intervention_prep_request(text):
        return message or ""
    prep_turn = _last_assistant_turn(history)
    if not prep_turn or not any(
            marker in _norm(prep_turn) for marker in _PREP_QUESTION_MARKERS):
        return message or ""
    ctx = context or {}
    team = _match_team_name(text, ctx)
    try:
        ref_today = today if today is not None else server_today()
        has_date = parse_date(text, ref_today) is not None
    except (TypeError, ValueError):
        has_date = False
    if team is None and not has_date:
        return message or ""
    turn_schools, _ = mentioned_places(prep_turn, ctx)
    if len(turn_schools) != 1:
        return message or ""
    prep_school = turn_schools[0]
    msg_schools, _ = mentioned_places(text, ctx)
    if msg_schools and not any(_school_arg_matches(s, prep_school) for s in msg_schools):
        return message or ""
    ref_match = WASH_REF_RE.search(prep_turn)
    ref = ref_match.group(0) if ref_match else None
    budget_match = _PREP_BUDGET_RE.search(prep_turn)
    budget = None
    if budget_match:
        try:
            budget = int(re.sub(r"[\s\u00a0.,]", "", budget_match.group(1)))
        except (TypeError, ValueError):
            budget = None
    if ref is None:
        parts = [f"Prépare une intervention à {short_school_name(prep_school)}"]
    else:
        parts = [f"Prépare une intervention pour {ref} à {short_school_name(prep_school)}"]
    if budget is not None:
        parts.append(f"budget {budget} XAF")
    if team is not None:
        parts.append(f"équipe {team}")
    if has_date:
        date_text = text.strip()
        while date_text and date_text[-1] in "?!":
            date_text = date_text[:-1].rstrip()
        parts.append(date_text)
    return ", ".join(parts)


def _single_school_scope(scope: dict[str, Any] | None) -> str | None:
    """Nom de l'école si périmètre restreint à une seule école, sinon None.

    Multi-écoles explicite (comparaison), district, territoire, défaut large
    ou scope absent : None (comportement historique inchangé).
    """
    if not scope or scope.get("scope") != "school":
        return None
    schools = scope.get("schools") or []
    if len(schools) == 1:
        return schools[0]
    if not schools and scope.get("school"):
        return scope["school"]
    return None


def _school_arg_matches(target: Any, school: str) -> bool:
    """L'argument/observation école désigne-t-il l'école du périmètre ?

    Fragments acceptés (« Ngok » = « École Rurale de Ngok »), mots génériques
    (« école ») ignorés dans la comparaison par tokens. Fonction pure.
    """
    if not isinstance(target, str) or not target.strip() or not school:
        return False
    want, have = _norm(target), _norm(school)
    if not want:
        return False
    if want in have or have in want:
        return True
    want_tokens = {t for t in want.split()
                   if len(t) >= 4 and t not in _GENERIC_PLACE_TOKENS}
    have_tokens = {t for t in have.split()
                   if len(t) >= 4 and t not in _GENERIC_PLACE_TOKENS}
    return bool(want_tokens & have_tokens)


def _obs_school_matches(entry: Any, school: str,
                        others: tuple[str, ...] | list[str] = ()) -> bool:
    """L'entrée d'observation concerne-t-elle l'école du périmètre ?

    Sans attribution école : conservée — on ne supprime que ce qui est
    prouvé hors périmètre (champ école d'une autre école, ou chaîne citant
    une autre école connue via `others`). Fonction pure.
    """
    if isinstance(entry, str):
        if not entry.strip() or _school_arg_matches(entry, school):
            return True
        return not any(_school_arg_matches(entry, other) for other in others)
    if not isinstance(entry, dict):
        return True
    value = entry.get("school_name") or entry.get("nom")
    if not value:
        return True
    return _school_arg_matches(value, school)


def _blocked_by_scope(name: str, arguments: dict[str, Any] | None,
                      scope: dict[str, Any] | None) -> str | None:
    """Motif de blocage si l'appel sort du périmètre école unique, sinon None.

    Bloque les outils district/territoire/comparaison, les appels globaux des
    outils mixtes (repair_trends sans école ou avec district, journal sans
    école, rapport sans topic) et les appels visant une autre école. Périmètre
    photo : TOUS les outils sont bloqués (commentaire de la photo seule).
    Fonction pure.
    """
    if _is_photo_scope(scope):
        return (
            "Hors périmètre : la question porte uniquement sur la photo jointe ; "
            f"l'outil {name} interroge les données WASH. "
            "Commente la photo sans appeler d'outil."
        )
    school = _single_school_scope(scope)
    if school is None:
        return None
    args = arguments or {}
    if name in SCHOOL_TOPIC_TOOLS:
        topic = args.get("topic")
        if not topic:
            return (
                f"Hors périmètre : la question porte uniquement sur {school} ; "
                f"précise topic={school} au lieu d'un rapport global."
            )
        if not _school_arg_matches(topic, school):
            return (
                f"Hors périmètre : la question porte uniquement sur {school} "
                f"({topic} est un autre lieu). "
                f"N'appelle que des outils pour {school}."
            )
        return None
    if name in DISTRICT_SCOPE_TOOLS:
        return (
            f"Hors périmètre : la question porte uniquement sur {school} ; "
            f"l'outil {name} couvre d'autres écoles (district, territoire ou "
            f"comparaison). N'appelle que des outils pour {school}."
        )
    if name in ("analyze_school", "repair_trends"):
        if args.get("district"):
            return (
                f"Hors périmètre : la question porte uniquement sur {school} ; "
                "ne demande aucune agrégation district. "
                f"Précise school={school}."
            )
        target = args.get("school")
        if name == "repair_trends" and not target:
            return (
                f"Hors périmètre : la question porte uniquement sur {school} ; "
                f"précise school={school} au lieu d'une synthèse globale."
            )
        if target and not _school_arg_matches(target, school):
            return (
                f"Hors périmètre : la question porte uniquement sur {school} "
                f"({target} est une autre école). "
                f"N'appelle que des outils pour {school}."
            )
    if name in ("list_maintenance_logs", "list_incidents") and not args.get("school"):
        return (
            f"Hors périmètre : la question porte uniquement sur {school} ; "
            f"précise school={school} au lieu de la liste globale."
        )
    return None


def _no_tool_nudge(scope: dict[str, Any] | None) -> str:
    """Recadrage no-tool : outils école seule en périmètre restreint."""
    school = _single_school_scope(scope)
    if school is None:
        return NO_TOOL_NUDGE
    return (
        "Tu as répondu à une question de données sans appeler d'outil : "
        f"appelle maintenant l'outil adapté pour l'école {school} "
        "(analyze_school, repair_trends, explain_incident, "
        "list_maintenance_logs, list_incidents). N'écris aucun texte, appelle juste l'outil."
    )


def _absence_nudge(scope: dict[str, Any] | None) -> str:
    """Recadrage absence : outils école seule en périmètre restreint."""
    school = _single_school_scope(scope)
    if school is None:
        return ABSENCE_CORRECTION_NUDGE
    return (
        "Tu viens d'affirmer une absence (aucun/aucune/rien/zéro) sans avoir "
        "observé un outil de lecture : appelle maintenant l'outil adapté "
        f"pour l'école {school} (list_incidents, list_maintenance_logs, repair_trends, "
        "explain_incident ou analyze_school) puis réponds à partir de "
        "son observation. N'écris aucun texte, appelle juste l'outil."
    )


#: Séparateur de phrases (ponctuation forte + sauts de ligne).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


def strip_other_school_mentions(answer: str, scope: dict[str, Any] | None,
                                context: dict[str, Any] | None = None) -> str:
    """Supprime les phrases citant une AUTRE école connue (fonction pure).

    Périmètre école unique uniquement : toute phrase mentionnant un nom (ou
    mot distinctif) d'une autre école du contexte est supprimée ; les phrases
    génériques (sans nom d'école) et celles de l'école demandée sont gardées.
    Hors périmètre restreint ou sans autre école connue : inchangé.
    """
    school = _single_school_scope(scope)
    if school is None or not answer or not answer.strip():
        return answer
    schools, _ = known_places(context or {})
    own = _norm(school)
    own_tokens = set(own.split())
    markers: list[str] = []
    for other in schools:
        other_norm = _norm(other)
        if not other_norm or other_norm == own:
            continue
        if len(other_norm) >= 4 and other_norm not in own and own not in other_norm:
            markers.append(other_norm)
        for token in other_norm.split():
            if (len(token) >= 4 and token not in _GENERIC_PLACE_TOKENS
                    and token not in own_tokens and token not in own):
                markers.append(token)
    if not markers:
        return answer
    kept: list[str] = []
    for part in _SENTENCE_SPLIT_RE.split(answer):
        if not part.strip():
            continue
        if any(marker in _norm(part) for marker in markers):
            continue
        kept.append(part.strip())
    return " ".join(kept)


# Garde-fou abstention : outils de lecture dont l'observation autorise un constat.
READ_TOOLS = frozenset({
    "list_maintenance_logs", "list_incidents", "summarize_district", "rank_schools_by_need",
    "repair_trends", "explain_incident", "territory_overview",
    "analyze_school", "build_briefing",
}) | PLUGIN_READ_ONLY

ABSENCE_RE = re.compile(r"aucun|aucune|pas d|rien|zéro|zero", re.IGNORECASE)

ABSENCE_CORRECTION_NUDGE = (
    "Tu viens d'affirmer une absence (aucun/aucune/rien/zéro) sans avoir "
    "observé un outil de lecture : appelle maintenant "
    "l'outil de liste adapté (list_incidents pour les signalements déclarés, "
    "list_maintenance_logs pour les interventions passées, sinon summarize_district, "
    "rank_schools_by_need, repair_trends, explain_incident, territory_overview, "
    "analyze_school ou build_briefing) puis réponds à partir de son observation. "
    "N'écris aucun texte, appelle juste l'outil."
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
    "Rappelle maintenant l'outil de liste adapté (list_incidents pour les "
    "signalements déclarés, list_maintenance_logs pour les interventions passées) "
    "sans filtre école parasite, puis réponds de "
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


def _build_system_prompt(lang: str, scope: dict[str, Any] | None = None,
                        time_window: dict[str, Any] | None = None) -> str:
    """Prompt système + langue de réponse explicite transmise au provider (en tête : primauté).

    Périmètre école unique : consigne de périmètre ajoutée (défense en
    profondeur, les garde-fous déterministes restant premiers). Période
    exprimée : consigne de verrou temporel (les observations sont déjà
    restreintes à la période, le modèle doit la dire et compter juste).
    """
    head = "REPLY ONLY IN ENGLISH. Never use French." if lang == "en" else "Réponds en français."
    today = datetime.now(timezone.utc).date().isoformat()
    text = (
        f"{head}\n{SYSTEM_PROMPT}\nLangue de réponse : {lang}.\n"
        f"Aujourd'hui : {today} (date du jour — utilise-la pour 'aujourd'hui' ; "
        "'hier' = la veille, 'cette semaine' = lundi à aujourd'hui, "
        "'ce mois-ci' = du 1er à aujourd'hui)."
    )
    if time_window is not None and time_window.get("preset"):
        label = time_window_label(time_window, lang)
        start, end = time_window.get("start"), time_window.get("end")
        if lang == "en":
            text += (
                f"\nTime lock: the user asked about {label} ({start} to {end}) "
                "ONLY — answer strictly about this period, state the period "
                "and the count, never mix with the general stock."
            )
        else:
            text += (
                f"\nPérimètre temporel imposé : l'utilisateur demande {label} "
                f"({start} au {end}) UNIQUEMENT — réponds strictement sur "
                "cette période, dis la période et le compte, ne mélange "
                "jamais avec le stock général."
            )
    school = _single_school_scope(scope)
    if school is not None:
        if lang == "en":
            text += (
                f"\nScope lock: the user asked about school {school} ONLY — "
                "talk only about this school, never mention another school, "
                "and never invent an unrequested comparison."
            )
        else:
            text += (
                f"\nPérimètre imposé : l'utilisateur demande l'école {school} "
                "UNIQUEMENT — ne parle que de cette école, ne cite aucune "
                "autre école, et n'invente aucune comparaison non demandée."
            )
    if _is_photo_scope(scope):
        if lang == "en":
            text += (
                "\nPhoto-only scope: the user asked about the attached photo "
                "ONLY — comment on it without calling any tool and without "
                "other figures."
            )
        else:
            text += (
                "\nPérimètre imposé : l'utilisateur demande UNIQUEMENT un "
                "commentaire de la photo jointe — sans appeler d'outil ni "
                "citer d'autres chiffres."
            )
    return text


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


def _unified_pupils_total(obs: dict[str, Any]) -> Any:
    """Effectif unifié (somme des max par école), repli legacy si absent.

    Le texte dit la même chose que les cartes (qui lisent *_max) : sans
    cette unification, la synthèse cite le vieux total sommé (double-compte
    à l'école) alors que la carte affiche le max unifié.
    """
    value = obs.get("total_affected_students_max")
    if value is None:
        value = obs.get("total_affected_students", 0)
    return value


def _period_meta(obs: dict[str, Any]) -> tuple[str, str, Any]:
    """Annotation période d'une observation : (libellé, suffixe lieu, stock général).

    ("", "", None) sans période exprimée : les synthèses suivent alors le
    chemin historique, strictement inchangé.
    """
    window = obs.get("time_window") or {}
    label = str(window.get("label") or "")
    if not label:
        return "", "", None
    return label, str(obs.get("period_place") or ""), obs.get("total_ouverts")


def _period_stock(stock_n: Any) -> str:
    """Parenthèse stock général (« (6 ouverts au total.) »), "" si inconnu."""
    if stock_n is None:
        return ""
    try:
        return f" ({int(stock_n)} ouverts au total.)"
    except (TypeError, ValueError):
        return ""


def _summarize_district(obs: dict[str, Any]) -> str:
    n = int(obs.get("open_incidents", 0) or 0)
    pupils = _fmt_int(_unified_pupils_total(obs))
    schools = obs.get("schools_involved", []) or []
    critical = int((obs.get("by_urgency", {}) or {}).get("critical", 0) or 0)
    label, place, stock_n = _period_meta(obs)
    if label:
        stock = _period_stock(stock_n)
        if n == 0:
            return f"Aucun incident signalé {label}{place}.{stock}"
        text = (
            f"{n} {_plural(n, 'incident signalé', 'incidents signalés')} "
            f"{label}{place} ({pupils} élèves, {len(schools)} "
            f"{_plural(len(schools), 'école')}"
        )
        if critical:
            text += f", dont {critical} {_plural(critical, 'critique')}"
        return text + f".{stock} Le détail est dans la carte ci-dessous."
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
    label, _place, stock_n = _period_meta(obs)
    if label:
        n = int(figures.get("total_incidents", 0) or 0)
        return (
            f"À {obs.get('school_name', '?')} {label} : "
            f"{n} {_plural(n, 'panne', 'pannes')}, "
            f"{_fmt_int(figures.get('total_cost', 0))} "
            f"{figures.get('currency', 'XAF')} de réparations."
            f"{_period_stock(stock_n)} Le graphique est dans la carte ci-dessous."
        )
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
    label, place, stock_n = _period_meta(obs)
    if label:
        stock = _period_stock(stock_n)
        if not ranking:
            return f"Aucune école avec panne signalée {label}{place}.{stock}"
        top = ranking[0]
        total = int(obs.get("total", len(ranking)) or 0)
        return (
            f"{total} {_plural(total, 'école concernée', 'écoles concernées')} "
            f"par des pannes signalées {label}{place}, en tête : "
            f"{top.get('school_name', '?')} (score {_fmt_1(top.get('need_score', 0))})."
            f"{stock} Le classement complet est dans la carte ci-dessous."
        )
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
    label, _place, stock_n = _period_meta(obs)
    if label:
        stock = _period_stock(stock_n)
        if n == 0:
            return (
                f"À {obs.get('school_name', '?')} : aucune panne signalée {label}."
                f"{stock} L'analyse complète est dans la carte ci-dessous."
            )
        return (
            f"À {obs.get('school_name', '?')} : {n} "
            f"{_plural(n, 'panne signalée', 'pannes signalées')} {label}, "
            f"ratio réparations/neuf de {_fmt_1(obs.get('repair_ratio_percent', 0))} %. "
            f"Verdict : {verdict}.{stock} L'analyse complète est dans la carte ci-dessous."
        )
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


def _summarize_incidents(obs: dict[str, Any]) -> str:
    items = obs.get("items", []) or []
    date = obs.get("date", "?")
    n = int(obs.get("total", len(items)) or 0)
    if not items and n == 0:
        return f"Aucun signalement déclaré le {date}."
    names = [str(i.get("school_name", "?")) for i in items[:3]]
    suffix = f" : {', '.join(names)}" if names else ""
    return (
        f"{n} {_plural(n, 'signalement déclaré', 'signalements déclarés')} "
        f"le {date}{suffix}. Le détail est dans la carte ci-dessous."
    )


def _summarize_territory(obs: dict[str, Any]) -> str:
    total = int(obs.get("total", 0) or 0)
    n = int(obs.get("open_incidents", 0) or 0)
    missing = len(obs.get("missing_gps", []) or [])
    label, place, stock_n = _period_meta(obs)
    if label:
        text = (
            f"{total} {_plural(total, 'école géolocalisée', 'écoles géolocalisées')}, "
            f"{n} {_plural(n, 'incident signalé', 'incidents signalés')} {label}{place}."
            f"{_period_stock(stock_n)} La carte interactive est ci-dessous."
        )
        if missing:
            text += f" ({missing} {_plural(missing, 'école sans', 'écoles sans')} GPS.)"
        return text
    text = (
        f"{total} {_plural(total, 'école géolocalisée', 'écoles géolocalisées')}, "
        f"{n} {_plural(n, 'incident ouvert', 'incidents ouverts')}. "
        "La carte interactive est ci-dessous."
    )
    if missing:
        text += f" ({missing} {_plural(missing, 'école sans', 'écoles sans')} GPS.)"
    return text


def _summarize_briefing(obs: dict[str, Any]) -> str:
    slides = int(obs.get("total", 0) or 0)
    value = (obs.get("slides", [{}])[0].get("stats", [{}])[0].get("value", "?"))
    label, _place, stock_n = _period_meta(obs)
    if label:
        return (
            f"Briefing prêt {label} : {slides} slides "
            f"({value} incidents signalés {label}).{_period_stock(stock_n)} "
            "La présentation est dans la carte ci-dessous."
        )
    return (
        f"Briefing prêt : {slides} slides "
        f"({value} "
        "incidents ouverts). La présentation est dans la carte ci-dessous."
    )


FALLBACK_SUMMARIES = {
    "list_maintenance_logs": _summarize_maintenance_logs,
    "list_incidents": _summarize_incidents,
    "summarize_district": _summarize_district,
    "repair_trends": _summarize_trends,
    "rank_schools_by_need": _summarize_ranking,
    "analyze_school": _summarize_analysis,
    "explain_incident": _summarize_incident,
    "prepare_report": _summarize_report,
    "prepare_incident": _summarize_proposal,
    "prepare_maintenance_log": _summarize_proposal,
    "territory_overview": _summarize_territory,
    "build_briefing": _summarize_briefing,
}

_STARTER_RE = re.compile(
    r"\b(bonjour|salut|coucou|hello|bonsoir|aide|aider|help|démarrer|commencer|"
    r"que (peux|sais)-tu|tu sais faire)\b", re.IGNORECASE)

def _intervention_answer(obs: dict[str, Any], lang: str) -> str:
    """Réponse de préparation d'intervention (fonction pure, FR/EN)."""
    fields = obs.get("fields") or {}
    label = fields.get("incident_label") or ("l'intervention" if lang != "en"
                                             else "the intervention")
    budget = fields.get("budget_xaf")
    try:
        budget_txt = f"{int(float(budget)):,}".replace(",", " ") if budget is not None else None
    except (TypeError, ValueError):
        budget_txt = None
    if lang == "en":
        head = f"Intervention \u00ab {label} \u00bb"
        if fields.get("school_name"):
            head += f" at {fields['school_name']}"
        if fields.get("date_label"):
            head += f", scheduled {fields['date_label']}"
        if budget_txt:
            head += f", budget {budget_txt} XAF"
        if fields.get("team"):
            head += f", team {fields['team']}"
        parts = [head + "."]
    else:
        head = f"Intervention \u00ab {label} \u00bb"
        if fields.get("school_name"):
            head += f" \u00e0 {fields['school_name']}"
        if fields.get("date_label"):
            head += f", pr\u00e9vue le {fields['date_label']}"
        if budget_txt:
            head += f", budget {budget_txt} XAF"
        if fields.get("team"):
            head += f", \u00e9quipe {fields['team']}"
        parts = [head + "."]
    verdict = obs.get("verdict") or {}
    if verdict.get("recommendation_label"):
        ratio = (verdict.get("figures") or {}).get("repair_ratio_percent")
        ratio_txt = f" (ratio {ratio} %)." if ratio else "."
        if lang == "en":
            parts.append(f"Parts verdict: {verdict['recommendation_label']}{ratio_txt}")
        else:
            parts.append(f"Verdict pi\u00e8ces : {verdict['recommendation_label']}{ratio_txt}")
    if obs.get("budget_verdict"):
        parts.append(str(obs["budget_verdict"]))
    kit = obs.get("repair_kit") or {}
    spares = [s for s in (kit.get("spare_parts_needed") or []) if s][:4]
    if spares:
        if lang == "en":
            parts.append(f"Kit: {', '.join(spares)}"
                         + (f" — estimated {kit.get('estimated_intervention_time')}."
                            if kit.get("estimated_intervention_time") else "."))
        else:
            parts.append(f"Kit : {', '.join(spares)}"
                         + (f" — dur\u00e9e estim\u00e9e {kit.get('estimated_intervention_time')}."
                            if kit.get("estimated_intervention_time") else "."))
    questions = [q for q in (obs.get("questions") or []) if q]
    if questions:
        parts.append(" ".join(questions))
    return " ".join(parts)


STARTER_CHIPS = ["Résumer mon district",
                 "Quelles écoles ont le plus besoin d'aide ?",
                 "Voir la carte du territoire"]
CATEGORY_CHIPS = ["Point d'eau", "Latrines", "Lavage des mains", "Évacuation"]
URGENCY_CHIPS = ["Basse", "Moyenne", "Haute", "Critique"]


def _follow_ups(message: str, executed: list[tuple[str, dict[str, Any]]],
                context: dict[str, Any],
                scope: dict[str, Any] | None = None) -> list[str]:
    """Relances cliquables : démarrage, ou réponses rapides au premier slot manquant.

    Périmètre école unique : relances cantonnées à cette école (ni district,
    ni territoire, ni autres écoles). scope=None = comportement historique.
    """
    school = _single_school_scope(scope)
    if not executed:
        if not _STARTER_RE.search(message or ""):
            return []
        if school is not None:
            return [f"Tendances de {school} ?",
                    f"Faut-il réparer à {school} ?",
                    f"Urgences à {school} ?"]
        return list(STARTER_CHIPS)
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
        if school is not None:
            return [school]
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
    scope: dict[str, Any] | None = None,
    time_window: dict[str, Any] | None = None,
) -> list[AgentCard]:
    """Force la carte si le texte l'annonce sans qu'elle soit construite.

    Seulement quand des écoles avec lat/lng existent (observations, puis
    contexte). N'ajoute jamais de doublon. Fonction pure (nouvelle liste).
    Périmètre école unique : jamais de carte territoire imposée.
    Période exprimée : titre suffixé (données déjà restreintes en amont).
    """
    cards = list(cards or [])
    if _single_school_scope(scope) is not None:
        return cards
    if not announces_map(answer):
        return cards
    if any("map" in (card.type or "") for card in cards):
        return cards
    points = collect_map_points(executed, context)
    if not points:
        return cards
    card = build_forced_map_card(points)
    label = time_window_label(time_window, "fr")
    if label:
        card.title = f"{card.title} ({label})"
    cards.append(card)
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


def _photo_card(photo: Any) -> AgentCard | None:
    """Carte photo_analysis depuis une analyse (None sans photo)."""
    if photo is None:
        return None
    obs = photo.model_dump() if hasattr(photo, "model_dump") else dict(photo)
    if obs.get("vision_unavailable"):
        title = "Analyse photo — vision indisponible"
    else:
        title = f"Analyse photo — {obs.get('infrastructure_detected', '?')}"
    return AgentCard(type="photo_analysis", title=title, data=obs)


#: Préparation d'intervention à venir (texte normalisé _norm, FR + EN) :
#: verbe de planification + objet réparation. Exclusions strictes :
#: documents (briefing/dossier/rapport/affiche), nouvelle panne à signaler,
#: avancement à consigner. Sans ces gardes, le modèle appelle analyze_school
#: (carte large) au lieu du dossier ciblé.
_INTERVENTION_PREP_VERB_RE = re.compile(
    r"\b(prepar\w*|planifi\w*|organis\w*|schedul\w*|plan\w*)\b")
_INTERVENTION_PREP_OBJ_RE = re.compile(
    r"\b(intervention\w*|reparation\w*|repare\w*|mission\w*|depannage\w*"
    r"|travaux\w*|repair\w*|fix\w*)\b")
_INTERVENTION_PREP_EXCLUDE_RE = re.compile(
    r"briefing|dossier|rapport|affiche|poster|deck|presentation|diaporama"
    r"|nouvelle?\s+panne|nouveau\s+signalement|signaler|avancement|consign"
    r"|journalis|suivi\s+de\s+chantier|suivi\s+du\s+chantier")

#: Fragments retirés pour isoler l'indice incident (« réparer la pompe
#: principale » -> « pompe principale »).
_INTERVENTION_STRIP_RES = (
    re.compile(r"\b(prepar\w*|planifi\w*|organis\w*|repare\w*|repair\w*"
               r"|fix\w*|schedul\w*|plan\w*)\b"),
    re.compile(r"\b(intervention\w*|reparation\w*|mission\w*|depannage\w*"
               r"|travaux\w*|chantier\w*|equipe\w*)\b"),
    re.compile(r"\b(demain|lendemain|apres[\s\-]*demain|aujourd[\s\-]*hui)\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(r"\d[\d\s\u00a0.,]*\s*(?:xaf|fcfa|francs?|k\b)"),
    re.compile(r"budget(?:\s+de)?\s+\d[\d\s\u00a0.,]*"),
    re.compile(r"\ble\s+\d{1,2}\b"),
    # Mot « budget » orphelin (montant déjà retiré par les motifs
    # ci-dessus) : il polluerait l'indice incident (« robinet budget »).
    re.compile(r"\bbudgets?\b"),
)
_INTERVENTION_STOPWORDS = frozenset({
    "pour", "avec", "une", "les", "des", "sur", "dans", "aux", "ces",
    "ses", "mon", "ton", "son", "notre", "votre", "leur", "est", "sont",
    "fait", "faire", "faut", "doit", "doivent", "peut",
    "the", "for", "with", "our", "your",
})


def is_intervention_prep_request(message: str) -> bool:
    """Demande de PLANIFICATION d'intervention future ? (fonction pure).

    Verbe + objet réparation, hors documents / nouveau signalement /
    consignation. « Prépare une intervention pour demain... » -> True ;
    « Prépare un briefing », « signale une nouvelle panne » -> False.
    """
    normed = _norm(message or "")
    if not normed.strip():
        return False
    if _INTERVENTION_PREP_EXCLUDE_RE.search(normed):
        return False
    # « Prépare ... » + objet : le verbe seul ne suffit pas (« prépare le
    # dossier » est exclu plus haut, « prépare quoi ? » reste au modèle).
    if not _INTERVENTION_PREP_VERB_RE.search(normed):
        return False
    return _INTERVENTION_PREP_OBJ_RE.search(normed) is not None


#: Dossier décideur (texte normalisé _norm, FR + EN) : demande explicite
#: de dossier/affiche/rapport décideur. « rapport » seul est ambigu (liste
#: de signalements, tendances) : il exige un cadrage décideur/complet.
_DOSSIER_STRONG_RE = re.compile(
    r"dossier|affiche|poster|deck|diaporama|presentation")
_DOSSIER_REPORT_SCOPE_RE = re.compile(
    r"decideur|complet|global|synthese|ecole|district|ville")
_DOSSIER_EXCLUDE_RE = re.compile(
    r"briefing|signal|panne|suivi|suivre|journal|avancement|tendance|incident")


def is_dossier_request(message: str) -> bool:
    """Demande explicite de dossier décideur ? (fonction pure).

    « Prépare le dossier de Ngok », « génère une affiche », « rapport
    décideur » -> True ; « prépare un briefing », « signale une panne »,
    « donne les rapports » (liste) -> False.
    """
    normed = _norm(message or "")
    if not normed.strip():
        return False
    if _DOSSIER_EXCLUDE_RE.search(normed):
        return False
    if _DOSSIER_STRONG_RE.search(normed):
        return True
    return "rapport" in normed and _DOSSIER_REPORT_SCOPE_RE.search(normed) is not None


def _intervention_hint(message: str, context: dict[str, Any] | None) -> str:
    """Indice incident isolé du message (fonction pure).

    La référence WASH (si présente) est préservée intacte en tête : la
    tokenisation l'exploserait sinon (« wash 2026 pump », inmatchable).
    """
    text = _norm(message or "")
    for pattern in _INTERVENTION_STRIP_RES:
        text = pattern.sub(" ", text)
    try:
        schools, districts = known_places(context or {})
    except (AttributeError, TypeError, ValueError):
        schools, districts = [], []
    for place in (*schools, *districts):
        if place and len(place) >= 3:
            text = text.replace(_norm(place), " ")
    tokens = [t for t in re.findall(r"[a-z0-9]+", text)
              if len(t) >= 3 and t not in _INTERVENTION_STOPWORDS]
    hint = " ".join(tokens)
    ref_match = WASH_REF_RE.search(message or "")
    if ref_match and ref_match.group(0).lower() not in hint:
        hint = f"{ref_match.group(0).lower()} {hint}".strip()
    return hint


class AgentLoop:
    """Boucle agentique réelle : le LLM choisit ses outils, Python les exécute."""

    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def chat(self, req: AgentChatRequest, today: Any = None) -> AgentChatResponse:
        """Un tour de conversation (today injectable : date|datetime|str ISO, tests).

        today=None (défaut, prod) : la période « aujourd'hui » suit la date
        du serveur (server_today, UTC documenté).
        """
        context = req.context.model_dump()
        # Mémo conversation : un lieu seul (« Mvila ») reprend la question
        # précédente en attente via l'historique (sans état serveur).
        memo_message = resolve_bare_place_followup(req.message, req.history, context)
        if memo_message != req.message:
            req = req.model_copy(update={"message": memo_message})
        # Mémo rapport : un livrable sans lieu (« Prépare un rapport »)
        # reprend le sujet discuté (un seul lieu récent) au lieu de couvrir
        # tout le territoire. Sans état serveur : que l'historique.
        report_message = resolve_report_followup(req.message, req.history, context)
        if report_message != req.message:
            req = req.model_copy(update={"message": report_message})
        # Mémo prépa : une planification sans lieu reprend le sujet discuté
        # (même helper, même règle d'ambiguïté que le mémo rapport).
        prep_message = resolve_prep_followup(req.message, req.history, context)
        if prep_message != req.message:
            req = req.model_copy(update={"message": prep_message})
        # Slot prépa : réponse courte (« Confier à… », « demain ») à un
        # dossier en interrogatoire -> requête complète reconstituée.
        slot_message = resolve_prep_slot_followup(
            req.message, req.history, context,
            today=_normalize_today(today) if today is not None else None)
        if slot_message != req.message:
            req = req.model_copy(update={"message": slot_message})
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
        scope_info = detect_scope(req.message, context)
        # Périmètre PHOTO : image + question sur l'image seule -> aucun outil,
        # carte photo_analysis unique, synthèse = commentaire de la photo.
        photo_only = is_photo_only_scope(
            req.message, context, photo_b64 is not None)
        if photo_only:
            scope_info = {"scope": "photo", "school": None,
                          "schools": [], "district": None}
        # Clarification guidée : périmètre exigé mais non nommé (« Compare un
        # district ? ») -> question + choix cliquables du contexte réel.
        # Jamais en périmètre photo (aucun lieu à demander).
        clarify_kind = (None if photo_only
                        else needs_clarification(req.message, context, scope_info))
        # Périmètre TEMPOREL : période exprimée -> les outils s'exécutent sur
        # le contexte restreint (incidents/logs de la période, bornes
        # incluses) ; le contexte original sert aux totaux (« N ouverts au
        # total ») et au lieu. Jamais en périmètre photo (commentaire seul).
        time_window = (None if photo_only
                       else parse_time_window(req.message, today))
        if time_window is not None and not time_window.get("preset"):
            time_window = None
        period_total = 0
        period_count = 0
        period_place = ""
        exec_context = context
        period: dict[str, Any] | None = None
        if time_window is not None:
            period_total = len(open_incidents_in_scope(context, scope_info))
            period_count = len(open_incidents_in_window(
                context, time_window, scope_info))
            period_place = period_place_suffix(scope_info, "fr")
            exec_context = scope_context_to_window(context, time_window)
            period = {"window": time_window, "total": period_total,
                      "place": period_place}
        # DOSSIER DÉCIDEUR : demande explicite + lieu résolu -> génération
        # déterministe (rapport pur + affiche cloud), sans boucle LLM : les
        # chiffres sont garantis issus du contexte, jamais inventés.
        if (not photo_only and clarify_kind is None
                and is_dossier_request(req.message)):
            dossier = await self._run_dossier_branch(
                req, context, scope_info, lang)
            if dossier is not None:
                return dossier
        # PRÉPARATION d'intervention à venir : dossier ciblé déterministe
        # (incident/date/budget/équipe + kit + verdict), sans boucle LLM.
        # Évite la carte large « Analyse école » sur une demande précise.
        prep_request = (not photo_only and clarify_kind is None
                        and is_intervention_prep_request(req.message))
        if prep_request:
            prepared = await self._run_intervention_prep(
                req, context, scope_info, lang, today)
            if prepared is not None:
                return prepared
        # Une planification qui rend la main (erreur plugin) ne doit JAMAIS
        # retomber sur un listing : les outils prepare_* restent visibles.
        intent = "create" if prep_request else route_intent(req.message)
        active_tools = compact_tools(tools_for_intent(intent, scope_info), self.llm.model)
        messages: list[dict[str, Any]] = [
            {"role": "system",
             "content": _build_system_prompt(lang, scope_info, time_window)}]
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
                blocked = _blocked_by_scope(name, arguments, scope_info)
                if blocked is not None:
                    seen.add(key)
                    messages.append(self.llm.format_tool_result(name, {"note": blocked}, call.get("id")))
                    continue
                if key in seen:
                    messages.append(self.llm.format_tool_result(name, {"note": REPEAT_NUDGE}, call.get("id")))
                    continue
                seen.add(key)
                fresh = True
                observation = self._execute_tool(name, arguments, exec_context)
                if period is not None:
                    _annotate_period_obs(name, observation, time_window,
                                         period_total, period_place)
                executed.append((name, observation))
                messages.append(self.llm.format_tool_result(name, _compact_observation(name, observation), call.get("id")))
            if not fresh:
                if nudged:
                    break
                nudged = True
        else:
            answer = self._fallback_answer(executed, context, photo, scope=scope_info)

        over_budget = time.monotonic() - started > RUN_BUDGET_S
        if (not photo_only and not executed and answer.strip()
                and self._looks_like_data_question(req.message)
                and not over_budget):
            answer = await self._force_tool_pass(
                messages, exec_context, executed, active_tools, budget,
                photo=photo, scope=scope_info, period=period)

        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            answer = self._fallback_answer(executed, context, photo, scope=scope_info)

        if (not photo_only and answer.strip() and _claims_absence(answer)
                and not _has_read_tool(executed)):
            if not over_budget and used_iterations < MAX_ITERATIONS:
                answer = await self._absence_correction_pass(
                    messages, exec_context, executed, seen, active_tools,
                    budget, nudge=_absence_nudge(scope_info), photo=photo,
                    scope=scope_info, period=period)
            else:
                answer = UNVERIFIED_HONEST_ANSWER

        if (not photo_only and answer.strip() and _cites_reference(answer)
                and _claims_absence(answer) and _has_empty_list_obs(executed)):
            if not over_budget and used_iterations < MAX_ITERATIONS:
                answer = await self._absence_correction_pass(
                    messages, exec_context, executed, seen, active_tools,
                    budget, nudge=CONTRADICTION_CORRECTION_NUDGE, photo=photo,
                    scope=scope_info, period=period)
            else:
                answer = self._fallback_answer(executed, context, photo, scope=scope_info)

        # Réparation déterministe AVANT envoi : puces vides remplies depuis
        # les observations, placeholders [...] supprimés (fonctions pures).
        answer = repair_final_answer(answer, executed)
        # Discipline de périmètre : purge des phrases citant une autre école.
        answer = strip_other_school_mentions(answer, scope_info, context)
        # Périmètre TEMPOREL vide : une liste d'incidents a été lue sur la
        # période (sans création en cours) et le compte période est nul ->
        # le message canonique (absence datée + stock général) remplace
        # toute liste générale déguisée ou vide sec. Jamais en photo.
        empty_period = (
            time_window is not None
            and not _has_prepare_exec(executed)
            and _has_successful_period_list(executed)
            and period_count == 0
        )
        if empty_period:
            answer = format_empty_period_message(
                time_window, scope_info, period_total, lang)
        if not answer.strip():
            answer = self._fallback_answer(executed, context, photo, scope=scope_info)
        # Clarification guidée : panorama court + LA question en une phrase.
        if clarify_kind is not None:
            answer = _with_clarify_question(answer, clarify_kind, lang)
        cards = self._build_cards(executed, context, photo=photo,
                                  scope=scope_info, time_window=time_window)
        # Annonce-carte sans carte construite : force la carte si des écoles
        # avec lat/lng existent (petit LLM : CAS "voici la carte..." seul).
        # Jamais en périmètre photo (photo_analysis unique).
        cards = (cards if photo_only else maybe_force_map_card(
            answer, executed, cards, context,
            scope=scope_info, time_window=time_window))
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
        follow_ups = _follow_ups(req.message, executed, context, scope_info)
        if clarify_kind is not None:
            # Choix cliquables du contexte réel ; sans lieu connu, repli sur
            # les relances actuelles (puis démarrage) : jamais vide, jamais
            # d'erreur.
            follow_ups = (clarify_follow_ups(clarify_kind, req.message, context, lang)
                          or follow_ups or list(STARTER_CHIPS))
        if empty_period:
            chip = EMPTY_PERIOD_FOLLOW_UPS.get(
                lang, EMPTY_PERIOD_FOLLOW_UPS["fr"])
            if chip not in follow_ups:
                follow_ups = [chip, *follow_ups]
        return AgentChatResponse(
            answer=answer.strip(),
            tools_executed=[name for name, _ in executed],
            cards=cards,
            model_used=self.llm.model,
            follow_ups=follow_ups,
        )

    async def _run_dossier_branch(
            self, req: AgentChatRequest, context: dict[str, Any],
            scope_info: dict[str, Any] | None, lang: str) -> AgentChatResponse | None:
        """Dossier décideur (rapport pur + affiche, sans boucle LLM).

        Retourne None sans lieu résolu (école ou district) : le flux
        normal demande alors « pour quelle école ? ».
        """
        from .tools.dossier_decideur import run_dossier
        scope = scope_info or {}
        school = scope.get("school") if scope.get("scope") == "school" else None
        district = scope.get("district")
        if school:
            scope_type, scope_name = "school", school
        elif district:
            scope_type, scope_name = "district", district
        else:
            return None
        scope_id = None
        if school:
            for row in context.get("schools", []) or []:
                if isinstance(row, dict) and str(row.get("school_name") or "") == school:
                    scope_id = row.get("school_id")
                    break
        run = await run_dossier(self.llm, scope_type, scope_name, context, scope_id)
        cards = run.get("cards", [])
        n_sections = len((run.get("report") or {}).get("sections", []))
        has_poster = any(c.type == "poster" for c in cards)
        if (lang or "fr") == "en":
            answer = (f"Brief pack \u00ab {scope_name} \u00bb ready: report "
                      f"({n_sections} sections)")
            answer += " + poster." if has_poster else "."
            if run.get("poster_error"):
                answer += f" {run['poster_error']}"
        else:
            answer = (f"Dossier \u00ab {scope_name} \u00bb pr\u00eat : rapport "
                      f"({n_sections} sections)")
            answer += " + affiche." if has_poster else "."
            if run.get("poster_error"):
                answer += f" {run['poster_error']}"
        follow_ups = _follow_ups(
            req.message, [("dossier_decideur", {"cards": len(cards)})],
            context, scope)
        briefing_chip = ("Prepare a briefing" if (lang or "fr") == "en"
                         else "Pr\u00e9parer un briefing")
        if briefing_chip not in follow_ups:
            follow_ups.append(briefing_chip)
        return AgentChatResponse(
            answer=answer,
            tools_executed=["dossier_decideur"],
            cards=cards,
            model_used=self.llm.model,
            follow_ups=follow_ups,
        )

    async def _run_intervention_prep(
            self, req: AgentChatRequest, context: dict[str, Any],
            scope_info: dict[str, Any] | None, lang: str,
            today: Any = None) -> AgentChatResponse | None:
        """Dossier de préparation d'intervention (déterministe, sans LLM).

        Ne rend la main (None) que sur erreur plugin : les cas métier
        (école manquante, incident non résolu) retournent une réponse
        guidée déterministe — une planification ne retombe JAMAIS sur un
        listing du flux normal.
        """
        from .tools.prepare_intervention import CARD_BUILDERS
        from .tools.prepare_intervention import execute as prep_execute
        scope = scope_info or {}
        school = scope.get("school") if scope.get("scope") == "school" else None
        if today is None:
            today_iso = None
        elif isinstance(today, str):
            today_iso = today[:10]
        elif isinstance(today, datetime):
            today_iso = today.date().isoformat()
        elif isinstance(today, date):
            today_iso = today.isoformat()
        else:
            today_iso = None
        obs = prep_execute({
            "incident": _intervention_hint(req.message, context),
            "date_text": req.message,
            "budget": req.message,
            "school": school or "",
            "team": _match_team_name(req.message, context) or "",
            "today": today_iso,
        }, context)
        if not isinstance(obs, dict) or obs.get("error"):
            return None
        fields = obs.get("fields") or {}
        if fields.get("incident_id") is None and not school \
                and not obs.get("candidates"):
            # Ni école ni incident : question guidée + choix écoles.
            return self._prep_missing_school_response(
                req, context, obs, lang, scope)
        incident = None
        for row in context.get("incidents", []) or []:
            if isinstance(row, dict) and row.get("id") == fields.get("incident_id"):
                incident = row
                break
        if incident is not None:
            obs["repair_kit"] = await self._repair_kit_for(
                incident, fields.get("school_name"))
        cards: list[AgentCard] = []
        if obs.get("candidates"):
            cards.append(AgentCard(
                type="incident_picker",
                title="Quel incident réparer ?",
                data={"candidates": obs["candidates"][:5],
                      "hint": obs.get("hint_unmatched"),
                      "action": "prepare_intervention"},
            ))
        elif fields.get("incident_id") is None and school:
            # École connue, incident non résolu (synonymes type « robinet »
            # vs « tap ») : picker des incidents ouverts de l'école.
            open_here = [
                {key: row.get(key) for key in (
                    "id", "reference_code", "title", "school_name",
                    "district", "category", "urgency", "status",
                    "affected_students", "priority_score", "reported_at")}
                for row in context.get("incidents", []) or []
                if isinstance(row, dict)
                and str(row.get("status") or "").lower() not in ("resolved", "closed")
                and _school_arg_matches(str(row.get("school_name") or ""), school)
            ]
            if open_here:
                cards.append(AgentCard(
                    type="incident_picker",
                    title=f"Quel incident réparer à {short_school_name(school)} ?",
                    data={"candidates": open_here[:5],
                          "hint": obs.get("hint_unmatched"),
                          "action": "prepare_intervention"},
                ))
        builder = CARD_BUILDERS.get("intervention_prep")
        card = builder(obs) if builder is not None else None
        if card is not None:
            cards.append(card)
        follow_ups = _follow_ups(
            req.message, [("prepare_intervention", obs)], context, scope)
        for choice in (obs.get("team_choices") or [])[:3]:
            chip = f"Confier à {choice}"
            if chip not in follow_ups:
                follow_ups.insert(0, chip)
        return AgentChatResponse(
            answer=_intervention_answer(obs, lang or "fr"),
            tools_executed=["prepare_intervention"],
            cards=cards,
            model_used=self.llm.model,
            follow_ups=follow_ups,
        )

    def _prep_missing_school_response(
            self, req: AgentChatRequest, context: dict[str, Any],
            obs: dict[str, Any], lang: str,
            scope: dict[str, Any]) -> AgentChatResponse:
        """Prépa sans école ni incident : question + choix écoles, jamais None."""
        from .tools.prepare_intervention import CARD_BUILDERS
        cards: list[AgentCard] = []
        builder = CARD_BUILDERS.get("intervention_prep")
        card = builder(obs) if builder is not None else None
        if card is not None:
            cards.append(card)
        use_lang = lang or "fr"
        answer = _with_clarify_question(
            _intervention_answer(obs, use_lang), "school", use_lang)
        follow_ups = (clarify_follow_ups(
            "school", req.message, context, use_lang)
            or _follow_ups(req.message, [("prepare_intervention", obs)],
                           context, scope))
        return AgentChatResponse(
            answer=answer,
            tools_executed=["prepare_intervention"],
            cards=cards,
            model_used=self.llm.model,
            follow_ups=follow_ups,
        )

    async def _repair_kit_for(self, incident: dict[str, Any],
                              school_name: Any) -> dict[str, Any]:
        """Kit réparation LLM, repli hors ligne garanti (jamais d'exception)."""
        from .repair_advisor import (
            DEFAULT_COST_TIER,
            DEFAULT_INTERVENTION_TIME,
            FALLBACK_REQUIRED_TOOLS,
            FALLBACK_SAFETY_MEASURES,
            FALLBACK_SPARE_PARTS,
            RepairAdvisor,
        )
        try:
            summary = str(incident.get("title") or "panne")
            if school_name:
                summary += f" — {school_name}"
            plan = await RepairAdvisor(self.llm).generate_plan(
                RepairPlanRequest(
                    incident_summary=summary,
                    infrastructure_type=str(incident.get("category") or "water_point"),
                    issue_type=str(incident.get("issue_type") or "total_breakdown"),
                    urgency_level=str(incident.get("urgency") or "medium")))
            data = plan.model_dump()
            data["kit_source"] = "llm"
            return data
        except Exception:
            return {
                "required_tools": list(FALLBACK_REQUIRED_TOOLS),
                "spare_parts_needed": list(FALLBACK_SPARE_PARTS),
                "estimated_intervention_time": DEFAULT_INTERVENTION_TIME,
                "immediate_safety_measures": list(FALLBACK_SAFETY_MEASURES),
                "estimated_cost_tier": DEFAULT_COST_TIER,
                "kit_source": "fallback",
            }

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
        scope: dict[str, Any] | None = None,
        period: dict[str, Any] | None = None,
    ) -> str:
        """Dernier recadrage : réponse directe à une question de données.

        On exige un appel d'outil immédiat. S'il obéit, on le laisse conclure
        sur les observations ; sinon, réponse honnête (jamais d'invention).
        Chaque appel LLM consomme le budget partagé (MAX_LLM_CALLS).
        Périmètre école unique : recadrage et exécutions cantonnés à l'école.
        Période exprimée (period) : observations tamponnées (période + stock).
        """
        tools = AGENT_TOOLS if tools is None else tools
        budget = {"llm_calls": 0} if budget is None else budget
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo, scope=scope)
        messages.append({"role": "user", "content": _no_tool_nudge(scope)})
        budget["llm_calls"] += 1
        retry = await self.llm.chat(messages, tools)
        messages.append(retry["raw"])
        for call in retry.get("tool_calls", []):
            name = call.get("name", "")
            arguments = call.get("arguments", {}) or {}
            blocked = _blocked_by_scope(name, arguments, scope)
            if blocked is not None:
                messages.append(self.llm.format_tool_result(name, {"note": blocked}, call.get("id")))
                continue
            observation = self._execute_tool(name, arguments, context)
            if period is not None:
                _annotate_period_obs(name, observation, period.get("window"),
                                     period.get("total", 0), period.get("place", ""))
            executed.append((name, observation))
            messages.append(self.llm.format_tool_result(name, _compact_observation(name, observation), call.get("id")))
        if not executed:
            return self._fallback_answer(executed, context, photo, scope=scope)
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo, scope=scope)
        budget["llm_calls"] += 1
        final = await self.llm.chat(messages, tools)
        messages.append(final["raw"])
        answer = final.get("content", "")
        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            return self._fallback_answer(executed, context, photo, scope=scope)
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
        scope: dict[str, Any] | None = None,
        period: dict[str, Any] | None = None,
    ) -> str:
        """Recadrage anti-hallucination : absence affirmée sans lecture
        (ou contradiction référence + absence, via un nudge adapté).

        Une seule tentative (bornée par MAX_ITERATIONS à l'appel) : on exige un
        outil de lecture puis on conclut ; si le modèle persiste sans observer,
        réponse honnête (jamais d'invention).
        Chaque appel LLM consomme le budget partagé (MAX_LLM_CALLS).
        Périmètre école unique : exécutions cantonnées à l'école.
        Période exprimée (period) : observations tamponnées (période + stock).
        """
        budget = {"llm_calls": 0} if budget is None else budget
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo, scope=scope)
        messages.append({"role": "user", "content": nudge})
        budget["llm_calls"] += 1
        retry = await self.llm.chat(messages, tools)
        messages.append(retry["raw"])
        for call in retry.get("tool_calls", []):
            name = call.get("name", "")
            arguments = call.get("arguments", {}) or {}
            key = (name, json.dumps(arguments, sort_keys=True, default=str))
            blocked = _blocked_by_scope(name, arguments, scope)
            if blocked is not None:
                seen.add(key)
                messages.append(self.llm.format_tool_result(
                    name, {"note": blocked}, call.get("id")))
                continue
            if key in seen:
                messages.append(self.llm.format_tool_result(
                    name, {"note": REPEAT_NUDGE}, call.get("id")))
                continue
            seen.add(key)
            observation = self._execute_tool(name, arguments, context)
            if period is not None:
                _annotate_period_obs(name, observation, period.get("window"),
                                     period.get("total", 0), period.get("place", ""))
            executed.append((name, observation))
            messages.append(self.llm.format_tool_result(name, _compact_observation(name, observation), call.get("id")))
        if not _has_read_tool(executed):
            return UNVERIFIED_HONEST_ANSWER
        if budget["llm_calls"] >= MAX_LLM_CALLS:
            return self._fallback_answer(executed, context, photo, scope=scope)
        budget["llm_calls"] += 1
        final = await self.llm.chat(messages, tools)
        messages.append(final["raw"])
        answer = final.get("content", "")
        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            return self._fallback_answer(executed, context, photo, scope=scope)
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
        scope: dict[str, Any] | None = None,
    ) -> str:
        """Résumé humain déterministe quand le modèle ne conclut pas.

        Prend la dernière observation réussie et la raconte en une phrase
        chiffrée qui pointe vers la carte (pas de jargon robotique).
        Sans observation d'outil mais avec photo : le résumé photo
        déterministe (le LLM commente, ne devine pas — y compris ici).
        Périmètre école unique : relances cantonnées à cette école (ni
        district, ni territoire) + purge des mentions d'autres écoles.
        """
        school = _single_school_scope(scope)
        for name, observation in reversed(executed):
            if "error" in observation:
                continue
            summarizer = FALLBACK_SUMMARIES.get(name)
            if summarizer:
                try:
                    text = summarizer(observation)
                except (TypeError, ValueError, KeyError, IndexError, AttributeError):
                    continue
                return self._scoped_fallback_text(text, school, scope, context)
            if school is not None:
                return (
                    f"Bonne nouvelle, j'ai trouvé vos données pour {school} : "
                    "le détail est dans la carte juste en dessous. Pour aller "
                    "plus loin, demandez par exemple : "
                    f"« Tendances de {school} ? » ou "
                    f"« Faut-il réparer à {school} ? »."
                )
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
            text = (
                f"{summarize_photo_analysis(photo)} "
                "Le détail est dans la carte ci-dessous."
            )
            return self._scoped_fallback_text(text, school, scope, context)
        if school is not None:
            return (
                f"Je n'ai pas pu récupérer de données pour {school}. "
                "Précisez ce que vous voulez savoir — par exemple : "
                f"« Tendances de {school} ? » ou "
                f"« Faut-il réparer à {school} ? »."
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

    @staticmethod
    def _scoped_fallback_text(text: str, school: str | None,
                              scope: dict[str, Any] | None,
                              context: dict[str, Any] | None) -> str:
        """Purge les mentions d'autres écoles, avec repli école honnête."""
        if school is None:
            return text
        scrubbed = strip_other_school_mentions(text, scope, context)
        if scrubbed.strip():
            return scrubbed
        return (
            f"Je n'ai pas de détail supplémentaire pour {school}. "
            f"Demandez par exemple : « Tendances de {school} ? » ou "
            f"« Faut-il réparer à {school} ? »."
        )

    def _build_cards(self, executed: list[tuple[str, dict[str, Any]]],
                     context: dict[str, Any] | None = None,
                     photo: ImageAnalysisResponse | dict[str, Any] | None = None,
                     scope: dict[str, Any] | None = None,
                     time_window: dict[str, Any] | None = None,
                     ) -> list[AgentCard]:
        """Cartes UI depuis les observations (périmètre école unique filtré).

        En périmètre école unique : seules les cartes de cette école sont
        émises (analyse, tendances, calendrier, détail/picker de SES incidents,
        journal filtré, guidage cantonné) ; les cartes district/territoire/
        comparaison globale sont supprimées. Périmètre photo : carte
        photo_analysis UNIQUEMENT. scope=None = historique. Période exprimée
        (time_window) : les cartes de données sont suffixées de la période
        (leurs données sont déjà restreintes en amont, jamais de mélange).
        """
        if _is_photo_scope(scope):
            card = _photo_card(photo)
            return [card] if card is not None else []
        period_label = time_window_label(time_window, "fr")
        school = _single_school_scope(scope)
        other_schools: list[str] = []
        if school is not None:
            try:
                known, _ = known_places(context or {})
            except (AttributeError, TypeError, ValueError):
                known = []
            own = _norm(school)
            other_schools = [s for s in known if _norm(s) != own]
        cards: list[AgentCard] = []
        photo_card = _photo_card(photo)
        if photo_card is not None:
            cards.append(photo_card)
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
                    name, observation, district_examples=district_examples,
                    scope_school=school)
                if guide is not None:
                    cards.append(guide)
                continue
            if school is not None and name in DISTRICT_SCOPE_TOOLS \
                    and name not in SCHOOL_TOPIC_TOOLS:
                continue
            if school is not None and name in SCHOOL_TOPIC_TOOLS \
                    and not _school_arg_matches(observation.get("topic"), school):
                continue
            if name == "analyze_school":
                if school is not None and not _obs_school_matches(observation, school, other_schools):
                    continue
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
                if school is not None and not _obs_school_matches(observation, school, other_schools):
                    continue
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
                    candidates = observation["candidates"]
                    if school is not None:
                        candidates = [c for c in candidates
                                      if _obs_school_matches(c, school, other_schools)]
                        if not candidates:
                            continue
                    cards.append(AgentCard(
                        type="incident_picker",
                        title="Quel incident ?",
                        data={"candidates": candidates,
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
                if school is not None and not _obs_school_matches(observation, school, other_schools):
                    continue
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
                if observation.get("budget_compare") and school is None:
                    cards.append(AgentCard(
                        type="budget_compare",
                        title="Comparaison des budgets réparations",
                        data=observation["budget_compare"],
                    ))
            elif name == "list_maintenance_logs":
                data = observation
                if school is not None:
                    items = [i for i in (observation.get("items") or [])
                             if _obs_school_matches(i, school, other_schools)]
                    removed = len(observation.get("items") or []) - len(items)
                    if removed and not items:
                        continue
                    if removed:
                        try:
                            total = max(0, int(observation.get("total", len(items)) or 0) - removed)
                        except (TypeError, ValueError):
                            total = len(items)
                        data = {**observation, "items": items, "total": total}
                cards.append(AgentCard(
                    type="maintenance_logs",
                    title=f"Interventions journalisées — {observation.get('date', '?')}",
                    data=data,
                ))
            elif name == "list_incidents":
                data = observation
                if school is not None:
                    items = [i for i in (observation.get("items") or [])
                             if _obs_school_matches(i, school, other_schools)]
                    removed = len(observation.get("items") or []) - len(items)
                    if removed and not items:
                        continue
                    if removed:
                        try:
                            total = max(0, int(observation.get("total", len(items)) or 0) - removed)
                        except (TypeError, ValueError):
                            total = len(items)
                        data = {**observation, "items": items, "total": total}
                cards.append(AgentCard(
                    type="incident_list",
                    title=f"Signalements déclarés — {observation.get('date', '?')}",
                    data=data,
                ))
            elif name in PLUGIN_CARDS:
                for builder in PLUGIN_CARDS[name].values():
                    card = builder(observation)
                    if card is not None:
                        if period_label and name in PLUGIN_READ_ONLY:
                            card.title = f"{card.title} ({period_label})"
                        cards.append(card)
        if period_label:
            for card in cards:
                if card.type in PERIOD_TITLE_TYPES:
                    card.title = f"{card.title} ({period_label})"
        unique: list[AgentCard] = []
        fingerprints: set[str] = set()
        for card in cards:
            fingerprint = f"{card.type}|{card.title}|{json.dumps(card.data, sort_keys=True, default=str)}"
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(card)
        return unique
