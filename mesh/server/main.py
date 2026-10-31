"""WASH Mesh Relay — point de rendez-vous store-and-forward du réseau maillé.

Rôle : quand deux nœuds se croisent avec un peu de réseau (WiFi village, 2G
intermittente), ils synchronisent leurs outbox ici. Le premier nœud avec un
vrai accès internet (ou le relai lui-même) fait l'uplink vers Laravel.

Persistance volontairement simple (mémoire + purge TTL) : Laravel reste la
source de vérité, le relai n'est qu'un sac à dos opportuniste.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

LARAVEL_URL = os.environ.get("LARAVEL_URL", "http://laravel:8080")
MAX_STORE = int(os.environ.get("MESH_MAX_STORE", "5000"))

app = FastAPI(title="WASH Mesh Relay", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# bundle_id -> bundle canonique
STORE: dict[str, dict[str, Any]] = {}
# node_id -> websocket live
PEERS: dict[str, WebSocket] = {}


# ---------- Modèles ----------

class Bundle(BaseModel):
    v: int = 1
    bundle_id: UUID
    origin_node_id: str = Field(max_length=64)
    school_id: int
    school_code: str | None = Field(default=None, max_length=32)
    channel: str = "text"
    message: str | None = Field(default=None, max_length=5000)
    created_at: datetime
    expires_at: datetime
    max_hops: int = Field(default=10, ge=1, le=20)
    hops: list[str] = Field(default_factory=list, max_length=21)
    checksum: str | None = Field(default=None, max_length=64)


class StoreRequest(BaseModel):
    node_id: str = Field(max_length=64)
    bundles: list[Bundle] = Field(max_length=100)


class FetchRequest(BaseModel):
    node_id: str = Field(max_length=64)
    known_ids: list[str] = Field(default_factory=list, max_length=5000)
    limit: int = Field(default=50, ge=1, le=200)


class SyncRequest(StoreRequest):
    known_ids: list[str] = Field(default_factory=list, max_length=5000)
    limit: int = Field(default=50, ge=1, le=200)


# ---------- Helpers ----------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_checksum(bundle: dict[str, Any]) -> str:
    payload = {k: v for k, v in bundle.items() if k != "checksum"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _expired(expires_at: datetime) -> bool:
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return exp <= _utcnow()


def purge_expired() -> int:
    expired = [bid for bid, b in STORE.items() if _expired(b["expires_at"])]
    for bid in expired:
        STORE.pop(bid, None)
    return len(expired)


def store_one(node_id: str, bundle: Bundle) -> str:
    """Retourne stored | duplicate | expired | rejected."""
    bid = str(bundle.bundle_id)
    if bid in STORE:
        # On enrichit les hops connus sans écraser le bundle d'origine.
        known = set(STORE[bid].get("hops", []))
        for hop in bundle.hops:
            if hop not in known:
                STORE[bid]["hops"].append(hop)
                known.add(hop)
        return "duplicate"
    data = bundle.model_dump(mode="json")
    data["expires_at"] = bundle.expires_at
    data["created_at"] = bundle.created_at
    if bundle.checksum and bundle.checksum != canonical_checksum(
        {**data, "expires_at": bundle.expires_at.isoformat(), "created_at": bundle.created_at.isoformat()}
    ):
        # Checksum calculé sur la forme canonique : tolère les variantes de
        # sérialisation en vérifiant aussi la forme brute reçue.
        raw = bundle.model_dump(mode="json")
        if bundle.checksum != canonical_checksum(raw):
            return "rejected"
    if _expired(bundle.expires_at):
        return "expired"
    hop_count = max(0, len(bundle.hops) - 1)
    if hop_count > bundle.max_hops:
        return "rejected"
    if len(STORE) >= MAX_STORE:
        purge_expired()
        if len(STORE) >= MAX_STORE:
            return "rejected"
    data["received_via"] = node_id
    data["stored_at"] = _utcnow()
    STORE[bid] = data
    return "stored"


def missing_for(known_ids: set[str], limit: int) -> list[dict[str, Any]]:
    purge_expired()
    out: list[dict[str, Any]] = []
    for bid, b in STORE.items():
        if bid in known_ids:
            continue
        if _expired(b["expires_at"]):
            continue
        out.append({**b, "expires_at": b["expires_at"].isoformat(), "created_at": b["created_at"].isoformat(),
                    "stored_at": b["stored_at"].isoformat()})
        if len(out) >= limit:
            break
    return out


# ---------- REST ----------

@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "healthy", "service": "WASH Mesh Relay",
            "stored": len(STORE), "peers_live": len(PEERS)}


@app.post("/v1/store")
def store(req: StoreRequest) -> dict[str, Any]:
    counts = {"stored": 0, "duplicates": 0, "expired": 0, "rejected": 0}
    for bundle in req.bundles:
        res = store_one(req.node_id, bundle)
        key = "duplicates" if res == "duplicate" else res
        counts[key] = counts.get(key, 0) + 1
    return {"message": f"{counts['stored']} bundle(s) stocké(s).", **counts,
            "stored_total": len(STORE)}


@app.post("/v1/fetch")
def fetch(req: FetchRequest) -> dict[str, Any]:
    bundles = missing_for(set(req.known_ids), req.limit)
    return {"bundles": bundles, "count": len(bundles), "stored_total": len(STORE)}


@app.post("/v1/sync")
def sync(req: SyncRequest) -> dict[str, Any]:
    """Échange opportuniste bidirectionnel : je donne mon outbox, je prends ce qui me manque."""
    stored = store(req)
    bundles = missing_for(set(req.known_ids) | {str(b.bundle_id) for b in req.bundles}, req.limit)
    return {**stored, "bundles": bundles, "count": len(bundles)}


@app.get("/v1/stats")
def stats() -> dict[str, Any]:
    purge_expired()
    origins = {b["origin_node_id"] for b in STORE.values()}
    hops = [max(0, len(b.get("hops", [])) - 1) for b in STORE.values()]
    return {"stored": len(STORE), "origins": len(origins),
            "avg_hops": round(sum(hops) / len(hops), 2) if hops else 0,
            "peers_live": len(PEERS)}


@app.post("/v1/uplink")
def uplink(dry_run: bool = False) -> dict[str, Any]:
    """Le relai (ou un nœud connecté) pousse tout le stock vers Laravel."""
    purge_expired()
    bundles = missing_for(set(), MAX_STORE)
    if dry_run or not bundles:
        return {"dry_run": dry_run, "pending": len(bundles), "laravel": None}
    payload = {"bundles": [
        {"bundle_id": b["bundle_id"], "origin_node_id": b["origin_node_id"],
         "school_id": b["school_id"], "school_code": b.get("school_code"),
         "message": b.get("message"), "channel": b.get("channel", "text"),
         "hops": b.get("hops", []), "max_hops": b.get("max_hops", 10),
         "expires_at": b["expires_at"], "received_via_node_id": b.get("received_via")}
        for b in bundles
    ]}
    try:
        resp = httpx.post(f"{LARAVEL_URL}/api/v1/mesh/bundles", json=payload, timeout=30)
        result = {"status_code": resp.status_code, "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:500]}
        if resp.status_code in (200, 201):
            for b in bundles:
                STORE.pop(b["bundle_id"], None)
        return {"pending": len(bundles), "laravel": result, "flushed": resp.status_code in (200, 201)}
    except Exception as exc:
        return {"pending": len(bundles), "laravel": {"error": f"{type(exc).__name__}: {exc}"}, "flushed": False}


# ---------- WebSocket temps réel ----------

@app.websocket("/v1/ws/{node_id}")
async def ws(node_id: str, websocket: WebSocket):
    await websocket.accept()
    PEERS[node_id] = websocket
    try:
        await websocket.send_json({"type": "hello", "stored": len(STORE), "peers": len(PEERS)})
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "offer" and isinstance(msg.get("bundles"), list):
                fresh: list[dict[str, Any]] = []
                for raw in msg["bundles"][:100]:
                    try:
                        res = store_one(node_id, Bundle(**raw))
                        if res == "stored":
                            fresh.append(raw)
                    except Exception:
                        continue
                # Propagation live vers les autres pairs connectés.
                dead: list[str] = []
                for peer_id, sock in PEERS.items():
                    if peer_id == node_id:
                        continue
                    try:
                        await sock.send_json({"type": "bundles", "from": node_id, "bundles": fresh})
                    except Exception:
                        dead.append(peer_id)
                for peer_id in dead:
                    PEERS.pop(peer_id, None)
                await websocket.send_json({"type": "ack", "stored": len(fresh)})
            elif msg.get("type") == "fetch":
                known = set(msg.get("known_ids", []))
                await websocket.send_json({"type": "bundles", "from": "relay",
                                           "bundles": missing_for(known, int(msg.get("limit", 50)))})
    except WebSocketDisconnect:
        pass
    finally:
        PEERS.pop(node_id, None)
