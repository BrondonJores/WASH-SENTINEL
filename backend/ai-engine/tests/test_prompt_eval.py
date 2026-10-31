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


# ---------------------------------------------------------------------------
# Eval de routage liste/création (ajout uniquement).
#
# Conventions reprises du fichier : cas GOLDEN figés en liste module,
# une classe unittest, messages d'assertion préfixés par l'id du cas.
# Ici le routeur est déterministe (app.agent_loop.route_intent) :
# REGLE D'OR miroir — si un cas échoue, on corrige le CAS (formulation
# documentée), jamais le routeur.
#
# Couverture (18 cas) : interventions passées (plusieurs formulations),
# création (journalise/enregistre/crée), ambiguïtés liste+création,
# questions écoles/incidents existantes (non-régression -> "other").
# ---------------------------------------------------------------------------

from app.agent_loop import route_intent, tools_for_intent  # noqa: E402
from app.agent_tools import AGENT_TOOLS  # noqa: E402


def _exposed_names(intent: str) -> list[str]:
    """Noms des tools exposés pour un intent (via tools_for_intent)."""
    return [t.get("function", {}).get("name", "") for t in tools_for_intent(intent)]


def _tool_description(name: str) -> str:
    for tool in AGENT_TOOLS:
        if tool.get("function", {}).get("name") == name:
            return tool["function"].get("description", "")
    return ""


ROUTING_CASES = [
    # -- Interventions passées -> list (list_maintenance_logs présent) --
    {
        "id": "exact_aujourdhui",
        "question": "donne-moi les interventions réalisées aujourd'hui",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident", "prepare_report", "prepare_maintenance_log"],
    },
    {
        "id": "passees_hier",
        "question": "Quelles interventions ont été réalisées hier ?",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    {
        "id": "passees_semaine",
        "question": "Liste les interventions de la semaine",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    {
        "id": "passees_historique_mois",
        "question": "Montre-moi l'historique des interventions du mois",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    {
        "id": "passees_combien",
        "question": "Combien d'interventions réalisées ce mois-ci ?",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    {
        "id": "passees_travaux_ecole",
        "question": "Affiche les travaux passés à l'école de Ngok",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    {
        "id": "passees_quels_travaux",
        "question": "Quels travaux ont été réalisés hier à Douala ?",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    # -- Création -> create (prepare_* exposés) --
    {
        "id": "cree_intervention",
        "question": "Crée une intervention pour fuite à l'école de Mendong",
        "intent": "create",
        "present": ["prepare_incident"],
        "absent": [],
    },
    {
        "id": "journalise_cout",
        "question": "Journalise une intervention à 50000 XAF pour WASH-001",
        "intent": "create",
        "present": ["prepare_maintenance_log"],
        "absent": [],
    },
    {
        "id": "enregistre_reparation",
        "question": "Enregistre une intervention de réparation de pompe",
        "intent": "create",
        "present": ["prepare_maintenance_log"],
        "absent": [],
    },
    {
        "id": "signale_panne",
        "question": "Signale une panne de forage à Ngok",
        "intent": "create",
        "present": ["prepare_report"],
        "absent": [],
    },
    {
        "id": "ajoute_nouvelle",
        "question": "Ajoute une nouvelle intervention pour latrines bouchées",
        "intent": "create",
        "present": ["prepare_incident"],
        "absent": [],
    },
    # -- Ambiguïtés liste + création -> list (priorité consultation) --
    {
        "id": "ambigu_journalise_realisees",
        "question": "Journalise les interventions réalisées hier",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    {
        "id": "ambigu_liste_prepare",
        "question": "Liste les interventions et prépare une nouvelle fiche",
        "intent": "list",
        "present": ["list_maintenance_logs"],
        "absent": ["prepare_incident"],
    },
    # -- Questions écoles/incidents existantes -> other (non-régression) --
    {
        "id": "noregress_resume_district",
        "question": "Résumer mon district",
        "intent": "other",
        "present": ["list_maintenance_logs", "prepare_incident"],
        "absent": [],
    },
    {
        "id": "noregress_besoin_ecoles",
        "question": "Quelles écoles ont le plus besoin d'aide ?",
        "intent": "other",
        "present": ["list_maintenance_logs", "prepare_incident"],
        "absent": [],
    },
    {
        "id": "noregress_carte",
        "question": "Voir la carte du territoire",
        "intent": "other",
        "present": ["list_maintenance_logs", "prepare_incident"],
        "absent": [],
    },
    {
        "id": "noregress_explique_incident",
        "question": "Explique l'incident WASH-001 en langage simple",
        "intent": "other",
        "present": ["list_maintenance_logs", "prepare_incident"],
        "absent": [],
    },
]


class RoutingEvalTest(unittest.TestCase):
    """Eval routage : intent + tool attendu / tool interdit par question."""

    def test_00_case_count_15_20(self) -> None:
        self.assertGreaterEqual(len(ROUTING_CASES), 15, "au moins 15 cas")
        self.assertLessEqual(len(ROUTING_CASES), 20, "au plus 20 cas")

    def test_01_intents(self) -> None:
        for case in ROUTING_CASES:
            with self.subTest(case["id"]):
                self.assertEqual(
                    route_intent(case["question"]), case["intent"],
                    f"[{case['id']}] intent",
                )

    def test_02_tools_present_absent(self) -> None:
        for case in ROUTING_CASES:
            with self.subTest(case["id"]):
                names = _exposed_names(route_intent(case["question"]))
                for tool in case["present"]:
                    self.assertIn(tool, names, f"[{case['id']}] {tool} exposé")
                for tool in case["absent"]:
                    self.assertNotIn(tool, names, f"[{case['id']}] {tool} masqué")

    def test_03_exact_question_masque_prepare_incident(self) -> None:
        question = "donne-moi les interventions réalisées aujourd'hui"
        self.assertEqual(route_intent(question), "list", "[exact] intent list")
        names = _exposed_names("list")
        self.assertIn("list_maintenance_logs", names, "[exact] list exposé")
        self.assertNotIn("prepare_incident", names, "[exact] prepare_incident masqué")

    def test_04_list_tool_declare(self) -> None:
        names = [t.get("function", {}).get("name", "") for t in AGENT_TOOLS]
        self.assertIn("list_maintenance_logs", names)

    def test_05_prepare_incident_desambigue(self) -> None:
        desc = _tool_description("prepare_incident")
        self.assertIn("JAMAIS", desc, "clause Ne JAMAIS utiliser présente")
        self.assertNotIn("Prépare une intervention directe", desc, "ancien libellé supprimé")
