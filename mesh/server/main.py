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
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

LARAVEL_URL = os.environ.get("LARAVEL_URL", "http://laravel:8080")
LARAVEL_KEY = os.environ.get("MESH_INGEST_KEY", "")
MAX_STORE = int(os.environ.get("MESH_MAX_STORE", "5000"))
RELAY_KEY = os.environ.get("MESH_RELAY_API_KEY", "")

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
# compteurs cumulés par cause (observabilité Phase 0)
COUNTERS: dict[str, int] = {"stored": 0, "duplicates": 0, "expired": 0, "rejected": 0, "evicted_lru": 0}
# tombstones : bundle_id -> acked_at (purge des outbox distantes). Capés + expirés.
ACKED: dict[str, datetime] = {}
ACK_TTL_DAYS = 7
ACK_MAX = 20000


def prune_acked() -> None:
    cutoff = _utcnow() - timedelta(days=ACK_TTL_DAYS)
    for bid in [k for k, v in ACKED.items() if v <= cutoff]:
        ACKED.pop(bid, None)
    while len(ACKED) > ACK_MAX:
        ACKED.pop(min(ACKED.items(), key=lambda kv: kv[1])[0], None)


def record_acked(ids: list[str]) -> int:
    prune_acked()
    now = _utcnow()
    n = 0
    for bid in ids[:5000]:
        if bid not in ACKED:
            n += 1
        ACKED[bid] = now
    prune_acked()
    return n


def require_key(request: Request) -> None:
    """Clé relai optionnelle : si MESH_RELAY_API_KEY est défini, X-Mesh-Key exigé."""
    if RELAY_KEY and request.headers.get("x-mesh-key") != RELAY_KEY:
        raise HTTPException(status_code=401, detail="Clé relai manquante ou invalide.")


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
    checksum: str | None = Field(default=None, max_length=128)
    # v1.1 additive (alignement BPv7, tous optionnels).
    destination: str | None = Field(default=None, max_length=128)
    report_to: str | None = Field(default=None, max_length=128)
    lifetime_seconds: int | None = Field(default=None, ge=60, le=2592000)
    previous_node: str | None = Field(default=None, max_length=64)
    copies_remaining: int = Field(default=8, ge=1, le=64)
    fragment_offset: int | None = Field(default=None, ge=0)
    fragment_total: int | None = Field(default=None, ge=1)
    custody_requested: bool = False
    priority: str = "normal"
    signature: str | None = Field(default=None, max_length=128)
    # V2 E2E : enveloppe opaque — le relai transporte sans lire.
    sealed: str | None = Field(default=None, max_length=20000)
    sealed_alg: str | None = Field(default=None, max_length=32)
    # V2b médias différés : fragments opaques + métadonnées du manifeste.
    bundle_group: str | None = Field(default=None, max_length=64)
    chunk: str | None = Field(default=None, max_length=65536)
    media_mime: str | None = Field(default=None, max_length=64)
    media_size: int | None = Field(default=None, ge=1, le=2097152)
    media_sha256: str | None = Field(default=None, max_length=128)
    media_sealed_alg: str | None = Field(default=None, max_length=32)


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


class AckRequest(BaseModel):
    node_id: str = Field(max_length=64)
    ids: list[str] = Field(max_length=1000)


# ---------- Helpers ----------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Champs de routage mutables : modifiés à chaque saut, donc exclus du
# checksum (modèle Rhizome : l'intégrité couvre le manifeste d'origine).
MUTABLE_FIELDS = frozenset({"checksum", "hops", "previous_node", "copies_remaining"})


def canonical_string(bundle: dict[str, Any]) -> str:
    """Forme canonique partagée avec le SDK TS et le client Kotlin :
    clés triées hors champs mutables, compact, UTF-8 brut (accents non échappés)."""
    payload = {k: v for k, v in bundle.items() if k not in MUTABLE_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_checksum(bundle: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_string(bundle).encode()).hexdigest()


def _expired(expires_at: datetime) -> bool:
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return exp <= _utcnow()


def purge_expired() -> int:
    expired = [bid for bid, b in STORE.items() if _expired(b["expires_at"])]
    for bid in expired:
        STORE.pop(bid, None)
    return len(expired)


def store_one(node_id: str, bundle: Bundle) -> str:
    """Retourne stored | duplicate | expired | rejected (et incrémente COUNTERS)."""
    bid = str(bundle.bundle_id)
    if bid in STORE:
        # On enrichit les hops connus sans écraser le bundle d'origine.
        known = set(STORE[bid].get("hops", []))
        for hop in bundle.hops:
            if hop not in known:
                STORE[bid]["hops"].append(hop)
                known.add(hop)
        COUNTERS["duplicates"] += 1
        return "duplicate"
    data = bundle.model_dump(mode="json")
    data["expires_at"] = bundle.expires_at
    data["created_at"] = bundle.created_at
    if bundle.checksum:
        # Même instant, deux écritures ISO (...Z vs +00:00) selon l'émetteur :
        # on accepte les deux formes (le checksum détecte la corruption,
        # pas la malice — la signature Ed25519 viendra en Phase 3).
        # exclude_unset : on vérifie exactement les champs envoyés par le client,
        # pas les défauts ajoutés par Pydantic.
        raw = canonical_string(bundle.model_dump(mode="json", exclude_unset=True))
        zulu = re.sub(r'(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\+00:00"', r'\1Z"', raw)
        offset = re.sub(r'(\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z"', r'\1+00:00"', raw)
        candidates = {raw, zulu, offset}
        if not any(bundle.checksum == hashlib.sha256(c.encode()).hexdigest() for c in candidates):
            COUNTERS["rejected"] += 1
            return "rejected"
    if _expired(bundle.expires_at):
        COUNTERS["expired"] += 1
        return "expired"
    hop_count = max(0, len(bundle.hops) - 1)
    if hop_count > bundle.max_hops:
        COUNTERS["rejected"] += 1
        return "rejected"
    if bundle.priority not in ("normal", "high", "alert"):
        COUNTERS["rejected"] += 1
        return "rejected"
    if len(STORE) >= MAX_STORE:
        purge_expired()
    while len(STORE) >= MAX_STORE:
        # Éviction LRU : le plus ancien stocké sort (jamais de rejet par manque
        # de place quand tout est frais — le rejet ne concerne que le contenu).
        oldest = min(STORE.items(), key=lambda kv: kv[1]["stored_at"])[0]
        STORE.pop(oldest, None)
        COUNTERS["evicted_lru"] += 1
    data["received_via"] = node_id
    data["stored_at"] = _utcnow()
    STORE[bid] = data
    COUNTERS["stored"] += 1
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


@app.post("/v1/store", dependencies=[Depends(require_key)])
def store(req: StoreRequest) -> dict[str, Any]:
    counts = {"stored": 0, "duplicates": 0, "expired": 0, "rejected": 0}
    for bundle in req.bundles:
        res = store_one(req.node_id, bundle)
        key = "duplicates" if res == "duplicate" else res
        counts[key] = counts.get(key, 0) + 1
    return {"message": f"{counts['stored']} bundle(s) stocké(s).", **counts,
            "stored_total": len(STORE)}


@app.post("/v1/fetch", dependencies=[Depends(require_key)])
def fetch(req: FetchRequest) -> dict[str, Any]:
    bundles = missing_for(set(req.known_ids), req.limit)
    prune_acked()
    known = set(req.known_ids)
    acked = sorted(bid for bid in ACKED if bid in known)
    return {"bundles": bundles, "count": len(bundles), "stored_total": len(STORE),
            "acked_ids": acked}


@app.post("/v1/sync", dependencies=[Depends(require_key)])
def sync(req: SyncRequest) -> dict[str, Any]:
    """Échange opportuniste bidirectionnel : je donne mon outbox, je prends ce qui me manque."""
    stored = store(req)
    mine = set(req.known_ids) | {str(b.bundle_id) for b in req.bundles}
    bundles = missing_for(mine, req.limit)
    prune_acked()
    acked = sorted(bid for bid in ACKED if bid in mine)
    return {**stored, "bundles": bundles, "count": len(bundles), "acked_ids": acked}


@app.post("/v1/ack", dependencies=[Depends(require_key)])
def ack(req: AckRequest) -> dict[str, Any]:
    """Un nœud connecté signale les bundles arrivés au serveur : les relais
    qui les transportent encore les purgeront à leur prochaine sync."""
    n = record_acked(req.ids)
    return {"message": f"{n} accusé(s) enregistré(s).", "new": n, "acked_total": len(ACKED)}


@app.get("/v1/stats", dependencies=[Depends(require_key)])
def stats() -> dict[str, Any]:
    purge_expired()
    origins = {b["origin_node_id"] for b in STORE.values()}
    hops = [max(0, len(b.get("hops", [])) - 1) for b in STORE.values()]
    return {"stored": len(STORE), "origins": len(origins),
            "avg_hops": round(sum(hops) / len(hops), 2) if hops else 0,
            "peers_live": len(PEERS), "counters": dict(COUNTERS)}


@app.post("/v1/uplink", dependencies=[Depends(require_key)])
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
         "expires_at": b["expires_at"], "received_via_node_id": b.get("received_via"),
         "destination_eid": b.get("destination"), "report_to_eid": b.get("report_to"),
         "lifetime_seconds": b.get("lifetime_seconds"),
         "previous_node_id": b.get("previous_node"),
         "copies_remaining": b.get("copies_remaining", 8),
         "fragment_offset": b.get("fragment_offset"), "fragment_total": b.get("fragment_total"),
         "custody_requested": b.get("custody_requested", False),
         "priority": b.get("priority", "normal"), "signature": b.get("signature"),
         "sealed": b.get("sealed"), "sealed_alg": b.get("sealed_alg"),
         "bundle_group": b.get("bundle_group"), "chunk": b.get("chunk"),
         "media_mime": b.get("media_mime"), "media_size": b.get("media_size"),
         "media_sha256": b.get("media_sha256"), "media_sealed_alg": b.get("media_sealed_alg"),
         "checksum": b.get("checksum")}
        for b in bundles
    ]}
    headers = {"Accept": "application/json"}
    if LARAVEL_KEY:
        headers["X-Mesh-Key"] = LARAVEL_KEY
    try:
        resp = httpx.post(f"{LARAVEL_URL}/api/v1/mesh/bundles", json=payload, headers=headers, timeout=30)
        result = {"status_code": resp.status_code, "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:500]}
        confirmed: set[str] = set()
        if resp.status_code in (200, 201) and isinstance(result.get("body"), dict):
            for inc in result["body"].get("incidents", []):
                if isinstance(inc, dict) and inc.get("bundle_id"):
                    confirmed.add(inc["bundle_id"])
        if confirmed:
            # Tombstones : les relais qui transportent ces bundles les purgeront.
            record_acked(sorted(confirmed))
            for bid in confirmed:
                STORE.pop(bid, None)
        return {"pending": len(bundles), "laravel": result, "flushed": sorted(confirmed)}
    except Exception as exc:
        return {"pending": len(bundles), "laravel": {"error": f"{type(exc).__name__}: {exc}"}, "flushed": False}


# ---------- WebSocket temps réel ----------

@app.websocket("/v1/ws/{node_id}")
async def ws(node_id: str, websocket: WebSocket):
    if RELAY_KEY and websocket.query_params.get("key") != RELAY_KEY:
        await websocket.close(code=4401)
        return
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
