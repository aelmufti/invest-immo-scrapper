"""Tests du parseur d'annonces."""

from __future__ import annotations

from core.parser import parser_annonce


ANNONCE_TYPE = """
Vends bel appartement T3 de 65 m² au 2ème étage,
construit en 1972, classe énergétique D, GES C.
Prix : 165 000 € net vendeur.
Charges de copropriété : 1 200 € / an.
Taxe foncière : 850 €.
Loyer estimé 750 €/mois.
72000 Le Mans, France.
"""


def test_extraction_globale():
    a = parser_annonce(ANNONCE_TYPE)
    assert a.type_bien == "appartement"
    assert a.prix == 165_000
    assert a.surface_m2 == 65
    assert a.nb_pieces == 3
    assert a.etage == 2
    assert a.annee_construction == 1972
    assert a.dpe == "D"
    assert a.ges == "C"
    assert a.charges_copro_annuelles == 1200
    assert a.taxe_fonciere_annuelle == 850
    assert a.loyer_mensuel_estime == 750
    assert a.code_postal == "72000"
    assert a.ville_nom == "Le Mans"


def test_texte_vide():
    a = parser_annonce("")
    assert a.prix is None
    assert a.surface_m2 is None


def test_prix_avec_espace_insecable():
    a = parser_annonce("Prix : 125\u202f000 €")
    assert a.prix == 125_000


def test_charges_mensuelles_converties():
    a = parser_annonce("charges 150 €/mois - appartement T2 30 m²")
    assert a.charges_copro_annuelles == 1800.0


def test_dpe_g_capture():
    a = parser_annonce("DPE G - à rénover. 80 000 € pour 40 m². 75011 Paris")
    assert a.dpe == "G"
    assert a.code_postal == "75011"
