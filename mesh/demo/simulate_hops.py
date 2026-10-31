#!/usr/bin/env python3
"""Démo du flux multi-sauts : A (offline) → B (relai) → C (connecté) → Laravel.

Usage :
    python simulate_hops.py                 # simulation pure (aucun serveur requis)
    python simulate_hops.py --live          # + POST réel vers le relai/Laravel locaux

Scénario Cameroun : l'école de Yokadouma (sans réseau) fait passer son
signalement par un taxi-moto (B) jusqu'à Bertoua (C, connecté).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

RELAY_URL = "http://localhost:8001"
LARAVEL_URL = "http://localhost/api"


def checksum_of(bundle: dict) -> str:
    payload = {k: v for k, v in bundle.items() if k != "checksum"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def create_bundle(school_id: int, message: str, origin: str = "node-A-yokadouma") -> dict:
    now = datetime.now(timezone.utc)
    bundle = {
        "v": 1,
        "bundle_id": str(uuid4()),
        "origin_node_id": origin,
        "school_id": school_id,
        "school_code": "CM-EST-0042",
        "channel": "text",
        "message": message,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "max_hops": 10,
        "hops": [origin],
    }
    bundle["checksum"] = checksum_of(bundle)
    return bundle


def forward(bundle: dict, node_id: str) -> dict | None:
    if node_id in bundle["hops"]:
        print(f"  ⛔ {node_id} déjà dans {bundle['hops']} → boucle évitée")
        return None
    if datetime.fromisoformat(bundle["expires_at"]) <= datetime.now(timezone.utc):
        print(f"  ⛔ bundle expiré → jeté par {node_id}")
        return None
    if len(bundle["hops"]) >= bundle.get("max_hops", 10) + 1:
        print(f"  ⛔ max_hops atteint → jeté par {node_id}")
        return None
    nxt = deepcopy(bundle)
    nxt["hops"].append(node_id)
    return nxt


def main(live: bool = False) -> int:
    print("🕸️  WASH Mesh — démo A → B → C → serveur\n")

    # 1. A crée son signalement hors-ligne (Yokadouma, pas de réseau).
    bundle = create_bundle(1, "Pompe du forage brisée depuis ce matin, 400 élèves sans eau potable.")
    print(f"1️⃣  A (Yokadouma, OFFLINE) crée le bundle {bundle['bundle_id'][:8]}…")
    print(f"   hops={bundle['hops']} checksum={bundle['checksum'][:12]}… ({len(json.dumps(bundle))} octets)")

    # 2. A croise B (taxi-moto) : copie via QR/Bluetooth.
    print("\n2️⃣  A croise B (taxi-moto) → copie locale (QR/Bluetooth)")
    at_b = forward(bundle, "node-B-taximoto")
    assert at_b is not None
    print(f"   hops={at_b['hops']}")

    # 3. B croise C (Bertoua, connecté).
    print("\n3️⃣  B croise C (Bertoua, CONNECTÉ) → copie locale")
    at_c = forward(at_b, "node-C-bertoua")
    assert at_c is not None
    print(f"   hops={at_c['hops']}  (hop_count={len(at_c['hops']) - 1})")

    # 4. Anti-boucle : C recroise A, A refuse son propre bundle.
    print("\n4️⃣  C recroise A → A refuse (déjà dans hops) :")
    assert forward(at_c, "node-A-yokadouma") is None

    # 5. Upload final.
    print("\n5️⃣  C uploade vers le serveur…")
    payload = {
        "bundle_id": at_c["bundle_id"],
        "origin_node_id": at_c["origin_node_id"],
        "school_id": at_c["school_id"],
        "school_code": at_c.get("school_code"),
        "message": at_c["message"],
        "channel": "text",
        "hops": at_c["hops"],
        "max_hops": at_c["max_hops"],
        "expires_at": at_c["expires_at"],
        "received_via_node_id": "node-C-bertoua",
        "checksum": at_c["checksum"],
    }
    if not live:
        print("   (dry-run) payload Laravel :")
        print("   " + json.dumps(payload, indent=2, ensure_ascii=False).replace("\n", "\n   "))
        print("\n✅ Simulation OK — relance avec --live pour POSTer vers le relai + Laravel locaux.")
        return 0

    import urllib.request

    def post(url: str, data: dict) -> tuple[int, str]:
        req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode()[:800]
        except Exception as exc:  # noqa: BLE001
            return 0, f"{type(exc).__name__}: {exc}"

    # D'abord le relai (sync), puis Laravel (upload final).
    status, body = post(f"{RELAY_URL}/v1/store", {"node_id": "node-C-bertoua", "bundles": [at_c]})
    print(f"   relai {RELAY_URL}/v1/store → {status}\n   {body}")
    status, body = post(f"{LARAVEL_URL}/v1/mesh/bundles", {"bundles": [payload]})
    print(f"   laravel {LARAVEL_URL}/v1/mesh/bundles → {status}\n   {body}")
    # Doublon : second upload du même bundle → duplicates=1.
    status, body = post(f"{LARAVEL_URL}/v1/mesh/bundles", {"bundles": [payload]})
    print(f"   re-upload (déduplication attendue) → {status}\n   {body}")
    return 0 if status in (200, 201) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="POST réel vers relai + Laravel locaux")
    args = parser.parse_args()
    sys.exit(main(live=args.live))
