<?php

/*
 * LOT 6 — valeurs métier WASH centralisées (extraction pure, comportement
 * inchangé). Source unique lue par IncidentTriageService, AgentProposalService
 * et ProposalGuidanceException. Les libellés FR/EN sont dans lang/{fr,en}/wash.php.
 */
return [

    // Listes fermées partagées (triage + propositions agent).
    'categories' => ['water_point', 'toilets_latrines', 'handwashing', 'sewage_drainage'],
    'urgencies' => ['low', 'medium', 'high', 'critical'],

    'triage' => [
        'duplicate_candidate_limit' => 20,
        'duplicate_similarity_default' => 0.0,
        'title_max_chars' => 120,
        'ai_input_max_chars' => 2000,
        'fallback_summary_max_chars' => 200,
        'default_category' => 'water_point',
        'default_issue_type' => 'total_breakdown',
        'default_status' => 'triaged',
        'default_urgency' => 'medium',
        'default_hazard' => 'low',
        'default_priority_score' => 50.0,
        'default_affected_students' => 0,
        'fallback_priority_score' => 50.0,
        'fallback_critical_priority_score' => 85.0,
        'fallback_critical_keywords' => ['urgent', 'critique', 'choléra', 'sans eau', 'immédiat'],
        'manual_issue_type' => 'other',
        'manual_hazard' => 'low',
        'manual_tag' => 'manuel',
    ],

    'proposals' => [
        'expiry_minutes' => 30,
        'affected_students_min' => 0,
        'affected_students_max' => 100000,
        'title_min_chars' => 3,
        'title_max_chars' => 120,
        'description_max_chars' => 2000,
        'notes_max_chars' => 2000,
        'cost_min' => 0,
        'cost_max' => 1000000000,
        'days_without_service_min' => 0,
        'days_without_service_max' => 3650,
        'redraft_description_limit' => 120,
        'redraft_title_limit' => 100,
        'recap_limit' => 200,
    ],

    /*
     * LOT 8 — valeurs des contrôleurs API (extraction pure, comportement
     * inchangé, SAUF les deux plafonds audio unifiés à 12 Mo et la règle
     * langues voix alignée sur le moteur : voir notes ci-dessous).
     */
    'pagination' => [
        'default' => 20,
        'min' => 5,
        'max' => 100,
    ],

    'voice' => [
        // Miroir de SUPPORTED_VOICE_LANGUAGES (ai-engine/app/stt_providers.py).
        // Parité verrouillée par WashLot8ControllersTest (lecture du set Python).
        // bbj_Latn (ghomala') ajouté ici : le moteur le couvre nativement
        // (driver omnilingual_ctc), la validation Laravel le rejetait à tort.
        'languages' => ['fr', 'en', 'dua_Latn', 'bassa', 'ewondo', 'bbj_Latn'],
        'default_language' => 'fr',
        // Miroir de DEFAULT_TTS_VOICE (ai-engine/app/schemas.py).
        'default_tts_voice' => 'fr_FR-upmc-medium',
        // Plafond audio UNIFIÉ à 12 Mo (Ko pour la règle max:), référence
        // STT_MAX_INPUT_MB côté ai-engine : agent 10240 -> 12288 (montée),
        // report 20480 -> 12288 (baisse). Photo 10 Mo inchangée (const locale).
        'audio_max_kb' => 12288,
        'text_max_chars' => 1000,
        'voice_max_chars' => 64,
        'language_max_chars' => 16,
    ],

    /*
     * CONTRAT avec le frontend : TTL 7 jours et max_hops 10 par défaut.
     * Le front suit ces valeurs — ne pas les modifier sans le synchroniser.
     * Partagé par WashMeshController, WashSmsController, WashUssdController.
     */
    'mesh' => [
        'default_ttl_days' => 7,
        'default_max_hops' => 10,
        'default_destination_eid' => 'dtn://wash-sentinel/ingest',
    ],

    /*
     * Photo du chat Sentinel — MIROIR de WashReportController::PHOTO_MAX_KB
     * (10 Mo) : plafond unique réutilisé par converse(image), pas une
     * nouvelle limite. Parité verrouillée par WashAgentPhotoTest.
     * Mimes alignés sur WashMeshController::MEDIA_MIMES (côté image).
     */
    'photo' => [
        'max_kb' => 10240,
        'mimes' => ['jpeg', 'png', 'jpg', 'webp'],
    ],

];
