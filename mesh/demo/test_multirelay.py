#!/usr/bin/env python3
"""Harnais multi-relais : preuve du multi-saut A→B→C sans téléphone.

Démarre 3 vrais relais uvicorn en sous-processus (ports 127.0.0.1 dynamiques,
bases SQLite temporaires distinctes, clés vides) et rejoue un flux
store-and-forward inter-relais via les seuls endpoints REST.

Usage :
    /tmp/venv-ops/bin/pytest mesh/demo/test_multirelay.py -q   # local (venv partagé)
    python -m pytest mesh/demo/test_multirelay.py -q            # CI (job relay, racine)

Conventions reprises de simulate_hops.py : forme canonique du checksum
(clés triées hors champs mutables, compact, UTF-8 brut), hops enrichis à
chaque saut. Dates à la seconde + suffixe Z : stables au round-trip
Pydantic/SQLite, donc le checksum reste vérifiable après chaque saut.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("uvicorn") is None,
    reason="uvicorn absent : harnais multi-relais ignoré",
)

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"

READY_TIMEOUT = 60.0  # boot uvicorn, CI lente
HTTP_TIMEOUT = 30.0
STOP_TIMEOUT = 15.0
POLL_INTERVAL = 0.25

# Champs de routage mutables : exclus du checksum (contrat du relai).
MUTABLE = {"checksum", "hops", "previous_node", "copies_remaining"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _zulu(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def checksum_of(bundle: dict) -> str:
    payload = {k: v for k, v in bundle.items() if k not in MUTABLE}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def make_bundle(origin: str = "node-A-yokadouma",
                message: str = "Pompe du forage brisée, 400 élèves sans eau.",
                expired: bool = False) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bundle = {
        "v": 1,
        "bundle_id": str(uuid4()),
        "origin_node_id": origin,
        "school_id": 1,
        "school_code": "CM-EST-0042",
        "channel": "text",
        "message": message,
        "created_at": _zulu(now),
        "expires_at": _zulu(now - timedelta(hours=1) if expired else now + timedelta(days=7)),
        "max_hops": 10,
        "hops": [origin],
        "destination": "dtn://wash-sentinel/ingest",
        "lifetime_seconds": 7 * 86400,
        "copies_remaining": 8,
        "priority": "normal",
    }
    bundle["checksum"] = checksum_of(bundle)
    return bundle


def forward(bundle: dict, node_id: str) -> dict:
    """Le transporteur retransmet son exemplaire local, hops enrichis."""
    nxt = deepcopy(bundle)
    nxt["hops"].append(node_id)
    nxt["previous_node"] = bundle["hops"][-1]
    return nxt


# Les relais sont sur 127.0.0.1 : jamais de proxy (un http_proxy positionné,
# même vide de no_proxy, avalerait sinon tout le trafic du harnais).
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"},
                                 method="POST")
    try:
        with _NO_PROXY_OPENER.open(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except ValueError:
            return exc.code, {}


def _get(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with _NO_PROXY_OPENER.open(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")


def _by_id(bundles: list[dict], bundle_id: str) -> dict | None:
    for bundle in bundles:
        if bundle.get("bundle_id") == bundle_id:
            return bundle
    return None


class Relay:
    """Un relai uvicorn en sous-processus : port dynamique, DB tmp, clés vides."""

    def __init__(self, name: str, db_path: Path, log_path: Path):
        self.name = name
        self.db_path = db_path
        self.log_path = log_path
        self.port = _free_port()
        self.proc: subprocess.Popen | None = None
        self._log_handle = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def store(self, node_id: str, bundles: list[dict]) -> tuple[int, dict]:
        return _post(f"{self.url}/v1/store", {"node_id": node_id, "bundles": bundles})

    def fetch(self, node_id: str, known_ids: list[str], limit: int = 50) -> tuple[int, dict]:
        return _post(f"{self.url}/v1/fetch",
                      {"node_id": node_id, "known_ids": known_ids, "limit": limit})

    def _spawn(self) -> None:
        env = dict(os.environ)
        env["MESH_DB_PATH"] = str(self.db_path)
        env["MESH_RELAY_API_KEY"] = ""
        env["MESH_INGEST_KEY"] = ""
        env["PYTHONUNBUFFERED"] = "1"
        self._log_handle = open(self.log_path, "a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(SERVER_DIR), env=env,
            stdout=self._log_handle, stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def _log_tail(self, nlines: int = 30) -> str:
        try:
            return "\n".join(self.log_path.read_text(encoding="utf-8").splitlines()[-nlines:])
        except OSError:
            return "<log illisible>"

    def _died_on_bind(self) -> bool:
        return (self.proc is not None and self.proc.poll() is not None
                and "address already in use" in self._log_tail().lower())

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + READY_TIMEOUT
        assert self.proc is not None
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"{self.name} : uvicorn sorti (code {self.proc.returncode}) :\n"
                                   f"{self._log_tail()}")
            try:
                status, _ = _get(f"{self.url}/health")
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(POLL_INTERVAL)
                continue
            if status == 200:
                return
            time.sleep(POLL_INTERVAL)
        self.stop()
        raise RuntimeError(f"{self.name} : /health injoignable après {READY_TIMEOUT}s :\n"
                           f"{self._log_tail()}")

    def start(self) -> None:
        self._spawn()
        try:
            self._wait_ready()
        except Exception:
            if self._died_on_bind():  # port repris entre-temps : un essai sur port frais
                self.port = _free_port()
                self._spawn()
                self._wait_ready()
            else:
                raise

    def kill9(self) -> None:
        """SIGKILL brutal : simule le crash du relai (le stock SQLite doit survivre)."""
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=STOP_TIMEOUT)

    def restart(self) -> None:
        """Redémarre sur la même DB (même port visé, repli sur port frais)."""
        self.stop()
        self._spawn()
        try:
            self._wait_ready()
        except Exception:
            if self._died_on_bind():
                self.port = _free_port()
                self._spawn()
                self._wait_ready()
            else:
                raise

    def stop(self) -> None:
        """Teardown garanti : terminate + join + timeout, puis kill. Ne lève jamais."""
        proc, self.proc = self.proc, None
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=STOP_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            print(f"[multirelay] {self.name} : arrêt incomplet ({exc})", file=sys.stderr)
        finally:
            if self._log_handle is not None:
                try:
                    self._log_handle.close()
                except OSError:
                    pass
                self._log_handle = None


@pytest.fixture
def cluster(tmp_path_factory):
    """Trio de relais A/B/C ; teardown garanti même en échec."""
    workdir = tmp_path_factory.mktemp("multirelay")
    relays = [Relay(name, workdir / f"{name}.sqlite", workdir / f"{name}.log")
              for name in ("A", "B", "C")]
    try:
        for relay in relays:
            relay.start()
    except Exception:
        for relay in reversed(relays):
            relay.stop()
        raise
    yield relays
    for relay in reversed(relays):
        relay.stop()


def test_multihop_chain_A_B_C(cluster):
    """store A → fetch → store B → fetch → store C : présent sur C, hops enrichis."""
    relay_a, relay_b, relay_c = cluster
    bundle = make_bundle(
        message="Pompe du forage brisée depuis ce matin, 400 élèves sans eau — multi-saut.")

    status, body = relay_a.store("node-A-yokadouma", [bundle])
    assert status == 200 and body["stored"] == 1, f"store A : {status} {body}"

    status, carried = relay_a.fetch("carrier-B-taximoto", [])
    assert status == 200, carried
    assert _by_id(carried["bundles"], bundle["bundle_id"]) is not None, carried

    leg_b = forward(bundle, "node-B-taximoto")
    status, body = relay_b.store("node-B-taximoto", [leg_b])
    assert status == 200 and body["stored"] == 1, f"store B : {status} {body}"

    status, carried = relay_b.fetch("carrier-C-bertoua", [])
    hop_b = _by_id(carried["bundles"], bundle["bundle_id"])
    assert hop_b is not None, carried
    assert hop_b["hops"] == ["node-A-yokadouma", "node-B-taximoto"], hop_b["hops"]

    leg_c = forward(leg_b, "node-C-bertoua")
    status, body = relay_c.store("node-C-bertoua", [leg_c])
    assert status == 200 and body["stored"] == 1, f"store C : {status} {body}"

    status, carried = relay_c.fetch("verifier", [])
    assert status == 200, carried
    final = _by_id(carried["bundles"], bundle["bundle_id"])
    assert final is not None, carried
    assert final["hops"] == ["node-A-yokadouma", "node-B-taximoto", "node-C-bertoua"], final["hops"]
    assert len(final["hops"]) - 1 == 2  # hop_count : 2 sauts


def test_median_relay_crash_keeps_sqlite_store(cluster):
    """kill -9 du relai médian puis restart : le stock SQLite survit (re-fetch OK)."""
    relay_a, relay_b, relay_c = cluster
    bundle = make_bundle(message="Crash-test : le stock SQLite survit au kill -9.")
    _, body = relay_a.store("node-A-yokadouma", [bundle])
    assert body["stored"] == 1, body
    leg_b = forward(bundle, "node-B-taximoto")
    _, body = relay_b.store("node-B-taximoto", [leg_b])
    assert body["stored"] == 1, body

    _, before = relay_b.fetch("verifier", [])
    assert _by_id(before["bundles"], bundle["bundle_id"]) is not None, before

    relay_b.kill9()
    relay_b.restart()

    status, after = relay_b.fetch("verifier", [])
    revived = _by_id(after["bundles"], bundle["bundle_id"])
    assert status == 200 and revived is not None, after
    assert revived["hops"] == ["node-A-yokadouma", "node-B-taximoto"], revived["hops"]

    fresh = make_bundle(message="Post-crash : le relai accepte de nouveaux bundles.")
    status, body = relay_b.store("node-B-taximoto", [fresh])
    assert status == 200 and body["stored"] == 1, body


def test_expired_bundle_not_propagated(cluster):
    """Bundle expiré : refusé partout, jamais propagé ni servi."""
    relay_a, relay_b, relay_c = cluster
    bundle = make_bundle(expired=True, message="Expiré : ne doit jamais traverser.")

    status, body = relay_a.store("node-A-yokadouma", [bundle])
    assert status == 200 and body["expired"] == 1 and body["stored"] == 0, body

    for relay in (relay_a, relay_b, relay_c):
        status, carried = relay.fetch("verifier", [])
        assert status == 200, carried
        assert _by_id(carried["bundles"], bundle["bundle_id"]) is None, carried

    for relay in (relay_b, relay_c):
        status, body = relay.store("node-X", [bundle])
        assert status == 200 and body["expired"] == 1 and body["stored"] == 0, body


def test_duplicate_store_enriches_without_downstream_copy(cluster):
    """Re-store → duplicates:1, hops enrichis, un seul exemplaire par relai."""
    relay_a, relay_b, relay_c = cluster
    bundle = make_bundle(message="Doublon : un seul exemplaire par relai.")

    _, first = relay_a.store("node-A-yokadouma", [bundle])
    assert first["stored"] == 1, first
    _, second = relay_a.store("node-A-yokadouma", [bundle])
    assert second["duplicates"] == 1 and second["stored"] == 0, second

    _, carried = relay_a.fetch("verifier", [])
    copies = [b for b in carried["bundles"] if b["bundle_id"] == bundle["bundle_id"]]
    assert len(copies) == 1, carried

    leg_b = forward(bundle, "node-B-taximoto")
    _, body = relay_b.store("node-B-taximoto", [leg_b])
    assert body["stored"] == 1, body
    leg_b_dup = forward(leg_b, "node-B-bis")
    _, body = relay_b.store("node-B-bis", [leg_b_dup])
    assert body["duplicates"] == 1 and body["stored"] == 0, body
    _, carried = relay_b.fetch("verifier", [])
    copies = [b for b in carried["bundles"] if b["bundle_id"] == bundle["bundle_id"]]
    assert len(copies) == 1, carried
    assert "node-B-bis" in copies[0]["hops"], copies[0]["hops"]

    leg_c = forward(leg_b, "node-C-bertoua")
    _, body = relay_c.store("node-C-bertoua", [leg_c])
    assert body["stored"] == 1, body
    _, carried = relay_c.fetch("verifier", [])
    copies = [b for b in carried["bundles"] if b["bundle_id"] == bundle["bundle_id"]]
    assert len(copies) == 1, carried
