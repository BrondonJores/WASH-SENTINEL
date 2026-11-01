"""Tests chantier 3/9 : suggestions « vouliez-vous dire ? » (place_suggest)."""
from __future__ import annotations

from app.place_suggest import SEUIL, suggest_places

CONTEXT = {
    "schools": [
        {"school_name": "École Primaire de Nkol", "district": "Mvila"},
        {"school_name": "École Publique de Biyem", "district": "Mvila"},
        {"school_name": "Lycée de Sangmélima", "district": "Dja-et-Lobo"},
        {"school_name": "École de Kribi Centre", "district": "Océan"},
    ],
    "incidents": [{"district": "Mvila"}, {"district": "Vallée-du-Ntem"}],
}


def test_typo_nkole_suggests_nkol():
    out = suggest_places("Il y a une panne à l'école de Nkole", CONTEXT)
    assert out["fragment"] == "Nkole"
    assert out["suggestions"], "faute de frappe Nkole -> suggestion attendue"
    top = out["suggestions"][0]
    assert top["kind"] == "school"
    assert "nkol" in top["label"].lower().replace("é", "e")


def test_typo_mvilla_suggests_mvila_district():
    out = suggest_places("Résume le district de Mvilla", CONTEXT)
    assert out["fragment"] == "Mvilla"
    labels = [(s["label"], s["kind"]) for s in out["suggestions"]]
    assert ("Mvila", "district") in labels


def test_fragment_case_accents_insensibles():
    out = suggest_places("PANNE SUR L'ECOLE DE nKoLe", CONTEXT)
    assert out["fragment"] == "nKoLe"
    assert out["suggestions"]
    assert "nkol" in out["suggestions"][0]["label"].lower().replace("é", "e")


def test_inconnu_total_donne_echantillons():
    out = suggest_places("panne à Zzzzxqw", CONTEXT)
    assert out["fragment"] == "Zzzzxqw"
    assert out["suggestions"] == []
    assert len(out["ecoles_sample"]) == 3
    assert set(out["districts_sample"]) == {
        "Mvila", "Dja-et-Lobo", "Océan", "Vallée-du-Ntem"}
    assert out["insight"], "jamais un mur : insight obligatoire"


def test_contexte_vide_aide_generique():
    for ctx in ({}, {"schools": [], "incidents": []}):
        out = suggest_places("panne à Nkole", ctx)
        assert out["suggestions"] == []
        assert out["ecoles_sample"] == []
        assert out["districts_sample"] == []
        assert "école" in out["insight"] and "district" in out["insight"]


def test_seuil_filtre_scores_faibles():
    assert SEUIL == 0.45
    out = suggest_places("panne à Xyzztop", CONTEXT)
    assert out["fragment"] == "Xyzztop"
    assert out["suggestions"] == []
    # ... mais une quasi-exactitude passe toujours le seuil.
    out2 = suggest_places("panne à Nkol", CONTEXT)
    assert any("nkol" in s["label"].lower().replace("é", "e")
               for s in out2["suggestions"])


def test_questions_cliquables_non_vides():
    out = suggest_places("problème d'eau pour Nkole", CONTEXT)
    assert out["suggestions"]
    for s in out["suggestions"]:
        assert s["label"] and s["kind"] in ("school", "district")
        assert s["question"] and len(s["question"]) > len(s["label"])
        assert s["label"] in s["question"]
    ecole_q = next(s["question"] for s in out["suggestions"]
                   if s["kind"] == "school")
    assert ecole_q.startswith("Analyser")


def test_contrat_retour_et_limite():
    out = suggest_places("panne vers Mvila", CONTEXT, limit=1)
    assert set(out) == {"insight", "fragment", "suggestions",
                        "ecoles_sample", "districts_sample"}
    assert len(out["suggestions"]) <= 1
    out3 = suggest_places("panne vers Mvila", CONTEXT, limit=3)
    assert len(out3["suggestions"]) <= 3
