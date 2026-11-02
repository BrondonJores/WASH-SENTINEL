"""Chat agent avec vision : photo jointe -> analyse + carte + synthèse.

Contrat inter-agents : AgentChatRequest gagne image_base64 + image_mime,
c'est tout ce que Laravel envoie. Sans image, comportement strictement
inchangé (aucun appel vision, aucune carte photo).

Lancer depuis backend/ai-engine : ./.venv/bin/python -m unittest
"""
from __future__ import annotations

import base64
import json
import unittest

import httpx
from pydantic import ValidationError

from app.agent_loop import AgentLoop
from app.schemas import (
    CHAT_IMAGE_MAX_BYTES,
    AgentChatRequest,
    AgentContext,
)
from app.providers import OllamaProvider, OpenAICompatibleProvider

CONTEXT = AgentContext(schools=[], incidents=[])
SMALL_B64 = base64.b64encode(b"fake-image-bytes").decode("ascii")

VISION_DICT = {
    "is_wash_related": True,
    "infrastructure_detected": "Pompe manuelle India Mark II",
    "visible_damage": "Fissure nette sur le conduit",
    "visual_severity_score": 72.0,
    "health_hazard_detected": True,
    "technician_notes": "Isoler la pompe et purger le circuit.",
}

TEXT_REPLY = {
    "raw": {"role": "assistant", "content": "Vu, pompe fissurée."},
    "content": "Vu, pompe fissurée.",
    "tool_calls": [],
}


class VisionStubLLM:
    """Stub texte seul (SANS chat_with_image) + vision scriptée."""

    def __init__(self, vision_dict=None, vision_error=None):
        self.model = "stub"
        self.vision_dict = VISION_DICT if vision_dict is None else vision_dict
        self.vision_error = vision_error
        self.vision_calls = 0
        self.chat_calls = 0
        self.seen_messages = None

    async def generate_vision_json(self, prompt, image_base64, system=""):
        self.vision_calls += 1
        if self.vision_error is not None:
            raise self.vision_error
        return dict(self.vision_dict)

    async def chat(self, messages, tools=None):
        self.chat_calls += 1
        self.seen_messages = list(messages)
        return dict(TEXT_REPLY)

    def format_tool_result(self, name, result, call_id=None):
        return {"role": "tool",
                "content": json.dumps(result, ensure_ascii=False)}


class VisionCapableStubLLM(VisionStubLLM):
    """Stub avec support vision du chat (enregistre l'appel)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.vision_chat_calls = []

    async def chat_with_image(self, messages, image_base64, image_mime="image/jpeg",
                              tools=None):
        self.vision_chat_calls.append({
            "messages": list(messages),
            "image_base64": image_base64,
            "image_mime": image_mime,
        })
        self.seen_messages = list(messages)
        return dict(TEXT_REPLY)


class BrokenVisionChatStubLLM(VisionStubLLM):
    """chat_with_image présent mais en échec -> repli texte attendu."""

    async def chat_with_image(self, messages, image_base64, image_mime="image/jpeg",
                              tools=None):
        raise RuntimeError("modèle texte seul, pas de vision")


def _req(message="Voici une photo, tu en penses quoi ?", **kwargs):
    return AgentChatRequest(message=message, context=CONTEXT, **kwargs)


class NoImageUnchangedTest(unittest.IsolatedAsyncioTestCase):
    async def test_request_without_image_is_unchanged(self) -> None:
        stub = VisionStubLLM()
        res = await AgentLoop(stub).chat(_req("bonjour"))
        self.assertEqual(res.answer, "Vu, pompe fissurée.")
        self.assertEqual(res.tools_executed, [])
        self.assertEqual(res.cards, [])
        self.assertEqual(stub.vision_calls, 0)
        self.assertGreaterEqual(stub.chat_calls, 1)
        user_text = " ".join(
            m.get("content", "") for m in stub.seen_messages
            if isinstance(m.get("content"), str))
        self.assertNotIn("Photo", user_text)


class ImageSizeValidationTest(unittest.TestCase):
    def test_oversize_image_rejected(self) -> None:
        huge = base64.b64encode(b"x" * (CHAT_IMAGE_MAX_BYTES + 1)).decode("ascii")
        with self.assertRaises(ValidationError) as ctx:
            _req(image_base64=huge, image_mime="image/jpeg")
        self.assertIn("10 Mo", str(ctx.exception))

    def test_exact_limit_accepted(self) -> None:
        edge = base64.b64encode(b"y" * CHAT_IMAGE_MAX_BYTES).decode("ascii")
        req = _req(image_base64=edge)
        self.assertIsNotNone(req.image_base64)

    def test_invalid_base64_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            _req(image_base64="!!! pas du base64 !!!")

    def test_data_url_prefix_tolerated(self) -> None:
        req = _req(image_base64="data:image/jpeg;base64," + SMALL_B64)
        self.assertIsNotNone(req.image_base64)


class PhotoCardAndSummaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_image_gives_card_and_injected_summary(self) -> None:
        stub = VisionStubLLM()
        res = await AgentLoop(stub).chat(
            _req(image_base64=SMALL_B64, image_mime="image/jpeg"))
        self.assertEqual(stub.vision_calls, 1)
        self.assertEqual(len(res.cards), 1)
        card = res.cards[0]
        self.assertEqual(card.type, "photo_analysis")
        self.assertEqual(card.type, "photo_analysis")
        for key in ("infrastructure_detected", "visible_damage",
                    "visual_severity_score", "health_hazard_detected",
                    "technician_notes", "vision_unavailable"):
            self.assertIn(key, card.data)
        self.assertEqual(card.data["visual_severity_score"], 72.0)
        self.assertFalse(card.data["vision_unavailable"])
        # Résumé déterministe injecté dans le message user : le LLM
        # commente ces faits, il ne devine rien.
        user_msg = stub.seen_messages[-1]["content"]
        self.assertIn("Pompe manuelle India Mark II", user_msg)
        self.assertIn("72/100", user_msg)
        self.assertIn("Fissure nette sur le conduit", user_msg)
        self.assertEqual(res.answer, "Vu, pompe fissurée.")


class TextFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_when_provider_has_no_vision_chat(self) -> None:
        stub = VisionStubLLM()  # pas de chat_with_image
        self.assertFalse(hasattr(stub, "chat_with_image"))
        res = await AgentLoop(stub).chat(_req(image_base64=SMALL_B64))
        self.assertEqual(res.answer, "Vu, pompe fissurée.")
        self.assertGreaterEqual(stub.chat_calls, 1)
        self.assertEqual(len(res.cards), 1)
        self.assertEqual(res.cards[0].type, "photo_analysis")

    async def test_fallback_when_vision_chat_raises(self) -> None:
        stub = BrokenVisionChatStubLLM()
        res = await AgentLoop(stub).chat(_req(image_base64=SMALL_B64))
        self.assertEqual(res.answer, "Vu, pompe fissurée.")
        self.assertGreaterEqual(stub.chat_calls, 1)
        self.assertEqual(len(res.cards), 1)

    async def test_graceful_when_vision_model_fails(self) -> None:
        stub = VisionStubLLM(vision_error=RuntimeError("404 modèle absent"))
        res = await AgentLoop(stub).chat(_req(image_base64=SMALL_B64))
        self.assertEqual(res.answer, "Vu, pompe fissurée.")
        self.assertEqual(len(res.cards), 1)
        card = res.cards[0]
        self.assertEqual(card.type, "photo_analysis")
        self.assertTrue(card.data["vision_unavailable"])
        user_msg = stub.seen_messages[-1]["content"]
        self.assertIn("vision indisponible", user_msg)


class VisionChatUsedTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_with_image_used_when_available(self) -> None:
        stub = VisionCapableStubLLM()
        res = await AgentLoop(stub).chat(
            _req(image_base64=SMALL_B64, image_mime="image/jpeg"))
        self.assertEqual(len(stub.vision_chat_calls), 1)
        call = stub.vision_chat_calls[0]
        self.assertEqual(call["image_base64"], SMALL_B64)
        self.assertEqual(call["image_mime"], "image/jpeg")
        self.assertEqual(res.answer, "Vu, pompe fissurée.")
        self.assertEqual(res.cards[0].type, "photo_analysis")


def _mock_provider(provider_cls, handler, **kwargs):
    provider = provider_cls(base_url="http://llm-test:11434", model="test-model",
                            **kwargs)
    provider._transport = httpx.MockTransport(handler)
    return provider


class OpenAIMultimodalPayloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_forms_text_plus_image_url_content(self) -> None:
        seen: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}]},
                request=request,
            )

        provider = _mock_provider(OpenAICompatibleProvider, handler,
                                  vision_model="gpt-4o")
        messages = [{"role": "user", "content": "Décris la panne."}]
        reply = await provider.chat_with_image(messages, SMALL_B64, "image/png")
        self.assertEqual(reply["content"], "ok")
        self.assertEqual(len(seen), 1)
        body = seen[0]
        self.assertEqual(body["model"], "gpt-4o")
        content = body["messages"][-1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "Décris la panne."})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith(
            "data:image/png;base64," + SMALL_B64))
        # Pureté : les messages d'entrée ne sont pas mutés.
        self.assertEqual(messages, [{"role": "user", "content": "Décris la panne."}])


class OllamaImagesPayloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_forms_images_array_on_chat_endpoint(self) -> None:
        seen: list = []
        paths: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            seen.append(json.loads(request.content.decode()))
            return httpx.Response(
                200, json={"message": {"content": "ok"}}, request=request)

        provider = _mock_provider(OllamaProvider, handler,
                                  vision_model="moondream")
        reply = await provider.chat_with_image(
            [{"role": "user", "content": "Décris la panne."}], SMALL_B64)
        self.assertEqual(reply["content"], "ok")
        self.assertEqual(paths, ["/api/chat"])
        body = seen[0]
        self.assertEqual(body["model"], "moondream")
        self.assertEqual(body["messages"][-1]["images"], [SMALL_B64])
        self.assertEqual(body["messages"][-1]["content"], "Décris la panne.")


if __name__ == "__main__":
    unittest.main()
