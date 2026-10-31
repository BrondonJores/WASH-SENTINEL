"""Plugin outil : etat de la file d'attente hors-ligne (synchro + connectivite).

Lit le contexte Laravel (cles "offline_queue" et "sync_status") sans reseau
ni LLM. Ne couvre QUE le non-synchronise : jamais les incidents synchronises.
"""
from __future__ import annotations

from typing import Any

from ..schemas import AgentCard

TOOL_NAME = "offline_queue"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Etat de la file d'attente HORS-LIGNE : signalements en attente de "
        "synchronisation (non envoyes) et connectivite (en ligne / hors-ligne, "
        "derniere synchro). A utiliser quand l'utilisateur demande ce qui est "
        "en attente d'envoi, la file hors-ligne, les signalements non "
        "synchronises, ou s'il y a du reseau. "
        "Exemple : 'Quels signalements sont en attente de synchro ?' -> "
        "offline_queue({}). "
        "Ne JAMAIS utiliser pour lister les incidents synchronises ni "
        "l'historique des interventions deja realisees (utiliser "
        "list_maintenance_logs, rank_schools_by_need ou explain_incident)."
    ),
    "parameters": {"type": "object", "properties": {}},
}

READ_ONLY = True

# Indices minuscules, formes sans-accent doublees (comparaison par sous-chaine
# dans route_intent). Verifie : aucun n'est sous-chaine d'un phrase legacy
# create/other (tests/test_prompt_eval.py ROUTING_CASES + GOLDEN_CASES,
# tests/test_agent_loop.py RouteIntentTest).
INTENT_HINTS = frozenset({
    "hors ligne",
    "hors-ligne",
    "offline",
    "file d'attente",
    "file dattente",
    "en attente",
    "synchronisation",
    "synchroniser",
    "synchronise",
    "synchronisé",
    "synchro",
    "pas de réseau",
    "pas de reseau",
    "pas de connexion",
    "sans connexion",
    "à envoyer",
    "a envoyer",
})


def _pending_of(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise un element de la file (cles id|temp_id, school, summary...)."""
    pid = row.get("id")
    if pid is None:
        pid = row.get("temp_id")
    school = row.get("school") or row.get("school_name") or row.get("ecole")
    summary = row.get("summary") or row.get("title") or row.get("description")
    created_at = (
        row.get("created_at") or row.get("createdAt") or row.get("date")
    )
    status = row.get("status") or "pending"
    return {
        "id": pid,
        "school": school,
        "summary": summary,
        "created_at": created_at,
        "status": status,
    }


def _sync_of(raw: Any) -> tuple[bool, Any]:
    """Extrait (online, last_sync) depuis sync_status (dict ou [dict])."""
    if isinstance(raw, bool):
        return raw, None
    data: dict[str, Any] | None = None
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                data = entry
                break
    if data is None:
        return True, None
    online = bool(data.get("online", True))
    last_sync = (
        data.get("last_sync") or data.get("lastSync")
        or data.get("last_synchronisation")
    )
    return online, last_sync


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Etat de la file hors-ligne (deterministe, synchrone, sans reseau/LLM)."""
    try:
        if not isinstance(args, dict):
            args = {}
        if not isinstance(context, dict):
            context = {}
        del args
        has_queue = "offline_queue" in context
        has_sync = "sync_status" in context
        if not has_queue and not has_sync:
            return {"error": (
                "File hors-ligne inconnue : le contexte ne contient ni "
                "'offline_queue' ni 'sync_status'. Reconnectez-vous ou "
                "precisez l'ecole concernee."
            )}
        raw_queue = context.get("offline_queue", [])
        if not isinstance(raw_queue, list):
            raw_queue = []
        pending = [
            _pending_of(row) for row in raw_queue if isinstance(row, dict)
        ]
        count = len(pending)
        online, last_sync = _sync_of(context.get("sync_status"))
        if count == 0:
            if online:
                insight = (
                    "File hors-ligne vide : tout est synchronise, "
                    "connexion active."
                )
            else:
                insight = (
                    "File hors-ligne vide, mais appareil hors-ligne : les "
                    "prochains signalements resteront en attente d'envoi."
                )
        elif count == 1:
            first = pending[0]
            where = f" ({first.get('school')})" if first.get("school") else ""
            if online:
                insight = (
                    f"1 signalement en attente de synchronisation{where} : "
                    "connexion active, envoi imminent."
                )
            else:
                insight = (
                    f"1 signalement en attente de synchronisation{where} : "
                    "appareil hors-ligne, il partira a la reconnexion."
                )
        else:
            if online:
                insight = (
                    f"{count} signalements en attente de synchronisation : "
                    "connexion active, envoi imminent."
                )
            else:
                insight = (
                    f"{count} signalements en attente de synchronisation : "
                    "appareil hors-ligne, ils partiront a la reconnexion."
                )
        if last_sync:
            insight += f" Derniere synchro : {last_sync}."
        result: dict[str, Any] = {
            "insight": insight,
            "pending": pending,
            "count": count,
            "online": online,
        }
        if last_sync is not None:
            result["last_sync"] = last_sync
        return result
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _build_offline_queue_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict):
        return None
    if obs.get("error"):
        return None
    if "pending" not in obs and "count" not in obs:
        return None
    return AgentCard(
        type="offline_queue",
        title="File hors-ligne",
        data=obs,
    )


CARD_BUILDERS = {"offline_queue": _build_offline_queue_card}
