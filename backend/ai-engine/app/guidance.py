"""Cartes de guidage : chaque erreur d'outil devient une aide simple.

Chantier 1/9 — JAMAIS de vide : quand un outil retourne {"error": ...},
build_guidance_card() construit une carte AgentCard(type="guidance") qui dit
ce qui s'est passé avec des mots simples et propose des questions cliquables.

Ton : francais parle, phrases courtes, zero jargon (lu a voix haute).
"""
from __future__ import annotations

import unicodedata
from typing import Any

from app.schemas import AgentCard

# Familles d'erreur detectees dans les retours {"error": ...} des outils.
FAMILY_LIEU = "lieu_inconnu"
FAMILY_PERIODE = "periode_vide"
FAMILY_DONNEES = "donnees_absentes"
FAMILY_PARAMETRE = "parametre_manquant"
FAMILY_FILE = "file_inconnue"
FAMILY_DEFAUT = "defaut"

DISTRICT_EXAMPLES = "Mvila, Wouri, Yaoundé, Douala"

# Outils qui raisonnent par district : on enrichit la carte d'exemples.
_DISTRICT_TOOLS = frozenset({
    "district_alerts",
    "epidemic_alerts",
    "summarize_district",
    "observatoire",
    "relances_proactives",
    "document_briefing",
    "rank_schools_by_need",
})

# Outils qui raisonnent par ecole : on propose la liste des ecoles.
_SCHOOL_TOOLS = frozenset({
    "analyze_school",
    "compare_schools",
    "explain_incident",
    "summarize_district",
    "build_briefing",
    "prepare_report",
    "prepare_incident",
    "document_briefing",
})

_ACTION_DISTRICTS = {"label": "Voir tous les districts",
                     "question": "Quels districts sont suivis ?"}
_ACTION_SCHOOLS = {"label": "Voir les écoles suivies",
                   "question": "Quelles écoles sont suivies ?"}
_ACTION_RECENT = {"label": "Voir les derniers faits",
                  "question": "Quels sont les derniers incidents signalés ?"}
_ACTION_PERIOD = {"label": "Voir une période plus longue",
                  "question": "Et sur les 90 derniers jours ?"}

# Un modele par famille : titre simple, explication courte, 2-3 causes,
# au moins 2 actions {label, question}.
_FAMILY_GUIDANCE: dict[str, dict[str, Any]] = {
    FAMILY_LIEU: {
        "title": "On ne trouve pas ce lieu",
        "insight": "Le nom donné ne correspond à aucun lieu suivi.",
        "explication": ("Vérifiez le nom lettre par lettre. "
                        "Un accent ou une faute suffit à bloquer la recherche."),
        "causes": [
            "Le nom est mal écrit.",
            "Ce lieu n'est pas encore suivi.",
            "Vous cherchez une école avec un nom de quartier.",
        ],
        "actions": [_ACTION_SCHOOLS, _ACTION_DISTRICTS],
    },
    FAMILY_PERIODE: {
        "title": "Rien sur cette période",
        "insight": "Aucun fait à signaler sur les jours demandés.",
        "explication": ("La recherche a marché. Il n'y a juste rien à montrer "
                        "sur cette période. C'est souvent une bonne nouvelle."),
        "causes": [
            "La période est trop courte.",
            "Il ne s'est vraiment rien passé.",
            "Les faits sont plus anciens.",
        ],
        "actions": [_ACTION_PERIOD, _ACTION_RECENT],
    },
    FAMILY_DONNEES: {
        "title": "Pas de données pour le moment",
        "insight": "Les infos ne sont pas encore arrivées.",
        "explication": ("La liste des écoles et des pannes est vide ou pas encore "
                        "envoyée. Sans ces infos, on ne peut rien calculer."),
        "causes": [
            "Les données ne sont pas encore envoyées.",
            "La connexion a coupé l'envoi.",
            "Le filtre choisi ne garde rien.",
        ],
        "actions": [_ACTION_SCHOOLS, _ACTION_RECENT],
    },
    FAMILY_PARAMETRE: {
        "title": "Il manque une info",
        "insight": "La question n'est pas assez précise.",
        "explication": ("Dites-moi au moins un nom d'école ou de district, "
                        "et ce que vous voulez savoir."),
        "causes": [
            "Le nom de l'école manque.",
            "Le nom du district manque.",
            "La question est trop vague.",
        ],
        "actions": [_ACTION_SCHOOLS, _ACTION_DISTRICTS],
    },
    FAMILY_FILE: {
        "title": "File d'attente introuvable",
        "insight": "On ne retrouve pas les messages en attente.",
        "explication": ("Les messages gardés sans connexion ne sont pas visibles ici. "
                        "Ils sont peut-être déjà partis, "
                        "ou gardés sur un autre appareil."),
        "causes": [
            "Les messages sont déjà partis.",
            "Ils sont gardés sur un autre appareil.",
            "La liste n'est pas encore chargée.",
        ],
        "actions": [
            {"label": "Vérifier la connexion",
             "question": "La connexion est-elle revenue ? Que dois-je faire ?"},
            _ACTION_RECENT,
        ],
    },
    FAMILY_DEFAUT: {
        "title": "Ça n'a pas marché",
        "insight": "La recherche a eu un problème.",
        "explication": ("Quelque chose a bloqué de notre côté. "
                        "Réessayez avec une question simple, "
                        "comme un nom d'école."),
        "causes": [
            "Un problème passager du service.",
            "La question mélange deux demandes.",
            "Une info attendue manque.",
        ],
        "actions": [
            {"label": "Reposer une question simple",
             "question": "Quelles écoles sont suivies ?"},
            _ACTION_RECENT,
        ],
    },
}


def _norm(text: str) -> str:
    """Minuscules sans accents pour comparer les messages d'erreur."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return folded.lower()


def _has(text: str, *keywords: str) -> bool:
    return any(kw in text for kw in keywords)


def _detect_family(tool_name: str, error_text: str) -> str:
    """Classe le message d'erreur dans une famille de guidage."""
    err = _norm(error_text)
    # 1. Parametre manquant : indices explicites ("precisez", "au moins"...).
    if _has(err, "manquant", "manquante", "precisez", "au moins", "parametre"):
        return FAMILY_PARAMETRE
    # 2. File hors-ligne inconnue.
    if _has(err, "file", "hors", "offline", "queue", "sync"):
        return FAMILY_FILE
    # 3. Lieu inconnu (ecole / district / reference introuvable).
    #    "outil inconnu" est une panne systeme, pas un lieu : defaut.
    if "outil inconnu" in err or "unknown tool" in err:
        return FAMILY_DEFAUT
    if _has(err, "introuvable", "inconnu", "inconnue", "district",
            "ecole", "school", "choix", "valides", "reconnu", "reconnue"):
        return FAMILY_LIEU
    # 4. Donnees absentes (contexte vide, service indisponible).
    if _has(err, "donnee", "disponible", "indisponible", "contexte", "vide"):
        return FAMILY_DONNEES
    # 5. Parametre invalide (formulation vague, sans contexte).
    if _has(err, "arguments", "invalide"):
        return FAMILY_PARAMETRE
    # 6. Periode vide (recherche OK mais aucun resultat).
    if _has(err, "aucun", "aucune", "periode", "jours", "dormant",
            "cluster", "alerte", "0 ", "neant"):
        return FAMILY_PERIODE
    return FAMILY_DEFAUT


def _ensure_action(actions: list[dict[str, str]], action: dict[str, str],
                   first: bool = False) -> None:
    """Ajoute l'action si son label n'est pas deja propose."""
    if any(a.get("label") == action["label"] for a in actions):
        return
    if first:
        actions.insert(0, dict(action))
    else:
        actions.append(dict(action))


def _apply_tool_hints(tool_name: str, family: str, error_text: str,
                      title: str, explication: str,
                      actions: list[dict[str, str]]
                      ) -> tuple[str, str, list[dict[str, str]]]:
    """Enrichit la carte selon l'outil appele (mapping par outil)."""
    err = _norm(error_text)
    if tool_name in _DISTRICT_TOOLS:
        # District inexistant : guider vers un nom valide.
        if family == FAMILY_LIEU or _has(err, "district"):
            explication = (f"Vérifiez le nom : {DISTRICT_EXAMPLES}… "
                           + explication)
        _ensure_action(actions, _ACTION_DISTRICTS, first=True)
    if tool_name in _SCHOOL_TOOLS:
        _ensure_action(actions, _ACTION_SCHOOLS, first=(family == FAMILY_LIEU))
    return title, explication, actions


def build_guidance_card(tool_name: str, observation: dict) -> AgentCard | None:
    """Construit une carte de guidage depuis une observation en erreur.

    Retourne None si l'observation ne contient pas d'erreur.
    Ne leve jamais : en cas de doute, retourne la carte generique-utile
    (jamais de vide).
    """
    try:
        if not isinstance(observation, dict):
            return None
        raw_error = observation.get("error")
        if not raw_error:
            return None
        error_text = str(raw_error)
        name = str(tool_name or "")
        family = _detect_family(name, error_text)
        template = _FAMILY_GUIDANCE[family]
        title = str(template["title"])
        insight = str(template["insight"])
        explication = str(template["explication"])
        causes = [str(c) for c in template["causes"]]
        actions = [dict(a) for a in template["actions"]]
        title, explication, actions = _apply_tool_hints(
            name, family, error_text, title, explication, actions)
        return AgentCard(
            type="guidance",
            title=title,
            data={
                "insight": insight,
                "explication": explication,
                "causes_possibles": causes,
                "actions": actions,
            },
        )
    except Exception:
        fallback = _FAMILY_GUIDANCE[FAMILY_DEFAUT]
        return AgentCard(
            type="guidance",
            title=str(fallback["title"]),
            data={
                "insight": str(fallback["insight"]),
                "explication": str(fallback["explication"]),
                "causes_possibles": [str(c) for c in fallback["causes"]],
                "actions": [dict(a) for a in fallback["actions"]],
            },
        )
