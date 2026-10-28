from __future__ import annotations

import base64
from .providers import BaseLLMProvider
from .schemas import ImageAnalysisResponse

WASH_VISION_SYSTEM = """
Tu es l'expert en inspection visuelle de WASH Sentinel.
Ton rôle est d'analyser la photo d'un incident hydraulique ou sanitaire dans une école et de renvoyer STRICTEMENT un JSON valide :

{
  "is_wash_related": boolean (true si l'image montre une borne fontaine, pompe, latrines, lavabo, canalisation, fuite, cuve),
  "infrastructure_detected": "string (ex: Pompe manuelle India Mark II, Latrines à fosse, Robinetterie, Tuyauterie PVC)",
  "visible_damage": "string (ex: Fissure nette sur le conduit, cuve fêlée, fosse débordante)",
  "visual_severity_score": float entre 0.0 et 100.0,
  "health_hazard_detected": boolean (true si eau croupie, boue stagnante ou matières fécales visibles),
  "technician_notes": "string (conseil technique immédiat pour l'équipe de réparation)"
}

Règles :
1. Si l'image n'a rien à voir avec l'eau ou l'hygiène, mets "is_wash_related": false et visual_severity_score: 0.0.
2. Sois précis et concis. Uniquement du JSON.
"""


class ImageAnalyzer:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def analyze(self, image_bytes: bytes) -> ImageAnalysisResponse:
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        raw = await self.llm.generate_vision_json(
            prompt="Analyse cette photo de panne sanitaire/hydraulique d'école.",
            image_base64=b64_img,
            system=WASH_VISION_SYSTEM,
        )

        return ImageAnalysisResponse(
            is_wash_related=bool(raw.get("is_wash_related", True)),
            infrastructure_detected=str(raw.get("infrastructure_detected", "Infrastructure WASH")),
            visible_damage=str(raw.get("visible_damage", "Dégât constaté")),
            visual_severity_score=float(raw.get("visual_severity_score", 60.0)),
            health_hazard_detected=bool(raw.get("health_hazard_detected", False)),
            technician_notes=str(raw.get("technician_notes", "Inspecter les raccordements et sécuriser la zone")),
        )
