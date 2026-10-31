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
    ],

    'whatsapp' => [
        'base_url' => env('WHATSAPP_BASE_URL', 'https://graph.facebook.com/v21.0'),
        'phone_number_id' => env('WHATSAPP_PHONE_NUMBER_ID', ''),
        'access_token' => env('WHATSAPP_ACCESS_TOKEN', ''),
        'verify_token' => env('WHATSAPP_VERIFY_TOKEN', ''),
        'app_secret' => env('WHATSAPP_APP_SECRET', ''),
        'simulator' => env('WHATSAPP_SIMULATOR', false),
    ],
];
