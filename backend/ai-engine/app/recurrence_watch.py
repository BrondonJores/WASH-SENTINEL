"""Détection prédictive de pannes WASH récurrentes : alerter AVANT la prochaine casse.

Ce module est 100 % déterministe et n'appelle aucun LLM : que des fonctions
pures de la bibliothèque standard (plus ``SchoolMaintenanceHistory`` importé
de :mod:`app.schemas` pour le mode « historique agrégé »).

Entrées acceptées par ``recurrence_risk`` (paramètre ``history``) :
- une liste d'incidents détaillés (dicts ou objets) avec un type de panne
  (``issue_type`` / ``category`` / ``issue``) et une date (``occurred_at`` /
  ``reported_at`` / ``created_at`` / ``date`` ; ISO, ``date`` ou ``datetime``) ;
- un ``SchoolMaintenanceHistory`` (données agrégées Laravel : pas de détail
  par panne, on applique alors les seuils agrégés cohérents avec la matrice
  Réparer vs Remplacer de :mod:`app.decision_agent`) ;
- un dict ``{"incidents": [...]}``, ``None`` ou ``[]`` (historique vide).

Seuils (constantes nommées ci-dessous) :
- ``RECURRENCE_WINDOW_DAYS = 90`` : fenêtre glissante d'observation. 90 jours
  ≈ un trimestre scolaire : assez long pour capter une récurrence, assez
  court pour rester actionnable avant la prochaine casse.
- ``HIGH_SAME_TYPE_COUNT = 3`` : 3 pannes du même type sur la fenêtre = la
  panne est chronique, la prochaine casse est probable → niveau ``high``.
- ``WATCH_SAME_TYPE_COUNT = 2`` : 2 pannes du même type = premier signal de
  récidive, pas encore une preuve → niveau ``watch`` (surveillance).
- ``MEAN_INTERVAL_ALERT_DAYS = 30`` : intervalle moyen entre pannes inférieur
  à ~1 mois ET en diminution = dégradation accélérée → ``high``, même sans
  atteindre 3 pannes du même type (filet de sécurité inter-types).
- ``AGGREGATE_HIGH_INCIDENT_COUNT = 4`` / ``AGGREGATE_WATCH_INCIDENT_COUNT
  = 2`` / ``AGGREGATE_CRITICAL_DAYS_OFF = 30`` : seuils agrégés repris à
  l'identique de ``decision_agent.evaluate_school_equipment`` (55 %, 4
  pannes, 30 jours sans service) pour que les deux moteurs ne se
  contredisent jamais sur la même école.

Règles de prudence documentées :
- incident sans date : compté dans les occurrences par type (on ne rate pas
  une alerte pour une date manquante) mais exclu du calcul des intervalles ;
- incident futur : exclu (ce n'est pas un antécédent) ;
- incident hors fenêtre (> 90 jours) : ignoré pour l'alerte, signalé dans
  les raisons quand il existe ;
- ex aequo entre types : le type le plus récent l'emporte (panne la plus
  fraîche = risque le plus imminent).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .extractor import ISSUE_TYPE_ALIASES, ISSUE_TYPE_LABELS
from .schemas import SchoolMaintenanceHistory

__all__ = [
    "RECURRENCE_WINDOW_DAYS",
    "HIGH_SAME_TYPE_COUNT",
    "WATCH_SAME_TYPE_COUNT",
    "MEAN_INTERVAL_ALERT_DAYS",
    "AGGREGATE_HIGH_INCIDENT_COUNT",
    "AGGREGATE_WATCH_INCIDENT_COUNT",
    "AGGREGATE_CRITICAL_DAYS_OFF",
    "PREVENTIVE_ACTIONS",
    "recurrence_risk",
    "preventive_plan",
    "watch_recurrence",
]


# ================= Seuils nommés (voir docstring du module) =================

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


#: Fenêtre glissante d'observation en jours (≈ un trimestre scolaire).
#: Override ENV : RECURRENCE_WINDOW_DAYS (défaut historique 90).
RECURRENCE_WINDOW_DAYS = _env_int("RECURRENCE_WINDOW_DAYS", 90)

#: Occurrences d'un même type sur la fenêtre → niveau "high" (panne chronique).
#: Override ENV : RECURRENCE_HIGH_SAME_TYPE_COUNT (défaut historique 3).
HIGH_SAME_TYPE_COUNT = _env_int("RECURRENCE_HIGH_SAME_TYPE_COUNT", 3)

#: Occurrences d'un même type sur la fenêtre → niveau "watch" (vigilance).
#: Override ENV : RECURRENCE_WATCH_SAME_TYPE_COUNT (défaut historique 2).
WATCH_SAME_TYPE_COUNT = _env_int("RECURRENCE_WATCH_SAME_TYPE_COUNT", 2)

#: Intervalle moyen (jours) sous lequel, combiné à une diminution, on alerte.
#: Override ENV : RECURRENCE_MEAN_INTERVAL_ALERT_DAYS (défaut historique 30.0).
MEAN_INTERVAL_ALERT_DAYS = _env_float("RECURRENCE_MEAN_INTERVAL_ALERT_DAYS", 30.0)

#: Historique agrégé : pannes cumulées → "high" (cohérence decision_agent).
#: Override ENV : RECURRENCE_AGGREGATE_HIGH_INCIDENT_COUNT (défaut historique 4).
AGGREGATE_HIGH_INCIDENT_COUNT = _env_int("RECURRENCE_AGGREGATE_HIGH_INCIDENT_COUNT", 4)

#: Historique agrégé : pannes cumulées → "watch" (cohérence decision_agent).
#: Override ENV : RECURRENCE_AGGREGATE_WATCH_INCIDENT_COUNT (défaut historique 2).
AGGREGATE_WATCH_INCIDENT_COUNT = _env_int("RECURRENCE_AGGREGATE_WATCH_INCIDENT_COUNT", 2)

#: Historique agrégé : jours sans service → "high" (cohérence decision_agent).
#: Override ENV : RECURRENCE_AGGREGATE_CRITICAL_DAYS_OFF (défaut historique 30).
AGGREGATE_CRITICAL_DAYS_OFF = _env_int("RECURRENCE_AGGREGATE_CRITICAL_DAYS_OFF", 30)


#: Champs reconnus pour le type de panne (ordre de priorité).
_TYPE_FIELDS = ("issue_type", "category", "issue", "type")

#: Champs reconnus pour la date de panne (ordre de priorité).
_DATE_FIELDS = ("occurred_at", "reported_at", "created_at", "incident_date", "date")

#: Table pannes canonique (LOT 3) : définie UNE SEULE FOIS dans
#: app/extractor.py (ISSUE_TYPE_LABELS / ISSUE_TYPE_ALIASES), importée ici
#: sous les noms historiques privés (mêmes objets, comportement inchangé).
_ISSUE_LABELS = ISSUE_TYPE_LABELS
_ISSUE_ALIASES = ISSUE_TYPE_ALIASES


#: Table interne des actions préventives par type de panne.
#: Valeurs prudentes : gestes à faible coût, pièces courantes, aucune
#: promesse de délai de réparation (seule une urgence est indiquée).
PREVENTIVE_ACTIONS: dict[str, dict[str, Any]] = {
    "leak": {
        "actions": [
            "Inspecter l'ensemble des joints et raccords du point d'eau.",
            "Resserrer ou remplacer les joints toriques usés.",
            "Stocker 2 robinets de rechange et 1 rouleau de téflon à l'école.",
        ],
        "parts_hint": "2 robinets + joints toriques + téflon",
        "suggested_action": (
            "Inspection des joints + stock de 2 robinets avant la prochaine fuite."
        ),
    },
    "total_breakdown": {
        "actions": [
            "Tester la pompe à pleine charge pendant 15 minutes.",
            "Vérifier la crépine, le clapet anti-retour et la tringlerie.",
            "Prévoir un point d'eau de secours (citerne ou forage voisin).",
        ],
        "parts_hint": "kit crépine + clapet anti-retour + graisse",
        "suggested_action": (
            "Test de la pompe à pleine charge + vérification crépine et clapet."
        ),
    },
    "contamination": {
        "actions": [
            "Chloration préventive du point d'eau, puis contrôle après 30 minutes.",
            "Nettoyer et désinfecter les abords dans un rayon de 10 mètres.",
            "Informer l'école : faire bouillir l'eau en cas de doute.",
        ],
        "parts_hint": "chlore ou pastilles de traitement de l'eau",
        "suggested_action": (
            "Chloration préventive + consigne d'ébullition en cas de doute."
        ),
    },
    "blockage": {
        "actions": [
            "Curage préventif des canalisations et des regards.",
            "Vider les fosses si le niveau dépasse les 2/3.",
            "Sensibiliser les élèves : rien à jeter dans les latrines.",
        ],
        "parts_hint": "furet + seau + gants + pelle",
        "suggested_action": "Curage préventif + sensibilisation des élèves.",
    },
    "dry_well": {
        "actions": [
            "Mesurer le niveau d'eau du puits (baisse par rapport au mois dernier ?).",
            "Réduire le débit de pompage et espacer les puisages.",
            "Identifier un point d'eau de secours dans un rayon de 2 km.",
        ],
        "parts_hint": "corde + poids (sonde) + bidons de stockage",
        "suggested_action": "Mesure du niveau du puits + point d'eau de secours.",
    },
    "vandalism": {
        "actions": [
            "Poser ou réparer la clôture et le cadenas du point d'eau.",
            "Créer un comité de garde scolaire avec un responsable désigné.",
            "Informer les autorités locales en cas de récidive.",
        ],
        "parts_hint": "cadenas + chaîne + grillage",
        "suggested_action": "Sécurisation du point d'eau (clôture + cadenas).",
    },
    "other": {
        "actions": [
            "Inspection visuelle complète de l'infrastructure.",
            "Interroger le comité de gestion sur les signes avant-coureurs.",
            "Consigner les observations dans le cahier de maintenance.",
        ],
        "parts_hint": "kit de maintenance courante",
        "suggested_action": "Inspection visuelle complète + cahier de maintenance.",
    },
}


# ============================ Utilitaires internes ============================

def _get_field(obj: Any, names: tuple[str, ...]) -> Any:
    """Lit le premier champ disponible sur un dict ou un objet."""
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return None


def _normalize_issue(raw: Any) -> str:
    """Normalise un type de panne vers un code canonique (inconnu → "other")."""
    if not isinstance(raw, str):
        return "other"
    key = raw.strip().lower().replace("é", "e").replace("è", "e")
    return _ISSUE_ALIASES.get(key, "other")


def _coerce_date(value: Any) -> date | None:
    """Convertit ISO / date / datetime / timestamp epoch → date (None sinon)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def _as_incident_list(history: Any) -> list[Any]:
    """Ramène toutes les formes d'historique détaillé à une liste d'incidents."""
    if history is None:
        return []
    if isinstance(history, SchoolMaintenanceHistory):
        return []
    if isinstance(history, dict):
        if "incidents" in history:
            nested = history["incidents"]
            return list(nested) if isinstance(nested, (list, tuple)) else []
        # Un dict incident isolé (avec type ou date) = un seul incident.
        keys = set(history.keys())
        if keys & set(_TYPE_FIELDS + _DATE_FIELDS):
            return [history]
        return []
    if isinstance(history, (list, tuple)):
        return list(history)
    return []


def _split_window(
    incidents: list[Any], today: date
) -> tuple[dict[str, list[date | None]], dict[str, list[date]], int]:
    """Trie les incidents : par type (fenêtre + sans date), datés triés, hors-fenêtre.

    Retourne (counts_par_type, datés_triés_par_type, nb_hors_fenêtre).
    Les dates futures sont exclues : ce ne sont pas des antécédents.
    """
    cutoff = today - timedelta(days=RECURRENCE_WINDOW_DAYS)
    counts: dict[str, list[date | None]] = {}
    dated: dict[str, list[date]] = {}
    outdated = 0
    for incident in incidents:
        issue = _normalize_issue(_get_field(incident, _TYPE_FIELDS))
        event = _coerce_date(_get_field(incident, _DATE_FIELDS))
        if event is not None and event > today:
            continue  # date future : pas un antécédent, on l'ignore
        if event is None:
            counts.setdefault(issue, []).append(None)  # prudent : compté
            continue
        if event < cutoff:
            outdated += 1
            continue
        counts.setdefault(issue, []).append(event)
        dated.setdefault(issue, []).append(event)
    for dates in dated.values():
        dates.sort()
    return counts, dated, outdated


def _intervals_days(dates: list[date]) -> list[int]:
    """Intervalles en jours entre pannes consécutives (ordre chronologique)."""
    return [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]


def _is_shrinking(intervals: list[int]) -> bool:
    """Vrai si les intervalles récents sont en moyenne plus courts qu'avant."""
    if len(intervals) < 2:
        return False
    mid = len(intervals) // 2
    older = intervals[:mid]
    recent = intervals[mid:]
    return (sum(recent) / len(recent)) < (sum(older) / len(older))


def _fmt_mean(value: float) -> str:
    """Formate une moyenne au format français (virgule décimale)."""
    return f"{value:.1f}".replace(".", ",")


def _dominant_issue(
    counts: dict[str, list[date | None]], dated: dict[str, list[date]]
) -> str | None:
    """Type dominant : occurrences max, ex aequo → le plus récent."""
    if not counts:
        return None

    def sort_key(issue: str) -> tuple[int, date]:
        last = max((d for d in (dated.get(issue) or []) if d), default=date.min)
        return (len(counts[issue]), last)

    return max(counts, key=sort_key)


# ============================ Fonctions publiques ============================

def recurrence_risk(history: Any = None, now: Any = None) -> dict[str, Any]:
    """Évalue le risque de récidive AVANT la prochaine casse.

    ``history`` : liste d'incidents détaillés, ``SchoolMaintenanceHistory``,
    dict ``{"incidents": [...]}``, ``None`` ou ``[]``. ``now`` : date de
    référence (défaut : aujourd'hui) ; le passer rend l'appel strictement
    déterministe. Ne mute jamais son entrée et ne lève jamais sur des
    données incomplètes : à défaut de signal, le niveau est ``"none"``.
    """
    today = _coerce_date(now) or date.today()

    if isinstance(history, SchoolMaintenanceHistory):
        return _risk_from_aggregate(history)

    incidents = _as_incident_list(history)
    if not incidents:
        return {
            "level": "none",
            "reasons": [
                "Historique vide : aucun antécédent de panne, "
                "aucune récurrence détectable."
            ],
        }

    counts, dated, outdated = _split_window(incidents, today)
    dominant = _dominant_issue(counts, dated)
    in_window = sum(len(v) for v in counts.values())

    high_reasons: list[str] = []
    watch_reasons: list[str] = []

    # Règle 1 : N pannes du même type sur la fenêtre.
    for issue in sorted(counts, key=lambda i: (-len(counts[i]), i)):
        n = len(counts[issue])
        label = _ISSUE_LABELS[issue]
        if n >= HIGH_SAME_TYPE_COUNT:
            high_reasons.append(
                f"{n} {label} en {RECURRENCE_WINDOW_DAYS} jours "
                f"(seuil d'alerte : {HIGH_SAME_TYPE_COUNT}) : prochaine casse "
                f"probable de type « {issue} », intervention préventive recommandée."
            )
        elif n >= WATCH_SAME_TYPE_COUNT:
            watch_reasons.append(
                f"{n} {label} en {RECURRENCE_WINDOW_DAYS} jours "
                f"(seuil de vigilance : {WATCH_SAME_TYPE_COUNT}) : risque de "
                "récidive, surveillance renforcée."
            )

    # Règle 2a : intervalles qui se resserrent pour un même type.
    for issue in sorted(dated):
        dates = dated[issue]
        if len(dates) < HIGH_SAME_TYPE_COUNT:
            continue
        gaps = _intervals_days(dates)
        mean_gap = sum(gaps) / len(gaps)
        if mean_gap < MEAN_INTERVAL_ALERT_DAYS and _is_shrinking(gaps):
            high_reasons.append(
                f"Intervalle moyen de {_fmt_mean(mean_gap)} jours entre les "
                f"{len(dates)} dernières {_ISSUE_LABELS[issue]} "
                f"(< {int(MEAN_INTERVAL_ALERT_DAYS)} jours) et en diminution "
                f"(de {gaps[0]} j à {gaps[-1]} j) : dégradation accélérée."
            )

    # Règle 2b : filet inter-types (tous types confondus).
    all_dates = sorted(d for dates in dated.values() for d in dates)
    if len(all_dates) >= HIGH_SAME_TYPE_COUNT:
        gaps = _intervals_days(all_dates)
        mean_gap = sum(gaps) / len(gaps)
        if mean_gap < MEAN_INTERVAL_ALERT_DAYS and _is_shrinking(gaps):
            high_reasons.append(
                f"Intervalle moyen de {_fmt_mean(mean_gap)} jours entre les "
                f"{len(all_dates)} dernières pannes tous types confondus "
                f"(< {int(MEAN_INTERVAL_ALERT_DAYS)} jours) et en diminution "
                f"(de {gaps[0]} j à {gaps[-1]} j) : l'équipement se dégrade "
                "de plus en plus vite."
            )

    if high_reasons:
        risk: dict[str, Any] = {"level": "high", "reasons": high_reasons}
    elif watch_reasons:
        risk = {"level": "watch", "reasons": watch_reasons}
    else:
        best = max((len(v) for v in counts.values()), default=0)
        reasons = [
            f"Aucun signal de récurrence : {in_window} panne(s) sur les "
            f"{RECURRENCE_WINDOW_DAYS} derniers jours, au maximum {best} pour "
            f"un même type (seuils : vigilance à {WATCH_SAME_TYPE_COUNT}, "
            f"alerte à {HIGH_SAME_TYPE_COUNT})."
        ]
        if len(all_dates) >= 2:
            gaps = _intervals_days(all_dates)
            mean_gap = sum(gaps) / len(gaps)
            if mean_gap >= MEAN_INTERVAL_ALERT_DAYS:
                reasons.append(
                    f"Intervalle moyen de {_fmt_mean(mean_gap)} jours entre les "
                    f"pannes (≥ {int(MEAN_INTERVAL_ALERT_DAYS)} jours) : "
                    "rythme stable, pas d'accélération."
                )
            elif not _is_shrinking(gaps):
                reasons.append(
                    f"Intervalle moyen de {_fmt_mean(mean_gap)} jours "
                    f"(< {int(MEAN_INTERVAL_ALERT_DAYS)} jours) mais pas en "
                    "diminution : pas d'accélération avérée."
                )
        elif in_window:
            reasons.append(
                "Pas assez d'antécédents datés pour mesurer une accélération "
                f"(minimum {HIGH_SAME_TYPE_COUNT} pannes datées)."
            )
        if outdated:
            reasons.append(
                f"{outdated} panne(s) plus ancienne(s) que "
                f"{RECURRENCE_WINDOW_DAYS} jours ignorée(s) (hors fenêtre)."
            )
        return {"level": "none", "reasons": reasons}

    if dominant:
        risk["predicted_issue"] = dominant
        risk["suggested_action"] = PREVENTIVE_ACTIONS[dominant]["suggested_action"]
    return risk


def _risk_from_aggregate(school: SchoolMaintenanceHistory) -> dict[str, Any]:
    """Risque depuis un historique agrégé (seuils repris de decision_agent)."""
    name = school.school_name
    generic_action = (
        "Collecter l'historique détaillé (type + dates de chaque panne) "
        "pour cibler la prévention."
    )
    if (
        school.incident_count >= AGGREGATE_HIGH_INCIDENT_COUNT
        or school.total_days_without_service >= AGGREGATE_CRITICAL_DAYS_OFF
    ):
        reasons = [
            f"{school.incident_count} pannes cumulées à {name} "
            f"(seuil critique : {AGGREGATE_HIGH_INCIDENT_COUNT}, cohérent avec "
            "la matrice Réparer vs Remplacer) : équipement à bout de souffle, "
            "remplacement à étudier."
        ]
        if school.total_days_without_service >= AGGREGATE_CRITICAL_DAYS_OFF:
            reasons.append(
                f"{school.total_days_without_service} jours cumulés sans service "
                f"(seuil critique : {AGGREGATE_CRITICAL_DAYS_OFF} jours) : "
                "continuité d'eau non assurée."
            )
        return {
            "level": "high",
            "reasons": reasons,
            "suggested_action": generic_action,
        }
    if school.incident_count >= AGGREGATE_WATCH_INCIDENT_COUNT:
        return {
            "level": "watch",
            "reasons": [
                f"{school.incident_count} pannes cumulées à {name} "
                f"(seuil de vigilance : {AGGREGATE_WATCH_INCIDENT_COUNT}) : "
                "usure précoce possible, surveillance renforcée."
            ],
            "suggested_action": generic_action,
        }
    return {
        "level": "none",
        "reasons": [
            f"Équipement fiable à {name} : {school.incident_count} panne(s) "
            f"cumulée(s), {school.total_days_without_service} jour(s) sans "
            f"service (sous les seuils {AGGREGATE_WATCH_INCIDENT_COUNT}/"
            f"{AGGREGATE_HIGH_INCIDENT_COUNT} pannes et "
            f"{AGGREGATE_CRITICAL_DAYS_OFF} jours)."
        ],
    }


def preventive_plan(risk: dict[str, Any] | None, history: Any = None) -> dict[str, Any]:
    """Construit le plan préventif correspondant au risque détecté.

    ``risk`` : dict retourné par :func:`recurrence_risk` (seuls ``level`` et
    ``predicted_issue`` sont lus). ``history`` : utilisé en repli pour
    retrouver le type dominant si ``predicted_issue`` est absent.
    """
    level = risk.get("level", "none") if isinstance(risk, dict) else "none"
    if level not in ("none", "watch", "high"):
        level = "none"
    issue = risk.get("predicted_issue") if isinstance(risk, dict) else None
    if issue not in PREVENTIVE_ACTIONS:
        counts, dated, _ = _split_window(_as_incident_list(history), date.today())
        issue = _dominant_issue(counts, dated) or "other"
    entry = PREVENTIVE_ACTIONS[issue]

    if level == "none":
        return {
            "actions": [
                "Poursuivre la maintenance courante : graissage, vérification "
                "visuelle mensuelle, cahier de maintenance à jour."
            ],
            "urgency": "low",
        }
    actions = list(entry["actions"])
    if level == "high":
        actions.append("Planifier l'intervention préventive sous 7 jours.")
    else:
        actions.append("Ajouter l'école à la tournée d'inspection du mois.")
    urgency = {"watch": "medium", "high": "high"}[level]
    if level == "high" and issue == "contamination":
        urgency = "critical"  # risque sanitaire : prudence maximale
    return {
        "actions": actions,
        "parts_hint": entry["parts_hint"],
        "urgency": urgency,
    }


def watch_recurrence(history: Any = None, now: Any = None) -> dict[str, Any]:
    """Enchaîne risque + plan : entrée directe pour POST /v1/wash/recurrence-watch."""
    risk = recurrence_risk(history, now)
    return {"risk": risk, "plan": preventive_plan(risk, history)}
