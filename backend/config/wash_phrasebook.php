<?php

/*
 * WASH Sentinel — phrasebook natif (réponses en langues locales).
 *
 * RÈGLE D'OR : le LLM ne parle NI ghomala' NI douala (vérifié : il répond
 * UNKNOWN quand on l'interroge, il inventerait sinon). Chaque phrase native
 * ci-dessous est donc écrite/collée par un LOCUTEUR HUMAIN, jamais générée.
 * Rendu uniquement si `native` + `validator` non vides (voir WashPhrasebook).
 *
 * Protocole : docs/PHRASEBOOK_NATIF.md (questionnaire 10 phrases pour le
 * locuteur, format attendu, où coller ici + source + nom + date).
 *
 * Slots : :ref (code WASH-...), :status (libellé statut FR/EN affiché tel
 * quel après la phrase native — jamais traduit par machine).
 */

$todo = 'LOCUTEUR REQUIS : traduire la phrase `fr` telle que parlée au village (pas du français déguisé), voir docs/PHRASEBOOK_NATIF.md';

$blank = fn (string $fr) => [
    'fr' => $fr,
    'native' => null,
    'source' => null,
    'validator' => null,
    'validated_at' => null,
    'todo' => $todo,
];

$intents = [
    'greeting' => 'Bonjour ! Ici Sentinel, pour l\'eau et l\'hygiène de votre école.',
    'thanks_case' => 'Merci ! Dossier :ref enregistré.',
    'ask_school' => 'De quelle école parlez-vous ? Dites son nom.',
    'ask_problem' => 'Quel est le problème ? Dites-le en une phrase, par exemple : robinet cassé, plus d\'eau, toilettes bouchées.',
    'ask_photo' => 'Envoyez une photo de la panne si vous pouvez.',
    'suivi_found' => 'Dossier :ref : :status.',
    'suivi_empty' => 'Aucun dossier trouvé pour ce numéro.',
    'not_understood' => 'Pardon, je n\'ai pas compris. Répétez lentement : le nom de l\'école, puis la panne.',
    'duplicate_seen' => 'Déjà reçu ! Dossier :ref suivi par nos équipes.',
    'goodbye' => 'Merci, à bientôt !',
];

$build = fn () => array_map($blank, $intents);

return [
    'version' => '0.1.0',
    'status' => 'EMPTY — locuteurs natifs requis (ghomala\' : grand frère, douala : à trouver)',

    'entries' => [
        // Ghomala' (bbj, Ouest Cameroun) — codes STT : bbj_Latn.
        'bbj_Latn' => $build(),
        // Douala (dua, Littoral Cameroun) — codes STT : dua_Latn.
        'dua_Latn' => $build(),
    ],
];
