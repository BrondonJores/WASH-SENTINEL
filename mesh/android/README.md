# 📱 WASH Relai — village Android node (Phase 1 + 2, hardened V2 relay)

One APK = **mesh node** (Nearby P2P_CLUSTER + BLE GATT fallback, store-and-forward) +
**SMS gateway** (SMSSync pattern) + **QR** (show/scan) + **field settings** + **visible outbox**.
Kotlin, minSdk 26. 28 sources (23 main + 5 unit tests).

## Build

Prerequisites: JDK 17 + Android SDK (platform 34, build-tools) + a system Gradle or Android Studio.

```bash
cd mesh/android
gradle wrapper            # once, generates gradlew (jar not versioned)
./gradlew :app:assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk → sideload onto phones
./gradlew :app:testDebugUnitTest   # pure-Kotlin unit tests (JUnit 4)
```

Field distribution: see [docs/INSTALL.md §3 "Android — native APK"](../../docs/INSTALL.md)
(install, offline formats, honest limits).

Set `gradle.properties` first: `LARAVEL_API_URL` and `RELAY_URL` (village LAN IPs of the
server/relay, not localhost), `MESH_SMS_SECRET` (same as `MESH_SMS_SECRET` in `backend/.env`),
`MESH_RELAY_KEY` if `MESH_INGEST_KEY` / `MESH_RELAY_API_KEY` are set server-side,
`MESH_SMS_ALLOWLIST` (CSV, empty = open) and `MESH_SMS_QUOTA_PER_SENDER` (default 10, like the backend).
These are compiled-in **defaults** — the in-app Settings screen (`FieldSettings`) can override all
six at runtime without rebuilding (empty field = compiled value).

> Not compiled in dev containers (no JDK/SDK): build via Android Studio or CI before distribution.
> Protocol logic (`MeshProtocol`) mirrors the verified TS SDK (`mesh/sdk/mesh-sdk.ts`) exactly,
> and the relay accepts its checksums (`test_checksum_*`).

## Architecture

```text
app/src/main/java/cm/wash/mesh/
├── MeshProtocol.kt     # v1.1 bundles, canonical JSON, sha256, binary spray, base64url QR
├── data/               # Room: BundleEntity + MeshDao + MeshDatabase (persistent outbox)
├── net/Api.kt          # minimal HTTP: relaySync, laravelUpload, smsPost (+ X-Mesh-Key)
├── mesh/
│   ├── MeshRelayService.kt  # foreground service: Nearby advertise+discover, gossip spray
│   ├── TransportSelector.kt # pure Nearby → BLE → QR selector (+ logged reason)
│   └── UploadWorker.kt      # WorkManager on CONNECTED: push outbox to Laravel, purge
├── ble/
│   ├── BleFrame.kt          # pure BLE frames (tested mirror of mesh/demo/ble_frames.py)
│   ├── BleDutyCycle.kt      # pure scan cycling: 8 s ON / 22 s OFF (30 s period)
│   └── BleMeshService.kt    # no-Play-Services fallback: GATT server+client, duty-cycled
├── relay/
│   ├── RelayPrefs.kt        # persistent node_id + relay switch
│   ├── FieldSettings.kt     # runtime URLs/secrets/quota (compiled defaults)
│   ├── RestartPolicy.kt     # pure backoff 5 s → 5 min for restarts
│   ├── BootReceiver.kt      # BOOT_COMPLETED / update: restart relay if enabled
│   └── RelayRestartWorker.kt# WorkManager safety net when direct restart is denied
├── sms/
│   ├── SmsPolicy.kt         # WASH/EAU grammar + allowlist + quota (backend mirror, pure)
│   ├── SmsQuotaStore.kt     # per-sender daily counter
│   ├── SmsReceiver.kt       # SMS_RECEIVED: reassemble, filter, enqueue WorkManager
│   └── SmsGatewayWorker.kt  # POST /api/v1/mesh/sms (shared secret, differentiated retry)
├── qr/Qr.kt            # QR encoding (ZXing; decoding via Play Services Code Scanner)
└── ui/
    ├── MainActivity.kt     # capture offline, visible outbox, QR, sync, upload, relay switch
    └── SettingsActivity.kt # field settings form (URLs, keys, quota) + reset to compiled
```

Unit tests (`app/src/test`): `TransportSelector`, `BleFrame`, `BleDutyCycle`, `SmsPolicy`,
`RestartPolicy`.

## Fallback BLE (V3)

Without Play Services (Huawei, degoogled…), the app switches to `BleMeshService`
(auto-selected by the relay button): GATT server (advertise + notify) and client
(filtered scan + write) running together, negotiated MTU up to 512, ≤3 connections,
scan duty-cycle 8 s / 22 s idle (AOSP 5-scans/30 s quota respected), small bundles
<50 KB (media fragments excluded — Nearby/WiFi only).

Frames (`BleFrame`, mirror of `mesh/demo/ble_frames.py`, 7 Python tests):
`WS` + ver + tag(4) + index/total (2+2 BE) + payload. Service UUID:
`a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5` (TX `…d6`, RX `…d7`).

## Field notes

- Nearby needs Bluetooth + WiFi + **location ON** (system) and runtime permissions asked at launch;
  without the foreground service, Android kills the relay within minutes (persistent notification is normal).
- Two modes: "voluntary sync" (button, frugal) and "ambient relay" (permanent service, opt-in — costs battery).
- The SMS gateway runs even without data: SMS queue up and leave once a connection returns.
  Plan 2 relay phones per zone (MTN + Orange) + solar charging.
- Hardened relay: persistent switch, boot restart (`BootReceiver`, `RECEIVE_BOOT_COMPLETED`),
  `START_STICKY` + relaunch on recents-swipe + WorkManager net. On API 31+, a foreground start
  from the background may be denied by the system: the Worker retries.
- BLE fallback: scan radio active 8 s / 30 s only (`BleDutyCycle`); notify GATT server +
  opportunistic client (MTU 512 requested). Frame: 11-byte header `WS` + ver + tag(4) + index/total,
  tag-based reassembly (`BleFrame`, tested Python mirror).
- SMS gateway: backend-aligned local filtering (`WASH <CODE> <TYPE> [detail]` grammar,
  P/L/E/H types + synonyms, exact allowlist, 10/day/sender quota), multi-segment reassembly,
  no retry on 403/422. Demo seed codes for SMS tests: `DOU-BON-001`, `DOU-LIB-002`,
  `DOU-BAL-003` (`backend/database/seeders/WashDemoSeeder.php`).
- Visible outbox: pending/sent counters, per-item remove, auto-refresh (Room on IO thread).
- Field settings: all 6 server values editable in-app; empty = compiled default; urgent secret
  rotation goes through the screen, then a rebuild to freeze the new values.
- iOS: excluded from relaying (Apple restrictions), capture + QR + direct upload only.
