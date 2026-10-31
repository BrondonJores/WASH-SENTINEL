"""Persistance SQLite (WAL) du relai mesh.

Les bundles et les accusés (tombstones) survivent au redémarrage.
``main.py`` garde STORE/ACKED en mémoire comme cache chaud (dédup, TTL,
éviction LRU) et réplique chaque mutation ici en écriture directe
(write-through). Au démarrage, ``load_all`` recharge le cache.

Chemin via ``MESH_DB_PATH`` (défaut ``./relay.db``). ``:memory:`` accepté
(tests). Aucun format protocole n'est défini ici : la colonne ``data``
stocke le bundle canonique tel quel (datetimes en ISO).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS bundles (
    bundle_id   TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    stored_at   TEXT NOT NULL,
    received_via TEXT
);
CREATE INDEX IF NOT EXISTS idx_bundles_expires ON bundles (expires_at);
CREATE TABLE IF NOT EXISTS acked (
    bundle_id TEXT PRIMARY KEY,
    acked_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acked_at ON acked (acked_at);
"""

_DT_FIELDS = ("created_at", "expires_at", "stored_at")

_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None
_DB_PATH = ""


def path_from_env() -> str:
    return os.environ.get("MESH_DB_PATH", "./relay.db")


def db_path() -> str:
    """Chemin de la base active ("" si pas encore initialisée)."""
    with _LOCK:
        return _DB_PATH


def init_db(path: str | None = None) -> str:
    """Ouvre (ou rouvre) la base, active WAL, crée le schéma. Retourne le chemin."""
    global _CONN, _DB_PATH
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
        _DB_PATH = path or path_from_env()
        if _DB_PATH != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(_DB_PATH)), exist_ok=True)
        _CONN = sqlite3.connect(_DB_PATH, check_same_thread=False)
        try:
            _CONN.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.DatabaseError:
            pass  # :memory: ou FS sans WAL : on continue sans.
        try:
            _CONN.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.DatabaseError:
            pass
        _CONN.executescript(SCHEMA)
        _CONN.commit()
        return _DB_PATH


def close_db() -> None:
    global _CONN
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None


def _ensure_locked() -> sqlite3.Connection:
    global _CONN, _DB_PATH
    if _CONN is None:
        _DB_PATH = path_from_env()
        if _DB_PATH != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(_DB_PATH)), exist_ok=True)
        _CONN = sqlite3.connect(_DB_PATH, check_same_thread=False)
        try:
            _CONN.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.DatabaseError:
            pass
        _CONN.executescript(SCHEMA)
        _CONN.commit()
    return _CONN


def _encode(data: dict) -> str:
    flat = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in data.items()}
    return json.dumps(flat, ensure_ascii=False, default=str)


def _decode(payload: str) -> dict | None:
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    for field in _DT_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            try:
                data[field] = datetime.fromisoformat(value)
            except ValueError:
                return None
    if data.get("expires_at") is None or data.get("stored_at") is None:
        return None
    return data


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


# ---------- Bundles ----------

def save_bundle(bundle_id: str, data: dict) -> None:
    row = (_encode(data), _iso(data.get("expires_at")), _iso(data.get("stored_at")),
           data.get("received_via"))
    with _LOCK:
        conn = _ensure_locked()
        conn.execute(
            "INSERT INTO bundles (bundle_id, data, expires_at, stored_at, received_via)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (bundle_id) DO UPDATE SET data=excluded.data,"
            " expires_at=excluded.expires_at, stored_at=excluded.stored_at,"
            " received_via=excluded.received_via",
            (bundle_id, *row),
        )
        conn.commit()


def delete_bundle(bundle_id: str) -> None:
    delete_bundles([bundle_id])


def delete_bundles(bundle_ids: list[str]) -> int:
    if not bundle_ids:
        return 0
    with _LOCK:
        conn = _ensure_locked()
        cur = conn.executemany("DELETE FROM bundles WHERE bundle_id = ?", [(bid,) for bid in bundle_ids])
        conn.commit()
        return cur.rowcount or 0


def purge_expired_db(now_iso: str) -> int:
    with _LOCK:
        conn = _ensure_locked()
        cur = conn.execute("DELETE FROM bundles WHERE expires_at <= ?", (now_iso,))
        conn.commit()
        return cur.rowcount or 0


def count_bundles() -> int:
    with _LOCK:
        conn = _ensure_locked()
        row = conn.execute("SELECT COUNT(*) FROM bundles").fetchone()
        return int(row[0]) if row else 0


# ---------- Accusés ----------

def save_acked(bundle_ids: list[str], acked_at_iso: str) -> None:
    if not bundle_ids:
        return
    with _LOCK:
        conn = _ensure_locked()
        conn.executemany(
            "INSERT INTO acked (bundle_id, acked_at) VALUES (?, ?)"
            " ON CONFLICT (bundle_id) DO UPDATE SET acked_at=excluded.acked_at",
            [(bid, acked_at_iso) for bid in bundle_ids],
        )
        conn.commit()


def delete_acked(bundle_ids: list[str]) -> int:
    if not bundle_ids:
        return 0
    with _LOCK:
        conn = _ensure_locked()
        cur = conn.executemany("DELETE FROM acked WHERE bundle_id = ?", [(bid,) for bid in bundle_ids])
        conn.commit()
        return cur.rowcount or 0


def count_acked() -> int:
    with _LOCK:
        conn = _ensure_locked()
        row = conn.execute("SELECT COUNT(*) FROM acked").fetchone()
        return int(row[0]) if row else 0


# ---------- Rechargement / introspection ----------

def load_all() -> tuple[dict[str, dict], dict[str, datetime]]:
    """Retourne (bundles, accusés). Les lignes corrompues sont ignorées."""
    with _LOCK:
        conn = _ensure_locked()
        bundles: dict[str, dict] = {}
        for bundle_id, payload in conn.execute("SELECT bundle_id, data FROM bundles"):
            data = _decode(payload)
            if data is not None:
                bundles[bundle_id] = data
        acked: dict[str, datetime] = {}
        for bundle_id, acked_at in conn.execute("SELECT bundle_id, acked_at FROM acked"):
            try:
                acked[bundle_id] = datetime.fromisoformat(acked_at)
            except (ValueError, TypeError):
                continue
        return bundles, acked


def db_size_bytes() -> int:
    """Taille cumulée base + WAL + SHM (0 si :memory: ou absente)."""
    with _LOCK:
        path = _DB_PATH or path_from_env()
    if path == ":memory:":
        return 0
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(path + suffix)
        except OSError:
            continue
    return total
