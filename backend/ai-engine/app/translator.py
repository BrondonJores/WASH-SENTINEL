"""Traduction d'AFFICHAGE des données terrain (titres, résumés saisis).

Un seul appel LLM pour tout le lot (liste numérotée, strict) : la source
n'est jamais modifiée, seuls les libellés rendus sont traduits. Repli
sûr : texte d'origine quand le modèle répond mal (jamais de vide).
"""
from __future__ import annotations

import re
from typing import Any

#: Cibles gérées (périmètre jury FR/EN).
TRANSLATE_TARGETS = ("en", "fr")

#: Garde-fous du lot (un rendu = quelques titres, pas un export).
TRANSLATE_MAX_TEXTS = 20
TRANSLATE_MAX_CHARS = 500

_LINE_RE = re.compile(r"^(\d+)\s*[.)]\s?(.*)$")

_LABELS = {"en": "English", "fr": "French"}


def _prompt(texts: list[str], target: str) -> str:
    label = _LABELS[target]
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    return (
        f"You are a faithful translator for a school water/sanitation app. "
        f"Translate each numbered text to {label}. Rules: translate meaning "
        f"only, never invent details; keep proper nouns (school names), "
        f"codes like WASH-2026-XXXX, numbers and units unchanged; if a text "
        f"is already in {label}, return it unchanged. Reply with exactly "
        f"one line per text as `N. translation` and nothing else.\n{numbered}"
    )


def _parse(content: str, originals: list[str]) -> list[str]:
    """Aligne les lignes `N. traduction` sur les originaux (repli sûr)."""
    found: dict[int, str] = {}
    for line in str(content or "").splitlines():
        match = _LINE_RE.match(line.strip())
        if not match:
            continue
        rank = int(match.group(1))
        if 1 <= rank <= len(originals) and rank not in found:
            found[rank] = match.group(2).strip()
    out = []
    for index, original in enumerate(originals, start=1):
        translated = found.get(index, "").strip()
        out.append(translated if translated else original)
    return out


class WashTranslator:
    """Traduit un lot via le provider LLM actif (fonction pure + 1 appel)."""

    def __init__(self, llm: Any):
        self._llm = llm

    async def translate(self, texts: list[str], target: str = "en") -> list[str]:
        """Traduit vers target ('en'|'fr') ; originaux sinon (jamais d'exception)."""
        full = [str(t or "") for t in (texts or [])]
        if target not in TRANSLATE_TARGETS:
            return full
        cleaned = [t.strip()[:TRANSLATE_MAX_CHARS] for t in full][:TRANSLATE_MAX_TEXTS]
        if not any(cleaned):
            return full
        try:
            answer = await self._llm.chat(
                [{"role": "user", "content": _prompt(cleaned, target)}])
            content = answer.get("content", "") if isinstance(answer, dict) else ""
            done = _parse(content, cleaned)
            # Repli : tout texte non traduit (vide, tronqué, hors lot) = original.
            out = []
            for index, original in enumerate(full):
                if index >= len(done) or done[index] == cleaned[index]:
                    out.append(original)
                else:
                    out.append(done[index])
            return out
        except Exception:
            return full
