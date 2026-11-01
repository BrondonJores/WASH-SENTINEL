"""Corpus de calibration du repli Jaccard (AXE 8).

19 textes distincts (10 goldens test_prompt_eval + 7 résumés test_epidemic +
2 nominaux) -> 171 paires non-doublons, + 8 paires paraphrases (même incident,
rewordings réalistes fixés AVANT le sweep). Total n=179.

La fonction jaccard() est la mesure EXACTE du repli
(DuplicateDetector._fallback_text_match : lower().split() ensembliste).
"""
from __future__ import annotations

GOLDEN_TEXTS = [
    "Il y a une fuite d'eau sur le tuyau principal près du robinet de la cour.",
    "Les latrines des filles sont bouchées et débordent depuis ce matin.",
    "Le forage de l'école est à sec, plus d'eau depuis trois jours.",
    "Le robinet donne une eau jaune et trouble que les enfants boivent.",
    "La pompe manuelle est cassée, elle ne fonctionne plus depuis lundi.",
    "La fuite du château d'eau prive 450 élèves d'eau potable.",
    "Les 320 élèves de l'école boivent une eau sale et contaminée.",
    "Les robinets du point d'eau ont été volés pendant la nuit.",
    "Il y a un problème d'eau à l'école, on ne sait pas trop.",
    "Le match de football inter-écoles aura lieu samedi au stade.",
]

EPIDEMIC_TEXTS = [
    "L'eau du forage est jaune et trouble, six élèves ont eu la diarrhée cette semaine.",
    "Plusieurs cas de diarrhée et de vomissements après avoir bu l'eau du puits de l'école.",
    "Eau jaunâtre au robinet et latrines qui débordent près du point d'eau.",
    "Pompe manuelle bloquée, le levier est cassé, aucune eau ne sort.",
    "Fuite sur le tuyau principal, le réparateur communal est prévenu.",
    "L'eau du robinet a un goût étrange et une légère odeur depuis deux jours.",
    "Eau légèrement trouble à la fontaine de la cour ce matin.",
]

NOMINAL_TEXTS = [
    "Le directeur signale que les toilettes des garçons fuient par le réservoir.",
    "Plus de pression au robinet de la cantine depuis la coupure d'hier soir.",
]

NON_DUP_TEXTS = GOLDEN_TEXTS + EPIDEMIC_TEXTS + NOMINAL_TEXTS

PARAPHRASE_PAIRS = [
    ("La pompe manuelle est cassée, elle ne fonctionne plus depuis lundi.",
     "Pompe manuelle hors service depuis lundi, les élèves pompent dans le vide."),
    ("Les latrines des filles sont bouchées et débordent depuis ce matin.",
     "Depuis ce matin, les WC des filles refoulent et inondent la dalle."),
    ("Le forage de l'école est à sec, plus d'eau depuis trois jours.",
     "Trois jours que le forage ne donne plus une goutte d'eau."),
    ("Le robinet donne une eau jaune et trouble que les enfants boivent.",
     "Les enfants boivent au robinet une eau jaunâtre et sale."),
    ("Il y a une fuite d'eau sur le tuyau principal près du robinet de la cour.",
     "Le tuyau principal de la cour fuit près du robinet, l'eau coule en continu."),
    ("Les robinets du point d'eau ont été volés pendant la nuit.",
     "On a arraché les robinets du point d'eau cette nuit, il n'y a plus rien."),
    ("La fuite du château d'eau prive 450 élèves d'eau potable.",
     "450 élèves sans eau potable à cause du château d'eau qui fuit."),
    ("Pompe manuelle bloquée, le levier est cassé, aucune eau ne sort.",
     "Le levier de la pompe est rompu, la pompe reste bloquée sans eau."),
]


def jaccard(a: str, b: str) -> float:
    """Jaccard ensembliste, miroir exact du repli de duplicate_detector."""
    wa, wb = set(a.lower().split()), set(b.lower().split())
    return len(wa & wb) / float(len(wa | wb))
