from __future__ import annotations

import json
import os
from datetime import date
from typing import Any
from .providers import BaseLLMProvider
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


# --- LOT 3 : matrice Réparer vs Remplacer (seuils historiques inchangés) ---
# Source unique des seuils décisionnels : tools/copilot_answer.py les importe
# (zéro recopie) et recurrence_watch.py reprend les mêmes valeurs agrégées.

#: Remplacement : ratio dépenses/neuf ≥55 %, ou ≥4 pannes, ou ≥30 j sans eau.
DECISION_REPLACE_MIN_RATIO_PCT = _env_float("DECISION_REPLACE_MIN_RATIO_PCT", 55.0)
DECISION_REPLACE_MIN_INCIDENTS = _env_int("DECISION_REPLACE_MIN_INCIDENTS", 4)
DECISION_REPLACE_MIN_DAYS_OFF = _env_int("DECISION_REPLACE_MIN_DAYS_OFF", 30)

#: Économie estimée : 45 % des réparations cumulées sur 24 mois.
DECISION_REPAIR_SAVING_RATIO = _env_float("DECISION_REPAIR_SAVING_RATIO", 0.45)
DECISION_SAVING_HORIZON_MONTHS = _env_int("DECISION_SAVING_HORIZON_MONTHS", 24)

#: Surveillance renforcée : ratio ≥30 % ou ≥2 pannes.
DECISION_MONITOR_MIN_RATIO_PCT = _env_float("DECISION_MONITOR_MIN_RATIO_PCT", 30.0)
DECISION_MONITOR_MIN_INCIDENTS = _env_int("DECISION_MONITOR_MIN_INCIDENTS", 2)


class DecisionAgent:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    @staticmethod
    def evaluate_school_equipment(school: SchoolMaintenanceHistory,
                                  lang: str = "fr") -> ReplaceVsRepairAnalysis:
        """
        Matrice d'arbitrage financier et opérationnel : Réparer vs Remplacer.
        Calcule le ratio Capex/Opex et la criticité du service. Coût du neuf
        à 0 (non communiqué) : ratio None, verdict sur fréquence et jours
        sans service seuls, textes sans affirmation monétaire.
        lang="en" : justification, économie et suggestion en anglais.
        """
        use_en = str(lang or "fr").strip().lower().startswith("en")
        known_cost = school.estimated_replacement_cost > 0
        repl_cost = max(school.estimated_replacement_cost, 1.0)
        ratio: float | None = (
            round((school.total_repair_cost / repl_cost) * 100.0, 1)
            if known_cost else None)

        # Années de service estimées (LOT 3 : année courante réelle, plus 2026 figé).
        years_in_service = max(1, date.today().year - (school.installation_year or 2021))
        annual_failure_rate = round(school.incident_count / float(years_in_service), 1)

        ratio_replace = ratio is not None and ratio >= DECISION_REPLACE_MIN_RATIO_PCT
        ratio_monitor = ratio is not None and ratio >= DECISION_MONITOR_MIN_RATIO_PCT
        unknown_note = (" New equipment cost not provided: fill in the school "
                        "record for a full financial arbitration."
                        if use_en else
                        (" Coût d'un équipement neuf non communiqué : renseignez "
                         "la fiche école pour un arbitrage financier complet."))

        # Règle d'arbitrage
        if ratio_replace or school.incident_count >= DECISION_REPLACE_MIN_INCIDENTS or school.total_days_without_service >= DECISION_REPLACE_MIN_DAYS_OFF:
            recommendation = "REPLACE_EQUIPMENT"
            if ratio is None:
                saving_text = ("Savings cannot be estimated without the new cost; "
                               "stopping repeated repairs is still recommended."
                               if use_en else
                               ("Économie non chiffrable sans le coût du neuf ; "
                                "stopper les réparations à répétition reste recommandé."))
                justification = (
                    (f"{school.school_name} suffers {school.incident_count} breakdowns. "
                     f"With {school.total_days_without_service} days without safe water, "
                     f"permanent corrective maintenance calls for a lasting replacement."
                     f"{unknown_note}")
                    if use_en else
                    (f"L'école {school.school_name} subit {school.incident_count} pannes. "
                     f"Avec {school.total_days_without_service} jours cumulés sans eau potable, "
                     f"la maintenance corrective permanente appelle un remplacement pérenne."
                     f"{unknown_note}")
                )
            else:
                if use_en:
                    saving_text = (f"Estimated savings of {int(school.total_repair_cost * DECISION_REPAIR_SAVING_RATIO):,} XAF over the next {DECISION_SAVING_HORIZON_MONTHS} months by stopping repeated repairs.")
                    justification = (
                        f"{school.school_name} already spent {ratio}% of a new installation's value on repairs ({school.incident_count} breakdowns). "
                        f"With {school.total_days_without_service} days without safe water, permanent corrective maintenance costs more than a lasting replacement."
                    )
                else:
                    saving_text = f"Économie estimée à {int(school.total_repair_cost * DECISION_REPAIR_SAVING_RATIO):,} FCFA sur les {DECISION_SAVING_HORIZON_MONTHS} prochains mois en stoppant les réparations à répétition."
                    justification = (
                        f"L'école {school.school_name} a déjà dépensé {ratio}% de la valeur d'une installation neuve en réparations ({school.incident_count} pannes subies). "
                        f"Avec {school.total_days_without_service} jours cumulés sans eau potable, la maintenance corrective permanente coûte plus cher qu'un remplacement pérenne."
                    )
            suggested = ("Replacement with a submerged solar pumping system and elevated buffer tank (10-year warranty, minimal maintenance)."
                         if use_en else
                         "Remplacement par un système de pompage solaire immergé avec cuve tampon surélevée (Garantie 10 ans, maintenance minimale).")
        elif ratio_monitor or school.incident_count >= DECISION_MONITOR_MIN_INCIDENTS:
            recommendation = "MONITOR_CLOSELY"
            saving_text = ("Possible optimization through a half-yearly preventive maintenance contract."
                             if use_en else
                             "Optimisation possible par un contrat de maintenance préventive semestrielle.")
            if ratio is None:
                justification = (
                    (f"The infrastructure shows early wear ({school.incident_count} breakdowns). "
                     f"Replacement not urgent but closer monitoring needed."
                     f"{unknown_note}")
                    if use_en else
                    (f"L'infrastructure montre des signes d'usure précoce ({school.incident_count} pannes). "
                     f"Remplacement non urgent mais surveillance accrue nécessaire."
                     f"{unknown_note}")
                )
            else:
                justification = (
                    (f"The infrastructure shows early wear ({school.incident_count} breakdowns). "
                     f"Cumulative cost reaches {ratio}% of replacement. Replacement not urgent but closer monitoring needed.")
                    if use_en else
                    (f"L'infrastructure montre des signes d'usure précoce ({school.incident_count} pannes). "
                     f"Le coût cumulé atteint {ratio}% du remplacement. Remplacement non urgent mais surveillance accrue nécessaire.")
                )
            suggested = ("Targeted renovation of wear parts (strainer, seals) and setup of a local school management committee."
                         if use_en else
                         "Rénovation ciblée des pièces d'usure (crépine, joints) et mise en place d'un comité de gestion scolaire local.")
        else:
            recommendation = "CONTINUE_REPAIR"
            saving_text = ("Keeping the current equipment is economically optimal."
                             if use_en else
                             "Maintien de l'équipement actuel économiquement optimal.")
            if ratio is None:
                justification = (
                    (f"Reliable equipment (only {school.incident_count} breakdown(s)). "
                     f"Financial arbitration impossible without the new cost."
                     f"{unknown_note}")
                    if use_en else
                    (f"Équipement fiable ({school.incident_count} panne(s) seulement). "
                     f"Arbitrage financier impossible sans le coût du neuf."
                     f"{unknown_note}")
                )
            else:
                justification = (
                    (f"Reliable equipment (only {school.incident_count} breakdown(s)). Maintenance cost far below replacement ({ratio}%).")
                    if use_en else
                    (f"Équipement fiable ({school.incident_count} panne(s) seulement). Coût de maintenance très inférieur au remplacement ({ratio}%).")
                )
            suggested = ("Routine maintenance and periodic servicing."
                         if use_en else
                         "Maintenance courante et graissage périodique.")

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

    async def answer_decision_query(
        self, req: DecisionCopilotRequest, allow_demo: bool = False
    ) -> DecisionCopilotResponse:
        """
        Agent conversationnel d'aide à la décision :
        1. Exécute les tools d'évaluation sur les données scolaires.
        2. Construit le contexte chiffré.
        3. Fait synthétiser la décision stratégique par Llama 3.2.

        Sans données : abstention honnête (HTTP 200, data_source="empty"),
        jamais d'écoles fictives. Les données de démo exigent l'opt-in
        explicite allow_demo=True (démo manuelle / jury uniquement).
        """
        tools_used: list[str] = ["evaluate_replace_vs_repair", "budget_impact_analyzer"]
        analyses: list[ReplaceVsRepairAnalysis] = []

        schools_data = req.schools_data
        if not schools_data:
            if allow_demo:
                schools_data = self._generate_demo_schools_data(req.district)
            else:
                district = req.district or "le district ciblé"
                return DecisionCopilotResponse(
                    answer=(
                        f"Données insuffisantes : aucun historique fourni pour {district}. "
                        "Transmettez les historiques Laravel (coûts, pannes, jours sans eau) "
                        "pour obtenir une analyse Réparer vs Remplacer."
                    ),
                    tools_executed=[],
                    replace_recommendations=[],
                    strategic_action_plan=[
                        "Transmettre les historiques Laravel (coûts de réparation, pannes, jours sans eau) pour chaque école du district",
                        "Préciser le district ciblé et la question budgétaire (remplacement, maintenance, achat groupé)",
                        "Relancer l'analyse une fois les données complétées",
                    ],
                    data_source="empty",
                    warnings=[
                        "Aucune donnée d'historique fournie — réponse d'abstention, aucune recommandation calculée."
                    ],
                    next_action="Fournissez schools_data (historiques Laravel) puis relancez la requête.",
                )

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

        raw_reply = await self.llm.generate_json(
            prompt=context_prompt,
            system=DECISION_COPILOT_SYSTEM + "\nRéponds avec un JSON : {\"answer\": \"texte du rapport\", \"action_plan\": [\"point 1\", \"point 2\", \"point 3\"]}"
        )

        degraded = False
        answer_text = raw_reply.get("answer")
        if not answer_text or len(str(answer_text)) < 50:
            # Fallback structuré (LLM muet) : chiffres déterministes, marqué dégradé.
            degraded = True
            answer_text = (
                "Réponse de secours sans LLM — chiffres issus des tools déterministes. "
                f"Sur les {len(schools_data)} écoles analysées, **{len(replace_targets)} établissement(s)** ont franchi le seuil critique d'inefficacité budgétaire. "
                f"Dans ces écoles, les factures de réparations successives représentent plus de {DECISION_REPLACE_MIN_RATIO_PCT:g}% du prix d'une installation neuve. "
                f"Nous recommandons un **remplacement immédiat par des forages solaires** pour éliminer les pannes chroniques et sécuriser l'eau des élèves."
            )

        actions = raw_reply.get("action_plan")
        if not isinstance(actions, list) or not actions:
            degraded = True
            actions = [
                f"Inscrire en priorité d'investissement Capex les écoles : {', '.join([a.school_name for a in replace_targets]) if replace_targets else 'Aucune urgence absolue'}",
                f"Geler les bons de commande de réparations palliatives pour les équipements ayant dépassé {DECISION_REPLACE_MIN_RATIO_PCT:g}% de ratio de vétusté",
                "Négocier un contrat d'achat groupé de kits solaires pour réduire les coûts unitaires de 20%"
            ]

        return DecisionCopilotResponse(
            answer=str(answer_text),
            tools_executed=tools_used,
            replace_recommendations=analyses,
            strategic_action_plan=actions,
            data_source="real",
            warnings=(
                ["Réponse de secours sans LLM — chiffres issus des tools déterministes."]
                if degraded else []
            ),
            next_action=(
                "Réveillez le modèle via POST /v1/admin/warmup puis relancez pour une synthèse complète."
                if degraded else ""
            ),
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
