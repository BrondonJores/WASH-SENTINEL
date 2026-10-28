from __future__ import annotations

from .ollama_client import OllamaClient
from .schemas import EpidemicClusterRequest, EpidemicClusterResponse

EPIDEMIC_ANALYZER_SYSTEM = """
Tu es l'épidémiologiste et expert en santé publique de WASH Sentinel.
Ton rôle est d'analyser un lot de signalements récents dans un district scolaire pour détecter si une grappe d'incidents (cluster) trahit un risque sanitaire majeur ou une épidémie imminente (choléra, dysenterie, contamination de nappe phréatique).

Renvoie STRICTEMENT un JSON valide :
{
  "risk_level": "normal | moderate | high | outbreak_warning",
  "alert_triggered": boolean (true si au moins 2 écoles ont des pannes critiques simultanées ou des signes de contamination de l'eau/latrines),
  "epidemic_syndrome": "string ou null (ex: Risque élevé d'épidémie de choléra par contamination de la nappe)",
  "recommended_health_actions": ["liste d'actions d'urgence, ex: Déploiement de kits de chloration Aquatabs, fermeture temporaire des points d'eau incriminés, prélèvements bactériologiques d'urgence"]
}

Règles :
1. Déclenche "outbreak_warning" dès que plusieurs écoles du même secteur rapportent une eau impropre à la consommation ou des latrines débordantes.
2. Uniquement du JSON.
"""


class EpidemicDetector:
    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama

    async def detect_cluster(self, req: EpidemicClusterRequest) -> EpidemicClusterResponse:
        count = len(req.recent_incidents)
        if count == 0:
            return EpidemicClusterResponse(
                district=req.district,
                incident_count=0,
                risk_level="normal",
                alert_triggered=False,
                epidemic_syndrome=None,
                recommended_health_actions=[],
            )

        incidents_summary = "\n".join([
            f"- École: {inc.school_name} | Catégorie: {inc.category} | Panne: {inc.summary} | Date: {inc.reported_at}"
            for inc in req.recent_incidents
        ])

        prompt = f"""
District analysé : {req.district}
Nombre d'incidents récents : {count}
Signalements :
{incidents_summary}
        """

        raw = await self.ollama.generate_json(prompt, EPIDEMIC_ANALYZER_SYSTEM)

        risk_level = str(raw.get("risk_level", "moderate")).lower()
        if risk_level not in ["normal", "moderate", "high", "outbreak_warning"]:
            risk_level = "moderate" if count >= 2 else "normal"

        actions = raw.get("recommended_health_actions")
        if not isinstance(actions, list) or not actions:
            actions = [
                "Distribution d'urgence de pastilles de purification d'eau (Aquatabs)",
                "Sensibilisation immédiate au lavage des mains au savon dans les classes",
                "Inspection sanitaire de la source d'approvisionnement communale"
            ]

        return EpidemicClusterResponse(
            district=req.district,
            incident_count=count,
            risk_level=risk_level,
            alert_triggered=bool(raw.get("alert_triggered", count >= 3)),
            epidemic_syndrome=raw.get("epidemic_syndrome") if raw.get("alert_triggered") else None,
            recommended_health_actions=actions if raw.get("alert_triggered") else [],
        )
