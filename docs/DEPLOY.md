# WASH Sentinel — Guide de déploiement production

> FR · honnête et vérifié : chaque affirmation technique renvoie à sa source
> (`fichier:ligne`). Ce qui est estimé est marqué **« indicatif Cameroun 2026 »**.
> Docs voisines : [INSTALL.md](INSTALL.md) (terrain) · [WHATSAPP_LIVE.md](WHATSAPP_LIVE.md)
> (mise en live WhatsApp) · [USSD.md](USSD.md) (canal USSD) · [MESH_RUNBOOK.md](MESH_RUNBOOK.md)
> (exploitation du relai mesh).

## 0. Ce que ce guide suppose (lire d'abord)

- Le repo tourne en local via `./start.sh` (cf. [start.sh](../start.sh), [README.md](../README.md)).
- La pile compte **7 services** (`compose.yaml:3-172`) : `laravel` (API, conteneur `:8080`,
  exposé sur `${APP_PORT:-80}`), `queue` (worker), `pgsql`, `ai-engine` (`:8000`),
  `ollama` (`:11434`), `mesh-relay` (`:8001`), `frontend` (dev `vite`, `:5173`).
- **Point d'honnêteté n° 1** : le service `frontend` de `compose.yaml:157-172` lance
  `npm run dev` (serveur de dev). En production, on **ne l'expose pas** : on build
  (`npm run build`, cf. [frontend/package.json](../frontend/package.json)) et on sert
  `frontend/dist/` en statique derrière Caddy (§ 2, § 5).
- **Point d'honnêteté n° 2** : aucun scheduler Laravel n'est défini
  (`backend/routes/console.php` ne contient que `inspire`, aucun `schedule()` dans
  `backend/app`). Il n'y a donc **pas** de `schedule:work` à faire tourner aujourd'hui.
  Le seul cron nécessaire est la poussée d'uplink du relai mesh (§ 4).

## 1. Prérequis

### 1.1 VPS

| Besoin | Recommandation |
|---|---|
| OS | Ubuntu 24.04 LTS, Docker + plugin Compose (vérifiés par [start.sh:8-20](../start.sh)) |
| CPU / disque | 2 vCPU, 40 Go SSD min (les modèles Ollama pèsent plusieurs Go) |
| RAM **avec LLM local** | **8 Go min** : `llama3.2:3b` (~2 Go) + `nomic-embed-text` + vision `11b` optionnelle (`compose.yaml:80-82`), + PostgreSQL + PHP + `ai-engine` |
| RAM **avec LLM cloud** | **2 Go min** : profils API externes créés depuis la page Réglages IA, sans Ollama local ([README.md § 8](../README.md), `frontend/src/pages/SettingsPage.tsx`) ; ne pas `pull` les modèles, voire arrêter le service `ollama` |

Le « ~5 €/mois, 2 Go » n'est donc viable **qu'en profil cloud** (ou IA dégradée en
règles déterministes, cf. [README.md § 12](../README.md)). Avec Ollama local, viser
l'offre 8 Go du même hébergeur.

### 1.2 Domaine + DNS + ports

- Un domaine (ex. `sentinel.example.cm`) avec enregistrements **A** (IPv4) et,
  si le VPS a de l'IPv6, **AAAA** vers l'IP du serveur. Propagation : 5 min à 48 h.
- Ouvrir **80/TCP** (ACME + redirect) et **443/TCP** (HTTPS). Tout le reste
  (PostgreSQL, Ollama, ai-engine, dev frontend) reste **non exposé** : en prod,
  ne publier sur l'hôte que ce que Caddy consomme, ou binder sur `127.0.0.1`.

## 2. HTTPS : Caddy devant `laravel:8080` + `mesh-relay:8001`

### 2.1 Pourquoi HTTPS est obligatoire (pas optionnel)

1. **PWA installable** : le service worker (`vite-plugin-pwa`,
   [frontend/vite.config.ts](../frontend/vite.config.ts)) et l'installation
   (« Sur l'écran d'accueil », [INSTALL.md § 1](INSTALL.md)) exigent un contexte
   sécurisé. Sans HTTPS, pas d'app terrain offline sur iPhone/Android.
2. **Webhooks Meta** : « Meta exige une URL **publique en HTTPS** »
   ([WHATSAPP_LIVE.md § 4](WHATSAPP_LIVE.md)). Sans HTTPS, pas de WhatsApp live.
3. **Callbacks USSD** : l'opérateur/la passerelle appelle `POST /api/v1/mesh/ussd`
   en continu ([USSD.md § 1](USSD.md)) ; en HTTP, sessions et contenus transitent
   en clair — et la plupart des agrégateurs refusent le HTTP.

### 2.2 Caddy en 8ᵉ service (recommandé, Let's Encrypt auto)

Créer `compose.override.yml` (non versionné, à côté de `compose.yaml`) :

```yaml
services:
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - ./frontend/dist:/srv/frontend:ro
    networks:
      - wash-network
    depends_on:
      - laravel
      - mesh-relay

volumes:
  caddy-data:
```

`Caddyfile` (adapter le domaine ; Caddy obtient et renouvelle le certificat seul) :

```caddy
# Console + API + PWA : MÊME domaine (cookies, /api, /m)
sentinel.example.cm {
	handle /api/* {
		reverse_proxy laravel:8080
	}
	handle {
		root * /srv/frontend
		try_files {path} /index.html
		file_server
	}
}

# Relai mesh pour les APK villageois (endpoints /v1/*, /health, /metrics)
relay.sentinel.example.cm {
	reverse_proxy mesh-relay:8001
}
```

Conséquences à appliquer avec (§ 3) :

- `APP_PORT` ne doit plus utiliser le 80 de l'hôte (Caddy l'occupe) : mettre
  `APP_PORT=127.0.0.1:8080` dans `.env` racine, ou retirer le `ports:` de `laravel`.
- `APP_URL=https://sentinel.example.cm` dans `backend/.env`.
- `VITE_API_URL=https://sentinel.example.cm/api`, puis **rebuild** du frontend
  (`npm run build` dans `frontend/`, sortie `dist/`, cf. [frontend/package.json](../frontend/package.json)).
- Webhook Meta prod : `https://sentinel.example.cm/api/v1/whatsapp/webhook`
  (remplace le tunnel du [WHATSAPP_LIVE.md § 4](WHATSAPP_LIVE.md)).
- L'APK villageoise pointera `RELAY_URL=https://relay.sentinel.example.cm` (§ 5).

## 3. Variables et secrets — checklist exhaustive

### 3.1 `.env` racine (Compose — cf. [compose.yaml](../compose.yaml), [.env.example](../.env.example))

| Variable | Rôle (source) | Valeur prod |
|---|---|---|
| `APP_PORT` | Port hôte → `laravel:8080` (`compose.yaml:8`) | `127.0.0.1:8080` (Caddy devant) |
| `FORWARD_DB_PORT` | Port hôte → `pgsql:5432` (`compose.yaml:56`) | **Ne pas exposer** (retirer ou `127.0.0.1:5432`) |
| `FORWARD_AI_PORT` | Port hôte → `ai-engine:8000` (`compose.yaml:77`) | **Ne pas exposer** |
| `FORWARD_OLLAMA_PORT` | Port hôte → `ollama:11434` (`compose.yaml:108`) | **Ne pas exposer** |
| `FORWARD_MESH_PORT` | Port hôte → `mesh-relay:8001` (`compose.yaml:134`) | `127.0.0.1:8001` (Caddy devant). **Absent du `.env` actuel** (défaut `8001` public) : à ajouter |
| `FRONTEND_PORT` | Dev vite (`compose.yaml:163`) | Inutilisé en prod (frontend servi buildé, § 2) |
| `VITE_API_URL` | URL API vue par le navigateur (`compose.yaml:165`) | `https://sentinel.example.cm/api` |
| `DB_DATABASE` / `DB_USERNAME` / `DB_PASSWORD` | PostgreSQL (`compose.yaml:15-17,58-60`) | `wash_sentinel` / `sentinel_user` / **mot de passe fort généré** (remplace `secret_sentinel`) |
| `OLLAMA_MODEL` / `OLLAMA_EMBED_MODEL` / `OLLAMA_VISION_MODEL` / `OLLAMA_URL` / `STT_DRIVER` | Moteur IA (`compose.yaml:79-83`, [backend/.env.example](../backend/.env.example)) | Défauts OK ; ne `pull` que le nécessaire (§ 1.1) |
| `MESH_INGEST_KEY` | Clé relai → Laravel, header `X-Mesh-Key` (`compose.yaml:137`, `backend/config/services.php:46`) | **Générer** (aléatoire ≥ 32 car.). Vide = ingestion publique (dev uniquement) |
| `MESH_RELAY_API_KEY` | Clé exigée sur `/v1/*` du relai (`compose.yaml:138`, [MESH_RUNBOOK.md § 2](MESH_RUNBOOK.md)) | **Générer** (≠ précédente). Vide = relai public |

> Constat honnête : `.env` et `.env.example` actuels ne définissent ni
> `MESH_INGEST_KEY` ni `MESH_RELAY_API_KEY` (défaut vide = public). En prod,
> les deux sont obligatoires, et l'APK reprend la clé relai (§ 5).

### 3.2 `backend/.env` (Laravel — cf. [backend/.env.example](../backend/.env.example))

Copier depuis l'exemple si absent (`start.sh:23` le fait en dev), puis positionner :

| Variable | Rôle (source) | Valeur prod |
|---|---|---|
| `APP_ENV` / `APP_DEBUG` | Mode (`backend/.env.example:2-4`) | `production` / `false` (**jamais `true` en prod**) |
| `APP_URL` | URL canonique (`backend/.env.example:5`) | `https://sentinel.example.cm` |
| `APP_KEY` | Chiffrement (cookies, clés API IA en base) | Générer (§ 3.4). Vide dans l'exemple |
| `DB_*` | Doivent **égaler** le `.env` racine (`compose.yaml:15-17`) | Idem § 3.1 |
| `QUEUE_CONNECTION` | File (`backend/.env.example:38`, `config/queue.php:16`) | `database` (défaut, consommée par le service `queue`) |
| `AI_ENGINE_URL` / `AI_ENGINE_TIMEOUT` | Moteur IA (`config/services.php:38-41`) | `http://ai-engine:8000` / `120` |
| `MESH_SEAL_SECRET` | Clé E2E sealed-box (`config/services.php:58`) | Sortie de `mesh:key-generate` (§ 3.4). Vide = E2E désactivé, clients en clair (avertis) |
| `MESH_INGEST_KEY` | **Doit égaler** le `.env` racine (`config/services.php:46`) | Idem § 3.1 |
| `MESH_SMS_SECRET` | Secret SMSSync, fail-closed si vide (`config/services.php:48`, `WashSmsController.php:34-39`) | **Générer** (≠ `change-moi-passerelle-sms`) |
| `MESH_SMS_ALLOWLIST` | CSV expéditeurs autorisés (`config/services.php:50`) | Numéros des téléphones passerelle, ou vide (ouvert) |
| `MESH_DAILY_CAP_PER_ORIGIN` / `MESH_SMS_QUOTA_PER_SENDER` | Quotas (`config/services.php:52-54`) | Défauts `500` / `10` OK |
| `WHATSAPP_*` (6 vars) | Cloud API Meta (`config/services.php:61-68`) | Cf. [WHATSAPP_LIVE.md § 3](WHATSAPP_LIVE.md) ; `WHATSAPP_SIMULATOR=false` en live |

### 3.3 `frontend/.env` (build-time Vite — cf. [frontend/.env.example](../frontend/.env.example))

| Variable | Rôle (source) | Valeur prod |
|---|---|---|
| `VITE_API_URL` | Base API du navigateur (`frontend/src/lib/api.ts:157`, `mesh.ts:29`) | `https://sentinel.example.cm/api` |
| `VITE_SMS_GATEWAY_NUMBER` | N° passerelle SMS (`frontend/src/lib/mesh.ts:32`, `MeshFieldPage.tsx:491`) | N° villageois au format `+2376XXXXXXXX`, ou vide (= secours SMS masqué) |

Attention : ces valeurs sont **figées au build** (`npm run build`). Tout changement
d'URL impose un rebuild + redéploiement de `dist/`.

### 3.4 Commandes (existence vérifiée)

```bash
# 1. Clé applicative (built-in Laravel ; start.sh:48 l'utilise déjà)
docker compose exec -T laravel php artisan key:generate --force

# 2. Migrations (built-in Laravel ; start.sh:62)
docker compose exec -T -u www-data laravel php artisan migrate --force

# 3. Seeders initiaux (rôles, écoles démo, profils IA ; start.sh:63)
#    Prod réelle : préférer un seed minimal, puis changer TOUS les mots de passe
#    (les comptes démo admin@wash.cm / tech@wash.cm / directeur@ecole.cm ont pour
#    mot de passe « password », backend/database/seeders/WashDemoSeeder.php:19-28).
docker compose exec -T -u www-data laravel php artisan db:seed --force

# 4. Clé E2E mesh (commande projet, backend/app/Console/Commands/MeshKeyGenerate.php:9)
docker compose exec -T -u www-data laravel php artisan mesh:key-generate
# → copier MESH_SEAL_SECRET dans backend/.env, puis redémarrer :
docker compose up -d laravel queue
```

## 4. Queue worker, cron uplink, backups

### 4.1 Worker `queue` (vérifié)

Le service `queue` existe (`compose.yaml:29-50`) : même image PHP, commande
`php artisan queue:work --sleep=3 --tries=3 --timeout=120` (`compose.yaml:32`),
file `database` (`config/queue.php:16-45`). Il traite les jobs WhatsApp
(`ProcessWhatsAppMessage`, cf. [WHATSAPP_LIVE.md § 0](WHATSAPP_LIVE.md)).

```bash
docker compose ps queue                    # doit être Up
docker compose logs --tail=20 queue        # activité du worker
# Après modif de backend/.env : le worker met ~60 s à recharger, ou forcer :
docker compose exec -T queue php artisan queue:restart   # cf. WHATSAPP_LIVE.md § 3
# File en échec :
docker compose exec -T -u www-data laravel php artisan queue:failed | tail -5
```

### 4.2 Cron uplink mesh (le seul cron nécessaire)

Le relai **ne pousse pas tout seul** vers Laravel ([MESH_RUNBOOK.md § dépannage](MESH_RUNBOOK.md)).
Sur l'hôte, toutes les 5 min (HTTPS prod) :

```bash
*/5 * * * * curl -sf -X POST -H "X-Mesh-Key: ${MESH_RELAY_API_KEY}" \
  https://relay.sentinel.example.cm/v1/uplink >/dev/null || \
  echo "uplink mesh en échec $(date)" | systemd-cat -t wash-mesh
```

Sondes utiles : `/health` (public), `/metrics` → `uplink.failures`, `breaker_opens`,
`rejected`, `sqlite.bytes` ([MESH_RUNBOOK.md § 5](MESH_RUNBOOK.md)).

### 4.3 Backups (noms de volumes vérifiés via `docker compose config`)

Volumes persistants (`compose.yaml:178-186`) et leurs noms Docker réels :

| Volume compose | Nom Docker réel | Contenu |
|---|---|---|
| `wash-pgsql` | `wash-sentinel_wash-pgsql` | Base Laravel (écoles, incidents, jobs, profils IA) |
| `mesh-relay-data` | `wash-sentinel_mesh-relay-data` | `/data/relay.db` du relai (`compose.yaml:139,145`) |
| `wash-ollama` | `wash-sentinel_wash-ollama` | Modèles pullés (re-téléchargeables, backup optionnel) |
| `wash-frontend-modules` | `wash-sentinel_wash-frontend-modules` | `node_modules` (jetable, **pas** de backup) |

```bash
mkdir -p /srv/backups/wash && cd /home/haro/projects/WASH-SENTINEL  # adapter le chemin prod

# Base Laravel (cohérent, à chaud)
docker compose exec -T pgsql pg_dump -U "${DB_USERNAME:-sentinel_user}" \
  -d "${DB_DATABASE:-wash_sentinel}" | gzip > /srv/backups/wash/pgsql-$(date +%F).sql.gz

# relay.db du relai mesh (fichier SQLite, snapshot du volume à froid relatif)
docker run --rm -v wash-sentinel_mesh-relay-data:/data:ro \
  -v /srv/backups/wash:/backup alpine \
  tar czf /backup/mesh-relay-data-$(date +%F).tgz -C /data .

# Restauration PostgreSQL :
gunzip -c /srv/backups/wash/pgsql-AAAA-MM-JJ.sql.gz | \
  docker compose exec -T pgsql psql -U "${DB_USERNAME:-sentinel_user}" \
  -d "${DB_DATABASE:-wash_sentinel}"

# Restauration relay.db (service arrêté pour éviter d'écrire dans SQLite) :
docker compose stop mesh-relay
docker run --rm -v wash-sentinel_mesh-relay-data:/data \
  -v /srv/backups/wash:/backup alpine \
  sh -c "rm -f /data/relay.db* && tar xzf /backup/mesh-relay-data-AAAA-MM-JJ.tgz -C /data"
docker compose up -d mesh-relay
```

Automatiser en cron quotidien + copier hors-serveur (le VPS seul n'est pas un backup).

## 5. Mobiles : APK + PWA

### 5.1 Build APK prod (propriétés vérifiées)

Config compile-time dans `mesh/android/gradle.properties:7-16`, injectée en
`BuildConfig` (`mesh/android/app/build.gradle:17-22`) :

| Propriété | BuildConfig | Valeur prod |
|---|---|---|
| `LARAVEL_API_URL` | `LARAVEL_API_URL` | `https://sentinel.example.cm/api` |
| `RELAY_URL` | `RELAY_URL` | `https://relay.sentinel.example.cm` |
| `MESH_RELAY_KEY` | `MESH_KEY` | = `MESH_RELAY_API_KEY` serveur (ou `MESH_INGEST_KEY` pour l'upload direct, cf. [mesh/android/README.md](../mesh/android/README.md)) |
| `MESH_SMS_SECRET` | `SMS_SECRET` | = `MESH_SMS_SECRET` backend |
| `MESH_SMS_ALLOWLIST` | `SMS_ALLOWLIST` | Idem backend (ou vide) |
| `MESH_SMS_QUOTA_PER_SENDER` | `SMS_QUOTA` | `10` (défaut, = backend) |

```bash
cd mesh/android
gradle wrapper              # une fois (gradlew non versionné)
./gradlew :app:assembleRelease
# → app/build/outputs/apk/release/app-release.apk (NON SIGNÉ, voir § 5.2)
```

> **Écran Paramètres in-app** : l'APK a un écran `Paramètres` (`SettingsActivity`,
> prefs `FieldSettings`) qui surcharge les 6 valeurs ci-dessus sans recompiler
> (champ vide = valeur compilée). Le build prod reste la source des défauts ;
> une rotation de secret en urgence passe par l'écran, puis par un rebuild
> pour figer les nouvelles valeurs. (La page Réglages du frontend ne gère,
> elle, que les profils LLM/STT — `SettingsPage.tsx`.)

### 5.2 Distribution : Play Store vs sideload

|  | Sideload (recommandé terrain) | Play Store |
|---|---|---|
| Prérequis | Aucun (cf. [INSTALL.md § 3](INSTALL.md)) | Compte dev payant, **App Bundle signé** (aucun `signingConfig` dans `app/build.gradle` aujourd'hui), fiche store, review Google |
| MàJ | Manuelle (renvoyer l'APK) | Auto |
| Adapté à | Flotte villageoise connue, offline | Grand public |

En pratique pilote : **sideload**. Signer quand même l'APK release avec une clé
dédiée conservée hors repo (sinon Android refuse les mises à jour).

### 5.3 PWA = même domaine, build statique

La PWA est la page `/m` (`start_url: '/m'`, [frontend/vite.config.ts](../frontend/vite.config.ts)),
publique et offline-first ([INSTALL.md](INSTALL.md)). En prod : la servir depuis
`frontend/dist/` **derrière le même domaine** que l'API (§ 2.2) — pas de CORS,
pas de second certificat, webhooks inchangés. Rappel : la première visite est
forcément en ligne ([INSTALL.md § 5](INSTALL.md)).

## 6. Opérateurs : USSD, SMS, WhatsApp

### 6.1 USSD — code à négocier, callback prête

- Endpoint vérifié : `POST /api/v1/mesh/ussd` (+ `GET` sonde),
  `backend/routes/api.php:87-88`, throttle 60/min, contrôleur
  `WashUssdController` (session 10 min, `WashUssdController.php:35`).
- Le `*123#` de la doc est **fictif** ([USSD.md § 4](USSD.md)) : négocier un vrai
  code auprès de l'opérateur/agrégateur (MTN, Orange, Camtel) et déclarer le callback :
  `POST https://sentinel.example.cm/api/v1/mesh/ussd` (format passerelle style
  Africa's Talking : `sessionId`, `serviceCode`, `phoneNumber`, `text`, [USSD.md § 1](USSD.md)).
- Sécurité : **pas de secret partagé ni allowlist sur l'USSD** ([USSD.md § 4](USSD.md)) —
  restreindre par IP côté Caddy (`remote_ip` matcher avec les IP de la passerelle).
- Vie privée : le numéro n'est jamais persisté (empreinte `sha256` tronquée,
  [USSD.md § 5](USSD.md)) — argument pour la convention opérateur.

### 6.2 SMS — téléphone passerelle + forfait data

- Principe vérifié : un Android villageois (APK § 5, `SmsGatewayWorker`) POSTe
  chaque SMS reçu vers `POST /api/v1/mesh/sms` (`WashSmsController.php:14-22`)
  dès qu'une data intermittente revient ([mesh/android/README.md § notes](../mesh/android/README.md)).
- Grammaire à diffuser : `WASH <CODE> <TYPE> [détail]`, types `P/L/E/H`
  (pompe/latrine/eau/hygiène, `frontend/src/lib/mesh.ts:49-53`).
- Matériel : **2 téléphones relais par zone (MTN + Orange) + charge solaire**
  ([mesh/android/README.md § notes](../mesh/android/README.md)) ; forfait data minimal
  par passerelle (quelques Mo/mois suffisent : que des POST JSON).
- Numéro à diffuser : le(s) numéro(s) des téléphones passerelle, et renseigner
  `VITE_SMS_GATEWAY_NUMBER` (§ 3.3) pour le bouton SMS pré-rempli de la PWA.
- Sécurité : `MESH_SMS_SECRET` obligatoire (fail-closed, `WashSmsController.php:34-39`)
  + `MESH_SMS_ALLOWLIST` si la flotte est connue.

### 6.3 WhatsApp — renvoi au runbook live

Procédure complète : [WHATSAPP_LIVE.md](WHATSAPP_LIVE.md) (création App Meta,
tokens, déclaration webhook, abonnement `messages`, simulation, rollback).
En prod, seule différence avec le runbook : remplacer le tunnel ngrok/cloudflared
par `https://sentinel.example.cm/api/v1/whatsapp/webhook`, et passer
`WHATSAPP_SIMULATOR=false` avec un vrai `WHATSAPP_APP_SECRET`.

## 7. Coûts, formation, boucle retour

### 7.1 Coûts mensuels estimés — **« indicatif Cameroun 2026 »**

| Poste | Fourchette mensuelle | Notes |
|---|---|---|
| VPS 2 Go (LLM cloud) | ~5 € (~3 300 FCFA) | § 1.1 ; 8 Go si Ollama local (~12-20 €) |
| Domaine `.cm` | ~1-2 € (~500-1 000 FCFA, amorti/an) | `.com` moins cher, `.cm` plus crédible localement |
| Forfaits data passerelles SMS (2 SIM) | ~3-8 € (~2 000-5 000 FCFA) | Trafic = POST JSON, quelques Mo |
| SMS émis (dépannage usagers) | ~0-5 € | Réception gratuite en général ; coût côté émetteur villageois |
| Code USSD / reversement opérateur | **variable, devis requis** | Négociation MTN/Orange/Camtel, souvent le poste dominant |
| WhatsApp Cloud API | 0 € (conversations utilitaires, volume pilote) | Facturation Meta au-delà des quotas gratuits |
| **Total pilote (hors USSD)** | **~10-20 €/mois (~6 500-13 000 FCFA)** | L'USSD reste l'inconnue budgétaire |

### 7.2 Formation terrain (demi-journée par zone)

Support : **fiche 1 page** (recto PWA/APK + QR, verso SMS/USSD) + **démo QR live** :

1. Montrer le cycle offline prouvé par [INSTALL.md § 4](INSTALL.md) : saisir dans
   la file locale → bouton **QR** → le voisin scanne → upload dès que ça capte.
2. Faire scanner un vrai QR entre deux téléphones (transfert A → B, `MeshPage`
   démo `/mesh` en salle, terrain réel sur `/m`).
3. Faire envoyer un SMS `WASH <CODE> P <détail>` et parcourir une fois les menus
   USSD (exemples curl rejouables dans [USSD.md § 3](USSD.md)).
4. Laisser la fiche + le numéro passerelle affiché à l'école.

### 7.3 Boucle retour écoles

- Chaque signalement reçoit un **ticket** (`END Merci! Ticket: <ref>` en USSD,
  accusé WhatsApp `WS-…`, cf. [USSD.md § 2](USSD.md), [WHATSAPP_LIVE.md § 7](WHATSAPP_LIVE.md)) :
  former les directeurs à le conserver et à le rappeler en cas de relance.
- Le technicien qui clôture explique le motif (visible dans la console incidents)
  ; le coordinateur fait une **tournée mensuelle** avec les stats
  (`GET /api/v1/mesh/stats`, `backend/routes/api.php:92`) imprimées par école.
- Remonter les frictions (menus USSD, grammaire SMS, pages PWA) au fil des
  tournées : ce sont elles qui fixent les priorités des versions suivantes.

## 8. Rollback

### 8.1 Retour code (git + compose)

```bash
cd /home/haro/projects/WASH-SENTINEL   # adapter le chemin prod
git log --oneline -5                   # repérer le commit sain
git stash -u 2>/dev/null; git checkout <commit-sain> -- .  # ou : git revert
docker compose up -d --build
docker compose exec -T -u www-data laravel php artisan migrate --force
docker compose ps                        # tout Up ?
curl -sf https://sentinel.example.cm/api/up               # health Laravel
curl -sf https://relay.sentinel.example.cm/health          # health relai
```

### 8.2 Restauration volumes (noms vérifiés § 4.3)

```bash
# PostgreSQL (à chaud, dump § 4.3)
gunzip -c /srv/backups/wash/pgsql-AAAA-MM-JJ.sql.gz | \
  docker compose exec -T pgsql psql -U "${DB_USERNAME:-sentinel_user}" \
  -d "${DB_DATABASE:-wash_sentinel}"

# relay.db (relai stoppé, § 4.3)
docker compose stop mesh-relay
docker run --rm -v wash-sentinel_mesh-relay-data:/data \
  -v /srv/backups/wash:/backup alpine \
  sh -c "rm -f /data/relay.db* && tar xzf /backup/mesh-relay-data-AAAA-MM-JJ.tgz -C /data"
docker compose up -d mesh-relay

# Cas extrême (tout raser, DONNÉES PERDUES — cf. stop.sh --volumes) :
# docker compose down -v   # supprime wash-pgsql, mesh-relay-data, wash-ollama
```

### 8.3 Rollback WhatsApp seul (< 2 min, sans toucher la pile)

Voir [WHATSAPP_LIVE.md § 10](WHATSAPP_LIVE.md) : supprimer l'abonnement `messages`
côté Meta, éventuellement `WHATSAPP_SIMULATOR=true` + `queue:restart`.

## 9. Checklist de mise en route (ordre exact)

- [ ] VPS + domaine + DNS (A/AAAA) + 80/443 ouverts (§ 1).
- [ ] `.env` racine : `APP_PORT`, ports non exposés, `DB_PASSWORD` fort,
      `MESH_INGEST_KEY` + `MESH_RELAY_API_KEY` générées (§ 3.1).
- [ ] `backend/.env` : `APP_ENV=production`, `APP_DEBUG=false`,
      `APP_URL=https://…`, `DB_*` alignés, `MESH_*` alignés, `WHATSAPP_*` (§ 3.2).
- [ ] `frontend/.env` : `VITE_API_URL=https://…/api`, `VITE_SMS_GATEWAY_NUMBER`,
      puis `npm run build` (§ 3.3).
- [ ] `Caddyfile` + `compose.override.yml`, `docker compose up -d --build` (§ 2.2).
- [ ] `key:generate`, `migrate --force`, `db:seed --force` (mots de passe démo
      changés aussitôt), `mesh:key-generate` + redémarrage (§ 3.4).
- [ ] Vérifier : `/api/up`, `/api/v1/wash/overview`, relai `/health`,
      `queue` Up, `curl` handshake WhatsApp GET (§ 4, [WHATSAPP_LIVE.md § 4](WHATSAPP_LIVE.md)).
- [ ] Cron uplink mesh + cron backups quotidiens (§ 4.2, § 4.3).
- [ ] APK prod buildée (`gradle.properties` HTTPS) et diffusée en sideload (§ 5).
- [ ] PWA `/m` installée sur un téléphone test depuis le domaine HTTPS (§ 5.3).
- [ ] SMS : passerelles en place, `MESH_SMS_SECRET` aligné APK ↔ backend, grammaire
      diffusée (§ 6.2). USSD : code négocié, callback déclarée, restriction IP (§ 6.1).
- [ ] WhatsApp : webhook prod déclaré, abonnement `messages`, test réel (§ 6.3).
- [ ] Formation : fiche 1 page imprimée, démo QR faite, numéros affichés (§ 7.2).
