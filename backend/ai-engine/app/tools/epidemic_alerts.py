"""Plugin : alertes épidémiques — détection de CLUSTERS sanitaires multi-écoles.

Un cluster = au moins 2 écoles DISTINCTES du même district avec des signaux
sanitaires (contamination, choléra, eau souillée/jaune, latrines débordées)
sur la fenêtre demandée. Logique maison à mots-clés, déterministe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..schemas import AgentCard
from ..textnorm import (
    HEALTH_SIGNALS,
    dedup_incidents,
    district_match,
    find_keyword_spans,
    fold,
    is_negated,
    negation_spans,
    parse_dt,
)

TOOL_NAME = "epidemic_alerts"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Détecte les CLUSTERS sanitaires multi-écoles : au moins 2 écoles "
        "distinctes du même district avec des signaux sanitaires "
        "(contamination, choléra, eau souillée ou jaune, latrines débordées) "
        "sur la fenêtre demandée (défaut 7 jours). À utiliser quand "
        "l'utilisateur demande s'il y a un risque d'épidémie, de choléra, de "
        "contamination ou une alerte sanitaire dans un district. "
        "Exemple : « Y a-t-il un risque d'épidémie à Douala ? » -> "
        "epidemic_alerts avec district=Douala. "
        "Ne JAMAIS utiliser pour un incident isolé d'une seule école "
        "(utiliser explain_incident), ni pour créer un signalement "
        "(outils prepare_*)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "district": {
                "type": "string",
                "description": "District à analyser (optionnel, sinon tous les districts)",
            },
            "days": {
                "type": "integer",
                "description": "Fenêtre en jours (défaut 7, 1 à 90)",
                "default": 7,
            },
        },
    },
}

READ_ONLY = True

# Indices minuscules, formes sans accent doublées. Vérifié : aucun n'est
# sous-chaîne d'un phrasé legacy (tests/test_prompt_eval.py, capacités).
INTENT_HINTS = frozenset({
    "épidémie", "epidemie",
    "épidémique", "epidemique",
    "choléra", "cholera",
    "contamination",
    "sanitaire",
    "cluster",
    "alerte sanitaire",
    "risque sanitaire", "risque épidémique", "risque epidemique",
    "cas groupés", "cas groupes",
    "flambée", "flambee",
    "diarrhée", "diarrhee",
    "propagation",
    "malades",
})

# Seuil multi-écoles : en dessous, incident(s) isolé(s), pas de cluster.
CLUSTER_MIN_SCHOOLS = 2

#: Libellés d'affichage des tiges sanitaires (table partagée HEALTH_SIGNALS).
_SIGNAL_LABELS = {
    "diarrh": "diarrhée",
    "cholera": "choléra",
    "vomiss": "vomissements",
    "vomit": "vomissements",
    "dysenteri": "dysenterie",
    "contamin": "contamination",
    "eau jaune": "eau jaune",
    "jaune": "eau jaune",
    "jaunatre": "eau jaunâtre",
    "debord": "débordement",
    "souille": "eau souillée",
    "epidemi": "épidémie",
    "fecal": "matières fécales",
    "trouble": "eau trouble",
    "odeur": "odeur",
    "gout": "goût",
    "ventre": "maux de ventre",
    "nause": "nausées",
    "dirty water": "eau sale",
    "running stomach": "diarrhée",
    "dirty wata": "eau sale",
    "wata don dirty": "eau sale",
}


def _incident_district(incident: dict[str, Any],
                       schools_by_id: dict[Any, dict[str, Any]]) -> str:
    district = str(incident.get("district") or "").strip()
    if district:
        return district
    school = schools_by_id.get(incident.get("school_id"))
    if isinstance(school, dict):
        return str(school.get("district") or "").strip()
    return ""


def _school_key(incident: dict[str, Any]) -> str:
    if incident.get("school_id") is not None:
        return f"id:{incident.get('school_id')}"
    name = fold(incident.get("school_name")).strip()
    if name:
        return f"name:{name}"
    return "unknown"  # prudent : écoles inconnues = un seul bucket


def _school_label(incident: dict[str, Any]) -> str:
    name = str(incident.get("school_name") or "").strip()
    if name:
        return name
    if incident.get("school_id") is not None:
        return f"École #{incident.get('school_id')}"
    return "École inconnue"


def _signal_keywords(incident: dict[str, Any]) -> list[str]:
    """Tiges sanitaires matchées hors négation (table partagée)."""
    text = fold(f"{incident.get('title') or ''} "
                f"{incident.get('summary') or ''}")
    spans = negation_spans(text)
    matched: list[str] = []
    for pattern, _strength, boundary, negatable in HEALTH_SIGNALS:
        hits = find_keyword_spans(text, pattern, boundary)
        if not hits:
            continue
        if negatable and all(is_negated(s, e, spans) for s, e in hits):
            continue
        matched.append(pattern)
    if fold(incident.get("issue_type")).strip() == "contamination":
        if "contamin" not in matched:
            matched.append("contamin")
    return matched


def _signal_labels(patterns: list[str] | set[str]) -> list[str]:
    return sorted({_SIGNAL_LABELS.get(p, p) for p in patterns})


def _cluster_risk(school_count: int, signals: set[str]) -> str:
    if "cholera" in signals or "diarrh" in signals:
        return "outbreak_warning"
    if school_count >= 3:
        return "high"
    return "moderate"


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Détecte les clusters sanitaires multi-écoles (déterministe, offline)."""
    try:
        args = args if isinstance(args, dict) else {}
        context = context if isinstance(context, dict) else {}
        try:
            days = int(args.get("days", 7) or 7)
        except (TypeError, ValueError):
            days = 7
        days = min(max(days, 1), 90)
        district_arg = args.get("district")
        district_label = str(district_arg or "").strip() or None
        if (context.get("incidents") is None
                and context.get("recent_incidents") is None):
            # Cas "unknown" : clés manquantes -> erreur (guidance). Des listes
            # présentes mais vides sont un vide valide -> carte typée vide.
            return {"error": (
                "Aucune donnée d'incident disponible pour détecter "
                "un cluster sanitaire."
            ), "days": days}

        schools_by_id: dict[Any, dict[str, Any]] = {}
        for school in context.get("schools", []) or []:
            if isinstance(school, dict) and school.get("school_id") is not None:
                schools_by_id[school.get("school_id")] = school

        pool = dedup_incidents(context.get("incidents"),
                               context.get("recent_incidents"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Incidents sanitaires dans la fenêtre (sans date = conservé, prudent).
        signals: list[dict[str, Any]] = []
        for incident in pool:
            seen_at = parse_dt(incident.get("reported_at")
                               or incident.get("created_at"))
            if seen_at is not None and seen_at < cutoff:
                continue
            district = _incident_district(incident, schools_by_id)
            if not district_match(district, district_arg):
                continue
            matched = _signal_keywords(incident)
            if matched:
                signals.append({"incident": incident, "district": district,
                                "matched": matched})

        # Regroupement par district, cluster si >= 2 écoles distinctes.
        by_district: dict[str, list[dict[str, Any]]] = {}
        for entry in signals:
            key = fold(entry["district"]) or "unknown"
            by_district.setdefault(key, []).append(entry)

        clusters: list[dict[str, Any]] = []
        for key in sorted(by_district):
            entries = by_district[key]
            schools = sorted({_school_key(e["incident"]) for e in entries})
            if len(schools) < CLUSTER_MIN_SCHOOLS:
                continue
            sig_words: set[str] = set()
            for e in entries:
                sig_words.update(e["matched"])
            sig_labels = _signal_labels(sig_words)
            display = entries[0]["district"] or "District inconnu"
            labels = sorted({_school_label(e["incident"]) for e in entries})
            clusters.append({
                "district": display,
                "risk_level": _cluster_risk(len(schools), sig_words),
                "schools": labels,
                "school_count": len(schools),
                "incident_count": len(entries),
                "signals": sig_labels,
                "incidents": [{
                    "id": e["incident"].get("id"),
                    "school_name": _school_label(e["incident"]),
                    "title": (e["incident"].get("title")
                             or e["incident"].get("summary")),
                    "reported_at": (e["incident"].get("reported_at")
                                    or e["incident"].get("created_at")),
                } for e in entries],
            })

        if not clusters:
            # Vide valide -> carte typée vide (pas d'erreur) : l'état vide
            # frontend devient atteignable (politique AXE 7 / P1b).
            scope = f" à {district_label}" if district_label else ""
            return {
                "insight": (
                    f"Aucun cluster sanitaire détecté{scope} sur les {days} "
                    f"derniers jours ({len(signals)} signal(aux) isolé(s), "
                    "pas de regroupement multi-écoles)."
                ),
                "clusters": [],
                "district": district_label,
                "days": days,
                "signals_count": len(signals),
                "signals_isolated": len(signals),
            }

        total_schools = sum(c["school_count"] for c in clusters)
        parts = [f"{c['district']} ({c['school_count']} écoles, "
                 f"{c['incident_count']} signaux)" for c in clusters]
        return {
            "insight": (
                f"Alerte sanitaire : {len(clusters)} cluster(s) détecté(s) "
                f"({total_schools} écoles, {len(signals)} signaux sur "
                f"{days} jours) : " + "; ".join(parts) + "."
            ),
            "clusters": clusters,
            "district": district_label,
            "days": days,
            "signals_count": len(signals),
        }
    except Exception as exc:
        return {"error": f"epidemic_alerts : {exc}"}


def _build_epidemic_alerts_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict) or obs.get("error"):
        return None
    clusters = obs.get("clusters")
    if not isinstance(clusters, list):
        return None
    district = obs.get("district")
    scope = f" — {district}" if district else ""
    if not clusters:
        return AgentCard(
            type="epidemic_alerts",
            title=f"Aucun foyer sanitaire détecté{scope}",
            data=obs,
        )
    schools = sum(len(c.get("schools", [])) for c in clusters
                  if isinstance(c, dict))
    return AgentCard(
        type="epidemic_alerts",
        title=f"Alerte sanitaire — {len(clusters)} cluster(s), {schools} écoles",
        data=obs,
    )


CARD_BUILDERS = {"epidemic_alerts": _build_epidemic_alerts_card}
