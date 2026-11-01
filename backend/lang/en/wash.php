<?php

/*
 * LOT 6 — English mirror of lang/fr/wash.php (same keys). Reference for
 * future locale-aware replies; current replies force locale 'fr' (unchanged).
 *
 * LOT 7 — English mirror of the WhatsApp/mesh/notification keys
 * (WashWhatsAppService, WashWhatsAppPersonality, notifications). FR-only
 * messages (technical error, unreadable media, off-topic, unknown school,
 * oversized, voice placeholder) have no EN variant: unchanged behaviour,
 * forced 'fr' locale. Notification EN texts are new translations, reference
 * for future locale-aware mails (current mails force 'fr').
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

    // LOT 7 — WhatsApp replies (WashWhatsAppService). Identical to the
    // original literals; FR-only messages have no EN variant (see header).
    'whatsapp' => [
        'confirmed_stale' => 'Thanks! Your report is recorded. For another issue, send a voice note or describe it in one sentence.',
        'confirmed' => "Perfect, confirmed! Case :ref is being followed by our teams. We'll write here as soon as it moves.",
        'clarify_ask' => 'Sorry! What should I fix? Reply in one sentence: what + where.',
        'clarify_applied' => 'Thanks! I fixed it: :summary. Is this correct?',
        'stale_note' => "I couldn't find your previous report, I'll treat your message as a new report. ",
        'buttons_body' => 'Is this correct? Tap Yes or No.',
        'button_yes' => 'Yes',
        'button_no' => 'No',
        'tts_confirm' => "Thanks! Case :ref recorded: :summary. We'll keep you posted.",
        'created' => "Thanks! Case :ref recorded: :summary. Priority :urgency. Next: our team is notified, we'll write here as soon as it moves.",
        'duplicate' => "Already received! Case :ref is being followed by our teams. Thanks, no need to resend. We'll keep you posted here.",

        // Inline priorities (raw codes, WhatsApp flow) — mirror of the FR map.
        'urgency' => [
            'low' => 'low',
            'medium' => 'medium',
            'high' => 'high',
            'critical' => 'critical',
        ],

        'suivi' => [
            'card' => ':ref — :summary. Status: :human:since. Next step: :next.',
            'since' => ' since :date',
            'status' => [
                'reported' => 'well received, awaiting triage',
                'triaged' => 'acknowledged by our team',
                'assigned' => 'technician assigned',
                'in_progress' => 'team on site',
                'resolved' => 'resolved — please confirm everything works',
                'closed' => 'closed',
            ],
            'next' => [
                'reported' => "triage by our team, we'll write here when it moves",
                'triaged' => "technician assignment, we'll write here when it moves",
                'assigned' => "technician visit planned, we'll write here when done",
                'in_progress' => "fix in progress, we'll write here when done",
                'resolved' => 'please confirm here that all is well, thanks',
                'closed' => 'nothing to do, thanks',
            ],
            'next_fallback' => "we'll write here when it moves",
            'empty' => 'No report yet for your school, describe your issue in one sentence: what + where (e.g. leaking tap in block A).',
            'unknown_reference' => "We can't find reference :ref. Check the code or describe your issue in one sentence: what + where.",
        ],
    ],

    // LOT 7 — conversational personality (WashWhatsAppPersonality).
    'personality' => [
        'greeting' => 'Hello! I am Sentinel, your school water and hygiene assistant. Here you can: 1) report a problem (leaking tap, blocked toilets, no soap...) in one sentence or voice note; 2) track your case ("where is my case?").',
        'identity' => 'I am Sentinel, your school water and hygiene assistant. I collect your reports: leaking tap, broken pump, blocked toilets, no soap... Describe it in one sentence or send a voice note, then track your case here.',
        'capabilities' => 'I am Sentinel, your school water and hygiene assistant. I can: 1) record problems (water, toilets, soap...); 2) track your cases. Ask "where is my case?" with your WASH-... reference for follow-up.',
        'thanks' => 'You are welcome! I am Sentinel, your school water and hygiene assistant. Another problem? Describe it in one sentence (tap, toilets, soap...) and I will take care of it. To track: "where is my case?"',
    ],

    // LOT 7 — mail notifications (reference translations; mails force 'fr').
    'notifications' => [
        'critical' => [
            'subject' => 'CRITICAL incident: :school (:ref)',
            'intro' => 'A critical incident was just reported and triaged by AI.',
            'school' => 'School: :school (:district)',
            'summary' => 'Summary: :summary',
            'priority' => 'Affected pupils: :affected — AI priority: :priority/100',
            'action' => 'View incident',
        ],
        'relance' => [
            'subject' => 'Dormant incident follow-up: :ref (:school)',
            'stale' => 'Incident :ref has been inactive for :days day(s).',
            'school' => 'School: :school (:district)',
            'title' => 'Title: :title',
            'status' => 'Status: :status — AI priority: :priority/100',
            'action' => 'View incident',
        ],
    ],

];
