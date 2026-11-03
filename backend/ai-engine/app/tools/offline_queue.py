"""Plugin outil : etat de la file d'attente hors-ligne (synchro + connectivite).

Lit le contexte Laravel (cles "offline_queue" et "sync_status") sans reseau
ni LLM. Ne couvre QUE le non-synchronise : jamais les incidents synchronises.
"""
from __future__ import annotations

from typing import Any

from ..schemas import AgentCard
from ..tool_consts import tool_lang

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


_URGENCES_SYSTEME = frozenset({"low", "medium", "high", "critical"})


def _pending_urgency(row: dict[str, Any]) -> str | None:
    """Urgence normalisée (liste blanche, jamais inventée : None sinon)."""
    raw = row.get("urgency")
    if raw is None:
        raw = row.get("urgency_level")
    low = str(raw or "").strip().lower()
    return low if low in _URGENCES_SYSTEME else None


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
    category = row.get("category") or row.get("issue_type")
    category = str(category).strip().lower() or None if category is not None else None
    affected = row.get("affected_students")
    return {
        "id": pid,
        "school": school,
        "summary": summary,
        "created_at": created_at,
        "status": status,
        "urgency": _pending_urgency(row),
        "category": category,
        "affected_students": affected,
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
        use_en = tool_lang(context) == "en"
        has_queue = "offline_queue" in context
        has_sync = "sync_status" in context
        if not has_queue and not has_sync:
            err = ("Offline queue unknown: the context holds neither "
                   "'offline_queue' nor 'sync_status'. Reconnect or "
                   "name the school concerned.") if use_en else (
                       "File hors-ligne inconnue : le contexte ne contient ni "
                       "'offline_queue' ni 'sync_status'. Reconnectez-vous ou "
                       "precisez l'ecole concernee.")
            return {"error": err}
        raw_queue = context.get("offline_queue", [])
        if not isinstance(raw_queue, list):
            raw_queue = []
        pending = [
            _pending_of(row) for row in raw_queue if isinstance(row, dict)
        ]
        count = len(pending)
        online, last_sync = _sync_of(context.get("sync_status"))
        if use_en:
            if count == 0:
                if online:
                    insight = ("Offline queue empty: everything synced, "
                               "connection active.")
                else:
                    insight = ("Offline queue empty, but device offline: the "
                               "next reports will wait to be sent.")
            elif count == 1:
                first = pending[0]
                where = f" ({first.get('school')})" if first.get("school") else ""
                if online:
                    insight = (f"1 report waiting for synchronisation{where}: "
                               "connection active, sending soon.")
                else:
                    insight = (f"1 report waiting for synchronisation{where}: "
                               "device offline, it will go out on reconnection.")
            elif online:
                insight = (f"{count} reports waiting for synchronisation: "
                           "connection active, sending soon.")
            else:
                insight = (f"{count} reports waiting for synchronisation: "
                           "device offline, they will go out on reconnection.")
        elif count == 0:
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
        if count >= 1:
            n_crit = sum(1 for p in pending if p.get("urgency") == "critical")
            n_high = sum(1 for p in pending if p.get("urgency") == "high")
            severe: list[str] = []
            if use_en:
                if n_crit:
                    severe.append(f"{n_crit} critical")
                if n_high:
                    severe.append(f"{n_high} high urgency")
                if severe:
                    insight += f" Of which {' and '.join(severe)}."
            else:
                if n_crit:
                    severe.append(f"{n_crit} critique{'s' if n_crit > 1 else ''}")
                if n_high:
                    many = n_high > 1
                    severe.append(f"{n_high} haute{'s' if many else ''} "
                                  f"urgence{'s' if many else ''}")
                if severe:
                    insight += f" Dont {' et '.join(severe)}."
        if last_sync:
            insight += (f" Last sync: {last_sync}." if use_en
                        else f" Derniere synchro : {last_sync}.")
        result: dict[str, Any] = {
            "insight": insight,
            "pending": pending,
            "count": count,
            "online": online,
            "lang": "en" if use_en else "fr",
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
    use_en = str(obs.get("lang") or "fr").lower().startswith("en")
    return AgentCard(
        type="offline_queue",
        title="Offline queue" if use_en else "File hors-ligne",
        data=obs,
    )


CARD_BUILDERS = {"offline_queue": _build_offline_queue_card}
