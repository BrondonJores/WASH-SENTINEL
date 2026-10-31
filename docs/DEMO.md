# 🎤 Runbook démo jury — 3 minutes chrono

> ⚠️ Variante mesh/offline — golden path console : [DEMO_JURY.md](DEMO_JURY.md).
>
> Objectif : prouver en 180 secondes qu'aucune école ne reste invisible,
> même sans internet. Tout tourne en local après `./start.sh`.

## Setup (avant le jury)

```bash
./start.sh
```

Ouvrir 3 onglets : `http://localhost:5173/` (console),
`http://localhost:5173/m` (terrain), `http://localhost:5173/admin/mesh` (maillage).
Vérifier : `curl -s http://localhost:8001/health` (relai mesh).

## Acte 1 — Le signalement multimodal (60 s)

1. Console → envoyer : *« Ici école Saint-Paul, la pompe est brisée depuis
   ce matin, 400 élèves sans eau… »* → carte **« Confirmer le signalement »**.
2. Répondre `oui` (obligatoire : `WashAgentController::interceptVote` ne crée
   l'incident qu'après vote explicite) → incident **CRITICAL**, référence
   `WASH-2026-XXXXXX`, priorité 95/100.
3. Renvoyer *« Problème d'eau à Saint-Paul »* → `is_duplicate: true`,
   rattaché au parent. Zéro spam de tickets.
4. (Optionnel) Photo d'un tuyau percé → score visuel affiché
   (non fusionné dans la priorité : `IncidentTriageService::ingest`
   stocke `visual` dans `ai_analyses`, la priorité vient de l'extraction).

## Acte 2 — Le village sans internet (90 s, le différenciateur 🏆)

1. Onglet **/m** (jouer le directeur offline à Yokadouma) : créer le
   signalement → il part en **file locale**, badge « Hors-ligne ».
2. Cliquer **QR** : le bundle (~600 octets, spray 8 copies) s'affiche.
3. Onglet **/admin/mesh** : jouer A → B → C (transmissions QR/BT simulées),
   puis **Uploader** → incident créé **après 2 sauts**, `source: mesh`.
4. Punchline : *« Ce signalement a voyagé 3 téléphones sans un octet
   d'internet — puis l'IA l'a trié comme les autres. »*

## Acte 3 — Le copilote équitable (30 s)

Console : *« Plan this week's tours »* → l'école rurale oubliée passe
devant le centre-ville, tournée groupée, note de transparence générée.

## Secours si le live casse

- Frontend `Failed to resolve import ...` ? Vieux `node_modules` : `docker compose restart frontend` (réinstalle au démarrage), ~1 min.
- Relai mesh down ? Le flux /m → file locale → upload direct suffit.
- Pas de réseau du tout ? `python3 mesh/demo/simulate_hops.py` (zéro serveur).
- WhatsApp : mode simulateur (limites : voir WHATSAPP_LIVE §12.4).
- SMS : `POST /api/v1/mesh/sms` (`WashSmsController::store` exige
  `secret` + `from` + `message`, code école du seed) → ticket + accusé :
  ```bash
  curl -s -X POST http://localhost/api/v1/mesh/sms \
    -H 'Content-Type: application/json' \
    -d '{"secret":"'"$MESH_SMS_SECRET"'","from":"237600112233","message":"WASH DOU-BON-001 P pompe cassee"}'
  ```

## Phrases jury (à placer)

Voir la liste de référence : [DEMO_JURY.md §5](DEMO_JURY.md#5-phrases-jury-à-placer).
