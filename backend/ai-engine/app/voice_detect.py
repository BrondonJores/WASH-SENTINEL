"""Arbitrage de transcription multi-moteurs (pur, piloté par données).

Quand la langue demandée n'est pas native Whisper (dua_Latn, bassa,
ewondo, bbj_Latn...), deux passes peuvent coexister : Whisper en
auto-détection (bon pour FR/EN, même mélangés) et le moteur local
(Omnilingual, 1600+ langues). Ce module choisit le gagnant SANS
connaître aucune langue en dur : l'ensemble « natif Whisper » dérive
de WHISPER_LANG_MAP (codes mappés vers autre chose que "auto").

Règles :
- Whisper détecte une langue native avec proba >= seuil -> Whisper gagne
  (le locuteur parlait FR/EN malgré la langue locale demandée : cas
  fréquent, mélange au micro).
- Sinon, transcription locale non vide -> moteur local gagne.
- Sinon, transcription Whisper non vide -> Whisper (repli).
- Sinon -> None (le service lève son guidage STT_INAUDIBLE habituel).
"""
from __future__ import annotations

from typing import Any

from .stt_providers import LANGUAGE_AUTO_EFFECTIVE, WHISPER_LANG_MAP


def whisper_native_languages() -> frozenset[str]:
    """Codes transcrits nativement par Whisper (dérivé de la map, pas en dur)."""
    return frozenset(
        code for code, effective in WHISPER_LANG_MAP.items()
        if effective != LANGUAGE_AUTO_EFFECTIVE
    )


def arbitrate(
    requested: str,
    whisper: dict[str, Any] | None,
    local: dict[str, Any] | None,
    *,
    min_prob: float,
) -> dict[str, Any] | None:
    """Choisit la gagnante entre passe Whisper-auto et passe locale (pur).

    `whisper` = {"transcript", "detected_language", "detection_prob"} ou
    None (moteur indisponible) ; `local` = {"transcript", "driver"} ou None.
    Retourne {"transcript", "language_detected", "driver", "reason"} ou None.
    """
    native = whisper_native_languages()
    w_text = str((whisper or {}).get("transcript") or "").strip()
    w_lang = (whisper or {}).get("detected_language")
    w_lang = str(w_lang).strip().lower() if w_lang else None
    try:
        w_prob = float((whisper or {}).get("detection_prob") or 0.0)
    except (TypeError, ValueError):
        w_prob = 0.0
    o_text = str((local or {}).get("transcript") or "").strip()
    o_driver = str((local or {}).get("driver") or "local")

    if w_text and w_lang in native and w_prob >= min_prob:
        return {
            "transcript": w_text,
            "language_detected": w_lang,
            "driver": "whisper_cpp",
            "reason": "whisper-native-detected",
        }
    if o_text:
        return {
            "transcript": o_text,
            "language_detected": requested,
            "driver": o_driver,
            "reason": "local-engine",
        }
    if w_text:
        return {
            "transcript": w_text,
            "language_detected": w_lang or requested,
            "driver": "whisper_cpp",
            "reason": "whisper-fallback",
        }
    return None
