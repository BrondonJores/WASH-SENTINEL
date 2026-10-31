"""Détecteur d'alerte épidémique (grappes d'incidents WASH par district).

Seuils validés le 2026-10-31 sur fixtures réalistes (tests/test_epidemic.py) :
cluster franc (3 écoles, eau jaune + diarrhées, 7 j) -> ``outbreak_warning``,
bruit de fond (pannes mécaniques hors district) -> ``normal``,
cas limite (2 écoles, signaux faibles) -> ``moderate``.

Architecture : le score déterministe (mots-clés sanitaires + regroupement
par école + filtre district + fenêtre temporelle) FAIT FOI pour le niveau
de risque et le déclenchement de l'alerte. Le LLM ne sert qu'à rédiger le
libellé du syndrome et les actions recommandées quand une alerte est
déclenchée (``high`` / ``outbreak_warning``), avec un repli statique s'il
est indisponible ou muet. En dessous du seuil d'alerte, aucun appel LLM
n'est émis (résultat purement déterministe, rapide et testable).

Limites honnêtes :
- Jamais confronté à de vraies données terrain : les seuils sont réglés
  sur 5 fixtures synthétiques, pas sur des cas historiques ni une courbe
  ROC. Recalibrer dès que des données réelles existent.
- Mots-clés français uniquement, sans analyse de négation ("pas de
  diarrhée" compte à tort comme signal) ni prise en charge des langues
  locales camerounaises.
- Aucune donnée sanitaire externe (centres de santé, pluviométrie,
  saisonnalité du choléra) : le détecteur ne voit que les signalements.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Any

from .providers import BaseLLMProvider
from .schemas import DistrictIncidentRecord, EpidemicClusterRequest, EpidemicClusterResponse

EPIDEMIC_ANALYZER_SYSTEM = """
Tu es l'épidémiologiste et expert en santé publique de WASH Sentinel.
Une grappe d'incidents sanitaires vient d'être confirmée par le moteur de règles
dans un district scolaire : formule le syndrome probable et les actions d'urgence.

Renvoie STRICTEMENT un JSON valide :
{
  "epidemic_syndrome": "string ou null (ex: Risque élevé d'épidémie de choléra par contamination de la nappe)",
  "recommended_health_actions": ["liste d'actions d'urgence, ex: Déploiement de kits de chloration Aquatabs, fermeture temporaire des points d'eau incriminés, prélèvements bactériologiques d'urgence"]
}

Règles :
1. Ne minimise jamais : l'alerte est déjà déclenchée, ton rôle est d'orienter la riposte.
2. Uniquement du JSON.
"""

# ---------------------------------------------------------------------------
# Constantes de réglage (justification sous chacune — validées le 2026-10-31)
# ---------------------------------------------------------------------------

#: Incidents pris en compte : signalés il y a au plus 7 jours (inclus).
#: Justification : incubation choléra/diarrhées (quelques heures à 5 j) +
#: délai de remontée terrain ; au-delà, le lien épidémiologique est douteux
#: et les vieux incidents gonfleraient artificiellement les grappes.
CLUSTER_WINDOW_DAYS = 7

#: Écoles distinctes avec signal FORT requises pour le niveau maximal.
#: Justification : 3 écoles = diffusion communautaire probable (source
#: commune : nappe, réseau), pas un incident isolé ; calibre la fixture (a).
OUTBREAK_MIN_STRONG_SCHOOLS = 3

#: Écoles distinctes avec signal FORT requises pour le niveau ``high``.
#: Justification : 2 écoles = suspicion sérieuse mais pas encore de grappe
#: avérée ; déclenche l'alerte (riposte) sans le niveau maximal.
HIGH_MIN_STRONG_SCHOOLS = 2

#: Sous-strings (normalisés : minuscules, sans accents) trahissant un danger
#: sanitaire avéré : symptômes ou contamination explicite de l'eau/latrines.
STRONG_SIGNAL_KEYWORDS = (
    "diarrh",    # diarrhée(s) — symptôme sentinelle n°1 des épidémies hydriques
    "cholera",   # mention explicite (même suspectée) : toujours maximale
    "vomiss",    # vomissements groupés = toxi-infection / choléra possible
    "dysenteri",  # dysenterie (selles sanglantes) : gravité immédiate
    "contamin",  # contamination / eau contaminée : cause racine explicite
    "eau jaune",  # eau jaune : turbidité/pollution organique visible
    "jaune",     # couvre "l'eau est jaune" (tournure courante des signalements)
    "jaunatre",  # variante orthographique fréquente
    "debord",    # latrines/WC qui débordent : contact fécal direct
)

#: Sous-strings trahissant un indice faible : anomalie sensorielle ou trouble
#: digestif vague, insuffisant seul pour alerter mais à surveiller.
WEAK_SIGNAL_KEYWORDS = (
    "trouble",  # eau trouble : anomalie visuelle, pas de symptôme
    "odeur",    # odeur inhabituelle : indice, pas preuve
    "gout",     # goût étrange : subjectif, à recouper
    "ventre",   # maux de ventre : vague, non spécifique
    "nause",    # nausées : symptôme léger, non spécifique
)

#: Actions d'urgence servies quand le LLM est indisponible ou muet.
#: Justification : kit standard OMS/choléra (chloration, hygiène, prélèvement)
#: applicable sans diagnostic précis ; mieux qu'une alerte sans conduite à tenir.
DEFAULT_HEALTH_ACTIONS = [
    "Distribution d'urgence de pastilles de purification d'eau (Aquatabs)",
    "Sensibilisation immédiate au lavage des mains au savon dans les classes",
    "Inspection sanitaire de la source d'approvisionnement communale",
]


def _normalize(text: str | None) -> str:
    """Minuscules + suppression des accents pour une comparaison robuste."""
    ascii_folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_folded.lower().split())


def _parse_reported_date(value: str | None) -> date | None:
    """Parse ``reported_at`` (ISO ``AAAA-MM-JJ`` ou datetime ISO), None sinon."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip()).date()
    except ValueError:
        return None


def signal_strength(incident: DistrictIncidentRecord) -> str:
    """Force du signal sanitaire d'un incident : ``strong`` | ``weak`` | ``none``.

    Les signaux forts (symptômes, contamination explicite) priment : dès
    qu'un mot-clé fort est présent, l'incident est fort même s'il contient
    aussi des mots faibles.
    """
    haystack = _normalize(f"{incident.category} {incident.summary}")
    if any(kw in haystack for kw in STRONG_SIGNAL_KEYWORDS):
        return "strong"
    if any(kw in haystack for kw in WEAK_SIGNAL_KEYWORDS):
        return "weak"
    return "none"


def _is_within_window(reported: date | None, today: date) -> bool:
    """Vrai si la date est dans la fenêtre (ou inconnue/future : fail-open).

    Justification du fail-open : ne jamais faire taire un signalement à
    cause d'un format de date inattendu ou d'une horloge décalée ; le tri
    se fait sur le contenu, pas sur la métadonnée.
    """
    if reported is None or reported > today:
        return True
    return (today - reported).days <= CLUSTER_WINDOW_DAYS


class EpidemicDetector:
    def __init__(self, llm: BaseLLMProvider | None):
        self.llm = llm

    def _relevant_incidents(
        self, req: EpidemicClusterRequest, today: date
    ) -> list[DistrictIncidentRecord]:
        """Incidents du district demandé ET dans la fenêtre temporelle."""
        district = _normalize(req.district)
        return [
            inc
            for inc in req.recent_incidents
            if _normalize(inc.district) == district
            and _is_within_window(_parse_reported_date(inc.reported_at), today)
        ]

    @staticmethod
    def _rule_level(strong_schools: int, weak_schools: int) -> tuple[str, bool]:
        """Niveau déterministe depuis les décomptes d'écoles touchées."""
        if strong_schools >= OUTBREAK_MIN_STRONG_SCHOOLS:
            return "outbreak_warning", True
        if strong_schools >= HIGH_MIN_STRONG_SCHOOLS:
            return "high", True
        if strong_schools >= 1 or weak_schools >= 1:
            return "moderate", False
        return "normal", False

    async def _enrich_with_llm(
        self,
        req: EpidemicClusterRequest,
        relevant: list[DistrictIncidentRecord],
        strong_schools: int,
    ) -> tuple[str | None, list[str]]:
        """Rédige syndrome + actions via le LLM, avec repli statique garanti."""
        fallback_syndrome = (
            f"Grappe suspecte : {strong_schools} écoles avec signaux sanitaires "
            f"forts dans le district {req.district} (fenêtre {CLUSTER_WINDOW_DAYS} j)"
        )
        if self.llm is None:
            return fallback_syndrome, list(DEFAULT_HEALTH_ACTIONS)
        incidents_summary = "\n".join(
            f"- École: {inc.school_name} | Catégorie: {inc.category} "
            f"| Panne: {inc.summary} | Date: {inc.reported_at}"
            for inc in relevant
        )
        prompt = (
            f"District analysé : {req.district}\n"
            f"Écoles avec signaux forts : {strong_schools}\n"
            f"Signalements retenus :\n{incidents_summary}"
        )
        try:
            raw: dict[str, Any] = await self.llm.generate_json(prompt, EPIDEMIC_ANALYZER_SYSTEM)
        except Exception:
            return fallback_syndrome, list(DEFAULT_HEALTH_ACTIONS)
        # NOTE : raw["risk_level"] / raw["alert_triggered"] sont volontairement
        # ignorés — le moteur de règles fait foi (décision déterministe).
        syndrome = raw.get("epidemic_syndrome") or fallback_syndrome
        actions = raw.get("recommended_health_actions")
        if not isinstance(actions, list) or not actions:
            actions = list(DEFAULT_HEALTH_ACTIONS)
        return syndrome, actions

    async def detect_cluster(self, req: EpidemicClusterRequest) -> EpidemicClusterResponse:
        if not req.recent_incidents:
            return EpidemicClusterResponse(
                district=req.district,
                incident_count=0,
                risk_level="normal",
                alert_triggered=False,
                epidemic_syndrome=None,
                recommended_health_actions=[],
            )

        relevant = self._relevant_incidents(req, date.today())

        # Regroupement par école : une école = une voix (évite qu'une école
        # très bavarde déclenche seule une alerte de grappe).
        school_signals: dict[str, str] = {}
        for inc in relevant:
            key = _normalize(inc.school_name)
            strength = signal_strength(inc)
            if strength == "strong" or key not in school_signals:
                school_signals[key] = strength
            elif school_signals[key] == "none":
                school_signals[key] = strength

        strong_schools = sum(1 for s in school_signals.values() if s == "strong")
        weak_schools = sum(1 for s in school_signals.values() if s == "weak")
        risk_level, alert_triggered = self._rule_level(strong_schools, weak_schools)

        if not alert_triggered:
            # Pas d'alerte : réponse purement déterministe, sans appel LLM.
            return EpidemicClusterResponse(
                district=req.district,
                incident_count=len(relevant),
                risk_level=risk_level,  # type: ignore[arg-type]
                alert_triggered=False,
                epidemic_syndrome=None,
                recommended_health_actions=[],
            )

        syndrome, actions = await self._enrich_with_llm(req, relevant, strong_schools)
        return EpidemicClusterResponse(
            district=req.district,
            incident_count=len(relevant),
            risk_level=risk_level,  # type: ignore[arg-type]
            alert_triggered=True,
            epidemic_syndrome=syndrome,
            recommended_health_actions=actions,
        )
