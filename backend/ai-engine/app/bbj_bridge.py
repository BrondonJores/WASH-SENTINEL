"""Pont déterministe ghomala' (bbj) -> français pour le triage WASH.

Contexte : la transcription bbj vient de Meta Omnilingual ASR (autre agent),
mais le LLM (Llama/Qwen 3B) NE comprend PAS le ghomala' et la qualité de
transcription est INCONNUE tant qu'un locuteur natif n'a pas testé.
Donc : pont 100 % déterministe (lexique + appariement de tokens),
AUCUN appel LLM, et `needs_human_check` TOUJOURS True pour bbj.

Deux niveaux de confiance (champ `tier` de chaque indice) :
- "validated" : forme du champ `bbj`, validée par un locuteur natif
  (verified=true). Règle d'or b799206 conservée : rien ne matche sans
  source (les entrées todo, sans `bbj` ni `candidates`, ne matchent JAMAIS).
- "web" : forme du champ `candidates`, issue d'une source web publiée
  et citée (dictionnaire HuggingFace, Wiktionary), NON validée par un
  locuteur. Toujours signalée comme telle dans le pivot.

Anti-invention : appariement par séquence de tokens entiers (jamais de
sous-chaîne : "sok" ne matche pas dans "sokoto"), variantes trop courtes
(< 3 caractères repliés) ignorées (tons perdus au repli + homophones :
voir notes du lexique), score de couverture exposé, et repli honnête
"incertain" (guesses forcés à "unknown") sous le seuil de couverture.

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

#: Lexique WASH bbj->fr (champ `bbj` = validé locuteur, `candidates` = web).
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

#: Repli des lettres ghomala' hors ASCII (NFKD ne les décompose pas) vers
#: leur voyelle/consonne de base, AVANT fold(). Une transcription ASR
#: sans ces caractères ("shye", "sok", "lunga") matche donc les formes
#: canoniques ("shyə", "sɔk", "luŋga"), et inversement.
_BBJ_FOLD_MAP = str.maketrans({
    "ə": "e",
    "ɛ": "e",
    "ɔ": "o",
    "ʉ": "u",
    "ŋ": "n",
    "ɑ": "a",
})

_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")

#: Longueur repliée minimale (espaces exclues) d'une variante matchable.
#: Les formes plus courtes (mu, pu, ca, la, go, mi...) sont exclues du
#: matching automatique : le repli efface les tons qui les distinguent
#: (lɔ́ propre / lɔ̀ pleurer, ghò malade / gho aller...) et plusieurs sont
#: des homophones ultra-fréquents (pu = "on", mu' = "un"). Les locutions
#: attestées qui les contiennent (wə go, la' pú, pú é...) restent
#: matchables via leur forme entière. Voir notes du lexique.
MIN_VARIANT_LEN = 3

#: Couverture minimale (part des tokens d'entrée reconnus) pour émettre
#: des hypothèses. En dessous : repli "incertain", guesses forcés à
#: "unknown", confiance "low". Ne jamais inventer une panne.
COVERAGE_MIN = 0.30


def _norm(text: Any) -> str:
    """Normalisation tolérante : minuscules, repli bbj, sans accents."""
    lowered = str(text or "").lower().translate(_BBJ_FOLD_MAP)
    return " ".join(_NON_ALNUM_RE.sub(" ", fold(lowered)).split())


def _matchable_tokens(variant: Any) -> list[str]:
    """Tokens d'une variante, ou [] si trop courte pour matcher (sécurité)."""
    tokens = _norm(variant).split()
    if len("".join(tokens)) < MIN_VARIANT_LEN:
        return []
    return tokens


def _contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    """Vrai si `needle` apparaît en tokens consécutifs dans `haystack`."""
    size = len(needle)
    if not size:
        return False
    return any(
        haystack[i:i + size] == needle
        for i in range(len(haystack) - size + 1)
    )


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

    Matching insensible à la casse/ponctuation/accents/tons, par séquence
    de tokens entiers (jamais de sous-chaîne). AUCUN appel LLM — pur lexique.
    Deux niveaux : "validated" (bbj + verified=true, locuteur natif) et
    "web" (candidates + source citée, NON validé — toujours signalé).

    Retour :
        french_pivot: template FR assemblé, toujours non vide.
        matched_slots: [{id, fr, slot, maps_to, matched_variant, tier}, ...].
        confidence: 'low' (défaut, ou indice web, ou repli) ou 'medium'
            (2+ indices TOUS validés), jamais plus.
        needs_human_check: TOUJOURS True pour bbj.
        unmatched: tokens d'entrée sans correspondance (plafonné à 20).
        infrastructure_guess / issue_guess / urgency_guess: catégorie
            extractor valide ou 'unknown' (jamais inventé ; forcés à
            'unknown' en repli "incertain").
        coverage: part des tokens d'entrée reconnus (0.0-1.0).
        verdict: 'indices' (couverture suffisante, à vérifier) ou
            'incertain' (couverture < COVERAGE_MIN : aucune panne déduite).
    """
    entries = lexicon if lexicon is not None else load_lexicon()
    tokens = _norm(text_bbj).split()
    matched: list[dict[str, Any]] = []

    for entry in entries:
        if entry.get("verified") is True:
            # Niveau 1 : formes validées par un locuteur natif.
            pool = entry.get("bbj") or []
            tier = "validated"
        else:
            # Niveau 2 : formes web sourcées (source citée exigée).
            # Sans candidats ni source (todo locuteur) : ne matche JAMAIS.
            if not entry.get("source"):
                continue
            pool = entry.get("candidates") or []
            tier = "web"
        for variant in pool:
            if _contains_sequence(tokens, _matchable_tokens(variant)):
                matched.append({
                    "id": entry.get("id", ""),
                    "fr": entry.get("fr", ""),
                    "slot": entry.get("slot", ""),
                    "maps_to": entry.get("maps_to"),
                    "matched_variant": variant,
                    "tier": tier,
                })
                break

    covered: set[str] = set()
    for slot in matched:
        covered.update(_norm(slot["matched_variant"]).split())
    recognized = sum(1 for tok in tokens if tok in covered)
    coverage = (recognized / len(tokens)) if tokens else 0.0
    fallback = coverage < COVERAGE_MIN

    infra_guess = "unknown"
    issue_guess = "unknown"
    urgency_guess = "unknown"
    if not fallback:
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

    all_validated = bool(matched) and all(
        m["tier"] == "validated" for m in matched
    )
    confidence = "medium" if (len(matched) >= 2 and all_validated) else "low"

    pct = int(round(coverage * 100))
    total = len(tokens)
    coverage_txt = f"Couverture lexicale : {pct} % ({recognized}/{total} mots)."
    if fallback:
        # Repli honnête : on liste les mots reconnus, on ne déduit RIEN.
        if matched:
            clues = " ; ".join(
                f"{m['fr']} (≈ « {m['matched_variant']} »)" for m in matched
            )
            known_txt = f"mots reconnus : {clues}."
        else:
            known_txt = "aucun mot reconnu."
        french_pivot = (
            "Signalement (ghomala', à vérifier) : couverture lexicale "
            f"insuffisante ({pct} %) — {known_txt} Verdict : incertain, "
            "aucune panne déduite. "
            "Vérification par un locuteur natif requise avant triage."
        )
    elif matched:
        parts = []
        clues = " ; ".join(
            f"{m['fr']} (≈ « {m['matched_variant']} »)"
            + ("" if m["tier"] == "validated" else " [source web, à valider]")
            for m in matched
        )
        parts.append(f"indices détectés : {clues}.")
        if infra_guess != "unknown":
            parts.append(f"Infrastructure probable : {_INFRA_LABELS[infra_guess]}.")
        if issue_guess != "unknown":
            parts.append(f"Panne probable : {_ISSUE_LABELS[issue_guess]}.")
        parts.append(coverage_txt)
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

    unmatched = [tok for tok in tokens if tok not in covered][:20]

    return {
        "french_pivot": french_pivot,
        "matched_slots": matched,
        "confidence": confidence,
        "needs_human_check": True,
        "unmatched": unmatched,
        "infrastructure_guess": infra_guess,
        "issue_guess": issue_guess,
        "urgency_guess": urgency_guess,
        "coverage": coverage,
        "verdict": "incertain" if fallback else "indices",
    }
