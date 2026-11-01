from __future__ import annotations

from .prompts import is_small_model, render_repair_prompt
from .providers import BaseLLMProvider
from .schemas import RepairPlanRequest, RepairPlanResponse

#: Alias historique : rendu neutre du builder prompts.repair_sections()
#: (sans few-shots par défaut, taille stable).
REPAIR_ADVISOR_SYSTEM = render_repair_prompt()


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

        # Few-shots réservés aux petits modèles ; JSON réparé quand le
        # provider l'offre (repli generate_json brut sinon, ex. stubs).
        system_prompt = render_repair_prompt(
            include_few_shots=is_small_model(getattr(self.llm, "model", "")))
        repaired = getattr(self.llm, "generate_json_repaired", None)
        if repaired is None:
            raw = await self.llm.generate_json(prompt, system_prompt)
        else:
            raw = await repaired(prompt, system_prompt)

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
