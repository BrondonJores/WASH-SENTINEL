# 🎤 Runbook démo jury — 3 minutes chrono

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
   ce matin, 400 élèves sans eau… »* → incident **CRITICAL**, référence
   `WASH-...`, priorité 95/100.
2. Renvoyer *« Problème d'eau à Saint-Paul »* → `is_duplicate: true`,
   rattaché au parent. Zéro spam de tickets.
3. (Optionnel) Photo d'un tuyau percé → score visuel fusionné.

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
- WhatsApp : mode simulateur intégré, identique au live.
- SMS : `POST /api/v1/mesh/sms` avec `WASH CE042 P` → ticket + accusé.

## Phrases jury (à placer)

- *« Dashboardless : l'agent décide, les cartes suivent. »*
- *« L'équité est l'algorithme, pas une option. »*
- *« Meta de bout en bout : Llama raisonne, Omnilingual transcrit le douala, WhatsApp livre. »*
- *« Leave no school behind — même sans réseau. »*
