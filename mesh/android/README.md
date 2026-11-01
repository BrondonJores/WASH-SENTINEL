# 📱 WASH Relai — Android Village Node

![minSdk 26](https://img.shields.io/badge/minSdk-26%20%28Android%208.0%29-green)
![targetSdk 34](https://img.shields.io/badge/targetSdk-34-blue)
![Kotlin 1.9.24](https://img.shields.io/badge/Kotlin-1.9.24-purple)
![JDK 17](https://img.shields.io/badge/JDK-17-orange)
![Nearby P2P_CLUSTER](https://img.shields.io/badge/Nearby-P2P__CLUSTER-9cf)
![BLE GATT fallback](https://img.shields.io/badge/BLE-GATT%20fallback-yellow)
![Room](https://img.shields.io/badge/Room-2.6.1-success)
![Tests](https://img.shields.io/badge/unit%20tests-5%20files%20%C2%B7%20JUnit4-brightgreen)

One APK = **offline-first mesh node** (Nearby P2P_CLUSTER gossip + raw BLE GATT
fallback + QR sneakernet) + **village SMS gateway** (SMSSync pattern) +
**relay sync / server upload** + **field settings** + **visible outbox**.

A teacher with zero connectivity taps “1. Enregistrer offline”, and the report
sprays phone-to-phone until any node with a data connection uploads it to
Sentinel. No account, no pairing code, no cloud dependency on the critical path.

> **Sources:** every fact below comes from a file in this module —
> 23 `main` Kotlin sources + 5 unit-test files + manifest + layouts +
> Gradle files. Key file references are cited inline.

## Contents

- [Build](#build)
- [Configuration](#configuration-field-settings--buildconfig)
- [Screens](#screens)
- [Architecture: every source file](#architecture-every-source-file)
- [Offline outbox (Room)](#offline-outbox-room)
- [Network client (`Api.kt`)](#network-client-apikt)
- [Nearby relay (`MeshRelayService`)](#nearby-relay-meshrelayservice)
- [BLE fallback (`BleMeshService`)](#ble-fallback-blemeshservice)
- [BLE frames (`BleFrame`)](#ble-frames-bleframe)
- [Duty cycle (`BleDutyCycle`)](#duty-cycle-bledutycycle)
- [SMS gateway](#sms-gateway)
- [QR transport](#qr-transport)
- [Boot & restart](#boot--restart)
- [Transport selector](#transport-selector)
- [Permissions & manifest](#permissions--manifest)
- [Tests](#tests)
- [Field notes](#field-notes)
- [Honest limits](#honest-limits)
- [Roadmap](#roadmap)

## Build

**Exact prerequisites** (read from `app/build.gradle`, root `build.gradle`,
`gradle/wrapper/gradle-wrapper.properties`):

| Tool | Version | Source |
|---|---|---|
| JDK | 17 (`sourceCompatibility`/`targetCompatibility`/`jvmTarget` = 17) | `app/build.gradle:34-38` |
| Android Gradle Plugin | 8.5.2 | root `build.gradle` |
| Kotlin | 1.9.24 (KSP 1.9.24-1.0.20) | root `build.gradle` |
| Gradle | 8.7 (`gradle-8.7-bin.zip`) | `gradle-wrapper.properties` |
| compileSdk / targetSdk | 34 | `app/build.gradle:9,14` |
| minSdk | 26 (Android 8.0) | `app/build.gradle:13` |
| applicationId / namespace | `cm.wash.mesh` | `app/build.gradle:8,12` |
| versionCode / versionName | 1 / `0.1.0` | `app/build.gradle:15-16` |

**No product flavors, no build-type tricks.** `buildTypes` only defines `release`
with `minifyEnabled = false`; `buildFeatures.buildConfig = true` keeps the six
`buildConfigField` values below available at runtime.

```bash
cd mesh/android
gradle wrapper            # once — generates gradlew (jar not versioned)
./gradlew :app:assembleDebug
# APK → app/build/outputs/apk/debug/app-debug.apk  (sideload onto phones)
./gradlew :app:testDebugUnitTest   # pure-Kotlin unit tests (JUnit 4, no device)
```

Field distribution (install, offline formats, limits) lives in
[docs/INSTALL.md §3](../../docs/INSTALL.md).

> Not compiled in dev containers (no JDK/SDK there): build with Android Studio
> or CI before distribution. Protocol logic mirrors the verified TS SDK
> (`mesh/sdk/mesh-sdk.ts`) exactly, and the relay accepts its checksums.

**Dependencies** (`app/build.gradle`):

| Artifact | Version | Used for |
|---|---|---|
| `androidx.core:core-ktx` | 1.13.1 | permissions, compat |
| `androidx.appcompat:appcompat` | 1.7.0 | activities, theme |
| `play-services-nearby` | 19.3.0 | P2P_CLUSTER gossip |
| `play-services-code-scanner` | 16.1.0 | QR scan, no camera permission |
| `room-runtime` / `room-ktx` / `room-compiler` (ksp) | 2.6.1 | persistent outbox |
| `work-runtime-ktx` | 2.9.0 | upload / SMS / restart workers |
| `kotlinx-coroutines-android` | 1.7.3 | IO scopes |
| `zxing:core` | 3.5.3 | QR encode |
| `junit:junit` (test) | 4.13.2 | unit tests |

## Configuration (field settings + BuildConfig)

Six values are compiled in from `gradle.properties` via `buildConfigField`
(`app/build.gradle`), then **overridable at runtime without rebuilding**
through the Settings screen (`relay/FieldSettings.kt`, prefs file
`wash_mesh_settings`).

| `gradle.properties` key | Default | `BuildConfig` field | `FieldSettings` getter | Meaning |
|---|---|---|---|---|
| `LARAVEL_API_URL` | `http://10.0.2.2/api` | `LARAVEL_API_URL` | `getLaravelApiUrl()` | Sentinel API base (upload + SMS gateway) |
| `RELAY_URL` | `http://10.0.2.2:8001` | `RELAY_URL` | `getRelayUrl()` | FastAPI mesh relay base (WiFi sync) |
| `MESH_RELAY_KEY` | *(empty)* | `MESH_KEY` | `getMeshKey()` | `X-Mesh-Key` header; empty = public ingest + quotas |
| `MESH_SMS_SECRET` | `change-moi` | `SMS_SECRET` | `getSmsSecret()` | shared SMS-gateway secret (must match backend `.env`) |
| `MESH_SMS_ALLOWLIST` | *(empty)* | `SMS_ALLOWLIST` | `getSmsAllowlist()` | CSV of allowed SMS senders; empty = everyone |
| `MESH_SMS_QUOTA_PER_SENDER` | `10` | `SMS_QUOTA` (int) | `getSmsQuota()` | local daily transfers per sender |

Semantics (`FieldSettings.kt`):

- **Empty or absent field ⇒ compiled value.** Each string getter does
  `getString(key, null).takeUnless { isNullOrEmpty() } ?: BuildConfig.*`.
- **Quota sentinel:** `QUOTA_UNSET = -1`; `getSmsQuota()` returns
  `BuildConfig.SMS_QUOTA` when the stored int is negative.
- `saveAll(ctx, relayUrl, laravelApiUrl, meshKey, smsSecret, allowlist, quota)`
  writes all six keys at once; `resetToDefaults(ctx)` clears the prefs file so
  every getter falls back to `BuildConfig`.
- `10.0.2.2` = the emulator alias for the dev PC’s localhost. On village LAN,
  set real IPs (e.g. `http://192.168.1.1:8001`) before building — or edit them
  in-app afterwards.

## Screens

### Main screen (`ui/MainActivity.kt` + `res/layout/activity_main.xml`)

Header: `tvStatus` shows `Nœud <nodeId>` (persistent id from `RelayPrefs`).
Inputs: `etSchoolId` (numbers only, e.g. `12`), `etSchoolCode`
(e.g. `DOU-BON-001`, optional), `etMessage` (multi-line report text).

| Button (layout label) | Behavior |
|---|---|
| `1. Enregistrer offline` (`btnSave`) | Requires numeric school id + non-empty message (else toast `École (id) + message requis.`). Builds a bundle via `MeshProtocol.newBundle` (blank school code ⇒ `null`) and inserts it into Room as `PENDING`. Toast `Bundle offline enregistré.` + outbox refresh. Runs on `Dispatchers.IO`. |
| `2. Afficher le QR` (`btnQr`) | Takes the **last** pending bundle, encodes `MeshProtocol.toQr(json)` into a 512 px bitmap (`Qr.encode`) shown in `ivQr` (256 dp). Empty outbox ⇒ toast `Outbox vide.` |
| `3. Scanner un QR` (`btnScan`) | Opens the Play Services code scanner. On success: `fromQr` + `requiredFieldsOk` + `verify`; valid ⇒ insert into Room, toast `Bundle reçu.` + refresh; invalid ⇒ `QR invalide.` Cancel/failure ⇒ `Scan annulé.` |
| `4. Sync relai WiFi` (`btnSync`) | `Api.relaySync(relayUrl, nodeId, pendingJson, pendingIds, meshKey)`. Each received bundle is validated + sprayed (`forward`) before insert; malformed/looped/expired frames are skipped. Toast `Sync: +N reçu(s).`; any exception ⇒ `Relai injoignable.` |
| `5. Uploader vers Sentinel` (`btnUpload`) | Enqueues a one-shot `UploadWorker` constrained to `NetworkType.CONNECTED` with `api_url`/`mesh_key` input. Fire-and-forget: toast `Upload planifié (dès que connecté).` |
| `Démarrer/Stopper le relai (Nearby¦BLE)` (`btnRelay`) | Label reflects Play Services availability (`GoogleApiAvailability… == SUCCESS` ⇒ Nearby, else BLE). Start launches **one** service; stop calls `stop()` on **both**. Also logs the `TransportSelector` decision (`WashUi` tag). |
| `Paramètres` (`btnSettings`) | Opens `SettingsActivity`. |

Startup side effects in `onCreate`: runtime permission request + a
`ModuleInstall` pre-warm of the code-scanner module (first use downloads it
from Play Services).

### Settings screen (`ui/SettingsActivity.kt` + `res/layout/activity_settings.xml`)

Six `EditText`s pre-filled with the **effective** values (`fillFromSettings()`),
banner `Champ vide = valeur compilée.`:

`etRelayUrl` (URI keyboard), `etLaravelApiUrl` (URI), `etMeshKey` (visible
password), `etSmsSecret` (visible password), `etSmsAllowlist` (plain), `etSmsQuota`
(numeric). **Save** trims every field, parses quota (`≥ 0` else `QUOTA_UNSET`),
calls `FieldSettings.saveAll(…)`, toasts `Paramètres enregistrés` and finishes.
**Reset** calls `resetToDefaults()`, refills the fields, toasts
`Valeurs compilées restaurées`.

### Visible outbox

`tvOutboxCounts` shows `En attente : <pending> • Envoyés : <done>` from
`pendingCount()`/`doneCount()`. `llOutbox` renders up to `OUTBOX_LIMIT = 50`
rows (`dao.outbox(50)`), each with a title
(`<id-prefix> • École <id> (<code>) • <date>`, date = `created_at` truncated to
16 chars), a ≤ 80-char single-line message excerpt, and a **Retirer** button
(`deleteById` + toast `Bundle retiré.`). Empty state:
`File vide — rien en attente.` Reloaded from Room on `IO` and rendered on
`Main` (`refreshOutbox()`), including on every `onResume()`.

## Architecture: every source file

`app/src/main/java/cm/wash/mesh/` — 23 files, each documented:

```text
MeshProtocol.kt          protocol core (see below)
data/
  BundleEntity.kt        Room @Entity "bundles"
  MeshDao.kt             8 DAO operations (see Room section)
  MeshDatabase.kt        RoomDatabase singleton "wash-mesh.db", v1
net/
  Api.kt                 HttpURLConnection client (see Network section)
mesh/
  MeshRelayService.kt    Nearby foreground relay (see Nearby section)
  TransportSelector.kt   pure Nearby → BLE → QR selector
  UploadWorker.kt        WorkManager CONNECTED upload to Laravel
ble/
  BleFrame.kt            pure BLE frame codec (see Frames section)
  BleDutyCycle.kt        pure 8 s / 22 s scan cycling
  BleMeshService.kt      dual-role GATT fallback service
relay/
  RelayPrefs.kt          node identity + relay on/off switch
  FieldSettings.kt       6 runtime settings over BuildConfig defaults
  BootReceiver.kt        boot/update restart
  RelayRestartWorker.kt  WorkManager safety-net restart
  RestartPolicy.kt       pure bounded exponential backoff
sms/
  SmsReceiver.kt         SMS_RECEIVED gateway entry point
  SmsPolicy.kt           pure grammar / allowlist / quota rules
  SmsQuotaStore.kt       per-day per-sender counters
  SmsGatewayWorker.kt    WorkManager POST to /api/v1/mesh/sms
qr/
  Qr.kt                  ZXing QR encoder
ui/
  MainActivity.kt        main screen + outbox + relay toggle
  SettingsActivity.kt    6-field settings screen
```

**`MeshProtocol.kt`** — bundle v1.1, exact mirror of `mesh/sdk/mesh-sdk.ts`
(same fields, canonical JSON, binary Spray-and-Wait; the FastAPI relay checks
the same checksum). Constants: `SERVICE_ID = "cm.wash.mesh.v1"`,
`DESTINATION = "dtn://wash-sentinel/ingest"`, `DEFAULT_COPIES = 8`,
`DEFAULT_MAX_HOPS = 10`, `TTL_DAYS = 7`. API: `newNodeId()` (`node-` + 8 UUID
chars); `newBundle(schoolId, schoolCode?, message, originNode, copies = 8)`
(sets `v/bundle_id/origin/school/channel="text"/created_at/expires_at/max_hops/
hops/destination/lifetime_seconds/copies_remaining/priority="normal"`, then
`checksum = sha256Hex(canonical)`); `canonical(bundle)` (sorted keys minus
mutable `checksum/hops/previous_node/copies_remaining`, compact, raw UTF-8);
`sha256Hex`; `forward(bundle, myNode): Forward?` (`give` + `keepCopies`;
binary spray give `⌊n/2⌋` / keep `⌈n/2⌉`; `null` on loop hit, expired/missing
`expires_at`, `hops ≥ max_hops + 1`, or `copies ≤ 1` — the last copy is
reserved for direct server delivery); `verify` (missing checksum ⇒ accepted,
needed by the SMS channel); `requiredFieldsOk` (`bundle_id` + `origin_node_id` +
`school_id`); `toQr`/`fromQr` (unpadded base64url of the bundle JSON).

**`relay/RelayPrefs.kt`** — prefs file `wash_mesh`: `getOrCreateNodeId()`
(generates once via `MeshProtocol.newNodeId()`), `isRelayEnabled()` (default
`false`), `setRelayEnabled()`.

**`qr/Qr.kt`** — `encode(text, size = 512): Bitmap` via `QRCodeWriter`
(`RGB_565`, black/white pixels). Decoding is delegated to Play Services
(see QR section).

(`TransportSelector`, `RestartPolicy`, SMS/relay workers and both services get
their own sections below.)

## Offline outbox (Room)

`data/BundleEntity.kt` — `@Entity(tableName = "bundles")`:

| Column | Type | Notes |
|---|---|---|
| `id` | `String` `@PrimaryKey` | = `bundle_id` |
| `originNode` | `String` | = `origin_node_id` |
| `schoolId` | `Int` | denormalized for list display |
| `json` | `String` | full bundle JSON (mutable: copies/hops evolve) |
| `status` | `String` | `PENDING` (default) → `DONE` after server upload |
| `updatedAt` | `Long` | `System.currentTimeMillis()`, refreshed by `updateJson` |

`data/MeshDao.kt` — every query, verbatim semantics:

- `pending()` — all `PENDING` rows, oldest first (`ORDER BY updatedAt ASC`).
- `outbox(limit = 50)` — same, capped (drives the visible list).
- `pendingCount()` / `doneCount()` — `COUNT(*)` per status (drives counters).
- `deleteById(id)` — hard delete (the **Retirer** button).
- `insert(e)` — `@Insert(onConflict = IGNORE)`, returns row id. **This is the
  dedup point:** re-received bundles are silently dropped everywhere
  (Nearby, BLE, QR, relay sync).
- `updateJson(id, json, now)` — rewrites the bundle JSON (spray budget / hops)
  and bumps `updatedAt`.
- `markDone(ids)` — flips a batch to `DONE` after the server acknowledges it.

`data/MeshDatabase.kt` — `RoomDatabase`, entities `[BundleEntity]`, `version 1`,
`exportSchema = false`, thread-safe singleton (`@Volatile` + `synchronized`)
named `wash-mesh.db`, accessed via `MeshDatabase.get(context)`.

## Network client (`Api.kt`)

Minimal `HttpURLConnection` client, zero dependencies — must run off the UI
thread (coroutine `IO` / `Worker`). Private `post(url, body, meshKey)`:
15 s connect / 30 s read timeouts, `Content-Type/Accept: application/json`,
`X-Mesh-Key` header only when non-empty, parses the error body for the message,
throws `ApiError(code, message)` outside 2xx. Result types:
`SyncResult(sent, received)`, `UploadResult(accepted, duplicates, doneIds)`.

- **`relaySync(relayUrl, nodeId, bundles, knownIds, meshKey)`** — opportunistic
  exchange with the relay: `POST {relayUrl}/v1/sync` with
  `{node_id, bundles[], known_ids[]}`; returns `{stored, bundles[]}` as
  `SyncResult`. “I give my outbox, I take what I’m missing.”
- **`laravelUpload(apiUrl, bundles, meshKey)`** — final upload:
  `POST {apiUrl}/v1/mesh/bundles` with `{bundles[]}`, each mapped to 18
  server fields (`bundle_id`, `origin_node_id`, `school_id`, `school_code`,
  `message`, `channel`, `hops`, `max_hops`, `expires_at`, `checksum`,
  `destination→destination_eid`, `report_to→report_to_eid`,
  `lifetime_seconds`, `previous_node→previous_node_id`, `copies_remaining`,
  `custody_requested`, `priority`, `signature`). Parses
  `summary.{accepted,duplicates}` + `incidents[].bundle_id`; when
  `accepted + duplicates == sent` the whole batch is done (server is
  idempotent — retries never duplicate). `UploadWorker` then `markDone`s them.
- **`smsPost(apiUrl, secret, from, message, sentAtIso)`** — gateway forward:
  `POST {apiUrl}/v1/mesh/sms` with `{secret, from, message, sent_at}`; returns
  the raw `JSONObject` (caller logs its `ticket`).

## Nearby relay (`MeshRelayService`)

Ambient foreground service: advertises **and** discovers
`MeshProtocol.SERVICE_ID` over Nearby Connections **`Strategy.P2P_CLUSTER`**
(BT + BLE + WiFi, 100 % offline), auto-connects and gossips bundles with binary
Spray-and-Wait.

Lifecycle: `onCreate` loads `nodeId`, builds the `ConnectionsClient`, enters
foreground (channel `wash_mesh_relay`, id `42`,
type `connectedDevice`), then `startAdvertising(nodeId, …)` +
`startDiscovery(…)`. `onStartCommand` returns `START_STICKY` and logs
(`WashRelay` tag). `onDestroy` stops endpoints/advertising/discovery and
cancels the `IO` scope. `start(ctx)`/`stop(ctx)` in the companion flip the
`RelayPrefs` switch and (re)start/stop the service (`startForegroundService`
on API 26+).

Gossip: `EndpointDiscoveryCallback.onEndpointFound` dedups via a synchronized
`requested` set and calls `requestConnection(nodeId, …)`.
`ConnectionLifecycleCallback` **auto-accepts** (`acceptConnection` with the
payload callback — deliberate v1 tradeoff for opportunistic store-and-forward;
Ed25519 signatures are the planned Phase 3 auth; id-dedup + server quotas
bound abuse meanwhile). On success → `sendOutbox(endpointId)`: for every
`pending()` bundle, `forward()` a sprayed copy as a byte `Payload`, then
persist the kept budget with `updateJson`. On failure/disconnect the endpoint
leaves `requested`. `PayloadCallback.onPayloadReceived` validates
(`requiredFieldsOk` + `verify`), adds our hop via `forward()` **before**
storing (so what we relay later already carries it), and `insert`s
(dedup by `IGNORE`).

Kill-safety: `onTaskRemoved` (swipe from recents) restarts immediately via
`start()` when still enabled; if the system refuses a background foreground
start (API 31+), it enqueues `RelayRestartWorker` with exponential backoff as
a net.

## BLE fallback (`BleMeshService`)

Raw BLE GATT transport — the **backup when Nearby / Play Services is missing**
(de-Googled phones, Huawei…). 100 % offline, small bundles only.
Every node is **dual-role**: server (advertise + notify its outbox) **and**
client (filtered scan + write its outbox), so both directions are covered and
`bundle_id` dedup absorbs duplicates between the two links.

Lifecycle: `onCreate` loads `nodeId`, enters foreground
(channel `wash_mesh_ble`, id `43`, type `connectedDevice`), opens the GATT
server, starts advertising, starts the duty-cycled scan. `START_STICKY`.
`onDestroy` cancels the scan job, stops scan + advertising, disconnects/closes
all client GATTs, closes the server, cancels the scope.
`isSupported(ctx)` = `FEATURE_BLUETOOTH_LE`; `start(ctx)`/`stop(ctx)` mirror
the Nearby service (same `RelayPrefs` switch).

Server role: one primary service (`SERVICE_UUID`) with a `TX` characteristic
(`PROPERTY_NOTIFY`, readable, with CCCD read/write) and an `RX` characteristic
(`WRITE | WRITE_NO_RESPONSE`, write-only). Advertising is
`LOW_LATENCY` / `HIGH` TX power / connectable, carrying the service UUID.
On CCCD subscribe → `sendOutboxToServerPeer(device)`; on RX write →
`onFramesReceived(value)`; `onNotificationSent` pumps the next queued frame
(`pumpServerQueue`, one at a time); disconnect clears subscribe + queue state;
`onMtuChanged` caches the MTU per device address.

Client role: filtered scan (service UUID, `SCAN_MODE_LOW_LATENCY`), at most
`MAX_CONNECTIONS = 3` concurrent GATTs, `connectGatt(…, TRANSPORT_LE)`.
On connect → `requestMtu(512)` (fallback: straight to `discoverServices()`);
on MTU → cache + discover; on services → enable TX notifications via CCCD
(dual code path: API 33+ `writeDescriptor(cccd, value)`, older
`cccd.value = …` + `writeDescriptor(cccd)`); on descriptor write →
`sendOutboxToClientPeer(gatt)`; `onCharacteristicChanged` has **both**
overloads (deprecated `characteristic.value` + API 33 `(gatt, char, value)`).
Every RX/TX frame funnels into `onFramesReceived`.

Exchange: `queueOutbox()` reads `dao.pending()`, **smallest-first (Rhizome)**,
drops media fragments (`chunk` field present) and anything over
`MAX_BUNDLE_BYTES = 50 KiB`, `forward()`s each survivor, persists the kept
budget, and returns `(bundle_id, bytes)` pairs. Each pair is `BleFrame.encode`d
for the peer’s MTU (cached, default 23) into a per-device
`ConcurrentLinkedQueue`, pumped one frame at a time
(`pumpServerQueue`/`pumpClientQueue` with `serverSending`/`clientSending`
guards — chained writes, never parallel). Inbound: `Reassembler.feed` →
`JSONObject` → `requiredFieldsOk` + `verify` → `forward` → `insert`.
Threading: `SupervisorJob + Dispatchers.IO` scope, `ConcurrentHashMap`s and a
synchronized `subscribed` set.

AOSP constraints honored: ≤ 1 scan per 30 s window (8 s scan / 22 s idle),
≤ 3 connections, negotiated MTU, chained writes, permanent foreground service.

## BLE frames (`BleFrame`)

Pure-Kotlin codec, no Android imports — exact mirror of
`mesh/demo/ble_frames.py` (also covered by JVM unit tests + a Python suite).

Frame layout (`HEADER_LEN = 11`):

| Bytes | Field | Value |
|---|---|---|
| 0–1 | magic | `W` `S` (`0x57 0x53`) |
| 2 | version | `1` |
| 3–6 | tag | `sha256(bundle_id)[:4]` (`bundleTag()`) |
| 7–8 | index | big-endian u16 |
| 9–10 | total | big-endian u16 |
| 11+ | payload | `mtu - 3 - 11` bytes max per frame |

UUIDs: service `a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5`, TX `…c4d6`,
RX `…c4d7`, CCCD `00002902-0000-1000-8000-00805f9b34fb` (standard).

- `encode(bundle, bundleId, mtu = 512)` — requires `mtu ≥ 16`, `total ≤ 0xFFFF`
  (else `IllegalArgumentException`); guarantees ≥ 1 frame even for empty input.
- `Reassembler.feed(frame, nowMs)` — `@Synchronized`; evicts partials older
  than `PARTIAL_TTL_MS = 60 000`; rejects short frames, bad magic/version,
  `total == 0`, `index ≥ total`, and total mismatches on an existing tag;
  tolerates out-of-order + duplicate chunks; returns the reassembled bundle
  once all `total` chunks for a tag arrived. (`MAX_CHUNK = 200` is reserved.)
- Tag collisions across bundles are theoretically possible (32-bit tag) but
  harmless in practice: `verify()` + `requiredFieldsOk()` re-check the
  reassembled JSON before storage.

## Duty cycle (`BleDutyCycle`)

Pure object: `ACTIVE_MS = 8 000`, `IDLE_MS = 22 000`, `CYCLE_MS = 30 000`
(~27 % duty cycle). **Only the scan is cycled** — advertising and the GATT
server stay continuous — because scanning is the hungriest and most
AOSP-throttled operation (5 scans / 30 s quota); cycling divides the fallback
relay’s cost by ~4. `isActiveWindow(elapsedMs)` is true during the active
window (negative input ⇒ true); `msUntilNextPhase(elapsedMs)` returns the
milliseconds until the next phase flip. `BleMeshService` consumes the two
constants as `SCAN_MS`/`IDLE_MS` in its `while (isActive)` scan coroutine.

## SMS gateway

Village gateway in the SMSSync pattern: any basic phone can file a report by
texting `WASH <school-code> <type> [detail]`; this phone auto-forwards valid
texts to `POST /api/v1/mesh/sms` whenever mobile data exists.

**Grammar** (`sms/SmsPolicy.kt`, pure, mirrors backend `MeshSmsParser` +
`WashSmsController`):

- Keywords: `WASH`, `EAU` (first token, case/accent-insensitive via
  `asciiUpper` = uppercase + NFD accent strip, the equivalent of backend
  `Str::ascii`).
- Types (exact token or synonym): `P` = panne pompe/forage
  (`P, PANNE, POMPE, FORAGE`), `L` = latrine
  (`L, LATRINE(S), WC, TOILETTE(S)`), `E` = eau/qualité
  (`E, EAU, QUALITE, TROUBLE, SALE`), `H` = hygiène
  (`H, HYGIENE, SAVON, LAVAGE`). Labels in `TYPE_LABELS`.
- School code regex: `[A-Z0-9][A-Z0-9\-]{0,30}[A-Z0-9]` or 1–2 alphanumerics
  (existence is checked server-side). Detail = remaining tokens joined,
  capped at 100 chars.
- `parse(raw): Parsed(ok, code, type, detail, error)`; any failure returns
  `HELP = "Envoyez: WASH CODE TYPE. Ex: WASH DOU-BON-001 P (P=panne, L=latrine,
  E=eau, H=hygiene)."` (with a specific prefix for bad code/type).

**Early filtering** (rejected here ⇒ never leaves the phone): grammar, then
**exact allowlist** (`isAllowlisted`: CSV split/trim, empty ⇒ open to all,
strict equality — no prefix match), then **daily quota**
(`quotaExceeded(sentToday, quota = DEFAULT_QUOTA = 10)`, aligned with backend
`MESH_SMS_QUOTA_PER_SENDER`).

**`sms/SmsReceiver.kt`** — `BroadcastReceiver` on `SMS_RECEIVED`: reassembles
multi-segment texts per sender (`Telephony.Sms.Intents.getMessagesFromIntent`,
concatenated bodies, earliest `timestampMillis` kept), stamps `LocalDate.now()`
for quota, then per sender runs parse → allowlist (`FieldSettings`) → quota
(`SmsQuotaStore.countFor`) → `SmsQuotaStore.record` → enqueues
`SmsGatewayWorker` with `from`/`body`/`sent_at`. Logs under `WashSms`.

**`sms/SmsQuotaStore.kt`** — prefs `wash_sms_quota`, key `"<yyyy-mm-dd>|<from>"`,
`countFor()` / `record()` (increments, returns new count). Redundant with the
server on purpose (local anti-spam even offline).

**`sms/SmsGatewayWorker.kt`** — `CoroutineWorker`: refuses to run when the SMS
secret is empty (`Result.failure()`, log `transfert impossible : … vide`);
`sent_at` epoch → ISO via `Instant`; `Api.smsPost(laravelApiUrl, secret, from,
body, sentAt)`, logs the returned `ticket`. Retry policy: `403` (secret/
allowlist) and `422` (format) ⇒ `Result.success()` — definitive, no retry;
`429` and `5xx` ⇒ `Result.retry()`; anything else ⇒ `Result.failure()`.
The server stays final arbiter (24 h dedup).

## QR transport

The no-radio fallback. **Encode:** `MeshProtocol.toQr(bundle)` (unpadded
base64url of the bundle JSON, UTF-8) → `Qr.encode(text, 512)` (ZXing
`QRCodeWriter`, `RGB_565` bitmap) → shown in `ivQr`.
**Decode:** `MeshProtocol.fromQr(payload)` (trim → base64url-decode → `JSONObject`,
`null` on any failure), fed by the **Play Services code scanner**
(`GmsBarcodeScanning.getClient(this).startScan()`) — no camera permission
needed — pre-warmed at startup via `ModuleInstall`. Every scanned bundle is
validated (`requiredFieldsOk` + `verify`) before insert.
`TransportSelector.QR_MAX_BYTES = 2000` is the safe binary-mode ceiling (margin
under the ~2953 theoretical bytes): oversized QR selections carry an explicit
“volumineux” warning in the logged reason.

## Boot & restart

- **`relay/BootReceiver.kt`** — exported receiver on `BOOT_COMPLETED`,
  `MY_PACKAGE_REPLACED` and `QUICKBOOT_POWERON`: no-op unless
  `RelayPrefs.isRelayEnabled()`; else starts `MeshRelayService` + (if
  `FEATURE_BLUETOOTH_LE`) `BleMeshService`, logging under `WashBoot`. If a
  background foreground-start is refused (API 31+), falls back to enqueueing
  `RelayRestartWorker` with exponential backoff.
- **`relay/RelayRestartWorker.kt`** — safety net `CoroutineWorker`: exits
  `success` when the relay was disabled; else starts both services (BLE gated
  on support); on exception `retry()` until `runAttemptCount >= 5`, then
  `failure()`.
- **`relay/RestartPolicy.kt`** — pure bounded backoff:
  `BASE_DELAY_MS = 5 000`, `MAX_DELAY_MS = 300 000` (5 min);
  `nextDelayMs(attempt, base, max)` = `base × 2^attempt` capped at max
  (attempt clamped to 20 iterations; `attempt ≤ 0` or `base ≤ 0` ⇒ base).
  Real timing is owned by WorkManager / the system.

## Transport selector

`mesh/TransportSelector.kt` — pure `select(nearbyReady, bleReady, payloadBytes):
Selection(primary, fallbacks, reason)`. Priority: `NEARBY` when ready →
`BLE` → `QR` (always usable, the ultimate manual recourse). Fallbacks = other
usable transports in enum order. Reasons (logged by callers): `Nearby actif`,
`Nearby indisponible → BLE (secours GATT)`, `Nearby et BLE indisponibles → QR
manuel`, plus the oversize warning when `primary == QR && payloadBytes > 2000`.
`MainActivity` logs the selection (`WashUi`) on every relay toggle.

## Permissions & manifest

`app/src/main/AndroidManifest.xml`. Install-time: `INTERNET` + `ACCESS_NETWORK_STATE`
(HTTP upload/sync; `usesCleartextTraffic = true` because the village LAN is
plain HTTP). Everything below needs a user grant or a system condition:

| Permission | Why | Runtime request |
|---|---|---|
| `ACCESS_FINE_LOCATION` | Nearby/BLE scanning counts as location (API 23–30 rule) | yes, at startup |
| `BLUETOOTH` / `BLUETOOTH_ADMIN` (`maxSdkVersion 30`) | legacy BT stack on old devices | no (legacy) |
| `BLUETOOTH_SCAN` / `BLUETOOTH_CONNECT` / `BLUETOOTH_ADVERTISE` | BLE scan + GATT + advertise (API 31+) | yes, API 31+ |
| `ACCESS_WIFI_STATE` / `CHANGE_WIFI_STATE` | Nearby’s WiFi radios | no (normal) |
| `NEARBY_WIFI_DEVICES` (`neverForLocation`) | Nearby on API 33+ | yes, API 33+ |
| `RECEIVE_SMS` | SMS gateway reads incoming texts | yes, at startup |
| `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_CONNECTED_DEVICE` | permanent ambient relay (mandatory notification) | no (type declared on both services) |
| `POST_NOTIFICATIONS` | the foreground notification itself (API 33+) | yes, API 33+ |
| `RECEIVE_BOOT_COMPLETED` | boot restart when enabled | no |

Also: `<uses-feature bluetooth_le required="true">` (Play filtering);
`allowBackup = true`; launcher `MainActivity` (`exported = true`);
`SettingsActivity` + both services `exported = false`, services declare
`foregroundServiceType = connectedDevice`; `SmsReceiver` `exported = true`,
priority `999`, `SMS_RECEIVED`; `BootReceiver` `exported = true` with the
three boot/update actions.

`MainActivity.requestPermissions()` requests exactly the runtime subset above
(location + SMS always; +BT trio on 31+; +Nearby-WiFi/notifications on 33+),
only the still-missing ones, via `RequestMultiplePermissions` (result ignored —
features degrade gracefully).

## Tests

`./gradlew :app:testDebugUnitTest` — 5 files, JUnit 4, all pure-Kotlin
(no Robolectric, no device):

| File | What it pins |
|---|---|
| `ble/BleDutyCycleTest.kt` (3 tests) | 8 s/22 s/30 s constants; active-window boundaries (0/7999/8000/29999/30000/60001); ms-until-phase (8000/1/22000/1/8000) |
| `ble/BleFrameTest.kt` (5 tests) | single-frame roundtrip; multi-frame (MTU 128, 1200 B) out-of-order + post-completion duplicate; 11-byte header layout (`WS`, ver 1, `sha256("b")[:4]`, BE index/total); every header byte corrupted ⇒ `null`, short frame ⇒ `null`; tag stability |
| `mesh/TransportSelectorTest.kt` (5 tests) | Nearby wins w/ `[BLE, QR]` fallbacks; BLE fallback w/ `[QR]` + reason; QR last resort w/ empty fallbacks; oversize (`MAX+1`) warns, exactly-MAX does not |
| `relay/RestartPolicyTest.kt` (3 tests) | 5 s → 10 s → 20 s → 40 s; capped at 300 000 (attempts 10/100); negative attempt ⇒ base |
| `sms/SmsPolicyTest.kt` (7 tests) | minimal valid SMS; `EAU` keyword + detail uppercasing; lowercase/accents/synonyms (`pompe` ⇒ `P`); synonyms (`WC/L`, `EAU/E`, `SAVON/H`, `FORAGE/P`); 5 invalid formats; exact allowlist (empty/open, no prefix match); quota 9 ok / 10+ exceeded |

Coverage is the pure policy/codec core (`BleDutyCycle`, `BleFrame`,
`TransportSelector`, `RestartPolicy`, `SmsPolicy`). Not unit-covered (by
design, they need a device/emulator): both foreground services, the three
workers, both receivers, both activities, Room, and `Api` — exercise those via
the two-phone field test below.

## Field notes

- **Battery & Doze:** the relay is a permanent foreground service (two when BLE
  is on) with an ongoing notification — that’s what keeps the process alive.
  Still, exempt the app from battery optimization on the village phones and
  prefer devices left plugged into the solar charger as “anchor” relays.
- **Location must stay ON:** Nearby and BLE scanning silently return nothing
  with location off (OS-level rule, not an app bug). If no neighbor is ever
  found, check location + the runtime grants first.
- **Play Services decides the transport:** with Play Services the toggle starts
  Nearby; without (de-Googled/Huawei), raw BLE GATT. The button label tells
  you which one *before* you start. Keep a QR workflow ready as the third leg.
- **Two-phone smoke test:** install the APK on two phones → phone A saves a
  bundle offline → start the relay on both → phone B’s outbox should show A’s
  bundle within a minute (watch `WashRelay` logcat: `voisin Nearby trouvé` →
  `connecté, envoi outbox` → `bundle Nearby reçu et stocké`). Then give B data
  and tap upload.
- **SMS gateway phone:** needs a SIM that can receive villagers’ texts and
  occasional data; set `MESH_SMS_SECRET` = backend value and the allowlist to
  the headmasters’ numbers. Every forward is logged with its server `ticket`.
- **Solar / low-end realities:** minSdk 26 keeps 2017+ phones in play; the BLE
  duty cycle (~27 %) and smallest-first transfers exist for weak batteries;
  media fragments never go over BLE (50 KiB cap) — they wait for Nearby/WiFi.
- **Sideload vs Play:** distribute the APK by sideload (USB/SD/relay download).
  `RECEIVE_SMS` makes Play distribution effectively impossible (SMS policy),
  and the app needs no store account anyway.
- **Emulator:** `10.0.2.2` defaults just work; on hardware, point both URLs at
  the village-LAN server/relay IPs (build-time or Settings screen).

## Honest limits

- **No crypto auth yet:** Nearby auto-accepts (required for opportunistic
  mesh); integrity is checksums + id-dedup + server quotas until Ed25519
  signatures land (Phase 3). A malicious neighbor can inject well-formed
  bundles — the server, not the phone, is the trust anchor.
- **BLE is small-only:** ≤ 50 KiB bundles, media fragments excluded, ≤ 3
  simultaneous peers, ~27 % scan duty cycle. Big reports need Nearby or WiFi.
- **QR is manual and small:** ~2000 safe bytes; one bundle per scan; needs
  Play Services for the scanner module (first use downloads it).
- **SMS channel is unverified on-device:** missing checksums are accepted by
  design (`verify` ⇒ true), so the server re-validates everything; quota and
  allowlist are mirrored locally but enforced authoritatively backend-side.
- **No delivery receipts / custody transfer:** `DONE` means “the server said
  accepted/duplicate”, not “a human read it”. No multi-hop custody accounting.
- **Single shared mesh key, HTTP on LAN:** village-LAN threat model (physical
  proximity); no per-node credentials, no TLS on the relay link.
- **Not Play-distributable** (`RECEIVE_SMS`), no iOS build, French/English UI
  strings mixed (see roadmap), Room schema v1 with no migration yet.

## Roadmap (APK)

1. **Phase 3 signatures:** Ed25519 sign on create, verify on receive,
   drop/replace auto-accept with authenticated gossip.
2. **Media over Nearby:** chunked photo transfer on the P2P_CLUSTER link
   (BLE stays text-only), resume + progress in the outbox.
3. **Delivery receipts:** server → relay → phone ack path so `DONE` becomes
   “acknowledged”, plus per-bundle state in the outbox (copies left, hops).
4. **i18n + UX:** proper `strings.xml` FR/EN, dark-mode check, outbox search,
   relay stats screen (neighbors seen, bundles relayed).
5. **Hardening:** Room migration strategy, TLS option for the relay link,
   per-node keys, Doze/optimizer onboarding checklist in-app.
6. **Play-adjacent SMS:** evaluate SMS Retriever/User-Consent as a
   policy-compliant gateway path (likely still sideload-first).

