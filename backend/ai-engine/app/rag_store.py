"""RAG documentaire minimal : le copilote cite des manuels au lieu d'inventer.

Pipeline : chargement des .md de ``app/data`` -> découpage en chunks
(~500 caractères, overlap 50) -> recherche par similarité cosinus sur les
embeddings Ollama (``BaseLLMProvider.get_embedding``) -> réponse du LLM
contrainte aux seuls extraits, avec citations ``[source]``.

La fonction d'embedding est injectable (``embed_fn``) pour permettre des
tests déterministes sans appel réseau. ``numpy`` est utilisé s'il est
disponible, avec repli sur un cosinus en stdlib pure.
"""

from __future__ import annotations

import inspect
import math
from pathlib import Path
from typing import Any, Awaitable, Callable

try:  # numpy est dans requirements.txt ; repli stdlib sinon.
    import numpy as _np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


DATA_DIR = Path(__file__).resolve().parent / "data"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
DEFAULT_K = 3
# Sous ce score, aucun chunk n'est retenu -> abstention ("je ne sais pas").
MIN_SIMILARITY = 0.30

ABSTENTION_MESSAGE = (
    "Je ne sais pas à partir des manuels disponibles. "
    "Aucun extrait pertinent n'a été trouvé."
)

RAG_SYSTEM_PROMPT = (
    "Tu es un assistant WASH qui répond à partir de manuels techniques. "
    "Réponds UNIQUEMENT depuis les extraits fournis ci-dessous. "
    "Cite chaque affirmation avec sa source entre crochets, par exemple [pompe_india_mark_ii.md]. "
    "Si les extraits ne contiennent pas la réponse, dis exactement : "
    f"'{ABSTENTION_MESSAGE}' N'invente rien."
)

EmbedFn = Callable[[str], "list[float] | Awaitable[list[float]]"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similarité cosinus entre deux vecteurs (numpy si dispo, sinon stdlib)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    if _HAS_NUMPY:
        va = _np.array(a, dtype=float)
        vb = _np.array(b, dtype=float)
        na = float(_np.linalg.norm(va))
        nb = float(_np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(_np.dot(va, vb) / (na * nb))
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Découpe un texte en chunks d'environ ``chunk_size`` caractères.

    On accumule des paragraphes entiers (séparés par lignes vides) jusqu'à
    atteindre la taille cible ; chaque chunk (sauf le premier) reprend les
    ``overlap`` derniers caractères du précédent pour préserver le contexte.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) > chunk_size and current:
            chunks.append(current)
            current = f"{current[-overlap:]}\n\n{para}".strip() if overlap > 0 else para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def load_markdown_files(data_dir: Path | None = None) -> list[tuple[str, str]]:
    """Charge les .md du dossier (triés) -> [(nom_source, texte)]."""
    directory = Path(data_dir) if data_dir is not None else DATA_DIR
    docs: list[tuple[str, str]] = []
    if not directory.is_dir():
        return docs
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            docs.append((path.name, text))
    return docs


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class RAGStore:
    """Magasin documentaire : chunks + recherche cosinus + réponse sourcée."""

    def __init__(
        self,
        data_dir: Path | None = None,
        embed_fn: EmbedFn | None = None,
        chunk_size: int = CHUNK_SIZE,
        overlap: int = CHUNK_OVERLAP,
        threshold: float = MIN_SIMILARITY,
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.threshold = threshold
        self._embed_fn = embed_fn
        self.chunks: list[dict[str, str]] = []
        for source, text in load_markdown_files(data_dir):
            for piece in split_text(text, chunk_size, overlap):
                self.chunks.append({"source": source, "chunk": piece})
        self._chunk_embeddings: list[list[float]] | None = None

    def _require_embed_fn(self) -> EmbedFn:
        if self._embed_fn is None:
            from .providers import OllamaProvider

            self._embed_fn = OllamaProvider().get_embedding
        return self._embed_fn

    async def _embed(self, text: str) -> list[float]:
        return await _maybe_await(self._require_embed_fn()(text))

    async def retrieve(self, question: str, k: int = DEFAULT_K) -> list[dict[str, Any]]:
        """Retourne jusqu'à ``k`` chunks [{source, chunk, score}] triés par score.

        Seuls les chunks au-dessus du seuil de similarité sont retenus ;
        liste vide = abstention (aucun appel LLM à faire).
        """
        if not question.strip() or not self.chunks:
            return []
        query_vec = await self._embed(question)
        if not query_vec:
            return []
        if self._chunk_embeddings is None:
            self._chunk_embeddings = [await self._embed(c["chunk"]) for c in self.chunks]
        scored: list[dict[str, Any]] = []
        for item, vec in zip(self.chunks, self._chunk_embeddings):
            score = cosine_similarity(query_vec, vec)
            if score >= self.threshold:
                scored.append({"source": item["source"], "chunk": item["chunk"], "score": round(score, 3)})
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[: max(k, 0)]

    async def answer_with_sources(
        self, question: str, llm: Any, k: int = DEFAULT_K
    ) -> dict[str, Any]:
        """Réponse du LLM contrainte aux extraits + liste des sources citées."""
        hits = await self.retrieve(question, k=k)
        if not hits:
            return {"answer": ABSTENTION_MESSAGE, "sources": []}
        extracts = "\n\n".join(f"[{h['source']}]\n{h['chunk']}" for h in hits)
        user_prompt = f"Question : {question}\n\nExtraits :\n{extracts}\n\nRéponse (avec citations [source]) :"
        result = await _maybe_await(
            llm.chat([
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ])
        )
        answer = (result.get("content", "") or "").strip() or ABSTENTION_MESSAGE
        sources = list(dict.fromkeys(h["source"] for h in hits))
        return {"answer": answer, "sources": sources}


_default_store: RAGStore | None = None


def get_default_store() -> RAGStore:
    """Singleton paresseux sur ``app/data`` (embeddings Ollama réels)."""
    global _default_store
    if _default_store is None:
        _default_store = RAGStore()
    return _default_store


async def retrieve(question: str, k: int = DEFAULT_K) -> list[dict[str, Any]]:
    """Raccourci module : recherche dans le store par défaut (Ollama réel)."""
    return await get_default_store().retrieve(question, k=k)


async def answer_with_sources(question: str, llm: Any, k: int = DEFAULT_K) -> dict[str, Any]:
    """Raccourci module : réponse sourcée via le store par défaut."""
    return await get_default_store().answer_with_sources(question, llm, k=k)
