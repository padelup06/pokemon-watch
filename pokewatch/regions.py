"""Les 13 régions de France métropolitaine : salon Discord, rôle et zones de recherche des magasins.

Chaque région est couverte par un ou plusieurs cercles (code postal, rayon en km) autour de
ses grandes villes. Le 06 garde sa propre zone, vérifiée plus souvent.
"""

REGIONS = [
    # clé (ligne du secret GitHub), nom (rôle Discord), salon, émoji, cercles
    ("idf", "Île-de-France", "alertes-ile-de-france", "🗼", [("75001", 70)]),
    ("ara", "Auvergne-Rhône-Alpes", "alertes-auvergne-rhone-alpes", "⛰️", [("69001", 120), ("63000", 80)]),
    ("paca", "Provence-Alpes-Côte d'Azur", "alertes-paca", "☀️", [("13001", 120)]),
    ("occ", "Occitanie", "alertes-occitanie", "🏉", [("31000", 120), ("34000", 100)]),
    ("naq", "Nouvelle-Aquitaine", "alertes-nouvelle-aquitaine", "🍇", [("33000", 130), ("87000", 100), ("86000", 80)]),
    ("hdf", "Hauts-de-France", "alertes-hauts-de-france", "🍟", [("59000", 100), ("80000", 80)]),
    ("ge", "Grand Est", "alertes-grand-est", "🥨", [("67000", 100), ("54000", 90), ("51100", 80)]),
    ("pdl", "Pays de la Loire", "alertes-pays-de-la-loire", "🏰", [("44000", 120), ("49000", 70)]),
    ("bre", "Bretagne", "alertes-bretagne", "🌊", [("35000", 120), ("29200", 80)]),
    ("nor", "Normandie", "alertes-normandie", "🍎", [("76000", 90), ("14000", 90)]),
    ("bfc", "Bourgogne-Franche-Comté", "alertes-bourgogne-franche-comte", "🍷", [("21000", 120), ("25000", 80)]),
    ("cvl", "Centre-Val de Loire", "alertes-centre-val-de-loire", "🏯", [("45000", 120), ("37000", 70)]),
    ("cor", "Corse", "alertes-corse", "🏝️", [("20000", 100), ("20200", 80)]),
]
