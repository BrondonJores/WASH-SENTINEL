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


if __name__ == "__main__":
    unittest.main()
