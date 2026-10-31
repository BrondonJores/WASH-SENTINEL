# 📱 WASH Relai — appli Android villageoise (Phase 1 + 2)

Un seul APK = **nœud mesh** (Nearby P2P_CLUSTER, store-and-forward) +
**passerelle SMS** (pattern SMSSync) + **QR** (émission/scan). Kotlin, minSdk 26.

## Compiler

Prérequis : JDK 17 + Android SDK (platform 34, build-tools) + un Gradle système
ou Android Studio.

```bash
cd mesh/android
gradle wrapper            # une fois, génère gradlew (jar non versionné)
./gradlew :app:assembleDebug
# APK : app/build/outputs/apk/debug/app-debug.apk → sideload sur les téléphones
```

Configurer d'abord `gradle.properties` : `LARAVEL_API_URL` et `RELAY_URL`
(IP LAN du serveur/relai au village, pas localhost), `MESH_SMS_SECRET`
(identique à `MESH_SMS_SECRET` côté `backend/.env`), `MESH_RELAY_KEY`
si `MESH_INGEST_KEY` / `MESH_RELAY_API_KEY` sont définis côté serveur.

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
│   └── UploadWorker.kt      # WorkManager CONNECTED : pousse l'outbox vers Laravel, purge
├── sms/
│   ├── SmsReceiver.kt       # SMS_RECEIVED filtré WASH/EAU → file WorkManager
│   └── SmsGatewayWorker.kt  # POST /api/v1/mesh/sms (secret partagé, retry différenciés)
├── qr/Qr.kt            # encodage QR (ZXing ; décodage via Play Services Code Scanner)
└── ui/MainActivity.kt  # écran unique : saisie offline, QR, sync, upload, marche/arrêt relai
```

## Notes terrain

- Nearby exige Bluetooth + WiFi + **localisation activée** (système) et des
  autorisations runtime demandées à l'ouverture ; sans foreground service,
  Android tue le relai en quelques minutes (notification permanente normale).
- Deux modes : « sync volontaire » (bouton, économe) et « relai ambiant »
  (service permanent, opt-in — coûte de la batterie).
- La passerelle SMS tourne même sans data : les SMS s'enfilent et partent
  dès qu'une connexion revient. Prévoir 2 téléphones relais par zone
  (MTN + Orange) + charge solaire.
- iOS : exclu du relai (restrictions Apple), saisie + QR + upload direct uniquement.
