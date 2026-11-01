"""Dialogue guide vocal partage (CANAL 3) : machine a slots deterministe.

Cadre vocal : max 3 options, UNE question courte a la fois, confirmations
oui/non, langue simple. Chaque etape = une question courte FR + une variante
douala (dua_Latn). Le douala est BEST-EFFORT (documente ci-dessous, validation
locuteur requise) ; seul "madiba" (eau) est deja valide par ailleurs
(cf. app/extractor.py, filet local).

Etapes : ecole -> probleme [eau/toilettes/fuite] -> gravite -> RECAP.

Notes douala (best-effort) :
- "Sukulu njika ?" : sukulu = ecole (emprunt), njika = quelle/laquelle.
- "Probleme njika ? Madiba, toilettes, to fuite ?" : volontairement en
  alternance codique (code-switching FR), pratique courante a l'oral ;
  madiba = eau (valide), "to" = ou (best-effort).
- "E bobe ?" : best-effort pour "c'est grave ?" (e = c'est, bobe = mauvais).
- "E bonga ?" : best-effort pour "c'est bon ?" (validation locuteur requise).
- Oui douala : "ee" (ecrit "eee"/"ee", prononce [e:]) -> oui.
- Non douala : "si" existe mais est AMBIGU avec le FR "si" (= oui, qui
  contredit une negation, ex. "C'est grave ? - Si !"). "si" seul est donc
  volontairement classe "unknown" -> on repose la question (jamais de
  devinette sur une confirmation). Les locuteurs douala peuvent dire "non",
  compris partout, ou "ee" pour oui.

Regles recherche (vocal) :
- Jamais plus d'UNE question par tour (0 ou 1 point d'interrogation).
- Max 3 options proposees (probleme : eau / toilettes / fuite).
- "repeter" (et variantes) -> on repose la question en cours, sans avancer.
- Slot incompris -> on repose la meme question (jamais de devinette).
"""
from __future__ import annotations

from typing import Any, Literal

Step = Literal["school", "problem", "severity", "confirm", "done"]
Confirmation = Literal["yes", "no", "repeat", "unknown"]

SCHOOL = "school"
PROBLEM = "problem"
SEVERITY = "severity"
CONFIRM = "confirm"
DONE = "done"

STEPS: tuple[str, ...] = (SCHOOL, PROBLEM, SEVERITY, CONFIRM)

# UNE question courte par etape (FR simple). Jamais plus d'un "?" par texte
# (contrat vocal : test_one_question_per_turn).
Q_SCHOOL_FR = "Quelle \u00e9cole ?"
Q_PROBLEM_FR = "Quel probl\u00e8me : eau, toilettes, ou fuite ?"
Q_SEVERITY_FR = "C'est grave ?"
RECAP_PREFIX = "R\u00e9cap : "
Q_CONFIRM_TAIL_FR = "C'est bon ? Dites oui ou non."

# Variantes douala (best-effort, voir docstring du module).
Q_SCHOOL_DUA = "Sukulu njika ?"
Q_PROBLEM_DUA = "Probleme njika : madiba, toilettes, to fuite ?"
Q_SEVERITY_DUA = "E bobe ?"
Q_CONFIRM_TAIL_DUA = "E bonga ? Na \u00e9\u00e9 to si."

QUESTIONS_FR: dict[str, str] = {
    SCHOOL: Q_SCHOOL_FR,
    PROBLEM: Q_PROBLEM_FR,
    SEVERITY: Q_SEVERITY_FR,
}
QUESTIONS_DUA: dict[str, str] = {
    SCHOOL: Q_SCHOOL_DUA,
    PROBLEM: Q_PROBLEM_DUA,
    SEVERITY: Q_SEVERITY_DUA,
}

#: Questions par langue (LOT 5) : ask() résout QUESTIONS[lang][step].
QUESTIONS: dict[str, dict[str, str]] = {
    "fr": QUESTIONS_FR,
    "dua": QUESTIONS_DUA,
}
#: Consigne de confirmation par langue (recap + oui/non).
CONFIRM_TAILS: dict[str, str] = {
    "fr": Q_CONFIRM_TAIL_FR,
    "dua": Q_CONFIRM_TAIL_DUA,
}
#: Message de fin par langue (étape DONE).
DONE_MESSAGES: dict[str, str] = {
    "fr": "C'est not\u00e9. Merci !",
    "dua": "E bonga. Mase !",
}

#: Longueur max du libellé école libre stocké dans le slot (tronqué).
SCHOOL_LABEL_MAX_CHARS = 80

#: Verdicts de parse_confirmation (oui/non/répéter/incompris).
CONFIRM_YES = "yes"
CONFIRM_NO = "no"
CONFIRM_REPEAT = "repeat"
CONFIRM_UNKNOWN = "unknown"

#: Pastilles cliquables par étape (max 3, jamais de 4e option).
PROBLEM_CHIPS: list[str] = ["Eau", "Toilettes", "Fuite"]
CONFIRM_CHIPS: list[str] = ["Oui", "Non"]
#: Plafond de pastilles (problème : 3 options ; écoles suggérées : 3 max).
MAX_GUIDED_CHIPS = 3

#: Tous les prompts guides reconnus (reprise de session via l'historique).
ALL_QUESTIONS: tuple[str, ...] = (
    Q_SCHOOL_FR, Q_PROBLEM_FR, Q_SEVERITY_FR,
    Q_SCHOOL_DUA, Q_PROBLEM_DUA, Q_SEVERITY_DUA,
)

#: Problemes canoniques (max 3 options).
PROBLEM_EAU = "eau"
PROBLEM_TOILETTES = "toilettes"
PROBLEM_FUITE = "fuite"
PROBLEMS: tuple[str, ...] = (PROBLEM_EAU, PROBLEM_TOILETTES, PROBLEM_FUITE)

#: Gravites canoniques.
SEV_GRAVE = "grave"
SEV_PAS_GRAVE = "pas grave"

# --- Parseur oui/non -------------------------------------------------------
# Comparaison sur texte replie (minuscules, sans accents) via textnorm.fold.

_YES_EXACT = frozenset({
    "oui", "ouai", "ouais", "ouais!", "yeah", "yes", "yep", "yess", "ok",
    "daccord", "dac", "affirmatif", "wi",  # "wi" = oui (pidgin camerounais)
    "ee", "eee", "eeee", "ii",  # "ee" = oui (douala, best-effort documente)
    "absolument", "tout a fait", "cest ca", "exact", "exactement",
})
_YES_LOOSE = (
    "oui", "ouais", "yeah", "daccord", "affirmatif",
)
_NO_EXACT = frozenset({
    "non", "no", "nan", "nann", "nop", "nope", "jamais",
    "non merci", "pas du tout", "pas question", "pas vraiment",
    "pas encore", "du tout",
})
_NO_LOOSE = (
    "non merci", "pas du tout", "pas question", "pas vraiment",
)
_REPEAT_CUES = (
    "repet", "redis", "redis-moi", "redis moi", "encore", "pardon",
    "comment", "quoi", "again", "repeat", "heinn", "hein",
    "je nai pas compris", "jai pas compris", "pas compris",
)
# "si" seul : AMBIGU (FR "si" = oui qui contredit / douala "si" = non).
# Volontairement classe "unknown" -> on repose la question (voir docstring).
_AMBIGUOUS_EXACT = frozenset({"si", "ci"})

# --- Parseur probleme ------------------------------------------------------
# Ordre documente : absence-d'eau > fuite > toilettes > eau.
# ("l'eau ne coule plus" = eau, PAS fuite ; "fuite d'eau" = fuite, le
# phenomene prime ; "fuite dans les toilettes" = fuite).
_ABSENCE_EAU_CUES = (
    "pas d", "plus d", "ne coule", "coule plus", "a sec", "tarit",
    "plus deau", "pas deau", "aucune eau", "zero eau", "coupe",
)
_FUITE_CUES = (
    "fuit", "fuite", "fuites", "leak", "coule", "coulent", "goutte",
    "gouttes", "degouline", "inond", "tuyau perce", "tuyau casse",
    "tuyau coupe", "eclate",
)
_TOILETTES_CUES = (
    "toilette", "toilettes", "latrine", "latrines", "wc", "toilet",
    "cabinets", "sanitaire", "selles", "selle",
)
_EAU_CUES = (
    "eau", "wata", "madiba", "robinet", "pompe", "forage", "puits",
    "fontaine", "chateau deau", "soif", "sale", "boueuse",
)

# --- Parseur gravite (mots directs, avant le oui/non) -----------------------
_GRAVE_CUES = (
    "grave", "urgent", "urgence", "critique", "serieux", "dangereux",
    "catastrophe", "bobe", "vite", "rapidement", "cholera",
)
_PAS_GRAVE_CUES = (
    "pas grave", "pas urgent", "petit", "petite", "leger", "legere",
    "small", "un peu", "lentement", "quand vous pouvez",
)

# --- Detection d'intention "signalement" (declencheur du mode guide) --------
_REPORT_CUES = (
    "signal", "declar", "panne", "casse", "fuit", "fuite", "leak",
    "pas d", "plus d", "robinet", "pompe", "toilette", "latrine",
    "report", "wata", "madiba", "forage", "puits", "fontaine",
    "plus deau", "pas deau",
)


def _fold(text: str) -> str:
    from .textnorm import fold
    return fold(text or "")


def _normalize_confirm(text: str) -> str:
    """Reponse courte normalisee : repliee, sans ponctuation ni apostrophes.

    "Non." -> "non", "d'accord" -> "daccord", "Si !" -> "si" (reste ambigu).
    """
    folded = _fold(text)
    for apostrophe in ("'", "\u2019", "\u2018", "`"):
        folded = folded.replace(apostrophe, "")
    for punct in ".,!?;:()[]\u2026\"-":
        folded = folded.replace(punct, " ")
    return " ".join(folded.split())


def parse_confirmation(text: str) -> Confirmation:
    """Classe une reponse courte : yes / no / repeat / unknown.

    FR + douala ("ee" = oui). "si" seul = unknown (ambigu FR/douala, voir
    docstring). "repeter" et variantes = repeat. Ne leve jamais.
    """
    folded = _normalize_confirm(text)
    if not folded:
        return CONFIRM_UNKNOWN
    for cue in _REPEAT_CUES:
        if cue in folded:
            return CONFIRM_REPEAT
    if folded in _AMBIGUOUS_EXACT:
        return CONFIRM_UNKNOWN
    if folded in _YES_EXACT or folded in _NO_EXACT:
        return CONFIRM_YES if folded in _YES_EXACT else CONFIRM_NO
    for cue in _NO_LOOSE:
        if cue in folded:
            return CONFIRM_NO
    for cue in _YES_LOOSE:
        if cue in folded:
            return CONFIRM_YES
    return CONFIRM_UNKNOWN


def parse_problem(text: str) -> str | None:
    """Probleme canonique ("eau"|"toilettes"|"fuite") ou None si incompris."""
    folded = _fold(text)
    if not folded.strip():
        return None
    if any(cue in folded for cue in _ABSENCE_EAU_CUES):
        return PROBLEM_EAU
    if any(cue in folded for cue in _FUITE_CUES):
        return PROBLEM_FUITE
    if any(cue in folded for cue in _TOILETTES_CUES):
        return PROBLEM_TOILETTES
    if any(cue in folded for cue in _EAU_CUES):
        return PROBLEM_EAU
    return None


def parse_severity(text: str) -> str | None:
    """Gravite canonique ("grave"|"pas grave") ou None si incomprise."""
    folded = _fold(text)
    if not folded.strip():
        return None
    if any(cue in folded for cue in _PAS_GRAVE_CUES):
        return SEV_PAS_GRAVE
    if any(cue in folded for cue in _GRAVE_CUES):
        return SEV_GRAVE
    verdict = parse_confirmation(text)
    if verdict == CONFIRM_YES:
        return SEV_GRAVE
    if verdict == CONFIRM_NO:
        return SEV_PAS_GRAVE
    return None


def is_report_message(text: str) -> bool:
    """Le message exprime-t-il un signalement (declencheur du mode guide) ?"""
    folded = _fold(text)
    return any(cue in folded for cue in _REPORT_CUES)


def is_guided_prompt(text: str) -> bool:
    """Le texte est-il une question du dialogue guide (reprise de session) ?"""
    value = (text or "").strip()
    if not value:
        return False
    if any(q in value for q in ALL_QUESTIONS):
        return True
    return value.startswith(RECAP_PREFIX) and (
        Q_CONFIRM_TAIL_FR in value or Q_CONFIRM_TAIL_DUA in value)


def next_step(slots: dict[str, Any]) -> Step:
    """Prochaine etape d'apres les slots remplis (ecole->probleme->gravite)."""
    for step in (SCHOOL, PROBLEM, SEVERITY):
        if not (slots.get(step) or ""):
            return step  # type: ignore[return-value]
    return CONFIRM


def ask(step: str, slots: dict[str, Any] | None = None, lang: str = "fr") -> str:
    """L'UNIQUE question du tour (recap + consigne pour "confirm").

    Garantie vocale : au plus UN point d'interrogation par texte.
    """
    dua = str(lang or "fr").lower().startswith(("dua", "douala"))
    key = "dua" if dua else "fr"
    table = QUESTIONS[key]
    if step in table:
        return table[step]
    if step == CONFIRM:
        slots = slots or {}
        tail = CONFIRM_TAILS[key]
        return (
            f"{RECAP_PREFIX}{slots.get(SCHOOL, '?')}, "
            f"{slots.get(PROBLEM, '?')}, {slots.get(SEVERITY, '?')}. {tail}"
        )
    if step == DONE:
        return DONE_MESSAGES[key]
    raise ValueError(f"\u00e9tape guid\u00e9e inconnue : {step!r}")


def guided_chips(step: str, context: dict[str, Any] | None = None) -> list[str]:
    """Pastilles cliquables du tour (max 3, jamais de 4e option)."""
    if step == PROBLEM:
        return list(PROBLEM_CHIPS)
    if step in (SEVERITY, CONFIRM):
        return list(CONFIRM_CHIPS)
    if step == SCHOOL:
        names = [s.get("school_name") for s in (context or {}).get("schools", [])[:MAX_GUIDED_CHIPS]]
        return [n for n in names if n][:MAX_GUIDED_CHIPS]
    return []


def _canonical_school(text: str, context: dict[str, Any] | None) -> str:
    """Libelle connu si l'ecole est reconnue, sinon texte brut (tronque)."""
    raw = " ".join((text or "").split())[:SCHOOL_LABEL_MAX_CHARS]
    if context:
        try:
            from .agent_loop import resolve_place
            found = resolve_place(raw, context)
        except (ImportError, AttributeError, ValueError):
            found = None
        if found is not None and found[0] == "school":
            return found[1]
    return raw


def _accept_school(text: str) -> bool:
    """Un texte libre peut-il remplir le slot ecole (ni vide, ni oui/non) ?"""
    if not (text or "").strip():
        return False
    if _normalize_confirm(text) in _AMBIGUOUS_EXACT:
        return False
    return parse_confirmation(text) == CONFIRM_UNKNOWN


def fill_from_text(
    slots: dict[str, Any],
    step: str,
    text: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """Tente de remplir le slot de l'etape depuis le texte. True si rempli."""
    if step == SCHOOL:
        if not _accept_school(text):
            return False
        slots[SCHOOL] = _canonical_school(text, context)
        return True
    if step == PROBLEM:
        found = parse_problem(text)
        if found is None:
            return False
        slots[PROBLEM] = found
        return True
    if step == SEVERITY:
        found = parse_severity(text)
        if found is None:
            return False
        slots[SEVERITY] = found
        return True
    return False


def prefill_from_trigger(
    message: str, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Pre-remplit les slots depuis le message declencheur ("panne a Bonanjo").

    Ecole : UNIQUEMENT si reconnue (lieu connu), sinon on posera la question.
    """
    slots: dict[str, Any] = {}
    school: str | None = None
    if context:
        try:
            from .agent_loop import resolve_place
            found = resolve_place(message or "", context)
        except (ImportError, AttributeError, ValueError):
            found = None
        if found is not None and found[0] == "school":
            school = found[1]
    if school:
        slots[SCHOOL] = school
    problem = parse_problem(message)
    if problem is not None:
        slots[PROBLEM] = problem
    severity = parse_severity(message)
    if severity is not None:
        slots[SEVERITY] = severity
    return slots


def _history_turns(history: Any) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for turn in history or []:
        role = getattr(turn, "role", "") or ""
        content = getattr(turn, "content", "") or ""
        if isinstance(turn, dict):
            role = str(turn.get("role", "") or "")
            content = str(turn.get("content", "") or "")
        turns.append({"role": role, "content": content})
    return turns


def collect_answers(history: Any, message: str) -> tuple[str | None, list[str]]:
    """Separe le declencheur d'origine des reponses guidees (dans l'ordre).

    Retourne (trigger, answers) : trigger = message utilisateur juste avant
    la premiere question guidee de l'historique (None si nouveau declencheur),
    answers = reponses utilisateur depuis (message courant inclus).
    """
    turns = _history_turns(history)
    first_guided = next(
        (i for i, t in enumerate(turns)
         if t["role"] == "assistant" and is_guided_prompt(t["content"])),
        None,
    )
    if first_guided is None:
        return None, []
    trigger: str | None = None
    for turn in turns[:first_guided]:
        if turn["role"] == "user" and (turn["content"] or "").strip():
            trigger = turn["content"]
    answers = [t["content"] for t in turns[first_guided:]
               if t["role"] == "user"]
    answers.append(message or "")
    return trigger, answers


def session_in_progress(history: Any) -> bool:
    """Une session guidee est-elle en cours (derniere reponse = question) ?"""
    turns = _history_turns(history)
    for turn in reversed(turns):
        if turn["role"] == "assistant" and (turn["content"] or "").strip():
            return is_guided_prompt(turn["content"])
    return False


def guided_turn(
    message: str,
    history: Any = None,
    context: dict[str, Any] | None = None,
    lang: str = "fr",
) -> dict[str, Any] | None:
    """Un tour de dialogue guide, ou None (laisser le flux normal tranquille).

    Retourne {"status": "ask", "step", "question", "slots", "chips"},
    {"status": "confirmed", "slots", "report_text"} (bascule flux normal),
    ou None (pas un signalement hors session : flux normal inchange).
    Session : etat reconstruit depuis l'historique (aucun etat serveur).
    """
    context = context or {}
    in_session = session_in_progress(history)
    if not in_session and not is_report_message(message):
        return None

    if parse_confirmation(message) == CONFIRM_REPEAT:
        # Repetition : on repose la question en cours, sans avancer.
        slots = seeded_replay(history, message, context, skip_current=True)["slots"]
        step = next_step(slots)
        if step == CONFIRM:
            return _ask_confirm(slots, lang)
        return _ask_step(step, slots, context, lang)

    if not in_session:
        # Nouveau declencheur : pre-remplissage, puis premiere question.
        slots = prefill_from_trigger(message, context)
        step = next_step(slots)
        if step == CONFIRM:
            return _ask_confirm(slots, lang)
        return _ask_step(step, slots, context, lang)

    # Session en cours : graines du recap + reponses post-recap rejouées.
    run = seeded_replay(history, message, context, skip_current=False)
    if run["confirmed"]:
        return {
            "status": "confirmed",
            "slots": dict(run["slots"]),
            "report_text": build_report_text(run["slots"]),
        }
    if run["restarted"]:
        # Refus du recap : on recommence a zero (pas de devinette).
        fresh = ask(SCHOOL, None, lang)
        prefix = ("On recommence. " if not _is_dua(lang)
                  else "E bobe te, e londe. ")
        return {"status": "ask", "step": SCHOOL,
                "question": f"{prefix}{fresh}",
                "slots": {}, "chips": guided_chips(SCHOOL, context)}
    step = next_step(run["slots"])
    if step == CONFIRM:
        return _ask_confirm(run["slots"], lang)
    return _ask_step(step, run["slots"], context, lang)


def _run_answers(
    slots: dict[str, Any], answers: list[str], context: dict[str, Any]
) -> dict[str, Any]:
    """Rejoue les reponses dans l'ordre (reponse incomprise = sautee).

    Retourne {"slots", "confirmed", "restarted"} : "restarted" = le dernier
    evenement marquant est un refus du recap (slots vides, on recommence).
    """
    slots = dict(slots)
    restarted = False
    for answer in answers:
        if parse_confirmation(answer) == CONFIRM_REPEAT:
            continue
        step = next_step(slots)
        if step == CONFIRM:
            verdict = parse_confirmation(answer)
            if verdict == CONFIRM_YES:
                return {"slots": slots, "confirmed": True, "restarted": False}
            if verdict == CONFIRM_NO:
                slots = {}
                restarted = True
                continue
            # Incompris (dont "si" ambigu) : on ignore, on reposera le recap.
            continue
        if fill_from_text(slots, step, answer, context):
            restarted = False
        # Slot incompris : on ignore la reponse, les suivantes reessayent.
    return {"slots": slots, "confirmed": False, "restarted": restarted}


def slots_from_recap(text: str) -> dict[str, str]:
    """Slots embarques dans un recap (self-descriptif), {} si illisible.

    Format : "Récap : <école>, <problème>, <gravité>. ..." — probleme et
    gravite doivent etre canoniques, sinon on ne devine rien ({}).
    """
    value = (text or "").strip()
    if not value.startswith(RECAP_PREFIX):
        return {}
    body = value[len(RECAP_PREFIX):].split("?")[0].split(".")[0]
    parts = [p.strip() for p in body.split(",")]
    if len(parts) != 3 or any(p in ("", "?") for p in parts):
        return {}
    school, problem, severity = parts
    if problem not in PROBLEMS or severity not in (SEV_GRAVE, SEV_PAS_GRAVE):
        return {}
    return {SCHOOL: school, PROBLEM: problem, SEVERITY: severity}


def seeded_replay(
    history: Any, message: str, context: dict[str, Any], skip_current: bool
) -> dict[str, Any]:
    """Etat courant : graines du dernier recap + reponses post-recap rejouées.

    Le recap résume tout l'état antérieur : on ne rejoue que les réponses
    postérieures (rejouer les anciennes les ferait passer pour des
    confirmations). Sans recap (ou récap illisible) : pré-remplissage
    déclencheur + toutes les réponses, comme avant.
    """
    turns = _history_turns(history)
    last_recap = None
    for i, turn in enumerate(turns):
        if turn["role"] == "assistant" and (turn["content"] or "").strip().startswith(
            RECAP_PREFIX
        ):
            last_recap = i
    if last_recap is not None:
        seed = slots_from_recap(turns[last_recap]["content"])
        if seed:
            answers = [
                t["content"] for t in turns[last_recap + 1:] if t["role"] == "user"
            ]
            answers.append(message or "")
            if skip_current and answers:
                answers = answers[:-1]
            return _run_answers(seed, answers, context)
    trigger, answers = collect_answers(history, message)
    if skip_current and answers:
        answers = answers[:-1]
    slots = prefill_from_trigger(trigger or "", context) if trigger else {}
    if trigger is None and not session_in_progress(history):
        slots = prefill_from_trigger(message, context)
    return _run_answers(slots, answers, context)


def _ask_step(
    step: str, slots: dict[str, Any], context: dict[str, Any], lang: str
) -> dict[str, Any]:
    return {"status": "ask", "step": step,
            "question": ask(step, slots, lang),
            "slots": dict(slots), "chips": guided_chips(step, context)}


def _ask_confirm(slots: dict[str, Any], lang: str) -> dict[str, Any]:
    return {"status": "ask", "step": CONFIRM,
            "question": ask(CONFIRM, slots, lang),
            "slots": dict(slots), "chips": guided_chips(CONFIRM)}


def _is_dua(lang: str) -> bool:
    return str(lang or "fr").lower().startswith(("dua", "douala"))


def build_report_text(slots: dict[str, Any]) -> str:
    """Texte de bascule vers le flux normal (apres confirmation oui)."""
    return (
        "Signaler une panne : \u00e9cole "
        f"{slots.get(SCHOOL, '?')}, probl\u00e8me {slots.get(PROBLEM, '?')}, "
        f"gravit\u00e9 {slots.get(SEVERITY, '?')}."
    )


def resolve_guided_lang(request: Any) -> str:
    """Langue du dialogue guide : "dua" si demandee, sinon "fr"."""
    for candidate in (getattr(request, "language", None),
                      getattr(request, "lang", None)):
        if isinstance(candidate, str) and candidate.strip().lower().startswith(
                ("dua", "douala")):
            return "dua"
    try:
        context = request.context.model_dump()
    except (AttributeError, ValueError):
        context = {}
    if isinstance(context, dict):
        for key in ("language", "lang", "locale"):
            value = context.get(key)
            if isinstance(value, str) and value.strip().lower().startswith(
                    ("dua", "douala")):
                return "dua"
    return "fr"
