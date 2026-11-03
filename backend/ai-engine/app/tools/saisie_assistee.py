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
from ..tool_consts import MAX_ECOLE_OPTIONS, tool_lang

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
    "help me report", "help me fill", "help me fill in",
    "report step by step", "step by step",
    "guided form", "guided entry", "guide me",
    "i want to report", "how to report",
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

PROBLEMES_EN = (
    "Water leak",
    "Blocked latrines",
    "Dry borehole / no water",
    "Dirty or contaminated water",
    "Broken pump",
    "Other problem",
)

URGENCES_EN = ("Low", "Medium", "High", "Critical")

PROGRESS = {"ecole": 0, "probleme": 33, "urgence": 66, "recap": 100}

_ECole_Q = "Dans quelle école y a-t-il un problème ? Touchez le nom de l'école."
_PROBLEME_Q = "Quel est le problème ? Touchez une réponse."
_URGENCE_Q = "C'est urgent comment ? Touchez une réponse."

_ECOLE_Q_EN = "Which school has a problem? Tap the school name."
_PROBLEME_Q_EN = "What is the problem? Tap an answer."
_URGENCE_Q_EN = "How urgent is it? Tap an answer."

_STEP_EN = {"ecole": "school", "probleme": "issue",
            "urgence": "urgency", "recap": "summary"}

#: Alias partagé (source unique : app.tool_consts).
_MAX_ECOLE_OPTIONS = MAX_ECOLE_OPTIONS


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
# Mêmes codes depuis les libellés EN (saisie bilingue, codes inchangés).
_URGENCE_LEVELS.update(zip(
    (_norm(u) for u in URGENCES_EN), ("low", "medium", "high", "critical")))
_PROBLEME_CODES.update(zip(
    (_norm(p) for p in PROBLEMES_EN),
    ("leak", "blockage", "dry_well", "contamination", "total_breakdown", "other")))


def _match_option_any(reponse: str, primary: tuple[str, ...],
                       fallback: tuple[str, ...]) -> str | None:
    """Apparie sur le tuple affiché, puis sur l'autre langue (texte seul)."""
    found = _match_option(reponse, primary)
    if found is not None:
        return found
    if str(reponse or "").strip().isdigit():
        return None  # les chiffres visent toujours les options affichées
    return _match_option(reponse, fallback)


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


def _recap_question(enriched: dict[str, Any], en: bool = False) -> str:
    ecole = enriched.get("ecole") or "?"
    probleme = enriched.get("probleme") or "?"
    urgence = enriched.get("urgence") or "?"
    if en:
        return (f"Summary: {ecole} — {probleme} — {urgence} urgency. "
                "Say « confirm » to save, or « restart ».")
    return (f"Récapitulatif : {ecole} — {probleme} — urgence {urgence}. "
            "Dites « confirmer » pour enregistrer, ou « recommencer ».")


def _recap_confirmation(enriched: dict[str, Any], ready: bool,
                        en: bool = False) -> str:
    if ready:
        if en:
            return ("Ready to save: say « confirm » and the operator "
                    "will use prepare_report with this entry.")
        return ("Prêt pour enregistrement : dites « confirmer » et l'opérateur "
                "utilisera prepare_report avec cette saisie.")
    missing = []
    if not enriched.get("ecole_valide"):
        missing.append("school" if en else "école")
    if not enriched.get("probleme_code"):
        missing.append("issue" if en else "problème")
    if not enriched.get("urgence_level"):
        missing.append("urgency" if en else "urgence")
    if en:
        return (f"Incomplete entry ({', '.join(missing)}): prepare_report "
                "will wait for a confirmed complete entry.")
    return (f"Saisie incomplète ({', '.join(missing)}) : prepare_report "
            "attendra une saisie complète confirmée.")


def _ecole_listing(names: list[str], recherche: str,
                   en: bool = False) -> tuple[list[str], str]:
    """Options (max 6) + question, avec recherche au-delà de 6 écoles."""
    filt = _norm(recherche)
    if len(names) > _MAX_ECOLE_OPTIONS and filt:
        filtered = [n for n in names if filt in _norm(n)]
    else:
        filtered = names
    options = filtered[:_MAX_ECOLE_OPTIONS]
    base_q = _ECOLE_Q_EN if en else _ECole_Q
    if len(names) > _MAX_ECOLE_OPTIONS and not filt:
        if en:
            question = (f"{base_q} ({len(names)} schools in total: "
                        "type a few letters to search.)")
        else:
            question = (f"{base_q} ({len(names)} écoles au total : "
                        "tapez quelques lettres pour chercher.)")
    elif len(names) > _MAX_ECOLE_OPTIONS:
        needle = str(recherche or "").strip()
        if not filtered:
            if en:
                question = (f"No school found for « {needle} » "
                            f"out of {len(names)}. Try another spelling.")
            else:
                question = (f"Aucune école trouvée pour « {needle} » "
                            f"sur {len(names)}. Essayez une autre orthographe.")
        elif en:
            question = (f"« {needle} »: {len(filtered)} school(s) out of {len(names)}. "
                        "Tap the school name, or refine the search.")
        else:
            question = (f"« {needle} » : {len(filtered)} école(s) sur {len(names)}. "
                        "Touchez le nom de l'école, ou affinez la recherche.")
    else:
        question = base_q
    return options, question


def execute(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Machine à états fixe ecole -> probleme -> urgence -> recap."""
    try:
        args = args if isinstance(args, dict) else {}
        context = context if isinstance(context, dict) else {}
        use_en = tool_lang(context) == "en"
        lang = "en" if use_en else "fr"
        problemes = PROBLEMES_EN if use_en else PROBLEMES
        urgences = URGENCES_EN if use_en else URGENCES
        q_probleme = _PROBLEME_Q_EN if use_en else _PROBLEME_Q
        q_urgence = _URGENCE_Q_EN if use_en else _URGENCE_Q

        def make(step: str, question: str, options: list[str],
                 recap: dict[str, Any], insight: str) -> dict[str, Any]:
            payload = _step_payload(step, question, options, recap, insight)
            payload["lang"] = lang
            return payload

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
                options, ecole_q = _ecole_listing(names, recherche, en=use_en)
                raw = recap.get("ecole")
                if use_en:
                    question = (f"I did not find the school « {raw} ». {ecole_q}"
                                if raw else ecole_q)
                else:
                    question = (f"Je n'ai pas trouvé l'école « {raw} ». {ecole_q}"
                                if raw else ecole_q)
                payload = make(
                    "ecole", question, options, enriched,
                    ("Summary rejected: unknown school, back to the first question." if use_en
                     else "Récapitulatif rejeté : école inconnue, retour à la première question."),
                )
                payload["total_ecoles"] = len(names)
                if recherche:
                    payload["recherche"] = recherche
                return payload
            ready = _recap_ready(enriched)
            payload = make(
                "recap",
                _recap_question(enriched, en=use_en),
                [],
                enriched,
                ("Entry complete: summary validated, awaiting confirmation." if use_en
                 else "Saisie terminée : récapitulatif validé, en attente de confirmation."),
            )
            payload["ready"] = ready
            payload["confirmation"] = _recap_confirmation(enriched, ready, en=use_en)
            return payload

        if etape == "ecole":
            recherche = str(args.get("recherche") or "").strip()
            options, ecole_q = _ecole_listing(names, recherche, en=use_en)
            if not reponse:
                payload = make(
                    "ecole", ecole_q, options, recap,
                    ("Guided entry started: I first ask which school is concerned." if use_en
                     else "Saisie assistée démarrée : je demande d'abord l'école concernée."),
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
                        return make(
                            "probleme", q_probleme, list(problemes), recap,
                            (f"School recognised: {found}. I now ask about the problem." if use_en
                         else f"École reconnue : {found}. Je demande maintenant le problème."),
                        )
            except (TypeError, ValueError):
                pass
            found = _match_school(reponse, names)
            if found is None and not names and reponse:
                found = reponse  # pas de référentiel : accepter le nom saisi
            if found is None:
                payload = make(
                    "ecole",
                    (f"I did not find the school « {reponse} ». {ecole_q}" if use_en
                     else f"Je n'ai pas trouvé l'école « {reponse} ». {ecole_q}"),
                    options, recap,
                    ("School not recognised: I ask again with the school list." if use_en
                     else "École non reconnue : je repose la question avec la liste des écoles."),
                )
                payload["total_ecoles"] = len(names)
                if recherche:
                    payload["recherche"] = recherche
                return payload
            recap = {**recap, "ecole": found, "ecole_valide": True,
                     "ecole_id": _school_id_by_name(found, context)}
            return make(
                "probleme", q_probleme, list(problemes), recap,
                (f"School recognised: {found}. I now ask about the problem." if use_en
                         else f"École reconnue : {found}. Je demande maintenant le problème."),
            )

        if etape == "probleme":
            if not reponse:
                return make(
                    "probleme", q_probleme, list(problemes), recap,
                    ("Guided entry: I ask the problem type." if use_en
                     else "Saisie assistée : je demande le type de problème."),
                )
            probleme = _match_option_any(reponse, problemes, PROBLEMES) if use_en else _match_option(reponse, PROBLEMES)
            if probleme is None:
                return make(
                    "probleme",
                    (f"« {reponse} » is not in the list. {q_probleme}" if use_en
                     else f"« {reponse} » n'est pas dans la liste. {q_probleme}"),
                    list(problemes), recap,
                    ("Problem not recognised: I ask again with the choices." if use_en
                     else "Problème non reconnu : je repose la question avec les choix."),
                )
            recap = {**recap, "probleme": probleme}
            return make(
                "urgence", q_urgence, list(urgences), recap,
                (f"Problem noted: {probleme}. I now ask about urgency." if use_en
                 else f"Problème noté : {probleme}. Je demande maintenant l'urgence."),
            )

        if etape == "urgence":
            if not reponse:
                return make(
                    "urgence", q_urgence, list(urgences), recap,
                    ("Guided entry: I ask the urgency level." if use_en
                     else "Saisie assistée : je demande le niveau d'urgence."),
                )
            urgence = _match_option_any(reponse, urgences, URGENCES) if use_en else _match_option(reponse, URGENCES)
            if urgence is None:
                return make(
                    "urgence",
                    (f"« {reponse} » is not in the list. {q_urgence}" if use_en
                     else f"« {reponse} » n'est pas dans la liste. {q_urgence}"),
                    list(urgences), recap,
                    ("Urgency not recognised: I ask again with the choices." if use_en
                     else "Urgence non reconnue : je repose la question avec les choix."),
                )
            recap = {**recap, "urgence": urgence}
            enriched = _finalize_recap(recap, context, names)
            if not enriched.get("ecole_valide"):
                # Saut direct à l'urgence sans école valide : retour à l'école.
                options, ecole_q = _ecole_listing(names, "", en=use_en)
                payload = make(
                    "ecole", ecole_q, options, enriched,
                    ("Missing school: I ask the first question again before the summary." if use_en
                     else "École manquante : je repose la première question avant le récapitulatif."),
                )
                payload["total_ecoles"] = len(names)
                return payload
            ready = _recap_ready(enriched)
            payload = make(
                "recap",
                _recap_question(enriched, en=use_en),
                [],
                enriched,
                ("Entry complete: summary validated, awaiting confirmation." if use_en
                 else "Saisie terminée : récapitulatif validé, en attente de confirmation."),
            )
            payload["ready"] = ready
            payload["confirmation"] = _recap_confirmation(enriched, ready, en=use_en)
            return payload

        # Étape inconnue : reprendre au début (défensif).
        options, ecole_q = _ecole_listing(names, "", en=use_en)
        payload = make(
            "ecole", ecole_q, options, {},
            ("Unknown step: I restart the entry at the first question." if use_en
             else "Étape inconnue : je recommence la saisie à la première question."),
        )
        payload["total_ecoles"] = len(names)
        return payload
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _build_saisie_assistee_card(obs: dict[str, Any]) -> AgentCard | None:
    if not isinstance(obs, dict) or obs.get("error") or not obs.get("question"):
        return None
    step = str(obs.get("step") or "?")
    use_en = str(obs.get("lang") or "fr").lower().startswith("en")
    if use_en:
        title = f"Guided entry — step {_STEP_EN.get(step, step)}"
    else:
        title = f"Saisie assistée — étape {step}"
    return AgentCard(type="saisie_assistee", title=title, data=obs)


CARD_BUILDERS = {"saisie_assistee": _build_saisie_assistee_card}
