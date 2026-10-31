"""Tests des signatures Ed25519 des bundles mesh (V2 « signatures nœuds »).

Vecteur doré partagé avec PHP (MeshSignatureTest) et TS (smoke /tmp) : généré
par ext-sodium depuis le seed sha256('wash-sentinel-mesh-sig-golden-v1').
Toute implémentation doit reproduire CANON à l'octet et valider SIG.
"""

import base64

import pytest

import mesh_verify

# Clés/libsodium : backend nacl préféré, repli 'cryptography' si absent.
needs_crypto = pytest.mark.skipif(not mesh_verify.is_available(), reason="ni pynacl ni cryptography installés")

GOLDEN_SECRET_B64 = "geBvTaFaB8DESUEbfrm3gnvT0xTHJTs4tRkcseXtj66Gd326hcVHGLNtFcmNQzNBknRX0AH+qos2OGBzeyMwKQ=="
GOLDEN_PUBLIC_B64 = "hnd9uoXFRxizbRXJjUMzQZJ0V9AB/qqLNjhgc3sjMCk="
GOLDEN_SIG_B64 = "f6DrYLlnkZbx4+YFRx8UKeXuql2DXjfrwkO/jPx7e8+fAUD6O3agxVljp5NTfB4ypbxSUycmh6t4V6X7sCB2BQ=="
GOLDEN_CANON = (
    '{"bundle_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6","channel":"text",'
    '"created_at":"2026-01-15T10:00:00.000Z","destination":"dtn://wash-sentinel/ingest",'
    '"expires_at":"2026-01-22T10:00:00.000Z","lifetime_seconds":604800,"max_hops":10,'
    '"message":"Pompe brisée, 400 élèves sans eau potable",'
    '"node_pubkey":"hnd9uoXFRxizbRXJjUMzQZJ0V9AB/qqLNjhgc3sjMCk=",'
    '"origin_node_id":"node-A-yokadouma","priority":"high","school_code":"CM-EST-42",'
    '"school_id":42,"v":1}'
)


def golden_bundle() -> dict:
    return {
        "v": 1,
        "bundle_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "origin_node_id": "node-A-yokadouma",
        "school_id": 42,
        "school_code": "CM-EST-42",
        "channel": "text",
        "message": "Pompe brisée, 400 élèves sans eau potable",
        "created_at": "2026-01-15T10:00:00.000Z",
        "expires_at": "2026-01-22T10:00:00.000Z",
        "max_hops": 10,
        "hops": ["node-A-yokadouma", "node-B-taximoto"],
        "destination": "dtn://wash-sentinel/ingest",
        "lifetime_seconds": 604800,
        "previous_node": "node-A-yokadouma",
        "copies_remaining": 4,
        "priority": "high",
        "node_pubkey": GOLDEN_PUBLIC_B64,
        "signature": GOLDEN_SIG_B64,
    }


def test_golden_canonical_matches_php():
    """Forme canonique à l'octet près (accents/slashs bruts, exclusions)."""
    assert mesh_verify.canonical_string(golden_bundle()) == GOLDEN_CANON
    assert mesh_verify.canonical_bytes(golden_bundle()) == GOLDEN_CANON.encode("utf-8")


def test_golden_signature_layout():
    assert len(base64.b64decode(GOLDEN_SIG_B64)) == 64
    assert len(base64.b64decode(GOLDEN_PUBLIC_B64)) == 32
    assert len(GOLDEN_SIG_B64) == 88 and GOLDEN_SIG_B64.endswith("=")
    assert len(GOLDEN_PUBLIC_B64) == 44 and GOLDEN_PUBLIC_B64.endswith("=")


@needs_crypto
def test_golden_signature_verifies():
    assert mesh_verify.verify(golden_bundle()) is True
    assert mesh_verify.verify(golden_bundle(), GOLDEN_PUBLIC_B64) is True


@needs_crypto
def test_sign_is_deterministic_and_matches_golden():
    """Ed25519 déterministe : Python resigne le doré à l'identique."""
    bundle = golden_bundle()
    del bundle["signature"]
    assert mesh_verify.sign(bundle, GOLDEN_SECRET_B64) == GOLDEN_SIG_B64


@needs_crypto
def test_sign_verify_roundtrip():
    pub, sec = mesh_verify.generate_keypair()
    bundle = {"v": 1, "bundle_id": "b1", "origin_node_id": "node-X", "school_id": 7,
              "message": "hello", "created_at": "2026-01-15T10:00:00.000Z",
              "expires_at": "2026-01-22T10:00:00.000Z", "hops": ["node-X"]}
    signed = mesh_verify.sign_bundle(bundle, sec)
    assert signed["node_pubkey"] == pub
    assert "signature" not in bundle  # sign_bundle ne mute pas son entrée
    assert mesh_verify.verify(signed) is True
    assert mesh_verify.verify(signed, pub) is True


@needs_crypto
def test_tampered_content_fails():
    for key, value in [("message", "Pompe réparée, tout va bien"), ("school_id", 43),
                       ("priority", "normal"), ("node_pubkey", GOLDEN_PUBLIC_B64[:-4] + "AAAA")]:
        tampered = golden_bundle()
        tampered[key] = value
        assert mesh_verify.verify(tampered) is False, key
    # Couper-coller : signature valide sous une autre clé.
    other_pub, _ = mesh_verify.generate_keypair()
    cutpaste = golden_bundle()
    cutpaste["node_pubkey"] = other_pub
    assert mesh_verify.verify(cutpaste) is False


@needs_crypto
def test_forward_mutations_preserve_signature():
    """Les relais mutent hops/previous_node/copies_remaining sans invalider."""
    relayed = golden_bundle()
    relayed["hops"] = ["node-A-yokadouma", "node-B-taximoto", "node-C-bertoua"]
    relayed["previous_node"] = "node-B-taximoto"
    relayed["copies_remaining"] = 1
    relayed["checksum"] = "recalculé-par-le-relai"
    assert mesh_verify.verify(relayed) is True


@needs_crypto
def test_wrong_pubkey_fails():
    other_pub, _ = mesh_verify.generate_keypair()
    assert mesh_verify.verify(golden_bundle(), other_pub) is False


@needs_crypto
def test_malformed_inputs_fail_closed():
    assert mesh_verify.verify({}) is False
    no_sig = golden_bundle()
    del no_sig["signature"]
    assert mesh_verify.verify(no_sig) is False
    no_key = golden_bundle()
    del no_key["node_pubkey"]
    assert mesh_verify.verify(no_key) is False
    bad_b64 = golden_bundle()
    bad_b64["signature"] = "!!!pas-du-base64!!!"
    assert mesh_verify.verify(bad_b64) is False
    bad_len = golden_bundle()
    bad_len["signature"] = base64.b64encode(b"court").decode()
    assert mesh_verify.verify(bad_len) is False
    non_string = golden_bundle()
    non_string["signature"] = 12345
    assert mesh_verify.verify(non_string) is False
    with pytest.raises(ValueError):
        mesh_verify.sign(golden_bundle(), "pas-une-clé")
    with pytest.raises(ValueError):
        mesh_verify.sign(golden_bundle(), base64.b64encode(b"court").decode())


def test_none_values_are_dropped_like_ts_undefined():
    """None explicite ≡ clé absente (le SDK TS n'émet jamais null)."""
    a = golden_bundle()
    b = golden_bundle()
    b["school_code"] = None
    del a["school_code"]
    assert mesh_verify.canonical_string(a) == mesh_verify.canonical_string(b)


@needs_crypto
def test_datetime_objects_from_z_wire_verify():
    """Tolérance model_dump(mode='python') : datetimes Z → forme Z millis."""
    from datetime import datetime, timezone

    bundle = golden_bundle()
    bundle["created_at"] = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    bundle["expires_at"] = datetime(2026, 1, 22, 10, 0, 0, tzinfo=timezone.utc)
    assert mesh_verify.verify(bundle) is True
@needs_crypto
def test_store_accepts_valid_signed_bundle():
    """Câblage R2 : bundle signé valide accepté via /v1/store."""
    pytest.importorskip("fastapi")
    from uuid import uuid4

    from fastapi.testclient import TestClient

    import main

    main.STORE.clear()
    main.ACKED.clear()
    for key in main.COUNTERS:
        main.COUNTERS[key] = 0
    _, sec = mesh_verify.generate_keypair()
    bundle = {
        "bundle_id": str(uuid4()),
        "origin_node_id": "node-sig",
        "school_id": 1,
        "message": "Pompe test signée",
        "created_at": "2026-01-15T10:00:00.000Z",
        "expires_at": "2030-01-15T10:00:00.000Z",
        "hops": ["node-sig"],
        "max_hops": 10,
    }
    signed = mesh_verify.sign_bundle(bundle, sec)
    r = TestClient(main.app).post("/v1/store", json={"node_id": "node-sig", "bundles": [signed]})
    assert r.status_code == 200, r.text
    assert r.json()["stored"] == 1


@needs_crypto
def test_store_rejects_tampered_signed_bundle():
    """Câblage R2 : bundle signé puis modifié rejeté via /v1/store."""
    pytest.importorskip("fastapi")
    from uuid import uuid4

    from fastapi.testclient import TestClient

    import main

    main.STORE.clear()
    main.ACKED.clear()
    for key in main.COUNTERS:
        main.COUNTERS[key] = 0
    _, sec = mesh_verify.generate_keypair()
    bundle = {
        "bundle_id": str(uuid4()),
        "origin_node_id": "node-sig",
        "school_id": 1,
        "message": "Message original",
        "created_at": "2026-01-15T10:00:00.000Z",
        "expires_at": "2030-01-15T10:00:00.000Z",
        "hops": ["node-sig"],
        "max_hops": 10,
    }
    tampered = mesh_verify.sign_bundle(bundle, sec)
    tampered["message"] = "Message modifié après signature"
    r = TestClient(main.app).post("/v1/store", json={"node_id": "node-sig", "bundles": [tampered]})
    assert r.status_code == 200, r.text
    assert r.json()["rejected"] == 1


def test_store_without_crypto_backend_logs_and_counts_bypass(monkeypatch, capsys):
    """Sans backend Ed25519 : signé-invalide accepté avec traçabilité, jamais en silence."""
    pytest.importorskip("fastapi")
    from uuid import uuid4

    from fastapi.testclient import TestClient

    import main

    main.STORE.clear()
    main.ACKED.clear()
    for key in main.COUNTERS:
        main.COUNTERS[key] = 0
    monkeypatch.setattr(mesh_verify, "is_available", lambda: False)
    tampered = {
        "bundle_id": str(uuid4()),
        "origin_node_id": "node-sig",
        "school_id": 1,
        "message": "Signature forgée, backend absent",
        "created_at": "2026-01-15T10:00:00.000Z",
        "expires_at": "2030-01-15T10:00:00.000Z",
        "hops": ["node-sig"],
        "max_hops": 10,
        "node_pubkey": GOLDEN_PUBLIC_B64,
        "signature": GOLDEN_SIG_B64,  # valide pour le doré, pas pour ce bundle
    }
    r = TestClient(main.app).post("/v1/store", json={"node_id": "node-sig", "bundles": [tampered]})
    assert r.status_code == 200, r.text
    assert r.json()["stored"] == 1
    assert main.COUNTERS["sig_bypassed_no_backend"] == 1
    assert "NON vérifiée" in capsys.readouterr().err


@needs_crypto
def test_uplink_payload_preserves_signature(monkeypatch):
    """P0 signature-via-relai : le payload /v1/uplink vérifie comme à l'émission.

    Miroir Python de WashMeshController (unset received_via/previous_node_id,
    destination_eid/report_to_eid → destination/report_to) : mesh_verify et
    MeshSignature partagent le vecteur doré, donc verify==true ici vaut
    accepté (pas bad_signature) côté Laravel.
    """
    pytest.importorskip("fastapi")
    from uuid import uuid4

    from fastapi.testclient import TestClient

    import main

    main.STORE.clear()
    main.ACKED.clear()
    for key in main.COUNTERS:
        main.COUNTERS[key] = 0
    _, sec = mesh_verify.generate_keypair()
    bundle = {
        "v": 1,
        "bundle_id": str(uuid4()),
        "origin_node_id": "node-A-yokadouma",
        "school_id": 1,
        "school_code": "CM-EST-0042",
        "channel": "text",
        "message": "Pompe brisée depuis ce matin",
        "created_at": "2026-10-31T10:00:00.000Z",
        "expires_at": "2030-11-07T10:00:00.000Z",
        "max_hops": 10,
        "hops": ["node-A-yokadouma"],
        "destination": "dtn://wash-sentinel/ingest",
        "lifetime_seconds": 7 * 86400,
        "copies_remaining": 8,
        "priority": "normal",
    }
    signed = mesh_verify.sign_bundle(bundle, sec)
    client = TestClient(main.app)
    r = client.post("/v1/store", json={"node_id": "node-A-yokadouma", "bundles": [signed]})
    assert r.json()["stored"] == 1, r.text

    captured = {}

    class FakeResp:
        status_code = 201
        headers = {"content-type": "application/json"}
        text = "{}"

        def json(self):
            return {"incidents": []}

    def fake_post(*a, **k):
        captured["payload"] = k["json"]
        return FakeResp()

    monkeypatch.setattr(main.httpx, "post", fake_post)
    assert client.post("/v1/uplink").status_code == 200
    up = captured["payload"]["bundles"][0]
    assert up["created_at"] == "2026-10-31T10:00:00.000Z"
    assert up["expires_at"] == "2030-11-07T10:00:00.000Z"
    assert up["v"] == 1
    assert up["custody_requested"] is None
    ts_shape = {k: v for k, v in up.items() if k not in ("received_via_node_id", "previous_node_id")}
    for src, dst in (("destination_eid", "destination"), ("report_to_eid", "report_to")):
        if src in ts_shape:
            ts_shape[dst] = ts_shape.pop(src)
    assert mesh_verify.verify(ts_shape) is True
