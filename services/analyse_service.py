"""Service d'analyse — calcule finance + scoring pour chaque bien et persiste.

Crée une nouvelle ligne `Analyse` à chaque passage (historisation).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from sqlalchemy import select

from core.finance import (
    AmortissementParams,
    AnalysisParams,
    BienInput,
    CreditParams,
    FraisParams,
    TaxParams,
    analyser_bien,
)
from core.scoring import ScoringContext, ScoringWeights, scorer_bien
from data.database import session_scope
from data.models import Bien, Parametres, Ville
from data.repositories import add_analyse, get_parametres

logger = logging.getLogger(__name__)


def _params_from_db(p: Parametres) -> tuple[AnalysisParams, ScoringWeights, dict]:
    """Construit les paramètres finance + scoring + préférences depuis la DB."""
    analysis = AnalysisParams(
        credit=CreditParams(
            taux_annuel=p.taux_credit,
            taux_assurance_annuel=p.taux_assurance,
            duree_annees=p.duree_credit_annees,
            apport=p.apport_disponible,
        ),
        frais=FraisParams(
            frais_notaire_pct=p.frais_notaire_pct,
            vacance_locative_pct=p.vacance_locative_pct,
            frais_gestion_pct=p.frais_gestion_pct,
            assurance_pno_annuelle=p.assurance_pno_annuelle,
            entretien_pct_loyer=p.entretien_pct_loyer,
            charges_copro_part_locataire=p.charges_copro_part_locataire,
        ),
        tax=TaxParams(tmi=p.tmi),
        amort=AmortissementParams(),
    )
    weights = ScoringWeights(
        cashflow=p.poids_cashflow,
        rendement=p.poids_rendement,
        decote_dvf=p.poids_decote_dvf,
        dpe=p.poids_dpe,
        tension=p.poids_tension,
        distance=p.poids_distance,
        travaux=p.poids_travaux,
    )
    prefs = {
        "rendement_brut_cible": p.rendement_brut_min,
        "distance_max_paris_km": p.distance_max_paris_km,
        "exclure_dpe_fg": p.exclure_dpe_fg,
        "score_alerte_seuil": p.score_alerte_seuil,
    }
    return analysis, weights, prefs


def _hash_params(p: Parametres) -> str:
    snap = {
        "tmi": p.tmi, "taux": p.taux_credit, "duree": p.duree_credit_annees,
        "apport": p.apport_disponible, "fn": p.frais_notaire_pct,
        "vac": p.vacance_locative_pct, "gest": p.frais_gestion_pct,
        "pno": p.assurance_pno_annuelle, "ent": p.entretien_pct_loyer,
        "copro": p.charges_copro_part_locataire,
        "w": [p.poids_cashflow, p.poids_rendement, p.poids_decote_dvf,
              p.poids_dpe, p.poids_tension, p.poids_distance, p.poids_travaux],
        "prefs": [p.rendement_brut_min, p.distance_max_paris_km, p.exclure_dpe_fg],
    }
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]


def analyser_un_bien(bien_id: int) -> dict | None:
    """Calcule et persiste une nouvelle analyse pour un bien. Renvoie un résumé."""
    with session_scope() as s:
        bien = s.get(Bien, bien_id)
        if bien is None or bien.prix is None or bien.surface_m2 is None:
            logger.info("Bien %s ignoré (prix ou surface manquant)", bien_id)
            return None

        p = get_parametres(s)
        analysis_params, weights, prefs = _params_from_db(p)
        params_hash = _hash_params(p)

        # Si la ville est connue, utiliser son prix/m² médian pour la décote
        ville: Ville | None = bien.ville
        prix_m2_marche = ville.dvf_prix_m2_median if ville else None
        loyer_m2 = (ville.loyer_m2_estime if ville and ville.loyer_m2_estime else None)

        # Construit l'input finance (loyer fourni > estimé par €/m²)
        bien_input = BienInput(
            prix=float(bien.prix),
            surface_m2=float(bien.surface_m2),
            loyer_mensuel=float(bien.loyer_mensuel_estime) if bien.loyer_mensuel_estime else None,
            loyer_m2_mensuel=loyer_m2,
            travaux=float(bien.travaux_estimes or 0),
            mobilier=0.0,  # paramétrable plus tard
            charges_copro_annuelles=float(bien.charges_copro_annuelles or 0),
            taxe_fonciere_annuelle=float(bien.taxe_fonciere_annuelle or 0),
            dpe=bien.dpe,
        )

        analyse = analyser_bien(bien_input, analysis_params)

        prix_m2_bien = (
            bien.prix / bien.surface_m2 if bien.prix and bien.surface_m2 else None
        )

        ctx = ScoringContext(
            dvf_prix_m2_median=prix_m2_marche,
            population=ville.population if ville else None,
            distance_paris_km=ville.distance_paris_km if ville else None,
            rendement_brut_cible=prefs["rendement_brut_cible"],
            distance_max_paris_km=prefs["distance_max_paris_km"],
            exclure_dpe_fg=prefs["exclure_dpe_fg"],
        )
        score = scorer_bien(
            analyse=analyse,
            prix_m2_bien=prix_m2_bien,
            ctx=ctx,
            weights=weights,
            dpe=bien.dpe,
            annee_construction=bien.annee_construction,
        )

        snapshot = {
            "finance": analyse.to_dict(),
            "scoring": score.to_dict(),
            "prix_m2_bien": prix_m2_bien,
            "prix_m2_marche": prix_m2_marche,
        }
        add_analyse(
            s,
            bien_id=bien_id,
            parametres_hash=params_hash,
            cout_total=analyse.cout_total,
            mensualite_credit=analyse.mensualite_totale,
            loyer_mensuel=analyse.loyer_mensuel,
            charges_annuelles=analyse.charges_annuelles_proprio,
            rendement_brut=analyse.rendement_brut,
            rendement_net=analyse.rendement_net,
            regime_optimal=analyse.regime_optimal,
            impot_annuel=analyse.impot_annuel,
            cashflow_mensuel=analyse.cashflow_mensuel,
            cashflow_annuel=analyse.cashflow_annuel,
            rendement_net_net=analyse.rendement_net_net,
            score=score.score,
            score_details=score.to_dict(),
            snapshot=snapshot,
        )

        return {
            "bien_id": bien_id,
            "score": score.score,
            "exclu": score.exclu,
            "regime_optimal": analyse.regime_optimal,
            "cashflow_mensuel": analyse.cashflow_mensuel,
            "rendement_brut": analyse.rendement_brut,
            "seuil_alerte": prefs["score_alerte_seuil"],
        }


def reanalyser_tous() -> dict:
    """Recalcule l'analyse pour tous les biens actifs en base."""
    with session_scope() as s:
        ids = [b.id for b in s.scalars(select(Bien).where(Bien.actif.is_(True)))]
    n_ok = n_err = 0
    for bid in ids:
        try:
            analyser_un_bien(bid)
            n_ok += 1
        except Exception:
            logger.exception("Erreur analyse bien %s", bid)
            n_err += 1
    return {"total": len(ids), "ok": n_ok, "erreurs": n_err}
