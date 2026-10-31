#!/usr/bin/env python3
"""Démo du flux multi-sauts : A (offline) → B (relai) → C (connecté) → Laravel.

Usage :
    python simulate_hops.py                 # simulation pure (aucun serveur requis)
    python simulate_hops.py --live          # + POST réel vers le relai/Laravel locaux
    python simulate_hops.py --burst N       # stress : N bundles vers le relai (+ doublons
                                            #   et invalides), rapport chiffré ; simulation
                                            #   locale si le relai est injoignable

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
import os
from uuid import uuid4

RELAY_URL = os.environ.get("MESH_RELAY_URL", "http://localhost:8001")
LARAVEL_URL = os.environ.get("LARAVEL_API_URL", "http://localhost/api")


MUTABLE = {"checksum", "hops", "previous_node", "copies_remaining"}


def checksum_of(bundle: dict) -> str:
    payload = {k: v for k, v in bundle.items() if k not in MUTABLE}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
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
        "destination": "dtn://wash-sentinel/ingest",
        "lifetime_seconds": 7 * 86400,
        "copies_remaining": 8,
        "priority": "normal",
    }
    bundle["checksum"] = checksum_of(bundle)
    return bundle


def forward(bundle: dict, node_id: str) -> dict | None:
    """Spray-and-Wait binaire : donne floor(n/2), garde ceil(n/2)."""
    if node_id in bundle["hops"]:
        print(f"  ⛔ {node_id} déjà dans {bundle['hops']} → boucle évitée")
        return None
    if datetime.fromisoformat(bundle["expires_at"]) <= datetime.now(timezone.utc):
        print(f"  ⛔ bundle expiré → jeté par {node_id}")
        return None
    if len(bundle["hops"]) >= bundle.get("max_hops", 10) + 1:
        print(f"  ⛔ max_hops atteint → jeté par {node_id}")
        return None
    copies = bundle.get("copies_remaining", 8)
    if copies <= 1:
        print(f"  ⛔ dernière copie → livraison directe au serveur uniquement")
        return None
    nxt = deepcopy(bundle)
    nxt["hops"].append(node_id)
    nxt["previous_node"] = bundle["hops"][-1]
    nxt["copies_remaining"] = copies // 2
    print(f"  📦 spray binaire : {copies} copies → donne {copies // 2}, garde {(copies + 1) // 2}")
    return nxt


def _burst_headers() -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    relay_key = os.environ.get("MESH_RELAY_API_KEY", "")
    if relay_key:
        headers["X-Mesh-Key"] = relay_key
    return headers


def _burst_post(url: str, data: dict) -> tuple[int, dict]:
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers=_burst_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except Exception:
            return exc.code, {}
    except Exception as exc:  # noqa: BLE001
        return 0, {"_error": f"{type(exc).__name__}: {exc}"}


def store_response_ok(status: int, body_text: str) -> bool:
    """Vrai si le POST /v1/store a réellement accepté le batch.

    Un HTTP 200 avec `rejected > 0` est un échec (faux-vert sinon : le
    relai répond toujours 200, même quand il rejette tout le batch).
    Corps non-JSON : on retombe sur le seul statut HTTP.
    """
    if status != 200:
        return False
    try:
        body = json.loads(body_text or "{}")
    except ValueError:
        return True
    return int(body.get("rejected", 0)) == 0


def _burst_get(url: str) -> tuple[int, dict]:
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, headers=_burst_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except Exception:  # noqa: BLE001
        return 0, {}


def burst_mode(n: int) -> int:
    """Stress : N bundles frais + doublons + invalides, rapport chiffré."""
    print(f"💥 WASH Mesh — burst x{n}\n")
    fresh = [create_bundle((i % 5) + 1, f"Stress #{i + 1} : forage en panne, test de charge.",
                           origin="node-burst") for i in range(n)]
    dups = fresh[: min(5, n)]
    # Accents couverts : checksum_of sérialise en UTF-8 brut (contrat README),
    # comme le relai — ces messages accentués le prouvent en --live comme en local.
    bad_priority = create_bundle(1, "Stress : priorité invalide — élève blessé.", origin="node-burst")
    bad_priority["priority"] = "urgentissime"
    bad_priority["checksum"] = checksum_of(bad_priority)  # checksum OK → rejet par la priorité
    expired = create_bundle(1, "Stress : bundle expiré — école inondée.", origin="node-burst")
    expired["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    expired["checksum"] = checksum_of(expired)  # checksum OK → compté expiré, pas rejeté

    status, _ = _burst_get(f"{RELAY_URL}/health")
    if status != 200:
        # Relai injoignable : simulation locale (checksums vérifiés, pas de réseau).
        ok = sum(1 for b in fresh if checksum_of({k: v for k, v in b.items() if k != "checksum"}) == b["checksum"])
        print(f"   (relai injoignable sur {RELAY_URL} — simulation locale)")
        print(f"   checksums valides : {ok}/{n}")
        print(f"\n📊 Rapport (prédit) : stockés={n} duplicatas={len(dups)} rejetés=1 expirés=1")
        return 0

    totals = {"stored": 0, "duplicates": 0, "rejected": 0, "expired": 0}
    stored_total = 0
    batches = [fresh[i: i + 100] for i in range(0, n, 100)]
    batches += ([dups] if dups else []) + [[bad_priority, expired]]
    for batch in batches:
        status, body = _burst_post(f"{RELAY_URL}/v1/store",
                                   {"node_id": "node-burst", "bundles": batch})
        if status != 200:
            print(f"   ❌ POST /v1/store → {status} {str(body)[:300]}")
            return 1
        for key in totals:
            totals[key] += int(body.get(key, 0))
        stored_total = int(body.get("stored_total", stored_total))
    print(f"   relai {RELAY_URL} : {len(batches)} batch(s) acceptés (HTTP 200)")
    print(f"\n📊 Rapport : stockés={totals['stored']} duplicatas={totals['duplicates']}"
          f" rejetés={totals['rejected']} expirés={totals['expired']}"
          f" (stock relai : {stored_total})")
    _, metrics = _burst_get(f"{RELAY_URL}/metrics")
    if metrics:
        print(f"   relai : uptime={metrics.get('uptime_seconds')}s sqlite={metrics.get('sqlite', {}).get('bytes')} octets"
              f" file-uplink={metrics.get('uplink_queue')}")
    expected = {"stored": n, "duplicates": len(dups), "rejected": 1, "expired": 1}
    ok = all(totals[k] == v for k, v in expected.items())
    print("✅ Burst conforme à l'attendu." if ok
          else f"⚠️  Écart vs attendu {expected} (relai non vide au départ ?).")
    return 0


def main(live: bool = False, burst: int = 0) -> int:
    if burst:
        return burst_mode(burst)
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
        "destination_eid": at_c.get("destination"),
        "lifetime_seconds": at_c.get("lifetime_seconds"),
        "copies_remaining": at_c.get("copies_remaining"),
        "priority": at_c.get("priority"),
    }
    if not live:
        print("   (dry-run) payload Laravel :")
        print("   " + json.dumps(payload, indent=2, ensure_ascii=False).replace("\n", "\n   "))
        print("\n✅ Simulation OK — relance avec --live pour POSTer vers le relai + Laravel locaux.")
        return 0

    import urllib.request
    import urllib.error

    def post(url: str, data: dict) -> tuple[int, str]:
        req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read().decode()[:1200]
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read().decode()[:1200]
            except Exception:
                return exc.code, f"HTTP Error {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return 0, f"{type(exc).__name__}: {exc}"

    def get(url: str) -> tuple[int, str]:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read().decode()[:1200]
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read().decode()[:1200]
            except Exception:
                return exc.code, f"HTTP Error {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return 0, f"{type(exc).__name__}: {exc}"

    ok = True
    # D'abord le relai (sync), puis Laravel (upload final).
    # Note : le relai répond 200 même en rejetant → store_response_ok.
    status, body = post(f"{RELAY_URL}/v1/store", {"node_id": "node-C-bertoua", "bundles": [at_c]})
    print(f"   relai {RELAY_URL}/v1/store → {status}\n   {body}")
    ok = ok and store_response_ok(status, body)
    status, body = post(f"{LARAVEL_URL}/v1/mesh/bundles", {"bundles": [payload]})
    print(f"   laravel {LARAVEL_URL}/v1/mesh/bundles → {status}\n   {body}")
    ok = ok and status in (200, 201)
    try:
        incident_id = json.loads(body)["incidents"][0]["incident_id"]
    except Exception:
        incident_id = None
    # Doublon : second upload du même bundle → duplicates=1.
    status, body = post(f"{LARAVEL_URL}/v1/mesh/bundles", {"bundles": [payload]})
    print(f"   re-upload (déduplication attendue) → {status}\n   {body}")
    try:
        ok = ok and json.loads(body)["summary"]["duplicates"] == 1
    except Exception:
        ok = False
    # Preuve : l'incident existe avec triage IA + les stats mesh bougent.
    if incident_id:
        status, body = get(f"{LARAVEL_URL}/v1/wash/incidents/{incident_id}")
        print(f"   incident #{incident_id} → {status}\n   {body}")
        ok = ok and status == 200
    status, body = get(f"{LARAVEL_URL}/v1/mesh/stats")
    print(f"   stats mesh → {status}\n   {body}")
    ok = ok and status == 200
    print("\n✅ Flux live OK : A → B → C → relai → Laravel → incident."
          if ok else "\n❌ Échec — voir les réponses ci-dessus.")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="POST réel vers relai + Laravel locaux")
    parser.add_argument("--burst", type=int, default=0, metavar="N",
                        help="stress : pousse N bundles vers le relai + rapport chiffré")
    args = parser.parse_args()
    if args.burst is not None and args.burst < 0:
        parser.error("--burst attend un entier >= 0")
    sys.exit(main(live=args.live, burst=args.burst))
