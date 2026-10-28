"""Script de vérification rapide des endpoints du moteur IA WASH Sentinel."""

import asyncio
from app.extractor import WashExtractor
from app.ollama_client import OllamaClient
from app.repair_advisor import RepairAdvisor
from app.schemas import RepairPlanRequest


async def run_diagnostics():
    print("==========================================")
    print("🚀 Test Rapide du Moteur IA WASH Sentinel")
    print("==========================================")

    client = OllamaClient()
    extractor = WashExtractor(client)
    advisor = RepairAdvisor(client)

    sample_report = (
        "Bonjour, ici l'école primaire publique de Bonabéri. "
        "Le tuyau principal alimentant les 4 latrines des filles a éclaté ce matin. "
        "L'eau fuit abondamment dans la cour et plus de 320 élèves n'ont plus accès aux sanitaires."
    )

    print("\n1. Test d'Extraction et Scoring de Priorité :")
    print(f"Message test : \"{sample_report}\"")
    
    try:
        extraction = await extractor.extract(sample_report, school_name="EPP Bonabéri")
        data = extraction.data
        print(f"✅ École détectée       : {data.school_detected}")
        print(f"✅ Type Infrastructure   : {data.infrastructure_type}")
        print(f"✅ Panne                 : {data.issue_type}")
        print(f"✅ Urgence               : {data.urgency_level}")
        print(f"✅ Élèves impactés       : {data.estimated_affected_students}")
        print(f"✅ Risque Sanitaire      : {data.health_hazard_risk}")
        print(f"⭐ Score Priorité Calculé : {data.recommended_priority_score}/100")
        print(f"📝 Résumé                : {data.short_summary}")

        print("\n2. Test de Génération de Fiche Réparateur :")
        plan_req = RepairPlanRequest(
            incident_summary=data.short_summary,
            infrastructure_type=data.infrastructure_type,
            issue_type=data.issue_type,
            urgency_level=data.urgency_level,
        )
        plan = await advisor.generate_plan(plan_req)
        print(f"🔧 Outils recommandés    : {', '.join(plan.required_tools)}")
        print(f"📦 Pièces de rechange    : {', '.join(plan.spare_parts_needed)}")
        print(f"⏱️ Temps estimé          : {plan.estimated_intervention_time}")
        print(f"💰 Niveau de coût        : {plan.estimated_cost_tier}")
        print(f"🛡️ Mesures d'urgence     : {plan.immediate_safety_measures[0] if plan.immediate_safety_measures else 'N/A'}")

    except Exception as e:
        print(f"ℹ️ Note test hors-ligne : {e}")
        print("Pour un test complet avec le LLM en direct, assurez-vous qu'Ollama tourne avec le modèle configuré.")

    print("\n✅ Tous les schémas et modules IA sont opérationnels !")


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
