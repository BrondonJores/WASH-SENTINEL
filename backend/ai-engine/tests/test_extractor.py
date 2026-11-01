from __future__ import annotations

import unittest

from app.extractor import WASH_SYSTEM_PROMPT, WashExtractor


class StubLLM:
    model = "stub-model"

    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_json(self, user_prompt: str, system_prompt: str) -> dict:
        return dict(self.payload)


class NoOtherCategoryTest(unittest.TestCase):
    def test_prompt_forbids_other(self) -> None:
        self.assertNotIn("| other", WASH_SYSTEM_PROMPT)
        self.assertIn("INTERDIT", WASH_SYSTEM_PROMPT)


class KeywordFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ex = WashExtractor(llm=None)  # type: ignore[arg-type]

    def test_latrines_guessed(self) -> None:
        text = "Les latrines des filles sont bouchées et débordent."
        self.assertEqual(self.ex._guess_infrastructure(text), "toilets_latrines")
        self.assertEqual(self.ex._guess_issue(text), "blockage")

    def test_broken_pump_guessed(self) -> None:
        text = "La pompe principale est cassée, plus d'eau depuis hier."
        self.assertEqual(self.ex._guess_infrastructure(text), "water_point")
        self.assertEqual(self.ex._guess_issue(text), "dry_well")

    def test_negation_is_not_a_leak(self) -> None:
        self.assertEqual(self.ex._guess_issue("L'eau ne coule plus au robinet."), "total_breakdown")

    def test_classroom_is_not_contamination(self) -> None:
        self.assertEqual(self.ex._guess_issue("Fuite près de la salle de classe."), "leak")


class OtherNeverStoredTest(unittest.IsolatedAsyncioTestCase):
    async def test_other_answers_become_real_categories(self) -> None:
        stub = StubLLM({
            "school_detected": None,
            "infrastructure_type": "other",
            "issue_type": "other",
            "urgency_level": "medium",
            "estimated_affected_students": 0,
            "health_hazard_risk": "low",
            "short_summary": "Latrines bouchées.",
        })
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        res = await ex.extract("Les latrines des filles sont bouchées et débordent.")
        self.assertEqual(res.data.infrastructure_type, "toilets_latrines")
        self.assertEqual(res.data.issue_type, "blockage")


class LocalKeywordsTest(unittest.TestCase):
    """Filet langues locales (conservateur) + non-régression du filet FR."""

    def setUp(self) -> None:
        self.ex = WashExtractor(llm=None)  # type: ignore[arg-type]

    def test_pidgin_wata_spoil_is_water_point(self) -> None:
        self.assertEqual(
            self.ex._guess_infrastructure("Wata don spoil for school pump."),
            "water_point",
        )

    def test_douala_madiba_leak_is_water_point(self) -> None:
        text = "Fuite autour du point madiba, l'eau coule depuis hier."
        self.assertEqual(self.ex._guess_infrastructure(text), "water_point")
        self.assertEqual(self.ex._guess_issue(text), "leak")

    def test_pidgin_toilet_is_latrines(self) -> None:
        self.assertEqual(
            self.ex._guess_infrastructure("The school toilet is blocked."),
            "toilets_latrines",
        )

    def test_french_net_unchanged(self) -> None:
        self.assertEqual(self.ex._guess_issue("L'eau ne coule plus au robinet."), "total_breakdown")
        self.assertEqual(
            self.ex._guess_infrastructure("Les latrines des filles sont bouchées et débordent."),
            "toilets_latrines",
        )

    def test_french_wins_over_local(self) -> None:
        self.assertEqual(
            self.ex._guess_infrastructure("Les toilettes sont bouchées, wata partout dans la cour."),
            "toilets_latrines",
        )


class HonestConfidenceTest(unittest.IsolatedAsyncioTestCase):
    """Confiance calculée + unknowns : jamais 0.92 par défaut."""

    async def test_llm_valid_high_confidence_no_unknowns(self) -> None:
        stub = StubLLM({
            "school_detected": "EPP Centre",
            "infrastructure_type": "water_point",
            "issue_type": "leak",
            "urgency_level": "high",
            "estimated_affected_students": 320,
            "health_hazard_risk": "high",
            "short_summary": "Fuite franche au point d'eau.",
        })
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        res = await ex.extract("Fuite au point d'eau.", school_name="EPP Centre")
        self.assertGreaterEqual(res.confidence_score, 0.85)
        self.assertNotEqual(res.confidence_score, 0.92)
        self.assertEqual(res.unknowns, [])
        self.assertEqual(res.next_action, "")
        self.assertEqual(res.field_provenance["infrastructure_type"], "llm")
        self.assertFalse(res.data.students_unknown)

    async def test_keyword_fallback_lower_confidence_with_unknowns(self) -> None:
        stub = StubLLM({
            "school_detected": None,
            "infrastructure_type": "other",
            "issue_type": "other",
            "urgency_level": "medium",
            "estimated_affected_students": 0,
            "health_hazard_risk": "low",
            "short_summary": "Latrines bouchées.",
        })
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        res = await ex.extract("Les latrines des filles sont bouchées et débordent.")
        self.assertEqual(res.data.infrastructure_type, "toilets_latrines")
        self.assertEqual(res.data.issue_type, "blockage")
        self.assertLess(res.confidence_score, 0.92)
        self.assertIn("infrastructure_guess", res.unknowns)
        self.assertIn("issue_guess", res.unknowns)
        self.assertIn("affected_students_unknown", res.unknowns)
        self.assertTrue(res.next_action)
        self.assertEqual(res.field_provenance["infrastructure_type"], "keyword")
        self.assertTrue(res.data.students_unknown)

    async def test_empty_report_explicit_unknowns(self) -> None:
        stub = StubLLM({
            "school_detected": None,
            "infrastructure_type": "other",
            "issue_type": "other",
            "urgency_level": "medium",
            "estimated_affected_students": None,
            "health_hazard_risk": "low",
            "short_summary": None,
        })
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        res = await ex.extract("   ")
        self.assertIn("empty_report", res.unknowns)
        self.assertTrue(res.next_action)
        self.assertLess(res.confidence_score, 0.92)
        self.assertIsNone(res.data.is_wash_related)

    async def test_off_topic_suspected_not_silent(self) -> None:
        stub = StubLLM({
            "school_detected": None,
            "infrastructure_type": "other",
            "issue_type": "other",
            "urgency_level": "medium",
            "estimated_affected_students": None,
            "health_hazard_risk": "low",
            "short_summary": None,
        })
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        res = await ex.extract("Le match de football inter-écoles aura lieu samedi au stade.")
        self.assertIn("off_topic_suspected", res.unknowns)
        self.assertFalse(res.data.is_wash_related)
        self.assertTrue(res.next_action)
        self.assertLess(res.confidence_score, 0.92)


if __name__ == "__main__":
    unittest.main()


class NegationBatteryTest(unittest.TestCase):
    """AXE 3 : négation scopée + accents + gazetteer (filet à mots-clés)."""

    def setUp(self) -> None:
        self.ex = WashExtractor(llm=None)  # type: ignore[arg-type]

    def test_positive_control_is_contamination(self) -> None:
        self.assertEqual(
            self.ex._guess_issue("Diarrhée dans trois classes ce matin."),
            "contamination")

    def test_negated_symptom_is_not_contamination(self) -> None:
        self.assertEqual(
            self.ex._guess_issue("Pas de diarrhée signalée cette semaine."),
            "total_breakdown")
        self.assertEqual(
            self.ex._guess_issue("L'eau n'est pas jaune au forage."),
            "total_breakdown")
        self.assertEqual(
            self.ex._guess_issue("Aucun vomissement à la cantine."),
            "total_breakdown")
        self.assertEqual(
            self.ex._guess_issue("No cholera in the school yard."),
            "total_breakdown")

    def test_absence_stays_dry_well(self) -> None:
        self.assertEqual(
            self.ex._guess_issue("Pas d'eau au robinet depuis lundi."),
            "dry_well")

    def test_accent_fold_uppercase(self) -> None:
        self.assertEqual(
            self.ex._guess_infrastructure("ÉVACUATION bouchée derrière les classes."),
            "sewage_drainage")

    def test_gazetteer_validated_and_unvalidated(self) -> None:
        self.assertEqual(
            self.ex._guess_infrastructure("Dirty wata stand for yard."),
            "water_point")
        self.assertTrue(self.ex._local_unvalidated_hit("Borehole don spoil."))
        self.assertFalse(
            self.ex._local_unvalidated_hit("Wata don spoil for pump."))

    def test_dual_form_causal_compound(self) -> None:
        self.assertEqual(
            self.ex._guess_issue("La pompe est cassée donc l'eau ne coule plus."),
            "total_breakdown")


class GazetteerExtractTest(unittest.IsolatedAsyncioTestCase):
    """Niveau non validé -> unknowns traçables via extract()."""

    async def test_unvalidated_local_hits_unknowns(self) -> None:
        stub = StubLLM({
            "school_detected": None,
            "infrastructure_type": "other",
            "issue_type": "other",
            "urgency_level": "medium",
            "estimated_affected_students": 0,
            "health_hazard_risk": "low",
            "short_summary": "Borehole broken.",
        })
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        # "borehole" seul : niveau non validé, aucun token validé (wata...).
        res = await ex.extract("The borehole is broken, no spare parts.")
        self.assertEqual(res.data.infrastructure_type, "water_point")
        self.assertIn("local_language_unvalidated", res.unknowns)
        self.assertTrue(res.next_action)
