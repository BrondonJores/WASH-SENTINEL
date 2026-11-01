"""Suggestions « vouliez-vous dire ? » pour école/district inconnu (chantier 3/9).

Jamais un mur : quand le lieu cité ne correspond à rien de connu, on propose
des candidats flous + des échantillons cliquables au lieu d'échouer sec.

Module volontairement autonome (zéro import app.*) : le parent câblera l'appel.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

SEUIL = 0.75

# Marqueurs (normalisés, sans accent) après lesquels se trouve le lieu probable.
_MARKERS = frozenset({
    "a", "au", "aux",            # à / au / aux
    "de", "des", "du", "d",      # de / d'
    "pour", "sur",
    "ecole", "ecoles",           # école(s)
    "district", "districts",
})

# Mots à sauter juste après un marqueur (articles / marqueurs en chaîne).
_SKIP_AFTER = frozenset({
    "le", "la", "les", "l", "un", "une",
    "de", "des", "du", "d", "a", "au", "aux",
    "ecole", "ecoles", "district", "districts",
})

# Mots qui terminent le fragment (politesse, questions, liaisons).
_STOP = frozenset({
    "stp", "svp", "merci",
    "quoi", "quel", "quelle", "quels", "quelles",
    "comment", "pourquoi", "combien", "quand", "ou",
    "est", "sont", "avec", "et", "mais", "donc",
    "que", "qui", "une", "fois", "aussi",
}) | _MARKERS

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\-]*")

# Mots génériques ignorés dans le score par mot (évite les faux positifs :
# « Nkole » ne doit pas matcher toutes les écoles via le mot « école »).
_GENERIC_TOKENS = frozenset({
    "ecole", "ecoles", "ec", "ep",
    "district", "districts",
    "primaire", "publique", "prive", "privee",
    "college", "lycee", "maternelle",
    "groupe", "scolaire", "gbs", "gbhs",
    "de", "des", "du", "d", "a", "au", "aux", "le", "la", "les",
})


def _norm(text: str) -> str:
    """Minuscules sans accent (même convention que agent_loop._norm)."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", (text or "").lower())
        if not unicodedata.combining(c))


def _known_places(context: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(écoles, districts) connus du contexte — même contrat que known_places."""
    context = context or {}
    schools = [str(s.get("school_name") or s.get("name") or "")
               for s in (context.get("schools") or [])]
    districts = {str(s.get("district") or "") for s in (context.get("schools") or [])}
    districts |= {str(i.get("district") or "") for i in (context.get("incidents") or [])}
    return ([s for s in schools if s],
            sorted(d for d in districts if d))


def _has_marker(message: str) -> bool:
    """True si le message cite un lieu via à/de/d'/pour/sur/école/district."""
    text = re.sub(r"\b([dDlL])['’]([A-Za-zÀ-ÿ])", r"\1' \2", message or "")
    return any(_norm(t) in _MARKERS for t in _TOKEN_RE.findall(text))


def _extract_fragment(message: str) -> str:
    """Fragment lieu probable : mots après à/de/d'/pour/sur/école/district.

    Insensible casse/accents pour la détection, texte d'origine préservé.
    Repli : dernier mot significatif ; "" si rien d'exploitable.
    """
    text = re.sub(r"\b([dDlL])['’]([A-Za-zÀ-ÿ])", r"\1' \2", message or "")
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return ""
    normed = [_norm(t) for t in tokens]

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


def _score(fragment_norm: str, label_norm: str) -> float:
    """Meilleur ratio difflib : nom complet ou meilleur mot du nom."""
    full = SequenceMatcher(None, fragment_norm, label_norm).ratio()
    best_token = max(
        (SequenceMatcher(None, fragment_norm, t).ratio()
         for t in label_norm.split()
         if t not in _GENERIC_TOKENS),
        default=0.0,
    )
    return max(full, best_token)


def _question(kind: str, label: str) -> str:
    """Question cliquable pré-remplie pour la suggestion."""
    if kind == "district":
        return f"Résumer le district de {label}"
    if _norm(label).startswith("ecole"):
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
    frag_norm = _norm(fragment)
    if frag_norm:
        for label in schools:
            s = _score(frag_norm, _norm(label))
            if s >= SEUIL:
                scored.append((s, "school", label))
        for label in districts:
            s = _score(frag_norm, _norm(label))
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
