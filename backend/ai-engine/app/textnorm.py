"""Normalisation textuelle partagée de l'AXE 3 (multilingue + négation + lieux).

Propriétaire unique des helpers déterministes : repli sans accents (via
``router.normalize``, sans duplication), négation à portée, comparaison de
districts, parsing de dates, déduplication d'incidents et score de lieu.
Les modules migrés (extractor, epidemic_detector, tools/epidemic_alerts,
tools/district_alerts, agent_tools, place_suggest) délèguent ici au lieu de
dupliquer ; les autres sites (document_briefing, observatoire, ...) restent
pour un suivi mécanique.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from .router import normalize as _router_normalize


def fold(text: Any) -> str:
    """Minuscules sans accents + espaces normalisés (sémantique canonique).

    Réutilise ``router.normalize`` (NFKD + minuscules) et ajoute le
    tassement des espaces (équivalent à l'ancien epidemic_detector._normalize).
    """
    return " ".join(_router_normalize(str(text or "")).split())


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize_folded(text: Any) -> list[str]:
    """Tokens alphanumériques du texte replié (frontières de mots)."""
    return _TOKEN_RE.findall(fold(text))


# ---------------------------------------------------------------------------
# Table unique des signaux sanitaires (extractor exclu : familles WASH).
# (motif replié, force, frontière, niable, validé)
# frontière : "word" (mot entier, pluriel s/x/es toléré) ou "subword" (tige).
# UNVALIDATED : palier candidat, ne fait foi qu'après validation locuteur.
# ---------------------------------------------------------------------------
# Chaque entrée : (motif, force, frontière, niable)
HEALTH_SIGNALS: tuple[tuple[str, str, str, bool], ...] = (
    # --- Forts français (validés, historique epidemic_detector) ---
    ("diarrh", "strong", "subword", True),
    ("cholera", "strong", "subword", True),
    ("vomiss", "strong", "subword", True),
    ("dysenteri", "strong", "subword", True),
    ("contamin", "strong", "subword", True),
    ("eau jaune", "strong", "subword", True),
    ("jaune", "strong", "word", True),
    ("jaunatre", "strong", "word", True),
    ("debord", "strong", "subword", True),
    # --- Forts ex-epidemic_alerts (fusion des deux listes divergentes) ---
    ("souille", "strong", "subword", True),  # tige : souillée/souillées
    ("epidemi", "strong", "subword", True),  # épidémie/épidémique
    ("fecal", "strong", "subword", True),
    # --- Forts anglais/pidgin ---
    ("vomit", "strong", "subword", True),  # vomit/vomiting (≠ vomiss* fr)
    ("dirty water", "strong", "subword", True),
    # --- UNVALIDATED : pidgin, validation locuteur requise avant promotion ---
    ("running stomach", "strong", "subword", True),
    ("dirty wata", "strong", "subword", True),
    ("wata don dirty", "strong", "subword", True),
    # --- Faibles français (validés) : mot entier (anti "gout" dans "goutte") ---
    ("trouble", "weak", "word", True),
    ("odeur", "weak", "word", True),
    ("gout", "weak", "word", True),
    ("ventre", "weak", "word", True),
    ("nause", "weak", "word", True),
)

#: Motifs UNVALIDATED (pidgin, en attente de validation par un locuteur).
UNVALIDATED_HEALTH_SIGNALS = frozenset({
    "running stomach", "dirty wata", "wata don dirty",
})

STRONG_HEALTH_PATTERNS = tuple(p for p, s, _, _ in HEALTH_SIGNALS if s == "strong")
WEAK_HEALTH_PATTERNS = tuple(p for p, s, _, _ in HEALTH_SIGNALS if s == "weak")


def _word_spans(haystack: str, pattern: str) -> list[tuple[int, int]]:
    """Occurrences mot-entier (+ pluriels s/x/es) avec offsets caractères."""
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[a-z0-9]+", haystack):
        token = match.group(0)
        if token == pattern or token in (pattern + "s", pattern + "x", pattern + "es"):
            spans.append((match.start(), match.end()))
    return spans


def _subword_spans(haystack: str, pattern: str) -> list[tuple[int, int]]:
    """Occurrences sous-chaîne (tiges, locutions) avec offsets caractères."""
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        found = haystack.find(pattern, start)
        if found < 0:
            return spans
        spans.append((found, found + len(pattern)))
        start = found + 1


def find_keyword_spans(
    haystack_folded: str, keyword: str, boundary: str = "subword",
) -> list[tuple[int, int]]:
    """Offsets caractères des occurrences selon la politique de frontière."""
    pattern = fold(keyword)
    if not pattern:
        return []
    if boundary == "word" and " " not in pattern:
        return _word_spans(haystack_folded, pattern)
    if " " in pattern:
        # Locution : mots consécutifs, frontières regex (robuste aux espaces).
        rx = r"\b" + r"\s+".join(re.escape(w) for w in pattern.split()) + r"\b"
        return [(m.start(), m.end()) for m in re.finditer(rx, haystack_folded)]
    return _subword_spans(haystack_folded, pattern)


# ---------------------------------------------------------------------------
# Négation à portée (~3 tokens à droite, reset de proposition).
# ---------------------------------------------------------------------------

#: Négateurs simples (token unique replié).
_NEGATORS_SINGLE = frozenset({
    "sans", "aucun", "aucune", "ni",
    "no", "not", "without", "never",
})
#: Second token d'un bigramme niant ("pas/plus de|d' ...").
_NEGATOR_BIGRAM_FIRST = frozenset({"pas", "plus"})
_NEGATOR_BIGRAM_SECOND = frozenset({"de", "d"})
#: Fermetures "ne ... X" (n'/ne + fermant à ≤5 tokens).
_NEGATOR_OPEN = frozenset({"ne", "n"})
_NEGATOR_CLOSE = frozenset({"pas", "plus", "jamais", "guere", "aucun", "rien"})
#: Reset de proposition : ponctuation + conjonctions adversatives/causales.
_CLAUSE_RESET = frozenset({
    "mais", "parce", "car", "alors", "donc", "or", "pourtant",
    "cependant", "but", "because", "however",
})
_PUNCT_RE = re.compile(r"[.,;:!?()]")

#: Famille absence-d'eau : NON NIABLE ("pas d'eau" EST l'incident).
NON_NEGATABLE_WATER = frozenset({"eau", "eaux", "wata", "madiba", "water"})


def negation_spans(text_folded: str) -> list[tuple[int, int]]:
    """Plages caractères neutralisées par les négateurs (fr/en/pidgin).

    Fenêtre ~3 tokens à droite du négateur, reset sur ponctuation ou
    conjonction de rupture ("pas de chloration, diarrhée partout" reste
    positif après la virgule).
    """
    tokens = [(m.group(0), m.start(), m.end())
              for m in re.finditer(r"[a-z0-9]+|[.,;:!?()]", text_folded)]
    muted: list[tuple[int, int]] = []

    def _mute_from(index: int) -> None:
        taken = 0
        for word, start, end in tokens[index:]:
            if _PUNCT_RE.fullmatch(word) or word in _CLAUSE_RESET:
                break
            muted.append((start, end))
            taken += 1
            if taken >= 3:
                break

    for i, (word, _s, _e) in enumerate(tokens):
        if word in _NEGATORS_SINGLE:
            _mute_from(i + 1)
        elif word in _NEGATOR_BIGRAM_FIRST:
            nxt = tokens[i + 1][0] if i + 1 < len(tokens) else ""
            if nxt in _NEGATOR_BIGRAM_SECOND:
                _mute_from(i + 2)
            elif word == "plus" and nxt not in _NEGATOR_BIGRAM_SECOND:
                # "ne coule plus" : le fermant seul ne nie pas (positif par
                # construction côté extracteur) → ignoré ici aussi.
                continue
        elif word in _NEGATOR_OPEN:
            window = [t[0] for t in tokens[i + 1:i + 6]]
            if any(w in _NEGATOR_CLOSE for w in window):
                closer = next(
                    j for j in range(i + 1, i + 1 + len(window))
                    if tokens[j][0] in _NEGATOR_CLOSE
                )
                _mute_from(closer + 1)
    return muted


def is_negated(
    start: int, end: int, spans: list[tuple[int, int]] | None,
) -> bool:
    """Vrai si la plage [start, end) chevauche une plage neutralisée."""
    return any(s < end and start < e for s, e in (spans or []))


def contains_keyword(
    haystack_folded: str,
    keyword: str,
    boundary: str = "subword",
    negatable: bool = True,
    spans: list[tuple[int, int]] | None = None,
) -> bool:
    """Vrai si le motif matche hors négation (niable=False → toujours vrai)."""
    matches = find_keyword_spans(haystack_folded, keyword, boundary)
    if not matches:
        return False
    if not negatable:
        return True
    if spans is None:
        spans = negation_spans(haystack_folded)
    return any(not is_negated(s, e, spans) for s, e in matches)


# ---------------------------------------------------------------------------
# Dates, districts, déduplication, lieux.
# ---------------------------------------------------------------------------

def parse_dt(value: Any) -> datetime | None:
    """Parse str|datetime|date (ISO, suffixe Z) -> aware UTC, None sinon.

    Sur-ensemble des variantes historiques (district_alerts n'acceptait
    que str) ; naive -> UTC (fail-open inchangé chez les appelants).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_date(value: Any) -> date | None:
    """Parse date ISO (AAAA-MM-JJ ou datetime ISO) -> date, None sinon."""
    dt = parse_dt(value)
    return dt.date() if dt is not None else None


def district_match(
    item: Any,
    wanted: Any,
    mode: str = "exact_folded",
    allow_substring: bool = False,
) -> bool:
    """Politique unique de comparaison de districts (insensible casse/accents).

    Chaîne : égalité repliée, puis chevauchement de tokens (multi-mots,
    robuste trait-d'union/espace), puis préfixe gardé (min 4 car.), puis
    sous-chaîne seulement si wanted ≥ 4 car. ET allow_substring. "oua" ne
    matche plus "Douala". wanted vide = pas de filtre = True.
    mode="strict" : égalité repliée seule.
    """
    item_folded = fold(item)
    wanted_folded = fold(wanted)
    if not wanted_folded:
        return True
    if not item_folded:
        return False
    if item_folded == wanted_folded:
        return True
    if mode == "strict":
        return False
    item_tokens = set(item_folded.replace("-", " ").split())
    wanted_tokens = set(wanted_folded.replace("-", " ").split())
    if item_tokens and wanted_tokens and (
            item_tokens <= wanted_tokens or wanted_tokens <= item_tokens):
        return True
    short, long = sorted((item_folded, wanted_folded), key=len)
    if len(short) >= 4 and long.startswith(short):
        return True
    if allow_substring and len(wanted_folded) >= 4:
        return wanted_folded in item_folded or item_folded in wanted_folded
    return False


def dedup_incidents(*pools: Any) -> list[dict[str, Any]]:
    """Fusion dédupliquée de pools d'incidents. Clé id exact quand présent,
    sinon (école, date, titre). Ordre stable. Canonique (AXE 3)."""
    seen: set[Any] = set()
    merged: list[dict[str, Any]] = []
    for pool in pools:
        for incident in pool or []:
            if not isinstance(incident, dict):
                continue
            if incident.get("id") is not None:
                key = ("id", incident.get("id"))
            else:
                key = ("row", incident.get("school_id"),
                       str(incident.get("reported_at")),
                       str(incident.get("title") or incident.get("summary")))
            if key in seen:
                continue
            seen.add(key)
            merged.append(incident)
    return merged


#: Seuil flou lieux, balayé 0.40-0.80 sur tests/fixtures_places.py
#: (optimum ex æquo 0.70/0.75, tie-break précision → 0.75 ; voir
#: tests/test_place_threshold.py qui échoue si ce choix dérive).
PLACE_CUTOFF = 0.75

#: Tokens génériques ignorés du score par mot (ex-place_suggest._GENERIC_TOKENS).
GENERIC_PLACE_TOKENS = frozenset({
    "ecole", "ecoles", "ec", "ep",
    "district", "districts",
    "primaire", "publique", "prive", "privee",
    "college", "lycee", "maternelle",
    "groupe", "scolaire", "gbs", "gbhs", "cet",
    "de", "des", "du", "d", "a", "au", "aux", "le", "la", "les",
    "school",
})


def known_places(context: Any) -> tuple[list[str], list[str]]:
    """(écoles, districts) connus du contexte — canonique (AXE 3).

    Remplace les copies ligne-pour-ligne de place_suggest._known_places
    et agent_loop.known_places.
    """
    context = context or {}
    schools = [str(s.get("school_name") or s.get("name") or "")
               for s in (context.get("schools") or [])]
    districts = {str(s.get("district") or "")
                 for s in (context.get("schools") or [])}
    districts |= {str(i.get("district") or "")
                  for i in (context.get("incidents") or [])}
    return ([s for s in schools if s],
            sorted(d for d in districts if d))


def score_place(
    query: Any,
    label: Any,
    generic_tokens: frozenset[str] | None = None,
) -> float:
    """Score flou unique : max(difflib global, meilleur mot non générique).

    Bonus +0.05 (plafonné à 1) quand requête et libellé partagent un mot
    non générique (chevauchement token-set).
    """
    generic = GENERIC_PLACE_TOKENS if generic_tokens is None else generic_tokens
    q = fold(query)
    lab = fold(label)
    if not q or not lab:
        return 0.0
    full = SequenceMatcher(None, q, lab).ratio()
    # Tokens alphanumériques (coupe aussi les traits d'union : "Ntem"
    # matche "Vallée-du-Ntem" via son mot "ntem").
    label_tokens = [t for t in _TOKEN_RE.findall(lab) if t not in generic]
    best_token = max(
        (SequenceMatcher(None, q, t).ratio() for t in label_tokens),
        default=0.0,
    )
    score = max(full, best_token)
    query_tokens = {t for t in _TOKEN_RE.findall(q) if t not in generic}
    if query_tokens and query_tokens & set(label_tokens):
        score = min(1.0, score + 0.05)
    return score
