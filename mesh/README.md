# 🕸️ WASH Mesh — offline reporting for remote schools

### Store-and-forward community mesh: a report hops phone to phone until it reaches the internet.

[![Relay](https://img.shields.io/badge/relay-FastAPI%20%7C%20SQLite%20WAL-green)]()
[![Tests](https://img.shields.io/badge/tests-59%20pytest%20%7C%2056%20PHPUnit%20%7C%20Kotlin-green)]()
[![Crypto](https://img.shields.io/badge/crypto-libsodium%20only-blue)]()
[![Coverage](https://img.shields.io/badge/interop-TS%20%E2%87%84%20Python%20%E2%87%84%20PHP%20golden%20vector-blue)]()
[![Status](https://img.shields.io/badge/status-functional%20except%20real%20radio-yellow)]()

> Part of [WASH Sentinel](../README.md) — the dashboardless AI guardian for school water & sanitation. Field guides: [install](../docs/INSTALL.md) · [USSD](../docs/USSD.md) · [relay ops](../docs/MESH_RUNBOOK.md) · [Android relay](android/README.md) · [Laravel backend](../backend/README.md) · [frontend](../frontend/README.md)

> **One sentence.** A director in a village without coverage writes a report on her phone; the report travels by QR, Bluetooth or WiFi from phone to phone (spray-and-wait, up to 10 hops, 7-day TTL) until one of them gets signal and uploads it — or falls back to SMS/USSD from any 2G phone.

Built for rural **Cameroon 🇨🇲** — pilot of the **Meta Hackathon**.

---

## Table of contents

1. [The problem](#1-the-problem) · 2. [The solution](#2-the-solution) · 3. [Why this design wins](#3-why-this-design-wins-) · 4. [Transports](#4-transports) · 5. [Bundle format](#5-bundle-format-exhaustive) · 6. [Canonical form, checksum, signature](#6-canonical-form-checksum--signature) · 7. [TOFU node keys](#7-tofu-node-keys) · 8. [End-to-end encryption](#8-end-to-end-encryption-sealed-boxes) · 9. [Fragmented media](#9-fragmented-media-photos--voice) · 10. [Forwarding: spray-and-wait, TTL, hops, ACK](#10-forwarding-spray-and-wait--ttl--hops--ack) · 11. [BLE frames](#11-ble-gatt-frames-backup-transport) · 12. [Relay server](#12-relay-server--8001) · 13. [Laravel ingest](#13-laravel-ingest--80) · 14. [TypeScript SDK](#14-typescript-sdk-zero-dependency) · 15. [PWA, desktop, APK](#15-pwa-desktop--apk) · 16. [SMS channel](#16-sms-channel-any-2g-phone) · 17. [USSD channel](#17-ussd-channel-guided-menus) · 18. [Threat model](#18-threat-model) · 19. [Tests](#19-tests-every-file) · 20. [Quickstart](#20-quickstart) · 21. [Honest limits](#21-honest-limits-what-is-not-proven) · 22. [Roadmap](#22-roadmap) · 23. [Glossary](#23-glossary) · 24. [Repo map](#24-repo-map)

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

## 3. Why this design wins 🏆

1. **Offline-first, honestly** — the outbox, the QR codec and the relay protocol are the product, not a degraded mode. The field app boots in airplane mode after one online visit.
2. **Zero home-made crypto** — libsodium sealed boxes (E2E) + Ed25519 (authenticity), verified byte-identical across TypeScript, Python and PHP against one golden vector.
3. **Delay-tolerant by the book** — Binary Spray-and-Wait (L=8), BPv7-aligned fields (destination EID, lifetime, custody/priority), 7-day TTL, ACK tombstones, SQLite persistence across restarts.
4. **Every claim has a test** — 59 relay/frames/harness pytest tests, 56 Laravel mesh PHPUnit tests, 5 Kotlin unit-test files, a 3-relay chaos harness in CI, live probes against real HTTP. What isn't proven (real radio) is labeled as such — see §21.
5. **Leave no phone behind** — $30 Android relays for everyone; iPhone captures and uploads; feature phones text `WASH DOU-BON-001 P`.

## 4. Transports

All transports carry the same bundle JSON. The Android app auto-selects `Nearby → BLE → QR` ([TransportSelector.kt](android/app/src/main/java/cm/wash/mesh/mesh/TransportSelector.kt)); a PWA or desktop user picks QR manually or uploads directly.

| Transport | Who | Payload | Measured capacity | Status |
|---|---|---|---|---|
| QR show/scan/photo | any phone + PWA + desktop | base64url of bundle JSON | ~0.5 KB text; ~700 chars unsigned, ~900 signed V2 (measured); safe cap 2000 bytes (`QR_MAX_BYTES`, margin under the ~2953 theoretical binary max) | ✅ proven in code |
| Nearby P2P_CLUSTER | Android relay APK | full bundles + media fragments | whole outbox, no bundle-size cap in code | 🟡 coded, radio untested |
| BLE GATT raw | degoogled Android (no Play Services) | bundles **without** media chunks, < 50 KB (`MAX_BUNDLE_BYTES`) | MTU-negotiated frames, ≤ 3 connections, 8 s/22 s duty cycle | 🟡 coded, radio untested |
| SMS `WASH <CODE> <TYPE>` | any 2G phone | 1 report/SMS, 1 segment ≤ 160 chars | grammar + synonyms, server-side dedup | ✅ live-tested path |
| USSD menus `*123#` | any 2G phone | guided report, ≤ 160 chars/screen | 6-step session, 10-min TTL | ✅ tested, no operator code yet |
| PWA `/m` | iPhone/Android/PC browser | create, carry (QR), upload | outbox in localStorage, installable | ✅ installable, offline |
| Desktop binary | Linux/Win/Mac PC | same as PWA (embedded `/m`) | Neutralino wrapper, offline bundle | ✅ CI artifact |
| Relay sync/fetch + WebSocket | any node with village WiFi | opportunistic outbox exchange | ≤ 100 bundles/store, limit ≤ 200/fetch | ✅ tested incl. chaos harness |

## 5. Bundle format (exhaustive)

The bundle is defined once in [`mesh-sdk.ts`](sdk/mesh-sdk.ts) (`MeshBundle`), mirrored by the relay's Pydantic model ([`main.py`](server/main.py) `Bundle`), the Laravel validator ([`WashMeshController.php`](../../backend/app/Http/Controllers/Api/WashMeshController.php) `rules()`) and the Kotlin protocol ([`MeshProtocol.kt`](android/app/src/main/java/cm/wash/mesh/MeshProtocol.kt)). Field names are identical on the wire except Laravel's upload mapping: `destination` → `destination_eid`, `report_to` → `report_to_eid`, `previous_node` → `previous_node_id` (the uplink and signature verifier translate back).

### 5.1 Core v1 fields

| Field | Type | Required | Constraint | Role |
|---|---|---|---|---|
| `v` | int | yes | `1` | format version |
| `bundle_id` | string | yes | UUIDv4 | global identity → dedup everywhere (relay, Laravel, outbox) |
| `origin_node_id` | string | yes | ≤ 64 chars | creator node; quota key; TOFU key |
| `school_id` | int | yes | must exist in `schools` (Laravel) | report target |
| `school_code` | string | no | ≤ 32 chars | human code (`DOU-BON-001`); USSD/SMS lookup key |
| `channel` | string | no | `text` (default) / `voice` / `photo` | triage channel |
| `message` | string | no | ≤ 5000 chars | report text; empty when `sealed` carries it |
| `created_at` | datetime | yes | ISO 8601 | creation instant; **verbatim on the wire** (see §6) |
| `expires_at` | datetime | yes | ISO 8601 | absolute TTL fallback (see `lifetime_seconds`) |
| `max_hops` | int | no | 1–20, default 10 | hop budget; `hop_count = len(hops) − 1` must stay ≤ it |
| `hops` | string[] | yes | ≤ 21 entries, each ≤ 64 chars | nodes that carried it (origin first); loop protection |
| `checksum` | string | no | ≤ 128 chars, SHA-256 hex (64) | integrity witness over immutable fields (see §6) |

### 5.2 v1.1 additive fields (BPv7 alignment, all optional)

| Field | Type | Constraint | BPv7 meaning |
|---|---|---|---|
| `destination` | string ≤ 128 | EID, default `dtn://wash-sentinel/ingest` | destination endpoint |
| `report_to` | string ≤ 128 | EID | status-report endpoint |
| `lifetime_seconds` | int 60–2592000 | default 604800 (7 days) | **preferred** over `expires_at`: village clocks are untrusted, the server derives expiry as `now + lifetime` |
| `previous_node` | string ≤ 64 | routing-prev | previous carrier (excluded from checksum/signature) |
| `copies_remaining` | int 1–64, default 8 | spray budget | remaining Spray-and-Wait copies (excluded from checksum/signature) |
| `fragment_offset` | int ≥ 0 (Laravel ≤ 199) | fragment index | media fragment position |
| `fragment_total` | int ≥ 1 (Laravel ≤ 200) | fragment count | media group size; presence marks a manifest |
| `custody_requested` | bool, default false | custody transfer ask | accepted but not acted on yet (stored, forwarded) |
| `priority` | `normal` / `high` / `alert` | class of service | anything else is **rejected** (not defaulted) |

### 5.3 Signatures (V2), E2E (V2), media (V2b)

| Field | Type | Constraint | Role |
|---|---|---|---|
| `signature` | string ≤ 128 | Ed25519 detached, base64 standard, **88 chars** | authenticity over canonical bytes (see §6) |
| `node_pubkey` | string ≤ 64 | Ed25519 pubkey, base64 standard, **44 chars** | self-announced origin key (TOFU, see §7); **included** in signed bytes |
| `sealed` | string ≤ 20000 | libsodium sealed box, base64 | E2E ciphertext of `message`; relays can't read it (see §8) |
| `sealed_alg` | string ≤ 32 | must be `nacl-sealed-box` when `sealed` is set | algorithm agility marker |
| `bundle_group` | string ≤ 64 | manifest's `bundle_id` | groups a manifest with its fragments |
| `chunk` | string ≤ 65536 | base64 slice (plaintext or sealed) | one fragment's payload |
| `media_mime` | string | enum: `image/jpeg`, `image/png`, `image/webp`, `audio/webm`, `audio/mp4`, `audio/ogg`, `audio/mpeg` | media type (manifest) |
| `media_size` | int 1–2097152 | bytes of decoded media | 2 MiB cap |
| `media_sha256` | string ≤ 128 | hex of the **plaintext** base64 | verified after seal-open (see §9) |
| `media_sealed_alg` | string ≤ 32 | e.g. `nacl-sealed-box` | set iff chunks are sealed |

### 5.4 Complete example (golden-vector bundle)

```json
{
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
  "node_pubkey": "hnd9uoXFRxizbRXJjUMzQZJ0V9AB/qqLNjhgc3sjMCk=",
  "signature": "f6DrYLlnkZbx4+YFRx8UKeXuql2DXjfrwkO/jPx7e8+fAUD6O3agxVljp5NTfB4ypbxSUycmh6t4V6X7sCB2BQ==",
  "checksum": "9f2c…"
}
```

## 6. Canonical form, checksum & signature

Three implementations must agree **byte-for-byte**: [`mesh-sdk.ts`](sdk/mesh-sdk.ts) (`canonicalString`/`canonicalBytes`/`checksumOf`), [`mesh_verify.py`](server/mesh_verify.py) and [`MeshSignature.php`](../../backend/app/Services/MeshSignature.php). The Kotlin side reuses the same contract.

**Canonical form.** Compact JSON: keys sorted (byte order — all keys are ASCII), separators `,`/`:` with no spaces, raw UTF-8 (`ensure_ascii=False`: accents and slashes NOT escaped, `dtn://…` stays as-is; only `"`, `\` and C0 controls escaped), `null` values **omitted** (TS never emits null, only absent keys). Encoded as UTF-8 with no BOM.

**Exclusion sets** (this is the subtle part — two different sets):

| Witness | Covers | Excludes | Rule |
|---|---|---|---|
| `checksum` (SHA-256 hex) | everything sent, **including** `signature`/`node_pubkey` | `checksum`, `hops`, `previous_node`, `copies_remaining` | always (re)compute **AFTER** `signBundle` |
| `signature` (Ed25519) | everything sent, **including** `node_pubkey` (binds content to the announced key) | `checksum`, `hops`, `previous_node`, `copies_remaining`, `signature` (a signature can't cover itself) | relays mutate routing fields without invalidating it |

**Checksum verification is encoding-tolerant, signature verification is verbatim.** Senders write the same instant as `…Z` or `…+00:00`; the relay tries 3 checksum candidates (raw + both rewrites) since the checksum detects corruption, not malice. Signatures are verified on the **received JSON strings, never re-serialized** (`…Z` ≠ `…+00:00`): the relay re-emits dates in canonical Z-millis form via `_wire_date`, and Python tolerates `datetime` objects by normalizing them to `…sssZ`.

**Algorithms.** SHA-256 hex for checksums (the TS SDK falls back to `fnv1a-…` only when WebCrypto is unavailable on non-secure `http:`); pure Ed25519 (RFC 8032, libsodium `crypto_sign_detached`, no pre-hash) with a 64-byte libsodium secret (`seed || pubkey`), standard base64 with padding. Order on the sender: set `node_pubkey` → drop old `signature` → sign → set `signature` → (re)compute `checksum`.

**Golden vector** (shared by `test_sig_verify.py`, `MeshSignatureTest.php` and the TS smoke test; keys generated by ext-sodium from seed `sha256('wash-sentinel-mesh-sig-golden-v1')`):

- public: `hnd9uoXFRxizbRXJjUMzQZJ0V9AB/qqLNjhgc3sjMCk=` (32 bytes, 44 chars)
- signature: `f6DrYLlnkZbx4+YFRx8UKeXuql2DXjfrwkO/jPx7e8+fAUD6O3agxVljp5NTfB4ypbxSUycmh6t4V6X7sCB2BQ==` (64 bytes, 88 chars)
- canonical: `{"bundle_id":"3fa85f64-…","channel":"text","created_at":"2026-01-15T10:00:00.000Z","destination":"dtn://wash-sentinel/ingest","expires_at":"2026-01-22T10:00:00.000Z","lifetime_seconds":604800,"max_hops":10,"message":"Pompe brisée, 400 élèves sans eau potable","node_pubkey":"hnd9…","origin_node_id":"node-A-yokadouma","priority":"high","school_code":"CM-EST-42","school_id":42,"v":1}` (single line, no spaces)

**Policy: unsigned accepted, invalid-signed rejected** — at relay ingress ([`main.py`](server/main.py) `store_one`) and on direct Laravel upload ([`WashMeshController.php`](../../backend/app/Http/Controllers/Api/WashMeshController.php)). Verifiers fail closed: any malformed input returns `false`, never throws. If no Ed25519 backend is installed on the relay (neither PyNaCl nor `cryptography`), signed bundles are **accepted with traceability** (`sig_bypassed_no_backend` counter + stderr log), never silently.

## 7. TOFU node keys

First `node_pubkey` seen per `origin_node_id` becomes the reference, stored in the `mesh_node_keys` table ([`MeshNodeKey.php`](../../backend/app/Models/MeshNodeKey.php): `origin_node_id`, `node_pubkey`, `first_seen_at`, `last_changed_at`). Rules:

- Memorized **only on a VERIFIED signature**, never on rejection.
- A changed key raises `mesh.node.key_changed` (log + `key_changed` summary counter) and **updates** the reference — accepted, never silently, never rejected: refusing would cut off a legitimate node that regenerated its key.
- Client-side, the PWA persists its Ed25519 secret in localStorage (`wash_mesh_node_sign_sk`), regenerating it if corrupt (new identity).

## 8. End-to-end encryption (sealed boxes)

Threat model: **curious relays**. Relays verify checksums and signatures but only ever see routing metadata; `sealed` payloads open exclusively on the server.

- Primitive: libsodium **sealed box** (anonymous — no node PKI), `sealed_alg: nacl-sealed-box`, in TS (`mesh-crypto.ts` → `crypto_box_seal`), PHP (`MeshSeal.php` → `sodium_crypto_box_seal_open`) and Kotlin.
- Server keypair derives from `MESH_SEAL_SECRET` (32 bytes, base64; generate with `php artisan mesh:key-generate`). `GET /api/v1/mesh/key` returns `{algorithm, public_key}`; **503 when unconfigured** → clients send cleartext **with a warning** (PWA seal toggle, `(chiffré)` vs plaintext labels).
- Encoding gotcha, handled: TS uses the explicit `ORIGINAL` base64 variant — libsodium's default URLSAFE-without-padding is incompatible with PHP's `base64_decode()`.
- `MeshSeal::open` is fail-closed: wrong alg, missing secret, bad base64 or forged box all return `null` → bundle rejected as `unseal_failed` (before signature-unrelated steps, after signature verification, since unsealing replaces `message`).

## 9. Fragmented media (photos & voice)

Encrypt-then-chunk ([`mesh-sdk.ts`](sdk/mesh-sdk.ts) `splitMedia`): seal the base64 first (if a key is available), then slice into ≤ 32768-char chunks (`MEDIA_CHUNK_SIZE`), 2 MiB max (`MEDIA_MAX_BYTES`). The **manifest** carries the text (triaged immediately) plus `media_mime`/`media_size`/`media_sha256`/`fragment_total`; each **fragment** carries `bundle_group` (= manifest id), `fragment_offset`, `fragment_total`, `chunk`.

- `media_sha256` covers the **plaintext** base64 and is verified **after** seal-open — same form as PHP `hash('sha256', $b64)`.
- Server reassembly ([`MeshMediaAssembler.php`](../../backend/app/Services/MeshMediaAssembler.php) `tryAssemble`): works out-of-order, even if the manifest arrives last; needs exact offsets `0..total-1` with `1 ≤ total ≤ 200`; idempotent (already-attached → no-op); stores to `reports/photos/mesh-{group}.{ext}` or `reports/audio/…` via the `public` disk and attaches `photo_path`/`audio_path` to the manifest's report. Failures (`unseal_failed`, `hash_mismatch`) keep fragments for retry.
- Laravel validation: mixing media keys without being a well-formed fragment or manifest → `malformed_fragment` rejection; a manifest without `message` → `manifest_without_message` rejection (nothing to triage).
- PWA capture: photos compressed to JPEG ≤ 1280 px q0.7 (~100–200 KB), voice via MediaRecorder (opus/webm/mp4 probes). Media never goes over QR (too big) or BLE (chunks excluded); full fragments travel over Nearby or relay sync.

## 10. Forwarding: spray-and-wait + TTL + hops + ACK

- **Binary Spray-and-Wait, L=8** (`forwardBundle` in TS, `forward` in `simulate_hops.py`, mirrored in Kotlin and in the multirelay harness): refuse if I'm already in `hops` (loop-free), if expired, if `len(hops) ≥ max_hops + 1`, or if `copies ≤ 1` (last copy = direct server upload only). Else give `floor(n/2)` to the contact, keep `ceil(n/2)` locally (`outbox.update(id, {copies_remaining: keepCopies})`), appending my node to `hops` and setting `previous_node`.
- **TTL**: 7 days default (`TTL_DAYS`, `lifetime_seconds: 604800`); Laravel prefers `lifetime_seconds` (server-derived `now + lifetime`) over `expires_at`; expired bundles are counted (`expired`), persisted with status `expired` on Laravel, and never served by the relay (purged on every read).
- **Hops**: `hop_count = len(hops) − 1`; enforced ≤ `max_hops` at relay ingress and Laravel ingest; re-storing a duplicate **enriches** known hops without duplicating the store.
- **ACK tombstones**: a connected node POSTs delivered ids to `/v1/ack`; tombstones live 7 days (`ACK_TTL_DAYS`), capped at 20000 (`ACK_MAX`, oldest evicted) and 5000 ids/record-call; `fetch`/`sync` advertise only ids the requester already holds (`known_ids` intersection — no leak to strangers); a successful relay uplink auto-records tombstones for confirmed bundles and purges them from the store.

## 11. BLE GATT frames (backup transport)

Reference: [`ble_frames.py`](demo/ble_frames.py), mirrored **exactly** by [`BleFrame.kt`](android/app/src/main/java/cm/wash/mesh/ble/BleFrame.kt) (tested in Python since no JDK/SDK is available in dev containers). Pure logic, no Android imports.

**Byte layout** (header = 11 bytes, all multi-byte ints big-endian):

| Offset | Size | Field | Value |
|---|---|---|---|
| 0–1 | 2 | magic | `WS` (`0x57 0x53`) |
| 2 | 1 | version | `1` |
| 3–6 | 4 | tag | `sha256(bundle_id)[:4]` — groups frames in flight |
| 7–8 | 2 | index | frame number, BE |
| 9–10 | 2 | total | frame count, BE, 1–65535 |
| 11+ | ≤ mtu−3−11 | payload | bundle JSON slice |

**UUIDs**: service `a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5`, TX char `…c4d6`, RX char `…c4d7`, CCCD standard `00002902-0000-1000-8000-00805f9b34fb`.

**MTU**: default 512 (payload 498/frame); minimum encodable 16; negotiated floor 23 (ATT overhead 3 → 9-byte payloads, proven by test). Bundles needing > 65535 frames are refused (`Bundle trop gros`).

**Reassembly** (`Reassembler.feed`): per-tag partials, out-of-order and interleaved tags OK; corrupt frames (short, bad magic/version, `index ≥ total`, `total == 0`) ignored; a tag reused with a different total is ignored; partials expire after **60 s** (`PARTIAL_TTL_S` / `PARTIAL_TTL_MS`). Identity and audit come from the JSON after reassembly (`bundle_id` + checksum), not from the tag.

**Duty cycle** ([`BleDutyCycle.kt`](android/app/src/main/java/cm/wash/mesh/ble/BleDutyCycle.kt)): 8 s active scan + 22 s idle = 30 s cycle (~27 %). Only scanning is cycled (advertise + GATT server stay continuous): scanning is the hungriest and AOSP-capped operation (5 scans/30 s), so the cycle divides backup-relay drain by ~4.

**Limits**: bundles < 50 KB only, media chunks excluded, ≤ 3 simultaneous connections — and real-radio range/throughput/battery are **unmeasured** (see §21).

## 12. Relay server (:8001)

FastAPI rendezvous ([`main.py`](server/main.py)): village nodes sync outboxes here over WiFi; the first connected one (or the relay itself) uplinks to Laravel. Hot in-memory cache (dedup, TTL purge, LRU eviction) + write-through SQLite — Laravel stays the source of truth, the relay is just an opportunistic backpack.

### 12.1 Endpoints (all of them)

Auth: `X-Mesh-Key` required **iff** `MESH_RELAY_API_KEY` is set; `/health` and `/metrics` stay open. WebSocket auth via `?key=`.

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| GET | `/health` | open | — | `{status, service, stored, peers_live}` |
| GET | `/metrics` | open | — | telemetry: `uptime_seconds`, `stored`, `uplink_queue` (= stored after purge), `acked`, `peers_live`, `counters`, `uplink{…}`, `sqlite{path, bytes}` |
| POST | `/v1/store` | key | `{node_id, bundles[≤100]}` | `{message, stored, duplicates, expired, rejected, stored_total}` — **always HTTP 200**, even when rejecting everything (check `rejected`, see `store_response_ok`) |
| POST | `/v1/fetch` | key | `{node_id, known_ids[≤5000], limit 1–200 default 50}` | `{bundles, count, stored_total, acked_ids}` (missing-only + tombstones you hold) |
| POST | `/v1/sync` | key | store + fetch combined | store counts + `{bundles, count, acked_ids}`; never returns what you just gave |
| POST | `/v1/ack` | key | `{node_id, ids[≤1000]}` | `{message, new, acked_total}` |
| GET | `/v1/stats` | key | — | `{stored, origins, avg_hops, peers_live, counters}` |
| POST | `/v1/uplink?dry_run=` | key | — | pushes the whole store to Laravel (see 12.3); `dry_run` reports `pending` without flushing |
| WS | `/v1/ws/{node_id}` | `?key=` | `hello` → `{type:offer,bundles[≤100]}` / `{type:fetch,known_ids,limit}` | live fan-out `{type:bundles,from,…}` to other peers + `{type:ack,stored}` |

Ingress policy (`store_one` → `stored | duplicate | expired | rejected`, each incrementing `COUNTERS`): duplicates enrich hops; checksum verified on exactly the sent fields (`exclude_unset`, 3 date-spelling candidates); signed-invalid rejected; expired counted; `hop_count > max_hops` rejected; `priority` outside the enum rejected; never a capacity rejection — over `MAX_STORE`, purge-then-evict-LRU (oldest `stored_at` first, `evicted_lru` counted).

### 12.2 Environment (all of it)

| Variable | Default | Effect |
|---|---|---|
| `MESH_DB_PATH` | `./relay.db` | SQLite path (WAL); `:memory:` = no persistence (tests); `/data/relay.db` on a named volume in compose |
| `MESH_MAX_STORE` | `5000` | bundle ceiling (LRU eviction beyond) |
| `MESH_RELAY_API_KEY` | empty (public) | if set, `X-Mesh-Key` required on `/v1/*` (`?key=` on WS) |
| `LARAVEL_URL` | `http://laravel:8080` | uplink target (`POST /api/v1/mesh/bundles`) |
| `MESH_INGEST_KEY` | empty | key sent to Laravel as `X-Mesh-Key` |
| `MESH_UPLINK_RETRIES` | `3` | retries per uplink (network errors, 429, 5xx; other 4xx are final, not retried) |
| `MESH_UPLINK_BACKOFF` | `0.5` | backoff base: `0.5 × 2^attempt + jitter(0–0.5 s)` |
| `MESH_UPLINK_BREAKER_THRESHOLD` | `5` | consecutive failures before the breaker opens |
| `MESH_UPLINK_BREAKER_COOLDOWN` | `60` | seconds open (`breaker_open` + `retry_after`, stock kept) |
| `FORWARD_MESH_PORT` | `8001` | compose host port only — **not** read by the relay itself |

### 12.3 Uplink, retry, breaker, persistence

- **Uplink** POSTs `{bundles:[…]}` with `Accept: application/json` (+ `X-Mesh-Key` if set), 30 s timeout/attempt. **Signature fidelity**: dates already in Z-millis, `v` included, `custody_requested` omitted unless explicitly true — a missing signed field or an added `false` would read as `bad_signature` server-side (proven by `test_uplink_payload_preserves_signature`).
- **Retry**: network exceptions, 429 and 5xx retried with exponential backoff + jitter; definitive 4xx returned as-is. Telemetry: `attempts`, `retries`, `failures`, `breaker_opens`, `last_error`, `breaker_open_until`.
- **Breaker**: after `BREAKER_THRESHOLD` consecutive failures, short-circuits uplinks for `BREAKER_COOLDOWN` seconds; one success closes it and resets `failures` to 0.
- **Persistence** ([`storage.py`](server/storage.py)): SQLite WAL, `bundles(bundle_id, data, expires_at, stored_at, received_via)` + `acked(bundle_id, acked_at)` with expiry indexes; write-through that **never breaks the flow** on disk error (stderr log); `RLock`-guarded; `load_all` skips corrupt rows; restart drops expired, keeps the newest `MAX_STORE` (LRU), drops stale ACKs; `/metrics → sqlite.bytes` sums base + WAL + SHM. Ops detail: [relay runbook](../docs/MESH_RUNBOOK.md).

## 13. Laravel ingest (:80)

First connected node uploads here; SMS/USSD gateways too. Mesh never bypasses the pipeline: every bundle becomes a `MeshBundle` row, then standard AI triage with `source = mesh|sms|ussd`.

### 13.1 Endpoints (all of them)

Prefix `/api/v1/mesh` ([`api.php`](../../backend/routes/api.php)). Writes throttled **60/min**.

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| POST | `/bundles` | `X-Mesh-Key` iff `MESH_INGEST_KEY` set (401 otherwise) | single bundle or `{bundles[≤100]}` | **201** `{message, summary{accepted, duplicates, expired, rejected, quota_exceeded, fragments, key_changed}, incidents[{bundle_id, incident_id, reference_code, hop_count}]}` |
| POST | `/sms` | shared `secret` (fail-closed 403) + optional allowlist | `{secret, from ≤32, message ≤1600, sent_at?}` | **201** `{ticket, incident_id, reply}`; 403 bad secret / not allowlisted; 429 quota; 422 invalid format (`{error, reply}`) |
| POST | `/ussd` | gateway/operator (no shared secret) | Africa's-Talking style `{sessionId, serviceCode?, phoneNumber, text?}` | **200 text/plain** `CON …` / `END …` |
| GET | `/ussd` | same | same as query string (manual probe) | same |
| GET | `/key` | open | — | `{algorithm: nacl-sealed-box, public_key}` or **503** when unconfigured |
| GET | `/bundles/pending` | open | `?per_page=` (≤ 100, default 20) | paginated pending bundles with school |
| GET | `/bundles/{bundleId}` | open | — | bundle with school + report (404 if unknown) |
| GET | `/stats` | open | — | `{total, by_status, avg_hops, relayed_share, origins, sealed_share}` |

### 13.2 Validation rules (`rules()`)

`bundle_id` required UUID · `origin_node_id` required ≤ 64 · `school_id` required, must exist · `school_code` ≤ 32 · `message` ≤ 5000 · `channel ∈ text,voice,photo` · `hops` ≤ 21 (each ≤ 64) · `max_hops` 1–20 · `created_at`/`expires_at` dates · `received_via_node_id` ≤ 64 · `checksum` ≤ 128 · `destination_eid`/`report_to_eid` ≤ 128 · `lifetime_seconds` 60–2592000 · `previous_node_id` ≤ 64 · `copies_remaining` 1–64 · `fragment_offset` 0–199 · `fragment_total` 1–200 · `custody_requested` boolean · `priority ∈ normal,high,alert` · `signature` ≤ 128 · `node_pubkey` ≤ 64 · `v` int · `sealed` ≤ 20000 · `sealed_alg` ≤ 32 · `bundle_group` ≤ 64 · `chunk` ≤ 65536 · `media_mime` ∈ 8-type enum · `media_size` 1–2097152 · `media_sha256`/`media_sealed_alg` ≤ 128/32.

### 13.3 Ingest pipeline order (per bundle)

dedup by `bundle_id` (incl. race-safe unique-violation catch) → daily quota per origin (**500**, `quota_exceeded`) → `max_hops` → signature (invalid-signed rejected, before unseal) → seal-open (`unseal_failed`) → expiry (`lifetime` preferred; expired rows persisted as `expired`) → fragment/manifest classification → school lookup → fragment store + `tryAssemble`, or transaction: bundle row + AI triage + `report_id`/`delivered_at` → TOFU update (verified signatures only) → summary + incidents.

### 13.4 Config & quotas

`MESH_INGEST_KEY` (empty = public ingest + throttle + quotas) · `MESH_SMS_SECRET` (fail-closed) · `MESH_SMS_ALLOWLIST` (CSV, empty = everyone) · `MESH_DAILY_CAP_PER_ORIGIN` = 500 · `MESH_SMS_QUOTA_PER_SENDER` = 10 (shared SMS/USSD) · `MESH_SEAL_SECRET` (empty = E2E off, 503 on `/key`). See [`services.php`](../../backend/config/services.php).

## 14. TypeScript SDK (zero dependency)

Source of truth [`mesh-sdk.ts`](sdk/mesh-sdk.ts), vendored into `frontend/src/lib/mesh-sdk.ts` (CI-guarded identical apart from the header). Every export:

| Export | Signature | Role |
|---|---|---|
| `MeshBundle` | interface (§5) | the bundle type |
| `DEFAULT_DESTINATION` | `const = 'dtn://wash-sentinel/ingest'` | default EID |
| `nodeId()` | `() → string` | stable node id in localStorage (`wash_mesh_node_id`), `node-` + random on first run |
| `canonicalString()` | `(bundle) → string` | signed canonical form: sorted keys, compact, UTF-8; drops `checksum/hops/previous_node/copies_remaining/signature` |
| `canonicalBytes()` | `(bundle) → Uint8Array` | UTF-8 bytes of the above — the exact Ed25519 input |
| `checksumOf()` | `async (bundle) → hex` | SHA-256 via WebCrypto; `fnv1a-…` fallback when unavailable (non-secure http) |
| `createBundle()` | `async ({schoolId, schoolCode?, message?, sealed?, sealedAlg?, channel?, ttlDays=7, maxHops=10, copies=8, priority?}) → MeshBundle` | builds + checksums a fresh bundle (origin = me, `hops: [me]`) |
| `ForwardResult` | `{give: MeshBundle, keepCopies: number}` | spray split shape |
| `forwardBundle()` | `(bundle, myNodeId?) → ForwardResult \| null` | binary spray (§10); `null` = loop/TTL/hops/last-copy refuse |
| `serializeForQR()` | `(bundle) → base64url` | compact QR payload (no padding) |
| `parseFromQR()` | `(payload) → MeshBundle` | decodes + validates required fields, throws otherwise |
| `MEDIA_CHUNK_SIZE` / `MEDIA_MAX_BYTES` | `32768` / `2097152` | chunk chars / 2 MiB cap |
| `chunkBytes()` / `assembleBytes()` | `(b64, size?) → string[]` / `(chunks) → string` | slice / join |
| `sha256Text()` | `async (text) → hex` | SHA-256 of a base64 string (same form as PHP) |
| `MediaSplit` | `{manifest, fragments}` | split shape |
| `splitMedia()` | `async ({schoolId, …, channel: photo\|voice, mime, dataB64, seal?, chunkSize?, …}) → MediaSplit` | encrypt-then-chunk (§9); manifest keeps the text |
| `MeshOutbox` | class (`wash_mesh_outbox`) | persistent localStorage queue: `add` (dedup), `update` (partial patch), `has`, `all`, `ids`, `remove`, `size`, `gc` (drops expired, returns count); corrupt store → clean restart |
| `syncWithRelay()` | `async (outbox, relayUrl) → {sent, received, acked}` | opportunistic exchange: POSTs outbox, `forwardBundle`-filters newcomers, purges acked ids |
| `ackDelivered()` | `async (ids, relayUrl) → newCount` | tells the relay what's on the server (0 on relay error — best effort) |
| `uploadToLaravel()` | `async (outbox, apiUrl) → {accepted, duplicates}` | final upload with Laravel field mapping (§5); accepted/duplicates leave the outbox |

Companions in `frontend/src/lib/`: **`mesh-crypto.ts`** — `fetchSealKey` (`/key`, null on 503), `sealMessage` (ORIGINAL base64), `generateNodeKeypair`, `getOrCreateNodeSigningKey` (persisted, regen on corruption), `signBundle` (sets pubkey → signs → re-checksums, in place), `verifyBundle` (fail-closed); **`mesh.ts`** — re-exports + `apiBase`/`smsGateway` env helpers, `isIOS`, `smsHref` (`?body=` Android vs `&body=` iOS), `smsText` (1-segment builder ≤ 160), school cache (300 max, `wash_mesh_schools`), `outboxAdd` (+ best-effort Background Sync); **`mesh-sync.ts`** — `registerMeshSync` (`wash-mesh-upload` tag, never throws: `registered|unsupported|failed`), `shouldFlushOutbox` (pure: online && pending && !inflight); **`mesh-outbox-status.ts`** — view derivation over outbox + local meta (pending/sending/failed + 20 recent sent, fragments hidden from the list).

## 15. PWA, desktop & APK

- **PWA `/m`** ([`MeshFieldPage.tsx`](../../frontend/src/pages/MeshFieldPage.tsx), 785 lines): public, installable, offline-first. Create (text + photo + voice + E2E toggle default-on) → local outbox → QR show/scan/photo-import → upload with retry (Background Sync on Chromium; `online`/`visibilitychange`/timer + SW-message fallbacks for iOS/Safari). School picker works offline from the 2nd visit (cached list); manual id/code fallback; SMS fallback link when `VITE_SMS_GATEWAY_NUMBER` is set; outbox states (pending/sending/failed + recent sent + first-error hint); iOS install-help card (dismiss persisted) and in-app install prompt on Chromium. A sibling [`MeshPage.tsx`](../../frontend/src/pages/MeshPage.tsx) is the authenticated console demo (create → hop-simulate → upload → mesh stats).
- **Desktop** (`desktop/`, Neutralino `wash-relai` v0.1.0, app id `cm.washsentinel.relai`): boots straight on `/index.html#/m` in a 480×860 window; `build.sh` = frontend build → copy to `resources/` → `neu update` (network) → `neu build --release` → per-OS binaries + `wash-relai-release.zip`. CI artifact `wash-relai-desktop`. Offline included (service worker + local files); transfers via on-screen QR or QR-photo import. See [install guide](../docs/INSTALL.md) §2.
- **APK** (`mesh/android/`, 21 sources + 5 unit-test files): background relay — Nearby Connections primary, raw BLE GATT fallback (degoogled phones), SMS gateway (same grammar/allowlist/quota as the backend, early-filtered), QR (ZXing encode, Play-Services scanner decode), Room persistence, boot-resilient (`BootReceiver` + restart worker), field settings UI. Build/test: `gradlew :app:assembleDebug` + `testDebugUnitTest` in CI. Details: [Android README](android/README.md).

## 16. SMS channel (any 2G phone)

Grammar ([`MeshSmsParser.php`](../../backend/app/Services/MeshSmsParser.php), mirrored by Kotlin `SmsPolicy`): `WASH <SCHOOL_CODE> <TYPE> [DETAIL…]`, one segment ≤ 160 chars. Keywords `WASH`/`EAU` (case- and accent-insensitive, normalized via `Str::ascii` + uppercase); detail truncated to 100 chars.

| Type | Letter | Synonyms |
|---|---|---|
| panne pompe/forage | `P` | P, PANNE, POMPE, FORAGE |
| latrine | `L` | L, LATRINE(S), WC, TOILETTE(S) |
| eau/qualité | `E` | E, EAU, QUALITE, TROUBLE, SALE |
| hygiène | `H` | H, HYGIENE, SAVON, LAVAGE |

School lookup is case- and dash-insensitive. Normalized text: `[SMS] {school name} : {label}[ — {DETAIL}]`. Help string on any error: `Envoyez: WASH CODE TYPE. Ex: WASH DOU-BON-001 P (P=panne, L=latrine, E=eau, H=hygiene).` Acknowledgement (≤ 160): `WASH OK {code} {type} {ticket} Merci!`.

Server rules ([`WashSmsController.php`](../../backend/app/Http/Controllers/Api/WashSmsController.php)): shared `secret` (fail-closed 403), optional exact allowlist (403), quota **10/day/sender** (429, `sms:<sender>` origin), 24 h dedup (same sender + normalized text → `{duplicate: true, ticket}`), then `MeshBundle` (`copies_remaining: 1`, 7-day expiry) + standard triage (`source: sms`). Compatible with SMSSync-style gateways: a village Android POSTs each received SMS when intermittent data allows.

## 17. USSD channel (guided menus)

Africa's-Talking-style gateway ([`WashUssdController.php`](../../backend/app/Http/Controllers/Api/WashUssdController.php), full doc: [USSD guide](../docs/USSD.md)): the gateway POSTs `{sessionId, serviceCode?, phoneNumber, text}` (form-encoded or JSON, 60/min throttle) and expects raw `text/plain` starting with `CON` (continue) or `END` (hang up). `text` accumulates inputs separated by `*`; only the **last** segment is interpreted, state lives in Laravel cache (10-min TTL). `GET /ussd` mirrors it for manual probing.

```
HOME ("Bienvenue… 1. Signaler 0. Quitter")
 └─ 1 → SCHOOL (free code, validated; 3 attempts max, then END)
      └─ OK → TYPE (1 Pompe/forage · 2 Latrine · 3 Eau/qualite · 4 Hygiene; also accepts P/L/E/H + SMS keywords)
           └─ 1-4 → URGENCY (1 Normale · 2 Urgente)
                └─ 1-2 → DESC (≤ 100 chars, tags stripped; 9 skip)
                     └─ text|9 → CONFIRM (school/type/urgency/desc; 1 confirm → END "Merci! Ticket: <ref>")
```

`0` cancels at every step (nothing created, session forgotten); invalid choices re-show the menu (`CON`, session kept). Normalized text: `[USSD] {name} : {label}[ (URGENT)][ — {detail}]`. Quota/dedup share the SMS setting (10/day/caller) keyed by origin `ussd:sha256(phone)[:16]`. Idempotence: gateway replays of a confirmed `sessionId` return the same ticket (24 h `ussd:done:` marker), one incident only. **Privacy**: the caller number is persisted nowhere — not in `mesh_bundles`, `reports`/`incidents`, cache or logs. All screens are accent-free GSM 7-bit, ≤ 160 chars when school/desc allow. Limits: `*123#` fictional (no operator code); `*` forbidden in descriptions (it's the separator); no back-navigation; no shared secret — auth rests on the gateway/operator (restrict by IP at the reverse proxy if needed).

## 18. Threat model

Adversary: **curious relays + active network meddlers**; relays are untrusted for confidentiality but relied on for transport.

| Threat | Mitigation | Residual risk (honest) |
|---|---|---|
| Relay reads reports | sealed boxes: only routing metadata visible; server-only open | metadata (school, hops, timing) still visible; unsealed bundles fully readable |
| Relay forges/alters bundles | Ed25519 over immutable fields; checksum detects corruption | **unsigned bundles accepted** (adoption > strictness) — verify `signature` presence where it matters |
| Key substitution (new node key) | TOFU: first verified key memorized, change alerted (`key_changed`) | first contact is trust-on-first-use; no out-of-band key distribution |
| Replay / duplicates | UUID dedup at relay + Laravel + outbox; SMS/USSD 24 h dedup; ACK tombstones | none known within TTL |
| Loops / storms | `hops` loop check, `max_hops`, spray budget L=8, LRU cap 5k, quotas | fixed spray, no congestion control (§21) |
| SMS spoofing / spam | shared secret (fail-closed), exact allowlist, 10/day/sender, throttle 60/min | SMS is **always cleartext** (feature phones); sender id forgeable upstream |
| USSD abuse | operator gateway trust, throttle 60/min, quota, no PII stored | **no shared secret** on USSD; restrict by IP at the proxy |
| Relay API abuse | optional `X-Mesh-Key`, Pydantic bounds (sizes, enums, UUID), 422 on malformed | keyless relays are public by design (rural anonymity) |
| Missing crypto backend | `sig_bypassed_no_backend` counter + stderr log, never silent | signed-invalid accepted while blind — monitor the counter |
| PII leakage | no names/phone numbers in bundles; USSD number hashed-then-dropped | SMS `from` lives in `payload.sms_from` (gateway requirement) |
| Clock attacks | `lifetime_seconds` preferred over absolute dates; server derives expiry | non-Z-millisecond emitters lose signatures in transit (re-serialization gap) |

## 19. Tests (every file)

**59 pytest** — relay, ops, signatures, BLE, demo, chaos harness:

| File | Tests | Covers |
|---|---|---|
| `server/test_relay.py` | 18 | store→fetch, dup enriches hops, TTL, max_hops, bidirectional sync, uplink dry-run, LRU eviction, API-key gate, stats counters, v1.1 passthrough, bad priority, 4 checksum cases (accents, Zulu, forward-mutations, tampered), ACK scoping, media passthrough, uplink tombstones |
| `server/test_ops.py` | 12 | bundles/ACKs survive restart, expired dropped on restore, LRU↔DB alignment, persisted hop-enrichment, `/metrics` shape, metrics-open-without-key, retry-then-success, 503-then-OK, 4xx-not-retried, breaker open/short-circuit, breaker cooldown recovery |
| `server/test_sig_verify.py` | 15 | golden canonical (byte-exact vs PHP), key/sig layout, golden verifies, deterministic re-sign, roundtrip, 4 tamper cases + cut-paste, forward-mutations preserve, wrong-key fails, malformed fail-closed, None≡absent, datetime tolerance, store-accepts-signed, store-rejects-tampered, no-backend bypass counter, uplink preserves signature |
| `demo/test_ble_frames.py` | 7 | tag determinism, default-MTU roundtrip, MTU-23 roundtrip (≤ 20-byte frames), out-of-order + interleaved tags, corrupt frames ignored, partial-then-complete, 60 s partial expiry |
| `demo/test_simulate_hops.py` | 3 | demo checksum ≡ relay canonical with accents, accented bundle accepted by `/v1/store`, `store_response_ok` truth table (200+rejected = failure) |
| `demo/test_multirelay.py` | 4 | A→B→C chain over 3 real uvicorn relays (hops enriched), median `kill -9` + restart keeps SQLite store, expired never propagates, duplicate enriches without downstream copy |

**56 PHPUnit** — `WashMeshTest` (14: batches, dedup, quotas, hops, sig policy, seal, lifetime, errors) · `WashMeshMediaTest` (6: manifest/fragment, out-of-order, sealed media, hash mismatch) · `WashSmsTest` (5: grammar, secret, allowlist, quota, dedup) · `WashUssdTest` (12: full menu walk, attempts, cancel, quota, dedup, idempotence, privacy) · `MeshSignatureTest` (10: golden vector, canonical, roundtrip, tamper, fail-closed) · `MeshNodeKeyTest` (4: TOFU memorize/change/verified-only) · `MeshSmsParserTest` (5: grammar, synonyms, USSD choices).

**Kotlin** — 5 unit-test files (`BleFrameTest`, `BleDutyCycleTest`, `SmsPolicyTest`, `RestartPolicyTest`, `TransportSelectorTest`) via `testDebugUnitTest`; **frontend** — `tsc` + PWA build (service worker precaches shell + `/m`) + lint 0 errors.

```bash
# Relay + demo (59 pytest; server tests use per-test tmp SQLite)
/tmp/venv-ops/bin/pytest mesh/server mesh/demo -q   # local venv
python -m pytest mesh/server mesh/demo -q            # CI (relay job)

# Laravel mesh (56 tests)
php artisan test --filter 'WashMeshTest|WashMeshMediaTest|WashSmsTest|MeshSmsParserTest|WashUssdTest|MeshSignatureTest|MeshNodeKeyTest'

# Android unit tests (CI has the JDK/SDK)
cd mesh/android && ./gradlew :app:testDebugUnitTest
```

Interop, not just unit tests: TS, Python and PHP reproduce the golden vector byte-for-byte (real libsodium, PyNaCl, ext-sodium), and the relay uplink preserves verifiable signatures end-to-end (TestClient + `php -r` proven).

## 20. Quickstart

```bash
python3 mesh/demo/simulate_hops.py            # A→B→C locally, loop + spray demo (no server)
python3 mesh/demo/simulate_hops.py --live     # POSTs to relay :8001 + Laravel :80 (store→upload→dedup→incident→stats)
python3 mesh/demo/simulate_hops.py --burst 50 # 50 fresh + 5 dups + 1 invalid-priority + 1 expired, with report

/tmp/venv-ops/bin/pytest mesh/demo/test_multirelay.py -q  # 3-relay chaos harness (local)
/tmp/venv-ops/bin/pytest mesh/server mesh/demo -q         # full 59 pytest

./start.sh                                   # 7 services incl. mesh-relay, then open http://localhost:5173/m
```

Field flow: install `/m` once online (Safari → Add to Home Screen) → airplane mode → create → QR to the next carrier → whoever gets signal uploads. Probes and relay ops: [runbook](../docs/MESH_RUNBOOK.md) §5.

## 21. Honest limits (what is NOT proven)

- **Real radio**: Nearby and BLE GATT never ran on physical phones — range, throughput, battery and the 8 s/22 s duty cycle are unmeasured. Two cheap Androids side by side remain the incompressible validation (no cloud emulator does proximity radio: Appetize none, Genymotion beacons only, Test Lab isolated devices).
- **No operator USSD code** provisioned (`*123#` is fictional); SMS costs + cleartext accepted.
- **iOS can't relay** (Apple background limits) — capture + QR + upload only.
- **Central server**: offline covers collection; consolidation still needs Laravel reachable.
- **Capacities**: relay SQLite is single-file (5k LRU), spray L=8 fixed, no congestion control, village clocks untrusted (lifetime preferred; non-Z-millisecond emitters lose signatures in transit).

## 22. Roadmap

- [x] v1: multi-hop text + QR + relay + Laravel ingest
- [x] v1.1: BPv7 alignment, binary spray, quotas, ACK, SMS channel
- [x] v2a: E2E sealed boxes (libsodium, zero home-made crypto)
- [x] v2b: photos + short voice (deferred fragments, E2E preserved)
- [x] v3: Android Nearby app, SMS gateway, raw BLE GATT fallback (+ auto-select)
- [x] app v1: installable offline PWA `/m` (iPhone), desktop binary, APK via CI
- [x] app v2: Ed25519 signatures + TOFU, USSD channel, SQLite/metrics/retry relay, PWA (Background Sync, install prompt, outbox states), hardened APK (boot, duty-cycle, SMS policy, unit tests)
- [x] P0: relay persistence volume, multi-relay chaos harness, jury docs aligned
- [ ] Two-phone field validation (Nearby + BLE range/battery/duty-cycle)
- [ ] LoRa feasibility + ART regulatory check
- [ ] Real operator USSD code + SMS gateway contract
- [ ] iOS native spike (Mac + Xcode required)
- [ ] Congestion control / adaptive spray (research)

## 23. Glossary

- **bundle** — one signed, checksummed report unit (§5); travels whole over every transport.
- **EID** — endpoint identifier (`dtn://wash-sentinel/ingest`); BPv7-style destination naming.
- **custody** — DTN concept: a carrier takes responsibility for delivery. `custody_requested` is stored and forwarded but not acted on yet.
- **spray-and-wait** — DTN routing: spray L copies (binary split here), then wait for direct delivery. Last copy = upload-only.
- **tombstone / ACK** — delivery record: "bundle X reached the server, purge your copy". 7-day TTL, capped.
- **TOFU** — trust on first use: the first verified key per origin becomes the reference; changes alert, never reject.
- **sealed box** — libsodium anonymous public-key encryption: anyone can seal to the server key, only the server opens.
- **manifest / fragment** — media split: the manifest triages immediately, fragments complete the attachment later.
- **duty cycle** — BLE scan schedule (8 s on / 22 s off) saving battery on the backup radio.
- **LRU** — least-recently-used eviction: a full relay drops the oldest-stored bundle, never rejects for capacity.
- **outbox** — a node's persistent local queue (localStorage on PWA, SQLite/Room on relay/APK).
- **uplink** — relay→Laravel push (retry + breaker); distinct from a node's direct upload.
- **breaker** — circuit breaker: after N failed uplinks, stop calling Laravel for a cooldown instead of hammering it.
- **harness** — the 3-real-relay pytest chaos fixture (spawn, `kill -9`, TTL, duplicates).

## 24. Repo map

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

---

*WASH Mesh — leave no school behind, even without signal.* 💧🇨🇲
