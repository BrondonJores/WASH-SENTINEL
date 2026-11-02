<?php

/*
 * LOT 6 — textes FR visibles des propositions agent (AgentProposalService,
 * ProposalGuidanceException). Extraction pure : textes strictement identiques
 * aux littéraux d'origine. Lus avec locale 'fr' forcée (comportement inchangé
 * quelle que soit la locale applicative). Miroir EN : lang/en/wash.php.
 *
 * LOT 7 — canaux WhatsApp/mesh/notifications (WashWhatsAppService,
 * WashWhatsAppPersonality, CriticalIncidentNotification,
 * WashRelanceNotification). Extraction pure : textes strictement identiques
 * aux littéraux d'origine. Clés 'whatsapp.*' lues avec locale forcée
 * ('fr' ou 'en' selon la langue détectée du message) ; clés
 * 'personality.*' et 'notifications.*' en 'fr' forcé par défaut.
 * Blindage cas extrêmes : erreur technique, médias illisibles, hors-sujet,
 * école inconnue, surpoids, type non supporté et numéro non validé ont une
 * variante EN (miroir lang/en/wash.php), servie quand la conversation est
 * en anglais. Seul 'voice_placeholder' reste FR-only (texte interne).
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

    // LOT 7 — réponses WhatsApp (WashWhatsAppService). Textes identiques
    // aux littéraux d'origine ; :ref :summary :urgency :school :human
    // :since :next :date sont interpolés par le service.
    'whatsapp' => [
        'error_technical' => "*Oups*, un problème technique nous empêche de traiter votre message. Réessayez dans quelques minutes, merci !",
        'unreadable_audio' => "On n'a pas compris votre note vocale. *Réenregistrez au calme, près du micro* : dites votre école + la panne (ex. robinet cassé au bloc A). Merci !",
        'unreadable_photo' => "La photo n'est pas arrivée jusqu'à nous. *Renvoyez-la avec une phrase* : école + panne (ex. fuite au bloc A). Merci !",
        'confirmed_stale' => 'Merci ! Votre signalement est bien *enregistré*. Pour un autre problème, envoyez une note vocale ou décrivez-le en une phrase.',
        'confirmed' => "Parfait, c'est confirmé ! Incident *:ref* suivi par nos équipes. On vous écrit ici dès que ça avance.",
        'clarify_ask' => 'Désolé ! *Que dois-je corriger ?* Répondez en une phrase : quoi + où.',
        'clarify_applied' => "Merci ! J'ai corrigé : :summary. *C'est bien ça ?*",
        'stale_note' => "Je n'ai pas retrouvé votre signalement précédent, je traite votre message comme un *nouveau signalement*. ",
        'buttons_body' => "C'est bien ça ? Touchez *Oui* ou *Non*.",
        'button_yes' => 'Oui',
        'button_no' => 'Non',
        'tts_confirm' => "Merci ! Incident *:ref* enregistré : :summary. On vous tient au courant.",
        'unknown_school_ecole' => "Merci ! On a bien noté « :school ». Mais ce numéro n'est rattaché à *aucune école* pour l'instant : demandez au directeur de l'enregistrer, puis réécrivez-nous.",
        'unknown_school' => "Bonjour ! Ce numéro n'est rattaché à *aucune école* WASH Sentinel. De quelle école parlez-vous ? Envoyez : *ECOLE Nom de votre école*. On vous aidera à l'enregistrer.",
        'off_topic' => "Merci pour votre message ! Ici on signale *l'eau et l'hygiène à l'école* : ex. robinet qui fuit, toilettes bouchées, plus de savon. Décrivez votre panne en une phrase.",
        'created' => "Merci ! Incident *:ref* enregistré : :summary.\n*Priorité :* :urgency.\nLa suite : notre équipe est notifiée, on vous écrit ici dès que ça avance.",
        'duplicate' => "*Déjà reçu !* Incident *:ref* suivi par nos équipes. Merci, pas besoin de renvoyer. On vous tient au courant ici.",
        'oversized_audio' => '*Note trop lourde*, renvoie plus court : réenregistre ta note vocale au calme, près du micro — école + panne en une phrase (ex. robinet cassé au bloc A). Merci !',
        'oversized_photo' => '*Photo trop lourde*, renvoie une photo plus légère avec une phrase : école + panne (ex. fuite au bloc A). Merci !',
        'voice_placeholder' => '[message vocal]',
        'unsupported' => "Je ne peux pas lire ce genre de message (sticker, position, fichier...). *Décris ta panne en une phrase ou envoie une note vocale* : école + panne (ex. robinet cassé au bloc A). Merci !",
        'unverified' => "Ton numéro est enregistré mais *pas encore validé*. Demande au directeur de valider ton numéro, puis réécris-nous. Merci !",

        // Priorités inline (minuscules, flux WhatsApp) — distinctes de
        // 'urgencies' (capitalisées, récapitulatifs agent LOT 6).
        'urgency' => [
            'low' => 'basse',
            'medium' => 'moyenne',
            'high' => 'haute',
            'critical' => 'critique',
        ],

        'suivi' => [
            'card' => "📁 *Dossier :ref*\n:summary\n\n*Statut :* :human:since",
            'since' => ' depuis le :date',
            'status' => [
                'reported' => 'bien reçu, en attente de tri',
                'triaged' => 'pris en compte par notre équipe',
                'assigned' => 'technicien assigné',
                'in_progress' => 'équipe en intervention',
                'resolved' => 'résolu — merci de confirmer que tout marche',
                'closed' => 'clôturé',
            ],
            'next' => [
                'reported' => "tri par notre équipe, on vous écrit ici dès que ça avance",
                'triaged' => "assignation d'un technicien, on vous écrit ici dès que ça avance",
                'assigned' => "intervention du technicien prévue, on vous écrit ici dès que c'est fini",
                'in_progress' => "réparation en cours, on vous écrit ici dès que c'est fini",
                'resolved' => 'confirmez ici que tout marche, merci',
                'closed' => 'rien à faire, merci',
            ],
            'next_fallback' => "on vous écrit ici dès que ça avance",
            'empty' => "Aucun signalement pour l'instant pour votre école. Décrivez votre panne en une phrase : *quoi + où* (ex. robinet qui fuit au bloc A).",
            'unknown_reference' => "On ne retrouve pas la référence *:ref*. Vérifiez le code ou décrivez votre panne en une phrase : quoi + où.",
            // Suivi guidé (un seul slot demandé à la fois, choix numérotés).
            'ask_id' => "Pour suivre votre dossier, envoyez son *numéro WASH* (ex. WASH-2026-ABC123). Il est dans mon message après votre signalement. Si vous ne l'avez pas, répondez *NON*.",
            'ask_school' => "Pas de problème ! De quelle *école* parlez-vous ? Répondez son nom (ex. Bonanjo).",
            'ask_school_retry' => "Je ne trouve pas cette école. Répondez le *nom de votre école* (ex. Bonanjo).",
            'ask_school_precision' => 'Plusieurs écoles ont ce nom. Répondez le *nom complet* : :schools.',
            'ask_date' => "Merci ! *Quel jour* avez-vous signalé la panne ? Répondez *AUJOURD'HUI*, *HIER*, ou le jour (ex. le 2).",
            'ask_date_retry' => "Je n'ai pas compris le jour. Répondez *AUJOURD'HUI*, *HIER*, ou le jour (ex. le 2).",
            'propose_intro' => "J'ai trouvé *:count* dossier(s) pour *:school* le :date :",
            'propose_intro_generic' => 'Plusieurs dossiers correspondent. Répondez le *NUMÉRO* (ex. 1) ou le *code WASH* :',
            'propose_hint' => 'Répondez le *NUMÉRO* (ex. 1) ou le *code WASH*.',
            'invalid_choice' => "Je n'ai pas compris. Répondez le *NUMÉRO* du dossier (1, 2...) ou son *code WASH*. Voici la liste :",
            'no_match' => "Aucun dossier pour *:school* le :date. Essayez un autre jour : *HIER*, *AUJOURD'HUI* ou le jour (ex. le 2).",
            'cancelled' => "D'accord, on arrête le suivi.\n• *Signaler* : décrivez la panne en une phrase.\n• *Suivre* : écrivez « suivre mon dossier ».",
            'details' => "\n*École :* :school\n*Signalé le :* :date\n*Urgence :* :urgency\n\n_Prochaine étape : :next._",
        ],
    ],

    // LOT 7 — personnalité conversationnelle (WashWhatsAppPersonality).
    'personality' => [
        'greeting' => "Bonjour ! Je suis *Sentinel*, l'assistant eau et hygiène de votre école. Ici vous pouvez :\n• *Signaler* une panne (robinet qui fuit, toilettes bouchées, plus de savon...) en une phrase ou note vocale\n• *Suivre* votre dossier (« où en est mon dossier ? »)",
        'identity' => "Je suis *Sentinel*, l'assistant eau et hygiène de votre école. Je reçois vos signalements : robinet qui fuit, pompe cassée, toilettes bouchées, plus de savon...\nDécrivez la panne en une phrase ou envoyez une note vocale, puis suivez votre dossier ici.",
        'capabilities' => "Je suis *Sentinel*, l'assistant eau et hygiène de votre école. Je peux :\n• *Enregistrer* vos pannes (eau, toilettes, savon...)\n• *Suivre* vos dossiers (« où en est mon dossier ? » ou votre référence WASH-...)",
        'thanks' => "Avec plaisir ! *Sentinel* reste à votre service : autre panne ? *Décrivez-la en une phrase* (robinet, toilettes, savon...) et je m'en occupe. Pour suivre : « où en est mon dossier ? ».",
    ],

    // LOT 7 — notifications mail (locale 'fr' forcée, comportement inchangé).
    'notifications' => [
        'critical' => [
            'subject' => 'Incident CRITIQUE : :school (:ref)',
            'intro' => "Un incident critique vient d'être signalé et trié par l'IA.",
            'school' => 'École : :school (:district)',
            'summary' => 'Résumé : :summary',
            'priority' => 'Élèves affectés : :affected — Priorité IA : :priority/100',
            'action' => "Voir l'incident",
        ],
        'relance' => [
            'subject' => 'Relance incident dormant : :ref (:school)',
            'stale' => "L'incident :ref est sans activité depuis :days jour(s).",
            'school' => 'École : :school (:district)',
            'title' => 'Titre : :title',
            'status' => 'Statut : :status — Priorité IA : :priority/100',
            'action' => "Voir l'incident",
        ],
    ],

];
