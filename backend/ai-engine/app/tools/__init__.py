"""Tools plugins auto-découverts : un fichier = un outil, zéro conflit.

CONTRAT (chaque module app/tools/<nom>.py doit définir) :
  TOOL_NAME: str            — nom unique, snake_case (ex: "list_incidents").
  TOOL_DEF: dict            — définition function-calling {"name", "description", "parameters"}.
                              Description FR : dire QUAND utiliser l'outil + 1 exemple + clause
                              "Ne JAMAIS utiliser pour ..." (anti-confusion).
  READ_ONLY: bool           — True = lecture seule (routée "list", garde-fou OK).
                              Un outil d'écriture DOIT s'appeler prepare_* et rester
                              un dossier SANS écriture (confirmation humaine obligatoire).
  INTENT_HINTS: frozenset[str] — indices minuscules pour route_intent (sans-accent doublés).
  CARD_BUILDERS: dict[str, Callable[[dict], AgentCard | None]]
                            — type_carte -> builder(observation). Builder pur, défensif
                              (asRecord/asArray style : .get partout, None si vide).
  def execute(args: dict, context: dict) -> dict:
                            — DÉTERMINISTE, SYNCHRONE, SANS RÉSEAU, SANS LLM.
                              Retourne {"insight": str, ...} ou {"error": str}.
                              Jamais d'exception vers la boucle (try/except -> error).

INTERDITS : importer app.agent_tools ou app.agent_loop (circulaire) — tout helper
  nécessaire est dupliqué localement ; toucher à un autre fichier (conflits).
  Les modules engine (epidemic_detector, rag_store, ...) sont autorisés en
  lecture de leurs parties DÉTERMINISTES synchrones uniquement.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any

REQUIRED_ATTRS = ("TOOL_NAME", "TOOL_DEF", "execute")


def discover_tools() -> list[dict[str, Any]]:
    """Charge tous les plugins app/tools/*.py (sauf __init__)."""
    bundles: list[dict[str, Any]] = []
    skipped: list[str] = []
    package = __name__
    for info in pkgutil.iter_modules(__path__, package + "."):
        module = importlib.import_module(info.name)
        try:
            for attr in REQUIRED_ATTRS:
                if not hasattr(module, attr):
                    raise AttributeError(f"{info.name}: {attr} manquant")
            name = str(module.TOOL_NAME)
            if name in ("", None) or not isinstance(module.TOOL_DEF, dict):
                raise ValueError(f"{info.name}: TOOL_NAME/TOOL_DEF invalide")
            if not callable(module.execute):
                raise ValueError(f"{info.name}: execute non appelable")
            bundles.append({
                "name": name,
                "def": dict(module.TOOL_DEF),
                "execute": module.execute,
                "hints": frozenset(module.INTENT_HINTS or frozenset()),
                "cards": dict(module.CARD_BUILDERS or {}),
                "read_only": bool(getattr(module, "READ_ONLY", True)),
            })
        except Exception as exc:  # pragma: no cover - robustesse chargement
            skipped.append(f"{info.name}: {exc}")
    bundles.sort(key=lambda b: b["name"])
    if skipped:
        import logging
        logging.getLogger(__name__).warning("plugins ignorés : %s", skipped)
    return bundles
