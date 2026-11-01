from __future__ import annotations

"""Inspection visuelle WASH : chaine vision configurable + repli gracieux.

Chaine configurable (machines faibles, 2 Go VRAM)
-------------------------------------------------
Le modele vision se regle via la variable d'environnement ``OLLAMA_VISION_MODEL``
(meme pattern ``OLLAMA_*`` que :class:`app.providers.OllamaProvider`, qui lit deja
cette variable). Priorite : parametre explicite > variable d'env > defaut.

Deploiement cible 2 Go VRAM :
  export OLLAMA_VISION_MODEL=moondream
  ollama pull moondream

LOT 5 : UN SEUL défaut vision (``moondream``), défini dans
:mod:`app.providers` (``DEFAULT_VISION_MODEL``) et réexporté ici : le provider
Ollama et cet analyseur ne divergent plus. Choix documenté : les tests
épinglent ``moondream`` (cf. tests/test_image_vision.py) et la cible reste
2 Go VRAM. Sur grosses machines : ``OLLAMA_VISION_MODEL=llama3.2-vision:11b``
(ancien défaut du provider, ~7,9 Go, ne passe PAS en 2 Go VRAM).

Alternatives (tailles approximatives vues dans ``ollama list``) :
  - ``moondream`` (~1,7 Go) — DEFAUT UNIQUE ; suivi d'instructions
    correct en vision legere, JSON generalement propre.
  - ``llava:7b`` (~4,7 Go) — qualite superieure mais ne tient pas en 2 Go VRAM.
  - ``llama3.2-vision:11b`` (~7,9 Go) — ancien defaut du provider ; ne passe
    PAS sur 2 Go VRAM (accessible via ``OLLAMA_VISION_MODEL``).

Repli gracieux
--------------
``analyze()`` ne leve jamais pour une panne vision (modele absent, 404, timeout,
reponse invalide) : il renvoie un diagnostic explicite marque
``"vision indisponible"``. Le schema ``ImageAnalysisResponse`` imposant un float
pour ``visual_severity_score``, ce champ vaut 0.0 en repli MAIS ne doit jamais
etre interprete comme un vrai score : l'appelant (triage) doit passer par
``visual_severity()`` qui renvoie ``None`` dans ce cas, puis
``visual_boost(None)`` qui vaut 0.0. Aucun score n'est invente : sans vision,
le triage continue sur le texte seul.
"""

import base64
import os

from .providers import (
    DEFAULT_VISION_MODEL,  # réexporté (LOT 5 : défaut unique moondream)
    VISION_MODEL_ENV_VAR,  # réexporté (nom de l'ENV, source unique)
    BaseLLMProvider,
)
from .schemas import ImageAnalysisResponse

__all__ = [
    "DEFAULT_VISION_MODEL",
    "VISION_MODEL_ENV_VAR",
    "VISION_UNAVAILABLE_MARKER",
    "WASH_VISION_SYSTEM",
    "ImageAnalyzer",
    "is_vision_unavailable",
    "resolve_vision_model",
    "vision_unavailable_response",
    "visual_boost",
    "visual_severity",
]

VISION_UNAVAILABLE_MARKER = "vision indisponible"

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


def resolve_vision_model(explicit: str | None = None) -> str:
    """Resout le modele vision : explicite > ``OLLAMA_VISION_MODEL`` > defaut leger."""
    if explicit:
        return explicit
    return os.getenv(VISION_MODEL_ENV_VAR, DEFAULT_VISION_MODEL) or DEFAULT_VISION_MODEL


def _vision_next_action(reason: str) -> str:
    """Prochaine action operateur selon la cause probable de la panne vision."""
    low = reason.lower()
    if "image vide" in low:
        return "Fournissez une photo nette de l'infrastructure."
    if any(k in low for k in ("introuvable", "404", "pull", "connexion", "connect")):
        return "Vérifiez le modèle vision ('ollama list' / 'ollama pull <modèle>') puis réessayez, ou continuez sans photo."
    if any(k in low for k in ("timeout", "délai", "delai", "timed out", "408", "warmup")):
        return "Réveillez le modèle via POST /v1/admin/warmup puis réessayez."
    if "score" in low or "vide ou invalide" in low:
        return "Reprenez la photo de près, nette et bien cadrée."
    return "Reprenez la photo ou continuez sans la vision."


def vision_unavailable_response(reason: str) -> ImageAnalysisResponse:
    """Diagnostic explicite de panne vision (jamais de score invente).

    ``visual_severity_score`` vaut 0.0 uniquement parce que le schema l'impose ;
    les appelants doivent utiliser ``visual_severity()`` (qui renvoie ``None``)
    et non ce champ.
    """
    message = f"{VISION_UNAVAILABLE_MARKER} : {reason}"
    next_action = _vision_next_action(reason)
    return ImageAnalysisResponse(
        is_wash_related=False,
        infrastructure_detected=VISION_UNAVAILABLE_MARKER,
        visible_damage=message[:300],
        visual_severity_score=0.0,
        health_hazard_detected=False,
        technician_notes=f"{message} — {next_action}",
        vision_unavailable=True,
        vision_error=reason[:300],
        next_action=next_action,
    )


def is_vision_unavailable(response: ImageAnalysisResponse) -> bool:
    """Vrai si le diagnostic est un repli « vision indisponible » (pas un 0 legitime)."""
    haystack = " ".join((
        response.infrastructure_detected,
        response.visible_damage,
        response.technician_notes,
    ))
    return VISION_UNAVAILABLE_MARKER in haystack


def visual_severity(response: ImageAnalysisResponse) -> int | None:
    """Severite visuelle entiere 0..100, ou ``None`` si la vision est indisponible.

    Seule lecture legitime du score pour le triage : distingue le 0 honnete
    (photo hors-sujet confirmee par le modele) du repli (panne vision).
    """
    if is_vision_unavailable(response):
        return None
    return int(round(max(0.0, min(100.0, response.visual_severity_score))))


def visual_boost(severity: int | None) -> float:
    """Bonus de priorite apporte par la vision, entre 0.0 et 15.0.

    - ``None`` (vision indisponible) -> 0.0 : le triage texte est inchange.
    - 0 -> 0.0, 100 -> 15.0, lineaire entre les deux (``round(s * 0.15, 1)``).
    - Monotone (croissante au sens large) : une severite plus haute ne donne
      jamais un bonus plus faible. La severite est bornee a 0..100.
    - N'est qu'un bonus additif ; le calcul de priorite existant est inchange
      (le triage borne le total a 100).
    """
    if severity is None:
        return 0.0
    clamped = max(0, min(100, round(severity)))
    return round(clamped * 0.15, 1)


class ImageAnalyzer:
    """Analyse une photo via le provider vision ; repli gracieux en cas de panne.

    :param llm: provider LLM (``OllamaProvider`` lit deja ``OLLAMA_VISION_MODEL``).
    :param vision_model: surcharge explicite ; ecrit aussi ``llm.vision_model``
        pour que l'appel effectif utilise vraiment ce modele.
    """

    def __init__(self, llm: BaseLLMProvider, vision_model: str | None = None):
        self.llm = llm
        if vision_model:
            self.vision_model = vision_model
            try:
                self.llm.vision_model = vision_model
            except (AttributeError, TypeError):
                pass
        else:
            self.vision_model = getattr(llm, "vision_model", None) or resolve_vision_model()

    async def analyze(self, image_bytes: bytes) -> ImageAnalysisResponse:
        """Analyse la photo ; en cas de panne vision, repli explicite (sans lever)."""
        if not image_bytes:
            return vision_unavailable_response("image vide fournie")
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        try:
            raw = await self.llm.generate_vision_json(
                prompt="Analyse cette photo de panne sanitaire/hydraulique d'école.",
                image_base64=b64_img,
                system=WASH_VISION_SYSTEM,
            )
        except Exception as exc:
            return vision_unavailable_response(f"{type(exc).__name__}: {str(exc)[:200]}")
        if not isinstance(raw, dict) or not raw:
            return vision_unavailable_response("réponse vision vide ou invalide")

        is_wash = bool(raw.get("is_wash_related", True))
        if not is_wash:
            # Anti-spam : photo hors-sujet confirmée par le modèle -> 0 honnête.
            score = 0.0
        else:
            try:
                score_raw = raw.get("visual_severity_score")
                score = float(score_raw) if score_raw is not None else None
            except (TypeError, ValueError):
                score = None
            if score is None or score != score:  # None ou NaN : pas de score inventé
                return vision_unavailable_response("score de sévérité visuelle absent de la réponse modèle")
            score = max(0.0, min(100.0, score))

        return ImageAnalysisResponse(
            is_wash_related=is_wash,
            infrastructure_detected=str(raw.get("infrastructure_detected", "Infrastructure WASH")),
            visible_damage=str(raw.get("visible_damage", "Dégât constaté")),
            visual_severity_score=score,
            health_hazard_detected=bool(raw.get("health_hazard_detected", False)),
            technician_notes=str(raw.get("technician_notes", "Inspecter les raccordements et sécuriser la zone")),
        )
