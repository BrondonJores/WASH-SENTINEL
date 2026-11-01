"""Source unique des seuils calibrés de l'AXE 8 + inventaire global (2026-11-01).

Inventaire exhaustif des seuils/constantes magiques de ``app/`` et statut AXE 8
(``calibré`` = ajusté sur seeds avec chiffres ci-dessous ; ``conservé`` = les
données ne contredisent pas la valeur ; ``hérité`` = aucun seed ne permet de
trancher, valeur historique inchangée) :

===========================  ========  =====================================
Seuil (fichier)              Valeur    Statut AXE 8
===========================  ========  =====================================
Doublons — décision cosinus  0.80      hérité (embeddings réels requis ;
(thresholds/duplic./schemas)           0 seed mesurable hors mocks)
Doublons — liste matches     0.70      hérité (idem)
Doublons — repli Jaccard      0.25      CALIBRÉ (était 0.50 ; P/R/F1 infra)
Router MARGIN_MIN            0.15      conservé (sweep 31 cas : 31/31 sur
                                        tout le plateau 0.00-0.40)
Router CREATE_MIN_SCORE      1.0       conservé (plateau 0.0-2.5 : 31/31)
Router DATA_MIN_SCORE        1.0       conservé (labels 31/31 sur tout
                                        le plateau 0.0-1.5 ; heuristique
                                        large voulue)
Router _STEM_GAP_MAX         3         conservé (0-1 cassent 1 cas, 2+ : 31/31)
Lieux PLACE_CUTOFF           0.75      conservé (sweep 40 cas, déjà épinglé
(textnorm/place_suggest)                par tests/test_place_threshold.py)
Épidémie fenêtre (j)         7         conservé (borne incluse par fixture ;
CLUSTER_WINDOW_DAYS                     incubation choléra + délai terrain)
Épidémie OUTBREAK (écoles)   3         conservé (fixtures a/b/c + négation)
Épidémie HIGH (écoles)       2         conservé (idem, n=7 fixtures)
Équité poids eau/urg/genre/  30/25/    hérité (aucun seed d'équité ;
isolement (%)                 25/20     politique publique, pas de vérité
Équité normalisations        20j/70km/ terrain disponible)
(/20, /70, /18, /4, clamp     18m/4WC,
0.3-0.7)                      ...
Équité tournées (≤18 km,     18.0/     hérité (aucun seed logistique)
×1.6, max 2 embarquées)       1.6/2
Extracteur priorité          35/35/30  hérité (aucun seed de priorité ;
poids + tables urgence/       ...      goldens = catégories, pas scores)
risque + cap 1000 élèves
Extracteur confiance         0.90 -    hérité (pénalités 0.15/0.10/0.05/
(base - pénalités)            ...       0.20, clamp 0.05-0.95 ; sans seed)
Décision remplacer/réparer   55%/4/    hérité (seuils financiers métier,
(ratio/pannes/jours)          30j       sans historique Laravel)
RAG MIN_SIMILARITY           0.30      hérité (sans corpus annoté)
Agent MAX_ITERATIONS         5         hérité (garde-fou boucle)
Divers (negation 3 tok,      ...       hérité (couverts par tests
district min 4 car., spike             comportementaux, pas de sweep)
≥3, heatmap 90 j, trend
±0.15, RMS 0.02/0.15)
===========================  ========  =====================================

Calibration Jaccard (le seul seuil contredit par les données) :
- Corpus : 171 paires non-doublons (19 textes distincts : 10 goldens
  tests/test_prompt_eval.py + 7 résumés tests/test_epidemic.py + 2 textes
  nominaux) et 8 paires paraphrases (même incident, rewordings réalistes
  fixés AVANT le sweep, cf. tests/fixtures_duplicates.py). Total n=179.
- Mesure : Jaccard ensembliste identique au repli (lower().split()).
- Non-doublon le plus dur : 4/18 = 0.222 (pompe cassée vs pompe bloquée,
  panne différente sur même famille d'équipement). Paraphrase la plus
  faible captée : 0.250 (vol de robinets rewordé).
- À 0.50 (ancien) : TP=0 FP=0 FN=8 → P=1.00 R=0.00 F1=0.00 (le repli ne
  servait quasiment jamais).
- À 0.25 (nouveau) : TP=5 FP=0 FN=3 → P=1.00 R=0.625 F1=0.77.
- 0.25 est la borne haute inclusive de l'intervalle de séparation
  (0.222, 0.250] : marge 0.028 au-dessus du non-doublon max, choix
  pro-précision cohérent avec PLACE_CUTOFF.
- Limite résiduelle documentée : 3 paraphrases à fort rewording (Jaccard
  0.150-0.222) chevauchent la plage des non-doublons (≤0.222) : AUCUN seuil
  Jaccard ne les sépare. Rappel plafonné à 0.625 en mode dégradé ; le chemin
  nominal (embeddings cosinus) les traite. Voir tests/test_threshold_calibration.py.

Ce module ne dépend d'aucun autre module ``app`` (importable partout, y
compris depuis schemas.py, sans cycle).
"""
from __future__ import annotations

#: Décision doublon sur similarité cosinus (chemin nominal, embeddings).
#: Hérité, NON calibré : aucun seed ne fournit de vrais vecteurs (les tests
#: mockent les embeddings). Cohérent avec l'appelant Laravel (threshold=0.80).
DUPLICATE_DECISION_THRESHOLD = 0.80

#: Inscription en liste ``matches`` (cosinus). Hérité, NON calibré (idem).
#: Les matches sous le seuil de décision sont marqués "moderate".
DUPLICATE_MATCH_CUTOFF = 0.70

#: Repli textuel Jaccard (embeddings indisponibles). CALIBRÉ AXE 8 :
#: 0.50 -> 0.25 (P=1.00 R=0.625 F1=0.77 sur n=179 paires, vs R=0.00 avant).
DUPLICATE_JACCARD_FALLBACK = 0.25
