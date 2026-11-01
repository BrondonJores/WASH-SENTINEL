"""Observabilite IA — latences et tokens des operations LLM (stdlib uniquement).

Usage typique dans un endpoint::

    from .ai_metrics import timed

    with timed("extract"):
        result = await extractor.extract(req.raw_text)

Le buffer circulaire garde les 500 dernieres operations (thread-safe).
``summary()`` alimente l'endpoint GET /v1/admin/ai-metrics.
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections import deque
from contextlib import contextmanager
from time import perf_counter, time
from typing import Any, Iterator

__all__ = ["MAX_ENTRIES", "COST_PER_1K", "record", "timed", "summary", "reset", "estimate_cost"]


def _env_int(name: str, default: int) -> int:
    """Override ENV typé ; défaut historique inchangé si absent/invalide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


#: Taille du buffer circulaire des opérations (thread-safe).
#: Override ENV : AI_METRICS_MAX_ENTRIES (défaut historique 500).
MAX_ENTRIES = _env_int("AI_METRICS_MAX_ENTRIES", 500)

# Coûts ESTIMATIFS $/1k tokens (prompt + completion confondus), pour comparer
# les profils modèles dans Réglages IA. Local (Ollama) = 0.0 exact ; valeurs
# cloud indicatives, surchargeables par appel via cost_per_1k.
_DEFAULT_COST_PER_1K: dict[str, float] = {
    "llama3.2:3b": 0.0,
    "llama3.2-vision:11b": 0.0,
    "nomic-embed-text": 0.0,
    "llama-3.3-70b-versatile": 0.06,
    "openai/gpt-oss-20b": 0.05,
    "whisper-1": 0.10,
    "gpt-4o-mini": 0.30,
    "gpt-4o": 3.00,
    "claude-sonnet-4-5": 4.50,
}


def _cost_table() -> dict[str, float]:
    """Table des coûts : défauts + surcharge JSON via AI_METRICS_COSTS_JSON.

    Exemple : AI_METRICS_COSTS_JSON='{"gpt-4o": 5.0, "nouveau": 0.1}'.
    JSON absent/invalide -> défauts historiques inchangés (jamais de crash).
    """
    table = dict(_DEFAULT_COST_PER_1K)
    raw = os.environ.get("AI_METRICS_COSTS_JSON", "").strip()
    if not raw:
        return table
    try:
        override = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return table
    if isinstance(override, dict):
        for model, price in override.items():
            try:
                table[str(model)] = float(price)
            except (TypeError, ValueError):
                continue
    return table


COST_PER_1K: dict[str, float] = _cost_table()

_lock = threading.Lock()
_buffer: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)


def estimate_cost(
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_per_1k: float | None = None,
) -> float | None:
    """Estime le coût $ d'un appel, ou None si modèle inconnu/non tarifé."""
    if cost_per_1k is None:
        if model is None or model not in COST_PER_1K:
            return None
        cost_per_1k = COST_PER_1K[model]
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    return round(total / 1000.0 * float(cost_per_1k), 6)


def record(
    operation: str,
    seconds: float,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    status: str = "ok",
    model: str | None = None,
    provider: str | None = None,
    error_type: str | None = None,
    cost_usd: float | None = None,
    cost_per_1k: float | None = None,
) -> dict[str, Any]:
    """Enregistre une operation. Les compteurs tokens sont optionnels (None-safe).

    Champs failure-aware optionnels (défauts = comportement historique) :
    ``status`` ("ok"/"error"), ``model``, ``provider``, ``error_type``
    (ex. "TimeoutError", "fallback-rules"), ``cost_usd`` (auto-estimé depuis
    COST_PER_1K quand model+tokens connus et coût non fourni).
    """
    if cost_usd is None:
        cost_usd = estimate_cost(model, prompt_tokens, completion_tokens, cost_per_1k)
    entry = {
        "operation": operation,
        "seconds": float(seconds),
        "duration_ms": round(float(seconds) * 1000.0, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "timestamp": time(),
        "status": status,
        "model": model,
        "provider": provider,
        "error_type": error_type,
        "cost_usd": cost_usd,
    }
    with _lock:
        _buffer.append(entry)
    return dict(entry)


@contextmanager
def timed(
    operation: str,
    model: str | None = None,
    provider: str | None = None,
    cost_per_1k: float | None = None,
) -> Iterator[dict[str, Any]]:
    """Context manager : mesure la duree (secondes) et l'enregistre via ``record``.

    Yields un dict mutable ``ctx`` : poser ``ctx["prompt_tokens"]`` /
    ``ctx["completion_tokens"]`` avant la sortie pour les attacher a l'entree ;
    ``ctx["model"]`` / ``ctx["error_type"]`` / ``ctx["status"]`` surchargent les
    paramètres. Enregistre meme si le bloc leve (status="error",
    error_type=type(exc).__name__), puis re-lève.
    """
    ctx: dict[str, Any] = {}
    start = perf_counter()
    try:
        yield ctx
    except BaseException as exc:
        record(
            operation,
            perf_counter() - start,
            prompt_tokens=ctx.get("prompt_tokens"),
            completion_tokens=ctx.get("completion_tokens"),
            status=str(ctx.get("status", "error")),
            model=ctx.get("model", model),
            provider=ctx.get("provider", provider),
            error_type=ctx.get("error_type") or type(exc).__name__,
            cost_usd=ctx.get("cost_usd"),
            cost_per_1k=ctx.get("cost_per_1k", cost_per_1k),
        )
        raise
    else:
        record(
            operation,
            perf_counter() - start,
            prompt_tokens=ctx.get("prompt_tokens"),
            completion_tokens=ctx.get("completion_tokens"),
            status=str(ctx.get("status", "ok")),
            model=ctx.get("model", model),
            provider=ctx.get("provider", provider),
            error_type=ctx.get("error_type"),
            cost_usd=ctx.get("cost_usd"),
            cost_per_1k=ctx.get("cost_per_1k", cost_per_1k),
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
    """Agrege le buffer : ``{by_operation, by_status, by_model, totals}``.

    ``by_operation`` et les clés historiques de ``totals`` (count, avg_ms,
    p95_ms, prompt/completion/total_tokens) sont inchangées ; les clés
    failure-aware (by_status, by_model, error_count, error_rate, cost_usd)
    sont purement additives.
    """
    with _lock:
        entries = list(_buffer)
    by_op: dict[str, list[float]] = {}
    by_model_ms: dict[str, list[float]] = {}
    by_model_err: dict[str, int] = {}
    by_model_tokens: dict[str, int] = {}
    by_model_cost: dict[str, float] = {}
    all_ms: list[float] = []
    prompt_total = 0
    completion_total = 0
    ok_count = 0
    error_count = 0
    cost_total = 0.0
    for e in entries:
        by_op.setdefault(str(e["operation"]), []).append(float(e["duration_ms"]))
        all_ms.append(float(e["duration_ms"]))
        prompt_total += int(e.get("prompt_tokens") or 0)
        completion_total += int(e.get("completion_tokens") or 0)
        if e.get("status", "ok") == "ok":
            ok_count += 1
        else:
            error_count += 1
        cost_total += float(e.get("cost_usd") or 0.0)
        model = e.get("model")
        if model is not None:
            m = str(model)
            by_model_ms.setdefault(m, []).append(float(e["duration_ms"]))
            by_model_err[m] = by_model_err.get(m, 0) + (0 if e.get("status", "ok") == "ok" else 1)
            by_model_tokens[m] = by_model_tokens.get(m, 0) + int(e.get("prompt_tokens") or 0) + int(
                e.get("completion_tokens") or 0
            )
            by_model_cost[m] = by_model_cost.get(m, 0.0) + float(e.get("cost_usd") or 0.0)
    totals = _stats(all_ms)
    totals.update(
        {
            "prompt_tokens": prompt_total,
            "completion_tokens": completion_total,
            "total_tokens": prompt_total + completion_total,
            "error_count": error_count,
            "error_rate": round(error_count / len(entries), 4) if entries else 0.0,
            "cost_usd": round(cost_total, 6),
        }
    )
    by_model: dict[str, dict[str, Any]] = {}
    for m in sorted(by_model_ms):
        stats = _stats(by_model_ms[m])
        stats.update(
            {
                "error_count": by_model_err.get(m, 0),
                "total_tokens": by_model_tokens.get(m, 0),
                "cost_usd": round(by_model_cost.get(m, 0.0), 6),
            }
        )
        by_model[m] = stats
    return {
        "by_operation": {op: _stats(durs) for op, durs in sorted(by_op.items())},
        "by_status": {"ok": ok_count, "error": error_count},
        "by_model": by_model,
        "totals": totals,
    }


def reset() -> None:
    """Vide le buffer (tests / remise a zero admin)."""
    with _lock:
        _buffer.clear()
