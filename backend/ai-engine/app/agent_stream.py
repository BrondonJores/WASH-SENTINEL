"""Streaming SSE des réponses Sentinel (transparence des outils en temps réel).

Ce module entoure la boucle existante sans la modifier : il exécute
``AgentLoop.chat()`` (entrée publique de ``app/agent_loop.py``) puis rejoue
le résultat sous forme d'événements SSE ::

    {"event": "tools", "tools": [...]}          dès que les outils sont connus
    {"event": "cards", "cards": [...]}          cartes structurées
    {"event": "delta", "text": "..."}           réponse découpée (~40 car.)
    {"event": "done", "model": ..., "follow_ups": [...]}

L'ordre tools -> [cards] -> deltas -> done est garanti.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from .agent_loop import AgentLoop
from .schemas import AgentChatRequest

CHUNK_SIZE = 40


async def stream_agent_events(
    loop: AgentLoop,
    req: AgentChatRequest,
    chunk_size: int = CHUNK_SIZE,
) -> AsyncIterator[dict[str, Any]]:
    """Exécute la boucle existante puis yield les events SSE (dicts)."""
    result = await loop.chat(req)

    yield {"event": "tools", "tools": list(result.tools_executed)}

    yield {
        "event": "cards",
        "cards": [card.model_dump() for card in result.cards],
    }

    answer = result.answer or ""
    for start in range(0, len(answer), chunk_size):
        yield {"event": "delta", "text": answer[start:start + chunk_size]}

    yield {
        "event": "done",
        "model": result.model_used,
        "follow_ups": list(result.follow_ups),
    }


def format_sse(payload: dict[str, Any]) -> str:
    """Formate un event dict en trame SSE (named event + data JSON)."""
    name = str(payload.get("event", "message"))
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
