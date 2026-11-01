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


class FailureTaggingTest(unittest.TestCase):
    """timed() tague les échecs : status/error_type, sans changer le succès."""

    def setUp(self) -> None:
        reset()

    def tearDown(self) -> None:
        reset()

    def test_timed_exception_tagged_error(self) -> None:
        with self.assertRaises(ValueError):
            with timed("extract", model="llama3.2:3b", provider="ollama"):
                raise ValueError("boom")
        out = summary()
        self.assertEqual(out["totals"]["error_count"], 1)
        self.assertAlmostEqual(out["totals"]["error_rate"], 1.0)
        self.assertEqual(out["by_status"], {"ok": 0, "error": 1})
        self.assertEqual(out["by_model"]["llama3.2:3b"]["error_count"], 1)

    def test_mixed_ok_and_error_counts(self) -> None:
        with self.assertRaises(TimeoutError):
            with timed("extract"):
                raise TimeoutError("froid")
        with timed("extract") as ctx:
            ctx["prompt_tokens"] = 10
        out = summary()
        self.assertEqual(out["totals"]["count"], 2)
        self.assertEqual(out["totals"]["error_count"], 1)
        self.assertAlmostEqual(out["totals"]["error_rate"], 0.5)
        self.assertEqual(out["by_status"], {"ok": 1, "error": 1})

    def test_error_type_preserved_on_entry(self) -> None:
        entry = record("extract", 0.2, status="error", model="llama3.2:3b", error_type="TimeoutError")
        self.assertEqual(entry["status"], "error")
        self.assertEqual(entry["error_type"], "TimeoutError")
        self.assertEqual(entry["model"], "llama3.2:3b")
        self.assertEqual(summary()["totals"]["error_count"], 1)

    def test_ctx_overrides_model_and_error_type(self) -> None:
        with self.assertRaises(RuntimeError):
            with timed("extract", model="llama3.2:3b") as ctx:
                ctx["model"] = "gpt-4o-mini"
                ctx["error_type"] = "fallback-rules"
                raise RuntimeError("down")
        out = summary()
        self.assertIn("gpt-4o-mini", out["by_model"])
        self.assertNotIn("llama3.2:3b", out["by_model"])


class ByModelSplitTest(unittest.TestCase):
    def setUp(self) -> None:
        reset()

    def tearDown(self) -> None:
        reset()

    def test_per_model_stats(self) -> None:
        record("extract", 0.1, prompt_tokens=100, completion_tokens=20, model="llama3.2:3b")
        record("extract", 0.3, prompt_tokens=200, completion_tokens=40, model="gpt-4o-mini")
        out = summary()
        local = out["by_model"]["llama3.2:3b"]
        cloud = out["by_model"]["gpt-4o-mini"]
        self.assertEqual(local["count"], 1)
        self.assertAlmostEqual(local["avg_ms"], 100.0, places=2)
        self.assertEqual(local["total_tokens"], 120)
        self.assertEqual(cloud["count"], 1)
        self.assertAlmostEqual(cloud["avg_ms"], 300.0, places=2)
        self.assertEqual(cloud["total_tokens"], 240)
        # Forme historique inchangée.
        self.assertEqual(out["totals"]["count"], 2)
        self.assertEqual(out["totals"]["total_tokens"], 360)
        self.assertEqual(out["by_operation"]["extract"]["count"], 2)

    def test_entries_without_model_skipped(self) -> None:
        record("extract", 0.1)
        out = summary()
        self.assertEqual(out["by_model"], {})
        self.assertEqual(out["totals"]["count"], 1)


class CostTest(unittest.TestCase):
    def setUp(self) -> None:
        reset()

    def tearDown(self) -> None:
        reset()

    def test_priced_model_positive_local_zero(self) -> None:
        priced = record("extract", 0.1, prompt_tokens=800, completion_tokens=200, model="gpt-4o-mini")
        local = record("extract", 0.1, prompt_tokens=800, completion_tokens=200, model="llama3.2:3b")
        self.assertGreater(priced["cost_usd"], 0.0)
        self.assertEqual(local["cost_usd"], 0.0)
        totals = summary()["totals"]
        self.assertAlmostEqual(totals["cost_usd"], priced["cost_usd"], places=6)

    def test_unknown_model_cost_none(self) -> None:
        entry = record("extract", 0.1, prompt_tokens=100, model="modele-inconnu")
        self.assertIsNone(entry["cost_usd"])
        self.assertEqual(summary()["totals"]["cost_usd"], 0.0)

    def test_explicit_cost_and_per_1k_override(self) -> None:
        explicit = record("extract", 0.1, prompt_tokens=1000, model="gpt-4o-mini", cost_usd=0.5)
        self.assertEqual(explicit["cost_usd"], 0.5)
        override = record("extract", 0.1, prompt_tokens=1000, model="modele-inconnu", cost_per_1k=0.2)
        self.assertAlmostEqual(override["cost_usd"], 0.2, places=6)


class BackwardCompatTest(unittest.TestCase):
    def setUp(self) -> None:
        reset()

    def tearDown(self) -> None:
        reset()

    def test_old_style_record_defaults(self) -> None:
        entry = record("extract", 0.1)
        self.assertEqual(entry["status"], "ok")
        self.assertIsNone(entry["model"])
        self.assertIsNone(entry["provider"])
        self.assertIsNone(entry["error_type"])
        self.assertIsNone(entry["cost_usd"])
        # Clés historiques présentes et identiques.
        for key in ("operation", "seconds", "duration_ms", "prompt_tokens", "completion_tokens", "timestamp"):
            self.assertIn(key, entry)

    def test_legacy_summary_keys_intact(self) -> None:
        record("extract", 0.1, prompt_tokens=10, completion_tokens=5)
        out = summary()
        self.assertEqual(set(out["by_operation"]["extract"]), {"count", "avg_ms", "p95_ms"})
        for key in ("count", "avg_ms", "p95_ms", "prompt_tokens", "completion_tokens", "total_tokens"):
            self.assertIn(key, out["totals"])
        # Additions purement additives.
        for key in ("error_count", "error_rate", "cost_usd"):
            self.assertIn(key, out["totals"])
        self.assertIn("by_status", out)
        self.assertIn("by_model", out)


if __name__ == "__main__":
    unittest.main()
