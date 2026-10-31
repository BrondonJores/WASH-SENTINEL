"""Détection de doublons par similarité cosinus sur embeddings.

Seuils constatés (hérités du code, NON calibrés empiriquement — heuristiques) :
- Décision doublon : 0.80 par défaut (`DuplicateCheckRequest.similarity_threshold`,
  schemas.py). Le service Laravel appelle avec threshold=0.80 : cohérent.
  Surcharge possible par appel via le paramètre `threshold` de `check()`.
- Inscription en liste `matches` : 0.70 (interne, fixe).
- Repli textuel Jaccard (embeddings indisponibles) : 0.50 (interne, fixe,
  indépendant du seuil cosinus).
"""
from __future__ import annotations

import numpy as np
from .providers import BaseLLMProvider
from .schemas import DuplicateCheckRequest, DuplicateCheckResponse, DuplicateMatch

DEFAULT_SIMILARITY_THRESHOLD = 0.80
"""Miroir documenté du défaut `DuplicateCheckRequest.similarity_threshold` (0.80)."""


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

        # 1. Vecteur du nouveau rapport
        query_vec = await self.llm.get_embedding(request.incoming_summary)
        if not query_vec:
            # Fallback textuel simple si pas de modèle d'embedding disponible
            return self._fallback_text_match(request)

        q_arr = np.array(query_vec, dtype=float)
        q_norm = np.linalg.norm(q_arr)
        if q_norm == 0:
            return DuplicateCheckResponse(is_duplicate=False)

        matches: list[DuplicateMatch] = []
        best_match_id: int | None = None
        max_similarity = 0.0

        for inc in request.active_incidents:
            inc_vec = await self.llm.get_embedding(inc.summary)
            if not inc_vec:
                continue

            i_arr = np.array(inc_vec, dtype=float)
            i_norm = np.linalg.norm(i_arr)
            if i_norm == 0:
                continue

            # Similarité Cosinus
            similarity = float(np.dot(q_arr, i_arr) / (q_norm * i_norm))

            if similarity >= 0.70:
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

        Seuil Jaccard fixe 0.50, indépendant du seuil cosinus (comportement hérité).
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

        is_dup = max_overlap >= 0.50
        return DuplicateCheckResponse(
            is_duplicate=is_dup,
            matched_incident_id=best_id if is_dup else None,
            similarity_score=round(max_overlap, 2),
        )
