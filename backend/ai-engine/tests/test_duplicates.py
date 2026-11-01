"""Tests détection de doublons : embeddings mockés déterministes, aucun réseau."""
from __future__ import annotations

import math
import unittest

from app.duplicate_detector import DEFAULT_SIMILARITY_THRESHOLD, DuplicateDetector
from app.schemas import DuplicateCheckRequest, IncidentItem


class StubEmbedder:
    """Mock déterministe : vecteurs fixés par texte, jamais de réseau."""

    model = "stub-embed"

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    async def get_embedding(self, text: str) -> list[float]:
        return list(self.vectors.get(text, []))

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [list(self.vectors.get(t, [])) for t in texts]


def _req(incoming: str, incidents: list[IncidentItem], **kw) -> DuplicateCheckRequest:
    return DuplicateCheckRequest(incoming_summary=incoming, active_incidents=incidents, **kw)


class ThresholdDefaultTest(unittest.TestCase):
    def test_default_threshold_is_080(self) -> None:
        self.assertEqual(
            DuplicateCheckRequest(incoming_summary="x", active_incidents=[]).similarity_threshold,
            0.80,
        )
        self.assertEqual(DEFAULT_SIMILARITY_THRESHOLD, 0.80)


class DuplicateVerdictTest(unittest.IsolatedAsyncioTestCase):
    async def test_near_identical_is_duplicate(self) -> None:
        llm = StubEmbedder({"in": [1.0, 0.0, 0.0], "same": [1.0, 0.0, 0.0]})
        res = await DuplicateDetector(llm).check(  # type: ignore[arg-type]
            _req("in", [IncidentItem(id=7, summary="same", category="water")])
        )
        self.assertTrue(res.is_duplicate)
        self.assertEqual(res.matched_incident_id, 7)
        self.assertEqual(res.similarity_score, 1.0)

    async def test_different_is_not_duplicate(self) -> None:
        llm = StubEmbedder({"in": [1.0, 0.0, 0.0], "other": [0.0, 1.0, 0.0]})
        res = await DuplicateDetector(llm).check(  # type: ignore[arg-type]
            _req("in", [IncidentItem(id=8, summary="other", category="water")])
        )
        self.assertFalse(res.is_duplicate)
        self.assertIsNone(res.matched_incident_id)

    async def test_stricter_custom_threshold_flips_verdict(self) -> None:
        # Cosinus exact 0.85 : doublon à 0.80, pas à 0.95.
        llm = StubEmbedder({"in": [1.0, 0.0], "near": [0.85, math.sqrt(1.0 - 0.85**2)]})
        det = DuplicateDetector(llm)  # type: ignore[arg-type]
        req = _req("in", [IncidentItem(id=9, summary="near", category="water")])
        self.assertTrue((await det.check(req)).is_duplicate)
        self.assertTrue((await det.check(req, threshold=0.80)).is_duplicate)
        strict = await det.check(req, threshold=0.95)
        self.assertFalse(strict.is_duplicate)
        self.assertIsNone(strict.matched_incident_id)

    async def test_request_level_threshold_preserved(self) -> None:
        # Non-régression : sans paramètre, le seuil du body s'applique toujours.
        llm = StubEmbedder({"in": [1.0, 0.0], "near": [0.85, math.sqrt(1.0 - 0.85**2)]})
        req = _req(
            "in",
            [IncidentItem(id=9, summary="near", category="water")],
            similarity_threshold=0.95,
        )
        res = await DuplicateDetector(llm).check(req)  # type: ignore[arg-type]
        self.assertFalse(res.is_duplicate)

    async def test_no_incidents_is_not_duplicate(self) -> None:
        llm = StubEmbedder({})
        res = await DuplicateDetector(llm).check(_req("in", []))  # type: ignore[arg-type]
        self.assertFalse(res.is_duplicate)


class BatchSingleCallTest(unittest.IsolatedAsyncioTestCase):
    async def test_check_uses_one_batch_call(self) -> None:
        llm = StubEmbedder({
            "in": [1.0, 0.0],
            "a": [1.0, 0.0],
            "b": [0.0, 1.0],
            "c": [1.0, 0.0],
        })
        calls: list[list[str]] = []
        orig = llm.get_embeddings

        async def spy(texts: list[str]) -> list[list[float]]:
            calls.append(list(texts))
            return await orig(texts)

        llm.get_embeddings = spy  # type: ignore[method-assign]
        res = await DuplicateDetector(llm).check(  # type: ignore[arg-type]
            _req("in", [
                IncidentItem(id=1, summary="a", category="water"),
                IncidentItem(id=2, summary="b", category="water"),
                IncidentItem(id=3, summary="c", category="water"),
            ])
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ["in", "a", "b", "c"])
        self.assertTrue(res.is_duplicate)

    async def test_runtime_error_falls_back_to_jaccard(self) -> None:
        class RaisingEmbedder(StubEmbedder):
            async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
                raise RuntimeError("Embeddings indisponibles (mock)")

        llm = RaisingEmbedder({})
        res = await DuplicateDetector(llm).check(  # type: ignore[arg-type]
            _req(
                "pompe cassee plus eau",
                [IncidentItem(id=3, summary="pompe cassee plus eau", category="water")],
            )
        )
        self.assertTrue(res.is_duplicate)


class FallbackTextMatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_identical_text_is_duplicate_without_embeddings(self) -> None:
        llm = StubEmbedder({})  # aucun vecteur -> repli Jaccard
        res = await DuplicateDetector(llm).check(  # type: ignore[arg-type]
            _req(
                "pompe cassee plus eau",
                [IncidentItem(id=3, summary="pompe cassee plus eau", category="water")],
            )
        )
        self.assertTrue(res.is_duplicate)

    async def test_different_text_is_not_duplicate_without_embeddings(self) -> None:
        llm = StubEmbedder({})
        res = await DuplicateDetector(llm).check(  # type: ignore[arg-type]
            _req(
                "pompe cassee plus eau",
                [IncidentItem(id=4, summary="latrines propres filles", category="sanitation")],
            )
        )
        self.assertFalse(res.is_duplicate)


if __name__ == "__main__":
    unittest.main()
