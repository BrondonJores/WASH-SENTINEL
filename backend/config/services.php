<?php

return [

    /*
    |--------------------------------------------------------------------------
    | Third Party Services
    |--------------------------------------------------------------------------
    |
    | This file is for storing the credentials for third party services such
    | as Mailgun, Postmark, AWS and more. This file provides the de facto
    | location for this type of information, allowing packages to have
    | a conventional file to locate the various service credentials.
    |
    */

    'postmark' => [
        'key' => env('POSTMARK_API_KEY'),
    ],

    'resend' => [
        'key' => env('RESEND_API_KEY'),
    ],

    'ses' => [
        'key' => env('AWS_ACCESS_KEY_ID'),
        'secret' => env('AWS_SECRET_ACCESS_KEY'),
        'region' => env('AWS_DEFAULT_REGION', 'us-east-1'),
    ],

    'slack' => [
        'notifications' => [
            'bot_user_oauth_token' => env('SLACK_BOT_USER_OAUTH_TOKEN'),
            'channel' => env('SLACK_BOT_USER_DEFAULT_CHANNEL'),
        ],
    ],

    'ai_engine' => [
        'url' => env('AI_ENGINE_URL', 'http://ai-engine:8000'),
        'timeout' => env('AI_ENGINE_TIMEOUT', 120),
        // LOT 7 — sondes admin + cache profils (WashAiEngineService).
        // Replis : constantes TIMEOUT_* / PROFILE_CACHE_TTL du service.
        'timeout_health' => env('AI_ENGINE_TIMEOUT_HEALTH', 10),
        'timeout_provider_types' => env('AI_ENGINE_TIMEOUT_PROVIDER_TYPES', 15),
        'timeout_test_profile' => env('AI_ENGINE_TIMEOUT_TEST_PROFILE', 45),
        'timeout_test_stt' => env('AI_ENGINE_TIMEOUT_TEST_STT', 120),
        'profile_cache_ttl' => env('AI_ENGINE_PROFILE_CACHE_TTL', 60),
        // Seuil cosinus décision doublon. MIROIR de DUPLICATE_DECISION_THRESHOLD
        // (ai-engine/app/thresholds.py, 0.80 hérité AXE 8) : même nom
        // d'ENV des deux côtés, changer l'un exige de changer l'autre.
        'duplicate_threshold' => env('DUPLICATE_DECISION_THRESHOLD', 0.80),
    ],

    'mesh' => [
        // Clé optionnelle exigée sur X-Mesh-Key pour POST /v1/mesh/bundles.
        // Vide = ingestion publique (nœuds ruraux anonymes) + throttle + quotas.
        'ingest_key' => env('MESH_INGEST_KEY', ''),
        // Secret partagé SMSSync pour POST /v1/mesh/sms (fail-closed si vide).
        'sms_secret' => env('MESH_SMS_SECRET', ''),
        // Allowlist optionnelle des numéros expéditeurs (séparés par des virgules).
        'sms_allowlist' => env('MESH_SMS_ALLOWLIST', ''),
        // Plafond journalier de bundles par nœud d'origine.
        'daily_cap_per_origin' => (int) env('MESH_DAILY_CAP_PER_ORIGIN', 500),
        // Plafond journalier de SMS par expéditeur.
        'sms_quota_per_sender' => (int) env('MESH_SMS_QUOTA_PER_SENDER', 10),
        // V2 E2E : clé secrète box du serveur (base64, 32 octets).
        // Générer avec : php artisan mesh:key-generate. Vide = E2E désactivé,
        // les clients retombent en clair avec un avertissement.
        'seal_secret' => env('MESH_SEAL_SECRET', ''),
    ],

    // LOT 7 — LEGACY DÉPRÉCIÉ MAIS FONCTIONNEL : la source unique est
    // config/whatsapp.php. Conservé pour compat ascendante : lu en repli
    // par MetaWhatsAppService::cfg() et WashWhatsAppController quand
    // whatsapp.* est vide. Ne plus y ajouter de clés.
    'whatsapp' => [
        'base_url' => env('WHATSAPP_BASE_URL', 'https://graph.facebook.com/v21.0'),
        'phone_number_id' => env('WHATSAPP_PHONE_NUMBER_ID', ''),
        'access_token' => env('WHATSAPP_ACCESS_TOKEN', ''),
        'verify_token' => env('WHATSAPP_VERIFY_TOKEN', ''),
        'app_secret' => env('WHATSAPP_APP_SECRET', ''),
        'simulator' => env('WHATSAPP_SIMULATOR', false),
    ],
];
