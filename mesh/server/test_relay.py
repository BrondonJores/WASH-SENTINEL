"""Tests du relai mesh : déduplication, TTL, sync bidirectionnelle."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from main import ACKED, COUNTERS, STORE, app

client = TestClient(app)


def make_bundle(**overrides):
    now = datetime.now(timezone.utc)
    base = {
        "bundle_id": str(uuid4()),
        "origin_node_id": "node-A",
        "school_id": 1,
        "channel": "text",
        "message": "Pompe brisée, 400 élèves sans eau",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "max_hops": 10,
        "hops": ["node-A"],
    }
    base.update(overrides)
    return base


def setup_function(_):
    STORE.clear()
    ACKED.clear()
    for key in COUNTERS:
        COUNTERS[key] = 0
    main.RELAY_KEY = ""


def test_store_then_fetch():
    b = make_bundle()
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    assert r.status_code == 200
    assert r.json()["stored"] == 1

    r = client.post("/v1/fetch", json={"node_id": "node-B", "known_ids": []})
    assert r.json()["count"] == 1
    assert r.json()["bundles"][0]["bundle_id"] == b["bundle_id"]


def test_duplicate_is_ignored_but_enriches_hops():
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    relayed = {**b, "hops": ["node-A", "node-B"]}
    r = client.post("/v1/store", json={"node_id": "node-B", "bundles": [relayed]})
    assert r.json()["duplicates"] == 1
    # Le stock ne contient toujours qu'un seul bundle.
    assert len(STORE) == 1
    assert "node-B" in STORE[b["bundle_id"]]["hops"]


def test_expired_bundle_rejected():
    now = datetime.now(timezone.utc)
    b = make_bundle(expires_at=(now - timedelta(hours=1)).isoformat())
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    assert r.json()["expired"] == 1
    assert len(STORE) == 0


def test_max_hops_rejected():
    hops = [f"node-{i}" for i in range(12)]
    b = make_bundle(hops=hops, max_hops=10)
    r = client.post("/v1/store", json={"node_id": "node-X", "bundles": [b]})
    assert r.json()["rejected"] == 1


def test_sync_is_bidirectional():
    a_bundle = make_bundle(origin_node_id="node-A", hops=["node-A"])
    b_bundle = make_bundle(origin_node_id="node-B", hops=["node-B"])
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [a_bundle]})
    # B donne son bundle et récupère celui de A en un seul appel.
    r = client.post("/v1/sync", json={"node_id": "node-B", "bundles": [b_bundle], "known_ids": []})
    body = r.json()
    assert body["stored"] == 1
    ids = {x["bundle_id"] for x in body["bundles"]}
    assert a_bundle["bundle_id"] in ids
    assert b_bundle["bundle_id"] not in ids  # on ne rend pas à B ce qu'il vient de donner


def test_uplink_dry_run():
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [make_bundle()]})
    r = client.post("/v1/uplink", params={"dry_run": True})
    assert r.json()["pending"] == 1
    assert len(STORE) == 1  # dry-run ne vide pas le stock


def test_lru_eviction_when_full(monkeypatch):
    monkeypatch.setattr(main, "MAX_STORE", 2)
    first = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [first]})
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [make_bundle()]})
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [make_bundle()]})
    assert r.json()["stored"] == 1  # jamais de rejet par manque de place
    assert len(STORE) == 2
    assert first["bundle_id"] not in STORE  # le plus ancien sort
    assert COUNTERS["evicted_lru"] == 1


def test_api_key_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(main, "RELAY_KEY", "secret")
    assert client.get("/health").status_code == 200  # health reste ouvert
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [make_bundle()]})
    assert r.status_code == 401
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [make_bundle()]},
                    headers={"X-Mesh-Key": "secret"})
    assert r.status_code == 200


def test_stats_exposes_counters():
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    client.post("/v1/store", json={"node_id": "node-B", "bundles": [b]})
    body = client.get("/v1/stats").json()
    assert body["counters"]["stored"] == 1
    assert body["counters"]["duplicates"] == 1


def test_v11_fields_preserved():
    b = make_bundle(priority="high", copies_remaining=4, destination="dtn://wash-sentinel/ingest",
                    lifetime_seconds=3600, custody_requested=True)
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    fetched = client.post("/v1/fetch", json={"node_id": "node-B", "known_ids": []}).json()["bundles"][0]
    assert fetched["priority"] == "high"
    assert fetched["copies_remaining"] == 4
    assert fetched["destination"] == "dtn://wash-sentinel/ingest"
    assert fetched["custody_requested"] is True


def test_bad_priority_rejected():
    b = make_bundle(priority="urgentissime")
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    assert r.json()["rejected"] == 1


def _ts_style_checksum(bundle: dict) -> str:
    """Reproduit le calcul du SDK TS / client Kotlin (immuables seuls, UTF-8 brut)."""
    import hashlib
    import json

    from main import MUTABLE_FIELDS

    payload = {k: v for k, v in bundle.items() if k not in MUTABLE_FIELDS}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_checksum_with_accents_verifies():
    b = make_bundle(message="Pompe brisée, élèves sans eau potable")
    b["checksum"] = _ts_style_checksum(b)
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    assert r.json()["stored"] == 1


def test_checksum_zulu_variant_verifies():
    b = make_bundle()
    b["created_at"] = b["created_at"].replace("+00:00", "Z")
    b["expires_at"] = b["expires_at"].replace("+00:00", "Z")
    b["checksum"] = _ts_style_checksum(b)
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    assert r.json()["stored"] == 1


def test_checksum_survives_forward_mutations():
    """Le checksum couvre les immuables : hops/copies mutés par les relais ne l'invalident pas."""
    b = make_bundle()
    b["checksum"] = _ts_style_checksum(b)
    # Simulation d'un forward A -> B -> C (comme simulate_hops.py).
    b["hops"] = ["node-A", "node-B", "node-C"]
    b["previous_node"] = "node-B"
    b["copies_remaining"] = 2
    r = client.post("/v1/store", json={"node_id": "node-C", "bundles": [b]})
    assert r.json()["stored"] == 1


def test_tampered_checksum_rejected():
    b = make_bundle()
    b["checksum"] = "0" * 64
    r = client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    assert r.json()["rejected"] == 1


def test_ack_advertised_only_to_nodes_holding_the_bundle():
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    # C a uploadé le bundle vers Laravel et prévient le relai.
    r = client.post("/v1/ack", json={"node_id": "node-C", "ids": [b["bundle_id"]]})
    assert r.json()["new"] == 1
    # B, qui transporte encore le bundle, apprend à le purger.
    r = client.post("/v1/sync", json={"node_id": "node-B", "bundles": [], "known_ids": [b["bundle_id"]]})
    assert b["bundle_id"] in r.json()["acked_ids"]
    # D, qui ne le connaît pas, ne reçoit rien (pas de fuite).
    r = client.post("/v1/sync", json={"node_id": "node-D", "bundles": [], "known_ids": []})
    assert r.json()["acked_ids"] == []


def test_media_fields_pass_through_opaque():
    manifest_id = make_bundle()["bundle_id"]
    frag = make_bundle(bundle_group=manifest_id, chunk="QUJDRA==", fragment_offset=0,
                       fragment_total=2, channel="photo")
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [frag]})
    fetched = client.post("/v1/fetch", json={"node_id": "node-B", "known_ids": []}).json()["bundles"][0]
    assert fetched["bundle_group"] == manifest_id
    assert fetched["chunk"] == "QUJDRA=="
    assert fetched["fragment_offset"] == 0


def test_uplink_flush_records_tombstones(monkeypatch):
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})

    class FakeResp:
        status_code = 201
        headers = {"content-type": "application/json"}

        def json(self):
            return {"incidents": [{"bundle_id": b["bundle_id"]}]}

    monkeypatch.setattr(main.httpx, "post", lambda *a, **k: FakeResp())
    r = client.post("/v1/uplink")
    assert r.json()["flushed"] == [b["bundle_id"]]
    assert len(STORE) == 0
    assert b["bundle_id"] in ACKED
