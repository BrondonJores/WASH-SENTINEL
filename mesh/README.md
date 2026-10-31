# 🕸️ WASH Mesh — signalements pair-à-pair pour zones sans internet

> En parallèle du projet principal : un réseau tolérant aux coupures (DTN / store-and-forward)
> pour que les localités éloignées du Cameroun signalent quand même leurs pannes d'eau.

## Le principe (simple)

```
Village sans réseau                    Ville avec réseau
┌──────────┐   Bluetooth/QR/WiFi   ┌──────────┐   WiFi/4G   ┌──────────┐   HTTPS   ┌─────────┐
│ Node A   │ ────────────────────► │ Node B   │ ─────────► │ Node C   │ ────────► │ Laravel │
│ (offline)│   bundle stocké       │ (relai)  │  bundle    │ (connecté)│  upload   │ + IA    │
└──────────┘                       └──────────┘            └──────────┘           └─────────┘
```

1. **A** (directeur d'école, hors-ligne) rédige son signalement. Le téléphone crée un **bundle**
   signé avec un `bundle_id` unique, stocké dans l'outbox locale.
2. **A croise B** (parent d'élève, taxi-moto…) : le bundle est copié via **QR code**,
   Bluetooth ou WiFi local. B ne peut pas le lire en clair (option chiffrement), il le transporte.
3. **B croise C** (connecté) : même copie opportuniste, `hops` s'allonge.
4. **C**, dès qu'il a internet, **uploade le batch** vers Laravel (`POST /api/v1/mesh/bundles`)
   ou vers le relai (`mesh-relay`). Laravel **déduplique** par `bundle_id` et lance le
   pipeline IA normal (triage, doublons, priorité) avec `source = 'mesh'`.

Pas de nœud connecté ? Les bundles attendent dans les outbox jusqu'au TTL (7 jours).

## Contenu du repo

```text
mesh/
├── README.md              # ce fichier (spec du protocole)
├── server/                # mesh-relay : FastAPI store-and-forward + WebSocket (port 8001)
├── sdk/                   # mesh-sdk.ts : outbox offline, bundles, QR, sync (zéro dépendance)
├── android/               # WASH Relai : appli Kotlin (Nearby + passerelle SMS + QR)
└── demo/                  # simulate_hops.py : démo A → B → C → serveur
```

Côté Laravel : `mesh_bundles` (migration + modèle). Endpoints réels
(`backend/routes/api.php`, préfixe `/api/v1/mesh`) :

- `POST /bundles` (throttle 60/min) : ingestion batch, dédup par `bundle_id`,
  puis triage IA standard (`source = 'mesh'`).
- `GET /bundles/pending` : bundles en attente, paginés (`per_page` ≤ 100).
- `GET /bundles/{bundleId}` : détail + école + signalement (404 si inconnu).
- `GET /stats` : total, par statut, hops moyens, parts relayé/chiffré, origines.
- `GET /key` : clé publique E2E serveur (503 si non configurée → clients en clair).
- `POST /sms` : canal SMS `WASH <CODE> <TYPE> [détail]` (secret partagé,
  allowlist, quotas — voir §v1.1).
- `POST /ussd` + `GET /ussd` : canal USSD (passerelle opérateur).

## Format du bundle (v1)

Compact (~0,5 Ko en JSON, ~700 caractères en QR base64url — mesuré sur un
bundle texte réaliste ; ~0,7 Ko / ~900 caractères avec signature V2),
sérialisable en QR :

```json
{
  "v": 1,
  "bundle_id": "uuidv4",
  "origin_node_id": "node-abc123",
  "school_id": 1,
  "school_code": "DOU-BON-001",
  "channel": "text",
  "message": "Pompe brisée depuis ce matin, 400 élèves sans eau",
  "created_at": "2026-10-31T10:00:00Z",
  "expires_at": "2026-11-07T10:00:00Z",
  "max_hops": 10,
  "hops": ["node-abc123", "node-def456"],
  "checksum": "sha256hex…"
}
```

Règles :

- `bundle_id` UUID v4 → **déduplication** partout (SDK, relai, Laravel).
- `hops` = traçabilité + **anti-boucle** (on ne retransmet jamais à un nœud déjà dans `hops`).
- `hop_count = len(hops) - 1`, refusé si `> max_hops` (défaut 10).
- `expires_at = created_at + TTL` (défaut 7 jours) → expiré = supprimé, jamais uploadé.
- `checksum = sha256(canonical)` sur les champs d'origine immuables uniquement — `hops`, `previous_node` et `copies_remaining` sont exclus car mutés à chaque saut (modèle Rhizome) → intégrité du manifeste, relais qui vérifient sans ré-écrire.
- Photos/vocal : **médias différés V2b** (manifeste + fragments, voir section dédiée).

## Transports (du plus rustique au plus fluide)

| # | Transport | Quand l'utiliser | Implémentation |
|---|-----------|------------------|----------------|
| 1 | **QR code** | Marche toujours, même sans Bluetooth | `sdk.serializeForQR()` → string base64url à afficher/scanner |
| 2 | **BLE GATT brut** | Android sans Play Services (secours V3) | `android/ble/` : trames WS 11 octets + payload, MTU négocié, duty-cycle 8 s/22 s |
| 3 | **Nearby** | Smartphones Android (principal) | `android/mesh/` : P2P_CLUSTER offline, BT+BLE+WiFi |
| 4 | **Sync locale** | Même WiFi village / hotspot / câble | `POST mesh-relay/v1/sync` : échange bidirectionnel en 1 appel |
| 5 | **WebSocket** | Deux nœuds en ligne en même temps | `WS mesh-relay/v1/ws/{node_id}` : push temps réel |
| 6 | **Upload final** | Premier nœud avec internet | `POST laravel/api/v1/mesh/bundles` (batch, dédupliqué) |

## Relai (`mesh/server`, port 8001)

Store-and-forward FastAPI : SQLite WAL + cache chaud mémoire, purge TTL,
éviction LRU, dédup par `bundle_id`. Clé optionnelle `X-Mesh-Key`
(`MESH_RELAY_API_KEY`, vide = public + quotas).

- `POST /v1/fetch` : `{node_id, known_ids[], limit ≤ 200 (déf. 50)}` →
  `{bundles[], count, stored_total, acked_ids[]}`. Lecture seule : rend
  tout ce que l'appelant ne connaît pas (expirés exclus) sans rien envoyer ;
  `acked_ids` (∩ avec `known_ids`) = ses bundles arrivés au serveur,
  à purger de son outbox.
- Autres : `POST /v1/store`, `POST /v1/sync` (= store + fetch en 1 appel),
  `POST /v1/ack`, `POST /v1/uplink` (pousse vers Laravel, `?dry_run=true`
  pour sonder), `GET /v1/stats`, `GET /health`, `GET /metrics`,
  `WS /v1/ws/{node_id}` (push temps réel).

## Protocole v1.1 (Phase 0, additif)

Alignement BPv7 (RFC 9171) sans casser la v1 — tous les champs sont optionnels,
le serveur applique des défauts :

- `destination` (`dtn://wash-sentinel/ingest`) + `report_to` : destination explicite.
- `lifetime_seconds` préféré à `expires_at` : le serveur dérive l'expiration
  (horloges villageoises non fiables).
- `previous_node` : dérivé du dernier hop si absent.
- `copies_remaining` (défaut 8) : Binary Spray-and-Wait — à chaque contact on
  donne `floor(n/2)` et on garde `ceil(n/2)` ; à 1, livraison directe au
  serveur uniquement, plus de relai P2P.
- `priority` (`normal` | `high` | `alert`) : `alert` = flooding autorisé
  (ex. suspicion choléra), sinon spray borné.
- `fragment_offset` / `fragment_total`, `custody_requested`.
- `signature` + `node_pubkey` : **livré Ed25519** (clôt le « réservé Phase 3 »,
  voir §Sécurité pour le format, la forme canonique et le modèle TOFU).

Serveur : clé optionnelle `X-Mesh-Key` (`MESH_INGEST_KEY` / `MESH_RELAY_API_KEY`,
vide = public + throttle + quotas), quota journalier par origine (défaut 500),
éviction LRU sur le relai, compteurs par cause dans `/v1/stats`, logs
`mesh.bundle.*` tracés par `bundle_id`.

Canal SMS : `WASH <CODE_ECOLE> <TYPE> [détail]` (`P`/`L`/`E`/`H`) via
`POST /api/v1/mesh/sms` (secret partagé SMSSync, allowlist, quota/expéditeur).
Le SMS devient un bundle `sms:<numéro>` puis suit le triage standard.

## Médias différés (V2b)

Photos compressées (JPEG ≤1280px q0.7) et vocaux courts (≤30 s, ≤2 Mo) :
chiffre-puis-découpe (même sealed box que le texte si E2E), découpage en
fragments base64 (~32 Ko), manifeste + `N` fragments (`bundle_group`,
`fragment_offset`/`fragment_total`, `media_*`).

- Le manifeste crée l'incident **immédiatement** (texte trié, `photo_path`
  vide) ; le média s'attache quand le groupe est complet — dans le désordre,
  même si le manifeste arrive en dernier.
- Serveur : concatène → ouvre l'enveloppe si scellée → vérifie `sha256` →
  stocke (`reports/photos|audio/mesh-<groupe>.<ext>`) → attache au signalement.
- Fragments = bundles ordinaires : dédup, spray, ACK et relai inchangés.
  Seul le QR en est exclu (trop gros) — Nearby/WiFi/HTTP les transportent.

## Sécurité (v2 : E2E en place)

- Intégrité par `checksum` (immuables seuls), rejets si corrompu.
- `throttle` sur l'ingestion Laravel (60/min), validation stricte (`school_id` existe).
- Pas de PII dans le bundle (pas de nom/téléphone).
- **E2E** : enveloppe `sealed` (libsodium sealed box, anonyme — pas de PKI
  nœuds requise) vers la clé publique serveur (`GET /api/v1/mesh/key`).
  Les relais voient les métadonnées de routage, jamais le contenu.
  Menace couverte = relais curieux/compromis ; le serveur (destinataire
  légitime) déchiffre. Serveur compromis et métadonnées = hors modèle.
- Dégradation assumée : clé absente → 503 → clients en clair avec avertissement.
- **Signatures Ed25519 (V2, livré)** : `signature` = détachée 64 o., base64
  standard paddée → **88 car.** ; `node_pubkey` = publique 32 o., base64 →
  **44 car.**, auto-annoncée (TOFU). Octets signés : JSON compact, clés
  triées, UTF-8 brut (accents/slashs non échappés), nulls omis, 5 champs
  exclus {`checksum`, `hops`, `previous_node`, `copies_remaining`,
  `signature`} — `node_pubkey` **incluse** (lie contenu ↔ clé).
  Non-signés acceptés, signés-invalides rejetés (`bad_signature`) : relai
  (si lib Ed25519 dispo) + Laravel (upload direct seul — le relai reformate).
  Ordre émetteur : clé → signer → `checksum` (il couvre aussi la signature).
  TOFU honnête : clé stockée pour audit (`mesh_bundles.node_pubkey`, index
  origine+clé), **alerte de changement de clé non implémentée**.
  Réf. : TS `canonicalBytes`, Python `mesh_verify`, PHP `MeshSignature`.
- SMS : toujours en clair (feature phones) — allowlist + quotas + secret partagé.

## Roadmap

- [x] v1 : texte multi-sauts + QR + relai + ingestion Laravel.
- [x] v1.1 : alignement BPv7, spray binaire, quotas, ACK, canal SMS.
- [x] v2a : chiffrement E2E (sealed boxes NaCl, zéro crypto maison).
- [x] v2b : photos compressées + vocal court (fragments différés, E2E préservé).
- [x] v3 : appli Android Nearby, passerelle SMS, BLE GATT brut de secours (+ sélecteur auto).
- [x] app v1 : PWA `/m` installable offline (iPhone), binaire desktop, APK via CI.
- [x] app v2 : signatures Ed25519 (Phase 3), canal USSD, relai SQLite+metrics+retry,
  PWA (Background Sync, install prompt, états file), APK relai durci
  (boot, duty-cycle, SMS filtrée, tests unitaires).
