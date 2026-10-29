from __future__ import annotations

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
- Pour tout historique, tendance ou comparaison chiffrée : appelle repair_trends (les graphiques sont générés en cartes).
- Reste strictement dans le domaine eau/assainissement scolaires : jamais de pédagogie, formation, cantine ou autre hors sujet.
- Si un outil renvoie une erreur, corrige tes arguments avec les valeurs exactes fournies et réessaie au lieu d'abandonner.
- Les données détaillées sont affichées dans des cartes séparées : ne recopie pas tout dans ta réponse.
"""

MAX_ITERATIONS = 5


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
        answer = ""
        for _ in range(MAX_ITERATIONS):
            reply = await self.llm.chat(messages, AGENT_TOOLS)
            messages.append(reply["raw"])
            calls = reply.get("tool_calls", [])
            if not calls:
                answer = reply.get("content", "")
                break
            for call in calls:
                name = call.get("name", "")
                arguments = call.get("arguments", {}) or {}
                executor = TOOL_EXECUTORS.get(name)
                if executor is None:
                    observation: dict[str, Any] = {"error": f"Outil inconnu : {name}."}
                else:
                    try:
                        observation = executor(arguments, context)
                    except Exception as exc:
                        observation = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                executed.append((name, observation))
                messages.append(self.llm.format_tool_result(name, observation, call.get("id")))
        else:
            answer = answer or "Voici ce que j'ai trouvé à partir des données disponibles."

        if not answer.strip():
            answer = "Voici ce que j'ai trouvé à partir des données disponibles."

        return AgentChatResponse(
            answer=answer.strip(),
            tools_executed=[name for name, _ in executed],
            cards=self._build_cards(executed),
            model_used=self.llm.model,
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
            elif name == "repair_trends":
                cards.append(AgentCard(
                    type="trend_chart",
                    title=f"Tendances — {observation.get('school_name', '?')} ({observation.get('months', 3)} mois)",
                    data=observation,
                ))
        return cards
