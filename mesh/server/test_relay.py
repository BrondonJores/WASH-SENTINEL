"""Tests du relai mesh : déduplication, TTL, sync bidirectionnelle."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from main import STORE, app

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
