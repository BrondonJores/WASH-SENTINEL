"""Tests du module d'observabilite IA (app/ai_metrics.py)."""

from __future__ import annotations

import time
import unittest

from app.ai_metrics import MAX_ENTRIES, record, reset, summary, timed


class RecordSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        reset()

    def tearDown(self) -> None:
        reset()

    def test_summary_fixed_data_single_operation(self) -> None:
        # 100 durees : 10ms, 20ms, ..., 1000ms
        for i in range(1, 101):
            record("extract", i / 100.0)
        out = summary()
        op = out["by_operation"]["extract"]
        self.assertEqual(op["count"], 100)
        self.assertAlmostEqual(op["avg_ms"], 505.0, places=2)
        # p95 nearest-rank : ceil(0.95*100) = 95e valeur = 950ms
        self.assertAlmostEqual(op["p95_ms"], 950.0, places=2)
        self.assertEqual(out["totals"]["count"], 100)
        self.assertAlmostEqual(out["totals"]["avg_ms"], 505.0, places=2)
        self.assertAlmostEqual(out["totals"]["p95_ms"], 950.0, places=2)

    def test_summary_multiple_operations(self) -> None:
        record("extract", 0.1)
        record("extract", 0.3)
        record("vision", 1.0)
        out = summary()
        self.assertEqual(set(out["by_operation"]), {"extract", "vision"})
        self.assertEqual(out["by_operation"]["extract"]["count"], 2)
        self.assertAlmostEqual(out["by_operation"]["extract"]["avg_ms"], 200.0, places=2)
        self.assertEqual(out["by_operation"]["vision"]["count"], 1)
        self.assertEqual(out["totals"]["count"], 3)

    def test_tokens_none_safe(self) -> None:
        record("extract", 0.1)  # sans tokens
        record("extract", 0.2, prompt_tokens=100, completion_tokens=40)
        record("extract", 0.3, prompt_tokens=None, completion_tokens=None)
        totals = summary()["totals"]
        self.assertEqual(totals["prompt_tokens"], 100)
        self.assertEqual(totals["completion_tokens"], 40)
        self.assertEqual(totals["total_tokens"], 140)

    def test_p95_small_sample(self) -> None:
        # 20 durees : 10ms..200ms -> p95 = ceil(19) = 19e = 190ms
        for i in range(1, 21):
            record("extract", i / 100.0)
        op = summary()["by_operation"]["extract"]
        self.assertAlmostEqual(op["p95_ms"], 190.0, places=2)

    def test_empty_summary(self) -> None:
        out = summary()
        self.assertEqual(out["by_operation"], {})
        self.assertEqual(out["totals"]["count"], 0)
        self.assertEqual(out["totals"]["avg_ms"], 0.0)
        self.assertEqual(out["totals"]["p95_ms"], 0.0)
        self.assertEqual(out["totals"]["total_tokens"], 0)


class BoundedBufferTest(unittest.TestCase):
    def setUp(self) -> None:
        reset()

    def tearDown(self) -> None:
        reset()

    def test_buffer_keeps_last_500(self) -> None:
        self.assertEqual(MAX_ENTRIES, 500)
        for i in range(600):
            record("extract", float(i))  # 0s, 1s, ..., 599s
        out = summary()
        self.assertEqual(out["totals"]["count"], 500)
        self.assertEqual(out["by_operation"]["extract"]["count"], 500)
        # Les 500 gardees sont 100..599 : moyenne = (100+599)/2 s = 349500 ms.
        # Prouve que ce sont les PLUS RECENTES qui sont gardees, pas les premieres.
        self.assertAlmostEqual(
            out["by_operation"]["extract"]["avg_ms"], 349500.0, places=1
        )


class ResetTest(unittest.TestCase):
    def test_reset_empties(self) -> None:
        record("extract", 0.5, prompt_tokens=10, completion_tokens=5)
        reset()
        out = summary()
        self.assertEqual(out["by_operation"], {})
        self.assertEqual(out["totals"]["count"], 0)
        self.assertEqual(out["totals"]["total_tokens"], 0)


class TimedTest(unittest.TestCase):
    def setUp(self) -> None:
        reset()

    def tearDown(self) -> None:
        reset()

    def test_timed_measures_positive_duration(self) -> None:
        with timed("extract"):
            time.sleep(0.01)
        op = summary()["by_operation"]["extract"]
        self.assertEqual(op["count"], 1)
        self.assertGreater(op["avg_ms"], 0.0)

    def test_timed_attaches_tokens_via_context(self) -> None:
        with timed("extract") as ctx:
            ctx["prompt_tokens"] = 50
            ctx["completion_tokens"] = 20
        totals = summary()["totals"]
        self.assertEqual(totals["prompt_tokens"], 50)
        self.assertEqual(totals["completion_tokens"], 20)

    def test_timed_records_even_on_exception(self) -> None:
        with self.assertRaises(ValueError):
            with timed("extract"):
                raise ValueError("boom")
        self.assertEqual(summary()["totals"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
