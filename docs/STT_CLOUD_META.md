# STT cloud Meta — muse-voice-transcribe-1.0

## Activation (3 clics, aucune commande)

1. `./start.sh` (migration + profil seedé).
2. Réglages → profils STT → **« Meta Muse Transcribe (cloud) »** → coller la
   clé `api.meta.ai` → **Tester** avec un vrai vocal.
3. Si le transcript revient propre → **Activer**. Tous les vocaux (console,
   WhatsApp, triage) y passent ; le transcript alimente la mémoire langue
   (`fr`/`en` mémorisée, natif → phrasebook) comme avant.

## Comportement moteur

- **Voie directe (fr/en)** : le provider actif transcrit ; la langue
  **détectée par Meta** gagne sur la langue demandée (un anglophone au
  micro avec langue=fr est détecté `en`, plus jamais affirmé `fr`).
- **Cascade (langues locales dua/bbj...)** : le cloud actif est honoré
  **d'abord** (`reason: cloud-first`), avec **repli automatique** sur
  Whisper-local + Omnilingual-local si le cloud échoue ou rend vide
  (réseau coupé, clé révoquée → le service ne tombe jamais).
- Réponse tolérante : `text` (OpenAI) ou `transcript`, langue détectée
  propagée (`language` / `detected_language` / `language_detected`).

## Transparence

Le driver qui a transcrit est exposé (`driver: meta_transcribe`,
`detection.reason`) : l'admin sait toujours quel moteur a parlé.

## Avertissement données

Variante *contributor* : les vocaux envoyés peuvent servir à entraîner les
modèles Meta. Voix d'écoles = données sensibles : assumer devant le jury,
ou basculer en variante standard. Le local reste le défaut hors ligne.
