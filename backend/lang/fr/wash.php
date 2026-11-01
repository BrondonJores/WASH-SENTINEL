<?php

/*
 * LOT 6 — textes FR visibles des propositions agent (AgentProposalService,
 * ProposalGuidanceException). Extraction pure : textes strictement identiques
 * aux littéraux d'origine. Lus avec locale 'fr' forcée (comportement inchangé
 * quelle que soit la locale applicative). Miroir EN : lang/en/wash.php.
 */
return [

    'categories' => [
        'water_point' => "Point d'eau",
        'toilets_latrines' => 'Toilettes / latrines',
        'handwashing' => 'Lavage des mains',
        'sewage_drainage' => 'Évacuation / drainage',
    ],

    'urgencies' => [
        'low' => 'Basse',
        'medium' => 'Moyenne',
        'high' => 'Haute',
        'critical' => 'Critique',
    ],

    'proposal' => [
        'unknown_action' => 'Action inconnue.',
        'permission_required' => 'Permission « :permission » requise.',
        'description_required' => 'Description requise (:max caractères max).',
        'title_required' => 'Titre requis (:min à :max caractères).',
        'incident_not_found' => 'Incident introuvable, précisez son numéro ou sa référence.',
        'cost_required' => 'Coût requis, en XAF, positif.',
        'notes_too_long' => 'Notes limitées à :max caractères.',
        'days_invalid' => 'Jours sans service invalides.',
        'school_not_found' => 'École introuvable, précisez son nom.',
        'enum_invalid' => 'Valeur invalide pour :key.',
        'int_invalid' => 'Nombre invalide pour :key.',

        'cancelled' => "Proposition annulée, rien n'a été créé.",
        'redraft_label' => 'Refaire la demande',
        'redraft_default' => 'Refais ma demande',
        'redraft_report' => 'Signale :where: :description',
        'redraft_incident' => 'Crée une intervention :where: :title',
        'redraft_log' => 'Journalise :cost XAF sur :ref',
        'redraft_at_school' => 'à :school',
        'redraft_a_problem' => 'un problème',
        'redraft_no_title' => 'sans titre',
        'redraft_the_incident' => "l'incident",

        'report_attached' => 'Signalement #:id rattaché à l\'incident :ref (doublon détecté).',
        'report_created' => 'Signalement #:id créé, incident :ref (:urgency).',
        'incident_created' => 'Intervention :ref créée : :title.',
        'log_created' => 'Intervention journalisée sur :ref : :cost XAF.',

        'recap_missing' => '—',
        'recap_school' => 'École',
        'recap_description' => 'Description',
        'recap_category' => 'Catégorie',
        'recap_urgency' => 'Urgence',
        'recap_affected' => 'Élèves affectés',
        'recap_title' => 'Titre',
        'recap_incident' => 'Incident',
        'recap_cost' => 'Coût',
        'recap_notes' => 'Notes',
        'recap_days' => 'Jours sans service',
    ],

    'guidance' => [
        'expired' => 'Ce dossier a expiré (:minutes min). Redemandez un récapitulatif : « :prompt ».',
        'redraft_label' => 'Refaire la demande',
        'already_done' => 'Déjà enregistré ! ',
        'already_validated' => 'Cette demande a déjà été validée. ',
        'already_see' => 'Voir : :ref.',
        'already_nothing' => "Rien de plus à valider.",
        'already_show_prompt' => 'Affiche le dossier :ref',
        'already_show_label' => 'Voir le dossier',
        'conflict' => "Quelqu'un l'a déjà traité : cette demande a été annulée et rien n'a été créé. Si besoin, refaites la demande : « :prompt ».",
        'refused' => "Action refusée : :reason Rien n'a été créé. Vérifiez votre rôle ou demandez à un administrateur.",
        'refused_label' => 'Voir mes actions possibles',
        'refused_prompt' => 'Que puis-je faire avec mon rôle ?',
        'owner_mismatch' => "Cette proposition appartient à un autre utilisateur. Rien n'a été créé sur votre compte.",
    ],

];
