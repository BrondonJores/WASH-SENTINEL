"""Eval des prompts d'extraction — 10 cas GOLDEN (filet de regression).

Protocole (jury) :
- LLM MOCKE au niveau provider (pattern ``StubLLM`` de tests/test_extractor.py).
- Degrade volontaire : le stub renvoie ``"other"`` pour infrastructure/issue,
  ce qui exerce le filet a mots-cles du code ACTUEL (``_guess_*``) sur des
  phrases FR realistes de terrain. Urgence / nb eleves / resume passent par
  le payload mocke (contrat extracteur).
- REGLE D'OR : ces goldens passent avec le code actuel. Si un cas echoue,
  on corrige le CAS (documente), jamais l'extracteur.

Couverture : fuite, latrines bouchees, forage a sec, eau jaune, pompe cassee,
vandalisme, 2 cas avec nombres d'eleves, 1 cas ambigu, 1 cas hors-sujet
(+ 1 bonus chaine vide, hors compteur des 10).
"""

from __future__ import annotations

import unittest

from app.extractor import WashExtractor


class StubLLM:
    """Meme pattern que tests/test_extractor.py : payload fige, pas d'appel reseau."""

    model = "stub-eval-model"

    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_json(self, user_prompt: str, system_prompt: str) -> dict:
        return dict(self.payload)


def _degraded_payload(urgency: str, students, health: str, summary: str | None) -> dict:
    """Payload LLM degrade : categories invalides -> repli keywords sur le texte brut."""
    return {
        "school_detected": None,
        "infrastructure_type": "other",  # invalide -> _guess_infrastructure(raw_text)
        "issue_type": "other",  # invalide -> _guess_issue(raw_text)
        "urgency_level": urgency,
        "estimated_affected_students": students,
        "health_hazard_risk": health,
        "short_summary": summary,
    }


GOLDEN_CASES = [
    {
        "id": "fuite",
        "text": "Il y a une fuite d'eau sur le tuyau principal près du robinet de la cour.",
        "payload": _degraded_payload("medium", 50, "medium", "Fuite d'eau sur le tuyau principal."),
        "expected": ("water_point", "leak", "medium", 50),
    },
    {
        "id": "latrines_bouchees",
        "text": "Les latrines des filles sont bouchées et débordent depuis ce matin.",
        "payload": _degraded_payload("critical", 50, "severe", "Latrines des filles bouchées et débordantes."),
        "expected": ("toilets_latrines", "blockage", "critical", 50),
    },
    {
        "id": "forage_a_sec",
        "text": "Le forage de l'école est à sec, plus d'eau depuis trois jours.",
        "payload": _degraded_payload("critical", 50, "high", "Forage à sec, école sans eau depuis trois jours."),
        "expected": ("water_point", "dry_well", "critical", 50),
    },
    {
        "id": "eau_jaune",
        "text": "Le robinet donne une eau jaune et trouble que les enfants boivent.",
        "payload": _degraded_payload("high", 50, "severe", "Eau jaune et trouble bue par les enfants."),
        "expected": ("water_point", "contamination", "high", 50),
    },
    {
        "id": "pompe_cassee",
        "text": "La pompe manuelle est cassée, elle ne fonctionne plus depuis lundi.",
        "payload": _degraded_payload("high", 50, "medium", "Pompe manuelle cassée depuis lundi."),
        "expected": ("water_point", "total_breakdown", "high", 50),
    },
    {
        "id": "eleves_450_fuite",
        "text": "La fuite du château d'eau prive 450 élèves d'eau potable.",
        # Le nombre d'eleves est extrait par le LLM (pas parse du texte par
        # l'extracteur) : le stub le porte, l'eval verifie le passthrough.
        "payload": _degraded_payload("high", 450, "medium", "Fuite du château d'eau, 450 élèves privés d'eau."),
        "expected": ("water_point", "leak", "high", 450),
    },
    {
        "id": "eleves_320_eau_sale",
        "text": "Les 320 élèves de l'école boivent une eau sale et contaminée.",
        "payload": _degraded_payload("critical", 320, "severe", "320 élèves boivent une eau contaminée."),
        "expected": ("water_point", "contamination", "critical", 320),
    },
    {
        "id": "vandalisme_robinets",
        "text": "Les robinets du point d'eau ont été volés pendant la nuit.",
        "payload": _degraded_payload("medium", 50, "low", "Robinet du point d'eau volé."),
        "expected": ("water_point", "vandalism", "medium", 50),
    },
    {
        "id": "ambigu",
        # Cas ambigu documente : aucun mot-cle -> defauts surs water_point /
        # total_breakdown ; urgence invalide -> normalisee a "medium" ;
        # 0 eleves -> defaut 50 (comportement actuel de l'extracteur).
        "text": "Il y a un problème d'eau à l'école, on ne sait pas trop.",
        "payload": _degraded_payload("unknown-value", 0, "medium", "Problème d'eau non précisé."),
        "expected": ("water_point", "total_breakdown", "medium", 50),
    },
    {
        "id": "hors_sujet",
        # Hors-sujet documente : l'extracteur actuel ne refuse jamais
        # (pas de detection hors-sujet, "other" interdit) -> defauts, sans crash.
        # short_summary=None -> repli sur raw_text[:120].
        "text": "Le match de football inter-écoles aura lieu samedi au stade.",
        "payload": _degraded_payload("medium", None, "low", None),
        "expected": ("water_point", "total_breakdown", "medium", 50),
    },
]


class PromptGoldenEvalTest(unittest.IsolatedAsyncioTestCase):
    """Les 10 cas golden : category (infra + issue) / urgency / affected."""

    async def _run_case(self, case: dict) -> None:
        ex = WashExtractor(llm=StubLLM(case["payload"]))  # type: ignore[arg-type]
        res = await ex.extract(case["text"])
        infra, issue, urgency, affected = case["expected"]
        self.assertEqual(res.data.infrastructure_type, infra, f"[{case['id']}] infra")
        self.assertEqual(res.data.issue_type, issue, f"[{case['id']}] issue")
        self.assertEqual(res.data.urgency_level, urgency, f"[{case['id']}] urgency")
        self.assertEqual(res.data.estimated_affected_students, affected, f"[{case['id']}] affected")
        self.assertGreaterEqual(res.data.recommended_priority_score, 0.0)
        self.assertLessEqual(res.data.recommended_priority_score, 100.0)
        self.assertEqual(res.model_used, "stub-eval-model")

    async def test_01_fuite(self) -> None:
        await self._run_case(GOLDEN_CASES[0])

    async def test_02_latrines_bouchees(self) -> None:
        await self._run_case(GOLDEN_CASES[1])

    async def test_03_forage_a_sec(self) -> None:
        await self._run_case(GOLDEN_CASES[2])

    async def test_04_eau_jaune(self) -> None:
        await self._run_case(GOLDEN_CASES[3])

    async def test_05_pompe_cassee(self) -> None:
        await self._run_case(GOLDEN_CASES[4])

    async def test_06_eleves_450_fuite(self) -> None:
        await self._run_case(GOLDEN_CASES[5])

    async def test_07_eleves_320_eau_sale(self) -> None:
        await self._run_case(GOLDEN_CASES[6])

    async def test_08_vandalisme_robinets(self) -> None:
        await self._run_case(GOLDEN_CASES[7])

    async def test_09_ambigu_defaults_surs(self) -> None:
        await self._run_case(GOLDEN_CASES[8])

    async def test_10_hors_sujet_defaults_sans_crash(self) -> None:
        await self._run_case(GOLDEN_CASES[9])
        # Bonus doc : le resume replie sur le texte brut.
        ex = WashExtractor(llm=StubLLM(GOLDEN_CASES[9]["payload"]))  # type: ignore[arg-type]
        res = await ex.extract(GOLDEN_CASES[9]["text"])
        self.assertEqual(res.data.short_summary, GOLDEN_CASES[9]["text"])


class PromptEdgeBonusTest(unittest.IsolatedAsyncioTestCase):
    """Bonus hors compteur : chaine vide -> defauts, sans exception."""

    async def test_empty_string_defaults(self) -> None:
        stub = StubLLM(_degraded_payload("medium", None, "low", None))
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        res = await ex.extract("")
        self.assertEqual(res.data.infrastructure_type, "water_point")
        self.assertEqual(res.data.issue_type, "total_breakdown")
        self.assertEqual(res.data.urgency_level, "medium")
        self.assertEqual(res.data.estimated_affected_students, 50)
        self.assertEqual(res.data.short_summary, "")


if __name__ == "__main__":
    unittest.main()
