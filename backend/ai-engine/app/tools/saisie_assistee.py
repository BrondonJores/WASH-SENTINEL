"""Plugin outil : saisie assistée pas à pas d'un signalement.

Guide un usager (même illettré, via questions lues à voix haute) pour
remplir un signalement : UNE question à la fois avec options cliquables,
progression suivie. Machine à états fixe : ecole -> probleme -> urgence
-> recap. Lecture seule, déterministe, sans réseau ni LLM.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from ..schemas import AgentCard

TOOL_NAME = "saisie_assistee"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Guide pas à pas un usager (même illettré, via questions vocales ou "
        "lues) pour remplir un signalement : école, problème, urgence, puis "
        "récapitulatif. Pose UNE seule question à la fois avec des options "
        "cliquables et suit la progression. À utiliser quand l'utilisateur "
        "demande de l'aide pour remplir ou signaler étape par étape "
        "('aide-moi à remplir', 'guide-moi', 'je veux signaler'). "
        "Exemple : 'Aide-moi à remplir un signalement' -> saisie_assistee({}). "
        "Ne JAMAIS utiliser pour créer directement un signalement "
        "(prepare_report), lister des données existantes, ni répondre à une "
        "question de données (écoles, incidents, tendances)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "etape": {
                "type": "string",
                "enum": ["ecole", "probleme", "urgence", "recap"],
                "description": "Étape en cours (absente = démarrer à 'ecole')",
            },
            "reponse": {
                "type": "string",
                "description": "Réponse de l'usager à l'étape en cours",
            },
        },
    },
}

READ_ONLY = True

INTENT_HINTS = frozenset({
    "aide-moi à remplir", "aide-moi a remplir",
    "aide moi à remplir", "aide moi a remplir",
    "aide-moi à signaler", "aide moi a signaler",
    "je veux signaler", "je souhaite signaler", "je voudrais signaler",
    "comment signaler", "comment faire un signalement",
    "formulaire", "formulaire de signalement",
    "pas à pas", "pas a pas",
    "étape par étape", "etape par etape",
    "guide-moi", "guide moi", "guidez-moi", "guidez moi",
    "guide-moi pour signaler", "guide moi pour signaler",
    "remplir un signalement", "remplir le formulaire",
})

PROBLEMES = (
    "Fuite d'eau",
    "Latrines bouchées",
    "Forage à sec / pas d'eau",
    "Eau sale ou contaminée",
    "Pompe cassée",
    "Autre problème",
)

URGENCES = ("Basse", "Moyenne", "Haute", "Critique")

PROGRESS = {"ecole": 0, "probleme": 33, "urgence": 66, "recap": 100}

_ECole_Q = "Dans quelle école y a-t-il un problème ? Touchez le nom de l'école."
_PROBLEME_Q = "Quel est le problème ? Touchez une réponse."
_URGENCE_Q = "C'est urgent comment ? Touchez une réponse."

_MAX_ECOLE_OPTIONS = 6


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _norm(value: Any) -> str:
    return _strip_accents(str(value or "").strip().lower())


def _school_names(context: dict[str, Any]) -> list[str]:
    names: list[str] = []
    schools = context.get("schools") if isinstance(context, dict) else None
    if not isinstance(schools, list):
        return names
    for school in schools:
        if not isinstance(school, dict):
            continue
        name = school.get("school_name") or school.get("name")
        if name and str(name).strip() and str(name) not in names:
            names.append(str(name))
    return names


def _match_school(reponse: str, names: list[str]) -> str | None:
    """Résolution floue par sous-chaîne normalisée (l'id exact est géré par l'appelant)."""
    hint = _norm(reponse)
    if not hint:
        return None
    for name in names:
        normed = _norm(name)
        if hint == normed or hint in normed or normed in hint:
            return name
    return None


def _match_option(reponse: str, options: tuple[str, ...]) -> str | None:
    """Indice 1-based ('1'..'6') ou libellé (normalisé, sous-chaîne)."""
    text = str(reponse or "").strip()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(options):
            return options[index]
        return None
    hint = _norm(text)
    if not hint:
        return None
    for option in options:
        normed = _norm(option)
        if hint == normed or hint in normed or normed in hint:
            return option
    return None


def _step_payload(step: str, question: str, options: list[str],
                  recap: dict[str, Any], insight: str) -> dict[str, Any]:
    return {
        "insight": insight,
        "step": step,
        "question": question,
        "options": options,
        "progress_percent": PROGRESS[step],
        "recap": recap,
    }


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Machine à états fixe ecole -> probleme -> urgence -> recap."""
    try:
        args = args if isinstance(args, dict) else {}
        context = context if isinstance(context, dict) else {}
        etape = _norm(args.get("etape")) or "ecole"
        reponse = str(args.get("reponse") or "").strip()
        recap_in = args.get("recap")
        recap: dict[str, Any] = dict(recap_in) if isinstance(recap_in, dict) else {}
        names = _school_names(context)

        if etape == "recap":
            return _step_payload(
                "recap",
                "Signalement prêt. Dites « confirmer » pour l'enregistrer, "
                "ou « recommencer » pour tout reprendre.",
                [],
                recap,
                "Saisie terminée : récapitulatif affiché, en attente de confirmation.",
            )

        if etape == "ecole":
            options = names[:_MAX_ECOLE_OPTIONS] if names else []
            if not reponse:
                return _step_payload(
                    "ecole", _ECole_Q, options, recap,
                    "Saisie assistée démarrée : je demande d'abord l'école concernée.",
                )
            # Id exact d'école ?
            try:
                wanted = int(reponse)
                for school in (context.get("schools") or []):
                    if isinstance(school, dict) and school.get("school_id") == wanted:
                        found = str(school.get("school_name") or school.get("name") or wanted)
                        recap = {**recap, "ecole": found}
                        return _step_payload(
                            "probleme", _PROBLEME_Q, list(PROBLEMES), recap,
                            f"École reconnue : {found}. Je demande maintenant le problème.",
                        )
            except (TypeError, ValueError):
                pass
            found = _match_school(reponse, names)
            if found is None and not names and reponse:
                found = reponse  # pas de référentiel : accepter le nom saisi
            if found is None:
                return _step_payload(
                    "ecole",
                    f"Je n'ai pas trouvé l'école « {reponse} ». {_ECole_Q}",
                    options, recap,
                    "École non reconnue : je repose la question avec la liste des écoles.",
                )
            recap = {**recap, "ecole": found}
            return _step_payload(
                "probleme", _PROBLEME_Q, list(PROBLEMES), recap,
                f"École reconnue : {found}. Je demande maintenant le problème.",
            )

        if etape == "probleme":
            if not reponse:
                return _step_payload(
                    "probleme", _PROBLEME_Q, list(PROBLEMES), recap,
                    "Saisie assistée : je demande le type de problème.",
                )
            probleme = _match_option(reponse, PROBLEMES)
            if probleme is None:
                return _step_payload(
                    "probleme",
                    f"« {reponse} » n'est pas dans la liste. {_PROBLEME_Q}",
                    list(PROBLEMES), recap,
                    "Problème non reconnu : je repose la question avec les choix.",
                )
            recap = {**recap, "probleme": probleme}
            return _step_payload(
                "urgence", _URGENCE_Q, list(URGENCES), recap,
                f"Problème noté : {probleme}. Je demande maintenant l'urgence.",
            )

        if etape == "urgence":
            if not reponse:
                return _step_payload(
                    "urgence", _URGENCE_Q, list(URGENCES), recap,
                    "Saisie assistée : je demande le niveau d'urgence.",
                )
            urgence = _match_option(reponse, URGENCES)
            if urgence is None:
                return _step_payload(
                    "urgence",
                    f"« {reponse} » n'est pas dans la liste. {_URGENCE_Q}",
                    list(URGENCES), recap,
                    "Urgence non reconnue : je repose la question avec les choix.",
                )
            recap = {**recap, "urgence": urgence}
            ecole = recap.get("ecole", "?")
            probleme = recap.get("probleme", "?")
            return _step_payload(
                "recap",
                f"Récapitulatif : {ecole} — {probleme} — urgence {urgence}. "
                "Dites « confirmer » pour enregistrer, ou « recommencer ».",
                [],
                recap,
                "Saisie terminée : récapitulatif prêt, en attente de confirmation.",
            )

        # Étape inconnue : reprendre au début (défensif).
        options = names[:_MAX_ECOLE_OPTIONS] if names else []
        return _step_payload(
            "ecole", _ECole_Q, options, {},
            "Étape inconnue : je recommence la saisie à la première question.",
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _build_saisie_assistee_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict) or obs.get("error") or not obs.get("question"):
        return None
    step = str(obs.get("step") or "?")
    return AgentCard(
        type="saisie_assistee",
        title=f"Saisie assistée — étape {step}",
        data=obs,
    )


CARD_BUILDERS = {"saisie_assistee": _build_saisie_assistee_card}
