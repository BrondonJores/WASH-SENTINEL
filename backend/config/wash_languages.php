<?php

/*
 * WASH Sentinel — détection de langue des TEXTES WhatsApp (FR/EN).
 *
 * Source unique pilotée par données : WashWhatsAppService ne contient plus
 * aucune liste de marqueurs en dur, il lit ce fichier (config wash_languages).
 *
 * AUDIT (ancien code : 4 constantes + 5 méthodes) :
 * - flux « reply » (signalement) : marqueurs FR larges (suivi + salutations
 *   + mots eau/hygiène) en VETO — un message mélangé FR/EN reste en français
 *   (langue par défaut) ; marqueurs EN génériques sinon. Appariement par
 *   frontières de mot (« bloc » ≠ « block », « tap » ≠ « taper »).
 * - flux « suivi » : marqueurs FR/EN courts, appariement par sous-chaîne
 *   (historique, conservé à l'identique).
 * - bascules : EN si marqueurs EN (reply OU suivi) ; FR si marqueur FR
 *   explicite ; sinon on GARDE la langue mémorisée (un slot neutre — « 2 »,
 *   « NON », nom d'école — n'écrase jamais une conversation EN).
 * - NOUVEAU : issue INCERTAIN — aucun marqueur net → pas de bascule au
 *   hasard : on garde la langue mémorisée et, seulement si AUCUNE langue
 *   n'est mémorisée, on demande poliment (clé « ask », FR simple + EN).
 *   Le choix FR/EN est persisté (codes stables, voir « codes »).
 *
 * Hors scope (volontairement hors de ce fichier) : intention suivi
 * (SUIVI_KEYWORDS), filtre eau/hygiène (WASH_KEYWORDS), stop-mots
 * (SUIVI_PARTIAL_STOPWORDS) — ce ne sont pas de la détection de langue.
 */

return [

    // Langue de réponse quand rien ne tranche (conversations existantes).
    'default' => 'fr',

    // Codes stables proposés à l'usager et persistés (FR ou EN suffit).
    'codes' => ['fr', 'en'],

    // Veto : langue gagnante quand les DEUX ont des marqueurs (mélange FR/EN).
    'veto' => 'fr',

    // Seuil : nb min de marqueurs DISTINCTS pour trancher une langue.
    'min_markers' => 1,

    // Demande polie (FR simple + EN) si incertain SANS langue mémorisée.
    'ask' => 'En quelle langue préférez-vous continuer ? Répondez FR ou EN. / Which language do you prefer? Reply FR or EN.',

    // Flux signalement : veto FR élargi, frontières de mot (« bloc » ≠ « block »).
    'reply' => [
        'match' => 'word',
        'french_markers' => [
            'suivi', 'suivre', 'statut', 'où en est', 'ou en est',
            'mon signalement', 'mes signalements', 'mon dossier',
            'avancé', 'avance', 'réparé', 'reparé', 'répare', 'repare',
            'bonjour', 'bonsoir', 'salut', 'merci',
            'eau', 'robinet', 'fuite', 'fuites', 'fuit', 'pompe', 'forage',
            'puits', 'toilette', 'toilettes', 'latrine', 'latrines', 'douche',
            'savon', 'hygiène', 'hygiene', 'égout', 'egout',
            'bouché', 'bouchée', 'bouchés', 'bouchées',
            'cassé', 'cassée', 'cassés', 'casse', 'panne',
            'réparation', 'reparation', 'bloc', 'coule', 'coulent',
            'goutte', 'gouttes', 'marche',
        ],
        'english_markers' => [
            'hello', 'good morning', 'good afternoon', 'good evening',
            'this is', 'thank', 'thanks', 'please', 'sorry',
            'school', 'pupil', 'pupils', 'student', 'students', 'teacher',
            'water', 'tap', 'taps', 'leak', 'leaks', 'leaking', 'leakage',
            'toilet', 'toilets', 'pipe', 'pipes', 'pump', 'borehole',
            'soap', 'drink', 'drinking', 'flush', 'tank',
            'block', 'blocks', 'broken', 'dirty', 'smell', 'shortage',
            'hygiene', 'sanitation', 'sewage',
        ],
    ],

    // Flux suivi : listes courtes, sous-chaîne (comportement historique).
    'suivi' => [
        'match' => 'contains',
        'french_markers' => [
            'suivi', 'suivre', 'statut', 'où en est', 'ou en est',
            'mon signalement', 'mes signalements', 'mon dossier',
            'avancé', 'avance', 'réparé', 'reparé', 'répare', 'repare',
        ],
        'english_markers' => [
            'where is', 'my report', 'track', 'tracking',
            'follow up', 'follow-up', 'followup',
        ],
    ],

];
