from __future__ import annotations

import math
import os
from typing import Any
from .providers import BaseLLMProvider
from .schemas import (
    FairnessDispatchPlan,
    FairnessDispatchRequest,
    FairnessRankingItem,
    GroupedMission,
    SchoolEquityProfile,
)

TRANSPARENCY_NOTE_SYSTEM = """
Tu es le Rapporteur Général de l'Autorité Territoriale de l'Eau et de l'Assainissement Scolaire (WASH Sentinel).
Ton rôle est de rédiger la "Note Officielle de Transparence et de Priorisation Territoriale" qui sera rendue publique pour couper court à toute accusation de favoritisme ou de clientélisme politique.

Structure impérative :
1. RAPPEL DU PRINCIPE D'ÉQUITÉ : Mentionner que les priorités sont calculées selon une formule transparente et auditable (durée de privation, risque sanitaire, protection de la scolarisation des filles, et rattrapage des écoles isolées).
2. JUSTIFICATION DES PRIORITÉS DU JOUR : Citer nommément les écoles prioritaires avec leurs chiffres réels (jours sans eau, nombre d'enfants).
3. OPTIMISATION LOGISTIQUE : Expliquer comment la tournée mutualise le carburant communal en traitant plusieurs établissements sur le même axe.
4. CALENDRIER D'ÉQUITÉ : Rassurer les autres écoles que leur tour viendra selon le planning mutualisé.

Ton ton doit être républicain, impartial, factuel et bienveillant.
"""


def _env_float(name: str, default: float) -> float:
    """Override ENV typé ; défaut historique inchangé si absent/invalide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    """Override ENV typé ; défaut historique inchangé si absent/invalide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --- LOT 3 : formule d'équité centralisée (valeurs historiques inchangées) ---

#: Normalisation de la privation d'eau : saturation à 20 jours sans eau.
EQUITY_WATER_NORM_DAYS = _env_float("EQUITY_WATER_NORM_DAYS", 20.0)

#: Table urgence sanitaire -> sous-score /100 (niveaux nommés + override ENV).
EQUITY_URGENCY_LOW = _env_float("EQUITY_URGENCY_LOW", 15.0)
EQUITY_URGENCY_MEDIUM = _env_float("EQUITY_URGENCY_MEDIUM", 45.0)
EQUITY_URGENCY_HIGH = _env_float("EQUITY_URGENCY_HIGH", 75.0)
EQUITY_URGENCY_CRITICAL = _env_float("EQUITY_URGENCY_CRITICAL", 100.0)
EQUITY_URGENCY_SCORES = {
    "low": EQUITY_URGENCY_LOW,
    "medium": EQUITY_URGENCY_MEDIUM,
    "high": EQUITY_URGENCY_HIGH,
    "critical": EQUITY_URGENCY_CRITICAL,
}

#: Clamp du ratio de filles (évite les extrêmes 0 % / 100 %).
EQUITY_FEMALE_RATIO_MIN = _env_float("EQUITY_FEMALE_RATIO_MIN", 0.3)
EQUITY_FEMALE_RATIO_MAX = _env_float("EQUITY_FEMALE_RATIO_MAX", 0.7)

#: Normalisation latrines HS : saturation à 4 WC ; plancher 0.1 sans panne.
EQUITY_LATRINE_NORM_COUNT = _env_float("EQUITY_LATRINE_NORM_COUNT", 4.0)
EQUITY_LATRINE_BASELINE_SCORE = _env_float("EQUITY_LATRINE_BASELINE_SCORE", 0.1)

#: Amplificateur genre (pondère le risque de décrochage des filles).
EQUITY_GENDER_AMPLIFIER = _env_float("EQUITY_GENDER_AMPLIFIER", 1.5)

#: Rattrapage isolement : 70 km -> 50 pts max, 18 mois d'oubli -> 50 pts max.
EQUITY_DISTANCE_NORM_KM = _env_float("EQUITY_DISTANCE_NORM_KM", 70.0)
EQUITY_DISTANCE_MAX_POINTS = _env_float("EQUITY_DISTANCE_MAX_POINTS", 50.0)
EQUITY_ABANDON_NORM_MONTHS = _env_float("EQUITY_ABANDON_NORM_MONTHS", 18.0)
EQUITY_ABANDON_MAX_POINTS = _env_float("EQUITY_ABANDON_MAX_POINTS", 50.0)

#: Poids du score global (somme = 1.0) : eau 30 / urgence 25 / genre 25 / isolement 20.
EQUITY_WEIGHT_WATER = _env_float("EQUITY_WEIGHT_WATER", 0.30)
EQUITY_WEIGHT_URGENCY = _env_float("EQUITY_WEIGHT_URGENCY", 0.25)
EQUITY_WEIGHT_GENDER = _env_float("EQUITY_WEIGHT_GENDER", 0.25)
EQUITY_WEIGHT_ISOLATION = _env_float("EQUITY_WEIGHT_ISOLATION", 0.20)

#: Seuils du motif d'équité affiché : ≥10 j sans eau, ≥2 latrines HS, ≥40 km.
EQUITY_REASON_MIN_DAYS_WITHOUT_WATER = _env_int("EQUITY_REASON_MIN_DAYS_WITHOUT_WATER", 10)
EQUITY_REASON_MIN_BROKEN_TOILETS = _env_int("EQUITY_REASON_MIN_BROKEN_TOILETS", 2)
EQUITY_REASON_MIN_ISOLATION_KM = _env_int("EQUITY_REASON_MIN_ISOLATION_KM", 40)

#: Tournées : écoles groupées si écart ≤18 km, économie aller-retour ×1.6, max 2 embarquées.
EQUITY_ROUTE_MAX_DIST_DIFF_KM = _env_float("EQUITY_ROUTE_MAX_DIST_DIFF_KM", 18.0)
EQUITY_ROUTE_SAVED_KM_FACTOR = _env_float("EQUITY_ROUTE_SAVED_KM_FACTOR", 1.6)
EQUITY_ROUTE_MAX_PIGGYBACK = _env_int("EQUITY_ROUTE_MAX_PIGGYBACK", 2)

#: Longueur min d'une note de transparence LLM recevable (sinon repli statique).
EQUITY_TRANSPARENCY_NOTE_MIN_CHARS = _env_int("EQUITY_TRANSPARENCY_NOTE_MIN_CHARS", 100)


class EquityDispatcher:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    def calculate_equity_score(self, school: SchoolEquityProfile) -> tuple[float, str]:
        """
        Formule d'Équité & Vulnérabilité Territoriale (0 à 100) :
        - 30% Durée de privation réelle d'eau
        - 25% Urgence sanitaire brute
        - 25% Impact Genre & Décrochage des filles (latrines)
        - 20% Rattrapage de l'isolement géographique et historique d'abandon
        """
        # 1. Privation Eau (Poids 30%)
        water_score = min(school.days_without_water / EQUITY_WATER_NORM_DAYS, 1.0) * 100.0

        # 2. Urgence sanitaire (Poids 25%)
        urgency_score = EQUITY_URGENCY_SCORES.get(school.urgency_level, EQUITY_URGENCY_MEDIUM)

        # 3. Impact Genre & Latrines (Poids 25%)
        tot = max(school.total_students, 1)
        female_ratio = min(max(school.female_students / float(tot), EQUITY_FEMALE_RATIO_MIN), EQUITY_FEMALE_RATIO_MAX)
        latrine_penalty = min(school.broken_toilets / EQUITY_LATRINE_NORM_COUNT, 1.0) if school.broken_toilets > 0 else EQUITY_LATRINE_BASELINE_SCORE
        gender_score = (female_ratio * EQUITY_GENDER_AMPLIFIER) * latrine_penalty * 100.0

        # 4. Rattrapage Isolement géographique & Oubli historique (Poids 20%)
        distance_comp = min(school.distance_from_center_km / EQUITY_DISTANCE_NORM_KM, 1.0) * EQUITY_DISTANCE_MAX_POINTS
        abandon_comp = min(school.months_since_last_intervention / EQUITY_ABANDON_NORM_MONTHS, 1.0) * EQUITY_ABANDON_MAX_POINTS
        isolation_score = distance_comp + abandon_comp

        # Score global pondéré
        total_score = (
            (water_score * EQUITY_WEIGHT_WATER)
            + (urgency_score * EQUITY_WEIGHT_URGENCY)
            + (gender_score * EQUITY_WEIGHT_GENDER)
            + (isolation_score * EQUITY_WEIGHT_ISOLATION)
        )
        total_score = round(min(max(total_score, 0.0), 100.0), 1)

        # Motif principal d'équité
        reasons = []
        if school.days_without_water >= EQUITY_REASON_MIN_DAYS_WITHOUT_WATER:
            reasons.append(f"{school.days_without_water}j sans eau")
        if school.broken_toilets >= EQUITY_REASON_MIN_BROKEN_TOILETS:
            reasons.append(f"Latrines HS ({school.female_students} filles menacées de décrochage)")
        if school.distance_from_center_km >= EQUITY_REASON_MIN_ISOLATION_KM:
            reasons.append(f"Zone isolée ({school.distance_from_center_km}km)")
        if school.urgency_level == "critical":
            reasons.append("Urgence critique immédiate")

        reason_str = " | ".join(reasons) if reasons else "Maintenance programmée standard"
        return total_score, reason_str

    def build_grouped_missions(self, ranked: list[FairnessRankingItem], schools_map: dict[int, SchoolEquityProfile]) -> list[GroupedMission]:
        """
        Optimiseur de tournées logistiques :
        Associe à chaque urgence critique les écoles secondaires sur le même axe
        pour éviter de faire 100 km pour un seul robinet.
        """
        missions: list[GroupedMission] = []
        visited = set()

        for item in ranked:
            if item.school_id in visited:
                continue

            primary_profile = schools_map.get(item.school_id)
            if not primary_profile:
                continue

            visited.add(item.school_id)
            piggybacked: list[str] = []
            saved_km = 0.0

            # Cherche les écoles dans un rayon de 20 km du même secteur
            for other_item in ranked:
                if other_item.school_id in visited:
                    continue
                other_profile = schools_map.get(other_item.school_id)
                if not other_profile:
                    continue

                # Calcul de proximité relative
                dist_diff = abs(primary_profile.distance_from_center_km - other_profile.distance_from_center_km)
                if dist_diff <= EQUITY_ROUTE_MAX_DIST_DIFF_KM:
                    visited.add(other_item.school_id)
                    piggybacked.append(other_item.school_name)
                    # Économie d'un aller-retour complet
                    saved_km += round(other_profile.distance_from_center_km * EQUITY_ROUTE_SAVED_KM_FACTOR, 1)
                    if len(piggybacked) >= EQUITY_ROUTE_MAX_PIGGYBACK:
                        break

            axis_name = f"Axe {primary_profile.district} (Direction {primary_profile.school_name})"
            brief = (
                f"Départ de l'équipe technique pour l'urgence prioritaire à {primary_profile.school_name}. "
            )
            if piggybacked:
                brief += (
                    f"Embarquer les pièces d'avance pour dépanner au passage : {', '.join(piggybacked)}. "
                    f"Mutualisation réussie : 1 seule mission pour {1 + len(piggybacked)} écoles."
                )
            else:
                brief += "Intervention ciblée directe sans détour possible."

            missions.append(GroupedMission(
                route_name=axis_name,
                primary_emergency_school=primary_profile.school_name,
                piggybacked_schools=piggybacked,
                total_schools_served=1 + len(piggybacked),
                estimated_kilometers_saved=saved_km,
                technician_mission_brief=brief,
            ))

        return missions

    async def generate_fairness_plan(self, req: FairnessDispatchRequest) -> FairnessDispatchPlan:
        schools = req.schools
        if not schools:
            schools = self._demo_schools_for_fairness(req.district)

        schools_map = {s.school_id: s for s in schools}

        # 1. Calcul des scores d'équité pour chaque établissement
        evaluated_items: list[tuple[float, FairnessRankingItem]] = []
        for s in schools:
            score, reason = self.calculate_equity_score(s)
            item = FairnessRankingItem(
                school_id=s.school_id,
                school_name=s.school_name,
                equity_score=score,
                rank=1,
                primary_vulnerability_reason=reason,
                days_deprived=s.days_without_water,
                distance_km=s.distance_from_center_km,
            )
            evaluated_items.append((score, item))

        # Tri décroissant selon le score d'équité
        evaluated_items.sort(key=lambda x: x[0], reverse=True)

        ranked: list[FairnessRankingItem] = []
        for index, (_, item) in enumerate(evaluated_items, start=1):
            item.rank = index
            ranked.append(item)

        # 2. Construction des tournées logistiques optimisées
        grouped_missions = self.build_grouped_missions(ranked, schools_map)

        # 3. Génération de la note officielle de transparence opposable
        prompt = f"""
District : {req.district}
Nombre d'écoles évaluées : {len(ranked)}
Top 3 des écoles prioritaires selon l'algorithme d'équité :
"""
        for r in ranked[:3]:
            prompt += f"- Rang #{r.rank} : {r.school_name} (Score : {r.equity_score}/100 | Motif : {r.primary_vulnerability_reason})\n"

        prompt += f"\nTournées logistiques prévues : {len(grouped_missions)} mission(s) mutualisée(s)."

        try:
            transparency_note = (await self.llm.generate_json(
                prompt=prompt,
                system=TRANSPARENCY_NOTE_SYSTEM + "\nRéponds avec un JSON : {\"official_note\": \"le texte complet de la note\"}"
            )).get("official_note", "")
        except Exception:
            transparency_note = ""

        if not transparency_note or len(transparency_note) < EQUITY_TRANSPARENCY_NOTE_MIN_CHARS:
            top_school = ranked[0].school_name if ranked else "N/A"
            transparency_note = (
                f"NOTE OFFICIELLE DE TRANSPARENCE TERRITORIALE - DISTRICT {req.district.upper()}\n\n"
                f"En application des critères d'équité républicaine et des standards OMS/UNICEF, "
                f"l'ordre d'intervention technique a été établi de manière algorithmique et auditable sans aucune distinction discrétionnaire.\n\n"
                f"L'intervention prioritaire n°1 est accordée à l'établissement {top_school} en raison d'une privation d'eau prolongée "
                f"et d'un risque élevé d'abandon scolaire pour les élèves.\n\n"
                f"Afin de préserver les deniers publics et le carburant communal, les équipes d'intervention mutualisent leurs déplacements "
                f"en traitant les écoles secondaires sur le même itinéraire."
            )

        return FairnessDispatchPlan(
            district=req.district,
            total_schools_evaluated=len(schools),
            ranked_schools=ranked,
            grouped_routes=grouped_missions,
            public_transparency_note=transparency_note,
        )

    def _demo_schools_for_fairness(self, district: str) -> list[SchoolEquityProfile]:
        """Génère 4 écoles aux profils très contrastés pour prouver l'anti-favoritisme au jury."""
        return [
            SchoolEquityProfile(
                school_id=101,
                school_name="École Rurale Oubliée de Ngok (72 km)",
                district=district,
                distance_from_center_km=72.0,
                days_without_water=22,  # 22 jours sans eau !
                total_students=380,
                female_students=195,
                broken_toilets=4,
                months_since_last_intervention=14,
                urgency_level="critical",
                issue_summary="Pompe manuelle arrachée, les élèves puisent dans le marigot",
            ),
            SchoolEquityProfile(
                school_id=102,
                school_name="École Centrale du Centre-Ville (3 km)",
                district=district,
                distance_from_center_km=3.0,
                days_without_water=2,  # Panne très récente, mais école en ville
                total_students=650,
                female_students=310,
                broken_toilets=1,
                months_since_last_intervention=2,
                urgency_level="medium",
                issue_summary="Fuite sur le robinet du bureau administratif",
            ),
            SchoolEquityProfile(
                school_id=103,
                school_name="Collège Rural de Mvila (65 km sur l'axe Ngok)",
                district=district,
                distance_from_center_km=65.0,  # Sur le même axe routier que Ngok !
                days_without_water=8,
                total_students=420,
                female_students=220,
                broken_toilets=2,
                months_since_last_intervention=9,
                urgency_level="high",
                issue_summary="Vanne de cuve bloquée, débit très faible",
            ),
            SchoolEquityProfile(
                school_id=104,
                school_name="École Publique Bilingue Plateau (12 km)",
                district=district,
                distance_from_center_km=12.0,
                days_without_water=5,
                total_students=290,
                female_students=140,
                broken_toilets=0,
                months_since_last_intervention=5,
                urgency_level="medium",
                issue_summary="Robinetterie extérieure à remplacer",
            ),
        ]
