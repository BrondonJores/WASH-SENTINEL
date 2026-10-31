"""Plugin exemple + utile : ce que Sentinel sait faire.

Pattern de référence pour les futurs outils (un fichier = un outil).
"""
from __future__ import annotations

from typing import Any

from ..schemas import AgentCard

TOOL_NAME = "capabilities"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Dit ce que Sentinel sait faire : liste des capacités avec des exemples "
        "de questions. À utiliser quand l'utilisateur demande 'que sais-tu faire', "
        "'aide-moi', 'comment ça marche'. "
        "Exemple : 'Que peux-tu faire pour moi ?' -> capabilities({}). "
        "Ne JAMAIS utiliser pour répondre à une question de données "
        "(écoles, incidents, tendances : utiliser les outils de lecture)."
    ),
    "parameters": {"type": "object", "properties": {}},
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "que sais-tu faire", "que sais tu faire", "tes capacités", "tes capacites",
    "aide-moi", "aide moi", "aidez-moi", "aidez moi",
    "comment ça marche", "comment ca marche",
    "tu peux faire quoi", "que peux-tu faire", "mode d'emploi", "mode demploi",
})

CAPABILITIES = (
    ("Voir les écoles prioritaires", "Quelles écoles ont le plus besoin d'aide ?"),
    ("Lister les incidents", "Montre les incidents ouverts"),
    ("Suivre les interventions", "Interventions réalisées aujourd'hui ?"),
    ("Voir les tendances", "Tendances de Bonanjo sur 3 mois"),
    ("Enregistrer une intervention", "Enregistre une intervention"),
    ("Signaler une panne", "Signale une fuite à l'école de Nkol"),
    ("Écouter une réponse", "Bouton Écouter sur chaque carte"),
)


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del args, context
    return {
        "insight": f"Je sais faire {len(CAPABILITIES)} choses : demande-moi par exemple « {CAPABILITIES[0][1]} »",
        "items": [{"capability": c, "exemple": e} for c, e in CAPABILITIES],
    }


def _build_capabilities_card(obs: dict[str, Any]) -> AgentCard | None:
    if not obs.get("items"):
        return None
    return AgentCard(
        type="capabilities_list",
        title="Ce que je sais faire",
        data=obs,
    )


CARD_BUILDERS = {"capabilities_list": _build_capabilities_card}
