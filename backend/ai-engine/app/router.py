"""Routage déterministe liste/création/autre (pur, sans appel LLM).

Remplace les tests de sous-chaîne bruts (``h in lowered``) par un appariement
sur tokens : normalisation sans accents + frontières de mots. Cela tue les
familles de collision « ou »-dans-« cour », « note »-dans-« notebook » ou
« date »-dans-« update », tout en gardant le vocabulaire historique
(migré depuis agent_loop LIST/CREATE/DATA_QUESTION_HINTS).

Chaque entrée porte un poids ; route() renvoie l'intent gagnant avec sa
confiance, sa marge et les raisons (tokens déclencheurs) pour les logs.
Règle conservée : en ambiguïté liste+création, la consultation gagne
(tiebreak explicite et journalisé au lieu de la règle implicite).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

IntentLabel = Literal["list", "create", "other"]

#: Écart minimal top1-top2 exigé pour un routage franc (sinon tiebreak/autre).
MARGIN_MIN = 0.15
#: Score minimal pour router « create » (évite les routages sur un indice faible).
CREATE_MIN_SCORE = 1.0
#: Score minimal pour considérer un message « question de données ».
DATA_MIN_SCORE = 1.0
#: Marqueurs de temps passé : forcent le tiebreak vers la consultation.
PAST_TIME_MARKERS = frozenset({
    "hier", "semaine", "semaines", "mois", "historique", "realise",
    "realisee", "realisees", "realises", "passe", "passee", "passees",
})


def normalize(text: str) -> str:
    """Minuscules sans accents pour comparer les messages (tokens)."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return folded.lower()


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Tokens alphanumériques normalisés (apostrophes/casse/accents neutralisés)."""
    return _TOKEN_RE.findall(normalize(text or ""))


def _joined(tokens: list[str]) -> str:
    return f" {' '.join(tokens)} "


# --- Tables de traits : (forme normalisée, poids, multi-mot ?) ---
# Vocabulaire migré des LIST/CREATE/DATA_QUESTION_HINTS historiques
# d'agent_loop (minuscules, accents repliés) + bigrammes explicites.

def _phrase(form: str) -> str:
    return " ".join(tokenize(form))


LIST_FEATURES: tuple[tuple[str, float], ...] = tuple(
    (form, weight)
    for form, weight in [
        # Indice forts : passé explicite.
        ("realise", 2.0),
        ("aujourdhui", 2.0),
        (_phrase("aujourd'hui"), 2.0),
        ("hier", 2.0),
        ("historique", 2.0),
        ("passe", 2.0),
        ("combien", 2.0),
        ("liste", 2.0),
        ("lister", 2.0),
        (_phrase("quels travaux"), 2.0),
        (_phrase("autre date"), 2.0),
        (_phrase("quel jour"), 2.0),
        (_phrase("cette semaine"), 2.0),
        # Indices moyens : verbes de consultation / repères temporels.
        ("semaine", 1.0),
        ("mois", 1.0),
        ("affiche", 1.5),
        ("montre", 1.5),
        ("voir", 1.0),
        ("date", 1.0),
    ]
)

CREATE_FEATURES: tuple[tuple[str, float], ...] = tuple(
    (form, weight)
    for form, weight in [
        ("cree", 2.0),
        ("creer", 2.0),
        ("creation", 2.0),
        ("ajoute", 2.0),
        ("ajout", 1.5),
        ("ajouter", 2.0),
        ("nouveau", 1.0),
        ("nouvelle", 1.0),
        ("journalise", 2.0),
        ("journaliser", 2.0),
        ("enregistre", 2.0),
        ("enregistrer", 2.0),
        ("enregistrement", 2.0),
        ("signale", 2.0),
        ("signaler", 2.0),
        ("declare", 2.0),
        ("prepare", 2.0),
        ("planifie", 2.0),
        ("note", 1.5),
        # Formes impératives nues avec objet direct.
        (_phrase("enregistre une"), 2.0),
        (_phrase("enregistre des"), 2.0),
        (_phrase("enregistre l'"), 2.0),
        (_phrase("enregistre la"), 2.0),
        (_phrase("enregistre le"), 2.0),
        (_phrase("note une"), 2.0),
        (_phrase("note les"), 2.0),
        (_phrase("note des"), 2.0),
        (_phrase("note la"), 2.0),
        (_phrase("note le"), 2.0),
        (_phrase("ajoute une"), 2.0),
        (_phrase("ajoute des"), 2.0),
        (_phrase("ajoute la"), 2.0),
        (_phrase("ajoute le"), 2.0),
        (_phrase("cree une"), 2.0),
        (_phrase("signale une"), 2.0),
        (_phrase("declare une"), 2.0),
        (_phrase("journalise une"), 2.0),
        (_phrase("journalise des"), 2.0),
        # Mise à jour du journal (formulation complète, sans ambiguïté).
        (_phrase("mets à jour le journal"), 2.0),
        (_phrase("met à jour le journal"), 2.0),
        (_phrase("mettre à jour le journal"), 2.0),
        (_phrase("mise à jour du journal"), 2.0),
        (_phrase("actualise le journal"), 2.0),
        (_phrase("actualiser le journal"), 2.0),
        (_phrase("maj le journal"), 2.0),
        (_phrase("mets a jour"), 1.5),
    ]
)

#: Poids des indices plugins (consultation) : un seul suffit à router « list ».
PLUGIN_FEATURE_WEIGHT = 2.0

DATA_FEATURES: tuple[tuple[str, float], ...] = tuple(
    (form, weight)
    for form, weight in [
        ("quel", 1.0),
        ("combien", 1.5),
        ("liste", 1.5),
        ("montre", 1.5),
        ("affiche", 1.5),
        ("carte", 1.0),
        ("tendance", 1.0),
        ("analyse", 1.0),
        ("resume", 1.0),
        ("briefing", 1.0),
        ("diaporama", 1.0),
        ("ou", 1.0),
        ("etat", 1.0),
        ("besoin", 1.0),
        ("aide", 1.0),
        ("panne", 1.0),
        ("incident", 1.0),
        ("ecole", 1.0),
        ("district", 1.0),
        ("graphique", 1.0),
        ("graphe", 1.0),
        ("cout", 1.0),
        ("budget", 1.0),
        ("intervention", 1.0),
        ("repar", 1.0),
        ("reparation", 1.0),
        ("remplac", 1.0),
        ("signal", 1.0),
        ("signalement", 1.0),
        ("cre", 1.0),
        ("cree", 1.0),
        ("creation", 1.0),
        ("ajoute", 1.0),
        ("enregistre", 1.0),
        ("enregistrement", 1.0),
        ("journalis", 1.0),
        ("declare", 1.0),
    ]
)

#: Écart de longueur max pour l'appariement radical/token
#: (« realise » matche « realisees » mais « note » ne matche pas « notebook »).
_STEM_GAP_MAX = 3


def _match_word(word: str, tokens: list[str]) -> str | None:
    """Forme déclencheuse si le mot/radical matche un token, sinon None.

    Mot entier d'abord, sinon préfixe de token avec un écart de longueur
    borné (flexions). Les formes très courtes (<= 3 lettres) exigent un
    mot entier : « ou » ne matche pas « cour ».
    """
    for token in tokens:
        if token == word:
            return token
        if (
            len(word) > 3
            and token.startswith(word)
            and len(token) - len(word) <= _STEM_GAP_MAX
        ):
            return token
    return None


def _score_table(
    table: tuple[tuple[str, float], ...],
    tokens: list[str],
    joined: str,
) -> tuple[float, list[str]]:
    """Score pondéré + raisons (une par entrée déclenchée, sans doublon)."""
    score = 0.0
    reasons: list[str] = []
    for form, weight in table:
        if " " in form:
            if f" {form} " in joined:
                score += weight
                reasons.append(form)
        else:
            hit = _match_word(form, tokens)
            if hit is not None:
                score += weight
                reasons.append(form if hit == form else f"{form}~{hit}")
    return score, reasons


def _score_plugin_hints(
    tokens: list[str],
    joined: str,
    plugin_hints: dict[str, frozenset[str]] | None,
) -> tuple[float, list[str]]:
    """Score des indices plugins (consultation), même appariement par tokens."""
    if not plugin_hints:
        return 0.0, []
    score = 0.0
    reasons: list[str] = []
    for _name, hints in plugin_hints.items():
        for hint in hints:
            form = " ".join(tokenize(hint))
            if not form:
                continue
            if " " in form:
                if f" {form} " in joined:
                    score += PLUGIN_FEATURE_WEIGHT
                    reasons.append(form)
            elif _match_word(form, tokens) is not None:
                score += PLUGIN_FEATURE_WEIGHT
                reasons.append(form)
    return score, reasons


def route(
    question: str,
    plugin_hints: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """Route calibré : {intent, confidence, margin, reasons, scores}.

    intent = argmax pondéré ; confiance = part normalisée ; marge =
    écart top1-top2. Sous le seuil (marge faible ou score création
    insuffisant) -> « other » (jeu d'outils complet, sans masquage).
    En ambiguïté liste+création, la consultation gagne (tiebreak
    explicite, raison journalisée) : règle historique conservée.
    """
    tokens = tokenize(question)
    joined = _joined(tokens)
    list_score, list_reasons = _score_table(LIST_FEATURES, tokens, joined)
    plugin_score, plugin_reasons = _score_plugin_hints(tokens, joined, plugin_hints)
    list_score += plugin_score
    list_reasons.extend(f"plugin:{r}" for r in plugin_reasons)
    create_score, create_reasons = _score_table(CREATE_FEATURES, tokens, joined)
    data_score, _ = _score_table(DATA_FEATURES, tokens, joined)

    reasons = [f"list:{r}" for r in list_reasons] + [f"create:{r}" for r in create_reasons]
    scores = {"list": round(list_score, 2), "create": round(create_score, 2)}
    total = list_score + create_score
    if total <= 0:
        return {
            "intent": "other",
            "confidence": 0.0,
            "margin": 0.0,
            "reasons": [],
            "scores": scores,
            "data_score": round(data_score, 2),
        }
    top, second = (
        (list_score, create_score)
        if list_score >= create_score
        else (create_score, list_score)
    )
    confidence = round(top / total, 3)
    margin = round((top - second) / total, 3) if total else 0.0

    if list_score > 0 and create_score > 0:
        # Ambiguïté : la consultation gagne (règle historique explicite).
        past = sorted(set(tokens) & PAST_TIME_MARKERS)
        tiebreak = f"tiebreak:list-wins-on-ambiguity:{'+'.join(past)}" if past else (
            "tiebreak:list-wins-on-ambiguity"
        )
        return {
            "intent": "list",
            "confidence": confidence,
            "margin": margin,
            "reasons": reasons + [tiebreak],
            "scores": scores,
            "data_score": round(data_score, 2),
        }
    if create_score > 0:
        if create_score < CREATE_MIN_SCORE or margin < MARGIN_MIN:
            return {
                "intent": "other",
                "confidence": confidence,
                "margin": margin,
                "reasons": reasons + ["below-threshold:create"],
                "scores": scores,
                "data_score": round(data_score, 2),
            }
        return {
            "intent": "create",
            "confidence": confidence,
            "margin": margin,
            "reasons": reasons,
            "scores": scores,
            "data_score": round(data_score, 2),
        }
    if margin < MARGIN_MIN:
        return {
            "intent": "other",
            "confidence": confidence,
            "margin": margin,
            "reasons": reasons + ["below-threshold:list"],
            "scores": scores,
            "data_score": round(data_score, 2),
        }
    return {
        "intent": "list",
        "confidence": confidence,
        "margin": margin,
        "reasons": reasons,
        "scores": scores,
        "data_score": round(data_score, 2),
    }


def is_data_question(
    question: str,
    plugin_hints: dict[str, frozenset[str]] | None = None,
) -> bool:
    """Heuristique large : en cas de doute on exige un outil (nudge no-tool)."""
    result = route(question, plugin_hints)
    if result["intent"] in ("list", "create"):
        return True
    return result["data_score"] >= DATA_MIN_SCORE
