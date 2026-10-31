"""Observabilite IA — latences et tokens des operations LLM (stdlib uniquement).

Usage typique dans un endpoint::

    from .ai_metrics import timed

    with timed("extract"):
        result = await extractor.extract(req.raw_text)

Le buffer circulaire garde les 500 dernieres operations (thread-safe).
``summary()`` alimente l'endpoint GET /v1/admin/ai-metrics.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from contextlib import contextmanager
from time import perf_counter, time
from typing import Any, Iterator

__all__ = ["MAX_ENTRIES", "record", "timed", "summary", "reset"]

MAX_ENTRIES = 500

_lock = threading.Lock()
_buffer: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)


def record(
    operation: str,
    seconds: float,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> dict[str, Any]:
    """Enregistre une operation. Les compteurs tokens sont optionnels (None-safe)."""
    entry = {
        "operation": operation,
        "seconds": float(seconds),
        "duration_ms": round(float(seconds) * 1000.0, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "timestamp": time(),
    }
    with _lock:
        _buffer.append(entry)
    return dict(entry)


@contextmanager
def timed(operation: str) -> Iterator[dict[str, Any]]:
    """Context manager : mesure la duree (secondes) et l'enregistre via ``record``.

    Yields un dict mutable ``ctx`` : poser ``ctx["prompt_tokens"]`` /
    ``ctx["completion_tokens"]`` avant la sortie pour les attacher a l'entree.
    Enregistre meme si le bloc leve (utile pour mesurer les echecs).
    """
    ctx: dict[str, Any] = {}
    start = perf_counter()
    try:
        yield ctx
    finally:
        record(
            operation,
            perf_counter() - start,
            prompt_tokens=ctx.get("prompt_tokens"),
            completion_tokens=ctx.get("completion_tokens"),
        )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Percentile par methode nearest-rank (ceil(p*n) - 1). Liste triee requise."""
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil((pct / 100.0) * len(sorted_values)))
    return sorted_values[min(rank - 1, len(sorted_values) - 1)]


def _stats(durations_ms: list[float]) -> dict[str, Any]:
    ordered = sorted(durations_ms)
    count = len(ordered)
    return {
        "count": count,
        "avg_ms": round(sum(ordered) / count, 3) if count else 0.0,
        "p95_ms": round(_percentile(ordered, 95), 3),
    }


def summary() -> dict[str, Any]:
    """Agrege le buffer : ``{by_operation: {op: {count, avg_ms, p95_ms}}, totals}``."""
    with _lock:
        entries = list(_buffer)
    by_op: dict[str, list[float]] = {}
    all_ms: list[float] = []
    prompt_total = 0
    completion_total = 0
    for e in entries:
        by_op.setdefault(str(e["operation"]), []).append(float(e["duration_ms"]))
        all_ms.append(float(e["duration_ms"]))
        prompt_total += int(e["prompt_tokens"] or 0)
        completion_total += int(e["completion_tokens"] or 0)
    totals = _stats(all_ms)
    totals.update(
        {
            "prompt_tokens": prompt_total,
            "completion_tokens": completion_total,
            "total_tokens": prompt_total + completion_total,
        }
    )
    return {
        "by_operation": {op: _stats(durs) for op, durs in sorted(by_op.items())},
        "totals": totals,
    }


def reset() -> None:
    """Vide le buffer (tests / remise a zero admin)."""
    with _lock:
        _buffer.clear()
