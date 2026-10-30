from __future__ import annotations

import json
from typing import Any

from .agent_tools import AGENT_TOOLS, TOOL_EXECUTORS
from .providers import BaseLLMProvider
from .schemas import AgentCard, AgentChatRequest, AgentChatResponse

SYSTEM_PROMPT = """Tu es Sentinel, l'agent omniprésent de WASH Sentinel, plateforme de surveillance
de l'eau et de l'assainissement dans les écoles du Cameroun.

Règles impératives :
- Réponds UNIQUEMENT en français, de façon concise (2 à 4 phrases).
- Ne devine jamais : utilise tes outils pour obtenir les faits (écoles, incidents, chiffres).
- Si l'utilisateur nomme une école, appelle directement l'outil avec ce nom même approximatif : ne demande JAMAIS un identifiant, un coût ou un historique, les outils les retrouvent seuls.
- N'invente jamais d'identifiant : utilise exactement ceux renvoyés par les outils.
- Si l'utilisateur signale une panne, appelle prepare_report puis demande confirmation avant tout enregistrement.
- Pour tout historique, tendance ou comparaison chiffrée : appelle repair_trends (les graphiques sont générés en cartes).\n- Pour toute carte, visualisation géographique ou question 'où' : appelle territory_overview (la carte interactive est générée).\n- Pour tout briefing, dossier, diaporama ou synthèse exécutive : appelle build_briefing (la présentation est générée).
- Reste strictement dans le domaine eau/assainissement scolaires : jamais de pédagogie, formation, cantine ou autre hors sujet.
- Si un outil renvoie une erreur, corrige tes arguments avec les valeurs exactes fournies et réessaie au lieu d'abandonner.
- N'appelle jamais deux fois le même outil avec les mêmes arguments : quand tu as le résultat, réponds.
- Les données détaillées sont affichées dans des cartes séparées : ne recopie pas tout dans ta réponse.
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
    "explain_incident, territory_overview ou build_briefing). "
    "N'écris aucun texte, appelle juste l'outil."
)

DATA_QUESTION_HINTS = (
    "quel", "combien", "liste", "montre", "affiche", "carte",
    "tendance", "analyse", "résume", "resume", "briefing", "diaporama",
    "où", "ou ", "état", "etat", "besoin", "aide", "panne",
    "incident", "école", "ecole", "district", "graphique", "graphe",
    "coût", "cout", "budget", "intervention", "répar", "remplac",
)


REFUSAL_PATTERNS = (
    "je suis désolé",
    "je ne peux pas vous aider",
    "je ne peux pas répondre",
    "désolé, mais je ne peux",
    "impossible de vous aider",
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
    matched = (obs.get("matched_school", {}) or {}).get("school_name")
    description = str(obs.get("description", "")).strip()[:120]
    if matched:
        return (
            f"Signalement préparé pour {matched} : « {description} ». "
            "Confirmez-le dans la carte ci-dessous."
        )
    return (
        f"Signalement préparé : « {description} ». "
        "Précisez l'école puis confirmez dans la carte ci-dessous."
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
    "summarize_district": _summarize_district,
    "repair_trends": _summarize_trends,
    "rank_schools_by_need": _summarize_ranking,
    "analyze_school": _summarize_analysis,
    "explain_incident": _summarize_incident,
    "prepare_report": _summarize_report,
    "territory_overview": _summarize_territory,
    "build_briefing": lambda obs: (
        f"Briefing prêt : {int(obs.get('total', 0) or 0)} slides "
        f"({(obs.get('slides', [{}])[0].get('stats', [{}])[0].get('value', '?'))} "
        "incidents ouverts). La présentation est dans la carte ci-dessous."
    ),
}


class AgentLoop:
    """Boucle agentique réelle : le LLM choisit ses outils, Python les exécute."""

    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def chat(self, req: AgentChatRequest) -> AgentChatResponse:
        context = req.context.model_dump()
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in req.history[-6:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": req.message})

        executed: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        nudged = False
        answer = ""
        for _ in range(MAX_ITERATIONS):
            reply = await self.llm.chat(messages, AGENT_TOOLS)
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
            answer = await self._force_tool_pass(messages, context, executed)

        if not answer.strip() or self._is_bogus_refusal(answer, executed):
            answer = self._fallback_answer(executed)

        return AgentChatResponse(
            answer=answer.strip(),
            tools_executed=[name for name, _ in executed],
            cards=self._build_cards(executed),
            model_used=self.llm.model,
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
    ) -> str:
        """Dernier recadrage : réponse directe à une question de données.

        On exige un appel d'outil immédiat. S'il obéit, on le laisse conclure
        sur les observations ; sinon, réponse honnête (jamais d'invention).
        """
        messages.append({"role": "user", "content": NO_TOOL_NUDGE})
        retry = await self.llm.chat(messages, AGENT_TOOLS)
        messages.append(retry["raw"])
        for call in retry.get("tool_calls", []):
            name = call.get("name", "")
            arguments = call.get("arguments", {}) or {}
            observation = self._execute_tool(name, arguments, context)
            executed.append((name, observation))
            messages.append(self.llm.format_tool_result(name, observation, call.get("id")))
        if not executed:
            return self._fallback_answer(executed)
        final = await self.llm.chat(messages, AGENT_TOOLS)
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
            elif name == "prepare_report":
                cards.append(AgentCard(
                    type="report_confirmation",
                    title="Confirmer le signalement",
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
        unique: list[AgentCard] = []
        fingerprints: set[str] = set()
        for card in cards:
            fingerprint = f"{card.type}|{card.title}|{json.dumps(card.data, sort_keys=True, default=str)}"
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(card)
        return unique
