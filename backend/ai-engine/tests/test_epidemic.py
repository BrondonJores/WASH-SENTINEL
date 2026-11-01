"""Validation du détecteur d'alerte épidémique sur fixtures réalistes.

ATTENTION : ces fixtures sont synthétiques et n'ont jamais été confrontées
à de vraies données terrain. Elles règlent les seuils, elles ne prouvent
pas une performance épidémiologique réelle.

Couverture : cluster franc -> outbreak_warning ; bruit de fond -> normal ;
cas limite -> moderate au plus ; filtre multi-districts ; fenêtre expirée.
Le LLM est toujours mocké (FakeLLM) : aucun appel Ollama réel.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.epidemic_detector import DEFAULT_HEALTH_ACTIONS, EpidemicDetector
from app.schemas import DistrictIncidentRecord, EpidemicClusterRequest


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


class FakeLLM:
    """LLM mocké : charge contrôlée, panne simulable, appels comptés."""

    model = "fake-epidemic-model"

    def __init__(self, payload: dict | None = None, exc: Exception | None = None):
        self.payload = payload or {}
        self.exc = exc
        self.calls = 0

    async def generate_json(self, prompt: str, system: str = "") -> dict:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return dict(self.payload)


def make_inc(
    i: int,
    school: str,
    district: str,
    category: str,
    summary: str,
    age_days: int,
) -> DistrictIncidentRecord:
    return DistrictIncidentRecord(
        id=i,
        school_name=school,
        district=district,
        category=category,
        summary=summary,
        reported_at=days_ago(age_days),
    )


DISTRICT = "District-Centre"


def fixture_cluster_franc() -> EpidemicClusterRequest:
    """(a) 3 écoles du même district, eau jaune + diarrhées, 7 jours."""
    return EpidemicClusterRequest(
        district=DISTRICT,
        recent_incidents=[
            make_inc(
                1, "École Publique Centre A", DISTRICT, "contamination",
                "L'eau du forage est jaune et trouble, six élèves ont eu "
                "la diarrhée cette semaine.", 1,
            ),
            make_inc(
                2, "École Publique Centre B", DISTRICT, "contamination",
                "Plusieurs cas de diarrhée et de vomissements après avoir "
                "bu l'eau du puits de l'école.", 3,
            ),
            make_inc(
                3, "Collège Espoir", DISTRICT, "latrines",
                "Eau jaunâtre au robinet et latrines qui débordent près du "
                "point d'eau.", 7,  # borne incluse de la fenêtre
            ),
        ],
    )


def fixture_bruit_de_fond() -> EpidemicClusterRequest:
    """(b) 2 pannes mécaniques isolées, dans deux autres districts."""
    return EpidemicClusterRequest(
        district=DISTRICT,
        recent_incidents=[
            make_inc(
                11, "École du Marché", "District-Nord", "panne_mecanique",
                "Pompe manuelle bloquée, le levier est cassé, aucune eau ne sort.", 1,
            ),
            make_inc(
                12, "École de la Gare", "District-Sud", "panne_mecanique",
                "Fuite sur le tuyau principal, le réparateur communal est prévenu.", 2,
            ),
        ],
    )


def fixture_cas_limite() -> EpidemicClusterRequest:
    """(c) 2 écoles, signaux faibles uniquement (goût, odeur, trouble)."""
    return EpidemicClusterRequest(
        district=DISTRICT,
        recent_incidents=[
            make_inc(
                21, "École Publique Centre A", DISTRICT, "qualite_eau",
                "L'eau du robinet a un goût étrange et une légère odeur "
                "depuis deux jours.", 2,
            ),
            make_inc(
                22, "École Les Palmiers", DISTRICT, "qualite_eau",
                "Eau légèrement trouble à la fontaine de la cour ce matin.", 1,
            ),
        ],
    )


class EpidemicFixturesTest(unittest.IsolatedAsyncioTestCase):
    async def test_cluster_franc_declenche_outbreak_warning(self) -> None:
        # Le LLM contredit volontairement (normal / pas d'alerte) : le moteur
        # de règles doit faire foi, seul le libellé vient du LLM.
        llm = FakeLLM({
            "risk_level": "normal",
            "alert_triggered": False,
            "epidemic_syndrome": "Syndrome mocké : suspicion choléra",
            "recommended_health_actions": ["Action mockée : chloration"],
        })
        res = await EpidemicDetector(llm).detect_cluster(fixture_cluster_franc())  # type: ignore[arg-type]
        self.assertEqual(res.risk_level, "outbreak_warning")
        self.assertTrue(res.alert_triggered)
        self.assertEqual(res.incident_count, 3)
        self.assertEqual(res.epidemic_syndrome, "Syndrome mocké : suspicion choléra")
        self.assertEqual(res.recommended_health_actions, ["Action mockée : chloration"])
        self.assertEqual(llm.calls, 1)

    async def test_bruit_de_fond_reste_normal(self) -> None:
        llm = FakeLLM({"risk_level": "outbreak_warning", "alert_triggered": True})
        res = await EpidemicDetector(llm).detect_cluster(fixture_bruit_de_fond())  # type: ignore[arg-type]
        self.assertEqual(res.risk_level, "normal")
        self.assertFalse(res.alert_triggered)
        self.assertEqual(res.incident_count, 0)
        self.assertIsNone(res.epidemic_syndrome)
        self.assertEqual(res.recommended_health_actions, [])
        self.assertEqual(llm.calls, 0)  # sans alerte, aucun appel LLM

    async def test_cas_limite_reste_intermediaire_au_plus(self) -> None:
        llm = FakeLLM({"risk_level": "outbreak_warning", "alert_triggered": True})
        res = await EpidemicDetector(llm).detect_cluster(fixture_cas_limite())  # type: ignore[arg-type]
        self.assertNotIn(res.risk_level, ("high", "outbreak_warning"))
        self.assertEqual(res.risk_level, "moderate")
        self.assertFalse(res.alert_triggered)
        self.assertEqual(res.incident_count, 2)
        self.assertEqual(llm.calls, 0)

    async def test_districts_multiples_seul_district_demande_compte(self) -> None:
        # 2 signaux forts dans le district + 1 panne locale + 2 forts ailleurs
        # => high (pas outbreak), et repli statique car le LLM est en panne.
        llm = FakeLLM(exc=RuntimeError("Ollama indisponible"))
        req = EpidemicClusterRequest(
            district=DISTRICT,
            recent_incidents=[
                make_inc(
                    31, "École Publique Centre A", DISTRICT, "contamination",
                    "Eau jaune au forage et trois élèves avec la diarrhée.", 1,
                ),
                make_inc(
                    32, "École Les Palmiers", DISTRICT, "contamination",
                    "Vomissements et diarrhée après la cantine, eau suspecte.", 2,
                ),
                make_inc(
                    33, "Collège Espoir", DISTRICT, "panne_mecanique",
                    "Poignée de la pompe cassée, pas d'eau au robinet.", 1,
                ),
                make_inc(
                    34, "École du Marché", "District-Nord", "contamination",
                    "Eau jaune et cas de diarrhée dans deux classes.", 1,
                ),
                make_inc(
                    35, "École de la Gare", "District-Nord", "contamination",
                    "Diarrhée signalée chez plusieurs élèves, puits trouble.", 2,
                ),
            ],
        )
        res = await EpidemicDetector(llm).detect_cluster(req)  # type: ignore[arg-type]
        self.assertEqual(res.risk_level, "high")
        self.assertTrue(res.alert_triggered)
        self.assertEqual(res.incident_count, 3)  # hors-district exclus
        self.assertIn("2 écoles", res.epidemic_syndrome or "")
        self.assertEqual(res.recommended_health_actions, DEFAULT_HEALTH_ACTIONS)

    async def test_fenetre_expiree_ignoree(self) -> None:
        # Motif de cluster franc mais signalements vieux de 30-45 jours.
        llm = FakeLLM({"risk_level": "outbreak_warning", "alert_triggered": True})
        req = EpidemicClusterRequest(
            district=DISTRICT,
            recent_incidents=[
                make_inc(
                    41, "École Publique Centre A", DISTRICT, "contamination",
                    "L'eau du forage est jaune, plusieurs élèves ont la diarrhée.", 30,
                ),
                make_inc(
                    42, "École Publique Centre B", DISTRICT, "contamination",
                    "Cas de diarrhée et vomissements, eau du puits suspecte.", 31,
                ),
                make_inc(
                    43, "Collège Espoir", DISTRICT, "latrines",
                    "Eau jaunâtre et latrines qui débordent.", 45,
                ),
            ],
        )
        res = await EpidemicDetector(llm).detect_cluster(req)  # type: ignore[arg-type]
        self.assertEqual(res.risk_level, "normal")
        self.assertFalse(res.alert_triggered)
        self.assertEqual(res.incident_count, 0)
        self.assertEqual(llm.calls, 0)


if __name__ == "__main__":
    unittest.main()


class NegationFixturesTest(unittest.IsolatedAsyncioTestCase):
    """AXE 3 : symptômes niés -> silence ; synonymes locaux -> cluster."""

    async def test_negated_symptoms_stay_normal(self) -> None:
        llm = FakeLLM({"risk_level": "outbreak_warning",
                       "alert_triggered": True})
        req = EpidemicClusterRequest(
            district=DISTRICT,
            recent_incidents=[
                make_inc(41, "École Publique Centre A", DISTRICT, "sante",
                         "Pas de diarrhée ni de vomissements cette semaine.", 1),
                make_inc(42, "École Les Palmiers", DISTRICT, "sante",
                         "Aucun cas de choléra signalé, eau claire.", 2),
            ],
        )
        res = await EpidemicDetector(llm).detect_cluster(req)  # type: ignore[arg-type]
        self.assertEqual(res.risk_level, "normal")
        self.assertFalse(res.alert_triggered)
        # incident_count = périmètre (district+fenêtre), pas signaux matchés.
        self.assertEqual(res.incident_count, 2)
        self.assertEqual(llm.calls, 0)

    async def test_local_synonyms_cluster_with_french_strong(self) -> None:
        llm = FakeLLM({})
        req = EpidemicClusterRequest(
            district=DISTRICT,
            recent_incidents=[
                make_inc(43, "École Publique Centre A", DISTRICT, "sante",
                         "Deux cas de choléra confirmés au dispensaire.", 1),
                make_inc(44, "École Les Palmiers", DISTRICT, "sante",
                         "Pikin them get running stomach, dirty wata for tap.", 1),
            ],
        )
        res = await EpidemicDetector(llm).detect_cluster(req)  # type: ignore[arg-type]
        self.assertEqual(res.risk_level, "high")
        self.assertTrue(res.alert_triggered)
        self.assertEqual(res.incident_count, 2)
