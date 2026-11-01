# WhatsApp — Guide de branchement (Canal 2 : vocal de bout en bout)

Flow live : note vocale usager → téléchargement média Meta → transcription
(profil STT actif + langue de l'école) → triage → récap texte + boutons
interactifs **Oui/Non** + note vocale TTS de confirmation. Clic Oui →
incident tagué `confirme-usager`. Clic Non → UNE question courte
(« Que dois-je corriger ? »), la réponse est triée comme un message normal.

## 1. Dashboard Meta (application déjà créée)

1. Produit **WhatsApp** → **API Setup** : noter
   - `WHATSAPP_TOKEN` (temporaire 24 h pour tester ; permanent ensuite,
     voir §5),
   - `WHATSAPP_PHONE_NUMBER_ID` (numéro de test prêté par Meta),
   - `WABA_ID` (compte WhatsApp Business).
2. Inventer `WHATSAPP_VERIFY_TOKEN` (≥ 16 caractères, ex. `sentinel-2026-...`).

## 2. Variables (.env backend, jamais en dur ni en commit)

```env
WHATSAPP_ENABLED=true
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_WABA_ID=...
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_APP_SECRET=...        # HMAC X-Hub-Signature-256, obligatoire en live
WHATSAPP_SIMULATOR=false       # true = dev local, aucun appel Graph API
```

Anciens noms repliés automatiquement : `WHATSAPP_ACCESS_TOKEN`,
`services.whatsapp.*` (voir `MetaWhatsAppService::cfg()`).

## 3. Webhook

Route : `POST /api/v1/whatsapp/webhook` (+ `GET` challenge verify).

```bash
ngrok http 80
# URL : https://xxxx.ngrok-free.app/api/v1/whatsapp/webhook
```

Dashboard → WhatsApp → **Configuration** : coller l'URL + le verify token →
**Vérifier** → s'abonner au champ **`messages`**.

## 4. Tester

1. Envoyer « bonjour » depuis un téléphone perso vers le numéro de test.
2. Logs Laravel : message entrant → réponse auto (`received: true`).
3. Envoyer une **note vocale** (« fuite au robinet du bloc A ») → triage →
   récap + boutons Oui/Non. Toucher Oui → « Parfait, c'est confirmé ! ».
4. Simulateur local sans Meta : `WHATSAPP_SIMULATOR=true` (aucun appel HTTP,
   médias factices) — c'est le mode des tests (`FakeWhatsAppService`).

## 5. Règle Meta des 24 h (bloquante, lue dans le code)

- Sous 24 h après le **dernier message de l'usager** : free-form autorisé
  (texte, boutons, audio). Toutes nos réponses webhook sont dans ce cas.
  Le service horodate chaque message (`wash.whatsapp.last_user_msg_at.*`,
  `isWithinFreeformWindow()`), et un clic Oui/Non **rouvre 24 h**.
- Hors fenêtre (relance proactive > 24 h) : free-form **refusé** par Meta
  (erreur 131047). Il faut un **template approuvé**.

### Template à créer côté Meta (Dashboard → WhatsApp → Message templates)

- Nom : `wash_confirmation` (ou renseigner
  `WHATSAPP_CONFIRMATION_TEMPLATE`), langue `fr`
  (`WHATSAPP_CONFIRMATION_LANGUAGE`), catégorie **UTILITY**.
- Corps proposé (paramètres `{{1}}` = référence, `{{2}}` = résumé) :

```text
Bonjour, votre signalement {{1}} est bien suivi par nos équipes : {{2}}.
Répondez à ce message pour ajouter une précision. Merci !
```

## 6. Passage en live

1. Numéro réel : une ligne **n'ayant jamais eu WhatsApp** (nouvelle SIM/eSIM).
2. Token permanent : **utilisateur système** (Business Settings → System Users,
   token avec permission `whatsapp_business_messaging`).
3. `WHATSAPP_APP_SECRET` renseigné (sinon webhook 403 en live).
4. Vérification business Meta pour envoyer en masse / lever les limites.
5. `WHATSAPP_SIMULATOR=false` en production (sinon aucun appel Meta réel).

## 7. Checklist jour J (ordre exact des opérations)

À exécuter dans cet ordre, sans sauter d'étape :

1. **Renseigner le `.env`** (§2) : `WHATSAPP_TOKEN` (permanent, §6.2),
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_WABA_ID`,
   `WHATSAPP_VERIFY_TOKEN` (≥ 16 caractères), `WHATSAPP_APP_SECRET`,
   `WHATSAPP_SIMULATOR=false`. Puis `php artisan config:clear`.
2. **Lancer le preflight** (depuis `backend/`) :
   ```bash
   php artisan wash:whatsapp:preflight
   ```
   Il vérifie chaque point en français (canal activé, token présent
   sans l'afficher, IDs, verify token, app secret, `SIMULATOR=false`,
   connectivité Graph API avec timeout 10 s, route webhook). Exit 0 =
   tout vert ; exit 1 = corriger chaque action listée puis relancer.
3. **Déclarer le webhook** (§3) : URL publique
   `https://<hôte>/api/v1/whatsapp/webhook` + verify token →
   **Vérifier** → s'abonner au champ **`messages`**.
4. **Test vocal de bout en bout** : depuis un téléphone personnel,
   envoyer une **note vocale** au numéro live
   (ex. « fuite au robinet du bloc A ») → vérifier le récap texte +
   les boutons **Oui/Non** + la note vocale TTS de confirmation →
   toucher **Oui** → « Parfait, c'est confirmé ! » et incident tagué
   `confirme-usager`. Tester aussi **Non** → « Que dois-je corriger ? ».
5. **Surveiller les logs** Laravel pendant le test (message entrant →
   transcription → triage → `received: true`) et
   `GET /api/v1/whatsapp/diagnostics` (`last_webhook_at` renseigné).
