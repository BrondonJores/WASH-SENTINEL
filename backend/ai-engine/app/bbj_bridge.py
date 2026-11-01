"""Pont déterministe ghomala' (bbj) -> français pour le triage WASH.

Contexte : la transcription bbj vient de Meta Omnilingual ASR (autre agent),
mais le LLM (Llama/Qwen 3B) NE comprend PAS le ghomala' et la qualité de
transcription est INCONNUE tant qu'un locuteur natif n'a pas testé.
Donc : pont 100 % déterministe (lexique + sous-chaînes), AUCUN appel LLM,
et `needs_human_check` TOUJOURS True pour bbj.

Sortie calibrée sur ce que le triage attend (voir extractor.py /
schemas.py) : catégorie d'infrastructure FR valide, nature de panne FR
valide, résumé pivot FR. En cas de doute : 'unknown' + vérification
humaine, jamais d'hallucination.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args

from .schemas import ExtractedWashIncident
from .textnorm import fold

#: Lexique WASH bbj->fr (toutes entrées UNVALIDATED par défaut).
LEXICON_PATH = Path(__file__).resolve().parent / "data" / "bbj_wash_lexicon.json"


def _literal_values(field_name: str, *, exclude_other: bool = True) -> frozenset[str]:
    """Valeurs du Literal d'un champ de schemas.ExtractedWashIncident.

    Source unique = les Literal de schemas.py (jamais recopiés ici).
    'other' est exclu : interdit par le prompt, le pont émet 'unknown'
    en cas de doute (cf. tests/test_lot2_consts.py pour la synchro).
    """
    values = set(get_args(ExtractedWashIncident.model_fields[field_name].annotation))
    if exclude_other:
        values.discard("other")
    return frozenset(values)


#: Catégories extractor valides, dérivées des Literal de schemas.py
#: (ExtractedWashIncident, hors 'other').
VALID_INFRASTRUCTURES = _literal_values("infrastructure_type")
VALID_ISSUES = _literal_values("issue_type")
VALID_URGENCIES = _literal_values("urgency_level")

#: Libellés FR courts pour le pivot (affichage opérateur uniquement).
#: Constantes de module LOT 2 — pas d'i18n complète (hors lot).
INFRA_LABELS_FR = {
    "water_point": "point d'eau",
    "toilets_latrines": "toilettes/latrines",
    "handwashing": "lavage des mains",
    "sewage_drainage": "évacuation des eaux",
}
ISSUE_LABELS_FR = {
    "leak": "fuite",
    "total_breakdown": "panne totale",
    "contamination": "contamination suspectée",
    "blockage": "obstruction/bouchon",
    "dry_well": "manque d'eau",
    "vandalism": "vandalisme/vol",
}

#: Alias historiques privés (mêmes objets, compatibilité).
_INFRA_LABELS = INFRA_LABELS_FR
_ISSUE_LABELS = ISSUE_LABELS_FR

_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")


def _norm(text: Any) -> str:
    """Normalisation tolérante : minuscules, sans accents, sans ponctuation."""
    return " ".join(_NON_ALNUM_RE.sub(" ", fold(text)).split())


def load_lexicon(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Charge les entrées du lexique bbj (liste, ordre stable du fichier)."""
    with open(Path(path) if path else LEXICON_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data.get("entries", []) if isinstance(data, dict) else data
    return [e for e in entries if isinstance(e, dict)]


def bridge_bbj_to_french(
    text_bbj: str,
    lexicon: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Projette une transcription ghomala' vers un pivot FR pour le triage.

    Matching insensible à la casse/ponctuation/accents, tolérant
    (sous-chaînes normalisées). AUCUN appel LLM — pur lexique.

    Retour :
        french_pivot: template FR assemblé, toujours non vide.
        matched_slots: [{id, fr, slot, maps_to, matched_variant}, ...].
        confidence: 'low' (0-1 indice) ou 'medium' (2+ indices), jamais plus.
        needs_human_check: TOUJOURS True pour bbj.
        unmatched: tokens d'entrée sans correspondance (plafonné à 20).
        infrastructure_guess / issue_guess: catégorie extractor valide
            ou 'unknown' (jamais inventé).
    """
    entries = lexicon if lexicon is not None else load_lexicon()
    normed = _norm(text_bbj)
    matched: list[dict[str, Any]] = []

    for entry in entries:
        variants = entry.get("bbj") or []
        for variant in variants:
            folded_variant = _norm(variant)
            if folded_variant and folded_variant in normed:
                matched.append({
                    "id": entry.get("id", ""),
                    "fr": entry.get("fr", ""),
                    "slot": entry.get("slot", ""),
                    "maps_to": entry.get("maps_to"),
                    "matched_variant": variant,
                })
                break

    infra_guess = "unknown"
    issue_guess = "unknown"
    urgency_guess = "unknown"
    for slot in matched:
        target = slot.get("maps_to")
        if slot["slot"] == "infrastructure" and infra_guess == "unknown":
            if target in VALID_INFRASTRUCTURES:
                infra_guess = target
        elif slot["slot"] == "issue" and issue_guess == "unknown":
            if target in VALID_ISSUES:
                issue_guess = target
        elif slot["slot"] == "urgency" and urgency_guess == "unknown":
            if target in VALID_URGENCIES:
                urgency_guess = target

    confidence = "medium" if len(matched) >= 2 else "low"

    if matched:
        clues = " ; ".join(f"{m['fr']} (≈ « {m['matched_variant']} »)" for m in matched)
        parts = [f"indices détectés : {clues}."]
        if infra_guess != "unknown":
            parts.append(f"Infrastructure probable : {_INFRA_LABELS[infra_guess]}.")
        if issue_guess != "unknown":
            parts.append(f"Panne probable : {_ISSUE_LABELS[issue_guess]}.")
        french_pivot = (
            "Signalement (ghomala', à vérifier) : "
            + " ".join(parts)
            + " Vérification par un locuteur natif requise avant triage."
        )
    else:
        french_pivot = (
            "Signalement (ghomala', à vérifier) : aucun indice WASH reconnu "
            "dans la transcription — vérification humaine requise."
        )

    covered: set[str] = set()
    for slot in matched:
        covered.update(_norm(slot["matched_variant"]).split())
    unmatched = [tok for tok in normed.split() if tok not in covered][:20]

    return {
        "french_pivot": french_pivot,
        "matched_slots": matched,
        "confidence": confidence,
        "needs_human_check": True,
        "unmatched": unmatched,
        "infrastructure_guess": infra_guess,
        "issue_guess": issue_guess,
        "urgency_guess": urgency_guess,
    }
