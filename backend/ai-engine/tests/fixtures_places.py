"""Fixtures de résolution de lieux (AXE 3) : typos, accents, noms courts, inconnus.

Chaque cas : (fragment, "school"|"district", label_attendu ou None).
Pool fermé (écoles + districts) ; le sweep des seuils (test_place_threshold)
mesure précision/rappel dessus et épingle le cutoff optimal.
"""
from __future__ import annotations

SCHOOLS = [
    "École Primaire de Nkol",
    "École Publique de Biyem",
    "Lycée de Sangmélima",
    "École de Kribi Centre",
    "École Publique de Bonanjo",
    "École Rurale de Ngok",
    "E1",
    "E2",
]

DISTRICTS = [
    "Mvila",
    "Dja-et-Lobo",
    "Océan",
    "Vallée-du-Ntem",
    "Wouri",
    "Douala",
]

#: (fragment, pool, label attendu ou None si aucune suggestion légitime)
PLACE_CASES: tuple[tuple[str, str, str | None], ...] = (
    # --- Typos écoles (doivent suggérer) ---
    ("Nkole", "school", "École Primaire de Nkol"),
    ("nKoLe", "school", "École Primaire de Nkol"),
    ("Nkol", "school", "École Primaire de Nkol"),
    ("Bonanjoo", "school", "École Publique de Bonanjo"),
    ("Biyen", "school", "École Publique de Biyem"),
    ("Kribbi", "school", "École de Kribi Centre"),
    ("Ngok", "school", "École Rurale de Ngok"),
    ("Ngo", "school", "École Rurale de Ngok"),
    ("Sangmelima", "school", "Lycée de Sangmélima"),
    ("Sangmélima", "school", "Lycée de Sangmélima"),
    ("Kribi", "school", "École de Kribi Centre"),
    ("EP Nkol", "school", "École Primaire de Nkol"),
    ("Centre", "school", "École de Kribi Centre"),
    # --- Typos districts (doivent suggérer) ---
    ("Mvilla", "district", "Mvila"),
    ("Mvla", "district", "Mvila"),
    ("Mvila", "district", "Mvila"),
    ("Wuri", "district", "Wouri"),
    ("Ocean", "district", "Océan"),
    ("Oceean", "district", "Océan"),
    ("Doualla", "district", "Douala"),
    ("Dja-et-lobo", "district", "Dja-et-Lobo"),
    ("Dja et Lobo", "district", "Dja-et-Lobo"),
    ("Vallee-du-Ntem", "district", "Vallée-du-Ntem"),
    ("Ntem", "district", "Vallée-du-Ntem"),
    # --- Noms courts exacts (idoines uniquement si exacts) ---
    ("E1", "school", "E1"),
    ("E2", "school", "E2"),
    # --- Inconnus / trop vagues (aucune suggestion) ---
    ("Zzzzxqw", "school", None),
    ("Xyzztop", "school", None),
    ("oua", "district", None),  # bug historique : "oua" matchait "Douala"
    ("Eau", "school", None),
    ("ecole", "school", None),  # générique seul
    ("Lycee", "school", None),  # générique seul
    ("le", "school", None),
    ("a", "district", None),
    ("Bi", "school", None),  # 2 lettres : trop ambigu
    ("de", "district", None),
    ("Kribi Zzz", "school", "École de Kribi Centre"),  # mot connu + déchet : suggestion tolérante
    ("Mvila-sur-Mer", "district", None),  # inconnu déguisé en connu
    ("Ngokoland", "school", None),
    ("Bon", "school", None),  # préfixe trop court, ambigu
)
