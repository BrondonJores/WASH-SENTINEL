# 📱 WASH Relai — appli Android villageoise (Phase 1 + 2, relai durci V2)

Un seul APK = **nœud mesh** (Nearby P2P_CLUSTER + secours BLE GATT,
store-and-forward) + **passerelle SMS** (pattern SMSSync) + **QR**
(émission/scan). Kotlin, minSdk 26.

## Compiler

Prérequis : JDK 17 + Android SDK (platform 34, build-tools) + un Gradle système
ou Android Studio.

```bash
cd mesh/android
gradle wrapper            # une fois, génère gradlew (jar non versionné)
./gradlew :app:assembleDebug
# APK : app/build/outputs/apk/debug/app-debug.apk → sideload sur les téléphones
```

Diffusion terrain : voir [docs/INSTALL.md §3 « Android — APK natif »](../../docs/INSTALL.md#3-android--apk-natif)
(installation, formats offline, limites honnêtes).

Configurer d'abord `gradle.properties` : `LARAVEL_API_URL` et `RELAY_URL`
(IP LAN du serveur/relai au village, pas localhost), `MESH_SMS_SECRET`
(identique à `MESH_SMS_SECRET` côté `backend/.env`), `MESH_RELAY_KEY`
si `MESH_INGEST_KEY` / `MESH_RELAY_API_KEY` sont définis côté serveur,
`MESH_SMS_ALLOWLIST` (CSV, vide = ouvert) et `MESH_SMS_QUOTA_PER_SENDER`
(défaut 10, comme le backend).

> Compilation non vérifiée dans le conteneur de dev (pas de JDK/SDK) :
> builder via Android Studio ou CI avant diffusion. La logique protocole
> (`MeshProtocol`) est le miroir exact du SDK TS vérifié (`mesh/sdk/mesh-sdk.ts`)
> et le relai accepte ses checksums (tests `test_checksum_*`).

## Architecture

```text
app/src/main/java/cm/wash/mesh/
├── MeshProtocol.kt     # bundles v1.1, JSON canonique, sha256, spray binaire, QR base64url
├── data/               # Room : BundleEntity + MeshDao + MeshDatabase (outbox persistante)
├── net/Api.kt          # HTTP minimal : relaySync, laravelUpload, smsPost (+ X-Mesh-Key)
├── mesh/
│   ├── MeshRelayService.kt  # foreground service : advertise+discover Nearby, gossip spray
│   ├── TransportSelector.kt # sélecteur pur Nearby → BLE → QR (+ motif journalisé)
│   └── UploadWorker.kt      # WorkManager CONNECTED : pousse l'outbox vers Laravel, purge
├── ble/
│   ├── BleFrame.kt          # trames BLE pures (miroir testé de mesh/demo/ble_frames.py)
│   ├── BleDutyCycle.kt      # rapport cyclique pur : 8 s radio ON / 22 s OFF (cycle 30 s)
│   └── BleMeshService.kt    # secours sans Play Services : serveur+client GATT, duty-cycle
├── relay/
│   ├── RelayPrefs.kt        # node_id + interrupteur relai persistants
│   ├── RestartPolicy.kt     # backoff pur 5 s → 5 min pour les relances
│   ├── BootReceiver.kt      # BOOT_COMPLETED / MAJ : relance le relai si activé
│   └── RelayRestartWorker.kt# filet WorkManager quand la relance directe est refusée
├── sms/
│   ├── SmsPolicy.kt         # grammaire WASH/EAU + allowlist + quota (miroir backend, pur)
│   ├── SmsQuotaStore.kt     # compteur local par expéditeur et par jour
│   ├── SmsReceiver.kt       # SMS_RECEIVED : réassemble, filtre, met en file WorkManager
│   └── SmsGatewayWorker.kt  # POST /api/v1/mesh/sms (secret partagé, retry différenciés)
├── qr/Qr.kt            # encodage QR (ZXing ; décodage via Play Services Code Scanner)
└── ui/MainActivity.kt  # écran unique : saisie offline, QR, sync, upload, marche/arrêt relai
```

## BLE de secours (V3)

Sans Play Services (Huawei, dégooglisés…), l'appli bascule sur `BleMeshService`
(sélection auto au bouton relai) : serveur GATT (advertise + notify) et client
(scan filtré + write) simultanés, MTU négocié jusqu'à 512, ≤3 connexions,
duty-cycle 8 s scan / 22 s idle (quota AOSP 5 scans/30 s respecté), petits
bundles <50 Ko (fragments médias exclus — Nearby/WiFi uniquement).

Trames (`BleFrame`, miroir de `mesh/demo/ble_frames.py`, 7 tests Python) :
`WS` + ver + tag(4) + index/total (2+2 BE) + payload. UUID service :
`a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5` (TX `…d6`, RX `…d7`).

Tests unitaires (`app/src/test`, Kotlin pur + JUnit 4) :

```bash
./gradlew :app:testDebugUnitTest
```

Couverts : `TransportSelector`, `BleFrame`, `BleDutyCycle`, `SmsPolicy`,
`RestartPolicy`.

## Notes terrain

- Nearby exige Bluetooth + WiFi + **localisation activée** (système) et des
  autorisations runtime demandées à l'ouverture ; sans foreground service,
  Android tue le relai en quelques minutes (notification permanente normale).
- Deux modes : « sync volontaire » (bouton, économe) et « relai ambiant »
  (service permanent, opt-in — coûte de la batterie).
- La passerelle SMS tourne même sans data : les SMS s'enfilent et partent
  dès qu'une connexion revient. Prévoir 2 téléphones relais par zone
  (MTN + Orange) + charge solaire.
- Relai durci : interrupteur persistant, relance au boot (`BootReceiver`,
  `RECEIVE_BOOT_COMPLETED`), `START_STICKY` + relance au balayage des
  récents + filet WorkManager. Sur API 31+, un démarrage foreground
  depuis le fond peut être refusé par le système : le Worker réessaie.
- Secours BLE : radio active 8 s / 30 s seulement (`BleDutyCycle`),
  serveur GATT en notify + client opportuniste (MTU 512 demandé).
  Trame : en-tête 11 octets `WS` + ver + tag(4) + index/total,
  réassemblage par tag (`BleFrame`, miroir Python testé).
- Passerelle SMS : filtrage local aligné backend (grammaire `WASH <CODE>
  <TYPE> [détail]`, types P/L/E/H + synonymes, allowlist exacte, quota
  10/jour/expéditeur), réassemblage multi-segments, 403/422 sans retry.
  Codes démo du seed pour les tests SMS : `DOU-BON-001`, `DOU-LIB-002`,
  `DOU-BAL-003` (`backend/database/seeders/WashDemoSeeder.php`).
- iOS : exclu du relai (restrictions Apple), saisie + QR + upload direct uniquement.
