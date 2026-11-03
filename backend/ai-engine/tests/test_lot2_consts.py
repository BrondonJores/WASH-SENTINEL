"""LOT 2 anti-valeurs-en-dur : constantes centralisées, comportement inchangé.

Ces tests épinglent les VALEURS des constantes (toute modification = décision
explicite) et vérifient que le scoring / la validation restent identiques.
"""
from __future__ import annotations

import unittest
from typing import get_args

from app import bbj_bridge, extractor, schemas
from app.extractor import WashExtractor
from app.schemas import (
    ExtractedWashIncident,
    ImageAnalysisResponse,
    ProviderTestRequest,
    RagAskRequest,
    SchoolEquityProfile,
    SchoolMaintenanceHistory,
    SttTestRequest,
    VoiceSynthesisRequest,
    VoiceSynthesisResponse,
    VoiceTranscriptionResponse,
)


class ExtractorConstsTest(unittest.TestCase):
    def test_values_pinned(self) -> None:
        self.assertEqual(extractor.DEFAULT_AFFECTED_STUDENTS, 50)
        self.assertEqual(extractor.MAX_AFFECTED_STUDENTS, 1000)
        self.assertEqual(extractor.PRIORITY_WEIGHT_URGENCY, 0.35)
        self.assertEqual(extractor.PRIORITY_WEIGHT_HAZARD, 0.35)
        self.assertEqual(extractor.PRIORITY_WEIGHT_STUDENTS, 0.30)
        self.assertEqual(
            extractor.URGENCY_SCORES,
            {"low": 10.0, "medium": 45.0, "high": 75.0, "critical": 100.0},
        )
        self.assertEqual(
            extractor.HAZARD_SCORES,
            {"low": 10.0, "medium": 40.0, "high": 75.0, "severe": 100.0},
        )
        self.assertEqual(extractor.DEFAULT_URGENCY_SCORE, 45.0)
        self.assertEqual(extractor.DEFAULT_HAZARD_SCORE, 40.0)
        self.assertEqual(extractor.CONFIDENCE_BASE, 0.90)
        self.assertEqual(extractor.CONFIDENCE_PENALTY_INFRA, 0.15)
        self.assertEqual(extractor.CONFIDENCE_PENALTY_ISSUE, 0.15)
        self.assertEqual(extractor.CONFIDENCE_PENALTY_URGENCY, 0.10)
        self.assertEqual(extractor.CONFIDENCE_PENALTY_STUDENTS, 0.10)
        self.assertEqual(extractor.CONFIDENCE_PENALTY_UNVALIDATED, 0.05)
        self.assertEqual(extractor.CONFIDENCE_PENALTY_BLANK_OFFTOPIC, 0.20)
        self.assertEqual(extractor.CONFIDENCE_MIN, 0.05)
        self.assertEqual(extractor.CONFIDENCE_MAX, 0.95)
        self.assertEqual(extractor.SUMMARY_FALLBACK_MAX_CHARS, 120)

    def test_priority_scores_unchanged(self) -> None:
        ex = WashExtractor(llm=None)  # type: ignore[arg-type]
        # Valeurs calculées à la main depuis la formule historique :
        # score = u*0.35 + h*0.35 + (min(students or 50, 1000)/1000*100)*0.30.
        cases = [
            ({"urgency_level": "critical", "health_hazard_risk": "severe",
              "estimated_affected_students": 1000}, 100.0),
            ({"urgency_level": "low", "health_hazard_risk": "low",
              "estimated_affected_students": 0}, 8.5),  # 0 -> 50
            ({"urgency_level": "medium", "health_hazard_risk": "medium",
              "estimated_affected_students": 50}, 31.2),
            ({"urgency_level": "high", "health_hazard_risk": "high",
              "estimated_affected_students": 320}, 62.1),
            ({"urgency_level": "???", "health_hazard_risk": "???",
              "estimated_affected_students": 100}, 32.8),  # replis 45/40
            ({"urgency_level": "high", "health_hazard_risk": "high",
              "estimated_affected_students": 5000}, 82.5),  # cap 1000
            ({}, 31.2),  # tout-défaut
        ]
        for data, expected in cases:
            with self.subTest(data=data):
                self.assertEqual(ex.calculate_priority_score(dict(data)), expected)


class SchemasConstsTest(unittest.TestCase):
    def test_values_pinned(self) -> None:
        self.assertEqual(schemas.SCORE_MIN, 0.0)
        self.assertEqual(schemas.SCORE_MAX, 100.0)
        self.assertEqual(schemas.RAG_K_DEFAULT, 3)
        self.assertEqual(schemas.RAG_K_MIN, 1)
        self.assertEqual(schemas.RAG_K_MAX, 10)
        self.assertEqual(schemas.DEFAULT_INSTALLATION_YEAR, 2021)
        # Coût sourcé : 0.0 = non communiqué (le 1 500 000 silencieux est banni).
        self.assertEqual(schemas.DEFAULT_REPLACEMENT_COST, 0.0)
        self.assertEqual(schemas.DEFAULT_EQUITY_DISTANCE_KM, 10.0)
        self.assertEqual(schemas.DEFAULT_EQUITY_DAYS_WITHOUT_WATER, 0)
        self.assertEqual(schemas.DEFAULT_EQUITY_TOTAL_STUDENTS, 300)
        self.assertEqual(schemas.DEFAULT_EQUITY_FEMALE_STUDENTS, 150)
        self.assertEqual(schemas.DEFAULT_EQUITY_BROKEN_TOILETS, 0)
        self.assertEqual(schemas.DEFAULT_EQUITY_MONTHS_SINCE_INTERVENTION, 6)
        self.assertEqual(schemas.DEFAULT_EQUITY_URGENCY, "medium")
        self.assertEqual(schemas.DEFAULT_EQUITY_ISSUE_SUMMARY, "")
        self.assertEqual(schemas.DEFAULT_LANGUAGE, "fr")
        self.assertEqual(schemas.DEFAULT_TTS_VOICE, "fr_FR-upmc-medium")
        self.assertEqual(schemas.DEFAULT_TTS_MIME_TYPE, "audio/wav")
        self.assertEqual(schemas.DEFAULT_LLM_PROVIDER, "ollama")
        self.assertEqual(schemas.DEFAULT_PROVIDER_TEST_TIMEOUT, 30.0)
        self.assertEqual(schemas.DEFAULT_STT_TEST_TIMEOUT, 60.0)
        self.assertEqual(schemas.DEFAULT_STT_DRIVER, "whisper_cpp")
        self.assertEqual(schemas.DEFAULT_STT_TEST_FILENAME, "test.wav")

    def test_models_use_consts(self) -> None:
        # Bornes ge/le branchées sur SCORE_MIN/SCORE_MAX.
        for model, field in (
            (ExtractedWashIncident, "recommended_priority_score"),
            (ImageAnalysisResponse, "visual_severity_score"),
        ):
            info = model.model_fields[field]
            metas = {type(m).__name__: m for m in info.metadata}
            self.assertEqual(getattr(metas["Ge"], "ge", None), schemas.SCORE_MIN)
            self.assertEqual(getattr(metas["Le"], "le", None), schemas.SCORE_MAX)
        rag = RagAskRequest.model_fields["k"]
        metas = {type(m).__name__: m for m in rag.metadata}
        self.assertEqual(rag.default, schemas.RAG_K_DEFAULT)
        self.assertEqual(getattr(metas["Ge"], "ge", None), schemas.RAG_K_MIN)
        self.assertEqual(getattr(metas["Le"], "le", None), schemas.RAG_K_MAX)
        # Défauts branchés sur les constantes.
        hist = SchoolMaintenanceHistory(school_id=1, school_name="E", district="D")
        self.assertEqual(hist.installation_year, schemas.DEFAULT_INSTALLATION_YEAR)
        self.assertEqual(hist.estimated_replacement_cost, schemas.DEFAULT_REPLACEMENT_COST)
        prof = SchoolEquityProfile(school_id=1, school_name="E", district="D")
        self.assertEqual(prof.distance_from_center_km, schemas.DEFAULT_EQUITY_DISTANCE_KM)
        self.assertEqual(prof.days_without_water, schemas.DEFAULT_EQUITY_DAYS_WITHOUT_WATER)
        self.assertEqual(prof.total_students, schemas.DEFAULT_EQUITY_TOTAL_STUDENTS)
        self.assertEqual(prof.female_students, schemas.DEFAULT_EQUITY_FEMALE_STUDENTS)
        self.assertEqual(prof.broken_toilets, schemas.DEFAULT_EQUITY_BROKEN_TOILETS)
        self.assertEqual(
            prof.months_since_last_intervention,
            schemas.DEFAULT_EQUITY_MONTHS_SINCE_INTERVENTION,
        )
        self.assertEqual(prof.urgency_level, schemas.DEFAULT_EQUITY_URGENCY)
        self.assertEqual(prof.issue_summary, schemas.DEFAULT_EQUITY_ISSUE_SUMMARY)
        self.assertEqual(VoiceTranscriptionResponse(transcript="x").language, "fr")
        self.assertEqual(VoiceSynthesisRequest(text="x").voice, schemas.DEFAULT_TTS_VOICE)
        self.assertEqual(
            VoiceSynthesisResponse(audio_base64="x", text="x").mime_type,
            schemas.DEFAULT_TTS_MIME_TYPE,
        )
        prov = ProviderTestRequest(base_url="http://x", model="m")
        self.assertEqual(prov.provider, schemas.DEFAULT_LLM_PROVIDER)
        self.assertEqual(prov.timeout, schemas.DEFAULT_PROVIDER_TEST_TIMEOUT)
        stt = SttTestRequest(audio_base64="x")
        self.assertEqual(stt.driver, schemas.DEFAULT_STT_DRIVER)
        self.assertEqual(stt.filename, schemas.DEFAULT_STT_TEST_FILENAME)
        self.assertEqual(stt.timeout, schemas.DEFAULT_STT_TEST_TIMEOUT)
        self.assertEqual(stt.language, schemas.DEFAULT_LANGUAGE)


class BbjSyncTest(unittest.TestCase):
    def _schema_values(self, field: str) -> frozenset[str]:
        return frozenset(
            v for v in get_args(ExtractedWashIncident.model_fields[field].annotation)
            if v != "other"
        )

    def test_valid_sets_mirror_schema_literals(self) -> None:
        # Le pont ne recopie plus : toute dérive avec schemas.py échoue ici.
        self.assertEqual(bbj_bridge.VALID_INFRASTRUCTURES, self._schema_values("infrastructure_type"))
        self.assertEqual(bbj_bridge.VALID_ISSUES, self._schema_values("issue_type"))
        self.assertEqual(bbj_bridge.VALID_URGENCIES, self._schema_values("urgency_level"))
        # Et les valeurs historiques sont inchangées.
        self.assertEqual(
            bbj_bridge.VALID_INFRASTRUCTURES,
            frozenset({"water_point", "toilets_latrines", "handwashing", "sewage_drainage"}),
        )
        self.assertEqual(
            bbj_bridge.VALID_ISSUES,
            frozenset({"leak", "total_breakdown", "contamination", "blockage",
                        "dry_well", "vandalism"}),
        )
        self.assertEqual(
            bbj_bridge.VALID_URGENCIES, frozenset({"low", "medium", "high", "critical"})
        )

    def test_french_labels_cover_valid_sets(self) -> None:
        self.assertEqual(set(bbj_bridge.INFRA_LABELS_FR), set(bbj_bridge.VALID_INFRASTRUCTURES))
        self.assertEqual(set(bbj_bridge.ISSUE_LABELS_FR), set(bbj_bridge.VALID_ISSUES))
        self.assertTrue(all(v.strip() for v in bbj_bridge.INFRA_LABELS_FR.values()))
        self.assertTrue(all(v.strip() for v in bbj_bridge.ISSUE_LABELS_FR.values()))
        # Alias historiques privés = mêmes objets.
        self.assertIs(bbj_bridge._INFRA_LABELS, bbj_bridge.INFRA_LABELS_FR)
        self.assertIs(bbj_bridge._ISSUE_LABELS, bbj_bridge.ISSUE_LABELS_FR)


if __name__ == "__main__":
    unittest.main()
