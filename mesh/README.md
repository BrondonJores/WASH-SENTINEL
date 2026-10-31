# 🕸️ WASH Mesh — offline reporting for remote schools

### Store-and-forward community mesh: a report hops phone to phone until it reaches the internet.

[![Relay](https://img.shields.io/badge/relay-FastAPI%20%7C%20SQLite-green)]()
[![Tests](https://img.shields.io/badge/tests-59%20pytest%20%7C%2056%20PHPUnit-green)]()
[![Crypto](https://img.shields.io/badge/crypto-libsodium%20only-blue)]()
[![Status](https://img.shields.io/badge/status-functional%20except%20real%20radio-yellow)]()

> Part of [WASH Sentinel](../README.md) — the dashboardless AI guardian for school water & sanitation. Runbooks: [field install](../docs/INSTALL.md) · [USSD](../docs/USSD.md) · [relay ops](../docs/MESH_RUNBOOK.md) · [Android app](android/README.md)

> **One sentence.** A director in a village without coverage writes a report on her phone; the report travels by QR, Bluetooth or WiFi from phone to phone (spray-and-wait, up to 10 hops, 7-day TTL) until one of them gets signal and uploads it — or falls back to SMS/USSD from any 2G phone.

Built for rural **Cameroon 🇨🇲** — pilot of the **Meta Hackathon**.

---

## 1. The problem

- Remote schools have **no data coverage**: the main console, WhatsApp and the public form all need internet.
- A broken pump still needs reporting **today**, not "when someone visits the village with a notebook".
- Feature phones (no apps, no data) must stay in the loop: **SMS/USSD + QR** are first-class citizens, not afterthoughts.
- iPhones can't relay in the background (Apple limits) — but they must still **create, carry and upload** reports.

## 2. The solution

```
Village (offline)                    Town (connected)         Server
┌─────────┐  QR/BT/WiFi  ┌─────────┐  QR/BT/WiFi  ┌─────────┐  HTTPS   ┌──────────┐
│ Node A  │─────────────►│ Node B  │─────────────►│ Node C  │─────────►│ Laravel  │
│ Yokad.  │  spray L=8   │taxi-moto│  spray L=4   │ Bertoua │  upload  │ incidents│
└─────────┘              └─────────┘              └─────────┘          └──────────┘
```
Every report is a **bundle**: signed, checksummed, deduplicated by UUID, forwarded with loop protection (`hops`), then triaged by the same AI pipeline as online reports (`source: mesh|sms|ussd`).

| Transport | Who | Payload | Status |
|---|---|---|---|
| QR show/scan/photo | any phone + PWA | ~0.5–0.9 KB text | ✅ proven in code |
| Nearby P2P_CLUSTER | Android relay APK | full bundles + media | 🟡 coded, radio untested |
| BLE GATT raw | degoogled Android | < 50 KB, no media | 🟡 coded, radio untested |
| SMS `WASH <CODE> <TYPE>` | any 2G phone | 1 report/SMS | ✅ live-tested path |
| USSD menus `*123#` | any 2G phone | guided report | ✅ tested, no operator code yet |
| PWA `/m` + desktop | iPhone/PC | create, carry, upload | ✅ installable, offline |

## 3. Why this design wins 🏆

1. **Offline-first, honestly** — the outbox, the QR codec and the relay protocol are the product, not a degraded mode. The field app boots in airplane mode after one online visit.
2. **Zero home-made crypto** — libsodium sealed boxes (E2E) + Ed25519 (authenticity), verified byte-identical across TypeScript, Python and PHP against one golden vector.
3. **Delay-tolerant by the book** — Binary Spray-and-Wait (L=8), BPv7-aligned fields (destination EID, lifetime, custody/priority), 7-day TTL, ACK tombstones, SQLite persistence across restarts.
4. **Every claim has a test** — 59 relay/frames/harness tests, 56 Laravel mesh tests, a 3-relay chaos harness in CI, live probes against real HTTP. What isn't proven (real radio) is labeled as such — see §11.
5. **Leave no phone behind** — $30 Android relays for everyone; iPhone captures and uploads; feature phones text `WASH DOU-BON-001 P`.

## 4. Protocol

A bundle (`mesh/sdk/mesh-sdk.ts`, zero dependencies):

```json
{
  "v": 1,
  "bundle_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "origin_node_id": "node-A-yokadouma",
  "school_id": 1,
  "school_code": "DOU-BON-001",
  "channel": "text",
  "message": "Pompe brisée, 400 élèves sans eau potable",
  "created_at": "2026-01-15T10:00:00.000Z",
  "expires_at": "2026-01-22T10:00:00.000Z",
  "max_hops": 10,
  "hops": ["node-A-yokadouma", "node-B-taximoto"],
  "destination": "dtn://wash-sentinel/ingest",
  "lifetime_seconds": 604800,
  "copies_remaining": 4,
  "priority": "high",
  "node_pubkey": "hnd9uoXFRxizbRXJjUMzQZJ0V9AB/qqLNjhgc3sjMCk=",
  "signature": "f6DrYLlnkZbx4+YFRx8UKeXuql2DXjfrwkO/jPx7e8+fAUD6O3agxVljp5NTfB4ypbxSUycmh6t4V6X7sCB2BQ==",
  "checksum": "9f2c…"
}
```

| Mechanism | Rule | Code |
|---|---|---|
| Identity | `bundle_id` UUIDv4 → dedup everywhere | SDK, relay, Laravel |
| Integrity | SHA-256 over immutable fields only (mutable `hops`/`previous_node`/`copies` excluded) | `checksumOf` × 3 langs |
| Authenticity | Ed25519 detached over canonical bytes; `node_pubkey` included, `signature` excluded | `MeshSignature`, `mesh_verify` |
| Trust on first use | first key memorized per origin; change → `key_changed` alert (accepted, never silently) | `mesh_node_keys` table |
| Confidentiality | libsodium sealed box to the server key; relays see routing metadata only | `MeshSeal`, `mesh-crypto` |
| Forwarding | Binary Spray-and-Wait L=8; refuse if already in `hops` (loop-free) | `forwardBundle` |
| Media | encrypt-then-chunk: manifest + fragments, out-of-order reassembly, SHA-256 after open | `splitMedia`, `MeshMediaAssembler` |
| BLE frames | `WS` + ver + tag(4) + index/total (2+2 BE) + payload; MTU ≤ 512 | `BleFrame.kt` ⇄ `ble_frames.py` |

## 5. Architecture

```text
                        ┌──────────────────────┐
                        │  Laravel 12 (:80)    │
                        │  bundles/sms/ussd    │
                        │  seal open · triage  │
                        └──────────▲───────────┘
                        upload     │ uplink (retry+breaker)
┌────────────┐  sync/fetch/store   │   ┌──────────────────┐
│ Village    │◄────────────────────┼───│ mesh-relay :8001 │
│ WiFi relay │                     │   │ SQLite · LRU 5k  │
└────────────┘                     │   └──────────────────┘
        │ QR / Nearby / BLE GATT   │ WS /v1/ws/{node}
┌───────┴────────┐  ┌──────────────┴┐  ┌──────────────────┐
│ Android APK    │  │ PWA /m +      │  │ Feature phones   │
│ (relay+SMS gw) │  │ desktop binary│  │ (SMS + USSD)     │
└────────────────┘  └───────────────┘  └──────────────────┘
```

**Repo map:**

```text
mesh/
├── README.md            # this file (protocol contract + status)
├── sdk/mesh-sdk.ts      # zero-dep TS client (mirrored into frontend/, CI-guarded)
├── server/              # FastAPI relay: main.py, storage.py, mesh_verify.py + tests
├── demo/                # simulate_hops.py (local/live/burst) + BLE frame mirror + multirelay harness
└── android/             # Kotlin relay APK: Nearby + BLE + SMS gateway + QR + UI + unit tests
```

Satellites: `backend/app/{Http/Controllers/Api/WashMesh*,Services/Mesh*,Models/Mesh*}` (ingest),
`frontend/src/pages/MeshFieldPage.tsx` + `lib/mesh*` (field PWA), `desktop/` (Neutralino binary).

## 6. Components

| Piece | What it does | Verify |
|---|---|---|
| Relay `:8001` | store/fetch/sync/ack/uplink/WS, LRU+SQLite, `/metrics` | `pytest mesh/server mesh/demo` → 59 |
| Laravel ingest | bundles+sms+ussd → sealed open → AI triage → incidents | `php artisan test --filter 'WashMesh\|WashSms\|WashUssd\|MeshSig\|MeshNodeKey'` → 56 |
| TS SDK | create/sign/QR/split/upload, localStorage outbox | `tsc`, SDK smoke, golden vector |
| Android APK | background relay, BLE fallback, SMS gateway, QR | CI `assembleDebug` + `testDebugUnitTest` |
| PWA `/m` | public, installable, offline outbox + QR + upload | build: 21 precache entries incl. `/m` |
| Desktop binary | Neutralino wrapper booting on `/m` offline | CI artifact `wash-relai-desktop` |
| SMS/USSD | `WASH <CODE> <TYPE>` + guided `*123#` menus | feature tests + live curl |

## 7. Quickstart

**Simulated hops (no hardware):**

```bash
python3 mesh/demo/simulate_hops.py            # A→B→C locally, loop + spray demo
python3 mesh/demo/simulate_hops.py --live     # POSTs to relay :8001 + Laravel :80
python3 mesh/demo/simulate_hops.py --burst 50 # 50 fresh + 5 dups + 1 invalid + 1 expired
```

**3-relay chaos harness** (spawns real relay processes, kill -9, TTL, duplicates):

```bash
/tmp/venv-ops/bin/pytest mesh/demo/test_multirelay.py -q   # local venv
python -m pytest mesh/demo/test_multirelay.py -q           # CI (relay job)
```

**Stack:** `./start.sh` (7 services incl. `mesh-relay`), then open the field app at
`http://localhost:5173/m` — install it once (Safari → Add to Home Screen), then try airplane mode.

## 8. API overview

**Relay** (`:8001`, `X-Mesh-Key` required iff `MESH_RELAY_API_KEY` set —
`/health` and `/metrics` stay open):
`GET /health|/metrics` · `POST /v1/store|fetch|sync|ack|uplink` · `GET /v1/stats` ·
`WS /v1/ws/{node_id}` (`?key=` auth).

**Laravel** (`:80/api/v1/mesh`, 60/min throttle on writes):
`POST /bundles|sms|ussd` · `GET /ussd` (probe) · `GET /key` (seal public key) ·
`GET /bundles/pending|bundles/{id}|stats`.

**Relay env** (`compose.yaml`): `LARAVEL_URL`, `MESH_INGEST_KEY`, `MESH_RELAY_API_KEY`,
`MESH_MAX_STORE` (5000), `MESH_DB_PATH` (`/data/relay.db` on named volume),
`MESH_UPLINK_RETRIES` (3) / `MESH_UPLINK_BACKOFF` (0.5s) / breaker (5 fails, 60s cooldown),
`FORWARD_MESH_PORT` (8001).

## 9. Security model

- **Curious-relay threat model**: relays verify checksums and signatures but only ever see
  routing metadata; `sealed` payloads open exclusively on the server (`MeshSeal`, libsodium).
- **Signatures**: Ed25519 detached, base64 standard (sig 88 chars, pubkey 44). Unsigned bundles
  accepted; invalid-signed rejected — at relay ingress **and** on direct Laravel upload.
- **TOFU**: first `node_pubkey` per origin is memorized (`mesh_node_keys`); a changed key raises
  `mesh.node.key_changed` (accepted, never silently).
- **Hygiene**: throttle 60/min, school must exist, quotas (SMS 10/day/sender, mesh 500/day/origin),
  no PII in bundles (no names/phone numbers), `sig_bypassed_no_backend` counter if Ed25519 libs are missing.
- **Honest downgrades**: no server key → 503 → clients send cleartext **with a warning**;
  SMS is always cleartext (feature phones) — allowlist + shared secret + quotas; USSD has no
  shared secret (relies on operator gateway + throttle).

## 10. Engineering you can audit 🔒

- **59 pytest** (`mesh/server` 18 relay + 12 ops + 15 sig · `mesh/demo` 7 BLE + 3 sim + 4 multirelay):
  `MESH_DB_PATH=/tmp/relay.db /tmp/venv-ops/bin/pytest mesh/server mesh/demo -q`
- **56 PHPUnit** (bundles, media, SMS, USSD, signatures, TOFU):
  `php artisan test --filter 'WashMeshTest|WashMeshMediaTest|WashSmsTest|MeshSmsParserTest|WashUssdTest|MeshSignatureTest|MeshNodeKeyTest'`
- **Interop, not just unit tests**: the TS SDK, `mesh_verify.py` and `MeshSignature.php` reproduce
  one golden vector byte-for-byte (real libsodium, real PyNaCl, real ext-sodium); the relay uplink
  preserves verifiable signatures end-to-end (proven with TestClient + `php -r`).
- **Android**: 21 sources + 5 unit-test files (`testDebugUnitTest` in CI); BLE frames mirrored and
  tested in Python (`ble_frames.py`, 7 tests) since no JDK/SDK is available in dev containers.
- **PWA**: `tsc` + build green, service worker precaches the shell + `/m`, lint 0 errors.

## 11. Honest limits (what is NOT proven)

- **Real radio**: Nearby and BLE GATT never ran on physical phones — range, throughput, battery
  and the 8 s/22 s duty cycle are unmeasured. Two cheap Androids side by side remain the
  incompressible validation (no cloud emulator does proximity radio: Appetize none, Genymotion
  beacons only, Test Lab isolated devices).
- **No operator USSD code** provisioned (`*123#` is fictional); SMS costs + cleartext accepted.
- **iOS can't relay** (Apple background limits) — capture + QR + upload only.
- **Central server**: offline covers collection; consolidation still needs Laravel reachable.
- **Capacities**: relay SQLite is single-file (5k LRU), spray L=8 fixed, no congestion control,
  village clocks untrusted (lifetime preferred; non-Z-millisecond emitters lose signatures in transit).

## 12. Roadmap

- [x] v1: multi-hop text + QR + relay + Laravel ingest
- [x] v1.1: BPv7 alignment, binary spray, quotas, ACK, SMS channel
- [x] v2a: E2E sealed boxes (libsodium, zero home-made crypto)
- [x] v2b: photos + short voice (deferred fragments, E2E preserved)
- [x] v3: Android Nearby app, SMS gateway, raw BLE GATT fallback (+ auto-select)
- [x] app v1: installable offline PWA `/m` (iPhone), desktop binary, APK via CI
- [x] app v2: Ed25519 signatures + TOFU, USSD channel, SQLite/metrics/retry relay,
  PWA (Background Sync, install prompt, outbox states), hardened APK (boot, duty-cycle, SMS policy, unit tests)
- [x] P0: relay persistence volume, multi-relay chaos harness, jury docs aligned
- [ ] Two-phone field validation (Nearby + BLE range/battery/duty-cycle)
- [ ] LoRa feasibility + ART regulatory check
- [ ] Real operator USSD code + SMS gateway contract
- [ ] iOS native spike (Mac + Xcode required)
- [ ] Congestion control / adaptive spray (research)

---

*WASH Mesh — leave no school behind, even without signal.* 💧🇨🇲
