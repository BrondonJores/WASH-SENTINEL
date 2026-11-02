# Phrasebook natif — protocole locuteur (ghomala' + douala)

## Pourquoi ce document ?

Le LLM (Llama/Qwen, même l'API Meta) **ne parle pas ghomala' ni douala** :
interrogé, il répond UNKNOWN — et inventerait des faux mots si on le forçait.
Donc les réponses WhatsApp en langues locales ne sont **jamais générées** :
elles sont écrites par un **locuteur humain**, relues, puis collées dans
`backend/config/wash_phrasebook.php` avec son nom + la date.

Effet une fois rempli : l'usager qui envoie un vocal ghomala' reçoit
**sa langue d'abord, puis le français** (bilingue, sans risque).

## Questionnaire : 10 phrases à traduire

Consignes pour le locuteur :

1. Traduire **comme parlé au village** (oral naturel, pas du français déguisé).
2. Garder les codes tels quels : `:ref` (ex. WASH-2026-AB12CD), `:status`.
3. Pour chaque phrase : **écrire le texte + envoyer un vocal WhatsApp** qui lit
   exactement ce texte (référence audio pour les tests STT).
4. Numéroter les réponses 1-10.

| # | Intent | Phrase FR source |
|---|--------|------------------|
| 1 | greeting | Bonjour ! Ici Sentinel, pour l'eau et l'hygiène de votre école. |
| 2 | thanks_case | Merci ! Dossier :ref enregistré. |
| 3 | ask_school | De quelle école parlez-vous ? Dites son nom. |
| 4 | ask_problem | Quel est le problème ? Dites-le en une phrase, par exemple : robinet cassé, plus d'eau, toilettes bouchées. |
| 5 | ask_photo | Envoyez une photo de la panne si vous pouvez. |
| 6 | suivi_found | Dossier :ref : :status. |
| 7 | suivi_empty | Aucun dossier trouvé pour ce numéro. |
| 8 | not_understood | Pardon, je n'ai pas compris. Répétez lentement : le nom de l'école, puis la panne. |
| 9 | duplicate_seen | Déjà reçu ! Dossier :ref suivi par nos équipes. |
| 10 | goodbye | Merci, à bientôt ! |

Statut :
- ghomala' (`bbj_Latn`) : attendu du grand frère (dispo pour les tests).
- douala (`dua_Latn`) : locuteur à trouver.

## Intégration (dev)

Pour chaque phrase reçue, dans `backend/config/wash_phrasebook.php` :

```php
'thanks_case' => [
    'fr' => 'Merci ! Dossier :ref enregistré.',
    'native' => '<phrase du locuteur, copiée telle quelle>',
    'source' => 'WhatsApp vocal + texte, <date>',
    'validator' => '<nom du locuteur>',
    'validated_at' => '<AAAA-MM-JJ>',
],
```

Règles :

- `native` non vide **exige** `validator` non vide (testé :
  `WashPhrasebookTest::test_no_validator_means_no_render`).
- Ne jamais retoucher la phrase du locuteur (« corriger » = inventer).
- Commit séparé par langue : `feat(phrasebook): <lang> 10/10 validées par <nom>`.

## Vérification

1. `php artisan test --filter="WashPhrasebookTest"` (4 tests).
2. Test live : envoyer un vocal dans la langue au numéro WhatsApp test →
   la réponse commence par la phrase native, suivie du français.
