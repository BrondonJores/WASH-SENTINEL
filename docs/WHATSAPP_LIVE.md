# WASH Sentinel — Mise en live WhatsApp (runbook hackathon Meta)

> Objectif : brancher le webhook WhatsApp Cloud API de Meta sur notre backend
> pour recevoir de vrais messages et créer de vrais incidents.
> Toutes les valeurs sensibles ci-dessous sont **fictives** : ne jamais
> commiter de vrais secrets (ni ici, ni ailleurs dans le repo).

État du code au 2026-10-31 : le webhook **existe déjà et est testé**
(voir § 0). Ce runbook décrit uniquement le branchement Meta → tunnel → backend.

---

## 0. Ce qui existe déjà (ne pas réimplémenter)

| Élément | Emplacement | État |
|---|---|---|
| Vérification GET (handshake Meta) | `GET /api/v1/whatsapp/webhook` (`WashWhatsAppController::verify`) | ✅ `hub.mode` / `hub.verify_token` / `hub.challenge`, comparaison `hash_equals` contre `WHATSAPP_VERIFY_TOKEN` |
| Réception POST | `POST /api/v1/whatsapp/webhook` (`WashWhatsAppController::receive`, throttle 60/min) | ✅ vérifie `X-Hub-Signature-256` (HMAC app secret), sauf si `WHATSAPP_SIMULATOR=true` |
| Parsing Meta | `MetaWhatsAppService::parseWebhook` | ✅ texte, audio, image (+légende) ; autres types ignorés |
| Réponses sortantes | `MetaWhatsAppService::sendText` via Graph API `v21.0` | ✅ accusé de réception après triage |
| Triage | `WashWhatsAppService` → `IncidentTriageService::ingest(..., source='whatsapp')` | ✅ texte→canal `text`, audio→canal `voice`, image→canal `photo` ; numéros inconnus reçoivent un message d'enregistrement |
| Traitement asynchrone | `ProcessWhatsAppMessage` (job `ShouldQueue`) + service compose `queue` (`queue:work`) | ✅ le POST répond `{"received":true}` immédiatement |
| Tests | `backend/tests/Feature/WashWhatsAppTest.php` (6 tests) | ✅ verts |

URL de callback exacte de notre projet (à déclarer chez Meta, § 5) :

```text
https://<TON-TUNNEL>/api/v1/whatsapp/webhook
```

Exemple : `https://faucon-rapide-42.ngrok-free.app/api/v1/whatsapp/webhook`

---

## 1. Créer l'App Meta et le numéro de test

1. Aller sur [Meta for Developers](https://developers.facebook.com/) → **Mes applis** → **Créer une application** → cas d'usage **Autre** → type **Business**.
2. Dans le tableau de bord de l'app : **Ajouter un produit** → **WhatsApp** → **Configurer**.
3. Dans **WhatsApp → Démarrage rapide** :
   - noter le **`phone_number_id`** du numéro de test (ex. fictif `109876543210987`) et le numéro affiché (ex. `+1 555 010 2030`) ;
   - ajouter ton vrai numéro mobile dans **À** (destinataires autorisés) et valider le code reçu par WhatsApp.

## 2. Générer le token d'accès

- **Démo courte (< 24 h)** : dans **WhatsApp → Démarrage rapide**, copier le **jeton temporaire** (ex. fictif `EAAJk...XyZ`, 24 h).
- **Démo longue / robuste** : **Paramètres de l'app → Utilisateurs système** → créer un utilisateur système → lui donner l'actif WhatsApp → générer un **jeton permanent** avec `whatsapp_business_messaging`.
- Noter aussi le **code secret de l'app** : **Paramètres de l'app → Données de base → Code secret** → **Afficher** (ex. fictif `a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4`).

## 3. Configurer le backend (`backend/.env`, jamais commité)

Ajouter / renseigner (valeurs fictives — remplace par les tiennes) :

```bash
WHATSAPP_BASE_URL=https://graph.facebook.com/v21.0
WHATSAPP_PHONE_NUMBER_ID=109876543210987
WHATSAPP_ACCESS_TOKEN=EAAJkEXEMPLEdeJETONfictifXyZ
WHATSAPP_VERIFY_TOKEN=sentinel-webhook-CHANGE-MOI-42
WHATSAPP_APP_SECRET=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
WHATSAPP_SIMULATOR=false
```

Règles :

- `WHATSAPP_VERIFY_TOKEN` : chaîne aléatoire ≥ 16 caractères, **identique** à celle saisie dans le dashboard Meta (§ 5). Sans elle, la validation Meta échoue (le handshake refuse tout quand le token n'est pas configuré).
- `WHATSAPP_APP_SECRET` : **obligatoire en live** — sans lui, le POST accepte les payloads non signés.
- `WHATSAPP_SIMULATOR=false` en live (à `true`, aucun appel Meta n'est émis : utile en dev local uniquement).
- Après modification du `.env`, recharger la config (aucun rebuild/restart de conteneur requis pour le `.env` Laravel, mais le worker `queue` met jusqu'à ~60 s à voir la nouvelle config ; pour forcer : `docker compose exec -T queue php artisan queue:restart`).

Vérifier que la pile tourne et que le worker consomme :

```bash
docker compose ps
docker compose logs --tail=5 queue
curl -s http://localhost/api/v1/wash/overview | head -c 300; echo
```

## 4. Ouvrir le tunnel HTTPS vers `http://localhost/api`

Meta exige une URL **publique en HTTPS**. Le backend écoute sur `http://localhost:${APP_PORT:-80}` (service `laravel`, port `8080` exposé sur `${APP_PORT:-80}`).

Option A — ngrok :

```bash
ngrok http 80
# Callback à déclarer : https://<sous-domaine>.ngrok-free.app/api/v1/whatsapp/webhook
```

Option B — cloudflared (sans compte) :

```bash
cloudflared tunnel --url http://localhost:80
# Callback à déclarer : https://<nom>.trycloudflare.com/api/v1/whatsapp/webhook
```

Garder le tunnel ouvert pendant toute la démo. Si l'URL change (redémarrage), refaire le § 5.

Test local (sans Meta) que le handshake répond à travers le tunnel — remplace par ton URL et ton token :

```bash
curl -i "https://<TON-TUNNEL>/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=sentinel-webhook-CHANGE-MOI-42&hub.challenge=CHALLENGE123"
# Attendu : HTTP 200 + corps CHALLENGE123 en text/plain
```

## 5. Déclarer l'URL de callback chez Meta (validation du handshake)

1. Dashboard Meta → **WhatsApp → Configuration** → **Webhook** → **Modifier**.
2. **URL de rappel** : `https://<TON-TUNNEL>/api/v1/whatsapp/webhook` (exactement, sans `/` final).
3. **Jeton de vérification** : la même valeur que `WHATSAPP_VERIFY_TOKEN` (ex. fictif `sentinel-webhook-CHANGE-MOI-42`).
4. **Vérifier et enregistrer** : Meta envoie le GET du § 4 ; notre contrôleur répond `200` + challenge si le token correspond, `403` sinon.

## 6. S'abonner au champ `messages`

1. Toujours dans **WhatsApp → Configuration → Webhook** → **Gérer** (ou **Abonnements au webhook**) → objet `whatsapp_business_account` → cocher **`messages`** → **Enregistrer**.
2. Sans cet abonnement, Meta valide le webhook mais n'envoie **aucun** message entrant.

## 7. Envoyer un message de test réel

1. Depuis le numéro destinataire autorisé (§ 1), envoyer un WhatsApp au numéro de test, par exemple :

   ```text
   Bonjour, le robinet du bloc A fuit beaucoup depuis hier.
   ```

   (Le numéro expéditeur doit exister dans `school_contacts`, sinon il reçoit le message « Ce numéro n'est rattaché à aucune école… » et aucun incident n'est créé.)
2. Vérifier la réception côté backend :

   ```bash
   docker compose exec -T -u www-data laravel php artisan tinker --execute='echo App\Models\Report::latest()->first()?->only(["source","channel","raw_content"]) ? json_encode(App\Models\Report::latest()->first()->only(["source","channel","raw_content"]), JSON_UNESCAPED_UNICODE) : "aucun report"; echo PHP_EOL;'
   curl -s http://localhost/api/v1/wash/overview | head -c 500; echo
   docker compose logs --tail=20 queue
   ```

3. Vérifier la réponse WhatsApp sur le téléphone : `WASH Sentinel : incident WS-… enregistré en priorité …`.

## 8. Simulation locale (sans appeler Meta, sans credentials)

Handshake GET (remplace le token par ton `WHATSAPP_VERIFY_TOKEN` local) :

```bash
curl -i "http://localhost/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=sentinel-webhook-CHANGE-MOI-42&hub.challenge=CHALLENGE123"
# Attendu : HTTP 200, corps CHALLENGE123
curl -i "http://localhost/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=MAUVAIS&hub.challenge=CHALLENGE123"
# Attendu : HTTP 403
```

POST signé façon Meta (payload d'exemple + signature HMAC-SHA256 valide) :

```bash
cd /home/haro/projects/WASH-SENTINEL
cat > /tmp/wa-sim.json <<'JSON'
{"object":"whatsapp_business_account","entry":[{"id":"123456789","changes":[{"field":"messages","value":{"messaging_product":"whatsapp","metadata":{"display_phone_number":"15550102030","phone_number_id":"109876543210987"},"contacts":[{"profile":{"name":"Testeur Demo"},"wa_id":"237600112233"}],"messages":[{"from":"237600112233","id":"wamid.SIM001","timestamp":"1760000000","type":"text","text":{"body":"Bonjour, le robinet du bloc A fuit beaucoup depuis hier."}}]}}]}]}
JSON
SECRET='ton-WHATSAPP_APP_SECRET-local'
SIG=$(openssl dgst -sha256 -hmac "$SECRET" /tmp/wa-sim.json | sed 's/^.* //')
curl -i -X POST http://localhost/api/v1/whatsapp/webhook \
  -H 'Content-Type: application/json' \
  -H "X-Hub-Signature-256: sha256=$SIG" \
  --data @/tmp/wa-sim.json
# Attendu : HTTP 200 {"received":true} puis traitement async par le worker queue.
```

Note : avec `WHATSAPP_SIMULATOR=true`, la signature n'est pas vérifiée et aucun appel Graph API n'est émis (pratique pour itérer en local, **interdit en live** si tu veux de vraies réponses).

## 9. Mapping Meta → nos endpoints

| Événement Meta | Notre endpoint | Traitement |
|---|---|---|
| Validation webhook (GET avec `hub.*`) | `GET /api/v1/whatsapp/webhook` | `WashWhatsAppController::verify` → `200` + challenge si token OK |
| Message entrant texte | `POST /api/v1/whatsapp/webhook` | `receive` → job `ProcessWhatsAppMessage` → `WashWhatsAppService` → `IncidentTriageService::ingest` canal `text` |
| Message entrant audio | idem | idem, média téléchargé via Graph API → canal `voice` (+ STT côté `ai-engine`) |
| Message entrant image (+légende) | idem | idem → canal `photo` (+ vision côté `ai-engine`) |
| Statuts (`statuses`), autres types | idem | ignorés (`200 {"received":true}`, rien en file utile) |
| Réponse à l'usager | sortant Graph API `POST /{phone_number_id}/messages` | `MetaWhatsAppService::sendText` (bloqué en mode `simulator`) |

## 10. Rollback (retour arrière en < 2 min)

1. **Couper l'entrée Meta** : dashboard Meta → **WhatsApp → Configuration → Webhook** → **Supprimer l'abonnement `messages`** (ou supprimer l'URL de rappel). Les messages WhatsApp n'arrivent plus, le reste de la pile est intact.
2. **Repasser en simulateur** (optionnel, pour continuer les tests locaux sans Meta) :

   ```bash
   # dans backend/.env :
   WHATSAPP_SIMULATOR=true
   docker compose exec -T queue php artisan queue:restart
   ```

3. **Purger la file** si des jobs WhatsApp en échec s'accumulent :

   ```bash
   docker compose exec -T -u www-data laravel php artisan queue:failed --queue=default | tail -5
   docker compose exec -T -u www-data laravel php artisan queue:flush  # ATTENTION : supprime tous les jobs en échec
   ```

4. Rejouer la suite de non-régression : `docker compose exec -T -u www-data laravel php artisan test --filter=WashWhatsApp`.

## 11. Dépannage rapide

| Symptôme | Cause probable | Correctif |
|---|---|---|
| Meta : « Échec de la validation » | `WHATSAPP_VERIFY_TOKEN` ≠ token saisi, ou tunnel fermé | aligner les deux valeurs (§ 3 = § 5), re-tester le curl du § 4 à travers l'URL publique |
| `403` sur le POST entrant | `WHATSAPP_APP_SECRET` faux ou absent | recopier le code secret (§ 2) dans le `.env` ; vérifier les logs `laravel` |
| `200 {"received":true}` mais aucun incident | worker `queue` arrêté, ou numéro expéditeur inconnu, ou `ai-engine` down | `docker compose ps`, `logs queue` ; vérifier `school_contacts` ; `curl -s http://localhost:8000/health` |
| Réponse reçue mais « rattaché à aucune école » | normal : numéro non enregistré | enregistrer le numéro dans `school_contacts` (téléphone normalisé, ex. `2376XXXXXXXX`) |
| Boucle / doublons | Meta renvoie tant qu'on ne répond pas `200` vite | le contrôleur répond avant traitement (job async) : vérifier que le POST répond < 5 s |
| Médias vides (`empty_media`) | token Graph expiré (jeton temporaire 24 h) | régénérer le token (§ 2), mettre à jour `WHATSAPP_ACCESS_TOKEN` |

---

## Références code (lecture seule)

- `backend/routes/api.php` (§ `v1/whatsapp`)
- `backend/app/Http/Controllers/Api/WashWhatsAppController.php`
- `backend/app/Services/MetaWhatsAppService.php`
- `backend/app/Services/WashWhatsAppService.php`
- `backend/app/Jobs/ProcessWhatsAppMessage.php`
- `backend/app/Services/IncidentTriageService.php`
- `backend/tests/Feature/WashWhatsAppTest.php` + `backend/tests/Fixtures/whatsapp/*.json`

---

## 12. Mode démo sans credentials

> Cycle simulé de bout en bout : aucun compte Meta, aucun token, aucun appel
> réseau sortant. Prérequis unique : `WHATSAPP_SIMULATOR=true` dans
> `backend/.env` (la signature `X-Hub-Signature-256` n'est alors pas vérifiée
> et `sendText` ne fait que logger).

### 12.1 Vérifier la configuration embarquée

```bash
curl -s http://localhost/api/v1/whatsapp/diagnostics | python3 -m json.tool
```

Réponse attendue (exemple, sans aucun secret — booléens + hints uniquement) :

```json
{
  "verify_token_configured": false,
  "app_token_configured": false,
  "webhook_url_hint": "http://localhost/api/v1/whatsapp/webhook",
  "queue_connection": "database",
  "last_webhook_at": null
}
```

### 12.2 Payload Meta d'exemple (message texte entrant, format Cloud API réel)

Le contrôleur attend le corps brut du webhook Meta (`entry[].changes[].value.messages[]`,
voir `MetaWhatsAppService::parseWebhook`) :

```bash
cat > /tmp/wa-demo.json <<'JSON'
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "123456789",
      "changes": [
        {
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "15550102030",
              "phone_number_id": "109876543210987"
            },
            "contacts": [
              {"profile": {"name": "Testeur Demo"}, "wa_id": "237600112233"}
            ],
            "messages": [
              {
                "from": "237600112233",
                "id": "wamid.SIMDEMO001",
                "timestamp": "1760000000",
                "type": "text",
                "text": {"body": "Bonjour, le robinet du bloc A fuit beaucoup depuis hier."}
              }
            ]
          }
        }
      ]
    }
  ]
}
JSON
```

### 12.3 Rejouer le webhook en local

```bash
curl -i -X POST http://localhost/api/v1/whatsapp/webhook \
  -H 'Content-Type: application/json' \
  --data @/tmp/wa-demo.json
# Attendu : HTTP 200 {"received":true} puis traitement async par le worker queue.
```

Vérifier le triage (le numéro `237600112233` doit exister dans `school_contacts`,
sinon : statut `unknown_contact` et aucun incident) :

```bash
docker compose logs --tail=20 queue
docker compose exec -T -u www-data laravel php artisan tinker --execute='echo App\Models\Report::latest()->first()?->only(["source","channel","raw_content"]) ? json_encode(App\Models\Report::latest()->first()->only(["source","channel","raw_content"]), JSON_UNESCAPED_UNICODE) : "aucun report"; echo PHP_EOL;'
```

### 12.4 Limites du mode démo

- Signature non vérifiée (`WHATSAPP_SIMULATOR=true` requis, sinon `403` sans
  HMAC valide) : ne prouve rien sur le § 2 (app secret).
- Aucune réponse réellement envoyée : `sendText` loggue et renvoie un faux id
  (`sim-…`), rien n'arrive sur un téléphone.
- Médias inutilisables : en simulateur `downloadMedia` renvoie des octets vides,
  donc audio/image terminent en `empty_media` sans triage (texte uniquement).
- Le worker `queue` doit tourner, sinon le job reste en file et aucun incident
  n'apparaît malgré le `200`.
- Statuts (`statuses`) et types non texte/audio/image toujours ignorés.
- Le handshake Meta (§ 5) et l'abonnement `messages` (§ 6) restent à valider
  manuellement pour le live réel.
