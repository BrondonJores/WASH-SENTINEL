# 🎤 WASH Sentinel — Package démo jury (hackathon Meta)

> Golden path 5 minutes + plan B + checklist jour J + captures.
> Pré-requis : `./start.sh` a tourné (migrations + seeders OK).
> Comptes démo (mot de passe `password`) : `admin@wash.cm` (Amina Ngo Bell, admin),
> `tech@wash.cm` (Jean Fotso, maintenance), `directeur@ecole.cm` (Clarisse Eko, reporter).
> Données : 8 écoles (Bonanjo, Libermann, Bali — Wouri ; Ngok, Nkol — Mvila ;
> Édéa, Pouuma, Nyo — Sanaga-Maritime), 9 incidents (`WashDemoSeeder`) :
> pompe Bonanjo CRITICAL (triaged), forage Ngok à sec HIGH (il y a 22 j),
> fuite Nkol MEDIUM (il y a 12 j), latrines Libermann HIGH résolues (il y a 5 j),
> forage Pouuma CRITICAL non desservi (il y a 31 j), lave-mains Édéa HIGH,
> caniveau Nyo HIGH, pompe Nyo résolue, robinet Bali LOW.

## 0. URLs du jour J

| Service | URL |
|---|---|
| Console agent (login admin) | http://localhost:5173/ |
| Widget public /signaler (sans compte) | http://localhost:5173/signaler |
| Journal IA (admin) | http://localhost:5173/admin/journal |
| API Laravel | http://localhost/api (`APP_PORT`, défaut 80) |
| AI engine (docs interactives) | http://localhost:8000/docs |
| Réglages IA (profils LLM/STT) | http://localhost:5173/admin/reglages |

> Si `APP_PORT` change dans `.env`, refléter dans `VITE_API_URL` (ex. `http://localhost:8080/api`).

## 1. Script golden path — 5 minutes

Se connecter à la console avec `admin@wash.cm` / `password` avant le chrono.
Parler français, taper les phrases EXACTES ci-dessous (guillemets exclus).

### 1.1 Signalement one-shot — 0:00 → 0:45

Taper dans la console :

```text
Nouveau signalement : école publique de Bonanjo, la pompe principale du puits est cassée depuis ce matin, 450 élèves sans eau potable.
```

Attendu : carte **« Confirmer le signalement »** (`action_confirmation`) avec
catégorie `water_point`, urgence `critical`, élèves affectés,
bouton **Confirmer**. Cliquer **Confirmer** (ou répondre `oui`, § 1.2).
Punchline : *« Un récit chaotique devient un ticket trié, scoré, traçable. »*

### 1.2 Signalement interactif + vote « oui » — 0:45 → 1:30

Taper une demande volontairement incomplète :

```text
Je veux signaler un problème d'eau à Ngok.
```

Attendu : l'agent pose des questions de clarification (type de panne, urgence,
élèves affectés — outil `prepare_report` incomplet, pas de carte).
Répondre :

```text
Le forage est à sec depuis trois semaines, 195 élèves affectés, c'est urgent.
```

Attendu : carte **« Confirmer le signalement »**. Puis taper EXACTEMENT :

```text
oui
```

Attendu : `confirm_proposal` exécuté, carte **« Résultat de la validation »**
(`action_result`), incident créé avec référence `WASH-2026-XXXXXX`.
(Le vote accepte aussi : `ok`, `je confirme`, `valider`, `d'accord` ;
`non` / `annuler` annule. Regex dans `WashAgentController::interceptVote`.)
Punchline : *« L'agent n'écrit jamais sans validation humaine — un mot suffit. »*

### 1.3 Journal de maintenance via titre flou — 1:30 → 2:10

Taper (titre volontairement ambigu, plusieurs incidents « eau » existent) :

```text
Ajoute une intervention au journal pour la panne d'eau : vidange et remplacement du joint, coût 250000 francs.
```

Attendu : l'outil ne peut pas trancher → carte **« Quel incident ? »**
(`incident_picker`) listant les candidats (école, urgence, élèves).

### 1.4 Carte picker + clic sur la référence — 2:10 → 2:30

Cliquer sur le bouton du bon incident dans la carte picker
(la référence affichée commence par **`WASH-2026-`**).
Attendu : la référence est renvoyée comme message, l'agent affiche la carte
**« Confirmer le journal »** (`prepare_maintenance_log`), puis taper :

```text
oui
```

Attendu : log de maintenance enregistré, carte résultat.
Punchline : *« Titre flou, zéro erreur : le jury clique, l'agent rattache. »*

### 1.5 Tiroir de détail — 2:30 → 3:00

Sur la carte incident (ou classement d'écoles), cliquer **« Détails »**
(carte incident) ou sur le nom d'une école (carte classement).
Attendu : **tiroir latéral** (`DetailDrawer`) avec le détail incident/école,
navigation croisée (incident ↔ école) et bouton « Poser une question ».
Punchline : *« Dashboardless : les cartes suivent la conversation, pas l'inverse. »*

### 1.6 Carte territoire — 3:00 → 3:35

Taper EXACTEMENT :

```text
Montre-moi la carte du territoire.
```

Attendu : carte **`territory_map`** (outil `territory_overview`) : écoles,
incidents ouverts, élèves affectés — 3 districts (Wouri, Mvila,
Sanaga-Maritime), contraste équité Bonanjo (critique servie) / Pouuma
(critique non desservie depuis 31 j). Variante district :

```text
Montre-moi la carte du territoire de Wouri.
```

### 1.7 Mini-deck briefing — 3:35 → 4:10

Taper EXACTEMENT :

```text
Prépare un briefing du district de Wouri.
```

Attendu : carte **`briefing_deck`** (outil `build_briefing`, composant
`SlideDeck`) : mini-deck de synthèse prêt à présenter.
Punchline : *« Le copilote génère le discours officiel, chiffres à l'appui. »*

### 1.8 Widget public /signaler — 4:10 → 4:40

Ouvrir http://localhost:5173/signaler (navigation privée = sans compte) :

1. École : taper `Bali` → choisir **École Publique de Bali**.
2. Type : **Point d'eau**. Urgence : **Haute**. Élèves : `120`.
3. Description (taper EXACTEMENT) :

```text
Le robinet de la cour ne coule plus depuis lundi, les élèves n'ont plus d'eau pour se laver les mains.
```

4. **Envoyer le signalement** → écran « Merci, c'est bien reçu ! » avec
   référence `WASH-2026-XXXXXX` + badge d'urgence.
   Si doublon : mention « rattaché » à l'incident existant.
Punchline : *« Gratuit, sans compte, en 30 secondes — côté citoyen. »*

### 1.9 Variante WhatsApp — 4:40 → 5:00

Option live (credential Meta + tunnel, voir `docs/WHATSAPP_LIVE.md`) :
envoyer depuis le numéro autorisé (`237600112233`, école de Bonanjo) :

```text
Bonjour, le robinet du bloc A fuit beaucoup depuis hier.
```

Attendu : réponse `WASH Sentinel : incident WASH-2026-XXXXXX enregistré…`,
incident créé (`source: whatsapp`, canal `text`), traitement async par le
worker `queue`. Option sans Meta : mode simulateur (`WHATSAPP_SIMULATOR=true`)
— même pipeline, sans appel Graph API.
Punchline : *« Meta de bout en bout : WhatsApp livre, Llama raisonne. »*

### Minutage récapitulatif

| Étape | Durée | Cumul |
|---|---|---|
| One-shot | 45 s | 0:45 |
| Interactif + « oui » | 45 s | 1:30 |
| Journal titre flou | 40 s | 2:10 |
| Picker + clic | 20 s | 2:30 |
| Tiroir détail | 30 s | 3:00 |
| Carte territoire | 35 s | 3:35 |
| Mini-deck briefing | 35 s | 4:10 |
| Widget /signaler | 30 s | 4:40 |
| WhatsApp | 20 s | 5:00 |

## 2. Plan B — modèle froid / hors-ligne

### 2.1 Warmup (modèle froid = première réponse lente)

1. Avant le jury, envoyer une question simple dans la console
   (ex. `Combien d'écoles sont sans eau aujourd'hui ?`) pour charger
   `llama3.2:3b` en mémoire Ollama.
2. Vérifier les modèles présents :
   `docker compose exec ollama ollama list`
   (attendus : `llama3.2:3b`, `nomic-embed-text`, optionnel `llama3.2-vision:11b`).
3. Si pull manquant : `docker compose exec ollama ollama pull llama3.2:3b`.

### 2.2 Fallbacks déterministes (prouvables devant le jury)

Le signalement ne s'arrête JAMAIS, même IA coupée :

| Couche | Comportement sans IA | Code |
|---|---|---|
| Extraction | règles mots-clés, `model_used: fallback-rules`, confiance 0.4 | `IncidentTriageService::fallbackExtraction` |
| Vision photo | ignorée avec warning, ticket créé quand même | `IncidentTriageService::ingest` (try/catch) |
| Doublons | pas de rattachement auto, ticket créé | idem (try/catch) |
| Réponse agent | résumé chiffré déterministe + carte | `AgentLoop::_fallback_answer` |
| Refus poli abusif | détecté et remplacé si un outil a réussi | `AgentLoop::_is_bogus_refusal` |

Démo du fallback : arrêter `ai-engine`, refaire § 1.1 → ticket créé,
journal IA affichant `fallback-rules`. Puis redémarrer.
Punchline : *« L'IA tombe, l'eau n'attend pas : le ticket part quand même. »*

### 2.3 Secours cloud (pas de GPU / réseau restreint)

Console → **Réglages IA** → **New LLM profile** → provider
`API externe (format OpenAI)` (ex. Groq `llama-3.3-70b-versatile`) →
**Test** → **Activate**. Bascule à chaud, sans redéploiement.
Idem STT cloud (`whisper-1`).

## 3. Checklist jour J

- [ ] `./start.sh` vert : `docker compose ps` — `laravel`, `queue`, `pgsql`,
      `ai-engine`, `ollama`, `mesh-relay`, `frontend` tous `Up` (7 services,
      voir `compose.yaml`).
- [ ] Seed vérifié : login `admin@wash.cm` / `password` OK, écoles et
      incidents visibles (Bonanjo CRITICAL présent).
- [ ] Modèles Ollama : `docker compose exec ollama ollama list`
      (`llama3.2:3b` + `nomic-embed-text` ; vision optionnelle).
- [ ] Warmup fait (§ 2.1) — première réponse déjà passée.
- [ ] Worker queue actif : `docker compose logs --tail=5 queue` récent
      (indispensable pour WhatsApp async).
- [ ] Santé rapide : `http://localhost/api/v1/wash/overview` répond ;
      `http://localhost:8000/health` répond.
- [ ] Tunnel WhatsApp (si variante live) : URL HTTPS ouverte, callback
      `https://<TUNNEL>/api/v1/whatsapp/webhook` déclarée chez Meta,
      `messages` souscrit, `WHATSAPP_SIMULATOR=false`
      (runbook complet : `docs/WHATSAPP_LIVE.md`).
- [ ] Onglets prêts : console `/`, `/signaler`, `/admin/journal`,
      AI engine `/docs` (secours).
- [ ] Captures de secours (§ 4) sur clé USB + vidéo `docs/demo.mp4` si dispo.

## 4. Captures d'écran à faire (6)

> Note : `docs/demo.mp4` est absent (ni sur disque ni dans git au 31/10) —
> ces 6 captures sont le plan B vidéo en attendant le montage.

| # | URL | Action exacte |
|---|---|---|
| 1 | http://localhost:5173/ | Envoyer la phrase one-shot (§ 1.1), capturer la carte « Confirmer le signalement » avec score et urgence. |
| 2 | http://localhost:5173/ | Après `oui`, capturer la carte « Résultat de la validation » avec la référence `WASH-2026-XXXXXX`. |
| 3 | http://localhost:5173/ | Envoyer `Montre-moi la carte du territoire.`, capturer la carte territoire + ouvrir le tiroir « Détails » d'un incident et capturer le tiroir ouvert. |
| 4 | http://localhost:5173/ | Envoyer `Prépare un briefing du district de Wouri.`, capturer le mini-deck briefing. |
| 5 | http://localhost:5173/signaler | Remplir (Bali / Point d'eau / Haute / 120 + description § 1.8), capturer l'écran « Merci, c'est bien reçu ! » avec référence. |
| 6 | http://localhost:5173/admin/journal | Filtrer par type `triage`, sélectionner la dernière analyse, capturer modèle + confiance + payload. |

## 5. Phrases jury (à placer)

- *« Dashboardless : l'agent décide, les cartes suivent. »*
- *« L'équité est l'algorithme, pas une option. »*
- *« Meta de bout en bout : Llama raisonne, Omnilingual transcrit le douala, WhatsApp livre. »*
- *« L'IA tombe, l'eau n'attend pas. »*
- *« Leave no school behind — même sans réseau. »* 💧🇨🇲
