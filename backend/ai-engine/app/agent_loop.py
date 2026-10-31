from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from .agent_tools import AGENT_TOOLS, TOOL_EXECUTORS
from .providers import BaseLLMProvider
from .schemas import AgentCard, AgentChatRequest, AgentChatResponse

SYSTEM_PROMPT = """Tu es Sentinel, l'agent omniprésent de WASH Sentinel, plateforme de surveillance
de l'eau et de l'assainissement dans les écoles du Cameroun.

Règles impératives :
- Réponds de façon concise (2 à 4 phrases).
- Ne devine jamais : utilise tes outils pour obtenir les faits (écoles, incidents, chiffres).
- Si l'utilisateur nomme une école ou un incident, appelle directement l'outil avec ce nom même approximatif : ne demande JAMAIS un identifiant, un coût ou un historique, les outils les retrouvent seuls.
- N'invente jamais d'identifiant : utilise exactement ceux renvoyés par les outils.
- Si l'utilisateur veut créer (signaler une panne, créer une intervention, journaliser des travaux) : rassemble TOUJOURS le dossier complet — école, description ou titre, catégorie, urgence, élèves affectés (ou incident et coût pour un journal). Si tout est donné en une phrase, appelle directement l'outil prepare_* ; sinon pose des questions courtes (2 éléments maximum par message) jusqu'au dossier complet. Si l'utilisateur répond par un mot seul ou un nom (chip cliquable), reprends le dossier en cours avec cette valeur au lieu de reposer la même question.
- Quand un outil prepare_* répond complete=true, présente le récapitulatif et demande de cliquer Confirmer (ou de répondre « oui »). N'annonce jamais un enregistrement effectué : seul l'humain valide, y compris pour préciser une école introuvable ou plusieurs incidents possibles (propose les choix fournis — school_choices, incident_choices — au lieu d'inventer ; si une carte de choix s'affiche, invite à cliquer sur le bon incident).
- Pour tout historique, tendance ou comparaison chiffrée : appelle repair_trends (les graphiques sont générés en cartes).\n- Pour toute carte, visualisation géographique ou question 'où' : appelle territory_overview (la carte interactive est générée).\n- Pour tout briefing, dossier, diaporama ou synthèse exécutive : appelle build_briefing (la présentation est générée).
- Reste strictement dans le domaine eau/assainissement scolaires : jamais de pédagogie, formation, cantine ou autre hors sujet.
- Si un outil renvoie une erreur, corrige tes arguments avec les valeurs exactes fournies et réessaie au lieu d'abandonner.
- N'appelle jamais deux fois le même outil avec les mêmes arguments : quand tu as le résultat, réponds.
- Les données détaillées sont affichées dans des cartes séparées : ne recopie pas tout dans ta réponse.
- Réponds toujours dans la langue du dernier message (français par défaut) ; termes techniques WASH traduisibles, références/codes inchangés ; si l'utilisateur écrit en langue locale, réponds en français simple et propose de reformuler.
- N'affirme jamais une absence (« aucun », « rien », « zéro ») sans observation d'un tool de liste (list_maintenance_logs, summarize_district, rank_schools_by_need, repair_trends, explain_incident, territory_overview, analyze_school, build_briefing) ; si aucun outil ne couvre la question, dis-le et propose tes capacités.
"""

MAX_ITERATIONS = 5

REPEAT_NUDGE = (
    "Tu as déjà appelé cet outil avec ces mêmes arguments : le résultat est plus haut. "
    "N'appelle plus aucun outil et réponds maintenant à l'utilisateur en français."
)

NO_TOOL_NUDGE = (
    "STOP. Tu as répondu à une question de données SANS appeler d'outil, "
    "c'est strictement interdit : tu dois appeler l'outil adapté MAINTENANT "
    "(rank_schools_by_need, summarize_district, analyze_school, repair_trends, "
    "explain_incident, territory_overview, build_briefing ou list_maintenance_logs). "
    "N'écris aucun texte, appelle juste l'outil."
)

DATA_QUESTION_HINTS = (
    "quel", "combien", "liste", "montre", "affiche", "carte",
    "tendance", "analyse", "résume", "resume", "briefing", "diaporama",
    "où", "ou ", "état", "etat", "besoin", "aide", "panne",
    "incident", "école", "ecole", "district", "graphique", "graphe",
    "coût", "cout", "budget", "intervention", "répar", "remplac",
    "signal", "cré", "cree", "ajoute", "enregistre", "journalis",
    "déclare", "declare",
)


# Routeur déterministe liste/création : indices en minuscules, comparaison par
# sous-chaîne sur la question. Les formes sans accent doublent les accentuées.
LIST_INTENT_HINTS = (
    "réalisé", "realise", "aujourd'hui", "aujourd’hui", "aujourdhui",
    "hier", "semaine", "mois", "liste", "lister", "combien",
    "quels travaux", "historique", "passé", "passe", "affiche", "montre",
)

CREATE_INTENT_HINTS = (
    "crée", "créer", "cree", "creer", "ajoute", "nouveau", "nouvelle",
    "journalise", "enregistre", "signale", "déclare", "declare",
    "prépare", "prepare", "planifie",
)


def route_intent(question: str) -> Literal["list", "create", "other"]:
    """Route la question : consultation du passé, création, ou autre (fonction pure).

    « create » seulement si un indice de création est présent SANS aucun indice
    de liste ; sinon « list » dès qu'un indice de liste est présent.
    """
    lowered = (question or "").lower()
    has_list = any(h in lowered for h in LIST_INTENT_HINTS)
    has_create = any(h in lowered for h in CREATE_INTENT_HINTS)
    if has_create and not has_list:
        return "create"
    if has_list:
        return "list"
    return "other"


def tools_for_intent(intent: str) -> list[dict[str, Any]]:
    """Jeu d'outils exposé : en consultation, les prepare_* (création) sont masqués."""
    if intent == "list":
        return [t for t in AGENT_TOOLS
                if not t.get("function", {}).get("name", "").startswith("prepare_")]
    return list(AGENT_TOOLS)


# Garde-fou abstention : outils de lecture dont l'observation autorise un constat.
READ_TOOLS = frozenset({
    "list_maintenance_logs", "summarize_district", "rank_schools_by_need",
    "repair_trends", "explain_incident", "territory_overview",
    "analyze_school", "build_briefing",
})

ABSENCE_RE = re.compile(r"aucun|aucune|pas d|rien|zéro|zero", re.IGNORECASE)

ABSENCE_CORRECTION_NUDGE = (
    "STOP. Tu viens d'affirmer une absence (aucun/aucune/rien/zéro) SANS avoir "
    "observé un outil de lecture, c'est strictement interdit : appelle MAINTENANT "
    "l'outil de liste adapté (list_maintenance_logs pour les interventions passées, "
    "sinon summarize_district, rank_schools_by_need, repair_trends, explain_incident, "
    "territory_overview, analyze_school ou build_briefing) puis réponds à partir de "
    "son observation. N'écris aucun texte, appelle juste l'outil."
)

UNVERIFIED_HONEST_ANSWER = (
    "Je ne peux pas vérifier les interventions pour cette question : aucun outil "
    "de liste n'a retourné de donnée observable. Précisez une date (AAAA-MM-JJ) "
    "ou un nom d'école et je consulterai le journal."
)


def _claims_absence(answer: str) -> bool:
    """La réponse affirme-t-elle une absence (aucun, rien, zéro...) ?"""
    return bool(answer and ABSENCE_RE.search(answer))


def _has_read_tool(executed: list[tuple[str, dict[str, Any]]]) -> bool:
    """Au moins un outil de lecture a-t-il été appelé ce tour-ci ?"""
    return any(name in READ_TOOLS for name, _ in executed)


WASH_REF_RE = re.compile(r"WASH-\d{4}-[A-Z0-9]+")

CONTRADICTION_CORRECTION_NUDGE = (
    "STOP. Tu cites une référence précise puis affirmes une absence "
    "(aucun/aucune/rien/zéro) alors que ton observation de liste adossée a "
    "un total de 0 : c'est contradictoire. Relis tes observations : si une "
    "référence WASH-AAAA-XXXX existe vraiment, décris-la sans affirmer "
    "d'absence ; si le total est vraiment 0, ne cite aucune référence. "
    "Rappelle MAINTENANT l'outil de liste adapté (list_maintenance_logs pour "
    "les interventions passées) SANS filtre école parasite, puis réponds de "
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


def _detect_lang(message: str) -> Literal["fr", "en"]:
    """Détecte la langue du message : 'fr' ou 'en'.

    Heuristique déterministe : on compte les mots-outils anglais puis français
    (scores indépendants, un mot ne vote que pour sa langue). Le score le plus
    élevé gagne ; égalité ou message vide (ou sans mot-outil) → 'fr' par défaut.
    Les langues locales (douala, etc.) ne sont PAS détectées par mots : elles
    arrivent via le contexte école (transcription STT) et restent acceptées en
    entrée — le prompt demande alors une réponse en français simple.
    """
    tokens = _TOKEN_RE.findall((message or "").lower())
    en_score = sum(1 for token in tokens if token in _EN_TOOL_WORDS)
    fr_score = sum(1 for token in tokens if token in _FR_TOOL_WORDS)
    if en_score > fr_score:
        return "en"
    return "fr"


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
    return (
        f"À {obs.get('school_name', '?')} sur {obs.get('months', 3)} mois : "
        f"{n} {_plural(n, 'panne')}, "
        f"{_fmt_int(figures.get('total_cost', 0))} {figures.get('currency', 'XAF')} de réparations, "
        f"tendance {trend}. Le graphique est dans la carte ci-dessous."
    )


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


class AgentLoop:
    """Boucle agentique réelle : le LLM choisit ses outils, Python les exécute."""

    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def chat(self, req: AgentChatRequest) -> AgentChatResponse:
        context = req.context.model_dump()
        lang = _resolve_lang(req)
        active_tools = tools_for_intent(route_intent(req.message))
        messages: list[dict[str, Any]] = [{"role": "system", "content": _build_system_prompt(lang)}]
        for turn in req.history[-6:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": req.message})

        executed: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        nudged = False
        answer = ""
        used_iterations = 0
        for _ in range(MAX_ITERATIONS):
            used_iterations += 1
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
                messages.append(self.llm.format_tool_result(name, observation, call.get("id")))
            if not fresh:
                if nudged:
                    break
                nudged = True
        else:
            answer = self._fallback_answer(executed)

        if not executed and answer.strip() and self._looks_like_data_question(req.message):
            answer = await self._force_tool_pass(messages, context, executed, active_tools)

        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            answer = self._fallback_answer(executed)

        if answer.strip() and _claims_absence(answer) and not _has_read_tool(executed):
            if used_iterations < MAX_ITERATIONS:
                answer = await self._absence_correction_pass(
                    messages, context, executed, seen, active_tools)
            else:
                answer = UNVERIFIED_HONEST_ANSWER

        if (answer.strip() and _cites_reference(answer) and _claims_absence(answer)
                and _has_empty_list_obs(executed)):
            if used_iterations < MAX_ITERATIONS:
                answer = await self._absence_correction_pass(
                    messages, context, executed, seen, active_tools,
                    nudge=CONTRADICTION_CORRECTION_NUDGE)
            else:
                answer = self._fallback_answer(executed)

        return AgentChatResponse(
            answer=answer.strip(),
            tools_executed=[name for name, _ in executed],
            cards=self._build_cards(executed),
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

    @staticmethod
    def _looks_like_data_question(message: str) -> bool:
        """Heuristique large : en cas de doute on exige un outil.

        Les salutations, remerciements et confirmations (« oui », « merci »)
        ne correspondent à aucun indice et passent sans recadrage.
        """
        lowered = message.lower()
        return any(h in lowered for h in DATA_QUESTION_HINTS)

    async def _force_tool_pass(
        self,
        messages: list[dict[str, Any]],
        context: dict[str, Any],
        executed: list[tuple[str, dict[str, Any]]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """Dernier recadrage : réponse directe à une question de données.

        On exige un appel d'outil immédiat. S'il obéit, on le laisse conclure
        sur les observations ; sinon, réponse honnête (jamais d'invention).
        """
        tools = AGENT_TOOLS if tools is None else tools
        messages.append({"role": "user", "content": NO_TOOL_NUDGE})
        retry = await self.llm.chat(messages, tools)
        messages.append(retry["raw"])
        for call in retry.get("tool_calls", []):
            name = call.get("name", "")
            arguments = call.get("arguments", {}) or {}
            observation = self._execute_tool(name, arguments, context)
            executed.append((name, observation))
            messages.append(self.llm.format_tool_result(name, observation, call.get("id")))
        if not executed:
            return self._fallback_answer(executed)
        final = await self.llm.chat(messages, tools)
        messages.append(final["raw"])
        answer = final.get("content", "")
        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            return self._fallback_answer(executed)
        return answer

    async def _absence_correction_pass(
        self,
        messages: list[dict[str, Any]],
        context: dict[str, Any],
        executed: list[tuple[str, dict[str, Any]]],
        seen: set[tuple[str, str]],
        tools: list[dict[str, Any]],
        nudge: str = ABSENCE_CORRECTION_NUDGE,
    ) -> str:
        """Recadrage anti-hallucination : absence affirmée sans lecture
        (ou contradiction référence + absence, via un nudge adapté).

        Une seule tentative (bornée par MAX_ITERATIONS à l'appel) : on exige un
        outil de lecture puis on conclut ; si le modèle persiste sans observer,
        réponse honnête (jamais d'invention).
        """
        messages.append({"role": "user", "content": nudge})
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
            messages.append(self.llm.format_tool_result(name, observation, call.get("id")))
        if not _has_read_tool(executed):
            return UNVERIFIED_HONEST_ANSWER
        final = await self.llm.chat(messages, tools)
        messages.append(final["raw"])
        answer = final.get("content", "")
        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            return self._fallback_answer(executed)
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

    def _fallback_answer(self, executed: list[tuple[str, dict[str, Any]]]) -> str:
        """Résumé humain déterministe quand le modèle ne conclut pas.

        Prend la dernière observation réussie et la raconte en une phrase
        chiffrée qui pointe vers la carte (pas de jargon robotique).
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
            return "J'ai consulté les données, le résultat est dans la carte ci-dessous."
        return (
            "Je n'ai pas pu récupérer de données pour cette question. "
            "Reformulez-la avec le nom d'une école ou d'un district."
        )

    def _build_cards(self, executed: list[tuple[str, dict[str, Any]]]) -> list[AgentCard]:
        cards: list[AgentCard] = []
        for name, observation in executed:
            if "error" in observation:
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
            elif name == "list_maintenance_logs":
                cards.append(AgentCard(
                    type="maintenance_logs",
                    title=f"Interventions journalisées — {observation.get('date', '?')}",
                    data=observation,
                ))
        unique: list[AgentCard] = []
        fingerprints: set[str] = set()
        for card in cards:
            fingerprint = f"{card.type}|{card.title}|{json.dumps(card.data, sort_keys=True, default=str)}"
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(card)
        return unique
