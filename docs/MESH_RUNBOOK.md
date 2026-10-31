# 📋 Runbook — relai mesh WASH-SENTINEL

Exploitation du relai store-and-forward (`mesh/server`, FastAPI, port 8001).
Contrat protocole : voir [mesh/README.md](../mesh/README.md) (formats et champs
immuables — ce runbook ne décrit que l'ops).

## 1. Démarrage

### Local (dev)

```bash
cd mesh/server
pip install -r requirements.txt
MESH_DB_PATH=./relay.db uvicorn main:app --host 0.0.0.0 --port 8001
```

Au boot, le relai recharge bundles + accusés depuis SQLite (`[relay] restore
sqlite : N bundles, M accusés`). Vérifier :

```bash
curl -s localhost:8001/health
# {"status":"healthy","service":"WASH Mesh Relay","stored":0,"peers_live":0}
```

### Docker Compose (prod)

Service `mesh-relay` (port `${FORWARD_MESH_PORT:-8001}` → 8001, healthcheck sur
`/health`). Persistance : monter un volume et pointer `MESH_DB_PATH` dessus,
sinon `relay.db` meurt avec le conteneur. Appliqué dans `compose.yaml`
(volume nommé `mesh-relay-data` sur `/data`, `MESH_DB_PATH=/data/relay.db`,
commit `mesh(compose)`) :

```yaml
# service mesh-relay :
    volumes:
      - 'mesh-relay-data:/data'
    environment:
      MESH_DB_PATH: /data/relay.db
# + volume racine :
volumes:
  mesh-relay-data:
```

Redémarrage sans perte : les bundles non expirés et les accusés de moins de
7 jours sont rechargés automatiquement (au-delà de `MESH_MAX_STORE`, seuls les
plus récents sont gardés, sémantique LRU).

## 2. Variables d'environnement

| Variable | Défaut | Effet |
|---|---|---|
| `MESH_DB_PATH` | `./relay.db` | Chemin SQLite (WAL). `:memory:` = sans persistance (tests) |
| `MESH_MAX_STORE` | `5000` | Plafond bundles en stock (éviction LRU au-delà) |
| `MESH_RELAY_API_KEY` | vide (public) | Si défini, `X-Mesh-Key` exigé sur `/v1/*` (`?key=` en WS). `/health` et `/metrics` restent ouverts |
| `LARAVEL_URL` | `http://laravel:8080` | Cible de l'uplink (`POST /api/v1/mesh/bundles`) |
| `MESH_INGEST_KEY` | vide | Clé envoyée à Laravel (`X-Mesh-Key`) |
| `MESH_UPLINK_RETRIES` | `3` | Retries par uplink (exceptions, 429, 5xx ; les autres 4xx ne sont pas rejouées) |
| `MESH_UPLINK_BACKOFF` | `0.5` | Base du backoff : `0.5 × 2^essai + jitter(0–0.5 s)` |
| `MESH_UPLINK_BREAKER_THRESHOLD` | `5` | Échecs consécutifs avant ouverture du disjoncteur |
| `MESH_UPLINK_BREAKER_COOLDOWN` | `60` | Secondes d'ouverture du disjoncteur (réponse `breaker_open`, stock conservé) |
| `FORWARD_MESH_PORT` | `8001` | Port hôte du relai (compose uniquement, `compose.yaml` — non lu par le relai lui-même) |
| `MESH_SEAL_SECRET` | vide | Côté Laravel (`backend/.env`) : secret sealed-box E2E ; vide = `GET /api/v1/mesh/key` en 503, clients en clair (avertis) |
| `VITE_SMS_GATEWAY_NUMBER` | vide | Côté frontend (`frontend/.env`) : n° passerelle SMS villageoise ; vide = secours SMS masqué dans l'app |

## 3. Seuils et quotas

Stockage et requêtes :

- `POST /v1/store` : ≤ 100 bundles par appel.
- `POST /v1/fetch` / `/v1/sync` : `known_ids` ≤ 5000, `limit` 1–200 (défaut 50).
- `POST /v1/ack` : ≤ 1000 ids par appel, tombstones capés à 20000, TTL 7 jours.
- Jamais de rejet par manque de place : à `MESH_MAX_STORE` atteint, le plus
  ancien bundle est évincé (`evicted_lru`).

Contenu bundle (rejeté → compteur `rejected`, jamais stocké) :

- `hop_count = len(hops) − 1` doit être ≤ `max_hops` (1–20).
- `priority` ∈ `normal` / `high` / `alert`.
- Tailles : `message` ≤ 5000, `hops` ≤ 21 entrées, `chunk` ≤ 65536 car.,
  `sealed` ≤ 20000 car., `media_size` ≤ 2 Mo.

Uplink : timeout 30 s par essai ; succès 2xx → tombstones + purge des confirmés.

## 4. Dépannage

### `rejected` qui monte (`/metrics` → `counters`, `/v1/stats`)

Trois causes, dans l'ordre de fréquence :

1. **Checksum invalide.** Le checksum couvre les champs immuables seuls
   (`checksum`, `hops`, `previous_node`, `copies_remaining` exclus), JSON à
   clés triées, compact, UTF-8 brut (`ensure_ascii=False`). Les deux écritures
   d'instant (`…Z` et `…+00:00`) sont acceptées. Vérifier côté émetteur :
   recalculer après chaque mutation d'un champ immuable, jamais après un
   changement de `hops`.
2. **`max_hops` dépassé** (`len(hops) − 1 > max_hops`) : boucle de routage ou
   `max_hops` trop bas à la création.
3. **`priority` hors enum** : seules `normal`, `high`, `alert` passent.

### `422 Unprocessable Entity` sur `/v1/store`

Validation Pydantic, pas un rejet métier : `bundle_id` doit être un UUID,
`created_at`/`expires_at` des datetimes ISO, `school_id` un entier, champs
requis présents, tailles (cf. §3) respectées. Le corps FastAPI (`detail`)
nomme le champ fautif — le relayer tel quel à l'émetteur.

### `401` sur `/v1/*`

`MESH_RELAY_API_KEY` est défini côté relai : fournir `X-Mesh-Key: <clé>`
(`?key=<clé>` pour le WebSocket). `/health` et `/metrics` restent publics.

### `breaker_open` sur `POST /v1/uplink`

Laravel injoignable (ou 5xx) `MESH_UPLINK_BREAKER_THRESHOLD` fois de suite :
le relai coupe les appels pendant `MESH_UPLINK_BREAKER_COOLDOWN` secondes et
garde le stock. Conduite : vérifier `LARAVEL_URL`, la connectivité réseau et
les logs Laravel ; `last_error` dans `/metrics` → `uplink` donne la dernière
cause. Reprise automatique après le cooldown (un succès referme le disjoncteur
et remet `failures` à 0).

### File uplink (`pending`) qui grandit

Causes : Laravel down (voir ci-dessus), `MESH_INGEST_KEY` invalide (4xx côté
Laravel, non rejouée — corriger la clé puis relancer l'uplink), ou uplink
jamais déclenché (le relai ne pousse pas tout seul : cron `POST /v1/uplink`).

### Base SQLite qui grossit

Bornée par construction : bundles ≤ `MESH_MAX_STORE`, purge TTL à chaque
lecture, accusés capés à 20000 + TTL 7 j, checkpoint WAL automatique
(1000 pages). Taille visible dans `/metrics` → `sqlite.bytes` (base + WAL
+ SHM cumulés). Si le FS est plein, le relai dégrade en mémoire
seule avec un log `[relay] sqlite …` sur stderr — traiter l'alerte disque,
puis redémarrer pour réactiver la persistance.

## 5. Commandes de sondage

```bash
R=http://localhost:8001
K=${MESH_RELAY_API_KEY:-}   # vide si relai public

curl -s $R/health | head -c 300; echo
curl -s $R/metrics | python3 -m json.tool | head -40
curl -s -H "X-Mesh-Key: $K" $R/v1/stats
curl -s -X POST -H "X-Mesh-Key: $K" -H 'Content-Type: application/json' \
  $R/v1/fetch -d '{"node_id":"ops","known_ids":[],"limit":5}'  # tire le stock
curl -s -X POST -H "X-Mesh-Key: $K" "$R/v1/uplink?dry_run=true"  # file sans vider
curl -s -X POST -H "X-Mesh-Key: $K" $R/v1/uplink                  # pousse vers Laravel

# Stress : 50 bundles + 5 doublons + 2 invalides, rapport chiffré
python3 mesh/demo/simulate_hops.py --burst 50
# Démo A → B → C (inchangée)
python3 mesh/demo/simulate_hops.py
python3 mesh/demo/simulate_hops.py --live   # nécessite relai + Laravel locaux

# Tests relai : 18 relai + 12 ops + 13 signatures = 43 (sqlite sur fichiers tmp)
cd mesh/server && MESH_DB_PATH=/tmp/relay-test.db python -m pytest . -q
```

Seuils d'alerte conseillés : `uptime_seconds` qui retombe à 0 (restart),
`uplink.failures > 0` persistant, `breaker_opens` qui augmente, `rejected`
qui croît brutalement (émetteur cassé), `sqlite.bytes` proche du quota FS.
