"""Suggestions « vouliez-vous dire ? » pour école/district inconnu (chantier 3/9).

Jamais un mur : quand le lieu cité ne correspond à rien de connu, on propose
des candidats flous + des échantillons cliquables au lieu d'échouer sec.

AXE 3 : scoring/normalisation/seuil partagés via textnorm (fini la dérive
SEUIL 0.75 vs test 0.45) ; marqueurs FR + EN/pidgin minimaux.
"""
from __future__ import annotations

import re
from typing import Any

from .textnorm import PLACE_CUTOFF, fold, known_places, score_place

#: Alias historique : cutoff balayé 0.40-0.80 (voir test_place_threshold).
SEUIL = PLACE_CUTOFF

# Marqueurs (repliés, sans accent) après lesquels se trouve le lieu probable.
_MARKERS = frozenset({
    "a", "au", "aux",            # à / au / aux
    "de", "des", "du", "d",      # de / d'
    "pour", "sur",
    "ecole", "ecoles",           # école(s)
    "district", "districts",
    "at", "in", "for", "from",   # EN/pidgin : "school at Nkol"
    "school",                    # "the school Kribi" / "school Nkol"
})

# Mots à sauter juste après un marqueur (articles / marqueurs en chaîne).
_SKIP_AFTER = frozenset({
    "le", "la", "les", "l", "un", "une",
    "de", "des", "du", "d", "a", "au", "aux",
    "ecole", "ecoles", "district", "districts",
    "the", "a", "an", "school",
})

# Mots qui terminent le fragment (politesse, questions, liaisons).
_STOP = frozenset({
    "stp", "svp", "merci",
    "quoi", "quel", "quelle", "quels", "quelles",
    "comment", "pourquoi", "combien", "quand", "ou",
    "est", "sont", "avec", "et", "mais", "donc",
    "que", "qui", "une", "fois", "aussi",
    "what", "where", "which", "who", "whom", "the", "of",
}) | _MARKERS

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\-]*")


def _known_places(context: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(écoles, districts) connus — délégation au canonique textnorm."""
    return known_places(context or {})


def _has_marker(message: str) -> bool:
    """True si le message cite un lieu (marqueurs FR + EN/pidgin)."""
    text = re.sub(r"\b([dDlL])['’]([A-Za-zÀ-ÿ])", r"\1' \2", message or "")
    return any(fold(t) in _MARKERS for t in _TOKEN_RE.findall(text))


def _extract_fragment(message: str) -> str:
    """Fragment lieu probable : mots après à/de/d'/pour/sur/école/district.

    Insensible casse/accents pour la détection, texte d'origine préservé.
    Repli : dernier mot significatif ; "" si rien d'exploitable.
    """
    text = re.sub(r"\b([dDlL])['’]([A-Za-zÀ-ÿ])", r"\1' \2", message or "")
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return ""
    normed = [fold(t) for t in tokens]

    last_marker = -1
    for i, n in enumerate(normed):
        if n in _MARKERS:
            last_marker = i
    if last_marker >= 0:
        words: list[str] = []
        for tok, n in zip(tokens[last_marker + 1:], normed[last_marker + 1:]):
            if not words and n in _SKIP_AFTER:
                continue
            if n in _STOP:
                break
            words.append(tok)
            if len(words) >= 3:
                break
        if words:
            return " ".join(words)
        # Marqueur en fin de message (« de l'école de ») : pas de fragment.
        return ""
    for tok, n in zip(reversed(tokens), reversed(normed)):
        if len(n) >= 3 and n not in _STOP and n not in _SKIP_AFTER:
            return tok
    return ""


def _question(kind: str, label: str) -> str:
    """Question cliquable pré-remplie pour la suggestion."""
    if kind == "district":
        return f"Résumer le district de {label}"
    if fold(label).startswith("ecole"):
        return f"Analyser {label}"
    return f"Analyser l'école de {label}"


def suggest_places(message: str, context: dict, limit: int = 3) -> dict[str, Any]:
    """Suggère des lieux connus proches du fragment cité (jamais un mur).

    Retourne {insight, fragment, suggestions[{label, kind, question}],
    ecoles_sample[3], districts_sample}.
    Contexte vide -> suggestions [] + aide générique.
    """
    context = context or {}
    schools, districts = _known_places(context)
    fragment = _extract_fragment(message)
    ecoles_sample = schools[:3]
    districts_sample = list(districts)

    if not schools and not districts:
        return {
            "insight": ("Je ne connais encore aucune école ni aucun district. "
                        "Précisez un nom (ex. « Analyser l'école de Nkol ») "
                        "et je lancerai l'analyse."),
            "fragment": fragment,
            "from_marker": _has_marker(message),
            "suggestions": [],
            "ecoles_sample": [],
            "districts_sample": [],
        }

    scored: list[tuple[float, str, str]] = []
    if fold(fragment):
        for label in schools:
            s = score_place(fragment, label)
            if s >= SEUIL:
                scored.append((s, "school", label))
        for label in districts:
            s = score_place(fragment, label)
            if s >= SEUIL:
                scored.append((s, "district", label))
    scored.sort(key=lambda t: t[0], reverse=True)
    suggestions = [
        {"label": label, "kind": kind, "question": _question(kind, label)}
        for _, kind, label in scored[: max(0, limit)]
    ]

    if suggestions:
        labels = ", ".join(s["label"] for s in suggestions)
        insight = (f"« {fragment} » ne correspond à aucun lieu connu — "
                   f"vouliez-vous dire : {labels} ? "
                   f"Cliquez sur une suggestion ou précisez.")
    elif fragment:
        insight = (f"« {fragment} » m'est inconnu. Voici des écoles "
                   f"et districts connus — précisez votre demande.")
    else:
        insight = ("Je n'ai pas repéré de lieu connu dans votre message — "
                   "voulez-vous parler d'une de ces écoles ou districts ?")
    return {
        "insight": insight,
        "fragment": fragment,
        "from_marker": _has_marker(message),
        "suggestions": suggestions,
        "ecoles_sample": ecoles_sample,
        "districts_sample": districts_sample,
    }
