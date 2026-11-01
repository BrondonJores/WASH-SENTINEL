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

];
