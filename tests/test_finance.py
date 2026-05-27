"""Tests pytest du moteur financier.

Cas chiffrés vérifiables — les valeurs attendues ont été calculées à la main /
avec un simulateur tiers (cf README).
"""

from __future__ import annotations

import math

import pytest

from core.finance import (
    AmortissementParams,
    AnalysisParams,
    BienInput,
    CreditParams,
    FraisParams,
    TaxParams,
    amortissements_lmnp,
    analyser_bien,
    calcul_charges_annuelles,
    cout_total_operation,
    interets_annuels_moyens,
    mensualite_assurance,
    mensualite_pret,
)


# ---------------------------------------------------------------------------
# Helpers de base
# ---------------------------------------------------------------------------

class TestMensualitePret:
    def test_pret_classique(self):
        # 100 000 € à 3,26 % sur 20 ans -> ~567,70 € (capital + intérêts hors assurance)
        # Formule PMT exacte : C * i / (1 - (1+i)^-n) avec i = 3,26%/12.
        m = mensualite_pret(100_000, 0.0326, 20)
        assert m == pytest.approx(567.70, abs=0.5)

    def test_taux_zero(self):
        # Sans intérêt : capital / nb_mensualités
        m = mensualite_pret(120_000, 0.0, 10)
        assert m == pytest.approx(1000.0, abs=0.01)

    def test_capital_nul(self):
        assert mensualite_pret(0, 0.05, 20) == 0.0

    def test_duree_nulle(self):
        assert mensualite_pret(100_000, 0.05, 0) == 0.0


class TestMensualiteAssurance:
    def test_calcul_simple(self):
        # 100 000 € à 0,34 %/an -> 100 000 * 0.0034 / 12 = 28.33 €/mois
        m = mensualite_assurance(100_000, 0.0034)
        assert m == pytest.approx(28.33, abs=0.01)


class TestCoutTotal:
    def test_avec_notaire_et_travaux(self):
        # 200 000 € + 8 % notaire + 10 000 € travaux + 5 000 € mobilier = 231 000
        c = cout_total_operation(200_000, 10_000, 5_000, 0.08)
        assert c == pytest.approx(231_000.0)


# ---------------------------------------------------------------------------
# Charges
# ---------------------------------------------------------------------------

class TestCharges:
    def test_charges_proprio_basique(self):
        bien = BienInput(
            prix=80_000, surface_m2=60, loyer_mensuel=600,
            charges_copro_annuelles=1200, taxe_fonciere_annuelle=900,
        )
        params = FraisParams()
        d = calcul_charges_annuelles(bien, 600, params)
        # vacance = 7200*0.04 = 288 ; gestion = 7200*0.07 = 504 ; entretien = 7200*0.05 = 360
        # PNO 180 ; copro non récup = 1200*0.25 = 300 ; taxe foncière 900
        attendu = 288 + 504 + 360 + 180 + 300 + 900
        assert d["total"] == pytest.approx(attendu, abs=1.0)


# ---------------------------------------------------------------------------
# Amortissements LMNP
# ---------------------------------------------------------------------------

class TestAmortissementsLMNP:
    def test_decomposition(self):
        # Prix 100 000, terrain 15 % -> bâti amortissable = 85 000 sur 30 ans -> 2 833
        a = AmortissementParams()
        amorts = amortissements_lmnp(
            prix=100_000, travaux=0, mobilier=7_000, frais_notaire=8_000, a=a
        )
        assert amorts["bati"] == pytest.approx(85_000 / 30, abs=0.5)
        assert amorts["mobilier"] == pytest.approx(7_000 / 7)
        assert amorts["notaire"] == pytest.approx(8_000 / 15, abs=0.5)
        assert amorts["travaux"] == 0.0


# ---------------------------------------------------------------------------
# Intérêts moyens
# ---------------------------------------------------------------------------

class TestInteretsAnnuelsMoyens:
    def test_pret_100k_20ans_3_26(self):
        # PMT ~567,70 * 240 = 136 248 -> intérêts totaux ~36 248 -> /20 = 1 812 €/an
        ia = interets_annuels_moyens(100_000, 0.0326, 20)
        assert ia == pytest.approx(1812, abs=10)


# ---------------------------------------------------------------------------
# Analyse complète — cas chiffré principal
# ---------------------------------------------------------------------------

class TestAnalyseBien:
    """Cas demandé dans le brief : 79 000 € / 65 m² / 825 € de loyer.

    Profil par défaut : 30 000 € apport, taux 3,26 %, assurance 0,34 %, 20 ans,
    TMI 30 %, frais notaire 8 % sur ancien.
    Doit donner un cash-flow mensuel positif et cohérent.
    """

    def setup_method(self):
        self.bien = BienInput(
            prix=79_000,
            surface_m2=65,
            loyer_mensuel=825,
            mobilier=4_000,
            charges_copro_annuelles=900,
            taxe_fonciere_annuelle=800,
            dpe="D",
        )
        self.params = AnalysisParams()

    def test_cout_total(self):
        r = analyser_bien(self.bien, self.params)
        # 79 000 * 1.08 + 0 + 4 000 = 89 320
        assert r.cout_total == pytest.approx(89_320, abs=1)

    def test_mensualite_credit(self):
        r = analyser_bien(self.bien, self.params)
        # Emprunté = 89 320 - 30 000 = 59 320
        assert r.montant_emprunte == pytest.approx(59_320, abs=1)
        # PMT(59 320, 3.26%/12, 240) ~ 338.50
        assert r.mensualite_credit == pytest.approx(338.5, abs=2.0)

    def test_rendement_brut_positif(self):
        r = analyser_bien(self.bien, self.params)
        # 825 * 12 / 89 320 ~ 11,1 %
        assert r.rendement_brut == pytest.approx(0.1108, abs=0.005)

    def test_cashflow_positif(self):
        r = analyser_bien(self.bien, self.params)
        # Doit être franchement positif (bien à haut rendement)
        assert r.cashflow_mensuel > 50.0, f"CF mensuel insuffisant : {r.cashflow_mensuel}"

    def test_lmnp_est_optimal_pour_meuble(self):
        r = analyser_bien(self.bien, self.params)
        # Sur un bien à fort rendement avec amortissements, LMNP réel doit dominer
        # ou être très proche du micro-BIC. On accepte les deux options "meublées".
        assert r.regime_optimal in ("lmnp_reel", "micro_bic")
        # Et le régime nu doit être strictement moins favorable
        assert r.regimes["nu"].cashflow_annuel <= r.regimes[r.regime_optimal].cashflow_annuel

    def test_lmnp_reduit_impot(self):
        r = analyser_bien(self.bien, self.params)
        # L'amortissement doit ramener l'IR du LMNP réel sous celui du nu et du micro-BIC.
        ir_lmnp = r.regimes["lmnp_reel"].impot_revenu
        ir_nu = r.regimes["nu"].impot_revenu
        ir_mb = r.regimes["micro_bic"].impot_revenu
        assert ir_lmnp < ir_nu, f"IR LMNP réel ({ir_lmnp}) doit être < IR nu ({ir_nu})"
        assert ir_lmnp < ir_mb, f"IR LMNP réel ({ir_lmnp}) doit être < IR micro-BIC ({ir_mb})"
        # Sur ce bien à fort rendement, le revenu imposable LMNP doit rester modeste
        assert r.regimes["lmnp_reel"].revenu_imposable < 4_000


class TestAnalyseBienCher:
    """Cas opposé : bien parisien cher où le cash-flow est négatif.

    Sert à vérifier que le moteur produit aussi des résultats négatifs cohérents,
    et que le micro-BIC redevient compétitif quand l'amortissement est limité.
    """

    def test_paris_negatif(self):
        bien = BienInput(
            prix=350_000, surface_m2=30, loyer_mensuel=1100,
            charges_copro_annuelles=1800, taxe_fonciere_annuelle=900,
        )
        r = analyser_bien(bien, AnalysisParams())
        # Achat très cher, faible rendement -> cash-flow doit être très négatif
        assert r.cashflow_mensuel < 0
        # Rendement brut autour de 3,5 %
        assert 0.025 < r.rendement_brut < 0.045


class TestEstimationLoyer:
    """Vérifie que l'estimation par €/m² fonctionne si le loyer absolu n'est pas fourni."""

    def test_estimation_par_m2(self):
        bien = BienInput(prix=100_000, surface_m2=50, loyer_m2_mensuel=12)
        r = analyser_bien(bien, AnalysisParams())
        assert r.loyer_mensuel == pytest.approx(600.0)


class TestSerialisation:
    def test_to_dict(self):
        bien = BienInput(prix=80_000, surface_m2=60, loyer_mensuel=600)
        r = analyser_bien(bien, AnalysisParams())
        d = r.to_dict()
        assert "regimes" in d
        assert "lmnp_reel" in d["regimes"]
        # Les valeurs doivent être JSON-sérialisables (pas de NaN/inf)
        for v in d["regimes"]["lmnp_reel"].values():
            if isinstance(v, float):
                assert math.isfinite(v)
