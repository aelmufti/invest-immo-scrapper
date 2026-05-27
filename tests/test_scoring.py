"""Tests pytest du module de scoring."""

from __future__ import annotations

import pytest

from core.finance import AnalysisParams, BienInput, analyser_bien
from core.scoring import (
    ScoreResult,
    ScoringContext,
    ScoringWeights,
    scorer_bien,
)


def _analyse(prix=80_000, surface=60, loyer=600) -> "AnalyseResult":
    bien = BienInput(prix=prix, surface_m2=surface, loyer_mensuel=loyer)
    return analyser_bien(bien, AnalysisParams())


class TestExclusionDPE:
    def test_dpe_g_est_exclu(self):
        a = _analyse()
        r = scorer_bien(
            analyse=a,
            prix_m2_bien=1300,
            ctx=ScoringContext(exclure_dpe_fg=True),
            dpe="G",
        )
        assert r.exclu is True
        assert r.score == 0.0
        assert "G" in (r.raison_exclusion or "")

    def test_dpe_g_non_exclu_si_pref_off(self):
        a = _analyse()
        r = scorer_bien(
            analyse=a,
            prix_m2_bien=1300,
            ctx=ScoringContext(exclure_dpe_fg=False),
            dpe="G",
        )
        assert r.exclu is False
        # Le sous-score DPE doit être bas (0)
        dpe_d = next(d for d in r.details if d.nom == "dpe")
        assert dpe_d.points_bruts == 0.0


class TestEchelleScores:
    """Vérifie que les sous-scores sont bornés sur [0, 100]."""

    def test_borne_inferieure_et_superieure(self):
        a = _analyse(prix=350_000, surface=30, loyer=1100)
        r = scorer_bien(
            analyse=a,
            prix_m2_bien=11_000,
            ctx=ScoringContext(
                dvf_prix_m2_median=9_000,
                population=2_000_000,
                distance_paris_km=0,
                rendement_brut_cible=0.07,
            ),
            dpe="E",
        )
        assert 0 <= r.score <= 100
        for d in r.details:
            assert 0 <= d.points_bruts <= 100


class TestPonderation:
    """Le score final est une moyenne pondérée — sa valeur doit dépendre des poids."""

    def test_score_change_avec_poids(self):
        a = _analyse()
        ctx = ScoringContext(dvf_prix_m2_median=1200, population=150_000, distance_paris_km=200)
        w1 = ScoringWeights(cashflow=100, rendement=0, decote_dvf=0, dpe=0,
                            tension=0, distance=0, travaux=0)
        w2 = ScoringWeights(cashflow=0, rendement=0, decote_dvf=0, dpe=100,
                            tension=0, distance=0, travaux=0)
        r1 = scorer_bien(analyse=a, prix_m2_bien=1300, ctx=ctx, weights=w1, dpe="D")
        r2 = scorer_bien(analyse=a, prix_m2_bien=1300, ctx=ctx, weights=w2, dpe="D")
        # Quand w1 est 100% cashflow, le score = sous-score cashflow.
        cf_pts = next(d for d in r1.details if d.nom == "cashflow").points_bruts
        dpe_pts = next(d for d in r2.details if d.nom == "dpe").points_bruts
        assert r1.score == pytest.approx(cf_pts, abs=0.5)
        assert r2.score == pytest.approx(dpe_pts, abs=0.5)


class TestDecoteDVF:
    def test_decote_donne_bonus(self):
        a = _analyse()
        ctx = ScoringContext(dvf_prix_m2_median=2000)
        # bien à 1500 €/m² avec marché à 2000 -> décote 25 % -> sous-score haut
        r_decote = scorer_bien(analyse=a, prix_m2_bien=1500, ctx=ctx, dpe="D")
        # bien à 2500 €/m² -> surcote 25 % -> sous-score bas
        r_surcote = scorer_bien(analyse=a, prix_m2_bien=2500, ctx=ctx, dpe="D")
        d1 = next(d for d in r_decote.details if d.nom == "decote_dvf").points_bruts
        d2 = next(d for d in r_surcote.details if d.nom == "decote_dvf").points_bruts
        assert d1 > 75
        assert d2 < 25


class TestCashflowScore:
    def test_cashflow_positif_haut(self):
        # Bien à fort rendement -> cash-flow > 300 -> 100 pts
        a = _analyse(prix=60_000, surface=50, loyer=700)
        r = scorer_bien(analyse=a, prix_m2_bien=1200,
                        ctx=ScoringContext(dvf_prix_m2_median=1300), dpe="D")
        cf = next(d for d in r.details if d.nom == "cashflow")
        assert cf.points_bruts >= 75

    def test_cashflow_negatif_bas(self):
        a = _analyse(prix=300_000, surface=30, loyer=900)
        r = scorer_bien(analyse=a, prix_m2_bien=10_000,
                        ctx=ScoringContext(dvf_prix_m2_median=9_500), dpe="D")
        cf = next(d for d in r.details if d.nom == "cashflow")
        assert cf.points_bruts < 25


class TestDistance:
    def test_paris_top(self):
        a = _analyse()
        r = scorer_bien(
            analyse=a, prix_m2_bien=1300,
            ctx=ScoringContext(distance_paris_km=0, distance_max_paris_km=400),
            dpe="D",
        )
        d = next(d for d in r.details if d.nom == "distance")
        assert d.points_bruts == 100.0

    def test_au_dela_du_seuil(self):
        a = _analyse()
        r = scorer_bien(
            analyse=a, prix_m2_bien=1300,
            ctx=ScoringContext(distance_paris_km=500, distance_max_paris_km=400),
            dpe="D",
        )
        d = next(d for d in r.details if d.nom == "distance")
        assert d.points_bruts == 0.0


class TestSerialisation:
    def test_to_dict_est_serialisable(self):
        a = _analyse()
        r = scorer_bien(analyse=a, prix_m2_bien=1300,
                        ctx=ScoringContext(), dpe="D")
        d = r.to_dict()
        assert "score" in d and "details" in d
        assert isinstance(d["details"], list) and len(d["details"]) == 7
