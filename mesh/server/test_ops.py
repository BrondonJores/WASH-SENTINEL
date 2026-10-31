"""Tests ops du relai mesh (chantier C5) : persistance SQLite, /metrics,
uplink résilient (retry + disjoncteur). Base SQLite sur fichier tmp par test."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
import storage
from main import ACKED, COUNTERS, STORE, UPLINK, app

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


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path):
    """Chaque test ops tourne sur sa propre base SQLite (fichier tmp)."""
    storage.init_db(str(tmp_path / "relay.db"))
    STORE.clear()
    ACKED.clear()
    for key in COUNTERS:
        COUNTERS[key] = 0
    UPLINK.update(attempts=0, retries=0, failures=0, breaker_opens=0,
                  last_error=None, breaker_open_until=None)
    main.RELAY_KEY = ""
    yield
    storage.init_db()  # retour à la base par défaut (MESH_DB_PATH ou ./relay.db)


def _restart() -> dict:
    """Simule un redémarrage : cache chaud vidé, puis rechargé depuis SQLite."""
    STORE.clear()
    ACKED.clear()
    return main.restore_from_db()


# ---------- Persistance ----------

def test_bundles_survive_restart():
    b = make_bundle()
    assert client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]}).json()["stored"] == 1
    assert storage.count_bundles() == 1
    stats = _restart()
    assert stats["bundles"] == 1
    body = client.post("/v1/fetch", json={"node_id": "node-B", "known_ids": []}).json()
    assert body["count"] == 1
    assert body["bundles"][0]["bundle_id"] == b["bundle_id"]
    assert body["bundles"][0]["message"] == b["message"]


def test_acks_survive_restart():
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    assert client.post("/v1/ack", json={"node_id": "node-C", "ids": [b["bundle_id"]]}).json()["new"] == 1
    assert storage.count_acked() == 1
    stats = _restart()
    assert stats["acked"] == 1
    body = client.post("/v1/sync", json={"node_id": "node-B", "bundles": [],
                                         "known_ids": [b["bundle_id"]]}).json()
    assert b["bundle_id"] in body["acked_ids"]


def test_expired_bundles_dropped_on_restore():
    now = datetime.now(timezone.utc)
    bid = str(uuid4())
    storage.save_bundle(bid, {"bundle_id": bid, "origin_node_id": "node-A",
                              "created_at": now - timedelta(days=8),
                              "expires_at": now - timedelta(days=1),
                              "stored_at": now - timedelta(days=8),
                              "received_via": "node-A", "hops": ["node-A"]})
    assert storage.count_bundles() == 1
    stats = _restart()
    assert stats["bundles"] == 0
    assert stats["dropped_expired"] == 1
    assert len(STORE) == 0
    assert storage.count_bundles() == 0


def test_lru_eviction_removes_from_db(monkeypatch):
    monkeypatch.setattr(main, "MAX_STORE", 2)
    first = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [first]})
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [make_bundle()]})
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [make_bundle()]})
    assert len(STORE) == 2
    assert storage.count_bundles() == 2  # le cache chaud et SQLite restent alignés
    bundles, _ = storage.load_all()
    assert first["bundle_id"] not in bundles


def test_duplicate_hops_enrichment_is_persisted():
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    relayed = {**b, "hops": ["node-A", "node-B"]}
    assert client.post("/v1/store", json={"node_id": "node-B", "bundles": [relayed]}).json()["duplicates"] == 1
    _restart()
    assert "node-B" in STORE[b["bundle_id"]]["hops"]


# ---------- /metrics ----------

def test_metrics_endpoint():
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    body = client.get("/metrics").json()
    assert body["stored"] == 1
    assert body["uplink_queue"] == 1
    assert body["counters"]["stored"] == 1
    assert body["uptime_seconds"] >= 0
    assert body["sqlite"]["bytes"] > 0
    assert body["sqlite"]["path"].endswith("relay.db")
    assert set(body["uplink"]) >= {"attempts", "retries", "failures", "breaker_opens", "last_error"}


def test_metrics_open_without_key(monkeypatch):
    monkeypatch.setattr(main, "RELAY_KEY", "secret")
    assert client.get("/metrics").status_code == 200  # sondage sans clé, comme /health
    assert client.get("/v1/stats").status_code == 401


# ---------- Uplink résilient ----------

class FakeResp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self._body = body if body is not None else {}
        self.text = str(self._body)[:500]

    def json(self):
        return self._body


def _store_one_for_uplink():
    b = make_bundle()
    client.post("/v1/store", json={"node_id": "node-A", "bundles": [b]})
    return b


def test_uplink_retries_then_succeeds(monkeypatch):
    import httpx as httpx_mod

    b = _store_one_for_uplink()
    monkeypatch.setattr(main, "UPLINK_BACKOFF_BASE", 0.0)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx_mod.ConnectError("réseau villageois")
        return FakeResp(201, {"incidents": [{"bundle_id": b["bundle_id"]}]})

    monkeypatch.setattr(main.httpx, "post", flaky)
    body = client.post("/v1/uplink").json()
    assert body["flushed"] == [b["bundle_id"]]
    assert len(STORE) == 0
    assert storage.count_bundles() == 0
    assert UPLINK["attempts"] == 3
    assert UPLINK["retries"] == 2
    assert UPLINK["failures"] == 0


def test_uplink_retryable_503_then_ok(monkeypatch):
    b = _store_one_for_uplink()
    monkeypatch.setattr(main, "UPLINK_BACKOFF_BASE", 0.0)
    responses = [FakeResp(503, {"error": "maintenance"}),
                 FakeResp(201, {"incidents": [{"bundle_id": b["bundle_id"]}]})]
    monkeypatch.setattr(main.httpx, "post", lambda *a, **k: responses.pop(0))
    body = client.post("/v1/uplink").json()
    assert body["flushed"] == [b["bundle_id"]]
    assert UPLINK["attempts"] == 2
    assert UPLINK["retries"] == 1


def test_uplink_4xx_is_not_retried(monkeypatch):
    _store_one_for_uplink()
    monkeypatch.setattr(main, "UPLINK_BACKOFF_BASE", 0.0)
    calls = {"n": 0}

    def bad_request(*a, **k):
        calls["n"] += 1
        return FakeResp(400, {"error": "payload invalide"})

    monkeypatch.setattr(main.httpx, "post", bad_request)
    body = client.post("/v1/uplink").json()
    assert calls["n"] == 1  # 4xx définitive : pas de retry
    assert body["laravel"]["status_code"] == 400
    assert body["flushed"] == []
    assert len(STORE) == 1  # le stock est conservé
    assert UPLINK["failures"] == 0


def test_uplink_breaker_opens_and_shortcircuits(monkeypatch):
    import httpx as httpx_mod

    _store_one_for_uplink()
    monkeypatch.setattr(main, "UPLINK_BACKOFF_BASE", 0.0)
    monkeypatch.setattr(main, "UPLINK_RETRIES", 1)
    monkeypatch.setattr(main, "BREAKER_THRESHOLD", 2)
    monkeypatch.setattr(main, "BREAKER_COOLDOWN", 60.0)
    calls = {"n": 0}

    def down(*a, **k):
        calls["n"] += 1
        raise httpx_mod.ConnectError("Laravel injoignable")

    monkeypatch.setattr(main.httpx, "post", down)
    assert client.post("/v1/uplink").json()["flushed"] is False
    assert UPLINK["failures"] == 1
    assert client.post("/v1/uplink").json()["flushed"] is False
    assert UPLINK["failures"] == 2
    assert UPLINK["breaker_opens"] == 1
    calls_before = calls["n"]
    assert calls_before == 4  # 2 uplinks x (1 essai + 1 retry)
    body = client.post("/v1/uplink").json()
    assert body["laravel"]["error"] == "breaker_open"
    assert calls["n"] == calls_before  # disjoncteur ouvert : aucun appel HTTP
    assert body["pending"] == 1  # … et le stock est conservé


def test_breaker_recovers_after_cooldown(monkeypatch):
    b = _store_one_for_uplink()
    monkeypatch.setattr(main, "UPLINK_BACKOFF_BASE", 0.0)
    UPLINK["failures"] = 5
    UPLINK["breaker_open_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(main.httpx, "post",
                        lambda *a, **k: FakeResp(201, {"incidents": [{"bundle_id": b["bundle_id"]}]}))
    body = client.post("/v1/uplink").json()
    assert body["flushed"] == [b["bundle_id"]]
    assert UPLINK["failures"] == 0
    assert UPLINK["breaker_open_until"] is None
