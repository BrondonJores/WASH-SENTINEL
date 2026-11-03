"""Cartes de guidage : chaque erreur d'outil devient une aide simple.

Chantier 1/9 — JAMAIS de vide : quand un outil retourne {"error": ...},
build_guidance_card() construit une carte AgentCard(type="guidance") qui dit
ce qui s'est passé avec des mots simples et propose des questions cliquables.

Ton : francais parle, phrases courtes, zero jargon (lu a voix haute).
"""
from __future__ import annotations

import re
from typing import Any

from app.router import normalize as _norm
from app.schemas import AgentCard

# Familles d'erreur detectees dans les retours {"error": ...} des outils.
FAMILY_LIEU = "lieu_inconnu"
FAMILY_PERIODE = "periode_vide"
FAMILY_DONNEES = "donnees_absentes"
FAMILY_PARAMETRE = "parametre_manquant"
FAMILY_FILE = "file_inconnue"
FAMILY_DEFAUT = "defaut"

#: REPLI historique — noms de districts seedés en dur, utilisés UNIQUEMENT
#: quand l'appelant ne fournit pas d'exemples via `district_examples`
#: (agent_loop._build_cards les tire du contexte : source préférée).
DISTRICT_EXAMPLES = "Mvila, Wouri, Yaoundé, Douala"

#: Période proposée par l'action "Voir une période plus longue" (jours).
GUIDANCE_PERIOD_DAYS = 90

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
                  "question": f"Et sur les {GUIDANCE_PERIOD_DAYS} derniers jours ?"}

_ACTION_DISTRICTS_EN = {"label": "See all districts",
                        "question": "Which districts are tracked?"}
_ACTION_SCHOOLS_EN = {"label": "See tracked schools",
                      "question": "Which schools are tracked?"}
_ACTION_RECENT_EN = {"label": "See latest events",
                     "question": "What are the latest reported incidents?"}
_ACTION_PERIOD_EN = {"label": "See a longer period",
                     "question": f"And over the last {GUIDANCE_PERIOD_DAYS} days?"}

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


_FAMILY_GUIDANCE_EN: dict[str, dict[str, Any]] = {
    FAMILY_LIEU: {
        "title": "Can't find that place",
        "insight": "The name given doesn't match any tracked place.",
        "explication": ("Check the name letter by letter. "
                        "One accent or typo is enough to block the search."),
        "causes": [
            "The name is misspelled.",
            "That place is not tracked yet.",
            "You are searching a school by a neighborhood name.",
        ],
        "actions": [_ACTION_SCHOOLS_EN, _ACTION_DISTRICTS_EN],
    },
    FAMILY_PERIODE: {
        "title": "Nothing in this period",
        "insight": "Nothing to report on the requested days.",
        "explication": ("The search worked. There is just nothing to show "
                        "for this period. That is often good news."),
        "causes": [
            "The period is too short.",
            "Nothing really happened.",
            "Events are older.",
        ],
        "actions": [_ACTION_PERIOD_EN, _ACTION_RECENT_EN],
    },
    FAMILY_DONNEES: {
        "title": "No data for now",
        "insight": "The information hasn't arrived yet.",
        "explication": ("The list of schools and breakdowns is empty or not sent "
                        "yet. Without it, nothing can be computed."),
        "causes": [
            "Data hasn't been sent yet.",
            "The connection cut the upload.",
            "The chosen filter keeps nothing.",
        ],
        "actions": [_ACTION_SCHOOLS_EN, _ACTION_RECENT_EN],
    },
    FAMILY_PARAMETRE: {
        "title": "Missing information",
        "insight": "The question is not specific enough.",
        "explication": ("Tell me at least a school or district name, "
                        "and what you want to know."),
        "causes": [
            "The school name is missing.",
            "The district name is missing.",
            "The question is too vague.",
        ],
        "actions": [_ACTION_SCHOOLS_EN, _ACTION_DISTRICTS_EN],
    },
    FAMILY_FILE: {
        "title": "Queue not found",
        "insight": "The pending messages can't be found.",
        "explication": ("Messages kept offline aren't visible here. "
                        "They may already be sent, "
                        "or kept on another device."),
        "causes": [
            "Messages already went out.",
            "They are kept on another device.",
            "The list isn't loaded yet.",
        ],
        "actions": [
            {"label": "Check the connection",
             "question": "Is the connection back? What should I do?"},
            _ACTION_RECENT_EN,
        ],
    },
    FAMILY_DEFAUT: {
        "title": "That didn't work",
        "insight": "The search ran into a problem.",
        "explication": ("Something blocked on our side. "
                        "Retry with a simple question, "
                        "like a school name."),
        "causes": [
            "A temporary service issue.",
            "The question mixes two requests.",
            "An expected detail is missing.",
        ],
        "actions": [
            {"label": "Ask a simple question",
             "question": "Which schools are tracked?"},
            _ACTION_RECENT_EN,
        ],
    },
}


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
                      actions: list[dict[str, str]],
                      district_examples: str | None = None,
                      lang: str = "fr",
                      ) -> tuple[str, str, list[dict[str, str]]]:
    """Enrichit la carte selon l'outil appele (mapping par outil)."""
    use_en = str(lang or "fr").lower().startswith("en")
    err = _norm(error_text)
    if tool_name in _DISTRICT_TOOLS:
        # District inexistant : guider vers un nom valide.
        if family == FAMILY_LIEU or _has(err, "district"):
            examples = district_examples or DISTRICT_EXAMPLES
            prefix = (f"Check the name: {examples}… "
                      if use_en else f"Vérifiez le nom : {examples}… ")
            explication = prefix + explication
        _ensure_action(actions,
                       _ACTION_DISTRICTS_EN if use_en else _ACTION_DISTRICTS,
                       first=True)
    if tool_name in _SCHOOL_TOOLS:
        _ensure_action(actions,
                       _ACTION_SCHOOLS_EN if use_en else _ACTION_SCHOOLS,
                       first=(family == FAMILY_LIEU))
    return title, explication, actions


def _school_scoped_actions(school: str, lang: str = "fr") -> list[dict[str, str]]:
    """Actions cliquables restreintes à UNE école (discipline de périmètre)."""
    if str(lang or "fr").lower().startswith("en"):
        return [
            {"label": f"Trends for {school}",
             "question": f"Trends for {school}?"},
            {"label": f"Emergencies at {school}",
             "question": f"Any emergencies at {school}?"},
        ]
    return [
        {"label": f"Tendances de {school}",
         "question": f"Tendances de {school} ?"},
        {"label": f"Urgences à {school}",
         "question": f"Y a-t-il des urgences à {school} ?"},
    ]


# ---------------------------------------------------------------------------
# Clarification guidée : le périmètre exigé n'est pas nommé (« Compare un
# district ? » sans district). On repose LA question en une phrase et on
# propose des choix cliquables bâtis UNIQUEMENT sur les lieux du contexte
# (reçus en paramètres) : jamais de district ni d'école inventés.
# ---------------------------------------------------------------------------

#: La question de clarification (une phrase) par périmètre et par langue.
CLARIFY_QUESTIONS: dict[str, dict[str, str]] = {
    "district": {
        "fr": "De quel district s'agit-il ?",
        "en": "Which district do you mean?",
    },
    "school": {
        "fr": "De quelle école s'agit-il ?",
        "en": "Which school do you mean?",
    },
}

#: Mots génériques (normalisés, cf. _norm) ignorés pour le nom court d'école.
_SHORT_NAME_SKIPS = frozenset({
    "ecole", "ecoles", "lycee", "lycees", "college", "colleges",
    "publique", "publiques", "public", "publics",
    "rural", "rurale", "rurales", "ruraux",
    "primaire", "primaires", "maternelle", "maternelles",
    "secondaire", "secondaires", "groupe", "groupement",
    "scolaire", "scolaires", "centre", "centres",
    "de", "du", "des", "le", "la", "les", "l", "d", "un", "une",
    "au", "aux", "en", "et",
})

#: Gabarits de choix district par intention (question complète + lieu réel).
_DISTRICT_CHOICE_TEMPLATES: dict[str, dict[str, str]] = {
    "compare": {"fr": "Comparer le district {place}",
                "en": "Compare district {place}"},
    "trends": {"fr": "Tendances du district {place} ?",
               "en": "Trends for district {place}?"},
    "budget": {"fr": "Budget réparations du district {place} ?",
               "en": "Repair budget for district {place}?"},
    "map": {"fr": "Voir le district {place} sur la carte",
            "en": "Show district {place} on the map"},
    "journal": {"fr": "Interventions du district {place}",
                "en": "Interventions in district {place}"},
    "recap": {"fr": "Résumer le district {place}",
              "en": "Summarize district {place}"},
}

#: Gabarits de choix école par intention (nom court + lieu réel).
_SCHOOL_CHOICE_TEMPLATES: dict[str, dict[str, str]] = {
    "trends": {"fr": "Tendances de {place} ?",
               "en": "Trends for {place}?"},
    "budget": {"fr": "Budget réparations de {place} ?",
               "en": "Repair budget for {place}?"},
    "map": {"fr": "Voir {place} sur la carte",
            "en": "Show {place} on the map"},
    "journal": {"fr": "Interventions à {place} ?",
                "en": "Interventions at {place}?"},
    "recap": {"fr": "Récap de {place} ?",
              "en": "Summary for {place}?"},
    "default": {"fr": "Que se passe-t-il à {place} ?",
                "en": "What is happening at {place}?"},
}


def clarify_question(kind: str, lang: str = "fr") -> str:
    """La question de clarification en une phrase (repli FR district)."""
    entry = CLARIFY_QUESTIONS.get(kind or "", CLARIFY_QUESTIONS["district"])
    if str(lang or "").strip().lower().startswith("en"):
        return entry["en"]
    return entry["fr"]


def short_school_name(label: str) -> str:
    """Nom court distinctif (« École Rurale de Ngok » -> « Ngok »).

    Premier mot non générique (>= 4 lettres), casse d'origine ; libellé
    complet en repli. Ne lève jamais.
    """
    try:
        text = str(label or "").strip()
        if not text:
            return ""
        for word in re.split(r"[\s\-'’]+", text):
            folded = _norm(word)
            if len(folded) >= 4 and folded not in _SHORT_NAME_SKIPS:
                return word.strip(".,;:!?()\"'")
        return text
    except Exception:
        return str(label or "")


def clarify_choices(kind: str, intent: str = "recap",
                   schools: Any = (), districts: Any = (),
                   lang: str = "fr", limit: int = 3) -> list[str]:
    """Choix cliquables de clarification (questions complètes, fonction pure).

    Chaque choix cite un lieu REÇU (écoles/districts du contexte) : sans
    lieu, liste vide (l'appelant replie sur les relances actuelles) ; jamais
    de lieu inventé, jamais d'erreur. Comparaison d'écoles : paires réelles
    (« Comparer Ngok et Bonanjo ») quand au moins deux écoles sont connues.
    """
    try:
        use_en = str(lang or "").strip().lower().startswith("en")
        count = max(1, min(int(limit or 3), 10))
    except (TypeError, ValueError):
        use_en, count = False, 3
    code = "en" if use_en else "fr"
    try:
        if kind == "district":
            places: list[str] = []
            seen: set[str] = set()
            for district in districts or ():
                name = str(district or "").strip()
                key = _norm(name)
                if name and key and key not in seen:
                    seen.add(key)
                    places.append(name)
            template = _DISTRICT_CHOICE_TEMPLATES.get(
                intent or "", _DISTRICT_CHOICE_TEMPLATES["recap"])[code]
            return [template.format(place=p) for p in places[:count]]
        if kind == "school":
            shorts: list[str] = []
            seen_shorts: set[str] = set()
            for school in schools or ():
                short = short_school_name(school)
                key = _norm(short)
                if short and key and key not in seen_shorts:
                    seen_shorts.add(key)
                    shorts.append(short)
            if not shorts:
                return []
            if (intent or "") == "compare" and len(shorts) >= 2:
                pairs = [(shorts[i], shorts[j])
                         for i in range(len(shorts))
                         for j in range(i + 1, len(shorts))][:count]
                if use_en:
                    return [f"Compare {a} and {b}" for a, b in pairs]
                return [f"Comparer {a} et {b}" for a, b in pairs]
            if (intent or "") == "compare":
                single = {"fr": "Comparer l'école {place}",
                          "en": "Compare school {place}"}[code]
                return [single.format(place=s) for s in shorts[:count]]
            template = _SCHOOL_CHOICE_TEMPLATES.get(
                intent or "", _SCHOOL_CHOICE_TEMPLATES["default"])[code]
            return [template.format(place=s) for s in shorts[:count]]
        return []
    except Exception:
        return []


def build_guidance_card(tool_name: str, observation: dict,
                        district_examples: str | None = None,
                        scope_school: str | None = None) -> AgentCard | None:
    """Construit une carte de guidage depuis une observation en erreur.

    Retourne None si l'observation ne contient pas d'erreur.
    Ne leve jamais : en cas de doute, retourne la carte generique-utile
    (jamais de vide).
    `district_examples` : noms fournis par l'appelant (contexte reel) ;
    à défaut, repli historique DISTRICT_EXAMPLES.
    `scope_school` : périmètre école unique — les actions restent sur cette
    école (ni districts, ni autres écoles) ; None = comportement historique.
    """
    lang = ""
    try:
        if not isinstance(observation, dict):
            return None
        raw_error = observation.get("error")
        if not raw_error:
            return None
        lang = str(observation.get("lang") or "fr")
        use_en = lang.lower().startswith("en")
        error_text = str(raw_error)
        name = str(tool_name or "")
        family = _detect_family(name, error_text)
        template = (_FAMILY_GUIDANCE_EN if use_en else _FAMILY_GUIDANCE)[family]
        title = str(template["title"])
        insight = str(template["insight"])
        explication = str(template["explication"])
        causes = [str(c) for c in template["causes"]]
        actions = [dict(a) for a in template["actions"]]
        if scope_school:
            # Périmètre école : actions cantonnées à l'école, sans enrichissement
            # district (ni exemples de districts, ni renvois larges).
            actions = _school_scoped_actions(str(scope_school), lang)
        else:
            title, explication, actions = _apply_tool_hints(
                name, family, error_text, title, explication, actions,
                district_examples=district_examples, lang=lang)
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
        use_en = str(lang or "fr").lower().startswith("en")
        fallback = (_FAMILY_GUIDANCE_EN if use_en else _FAMILY_GUIDANCE)[FAMILY_DEFAUT]
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
