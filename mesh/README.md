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

Côté Laravel : `mesh_bundles` (migration + modèle) et `WashMeshController`
(`POST /api/v1/mesh/bundles`, `GET /api/v1/mesh/stats`…).

## Format du bundle (v1)

Compact (~1 Ko en texte), sérialisable en QR :

```json
{
  "v": 1,
  "bundle_id": "uuidv4",
  "origin_node_id": "node-abc123",
  "school_id": 12,
  "school_code": "CM-LT-0042",
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
- Photos/vocal : **différés** (v1 = texte seul sur le mesh ; médias uploadés par le nœud
  connecté s'il les reçoit en local — voir roadmap).

## Transports (du plus rustique au plus fluide)

| # | Transport | Quand l'utiliser | Implémentation |
|---|-----------|------------------|----------------|
| 1 | **QR code** | Marche toujours, même sans Bluetooth | `sdk.serializeForQR()` → string base64url à afficher/scanner |
| 2 | **Sync locale** | Même WiFi village / hotspot / câble | `POST mesh-relay/v1/sync` : échange bidirectionnel en 1 appel |
| 3 | **WebSocket** | Deux nœuds en ligne en même temps | `WS mesh-relay/v1/ws/{node_id}` : push temps réel |
| 4 | **Upload final** | Premier nœud avec internet | `POST laravel/api/v1/mesh/bundles` (batch, dédupliqué) |

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
- `fragment_offset` / `fragment_total`, `custody_requested`, `signature`
  (réservé Phase 3, Ed25519).

Serveur : clé optionnelle `X-Mesh-Key` (`MESH_INGEST_KEY` / `MESH_RELAY_API_KEY`,
vide = public + throttle + quotas), quota journalier par origine (défaut 500),
éviction LRU sur le relai, compteurs par cause dans `/v1/stats`, logs
`mesh.bundle.*` tracés par `bundle_id`.

Canal SMS : `WASH <CODE_ECOLE> <TYPE> [détail]` (`P`/`L`/`E`/`H`) via
`POST /api/v1/mesh/sms` (secret partagé SMSSync, allowlist, quota/expéditeur).
Le SMS devient un bundle `sms:<numéro>` puis suit le triage standard.

## Sécurité (v1 pragmatique)

- Intégrité par `checksum`, rejets si corrompu.
- `throttle` sur l'ingestion Laravel (60/min), validation stricte (`school_id` existe).
- Pas de PII dans le bundle (pas de nom/téléphone en v1).
- ⚠️ V1 = **non chiffré** (payload lisible par les relais, comme un SMS).
  V2 prévue : chiffrement E2E X25519 vers la clé publique du serveur.

## Roadmap

- [ ] v1 : texte multi-sauts + QR + relai + ingestion Laravel (ce PR).
- [ ] v2 : chiffrement E2E + photos compressées différées + vocal court.
- [ ] v3 : transport Bluetooth LE / WiFi Direct natif (app mobile), SMS fallback via gateway.
