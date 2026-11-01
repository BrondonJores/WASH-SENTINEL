<?php

/*
|--------------------------------------------------------------------------
| WASH Sentinel — Canal WhatsApp (CANAL 2 : vocal de bout en bout)
|--------------------------------------------------------------------------
|
| Tous les secrets viennent du .env, jamais en dur dans le code :
|   WHATSAPP_ENABLED=true|false        (défaut true ; false = webhook 503)
|   WHATSAPP_TOKEN=...                 (token Cloud API ; repli legacy :
|                                       WHATSAPP_ACCESS_TOKEN)
|   WHATSAPP_PHONE_NUMBER_ID=...       (numéro expéditeur Meta)
|   WHATSAPP_WABA_ID=...               (id du compte WhatsApp Business)
|   WHATSAPP_VERIFY_TOKEN=...          (handshake GET, >= 16 caractères)
|   WHATSAPP_APP_SECRET=...            (HMAC X-Hub-Signature-256, obligatoire live)
|   WHATSAPP_BASE_URL=...              (défaut Graph API v21.0)
|   WHATSAPP_SIMULATOR=true|false      (dev local : aucun appel Meta)
|
| Réglages du flow vocal :
|   WHATSAPP_VOICE_CONFIRMATION=true|false (défaut true : après une note
|       vocale triée, on envoie récap texte + boutons Oui/Non + note vocale TTS)
|   WHATSAPP_VOICE_NOTE=true|false         (défaut true : note vocale TTS de
|       confirmation, best-effort — texte + boutons toujours envoyés)
|   WHATSAPP_TTS_VOICE=fr_FR-upmc-medium   (voix Piper côté ai-engine)
|   WHATSAPP_CONFIRMATION_TEMPLATE=wash_confirmation (template Meta utilisé
|       hors fenêtre 24h, voir règle ci-dessous)
|   WHATSAPP_CONFIRMATION_LANGUAGE=fr      (langue du template)
|
|--------------------------------------------------------------------------
| RÈGLE META DES 24H (résumé, voir MetaWhatsAppService + doc)
|--------------------------------------------------------------------------
| - Sous 24h après le DERNIER message de l'usager : free-form autorisé
|   (texte, boutons interactifs, audio). C'est le cas de toutes nos réponses
|   directes au webhook (on répond en quelques secondes).
| - Hors fenêtre (> 24h sans message usager, ex. relance proactive) :
|   free-form REFUSÉ par Meta (erreur 131047). Il faut un TEMPLATE approuvé.
|   Le template de confirmation à créer côté Meta s'appelle par défaut
|   "wash_confirmation" (voir docs/WHATSAPP_BRANCHEMENT.md § templates).
| - Le clic sur un bouton Oui/Non est un message usager : il ROUVRE une
|   fenêtre de 24h.
|
*/

return [
    'enabled' => (bool) env('WHATSAPP_ENABLED', true),

    'base_url' => env('WHATSAPP_BASE_URL', 'https://graph.facebook.com/v21.0'),

    'phone_number_id' => env('WHATSAPP_PHONE_NUMBER_ID', ''),

    'waba_id' => env('WHATSAPP_WABA_ID', env('WABA_ID', '')),

    // Nouveau nom WHATSAPP_TOKEN, repli sur l'ancien WHATSAPP_ACCESS_TOKEN.
    'token' => env('WHATSAPP_TOKEN', env('WHATSAPP_ACCESS_TOKEN', '')),

    'verify_token' => env('WHATSAPP_VERIFY_TOKEN', ''),

    'app_secret' => env('WHATSAPP_APP_SECRET', ''),

    // Dev local : aucun appel Graph API, signature non exigée. Interdit en live.
    // Défaut null (pas false) : laisse MetaWhatsAppService::cfg() tomber sur
    // l'ancien services.whatsapp.simulator puis sur false. Un false en dur
    // masquerait le legacy (config() ne distingue pas défaut/explicite).
    'simulator' => env('WHATSAPP_SIMULATOR'),

    // Flow vocal : récap + boutons Oui/Non + note vocale TTS après triage.
    'voice_confirmation' => (bool) env('WHATSAPP_VOICE_CONFIRMATION', true),
    'voice_note' => (bool) env('WHATSAPP_VOICE_NOTE', true),
    'tts_voice' => env('WHATSAPP_TTS_VOICE', 'fr_FR-upmc-medium'),

    // Template Meta (à créer/approuver côté dashboard) pour parler à un
    // usager dont la fenêtre free-form de 24h est fermée.
    'confirmation_template' => env('WHATSAPP_CONFIRMATION_TEMPLATE', 'wash_confirmation'),
    'confirmation_language' => env('WHATSAPP_CONFIRMATION_LANGUAGE', 'fr'),

    // Durée de vie (secondes) d'une demande de confirmation Oui/Non en cache.
    'pending_ttl' => (int) env('WHATSAPP_PENDING_TTL', 86400),
];
