"""Tests du RAG documentaire : 100 % hors-ligne (embeddings et LLM stubbés)."""

from __future__ import annotations

import unittest

from app.rag_store import (
    ABSTENTION_MESSAGE,
    CHUNK_OVERLAP,
    DATA_DIR,
    RAGStore,
    RAG_SYSTEM_PROMPT,
    cosine_similarity,
    load_markdown_files,
    split_text,
)

SOURCES = {
    "pompe_india_mark_ii.md",
    "eau_trouble_cholera_urgence.md",
    "latrines_vip_scolaires.md",
}

# Vecteurs one-hot par source : similarité cosinus totalement contrôlée.
SOURCE_VECTORS = {
    "pompe_india_mark_ii.md": [1.0, 0.0, 0.0],
    "eau_trouble_cholera_urgence.md": [0.0, 1.0, 0.0],
    "latrines_vip_scolaires.md": [0.0, 0.0, 1.0],
}


def make_stub_embed(store: RAGStore, question_vector: list[float]):
    """Embedder synchrone déterministe : vecteur one-hot par source des chunks."""

    def embed(text: str) -> list[float]:
        for item in store.chunks:
            if item["chunk"] == text:
                return list(SOURCE_VECTORS[item["source"]])
        return list(question_vector)  # tout autre texte = la question

    return embed


class FakeLLM:
    """Faux LLM : capture le prompt, répond une citation fixe, zéro réseau."""

    def __init__(self, content: str = "Réparer avec des joints [pompe_india_mark_ii.md]."):
        self.content = content
        self.calls: list[list[dict]] = []

    async def chat(self, messages: list[dict]) -> dict:
        self.calls.append(messages)
        return {"content": self.content, "tool_calls": []}


class ChunkingTest(unittest.TestCase):
    def test_three_docs_loaded(self) -> None:
        docs = load_markdown_files(DATA_DIR)
        self.assertEqual({name for name, _ in docs}, SOURCES)
        for _, text in docs:
            self.assertTrue(text.strip())

    def test_chunks_non_empty_with_named_sources(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        self.assertGreaterEqual(len(store.chunks), 3)
        self.assertEqual({c["source"] for c in store.chunks}, SOURCES)
        for item in store.chunks:
            self.assertTrue(item["chunk"].strip())
            self.assertLessEqual(len(item["chunk"]), 900)  # ~500 + une marge paragraphe

    def test_overlap_between_consecutive_chunks(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        checked = 0
        for prev, nxt in zip(store.chunks, store.chunks[1:]):
            if prev["source"] == nxt["source"]:
                tail = prev["chunk"][-CHUNK_OVERLAP:].lstrip()  # split_text() strippe le chunk
                self.assertTrue(nxt["chunk"].startswith(tail))
                checked += 1
        self.assertGreater(checked, 0)

    def test_split_text_basic(self) -> None:
        self.assertEqual(split_text(""), [])
        self.assertEqual(split_text("   \n\n  "), [])
        self.assertEqual(split_text("court"), ["court"])


class CosineTest(unittest.TestCase):
    def test_values(self) -> None:
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)
        self.assertEqual(cosine_similarity([], [1.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0], [1.0, 0.0]), 0.0)
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 0.0]), 0.0)


class RetrieveTest(unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_returns_matching_source(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        store._embed_fn = make_stub_embed(store, [1.0, 0.0, 0.0])  # question "pompe"
        hits = await store.retrieve("Comment réparer la pompe ?", k=2)
        self.assertEqual(len(hits), 2)
        for hit in hits:
            self.assertEqual(hit["source"], "pompe_india_mark_ii.md")
            self.assertTrue(hit["chunk"].strip())
            self.assertAlmostEqual(hit["score"], 1.0)

    async def test_retrieve_other_source(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        store._embed_fn = make_stub_embed(store, [0.0, 0.0, 1.0])  # question "latrines"
        hits = await store.retrieve("Entretenir les latrines ?", k=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["source"], "latrines_vip_scolaires.md")

    async def test_retrieve_supports_async_embed_fn(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        sync_stub = make_stub_embed(store, [0.0, 1.0, 0.0])

        async def async_stub(text: str) -> list[float]:
            return sync_stub(text)

        store._embed_fn = async_stub
        hits = await store.retrieve("Eau trouble et choléra ?", k=1)
        self.assertEqual(hits[0]["source"], "eau_trouble_cholera_urgence.md")

    async def test_abstention_when_nothing_matches(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        store._embed_fn = make_stub_embed(store, [-1.0, -1.0, -1.0])  # loin de tout
        self.assertEqual(await store.retrieve("Question hors sujet total ?", k=3), [])

    async def test_abstention_below_threshold(self) -> None:
        store = RAGStore(data_dir=DATA_DIR, threshold=0.99)
        store._embed_fn = make_stub_embed(store, [1.0, 1.0, 0.0])  # cos = 0.707 < 0.99
        self.assertEqual(await store.retrieve("Pompe et chlore ?", k=3), [])

    async def test_empty_question_returns_nothing(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        store._embed_fn = make_stub_embed(store, [1.0, 0.0, 0.0])
        self.assertEqual(await store.retrieve("   ", k=3), [])


class AnswerWithSourcesTest(unittest.IsolatedAsyncioTestCase):
    async def test_answer_returns_citations_and_sources(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        store._embed_fn = make_stub_embed(store, [1.0, 0.0, 0.0])
        llm = FakeLLM()
        result = await store.answer_with_sources("La pompe fuit, que faire ?", llm, k=2)
        self.assertIn("[pompe_india_mark_ii.md]", result["answer"])
        self.assertEqual(result["sources"], ["pompe_india_mark_ii.md"])
        # Le prompt système verrouille le LLM aux seuls extraits.
        system_msg = llm.calls[0][0]["content"]
        self.assertIn("UNIQUEMENT", system_msg)
        self.assertIn("[pompe_india_mark_ii.md]", llm.calls[0][1]["content"])

    async def test_answer_abstains_without_calling_llm(self) -> None:
        store = RAGStore(data_dir=DATA_DIR)
        store._embed_fn = make_stub_embed(store, [-1.0, -1.0, -1.0])

        class ExplodingLLM:
            async def chat(self, messages):  # pragma: no cover
                raise AssertionError("Le LLM ne doit pas être appelé en cas d'abstention")

        result = await store.answer_with_sources("Hors sujet ?", ExplodingLLM(), k=3)
        self.assertEqual(result["answer"], ABSTENTION_MESSAGE)
        self.assertEqual(result["sources"], [])

    def test_system_prompt_forbids_invention(self) -> None:
        self.assertIn("UNIQUEMENT", RAG_SYSTEM_PROMPT)
        self.assertIn("je ne sais pas", RAG_SYSTEM_PROMPT.lower())


if __name__ == "__main__":
    unittest.main()
