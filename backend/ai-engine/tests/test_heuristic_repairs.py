"""Réparations heuristiques déterministes : anti-hallucination petit LLM.

Cas réels constatés en prod (Qwen 3B) à éradiquer :
- CAS 1 : puces VIDES ("Les incidents concernés sont : * * * ...") ;
- CAS 2 : faux placeholder "[Carte interactive ...]" au lieu de la vraie carte.

Lancer depuis backend/ai-engine : ./.venv/bin/python -m unittest
"""
from __future__ import annotations

import unittest

from app.agent_loop import (
    announces_map,
    collect_map_points,
    collect_repair_names,
    maybe_force_map_card,
    repair_empty_bullets,
    repair_final_answer,
    strip_bracket_placeholders,
)
from app.prompts import render_agent_prompt
from app.schemas import AgentCard

DISTRICT_OBS = {
    "open_incidents": 3,
    "by_urgency": {"critical": 1, "high": 2},
    "by_category": {"water_point": 3},
    "total_affected_students": 450,
    "schools_involved": ["EP Mvila Centre", "EP Eboman", "CES Ngoulémakong"],
    "insight": "Tous les 3 incidents ouverts concernent « point d'eau ».",
}

RANK_OBS = {
    "ranking": [
        {"school_id": 1, "school_name": "EP Mvila Centre", "district": "Mvila",
         "need_score": 12.5, "open_incidents": 2, "affected_students": 300,
         "top_urgency": "critical", "rank": 1},
        {"school_id": 2, "school_name": "EP Eboman", "district": "Mvila",
         "need_score": 7.0, "open_incidents": 1, "affected_students": 150,
         "top_urgency": "high", "rank": 2},
    ],
    "total": 2,
    "insight": "EP Mvila Centre devance EP Eboman de 5,5 points.",
}

EXECUTED = [("summarize_district", DISTRICT_OBS), ("rank_schools_by_need", RANK_OBS)]

CONTEXT = {
    "schools": [
        {"school_id": 1, "school_name": "EP Mvila Centre", "district": "Mvila",
         "latitude": 2.95, "longitude": 11.15},
        {"school_id": 2, "school_name": "EP Eboman", "district": "Mvila",
         "latitude": 2.90, "longitude": 11.20},
        {"school_id": 3, "school_name": "EP Sans GPS", "district": "Mvila"},
    ]
}


class CollectRepairNamesTest(unittest.TestCase):
    def test_names_from_observations(self) -> None:
        names = collect_repair_names(EXECUTED)
        self.assertIn("EP Mvila Centre", names)
        self.assertIn("EP Eboman", names)
        self.assertIn("CES Ngoulémakong", names)
        self.assertEqual(len(names), len(set(names)))

    def test_error_observations_ignored(self) -> None:
        names = collect_repair_names([("summarize_district", {"error": "oups"})])
        self.assertEqual(names, [])


class EmptyBulletsTest(unittest.TestCase):
    def test_line_bullets_filled_from_observations(self) -> None:
        answer = "Dans le district Mvila, 3 écoles sans eau :\n-\n-\n*"
        repaired = repair_final_answer(answer, EXECUTED)
        self.assertNotRegex(repaired, r"(?m)^\s*[-*•]\s*$")
        self.assertIn("EP Mvila Centre", repaired)
        self.assertIn("EP Eboman", repaired)

    def test_numbered_bullets_filled_marker_kept(self) -> None:
        repaired = repair_empty_bullets("Écoles :\n1. \n2. ", ["EP A", "EP B"])
        self.assertIn("1. EP A", repaired)
        self.assertIn("2. EP B", repaired)

    def test_short_content_counts_as_empty(self) -> None:
        repaired = repair_empty_bullets("- **\n- vraie école citée", ["EP A"])
        self.assertIn("- EP A", repaired)
        self.assertIn("- vraie école citée", repaired)

    def test_cas1_inline_bullets_filled(self) -> None:
        answer = ("Dans le district Mvila, il y a actuellement 3 écoles sans eau. "
                  "Les incidents concernés sont : * * * Ces écoles ont des "
                  "problèmes avec les points d'eau.")
        repaired = repair_final_answer(answer, EXECUTED)
        self.assertNotIn("* * *", repaired)
        self.assertIn("EP Mvila Centre", repaired)
        self.assertIn("EP Eboman", repaired)

    def test_empty_bullets_removed_without_data(self) -> None:
        answer = "Constat :\n- \n* \n1. \nFin du message."
        repaired = repair_final_answer(answer, [])
        self.assertNotIn("-", repaired.replace("Fin du message.", ""))
        self.assertNotIn("*", repaired)
        self.assertIn("Fin du message.", repaired)

    def test_inline_bullets_removed_without_data(self) -> None:
        repaired = repair_final_answer("Incidents : * * * Fin.", [])
        self.assertNotIn("*", repaired)
        self.assertIn("Fin.", repaired)

    def test_multiplication_not_treated_as_bullet(self) -> None:
        repaired = repair_empty_bullets("2 * 3 font 6", ["EP A"])
        self.assertEqual(repaired, "2 * 3 font 6")


class BracketPlaceholdersTest(unittest.TestCase):
    def test_cas2_placeholder_removed(self) -> None:
        answer = ("Voici la carte interactive des deux écoles du district Mvila : "
                  "[Carte interactive affichant les deux écoles]")
        repaired = strip_bracket_placeholders(answer)
        self.assertNotIn("[", repaired)
        self.assertNotIn("]", repaired)
        self.assertIn("Voici la carte interactive", repaired)

    def test_placeholder_variants_removed(self) -> None:
        for placeholder in ("[carte du district]", "[graphique des pannes]",
                            "[voir la carte ci-dessous]", "[interactive map]",
                            "[Chart of incidents]"):
            with self.subTest(placeholder=placeholder):
                self.assertNotIn("[", strip_bracket_placeholders(f"Texte {placeholder}."))

    def test_truncation_notes_preserved(self) -> None:
        note = "Détail…[tronqué, 5000 caractères au total]"
        self.assertEqual(strip_bracket_placeholders(note), note)
        plus = "Écoles : A, B [+3 autres, voir la carte]"
        self.assertEqual(strip_bracket_placeholders(plus), plus)


class ForcedMapTest(unittest.TestCase):
    def test_map_announcement_without_card_forces_card(self) -> None:
        answer = "Voici la carte interactive des écoles du district Mvila."
        cards = maybe_force_map_card(answer, EXECUTED, [], CONTEXT)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].type, "territory_map")
        self.assertEqual(cards[0].data["total"], 2)
        names = [s["school_name"] for s in cards[0].data["schools"]]
        self.assertIn("EP Mvila Centre", names)
        self.assertTrue(all("lat" in s and "lng" in s for s in cards[0].data["schools"]))

    def test_direct_obs_points_used_first(self) -> None:
        obs = {"schools": [{"school_name": "EP Directe", "district": "Mvila",
                            "lat": 3.0, "lng": 11.0, "open_incidents": 1}]}
        points = collect_map_points([("custom", obs)], None)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["school_name"], "EP Directe")

    def test_no_announcement_no_card(self) -> None:
        cards = maybe_force_map_card("Deux écoles sans eau à Mvila.", EXECUTED, [], CONTEXT)
        self.assertEqual(cards, [])

    def test_existing_map_card_not_duplicated(self) -> None:
        existing = [AgentCard(type="territory_map", title="Carte", data={})]
        cards = maybe_force_map_card("Voici la carte interactive.", EXECUTED, existing, CONTEXT)
        self.assertEqual(len(cards), 1)

    def test_no_gps_no_card(self) -> None:
        cards = maybe_force_map_card("Voici la carte interactive.", EXECUTED, [], {})
        self.assertEqual(cards, [])

    def test_announces_map_fr_and_en(self) -> None:
        self.assertTrue(announces_map("Voici la carte des écoles."))
        self.assertTrue(announces_map("La carte interactive est ci-dessous."))
        self.assertTrue(announces_map("Here is the map of the district."))
        self.assertFalse(announces_map("Deux écoles ont besoin d'aide."))


class PromptRulesTest(unittest.TestCase):
    def test_prompt_forbids_placeholders_maps_announcements(self) -> None:
        prompt = render_agent_prompt()
        self.assertIn("[carte]", prompt)
        self.assertIn("[map]", prompt)
        self.assertIn("voici la carte", prompt)
        self.assertIn("carte interactive", prompt)
        self.assertIn("never announce or describe cards or maps", prompt.lower())
        self.assertIn("exactly as observed", prompt.lower())


class IdempotenceTest(unittest.TestCase):
    def test_healthy_answer_unchanged(self) -> None:
        answer = ("3 incidents ouverts touchent 450 élèves dans 3 écoles, "
                  "dont 1 critique. Le détail est dans la carte ci-dessous.")
        self.assertEqual(repair_final_answer(answer, EXECUTED), answer)

    def test_repair_is_idempotent(self) -> None:
        answer = ("Écoles sans eau : * * * vraiment [Carte interactive des écoles].\n"
                  "-\n1. ")
        once = repair_final_answer(answer, EXECUTED)
        self.assertEqual(repair_final_answer(once, EXECUTED), once)


if __name__ == "__main__":
    unittest.main()
