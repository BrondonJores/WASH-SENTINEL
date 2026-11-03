"""Constantes partagées des outils agent (LOT 4 anti-valeurs-en-dur).

Source unique des fenêtres temporelles, clamps, seuils et plafonds utilisés
par ``app/tools/*.py`` (et ``app/agent_tools.py`` pour le ratio flou incident) :
zéro duplication, valeurs métier historiques inchangées.

Cohérence des fenêtres (jours glissants, sauf TREND_MONTHS en mois) :
- 7 j : défaut "récent" des alertes (district_alerts, epidemic_alerts,
  relances_proactives) + seuil de dormance/ancienneté (STALE_AFTER_DAYS) ;
- 30 j : défaut "missions/journal" (interventoils_mission,
  document_briefing LOG_WINDOW_DAYS) ;
- 90 j : plafond des fenêtres courtes (clamp 1-90 : alertes, pics, dormants)
  + heatmap pannes (agent_tools.HEATMAP_WINDOW_DAYS, source propre avec
  override ENV car paramètre d'affichage, pas de détection) ;
- 365 j : plafond des fenêtres longues (clamp 1-365 : missions terrain) ;
- 6 mois : mini-tendance observatoire (TREND_MONTHS, agrégation mensuelle,
  pas une fenêtre jour).
"""
from __future__ import annotations

#: Fenêtre "récente" par défaut des détections (alertes, clusters, dormants).
ALERT_WINDOW_DAYS_DEFAULT = 7
#: Bornes de clamp des fenêtres courtes (jours).
ALERT_WINDOW_DAYS_MIN = 1
ALERT_WINDOW_DAYS_MAX = 90

#: Fenêtre "missions/journal" par défaut (timeline terrain).
MISSION_WINDOW_DAYS_DEFAULT = 30
#: Bornes de clamp des fenêtres longues (jours).
MISSION_WINDOW_DAYS_MIN = 1
MISSION_WINDOW_DAYS_MAX = 365

#: Ancienneté définissant un incident dormant/critique ancien (jours).
STALE_AFTER_DAYS = 7
#: Fenêtre des journaux pris en compte dans les documents (jours).
LOG_WINDOW_DAYS = 30

#: Profondeur de la mini-tendance observatoire (mois).
TREND_MONTHS = 6

#: Plafond d'options école affichées en saisie assistée.
MAX_ECOLE_OPTIONS = 6

#: Score difflib minimal pour apparier un incident par titre flou.
INCIDENT_FUZZY_MIN_RATIO = 0.6

# ---------------------------------------------------------------------------
# Périmètre temporel du chat agent (parse_time_window, agent_loop).
# « Aujourd'hui » = date du serveur (SERVER_DATE_TZ), documentée une fois
# ici : aucun fuseau inventé, aucune conversion cachée. Les lignes sont
# comparées en date civile (pas datetime), bornes incluses. Sans période
# exprimée, le contexte d'exécution est inchangé (général = ouverts).
# ---------------------------------------------------------------------------

#: Fuseau de la date serveur servant de référence à « aujourd'hui ».
SERVER_DATE_TZ = "UTC"
#: Fenêtre glissante « 7 derniers jours » (jours, bornes incluses).
TIME_WINDOW_LAST_7D_DAYS = 7
#: Fenêtre glissante « 30 derniers jours » (jours, bornes incluses).
TIME_WINDOW_LAST_30D_DAYS = 30
#: Presets reconnus par parse_time_window (+ "last_{N}d" dynamique).
TIME_WINDOW_PRESETS = (
    "today",
    "yesterday",
    "last_7d",
    "last_30d",
    "this_week",
    "this_month",
    "this_year",
    "since",
)


def tool_lang(context: dict | None) -> str:
    """Langue des libellés d'outils/cartes : 'en' ou 'fr' (défaut).

    Posée par AgentLoop.chat (langue de réponse résolue) ; les appels
    directs (tests, scripts) sans clé restent en français.
    """
    lang = str((context or {}).get("lang") or "fr").strip().lower()
    return "en" if lang.startswith("en") else "fr"
