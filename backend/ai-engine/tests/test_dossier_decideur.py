"""Dossier décideur : génération d'image cloud + rapport pur anti-invention.

Zéro réseau : httpx.MockTransport uniquement, LLM stubbé pour run_dossier.
"""
from __future__ import annotations

import base64
import json
import os
import re
import unittest
from typing import get_args
from unittest import mock

import httpx

from app.providers import (
    IMAGE_GENERATIONS_PATH_DEFAULT,
    NotSupportedError,
    OllamaProvider,
    OpenAICompatibleProvider,
)
from app.tools import dossier_decideur
from app.tools.dossier_decideur import SECTION_HEADINGS, build_dossier, run_dossier

_FAKE_PNG = b"\x89PNG-fake-bytes"

SCHOOLS = [
    {"school_id": 1, "school_name": "École Publique de Bonanjo", "district": "Wouri"},
    {"school_id": 2, "school_name": "École de Nkol", "district": "Mvila"},
]

INCIDENTS = [
    {"id": 1, "school_id": 1, "school_name": "École Publique de Bonanjo",
     "district": "Wouri", "title": "Pompe cassée",
     "summary": "Pompe principale hors service", "status": "open",
     "urgency": "critical", "affected_students": 450,
     "reported_at": "2026-10-20T08:00:00+00:00", "reference_code": "WASH-001"},
    {"id": 2, "school_id": 2, "school_name": "École de Nkol",
     "district": "Mvila", "title": "Eau contaminée",
     "summary": "Eau jaunâtre au forage", "status": "open",
     "urgency": "high", "affected_students": 160,
     "reported_at": "2026-11-01T08:00:00+00:00", "reference_code": "WASH-002"},
]

LOGS = [
    {"id": 1, "school_id": 1, "school_name": "École Publique de Bonanjo",
     "action": "Remplacement du joint de pompe", "cost_amount": 50000,
     "created_at": "2026-10-25T10:00:00+00:00"},
    {"id": 2, "school_id": 2, "school_name": "École de Nkol",
     "action": "Chloration du forage", "cost_amount": 25000,
     "created_at": "2026-11-01T12:00:00+00:00"},
]

CONTEXT = {"schools": SCHOOLS, "incidents": INCIDENTS,
           "maintenance_logs": LOGS,
           "photos": [{"title": "Pompe Bonanjo fissurée"}]}

NO_BUDGET = {"schools": SCHOOLS, "incidents": INCIDENTS,
             "maintenance_logs": [
                 {"id": 9, "school_id": 1,
                  "school_name": "École Publique de Bonanjo",
                  "action": "Diagnostic visuel",
                  "created_at": "2026-11-01T12:00:00+00:00"},
             ]}


def _mock_image_provider(handler, **kwargs):
    provider = OpenAICompatibleProvider(
        base_url="http://img-test:11434/v1", model="text-model",
        api_key="k", **kwargs)
    provider._transport = httpx.MockTransport(handler)
    return provider


def _xaf_amounts(report: dict) -> list[str]:
    dumped = json.dumps(report, ensure_ascii=False)
    return [m.strip() for m in re.findall(r"[\d ]+ XAF", dumped)]


class GenerateImageTest(unittest.IsolatedAsyncioTestCase):
    async def test_b64_json_decoded(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            payload = {"data": [{"b64_json": base64.b64encode(_FAKE_PNG).decode("ascii")}]}
            return httpx.Response(200, json=payload, request=request)

        provider = _mock_image_provider(handler)
        raw = await provider.generate_image("Une pompe bleue", "1024x1024")
        self.assertEqual(raw, _FAKE_PNG)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].url.path.endswith(IMAGE_GENERATIONS_PATH_DEFAULT))
        body = json.loads(seen[0].content.decode("utf-8"))
        self.assertEqual(body["prompt"], "Une pompe bleue")
        self.assertEqual(body["size"], "1024x1024")
        self.assertEqual(body["model"], "muse-image-1.0")

    async def test_http_url_downloaded(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "GET":
                return httpx.Response(200, content=_FAKE_PNG, request=request)
            return httpx.Response(
                200, json={"data": [{"url": "https://cdn.test/affiche.png"}]},
                request=request)

        provider = _mock_image_provider(handler)
        raw = await provider.generate_image("Une affiche")
        self.assertEqual(raw, _FAKE_PNG)
        self.assertEqual([r.method for r in seen], ["POST", "GET"])

    async def test_data_url_no_second_call(self) -> None:
        seen: list[httpx.Request] = []
        data_url = ("data:image/png;base64,"
                    + base64.b64encode(_FAKE_PNG).decode("ascii"))

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": [{"url": data_url}]},
                                    request=request)

        provider = _mock_image_provider(handler)
        raw = await provider.generate_image("Une affiche")
        self.assertEqual(raw, _FAKE_PNG)
        self.assertEqual(len(seen), 1)

    async def test_401_explicit_french(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "bad key"}, request=request)

        provider = _mock_image_provider(handler)
        with self.assertRaises(RuntimeError) as ctx:
            await provider.generate_image("Une affiche")
        self.assertIn("clé API", str(ctx.exception))
        self.assertIn("401", str(ctx.exception))

    async def test_response_without_image_explicit(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{}]}, request=request)

        provider = _mock_image_provider(handler)
        with self.assertRaises(RuntimeError) as ctx:
            await provider.generate_image("Une affiche")
        self.assertIn("sans 'b64_json' ni 'url'", str(ctx.exception))

    async def test_ollama_refuses_cleanly(self) -> None:
        provider = OllamaProvider(base_url="http://x:11434", model="llama3.2:3b")
        with self.assertRaises(NotSupportedError) as ctx:
            await provider.generate_image("Une affiche")
        self.assertIn("génération d'image cloud uniquement", str(ctx.exception))

    async def test_path_and_model_env_override(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            payload = {"data": [{"b64_json": base64.b64encode(_FAKE_PNG).decode("ascii")}]}
            return httpx.Response(200, json=payload, request=request)

        provider = _mock_image_provider(handler)
        env = {"OPENAI_IMAGE_GENERATIONS_PATH": "custom/img",
               "OPENAI_IMAGE_MODEL": "autre-modele"}
        with mock.patch.dict(os.environ, env):
            raw = await provider.generate_image("Une affiche")
        self.assertEqual(raw, _FAKE_PNG)
        self.assertTrue(seen[0].url.path.endswith("custom/img"))
        body = json.loads(seen[0].content.decode("utf-8"))
        self.assertEqual(body["model"], "autre-modele")


class BuildDossierTest(unittest.TestCase):
    def test_sections_complete_ordered(self) -> None:
        built = build_dossier("district", scope_name="Mvila", context=CONTEXT)
        report = built["report"]
        self.assertIn("Mvila", report["subject"])
        self.assertTrue(report["period"])
        self.assertEqual([s["heading"] for s in report["sections"]],
                         list(SECTION_HEADINGS))
        for section in report["sections"]:
            self.assertTrue(section["body_md"])
            self.assertIsInstance(section["figures"], list)
        summary = report["sections"][0]["body_md"]
        lines = [line for line in summary.splitlines() if line.strip()]
        self.assertLessEqual(len(lines), 5)

    def test_no_budget_adversarial_never_invented(self) -> None:
        built = build_dossier(None, context=NO_BUDGET)
        report = built["report"]
        dumped = json.dumps(report, ensure_ascii=False)
        budget = next(s for s in report["sections"] if s["heading"] == "Budget")
        self.assertIn("non communiqué", budget["body_md"])
        self.assertNotIn("XAF", dumped)
        self.assertNotIn("1500000", dumped)
        self.assertNotIn("1 500 000", dumped)
        for section in report["sections"]:
            for figure in section["figures"]:
                self.assertNotIn("XAF", json.dumps(figure, ensure_ascii=False))

    def test_figures_verified_from_context_only(self) -> None:
        built = build_dossier(None, context=CONTEXT)
        report = built["report"]
        expected = {"50 000 XAF", "25 000 XAF", "75 000 XAF"}
        self.assertLessEqual(set(_xaf_amounts(report)), expected)
        self.assertIn("75 000 XAF", json.dumps(report, ensure_ascii=False))
        dumped_ctx = json.dumps(CONTEXT, ensure_ascii=False)
        for stamp in ("2026-10-20", "2026-11-01"):
            self.assertIn(stamp, dumped_ctx)
        self.assertIn("2026-10-20", report["period"])
        self.assertIn("2026-11-01", report["period"])
        annexes = next(s for s in report["sections"] if s["heading"] == "Annexes")
        self.assertIn("Pompe Bonanjo fissurée", annexes["body_md"])

    def test_poster_prompt_factual_only(self) -> None:
        built = build_dossier("school", scope_name="Bonanjo", context=CONTEXT)
        prompt = built["poster_prompt"]
        self.assertIn("Bonanjo", prompt)
        self.assertIn("Pompe cassée", prompt)
        self.assertIn("450", prompt)
        self.assertNotIn("XAF", prompt)
        self.assertNotIn("1500000", prompt)
        self.assertIn("Bonanjo", built["poster_caption"])

    def test_deck_ref_reuses_briefing(self) -> None:
        built = build_dossier(None, context=CONTEXT)
        deck = built["deck_ref"]
        self.assertEqual(deck["source"], "document_briefing")
        self.assertGreater(len(deck["slides"]), 0)
        self.assertEqual(deck["slides_count"], len(deck["slides"]))
        kinds = {slide["kind"] for slide in deck["slides"]}
        self.assertIn("cover", kinds)

    def test_empty_context_never_raises(self) -> None:
        built = build_dossier("district", scope_name="Zorglub", context=CONTEXT)
        self.assertEqual(len(built["report"]["sections"]), 6)
        self.assertEqual(built["deck_ref"]["source"], None)
        self.assertTrue(built["deck_ref"]["reason"])
        self.assertNotIn("450", built["poster_prompt"])
        nothing = build_dossier(None, context={})
        self.assertEqual(len(nothing["report"]["sections"]), 6)
        self.assertIn("non communiqué", nothing["report"]["period"])


class _StubImageLLM:
    def __init__(self, payload: bytes | Exception):
        self.payload = payload
        self.seen: list[tuple[str, str]] = []

    async def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes:
        self.seen.append((prompt, size))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class RunDossierTest(unittest.IsolatedAsyncioTestCase):
    async def test_poster_base64_and_cards(self) -> None:
        llm = _StubImageLLM(_FAKE_PNG)
        run = await run_dossier(llm, "district", "Mvila", CONTEXT)
        self.assertIsNone(run["poster_error"])
        self.assertEqual(base64.b64decode(run["poster"]["image_base64"]), _FAKE_PNG)
        self.assertEqual(set(run["poster"]), {"image_base64", "image_url",
                                              "prompt", "caption"})
        self.assertEqual(set(run["report"]), {"subject", "period", "sections"})
        self.assertEqual([c.type for c in run["cards"]],
                         ["poster", "dossier_report"])
        self.assertEqual(llm.seen[0][1], "1024x1024")
        self.assertIn("Mvila", llm.seen[0][0])

    async def test_image_failure_keeps_report(self) -> None:
        llm = _StubImageLLM(NotSupportedError("génération d'image cloud uniquement"))
        run = await run_dossier(llm, None, None, CONTEXT)
        self.assertIsNone(run["poster"]["image_base64"])
        self.assertIsNone(run["poster"]["image_url"])
        self.assertIn("Affiche indisponible", run["poster_error"] or "")
        self.assertEqual([c.type for c in run["cards"]], ["dossier_report"])
        self.assertEqual(len(run["report"]["sections"]), 6)


class DossierCardContractTest(unittest.TestCase):
    def test_types_emitted_now_wired(self) -> None:
        from app.schemas import FRONTEND_RESERVED, CardType
        literal = set(get_args(CardType))
        self.assertIn("poster", literal)
        self.assertIn("dossier_report", literal)
        # Câblage livré (cases frontend + branche loop) : émis, plus réservés.
        self.assertNotIn("poster", set(FRONTEND_RESERVED))
        self.assertNotIn("dossier_report", set(FRONTEND_RESERVED))

    def test_module_not_auto_discovered(self) -> None:
        from app.agent_tools import PLUGIN_CARDS, TOOL_EXECUTORS
        self.assertNotIn("dossier_decideur", TOOL_EXECUTORS)
        emitted = {card for builders in PLUGIN_CARDS.values()
                   for card in builders}
        self.assertNotIn("poster", emitted)
        self.assertNotIn("dossier_report", emitted)

    def test_builders_validate_contract(self) -> None:
        from app.schemas import DossierReportCardData, PosterCardData
        run_poster = {"image_base64": base64.b64encode(_FAKE_PNG).decode("ascii"),
                      "image_url": None, "prompt": "p", "caption": "c"}
        card = dossier_decideur.build_poster_card(run_poster)
        self.assertIsNotNone(card)
        assert card is not None
        PosterCardData.model_validate(card.data)
        self.assertIsNone(dossier_decideur.build_poster_card(
            {"image_base64": None, "image_url": None, "prompt": "p", "caption": "c"}))
        report = build_dossier(None, context=CONTEXT)["report"]
        report_card = dossier_decideur.build_dossier_report_card(report)
        self.assertIsNotNone(report_card)
        assert report_card is not None
        DossierReportCardData.model_validate(report_card.data)
        self.assertIsNone(dossier_decideur.build_dossier_report_card({}))


class _StubLoopLLM(_StubImageLLM):
    """Stub boucle : generate_image scripté + chat compté (0 attendu)."""

    def __init__(self, payload: bytes | Exception):
        super().__init__(payload)
        self.model = "stub"
        self.chat_calls = 0

    async def chat(self, messages, tools=None):
        self.chat_calls += 1
        return {"raw": {"role": "assistant", "content": "hors branche"},
                "content": "hors branche", "tool_calls": []}

    def format_tool_result(self, name, result, call_id=None):
        return {"role": "tool",
                "content": json.dumps(result, ensure_ascii=False)}


def _loop_req(message: str):
    from app.schemas import AgentChatRequest, AgentContext
    return AgentChatRequest(
        message=message,
        context=AgentContext(
            schools=[dict(s) for s in SCHOOLS],
            incidents=[dict(i) for i in INCIDENTS],
            maintenance_logs=[dict(l) for l in LOGS]),
    )


class DossierLoopBranchTest(unittest.IsolatedAsyncioTestCase):
    async def test_dossier_school_bypasses_llm(self) -> None:
        from app.agent_loop import AgentLoop
        stub = _StubLoopLLM(_FAKE_PNG)
        res = await AgentLoop(stub).chat(_loop_req("Prépare le dossier de Nkol"))
        self.assertEqual(res.tools_executed, ["dossier_decideur"])
        self.assertEqual([c.type for c in res.cards],
                         ["poster", "dossier_report"])
        self.assertEqual(stub.chat_calls, 0)
        self.assertIn("Nkol", res.answer)
        self.assertIn("6 sections", res.answer)

    async def test_affiche_district(self) -> None:
        from app.agent_loop import AgentLoop
        stub = _StubLoopLLM(_FAKE_PNG)
        res = await AgentLoop(stub).chat(
            _loop_req("Génère une affiche pour le district Mvila"))
        self.assertEqual(res.tools_executed, ["dossier_decideur"])
        self.assertIn("poster", [c.type for c in res.cards])
        self.assertIn("Mvila", res.answer)

    async def test_image_failure_keeps_report(self) -> None:
        from app.agent_loop import AgentLoop
        stub = _StubLoopLLM(NotSupportedError("cloud uniquement"))
        res = await AgentLoop(stub).chat(_loop_req("Prépare le dossier de Nkol"))
        self.assertEqual(res.tools_executed, ["dossier_decideur"])
        self.assertEqual([c.type for c in res.cards], ["dossier_report"])
        self.assertIn("Affiche indisponible", res.answer)

    async def test_no_place_falls_through(self) -> None:
        from app.agent_loop import AgentLoop
        stub = _StubLoopLLM(_FAKE_PNG)
        res = await AgentLoop(stub).chat(_loop_req("Prépare un dossier"))
        self.assertNotIn("dossier_decideur", res.tools_executed)

    async def test_briefing_not_captured(self) -> None:
        from app.agent_loop import AgentLoop
        stub = _StubLoopLLM(_FAKE_PNG)
        res = await AgentLoop(stub).chat(_loop_req("Prépare un briefing du district"))
        self.assertNotIn("dossier_decideur", res.tools_executed)

    async def test_bare_rapports_not_captured(self) -> None:
        from app.agent_loop import AgentLoop
        stub = _StubLoopLLM(_FAKE_PNG)
        res = await AgentLoop(stub).chat(_loop_req("Donne-moi les rapports"))
        self.assertNotIn("dossier_decideur", res.tools_executed)


if __name__ == "__main__":
    unittest.main()
