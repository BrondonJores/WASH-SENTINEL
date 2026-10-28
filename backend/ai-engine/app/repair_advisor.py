from __future__ import annotations

from .providers import BaseLLMProvider
from .schemas import RepairPlanRequest, RepairPlanResponse

REPAIR_ADVISOR_SYSTEM = """
Tu es l'ingénieur de maintenance en chef de WASH Sentinel.
À partir de la description d'une panne d'infrastructure d'eau ou d'assainissement dans une école, tu dois générer une fiche technique de réparation exploitable par un plombier ou un technicien communal.

Renvoie STRICTEMENT un JSON valide :
{
  "required_tools": ["liste des outils nécessaires, ex: Clé à molette, Pince multiprise, Scie à métaux"],
  "spare_parts_needed": ["liste des pièces de rechange, ex: Joint torique 20/27, Manchon PVC Ø32, Téflon"],
  "estimated_intervention_time": "durée estimée (ex: 2h à 3h)",
  "immediate_safety_measures": ["consignes de sécurité immédiates pour l'école avant l'arrivée du technicien"],
  "estimated_cost_tier": "low | medium | high | critical_budget"
}

Règles :
1. Adapte les recommandations aux contextes scolaires (pièces standardisées et robustes).
2. Propose des mesures de sécurité vitales pour les enfants (ex: couper l'électricité si fuite proche d'un câble, fermer la vanne d'arrêt générale, chlorer l'eau de secours).
3. Uniquement du JSON.
"""


class RepairAdvisor:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def generate_plan(self, req: RepairPlanRequest) -> RepairPlanResponse:
        prompt = f"""
Panne signalée : {req.incident_summary}
Type d'infrastructure : {req.infrastructure_type}
Nature du problème : {req.issue_type}
Niveau d'urgence : {req.urgency_level}
        """

        raw = await self.llm.generate_json(prompt, REPAIR_ADVISOR_SYSTEM)

        tools = raw.get("required_tools")
        if not isinstance(tools, list) or not tools:
            tools = ["Clé à griffe", "Pince multiprise", "Ruban Téflon", "Jeu de tournevis"]

        parts = raw.get("spare_parts_needed")
        if not isinstance(parts, list) or not parts:
            parts = ["Joints d'étanchéité", "Raccords PVC/laiton adaptés", "Colle PVC"]

        safety = raw.get("immediate_safety_measures")
        if not isinstance(safety, list) or not safety:
            safety = [
                "Couper l'arrivée d'eau amont pour stopper la fuite",
                "Balisage d'interdiction d'accès pour les élèves",
                "Fournir des réserves d'eau temporaires traitées"
            ]

        cost_tier = str(raw.get("estimated_cost_tier", "medium")).lower()
        if cost_tier not in ["low", "medium", "high", "critical_budget"]:
            cost_tier = "medium"

        return RepairPlanResponse(
            required_tools=tools,
            spare_parts_needed=parts,
            estimated_intervention_time=str(raw.get("estimated_intervention_time", "2 heures")),
            immediate_safety_measures=safety,
            estimated_cost_tier=cost_tier,
        )
