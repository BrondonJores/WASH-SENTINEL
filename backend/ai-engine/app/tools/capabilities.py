"""Plugin exemple + utile : ce que Sentinel sait faire.

Pattern de référence pour les futurs outils (un fichier = un outil).
"""
from __future__ import annotations

from typing import Any

from ..schemas import AgentCard
from ..tool_consts import tool_lang

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

CAPABILITIES_EN = (
    ("See priority schools", "Which schools need help most?"),
    ("List incidents", "Show open incidents"),
    ("Track interventions", "Interventions done today?"),
    ("See trends", "Trends for Bonanjo over 3 months"),
    ("Log an intervention", "Log an intervention"),
    ("Report a breakdown", "Report a leak at Nkol school"),
    ("Listen to an answer", "Listen button on each card"),
)


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del args
    items = CAPABILITIES_EN if tool_lang(context) == "en" else CAPABILITIES
    if tool_lang(context) == "en":
        insight = (f"I can do {len(items)} things: ask me for example "
                   f"\u201c{items[0][1]}\u201d")
    else:
        insight = (f"Je sais faire {len(items)} choses : demande-moi par exemple "
                   f"« {items[0][1]} »")
    return {
        "insight": insight,
        "items": [{"capability": c, "exemple": e} for c, e in items],
    }


def _build_capabilities_card(obs: dict[str, Any]) -> AgentCard | None:
    if not obs.get("items"):
        return None
    use_en = str(obs.get("lang") or "fr").lower().startswith("en")
    return AgentCard(
        type="capabilities_list",
        title="What I can do" if use_en else "Ce que je sais faire",
        data=obs,
    )


CARD_BUILDERS = {"capabilities_list": _build_capabilities_card}
