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
        "intent": "list",
        "present": ["territory_overview", "list_maintenance_logs"],
        "absent": ["prepare_incident", "prepare_report", "prepare_maintenance_log"],
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


# ---------------------------------------------------------------------------
# Eval LLM-fidèle + pannes (ajout uniquement — les 10 GOLDEN dégradés et les
# 18 cas de routage ci-dessus restent le filet de non-régression figé).
#
# Ici le stub renvoie un payload LLM VALIDE (catégories dans la liste) : on
# mesure le chemin nominal (passthrough) au lieu du filet mots-clés, plus le
# contrat en cas de panne provider (propagation / défauts sûrs).
# Conventions reprises du fichier : stubs figés sans réseau, meta dict
# out-param de WashExtractor.extract pour distinguer "LLM juste" / "filet".
# ---------------------------------------------------------------------------


class FaithfulLLM:
    """Stub LLM nominal : payload entièrement valide, pas d'appel réseau."""

    model = "stub-faithful-model"

    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_json(self, user_prompt: str, system_prompt: str) -> dict:
        return dict(self.payload)


class RaisingLLM:
    """Stub provider en panne : lève à chaque appel (ex. TimeoutError)."""

    model = "stub-raising-model"

    def __init__(self, exc: BaseException):
        self.exc = exc

    async def generate_json(self, user_prompt: str, system_prompt: str) -> dict:
        raise self.exc


def _faithful_payload(
    infra: str, issue: str, urgency: str, students: int, health: str, summary: str
) -> dict:
    """Payload LLM nominal : catégories valides -> passthrough, filet inactif."""
    return {
        "school_detected": None,
        "infrastructure_type": infra,
        "issue_type": issue,
        "urgency_level": urgency,
        "estimated_affected_students": students,
        "health_hazard_risk": health,
        "short_summary": summary,
    }


class PromptFaithfulEvalTest(unittest.IsolatedAsyncioTestCase):
    """Chemin LLM nominal : le payload valide gagne, sans override keywords."""

    async def _run_faithful(self, text: str, payload: dict) -> tuple:
        meta: dict = {}
        ex = WashExtractor(llm=FaithfulLLM(payload))  # type: ignore[arg-type]
        res = await ex.extract(text, meta=meta)
        return res, meta, ex

    async def test_01_passthrough_sans_mot_cle(self) -> None:
        # Texte SANS aucun mot-clé (le filet devinerait water_point /
        # total_breakdown) : le payload LLM valide doit gagner tel quel.
        text = "Signalement du directeur : la situation empire depuis lundi matin, les classes sont perturbées."
        payload = _faithful_payload("toilets_latrines", "blockage", "high", 120, "high", "Situation préoccupante à l'école.")
        res, meta, _ = await self._run_faithful(text, payload)
        self.assertEqual(res.data.infrastructure_type, "toilets_latrines", "[passthrough] infra")
        self.assertEqual(res.data.issue_type, "blockage", "[passthrough] issue")
        self.assertEqual(res.data.urgency_level, "high", "[passthrough] urgency")
        self.assertEqual(res.data.estimated_affected_students, 120, "[passthrough] affected")
        self.assertEqual(res.model_used, "stub-faithful-model")
        self.assertEqual(meta, {"fallback_infra": False, "fallback_issue": False})

    async def test_02_urgence_invalide_normalisee(self) -> None:
        # Infra/issue valides (passthrough) mais urgence hors liste -> "medium".
        text = "Un souci a été noté près du portail, à surveiller."
        payload = _faithful_payload("water_point", "leak", "super-urgent", 60, "low", "Souci près du portail.")
        res, meta, _ = await self._run_faithful(text, payload)
        self.assertEqual(res.data.infrastructure_type, "water_point", "[urgence] infra")
        self.assertEqual(res.data.issue_type, "leak", "[urgence] issue")
        self.assertEqual(res.data.urgency_level, "medium", "[urgence] normalisée")
        self.assertEqual(meta, {"fallback_infra": False, "fallback_issue": False})

    async def test_03_handwashing_fidele(self) -> None:
        # Catégorie handwashing via payload fidèle (zéro ligne démo).
        text = "Le dispositif près des salles de classe est inutilisable depuis hier."
        payload = _faithful_payload("handwashing", "vandalism", "medium", 200, "low", "Dispositif inutilisable.")
        res, meta, _ = await self._run_faithful(text, payload)
        self.assertEqual(res.data.infrastructure_type, "handwashing", "[handwashing] infra")
        self.assertEqual(res.data.issue_type, "vandalism", "[handwashing] issue")
        self.assertEqual(meta, {"fallback_infra": False, "fallback_issue": False})

    async def test_04_sewage_drainage_fidele(self) -> None:
        # Catégorie sewage_drainage via payload fidèle (zéro ligne démo).
        text = "Une odeur nauséabonde persiste derrière le bâtiment depuis plusieurs jours."
        payload = _faithful_payload("sewage_drainage", "blockage", "high", 150, "high", "Odeurs derrière le bâtiment.")
        res, meta, _ = await self._run_faithful(text, payload)
        self.assertEqual(res.data.infrastructure_type, "sewage_drainage", "[sewage] infra")
        self.assertEqual(res.data.issue_type, "blockage", "[sewage] issue")
        self.assertEqual(meta, {"fallback_infra": False, "fallback_issue": False})

    async def test_05_pidgin_en_fidele(self) -> None:
        # Texte pidgin/EN : "blocked" ne matche aucun mot-clé issue (filet ->
        # total_breakdown) donc blockage prouve la victoire du LLM.
        text = "The school toilet is blocked, wata everywhere, pupils suffer."
        payload = _faithful_payload(
            "toilets_latrines", "blockage", "critical", 300, "severe",
            "Toilettes bloquées, eau partout.",
        )
        res, meta, _ = await self._run_faithful(text, payload)
        self.assertEqual(res.data.infrastructure_type, "toilets_latrines", "[pidgin] infra")
        self.assertEqual(res.data.issue_type, "blockage", "[pidgin] issue")
        self.assertEqual(res.data.urgency_level, "critical", "[pidgin] urgency")
        self.assertEqual(meta, {"fallback_infra": False, "fallback_issue": False})

    async def test_06_meta_degrade_vs_fidele(self) -> None:
        # Même texte : chemin dégradé -> filet True/True ; chemin fidèle ->
        # False/False ; mixte (infra valide + issue "other") -> False/True.
        text = GOLDEN_CASES[1]["text"]  # latrines bouchées (mots-clés FR)
        degraded = WashExtractor(llm=StubLLM(GOLDEN_CASES[1]["payload"]))  # type: ignore[arg-type]
        meta_d: dict = {}
        res_d = await degraded.extract(text, meta=meta_d)
        self.assertEqual(meta_d, {"fallback_infra": True, "fallback_issue": True}, "[meta] dégradé")
        self.assertEqual(degraded.last_meta, meta_d, "[meta] last_meta miroir")
        self.assertEqual(res_d.data.infrastructure_type, "toilets_latrines")

        faithful = WashExtractor(  # type: ignore[arg-type]
            llm=FaithfulLLM(_faithful_payload("water_point", "leak", "low", 50, "low", "Fidèle."))
        )
        meta_f: dict = {}
        res_f = await faithful.extract(text, meta=meta_f)
        self.assertEqual(meta_f, {"fallback_infra": False, "fallback_issue": False}, "[meta] fidèle")
        self.assertEqual(res_f.data.infrastructure_type, "water_point", "[meta] LLM gagne sur filet")

        mixed_payload = _faithful_payload("handwashing", "other", "medium", 50, "low", "Mixte.")
        mixed = WashExtractor(llm=FaithfulLLM(mixed_payload))  # type: ignore[arg-type]
        meta_m: dict = {}
        await mixed.extract(text, meta=meta_m)
        self.assertEqual(meta_m, {"fallback_infra": False, "fallback_issue": True}, "[meta] mixte")


class PromptFailureEvalTest(unittest.IsolatedAsyncioTestCase):
    """Contrat de panne : propagation documentée + défauts sûrs, sans crash."""

    async def test_01_timeout_propage(self) -> None:
        # L'extracteur n'avale rien : le TimeoutError remonte à l'appelant
        # (c'est la couche endpoint / Laravel qui décide du repli).
        ex = WashExtractor(llm=RaisingLLM(TimeoutError("ollama froid")))  # type: ignore[arg-type]
        with self.assertRaises(TimeoutError):
            await ex.extract("La pompe est cassée.")

    async def test_02_payload_vide_defauts_surs(self) -> None:
        # Payload {} -> défauts sûrs, résumé replié sur le texte brut.
        text = "Rien à signaler pour le moment."
        ex = WashExtractor(llm=StubLLM({}))  # type: ignore[arg-type]
        meta: dict = {}
        res = await ex.extract(text, meta=meta)
        self.assertEqual(res.data.infrastructure_type, "water_point", "[vide] infra")
        self.assertEqual(res.data.issue_type, "total_breakdown", "[vide] issue")
        self.assertEqual(res.data.urgency_level, "medium", "[vide] urgency")
        self.assertEqual(res.data.estimated_affected_students, 50, "[vide] affected")
        self.assertEqual(res.data.short_summary, text, "[vide] résumé repli")
        self.assertEqual(meta, {"fallback_infra": True, "fallback_issue": True})
        self.assertGreaterEqual(res.data.recommended_priority_score, 0.0)
        self.assertLessEqual(res.data.recommended_priority_score, 100.0)

    async def test_03_types_bizarres_normalises(self) -> None:
        # Entiers à la place des enums -> normalisés via le filet (texte à
        # mots-clés connus) ; urgence entière -> "medium".
        text = "Les latrines des garçons sont bouchées."
        payload = {
            "school_detected": None,
            "infrastructure_type": 123,
            "issue_type": 456,
            "urgency_level": 789,
            "estimated_affected_students": 100,
            "health_hazard_risk": "high",
            "short_summary": "Résumé forcé.",
        }
        ex = WashExtractor(llm=StubLLM(payload))  # type: ignore[arg-type]
        meta: dict = {}
        res = await ex.extract(text, meta=meta)
        self.assertEqual(res.data.infrastructure_type, "toilets_latrines", "[bizarre] infra filet")
        self.assertEqual(res.data.issue_type, "blockage", "[bizarre] issue filet")
        self.assertEqual(res.data.urgency_level, "medium", "[bizarre] urgency")
        self.assertEqual(res.data.estimated_affected_students, 100, "[bizarre] affected")
        self.assertEqual(meta, {"fallback_infra": True, "fallback_issue": True})


class PromptHonestyEvalTest(unittest.IsolatedAsyncioTestCase):
    """Abstention honnête sur ambigu/hors-sujet/vide : catégories golden
    inchangées (cf. PromptGoldenEvalTest), mais unknowns + next_action
    explicites et confiance < 0.92."""

    async def test_01_ambigu_unknowns(self) -> None:
        case = GOLDEN_CASES[8]  # ambigu
        ex = WashExtractor(llm=StubLLM(case["payload"]))  # type: ignore[arg-type]
        res = await ex.extract(case["text"])
        self.assertLess(res.confidence_score, 0.92, "[ambigu] confiance honnête")
        self.assertTrue(res.unknowns, "[ambigu] unknowns non vides")
        self.assertTrue(res.next_action, "[ambigu] next_action non vide")
        self.assertTrue(res.data.students_unknown, "[ambigu] élèves non confirmés")

    async def test_02_hors_sujet_unknowns(self) -> None:
        case = GOLDEN_CASES[9]  # hors_sujet
        ex = WashExtractor(llm=StubLLM(case["payload"]))  # type: ignore[arg-type]
        res = await ex.extract(case["text"])
        self.assertLess(res.confidence_score, 0.92, "[hors_sujet] confiance honnête")
        self.assertIn("off_topic_suspected", res.unknowns, "[hors_sujet] flag")
        self.assertFalse(res.data.is_wash_related, "[hors_sujet] non-WASH")
        self.assertTrue(res.next_action, "[hors_sujet] next_action non vide")

    async def test_03_empty_unknowns(self) -> None:
        stub = StubLLM(_degraded_payload("medium", None, "low", None))
        ex = WashExtractor(llm=stub)  # type: ignore[arg-type]
        res = await ex.extract("")
        self.assertLess(res.confidence_score, 0.92, "[vide] confiance honnête")
        self.assertIn("empty_report", res.unknowns, "[vide] flag")
        self.assertTrue(res.next_action, "[vide] next_action non vide")
