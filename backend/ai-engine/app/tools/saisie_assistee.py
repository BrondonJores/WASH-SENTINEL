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
            "recherche": {
                "type": "string",
                "description": "Filtre de recherche pour l'étape 'ecole' quand le référentiel dépasse 6 écoles (sous-chaîne, insensible à la casse et aux accents)",
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


# Libellés FR -> valeurs système (construits depuis les tuples : pas de dérive).
_URGENCE_LEVELS = dict(zip(
    (_norm(u) for u in URGENCES), ("low", "medium", "high", "critical")))
_PROBLEME_CODES = dict(zip(
    (_norm(p) for p in PROBLEMES),
    ("leak", "blockage", "dry_well", "contamination", "total_breakdown", "other")))


def _school_by_id(wanted: int, context: dict[str, Any]) -> dict[str, Any] | None:
    schools = context.get("schools") if isinstance(context, dict) else None
    if not isinstance(schools, list):
        return None
    for school in schools:
        if isinstance(school, dict) and school.get("school_id") == wanted:
            return school
    return None


def _school_id_by_name(name: str, context: dict[str, Any]) -> int | None:
    schools = context.get("schools") if isinstance(context, dict) else None
    if not isinstance(schools, list):
        return None
    for school in schools:
        if not isinstance(school, dict):
            continue
        label = school.get("school_name") or school.get("name")
        if label is not None and str(label) == name:
            sid = school.get("school_id")
            return sid if isinstance(sid, int) else None
    return None


def _validate_ecole(ecole_raw: Any, context: dict[str, Any],
                    names: list[str]) -> tuple[str | None, int | None, bool]:
    """Valide l'école côté serveur (id exact, puis flou, puis repli).

    Retourne (nom résolu ou brut, school_id ou None, valide). Sans
    référentiel (names vide), le nom saisi est accepté tel quel : la
    saisie n'est jamais perdue.
    """
    text = str(ecole_raw or "").strip()
    if not text:
        return None, None, False
    try:
        wanted = int(text)
    except (TypeError, ValueError):
        wanted = None
    if wanted is not None:
        school = _school_by_id(wanted, context)
        if school is not None:
            label = str(school.get("school_name") or school.get("name") or wanted)
            return label, wanted, True
    found = _match_school(text, names)
    if found is not None:
        return found, _school_id_by_name(found, context), True
    if not names:
        return text, None, True  # pas de référentiel : accepter le nom saisi
    return text, None, False


def _finalize_recap(recap: dict[str, Any], context: dict[str, Any],
                    names: list[str]) -> dict[str, Any]:
    """Recalcule un récap validé (ne fait jamais confiance au client)."""
    ecole, ecole_id, ecole_valide = _validate_ecole(
        recap.get("ecole"), context, names)
    probleme = recap.get("probleme")
    urgence = recap.get("urgence")
    enriched = dict(recap)
    if ecole is not None:
        enriched["ecole"] = ecole
    enriched["ecole_id"] = ecole_id
    enriched["ecole_valide"] = ecole_valide
    enriched["probleme_code"] = (
        _PROBLEME_CODES.get(_norm(probleme)) if probleme else None)
    enriched["urgence_level"] = (
        _URGENCE_LEVELS.get(_norm(urgence)) if urgence else None)
    return enriched


def _recap_ready(enriched: dict[str, Any]) -> bool:
    return bool(enriched.get("ecole_valide")
                and enriched.get("probleme_code")
                and enriched.get("urgence_level"))


def _recap_question(enriched: dict[str, Any]) -> str:
    ecole = enriched.get("ecole") or "?"
    probleme = enriched.get("probleme") or "?"
    urgence = enriched.get("urgence") or "?"
    return (f"Récapitulatif : {ecole} — {probleme} — urgence {urgence}. "
            "Dites « confirmer » pour enregistrer, ou « recommencer ».")


def _recap_confirmation(enriched: dict[str, Any], ready: bool) -> str:
    if ready:
        return ("Prêt pour enregistrement : dites « confirmer » et l'opérateur "
                "utilisera prepare_report avec cette saisie.")
    missing = []
    if not enriched.get("ecole_valide"):
        missing.append("école")
    if not enriched.get("probleme_code"):
        missing.append("problème")
    if not enriched.get("urgence_level"):
        missing.append("urgence")
    return (f"Saisie incomplète ({', '.join(missing)}) : prepare_report "
            "attendra une saisie complète confirmée.")


def _ecole_listing(names: list[str], recherche: str) -> tuple[list[str], str]:
    """Options (max 6) + question, avec recherche au-delà de 6 écoles."""
    filt = _norm(recherche)
    if len(names) > _MAX_ECOLE_OPTIONS and filt:
        filtered = [n for n in names if filt in _norm(n)]
    else:
        filtered = names
    options = filtered[:_MAX_ECOLE_OPTIONS]
    if len(names) > _MAX_ECOLE_OPTIONS and not filt:
        question = (f"{_ECole_Q} ({len(names)} écoles au total : "
                    "tapez quelques lettres pour chercher.)")
    elif len(names) > _MAX_ECOLE_OPTIONS:
        needle = str(recherche or "").strip()
        if not filtered:
            question = (f"Aucune école trouvée pour « {needle} » "
                        f"sur {len(names)}. Essayez une autre orthographe.")
        else:
            question = (f"« {needle} » : {len(filtered)} école(s) sur {len(names)}. "
                        "Touchez le nom de l'école, ou affinez la recherche.")
    else:
        question = _ECole_Q
    return options, question


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
            enriched = _finalize_recap(recap, context, names)
            if not enriched.get("ecole_valide"):
                # École inconnue ou absente : retour à l'école au lieu
                # d'un faux récapitulatif.
                recherche = str(args.get("recherche") or "").strip()
                options, ecole_q = _ecole_listing(names, recherche)
                raw = recap.get("ecole")
                question = (f"Je n'ai pas trouvé l'école « {raw} ». {ecole_q}"
                            if raw else ecole_q)
                payload = _step_payload(
                    "ecole", question, options, enriched,
                    "Récapitulatif rejeté : école inconnue, retour à la première question.",
                )
                payload["total_ecoles"] = len(names)
                if recherche:
                    payload["recherche"] = recherche
                return payload
            ready = _recap_ready(enriched)
            payload = _step_payload(
                "recap",
                _recap_question(enriched),
                [],
                enriched,
                "Saisie terminée : récapitulatif validé, en attente de confirmation.",
            )
            payload["ready"] = ready
            payload["confirmation"] = _recap_confirmation(enriched, ready)
            return payload

        if etape == "ecole":
            recherche = str(args.get("recherche") or "").strip()
            options, ecole_q = _ecole_listing(names, recherche)
            if not reponse:
                payload = _step_payload(
                    "ecole", ecole_q, options, recap,
                    "Saisie assistée démarrée : je demande d'abord l'école concernée.",
                )
                payload["total_ecoles"] = len(names)
                if recherche:
                    payload["recherche"] = recherche
                return payload
            # Id exact d'école ?
            try:
                wanted = int(reponse)
                for school in (context.get("schools") or []):
                    if isinstance(school, dict) and school.get("school_id") == wanted:
                        found = str(school.get("school_name") or school.get("name") or wanted)
                        recap = {**recap, "ecole": found, "ecole_id": wanted,
                                 "ecole_valide": True}
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
                payload = _step_payload(
                    "ecole",
                    f"Je n'ai pas trouvé l'école « {reponse} ». {ecole_q}",
                    options, recap,
                    "École non reconnue : je repose la question avec la liste des écoles.",
                )
                payload["total_ecoles"] = len(names)
                if recherche:
                    payload["recherche"] = recherche
                return payload
            recap = {**recap, "ecole": found, "ecole_valide": True,
                     "ecole_id": _school_id_by_name(found, context)}
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
            enriched = _finalize_recap(recap, context, names)
            if not enriched.get("ecole_valide"):
                # Saut direct à l'urgence sans école valide : retour à l'école.
                options, ecole_q = _ecole_listing(names, "")
                payload = _step_payload(
                    "ecole", ecole_q, options, enriched,
                    "École manquante : je repose la première question avant le récapitulatif.",
                )
                payload["total_ecoles"] = len(names)
                return payload
            ready = _recap_ready(enriched)
            payload = _step_payload(
                "recap",
                _recap_question(enriched),
                [],
                enriched,
                "Saisie terminée : récapitulatif validé, en attente de confirmation.",
            )
            payload["ready"] = ready
            payload["confirmation"] = _recap_confirmation(enriched, ready)
            return payload

        # Étape inconnue : reprendre au début (défensif).
        options, ecole_q = _ecole_listing(names, "")
        payload = _step_payload(
            "ecole", ecole_q, options, {},
            "Étape inconnue : je recommence la saisie à la première question.",
        )
        payload["total_ecoles"] = len(names)
        return payload
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
