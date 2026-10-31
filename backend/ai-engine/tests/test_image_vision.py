"""Vision live legere : anti-spam, diagnostic WASH, repli gracieux, boost.

LLM toujours moque (stubs, cf. tests/test_extractor.py) : aucun appel Ollama reel.
Lancer depuis backend/ai-engine : .venv/bin/python -m unittest tests.test_image_vision
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.image_analyzer import (
    DEFAULT_VISION_MODEL,
    VISION_MODEL_ENV_VAR,
    VISION_UNAVAILABLE_MARKER,
    ImageAnalyzer,
    is_vision_unavailable,
    resolve_vision_model,
    visual_boost,
    visual_severity,
)
from app.providers import VISION_FALLBACK


class StubVisionLLM:
    model = "stub-text"
    vision_model = "stub-vision"

    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls: list[dict] = []

    async def generate_vision_json(self, prompt: str, image_base64: str, system: str = "") -> dict:
        self.calls.append({"prompt": prompt, "image_base64": image_base64, "system": system})
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return dict(self.payload)


OFF_TOPIC_PAYLOAD = {
    "is_wash_related": False,
    "infrastructure_detected": "Salon",
    "visible_damage": "Aucun dégât WASH",
    "visual_severity_score": 0.0,
    "health_hazard_detected": False,
    "technician_notes": "Photo hors-sujet : un chat sur un canapé.",
}

WASH_PAYLOAD = {
    "is_wash_related": True,
    "infrastructure_detected": "Pompe manuelle India Mark II",
    "visible_damage": "Fissure nette sur le conduit de refoulement",
    "visual_severity_score": 82.0,
    "health_hazard_detected": True,
    "technician_notes": "Couper l'alimentation et remplacer le joint.",
}

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class ResolveVisionModelTest(unittest.TestCase):
    def test_default_is_lightweight(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_vision_model(), "moondream")
            self.assertEqual(resolve_vision_model(), DEFAULT_VISION_MODEL)

    def test_env_var_honored(self) -> None:
        with patch.dict(os.environ, {VISION_MODEL_ENV_VAR: "llava:7b"}):
            self.assertEqual(resolve_vision_model(), "llava:7b")

    def test_explicit_wins_over_env(self) -> None:
        with patch.dict(os.environ, {VISION_MODEL_ENV_VAR: "llava:7b"}):
            self.assertEqual(resolve_vision_model("moondream"), "moondream")


class AnalyzerConfigTest(unittest.TestCase):
    def test_explicit_model_overrides_provider(self) -> None:
        stub = StubVisionLLM(WASH_PAYLOAD)
        analyzer = ImageAnalyzer(stub, vision_model="moondream")  # type: ignore[arg-type]
        self.assertEqual(analyzer.vision_model, "moondream")
        self.assertEqual(stub.vision_model, "moondream")

    def test_provider_model_kept_by_default(self) -> None:
        stub = StubVisionLLM(WASH_PAYLOAD)
        analyzer = ImageAnalyzer(stub)  # type: ignore[arg-type]
        self.assertEqual(analyzer.vision_model, "stub-vision")


class AntiSpamTest(unittest.IsolatedAsyncioTestCase):
    async def test_off_topic_rejected(self) -> None:
        stub = StubVisionLLM(OFF_TOPIC_PAYLOAD)
        res = await ImageAnalyzer(stub).analyze(FAKE_JPEG)  # type: ignore[arg-type]
        self.assertFalse(res.is_wash_related)
        self.assertFalse(is_vision_unavailable(res))
        self.assertEqual(visual_severity(res), 0)
        self.assertEqual(visual_boost(visual_severity(res)), 0.0)
        self.assertTrue(stub.calls and len(stub.calls[0]["image_base64"]) > 0)


class WashPhotoTest(unittest.IsolatedAsyncioTestCase):
    async def test_wash_photo_gives_diagnostic_and_severity(self) -> None:
        stub = StubVisionLLM(WASH_PAYLOAD)
        res = await ImageAnalyzer(stub).analyze(FAKE_JPEG)  # type: ignore[arg-type]
        self.assertTrue(res.is_wash_related)
        self.assertIn("Pompe manuelle", res.infrastructure_detected)
        self.assertTrue(res.health_hazard_detected)
        self.assertEqual(visual_severity(res), 82)
        self.assertEqual(visual_boost(82), round(82 * 0.15, 1))
        self.assertGreater(visual_boost(visual_severity(res)), 0.0)


class GracefulFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_model_gives_explicit_fallback(self) -> None:
        stub = StubVisionLLM(error=RuntimeError("Modèle Ollama 'x' introuvable (404)."))
        res = await ImageAnalyzer(stub).analyze(FAKE_JPEG)  # type: ignore[arg-type]
        self.assertIn(VISION_UNAVAILABLE_MARKER, res.visible_damage)
        self.assertIn(VISION_UNAVAILABLE_MARKER, res.technician_notes)
        self.assertTrue(is_vision_unavailable(res))
        self.assertIsNone(visual_severity(res))
        self.assertEqual(visual_boost(visual_severity(res)), 0.0)

    async def test_timeout_gives_explicit_fallback(self) -> None:
        stub = StubVisionLLM(error=TimeoutError("ollama timed out"))
        res = await ImageAnalyzer(stub).analyze(FAKE_JPEG)  # type: ignore[arg-type]
        self.assertTrue(is_vision_unavailable(res))
        self.assertIsNone(visual_severity(res))

    async def test_silent_provider_fallback_requalified(self) -> None:
        stub = StubVisionLLM(dict(VISION_FALLBACK))
        res = await ImageAnalyzer(stub).analyze(FAKE_JPEG)  # type: ignore[arg-type]
        self.assertTrue(is_vision_unavailable(res))
        self.assertIsNone(visual_severity(res))

    async def test_missing_score_never_invented(self) -> None:
        payload = {k: v for k, v in WASH_PAYLOAD.items() if k != "visual_severity_score"}
        stub = StubVisionLLM(payload)
        res = await ImageAnalyzer(stub).analyze(FAKE_JPEG)  # type: ignore[arg-type]
        self.assertTrue(is_vision_unavailable(res))
        self.assertIsNone(visual_severity(res))

    async def test_empty_image_does_not_raise(self) -> None:
        stub = StubVisionLLM(WASH_PAYLOAD)
        res = await ImageAnalyzer(stub).analyze(b"")  # type: ignore[arg-type]
        self.assertTrue(is_vision_unavailable(res))
        self.assertEqual(stub.calls, [])


class VisualBoostTest(unittest.TestCase):
    def test_none_gives_zero(self) -> None:
        self.assertEqual(visual_boost(None), 0.0)

    def test_bounds(self) -> None:
        self.assertEqual(visual_boost(0), 0.0)
        self.assertEqual(visual_boost(100), 15.0)
        self.assertEqual(visual_boost(-5), 0.0)
        self.assertEqual(visual_boost(999), 15.0)

    def test_monotone_and_bounded(self) -> None:
        previous = -1.0
        for severity in range(0, 101):
            boost = visual_boost(severity)
            self.assertGreaterEqual(boost, 0.0)
            self.assertLessEqual(boost, 15.0)
            self.assertGreaterEqual(boost, previous)
            previous = boost


if __name__ == "__main__":
    unittest.main()
