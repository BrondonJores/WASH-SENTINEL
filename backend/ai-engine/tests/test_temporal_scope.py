"""Périmètre temporel : une période demandée = UNIQUEMENT cette période.

Non-régression prod : « Donne-moi les incidents signalés aujourd'hui à
Bonanjo » retournait les 6 incidents ouverts au lieu de ceux du jour (le
modèle confondait demande générale et demande datée). La période est
désormais parsée (déterministe FR/EN, sans LLM), les outils s'exécutent
sur le contexte restreint, les cartes n'affichent que la période (titres
suffixés) et la synthèse dit la période et le compte. Période vide :
message canonique + stock général + proposition, jamais de vide sec.
Sans période : comportement historique inchangé (général = ouverts).

Dates gelées : parse_time_window(message, TODAY) et chat(..., today=TODAY).

Lancer depuis backend/ai-engine : ./.venv/bin/python -m unittest
"""
from __future__ import annotations

import json
import unittest
from datetime import date

from app.agent_loop import (
    EMPTY_PERIOD_FOLLOW_UPS,
    AgentLoop,
    _annotate_period_obs,
    detect_scope,
    parse_time_window,
    time_window_label,
)
from app.agent_tools import (
    filter_incidents_by_window,
    in_time_window,
    open_incidents_in_window,
    scope_context_to_window as scope_ctx,
    tool_summarize_district,
)
from app.schemas import AgentChatRequest, AgentContext

BONANJO = "École Publique de Bonanjo"
NGOK = "École Rurale de Ngok"

#: Mercredi 4 novembre 2026 (dates gelées) : semaine lun. 02 -> mer. 04.
TODAY = date(2026, 11, 4)


def _incident(num: int, reported_at: str | None, school: str = BONANJO,
              school_id: int = 2, district: str = "Wouri",
              status: str = "open", title: str | None = None) -> dict:
    row: dict = {
        "id": num, "school_id": school_id, "school_name": school,
        "district": district, "title": title or f"Panne {num}",
        "urgency": "high", "affected_students": 100, "status": status,
        "reference_code": f"WASH-2026-{num:04d}",
    }
    if reported_at is not None:
        row["reported_at"] = reported_at
    return row


def _ctx_all_old() -> AgentContext:
    """6 ouverts à Bonanjo, tous signalés en octobre (rien le jour J)."""
    return AgentContext(
        schools=[
            {"school_id": 2, "school_name": BONANJO, "district": "Wouri"},
            {"school_id": 1, "school_name": NGOK, "district": "Mvila"},
        ],
        incidents=[
            _incident(num, "2026-10-20T08:00:00+00:00",
                      title=f"Vieille panne {num}")
            for num in range(1, 7)
        ],
    )


def _ctx_two_today() -> AgentContext:
    """2 ouverts du jour + 4 vieux ouverts, tous à Bonanjo."""
    fresh = [
        _incident(1, "2026-11-04T08:00:00+00:00", title="Panne du jour 1"),
        _incident(2, "2026-11-04T09:30:00+00:00", title="Panne du jour 2"),
    ]
    old = [_incident(num, "2026-10-20T08:00:00+00:00",
                     title=f"Vieille panne {num}")
           for num in range(3, 7)]
    return AgentContext(
        schools=[
            {"school_id": 2, "school_name": BONANJO, "district": "Wouri"},
            {"school_id": 1, "school_name": NGOK, "district": "Mvila"},
        ],
        incidents=fresh + old,
    )


def _call(name: str, args: dict | None = None) -> dict:
    return {"raw": {"role": "assistant", "content": ""}, "content": "",
            "tool_calls": [{"id": "1", "name": name, "arguments": args or {}}]}


def _text(content: str) -> dict:
    return {"raw": {"role": "assistant", "content": content},
            "content": content, "tool_calls": []}


class StubLLM:
    """Provider scripté : rejoue les réponses puis répète la dernière."""

    def __init__(self, script: list[dict]):
        self.model = "stub"
        self.script = list(script)

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN202
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def format_tool_result(self, name, result, call_id=None):  # noqa: ANN001, ANN202
        return {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}


class ParseTimeWindowTest(unittest.TestCase):
    def test_today_fr_and_en(self) -> None:
        for message in ("Donne-moi les incidents signalés aujourd'hui à Bonanjo",
                        "Show me the incidents reported today at Bonanjo"):
            with self.subTest(message=message):
                window = parse_time_window(message, TODAY)
                self.assertEqual(window["preset"], "today")
                self.assertEqual(window["start"], TODAY)
                self.assertEqual(window["end"], TODAY)
                self.assertEqual(set(window), {"preset", "start", "end"})

    def test_yesterday_fr_and_en(self) -> None:
        for message in ("Liste les interventions d'hier",
                        "What happened yesterday?"):
            with self.subTest(message=message):
                window = parse_time_window(message, TODAY)
                self.assertEqual(window["preset"], "yesterday")
                self.assertEqual(window["start"], date(2026, 11, 3))
                self.assertEqual(window["end"], date(2026, 11, 3))

    def test_last_7d_fr_and_en(self) -> None:
        for message in ("les 7 derniers jours",
                        "incidents des sept derniers jours",
                        "Show incidents from the last 7 days"):
            with self.subTest(message=message):
                window = parse_time_window(message, TODAY)
                self.assertEqual(window["preset"], "last_7d")
                self.assertEqual(window["start"], date(2026, 10, 29))
                self.assertEqual(window["end"], TODAY)

    def test_this_month_fr_and_en(self) -> None:
        for message in ("Combien d'interventions réalisées ce mois-ci ?",
                        "Show me incidents from this month"):
            with self.subTest(message=message):
                window = parse_time_window(message, TODAY)
                self.assertEqual(window["preset"], "this_month")
                self.assertEqual(window["start"], date(2026, 11, 1))
                self.assertEqual(window["end"], TODAY)

    def test_this_week_since_this_year_and_last_30d(self) -> None:
        window = parse_time_window("incidents de cette semaine", TODAY)
        self.assertEqual(
            (window["preset"], window["start"], window["end"]),
            ("this_week", date(2026, 11, 2), TODAY))
        window = parse_time_window("trends this week", TODAY)
        self.assertEqual(window["preset"], "this_week")
        for message in ("depuis lundi", "since Monday"):
            with self.subTest(message=message):
                window = parse_time_window(message, TODAY)
                self.assertEqual(
                    (window["preset"], window["start"], window["end"]),
                    ("since", date(2026, 11, 2), TODAY))
        window = parse_time_window("depuis le 3 novembre", TODAY)
        self.assertEqual(
            (window["preset"], window["start"], window["end"]),
            ("since", date(2026, 11, 3), TODAY))
        for message in ("bilan de cette année", "this year overview"):
            with self.subTest(message=message):
                window = parse_time_window(message, TODAY)
                self.assertEqual(
                    (window["preset"], window["start"], window["end"]),
                    ("this_year", date(2026, 1, 1), TODAY))
        window = parse_time_window("les 30 derniers jours", TODAY)
        self.assertEqual(
            (window["preset"], window["start"], window["end"]),
            ("last_30d", date(2026, 10, 6), TODAY))

    def test_no_period_returns_none(self) -> None:
        for message in ("Donne-moi les incidents à Bonanjo",
                        "Bonjour",
                        "Compare les tendances de Ngok sur 6 mois",
                        "",
                        "avant-hier",
                        "le 15 du mois"):
            with self.subTest(message=message):
                self.assertEqual(
                    parse_time_window(message, TODAY),
                    {"preset": None, "start": None, "end": None})

    def test_labels_fr_and_en(self) -> None:
        self.assertEqual(
            time_window_label(parse_time_window("aujourd'hui", TODAY), "fr"),
            "aujourd'hui")
        self.assertEqual(
            time_window_label(parse_time_window("today", TODAY), "en"),
            "today")
        self.assertEqual(
            time_window_label(parse_time_window("hier", TODAY), "fr"), "hier")
        self.assertEqual(time_window_label(None), "")
        self.assertEqual(
            time_window_label({"preset": None, "start": None, "end": None}), "")


class WindowFilterTest(unittest.TestCase):
    def test_inclusive_bounds_compare_dates_not_datetimes(self) -> None:
        start = end = TODAY
        self.assertTrue(in_time_window(TODAY, start, end))
        self.assertFalse(in_time_window(date(2026, 11, 3), start, end))
        self.assertFalse(in_time_window(date(2026, 11, 5), start, end))
        self.assertFalse(in_time_window(None, start, end))
        rows = [
            _incident(1, "2026-11-04T00:00:00+00:00"),
            _incident(2, "2026-11-04T23:59:59+00:00"),
            _incident(3, "2026-11-03T23:59:59+00:00"),
            _incident(4, "2026-11-05T00:00:00+00:00"),
            _incident(5, None),
        ]
        kept = filter_incidents_by_window(rows, start, end)
        self.assertEqual([r["id"] for r in kept], [1, 2])

    def test_yesterday_excludes_today_and_closed(self) -> None:
        ctx = AgentContext(
            schools=[{"school_id": 2, "school_name": BONANJO}],
            incidents=[
                _incident(1, "2026-11-04T08:00:00+00:00"),
                _incident(2, "2026-11-03T12:00:00+00:00"),
                _incident(3, "2026-11-03T15:00:00+00:00", status="closed"),
            ],
        ).model_dump()
        yesterday = parse_time_window("hier", TODAY)
        kept = open_incidents_in_window(ctx, yesterday)
        self.assertEqual([r["id"] for r in kept], [2])
        today = parse_time_window("aujourd'hui", TODAY)
        kept = open_incidents_in_window(ctx, today)
        self.assertEqual([r["id"] for r in kept], [1])

    def test_scope_context_filters_incidents_and_logs(self) -> None:
        ctx = {
            "schools": [{"school_id": 2, "school_name": BONANJO}],
            "incidents": [
                _incident(1, "2026-11-04T08:00:00+00:00"),
                _incident(2, "2026-10-01T08:00:00+00:00"),
                _incident(3, None),
            ],
            "recent_incidents": [
                _incident(4, "2026-11-04T10:00:00+00:00"),
                _incident(5, "2026-09-01T08:00:00+00:00"),
            ],
            "maintenance_logs": [
                {"id": 1, "repaired_at": "2026-11-04T11:00:00+00:00"},
                {"id": 2, "created_at": "2026-11-04T11:00:00+00:00"},
                {"id": 3, "repaired_at": "2026-10-01T11:00:00+00:00"},
                {"id": 4},
            ],
        }
        scoped = scope_ctx(ctx, parse_time_window("aujourd'hui", TODAY))
        self.assertIsNot(scoped, ctx)
        self.assertEqual([r["id"] for r in scoped["incidents"]], [1])
        self.assertEqual([r["id"] for r in scoped["recent_incidents"]], [4])
        self.assertEqual([r["id"] for r in scoped["maintenance_logs"]], [1, 2])
        # Sans période : contexte inchangé (même objet).
        for window in (None, {"preset": None, "start": None, "end": None},
                       {"preset": "today", "start": None, "end": None}):
            with self.subTest(window=window):
                self.assertIs(scope_ctx(ctx, window), ctx)


class TemporalChatTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_period_canonical_message_and_chip(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("analyze_school", {"school": "Bonanjo"}),
            _text("Voici les 6 incidents ouverts de Bonanjo."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="Donne-moi les incidents signalés aujourd'hui à Bonanjo",
            context=_ctx_all_old()), today=TODAY)
        # Jamais de liste générale déguisée : le message canonique remplace.
        self.assertEqual(
            res.answer,
            "Aucun incident signalé aujourd'hui à Bonanjo. "
            "(6 ouverts au total.)")
        self.assertNotIn("Vieille", res.answer)
        self.assertEqual(res.follow_ups, ["Voir les ouverts ?"])
        self.assertIn("analyze_school", res.tools_executed)
        self.assertEqual(len(res.cards), 1)
        self.assertTrue(res.cards[0].title.endswith("(aujourd'hui)"),
                        res.cards[0].title)
        self.assertEqual(res.cards[0].data["open_incidents"], [])

    async def test_no_period_unchanged(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("analyze_school", {"school": "Bonanjo"}),
            _text("6 incidents ouverts à Bonanjo."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="Donne-moi les incidents à Bonanjo",
            context=_ctx_all_old()), today=TODAY)
        self.assertEqual(res.answer, "6 incidents ouverts à Bonanjo.")
        self.assertEqual(res.follow_ups, [])
        self.assertEqual(len(res.cards), 1)
        self.assertNotIn("(aujourd", res.cards[0].title)
        self.assertEqual(len(res.cards[0].data["open_incidents"]), 6)
        self.assertNotIn("time_window", res.cards[0].data)

    async def test_period_cards_show_only_period(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("analyze_school", {"school": "Bonanjo"}),
            _text("2 incidents signalés aujourd'hui à Bonanjo."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="Donne-moi les incidents signalés aujourd'hui à Bonanjo",
            context=_ctx_two_today()), today=TODAY)
        self.assertEqual(
            res.answer, "2 incidents signalés aujourd'hui à Bonanjo.")
        self.assertEqual(res.follow_ups, [])
        self.assertEqual(len(res.cards), 1)
        self.assertTrue(res.cards[0].title.endswith("(aujourd'hui)"),
                        res.cards[0].title)
        titles = [i["title"] for i in res.cards[0].data["open_incidents"]]
        self.assertEqual(titles, ["Panne du jour 1", "Panne du jour 2"])

    async def test_english_today_empty(self) -> None:
        loop = AgentLoop(StubLLM([
            _call("analyze_school", {"school": "Bonanjo"}),
            _text("Here are the open incidents."),
        ]))
        res = await loop.chat(AgentChatRequest(
            message="Show me the incidents reported today at Bonanjo",
            context=_ctx_all_old()), today=TODAY)
        self.assertEqual(
            res.answer,
            "No incidents reported today at Bonanjo. (6 open in total.)")
        self.assertEqual(res.follow_ups, [EMPTY_PERIOD_FOLLOW_UPS["en"]])


class TemporalSummaryTest(unittest.TestCase):
    def _annotated_district_obs(self, today_count: int) -> dict:
        ctx = (_ctx_two_today() if today_count else _ctx_all_old()).model_dump()
        window = parse_time_window("incidents signalés aujourd'hui", TODAY)
        obs = tool_summarize_district({}, scope_ctx(ctx, window))
        _annotate_period_obs("summarize_district", obs, window,
                             6, " à Bonanjo")
        return obs

    def test_fallback_says_period_and_count(self) -> None:
        loop = AgentLoop(StubLLM([_text("ok")]))
        ctx = _ctx_two_today().model_dump()
        scope = detect_scope("incidents à Bonanjo", ctx)
        text = loop._fallback_answer(
            [("summarize_district", self._annotated_district_obs(2))],
            ctx, scope=scope)
        self.assertIn("2 incidents signalés aujourd'hui à Bonanjo", text)
        self.assertIn("(6 ouverts au total.)", text)
        self.assertIn("carte", text)

    def test_fallback_empty_period(self) -> None:
        loop = AgentLoop(StubLLM([_text("ok")]))
        ctx = _ctx_all_old().model_dump()
        scope = detect_scope("incidents à Bonanjo", ctx)
        text = loop._fallback_answer(
            [("summarize_district", self._annotated_district_obs(0))],
            ctx, scope=scope)
        self.assertEqual(
            text,
            "Aucun incident signalé aujourd'hui à Bonanjo. "
            "(6 ouverts au total.)")

    def test_prompt_rule_mentions_period(self) -> None:
        from app.agent_loop import SYSTEM_PROMPT
        self.assertIn("période", SYSTEM_PROMPT)
        self.assertIn("filter strictly", SYSTEM_PROMPT)
        self.assertIn("general stock", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
