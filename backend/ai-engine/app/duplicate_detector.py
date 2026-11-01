"""Détection de doublons par similarité cosinus sur embeddings.

Seuils (source unique : app.thresholds, AXE 8) :
- Décision doublon : 0.80 par défaut (`DuplicateCheckRequest.similarity_threshold`,
  schemas.py). Le service Laravel appelle avec threshold=0.80 : cohérent.
  Surcharge possible par appel via le paramètre `threshold` de `check()`.
  NON calibré empiriquement (aucun seed ne fournit de vrais vecteurs).
- Inscription en liste `matches` : 0.70 (cosinus, NON calibré, idem).
- Repli textuel Jaccard (embeddings indisponibles) : 0.25, CALIBRÉ AXE 8
  (était 0.50 : R=0.00 -> P=1.00 R=0.625 F1=0.77 sur n=179 paires, voir
  app.thresholds + tests/test_threshold_calibration.py).
  Indépendant du seuil cosinus (comportement hérité).

Latence : UN seul appel batch (`get_embeddings`, requête + candidats) au lieu
de N+1 appels unitaires. Pas de pré-filtre Jaccard volontairement : il casserait
le rappel sur paraphrases (« la pompe fuit » vs « plus d'eau au robinet » ont un
Jaccard de 0 mais sont un vrai doublon), et le batch natif coûte 1 appel quel
que soit N (Laravel filtre déjà : même école, < 7 jours).
"""
from __future__ import annotations

import numpy as np
from .providers import BaseLLMProvider
from .schemas import DuplicateCheckRequest, DuplicateCheckResponse, DuplicateMatch
from .thresholds import (
    DUPLICATE_DECISION_THRESHOLD,
    DUPLICATE_JACCARD_FALLBACK,
    DUPLICATE_MATCH_CUTOFF,
)

DEFAULT_SIMILARITY_THRESHOLD = DUPLICATE_DECISION_THRESHOLD
"""Alias historique : défaut `DuplicateCheckRequest.similarity_threshold` (0.80)."""


class DuplicateDetector:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    async def check(
        self,
        request: DuplicateCheckRequest,
        threshold: float | None = None,
    ) -> DuplicateCheckResponse:
        """Compare un nouveau signalement aux incidents ouverts pour identifier les doublons.

        `threshold` (optionnel) surcharge `request.similarity_threshold` pour cet
        appel uniquement. `None` (défaut) = comportement actuel inchangé.
        """
        effective_threshold = request.similarity_threshold if threshold is None else threshold
        if not request.active_incidents:
            return DuplicateCheckResponse(is_duplicate=False)

        # 1. Batch unique : requête + tous les candidats en un seul appel.
        try:
            vectors = await self.llm.get_embeddings(
                [request.incoming_summary]
                + [inc.summary for inc in request.active_incidents]
            )
        except RuntimeError:
            # Embeddings indisponibles -> repli textuel (Jaccard, cf. thresholds).
            return self._fallback_text_match(request)
        if not vectors or not vectors[0]:
            return self._fallback_text_match(request)

        q_arr = np.array(vectors[0], dtype=float)
        q_norm = np.linalg.norm(q_arr)
        if q_norm == 0:
            return DuplicateCheckResponse(is_duplicate=False)

        matches: list[DuplicateMatch] = []
        best_match_id: int | None = None
        max_similarity = 0.0

        for inc, inc_vec in zip(request.active_incidents, vectors[1:]):
            if not inc_vec:
                continue

            i_arr = np.array(inc_vec, dtype=float)
            i_norm = np.linalg.norm(i_arr)
            if i_norm == 0:
                continue

            # Similarité Cosinus
            similarity = float(np.dot(q_arr, i_arr) / (q_norm * i_norm))

            if similarity >= DUPLICATE_MATCH_CUTOFF:
                conf = "high" if similarity >= effective_threshold else "moderate"
                matches.append(DuplicateMatch(
                    incident_id=inc.id,
                    similarity=round(similarity, 3),
                    confidence=conf,
                ))

            if similarity > max_similarity:
                max_similarity = similarity
                best_match_id = inc.id

        is_dup = max_similarity >= effective_threshold

        return DuplicateCheckResponse(
            is_duplicate=is_dup,
            matched_incident_id=best_match_id if is_dup else None,
            similarity_score=round(max_similarity, 3),
            matches=sorted(matches, key=lambda m: m.similarity, reverse=True),
        )

    def _fallback_text_match(self, request: DuplicateCheckRequest) -> DuplicateCheckResponse:
        """Fallback basique par intersection de mots-clés si Ollama Embeddings est injoignable.

        Seuil Jaccard DUPLICATE_JACCARD_FALLBACK (0.25, calibré AXE 8),
        indépendant du seuil cosinus (comportement hérité).
        """
        incoming_words = set(request.incoming_summary.lower().split())
        best_id = None
        max_overlap = 0.0

        for inc in request.active_incidents:
            inc_words = set(inc.summary.lower().split())
            if not inc_words or not incoming_words:
                continue
            overlap = len(incoming_words & inc_words) / float(len(incoming_words | inc_words))
            if overlap > max_overlap:
                max_overlap = overlap
                best_id = inc.id

        is_dup = max_overlap >= DUPLICATE_JACCARD_FALLBACK
        return DuplicateCheckResponse(
            is_duplicate=is_dup,
            matched_incident_id=best_id if is_dup else None,
            similarity_score=round(max_overlap, 2),
        )
