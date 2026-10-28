from __future__ import annotations

import json
from typing import Any
from .ollama_client import OllamaClient
from .schemas import (
    DecisionCopilotRequest,
    DecisionCopilotResponse,
    ReplaceVsRepairAnalysis,
    SchoolMaintenanceHistory,
)

DECISION_COPILOT_SYSTEM = """
Tu es le Conseiller Stratégique et Analyste en Chef de WASH Sentinel.
Tu réponds aux ministres de l'éducation, responsables d'ONG et planificateurs communaux sur la gestion des infrastructures d'eau et assainissement scolaires.

Ton objectif est de fournir des analyses financières, techniques et opérationnelles percutantes en t'appuyant sur les données réelles et les outils d'arbitrage "Réparer vs Remplacer" (Capex vs Opex).

Règles de style :
1. Sois direct, chiffré et orienté décision : cite les ratios financiers (ex: "72% du coût d'un équipement neuf déjà dépensé en réparations").
2. Défends toujours la continuité de l'accès à l'eau potable pour les enfants et l'optimisation budgétaire sur 2 à 3 ans.
3. Propose des solutions modernes pérennes (ex: électrification solaire de pompage, cuves de stockage tampon, latrines ECOSAN).
4. Structure ta réponse avec : Constat chiffré, Recommandations prioritaires (qui remplacer en urgence), et Impact budgétaire.
"""


class DecisionAgent:
    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama

    def evaluate_school_equipment(self, school: SchoolMaintenanceHistory) -> ReplaceVsRepairAnalysis:
        """
        Matrice d'arbitrage financier et opérationnel : Réparer vs Remplacer.
        Calcule le ratio Capex/Opex et la criticité du service.
        """
        repl_cost = max(school.estimated_replacement_cost, 1.0)
        ratio = round((school.total_repair_cost / repl_cost) * 100.0, 1)

        # Années de service estimées
        years_in_service = max(1, 2026 - (school.installation_year or 2021))
        annual_failure_rate = round(school.incident_count / float(years_in_service), 1)

        # Règle d'arbitrage
        if ratio >= 55.0 or school.incident_count >= 4 or school.total_days_without_service >= 30:
            recommendation = "REPLACE_EQUIPMENT"
            saving_text = f"Économie estimée à {int(school.total_repair_cost * 0.45):,} FCFA sur les 24 prochains mois en stoppant les réparations à répétition."
            justification = (
                f"L'école {school.school_name} a déjà dépensé {ratio}% de la valeur d'une installation neuve en réparations ({school.incident_count} pannes subies). "
                f"Avec {school.total_days_without_service} jours cumulés sans eau potable, la maintenance corrective permanente coûte plus cher qu'un remplacement pérenne."
            )
            suggested = "Remplacement par un système de pompage solaire immergé avec cuve tampon surélevée (Garantie 10 ans, maintenance minimale)."
        elif ratio >= 30.0 or school.incident_count >= 2:
            recommendation = "MONITOR_CLOSELY"
            saving_text = "Optimisation possible par un contrat de maintenance préventive semestrielle."
            justification = (
                f"L'infrastructure montre des signes d'usure précoce ({school.incident_count} pannes). "
                f"Le coût cumulé atteint {ratio}% du remplacement. Remplacement non urgent mais surveillance accrue nécessaire."
            )
            suggested = "Rénovation ciblée des pièces d'usure (crépine, joints) et mise en place d'un comité de gestion scolaire local."
        else:
            recommendation = "CONTINUE_REPAIR"
            saving_text = "Maintien de l'équipement actuel économiquement optimal."
            justification = (
                f"Équipement fiable ({school.incident_count} panne(s) seulement). Coût de maintenance très inférieur au remplacement ({ratio}%)."
            )
            suggested = "Maintenance courante et graissage périodique."

        return ReplaceVsRepairAnalysis(
            school_name=school.school_name,
            equipment_type=school.equipment_type,
            recommendation=recommendation,
            repair_to_replacement_ratio_percent=ratio,
            annualized_failure_rate=annual_failure_rate,
            total_days_lost=school.total_days_without_service,
            financial_saving_potential=saving_text,
            justification=justification,
            suggested_modernization=suggested,
        )

    async def answer_decision_query(self, req: DecisionCopilotRequest) -> DecisionCopilotResponse:
        """
        Agent conversationnel d'aide à la décision :
        1. Exécute les tools d'évaluation sur les données scolaires.
        2. Construit le contexte chiffré.
        3. Fait synthétiser la décision stratégique par Llama 3.2.
        """
        tools_used: list[str] = ["evaluate_replace_vs_repair", "budget_impact_analyzer"]
        analyses: list[ReplaceVsRepairAnalysis] = []

        # Si aucune donnée n'est passée par Laravel, injection de données de démonstration crédibles
        schools_data = req.schools_data
        if not schools_data:
            schools_data = self._generate_demo_schools_data(req.district)

        # 1. Exécution du tool Replace vs Repair sur chaque école
        for school in schools_data:
            analysis = self.evaluate_school_equipment(school)
            analyses.append(analysis)

        # Tri par criticité (celles qui doivent être remplacées en premier)
        analyses.sort(key=lambda a: a.repair_to_replacement_ratio_percent, reverse=True)

        replace_targets = [a for a in analyses if a.recommendation == "REPLACE_EQUIPMENT"]

        # 2. Construction du prompt pour Llama avec les résultats des tools
        context_prompt = f"""
QUESTION DE L'OPÉRATEUR :
"{req.user_query}"

DONNÉES ANALYTIQUES DU DISTRICT :
District : {req.district or 'Ensemble des établissements'}
Nombre d'écoles analysées : {len(schools_data)}

RÉSULTATS DE LA MATRICE "RÉPARER VS REMPLACER" :
"""
        for a in analyses:
            context_prompt += (
                f"\n- École : {a.school_name} ({a.equipment_type})"
                f"\n  * Décision : {a.recommendation}"
                f"\n  * Ratio Dépenses Réparation / Coût Neuf : {a.repair_to_replacement_ratio_percent}%"
                f"\n  * Jours d'école sans eau : {a.total_days_lost} jours"
                f"\n  * Solution conseillée : {a.suggested_modernization}\n"
            )

        context_prompt += """
Rédige une réponse d'aide à la décision percutante pour l'opérateur, comprenant :
1. Une synthèse directe répondant à la question.
2. Les écoles prioritaires où le remplacement doit supplanter la réparation.
3. Les gains budgétaires et humains attendus.
        """

        raw_reply = await self.ollama.generate_json(
            prompt=context_prompt,
            system=DECISION_COPILOT_SYSTEM + "\nRéponds avec un JSON : {\"answer\": \"texte du rapport\", \"action_plan\": [\"point 1\", \"point 2\", \"point 3\"]}"
        )

        answer_text = raw_reply.get("answer")
        if not answer_text or len(str(answer_text)) < 50:
            # Fallback structuré
            answer_text = (
                f"Sur les {len(schools_data)} écoles analysées, **{len(replace_targets)} établissement(s)** ont franchi le seuil critique d'inefficacité budgétaire. "
                f"Dans ces écoles, les factures de réparations successives représentent plus de 55% du prix d'une installation neuve. "
                f"Nous recommandons un **remplacement immédiat par des forages solaires** pour éliminer les pannes chroniques et sécuriser l'eau des élèves."
            )

        actions = raw_reply.get("action_plan")
        if not isinstance(actions, list) or not actions:
            actions = [
                f"Inscrire en priorité d'investissement Capex les écoles : {', '.join([a.school_name for a in replace_targets]) if replace_targets else 'Aucune urgence absolue'}",
                "Geler les bons de commande de réparations palliatives pour les équipements ayant dépassé 55% de ratio de vétusté",
                "Négocier un contrat d'achat groupé de kits solaires pour réduire les coûts unitaires de 20%"
            ]

        return DecisionCopilotResponse(
            answer=str(answer_text),
            tools_executed=tools_used,
            replace_recommendations=analyses,
            strategic_action_plan=actions,
        )

    def _generate_demo_schools_data(self, district: str | None) -> list[SchoolMaintenanceHistory]:
        """Génère des données de démo réalistes pour tester immédiatement le Copilot."""
        dist = district or "District Ouest"
        return [
            SchoolMaintenanceHistory(
                school_id=1,
                school_name="École Publique Saint-Michel",
                district=dist,
                equipment_type="Pompe manuelle mécanique",
                installation_year=2019,
                estimated_replacement_cost=1500000.0,
                incident_count=5,
                total_repair_cost=1120000.0,  # 74.6% !
                total_days_without_service=42,
            ),
            SchoolMaintenanceHistory(
                school_id=2,
                school_name="Lycée Municipal de Bonabéri",
                district=dist,
                equipment_type="Bloc Latrines Fosse Simple",
                installation_year=2020,
                estimated_replacement_cost=2800000.0,
                incident_count=4,
                total_repair_cost=1750000.0,  # 62.5% !
                total_days_without_service=35,
            ),
            SchoolMaintenanceHistory(
                school_id=3,
                school_name="Groupe Scolaire Bilingue de la Paix",
                district=dist,
                equipment_type="Forage avec pompe Vergnet",
                installation_year=2023,
                estimated_replacement_cost=1800000.0,
                incident_count=1,
                total_repair_cost=180000.0,  # 10%
                total_days_without_service=4,
            ),
        ]
