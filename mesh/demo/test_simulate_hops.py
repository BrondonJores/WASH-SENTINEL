"""Tests de la démo multi-sauts (simulate_hops.py).

P0 accents : `checksum_of` sérialise en UTF-8 brut (`ensure_ascii=False`),
exactement comme le relai (`main.canonical_checksum`) — sinon tout bundle
accentué est rejeté en --live. Faux-vert --live : un HTTP 200 avec
`rejected > 0` est un échec (`store_response_ok`).
"""

import hashlib
import json
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(DEMO_DIR.parent / "server"))

import simulate_hops  # noqa: E402


def _accented_bundle() -> dict:
    return {
        "v": 1,
        "bundle_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "origin_node_id": "node-A-yokadouma",
        "school_id": 1,
        "channel": "text",
        "message": "Pompe brisée, 400 élèves sans eau — forage en panne.",
        "created_at": "2026-10-31T10:00:00+00:00",
        "expires_at": "2026-11-07T10:00:00+00:00",
        "max_hops": 10,
        "hops": ["node-A-yokadouma"],
        "destination": "dtn://wash-sentinel/ingest",
        "lifetime_seconds": 604800,
        "copies_remaining": 8,
        "priority": "normal",
    }


def test_checksum_of_matches_relay_canonical_with_accents():
    """Même octets canoniques des deux côtés malgré les accents."""
    import main

    bundle = _accented_bundle()
    assert simulate_hops.checksum_of(bundle) == main.canonical_checksum(bundle)
    # Et ce n'est pas la forme ASCII historique (accents échappés).
    ascii_raw = json.dumps(
        {k: v for k, v in bundle.items() if k not in simulate_hops.MUTABLE},
        sort_keys=True, separators=(",", ":"),
    )
    assert "\\u00e9" in ascii_raw  # la forme ASCII échappe bien les accents…
    assert simulate_hops.checksum_of(bundle) != hashlib.sha256(ascii_raw.encode()).hexdigest()


def test_accented_bundle_accepted_by_relay_store():
    """Preuve live-path : bundle accentué de la démo accepté par /v1/store."""
    from fastapi.testclient import TestClient

    import main

    main.STORE.clear()
    main.ACKED.clear()
    for key in main.COUNTERS:
        main.COUNTERS[key] = 0
    bundle = simulate_hops.create_bundle(1, "Forage brisé — élèves sans eau potable.")
    r = TestClient(main.app).post("/v1/store", json={"node_id": "node-C-bertoua", "bundles": [bundle]})
    assert r.status_code == 200, r.text
    assert r.json()["stored"] == 1, r.text
    assert r.json()["rejected"] == 0, r.text


def test_store_response_ok():
    ok = simulate_hops.store_response_ok
    assert ok(200, '{"stored": 1, "rejected": 0}') is True
    assert ok(200, '{"stored": 0, "rejected": 2, "stored_total": 5}') is False
    assert ok(200, "") is True  # corps vide : retombe sur le statut HTTP
    assert ok(200, "pas-du-json{") is True
    assert ok(500, '{"stored": 0}') is False
    assert ok(0, "ConnectError: refusé") is False
