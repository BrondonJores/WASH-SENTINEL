<?php

/*
 * LOT 6 — English mirror of lang/fr/wash.php (same keys). Reference for
 * future locale-aware replies; current replies force locale 'fr' (unchanged).
 */
return [

    'categories' => [
        'water_point' => 'Water point',
        'toilets_latrines' => 'Toilets / latrines',
        'handwashing' => 'Handwashing',
        'sewage_drainage' => 'Sewage / drainage',
    ],

    'urgencies' => [
        'low' => 'Low',
        'medium' => 'Medium',
        'high' => 'High',
        'critical' => 'Critical',
    ],

    'proposal' => [
        'unknown_action' => 'Unknown action.',
        'permission_required' => 'Permission ":permission" required.',
        'description_required' => 'Description required (:max characters max).',
        'title_required' => 'Title required (:min to :max characters).',
        'incident_not_found' => 'Incident not found, please give its number or reference.',
        'cost_required' => 'Cost required, in XAF, positive.',
        'notes_too_long' => 'Notes limited to :max characters.',
        'days_invalid' => 'Invalid days without service.',
        'school_not_found' => 'School not found, please give its name.',
        'enum_invalid' => 'Invalid value for :key.',
        'int_invalid' => 'Invalid number for :key.',

        'cancelled' => 'Proposal cancelled, nothing was created.',
        'redraft_label' => 'Redo the request',
        'redraft_default' => 'Redo my request',
        'redraft_report' => 'Report :where: :description',
        'redraft_incident' => 'Create a job :where: :title',
        'redraft_log' => 'Log :cost XAF on :ref',
        'redraft_at_school' => 'at :school',
        'redraft_a_problem' => 'an issue',
        'redraft_no_title' => 'untitled',
        'redraft_the_incident' => 'the incident',

        'report_attached' => 'Report #:id attached to incident :ref (duplicate detected).',
        'report_created' => 'Report #:id created, incident :ref (:urgency).',
        'incident_created' => 'Job :ref created: :title.',
        'log_created' => 'Job logged on :ref: :cost XAF.',

        'recap_missing' => '—',
        'recap_school' => 'School',
        'recap_description' => 'Description',
        'recap_category' => 'Category',
        'recap_urgency' => 'Urgency',
        'recap_affected' => 'Affected pupils',
        'recap_title' => 'Title',
        'recap_incident' => 'Incident',
        'recap_cost' => 'Cost',
        'recap_notes' => 'Notes',
        'recap_days' => 'Days without service',
    ],

    'guidance' => [
        'expired' => 'This case has expired (:minutes min). Ask for a new summary: ":prompt".',
        'redraft_label' => 'Redo the request',
        'already_done' => 'Already saved! ',
        'already_validated' => 'This request was already validated. ',
        'already_see' => 'See: :ref.',
        'already_nothing' => 'Nothing more to validate.',
        'already_show_prompt' => 'Show case :ref',
        'already_show_label' => 'See the case',
        'conflict' => 'Someone already handled it: this request was cancelled and nothing was created. If needed, redo the request: ":prompt".',
        'refused' => 'Action refused: :reason Nothing was created. Check your role or ask an administrator.',
        'refused_label' => 'See my possible actions',
        'refused_prompt' => 'What can I do with my role?',
        'owner_mismatch' => 'This proposal belongs to another user. Nothing was created on your account.',
    ],

];
