"""Moteur financier — calcul de cash-flow et rendement pour un investissement locatif.

Conçu pour être :
- Pur Python, sans dépendance à la base, facilement testable.
- Configurable : tous les hypothèses passent par des dataclasses paramétrables.
- Comparable : calcule les 3 régimes (nu, micro-BIC, LMNP réel) côte à côte.

Conventions :
- Tous les taux sont en décimal (3,26 % = 0.0326).
- Toutes les valeurs monétaires sont en euros.
- "net-net" = cash-flow après mensualité de crédit, charges, impôts et prélèvements
  sociaux.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Regime = Literal["nu", "micro_bic", "lmnp_reel"]

# Plafond micro-BIC meublé longue durée (loi fév. 2025, applicable 2026)
PLAFOND_MICRO_BIC_LD = 77_700.0
ABATTEMENT_MICRO_BIC = 0.50
PLAFOND_MICRO_FONCIER = 15_000.0
ABATTEMENT_MICRO_FONCIER = 0.30


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------

@dataclass
class CreditParams:
    """Paramètres du crédit immobilier."""

    taux_annuel: float = 0.0326          # taux nominal hors assurance
    taux_assurance_annuel: float = 0.0034  # assurance emprunteur (sur capital initial)
    duree_annees: int = 20
    apport: float = 30_000.0


@dataclass
class FraisParams:
    """Frais récurrents annuels et hypothèses d'exploitation."""

    frais_notaire_pct: float = 0.08      # % du prix (ancien)
    vacance_locative_pct: float = 0.04   # part du loyer annuel perdue
    frais_gestion_pct: float = 0.07      # honoraires d'agence sur loyers
    assurance_pno_annuelle: float = 180.0
    entretien_pct_loyer: float = 0.05    # provision entretien sur loyer annuel
    charges_copro_part_locataire: float = 0.75  # part récupérable sur locataire


@dataclass
class TaxParams:
    """Paramètres fiscaux."""

    tmi: float = 0.30                    # tranche marginale d'imposition
    # Prélèvements sociaux sur revenus fonciers / BIC LMNP non-pro.
    # Valeur correcte 2026 : 17,2 % (CSG 9,2 + CRDS 0,5 + prélèv. solidarité 7,5).
    # Editable par l'utilisateur si une réforme change ce taux.
    prelevements_sociaux: float = 0.172


@dataclass
class AmortissementParams:
    """Durées d'amortissement pour le régime LMNP au réel."""

    duree_bati_annees: int = 30
    duree_mobilier_annees: int = 7
    duree_notaire_annees: int = 15
    duree_travaux_annees: int = 10
    part_terrain: float = 0.15           # non amortissable


@dataclass
class BienInput:
    """Caractéristiques du bien à analyser."""

    prix: float
    surface_m2: float
    loyer_mensuel: float | None = None    # si None, estimé via loyer_m2
    loyer_m2_mensuel: float | None = None # €/m²/mois — utilisé si loyer non fourni
    travaux: float = 0.0
    mobilier: float = 0.0
    charges_copro_annuelles: float = 0.0   # total annuel (récupérable et non)
    taxe_fonciere_annuelle: float = 0.0
    dpe: str | None = None


@dataclass
class AnalysisParams:
    """Bundle de tous les paramètres de configuration."""

    credit: CreditParams = field(default_factory=CreditParams)
    frais: FraisParams = field(default_factory=FraisParams)
    tax: TaxParams = field(default_factory=TaxParams)
    amort: AmortissementParams = field(default_factory=AmortissementParams)


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

@dataclass
class RegimeResult:
    """Résultat fiscal pour un régime donné."""

    nom: Regime
    revenu_imposable: float
    impot_revenu: float
    prelevements_sociaux: float
    impot_total: float
    cashflow_annuel: float          # après impôts
    cashflow_mensuel: float
    rendement_net_net: float        # cashflow annuel + part amortissement crédit / coût total ? Non — on garde simple : cashflow / coût total


@dataclass
class AnalysisResult:
    """Résultat complet pour un bien."""

    # Entrées rappelées
    prix: float
    surface_m2: float
    loyer_mensuel: float

    # Financement
    cout_total: float
    apport: float
    montant_emprunte: float
    mensualite_credit: float
    mensualite_assurance: float
    mensualite_totale: float        # crédit + assurance
    cout_total_credit: float        # intérêts + assurance sur toute la durée

    # Exploitation
    loyer_annuel: float
    charges_annuelles_proprio: float  # ce qui reste à la charge du propriétaire
    charges_detail: dict

    # Rendements
    rendement_brut: float
    rendement_net: float              # avant impôts mais après charges

    # Régimes fiscaux
    regimes: dict[Regime, RegimeResult]
    regime_optimal: Regime

    # Champs pratiques pour l'historisation
    cashflow_mensuel: float           # = regimes[regime_optimal].cashflow_mensuel
    cashflow_annuel: float
    impot_annuel: float
    rendement_net_net: float

    def to_dict(self) -> dict:
        out = asdict(self)
        out["regimes"] = {k: asdict(v) for k, v in self.regimes.items()}
        return out


# ---------------------------------------------------------------------------
# Helpers — formules de base
# ---------------------------------------------------------------------------

def mensualite_pret(capital: float, taux_annuel: float, duree_annees: int) -> float:
    """Mensualité d'un prêt amortissable (formule PMT classique)."""
    if capital <= 0 or duree_annees <= 0:
        return 0.0
    n = duree_annees * 12
    if taux_annuel <= 0:
        return capital / n
    i = taux_annuel / 12.0
    return capital * i / (1.0 - (1.0 + i) ** (-n))


def mensualite_assurance(capital_initial: float, taux_annuel_assurance: float) -> float:
    """Prime mensuelle d'assurance emprunteur sur capital initial constant."""
    return capital_initial * taux_annuel_assurance / 12.0


def cout_total_operation(
    prix: float, travaux: float, mobilier: float, frais_notaire_pct: float
) -> float:
    """Coût d'acquisition total : prix + notaire + travaux + mobilier."""
    return prix * (1.0 + frais_notaire_pct) + travaux + mobilier


def estimer_loyer(bien: BienInput) -> float:
    """Renvoie le loyer mensuel à utiliser (fourni ou estimé)."""
    if bien.loyer_mensuel and bien.loyer_mensuel > 0:
        return float(bien.loyer_mensuel)
    if bien.loyer_m2_mensuel and bien.surface_m2 > 0:
        return float(bien.loyer_m2_mensuel * bien.surface_m2)
    return 0.0


# ---------------------------------------------------------------------------
# Charges
# ---------------------------------------------------------------------------

def calcul_charges_annuelles(
    bien: BienInput, loyer_mensuel: float, params: FraisParams
) -> dict:
    """Détail des charges annuelles à la charge du propriétaire.

    La part des charges de copropriété récupérable sur le locataire est exclue.
    """
    loyer_annuel = loyer_mensuel * 12.0
    charges_copro_non_recup = bien.charges_copro_annuelles * (
        1.0 - params.charges_copro_part_locataire
    )
    vacance = loyer_annuel * params.vacance_locative_pct
    gestion = loyer_annuel * params.frais_gestion_pct
    entretien = loyer_annuel * params.entretien_pct_loyer

    detail = {
        "taxe_fonciere": float(bien.taxe_fonciere_annuelle),
        "charges_copro_non_recuperables": float(charges_copro_non_recup),
        "assurance_pno": float(params.assurance_pno_annuelle),
        "frais_gestion": float(gestion),
        "entretien_provision": float(entretien),
        "vacance_locative": float(vacance),
    }
    detail["total"] = float(sum(detail.values()))
    return detail


# ---------------------------------------------------------------------------
# Régimes fiscaux
# ---------------------------------------------------------------------------

def _impot_revenu(revenu_imposable: float, tmi: float) -> float:
    """Approximation : on applique la TMI au revenu locatif marginal.

    En pratique le revenu locatif s'ajoute au revenu global ; pour un calcul
    fin il faudrait simuler le barème complet. Cette approximation est suffisante
    pour comparer les régimes entre eux à profil constant.
    """
    if revenu_imposable <= 0:
        return 0.0
    return revenu_imposable * tmi


def _regime_nu(
    loyer_annuel: float,
    charges_deductibles: float,
    interets_annuels: float,
    params: AnalysisParams,
) -> tuple[float, float, float]:
    """Régime nu : micro-foncier (abattement 30%) ou réel selon plafond.

    Renvoie (revenu_imposable, ir, ps).
    """
    if loyer_annuel <= PLAFOND_MICRO_FONCIER:
        # Micro-foncier : 30 % d'abattement forfaitaire
        revenu_imposable = max(0.0, loyer_annuel * (1.0 - ABATTEMENT_MICRO_FONCIER))
    else:
        # Réel foncier : déduction des charges et des intérêts d'emprunt
        revenu_imposable = max(0.0, loyer_annuel - charges_deductibles - interets_annuels)
    ir = _impot_revenu(revenu_imposable, params.tax.tmi)
    ps = revenu_imposable * params.tax.prelevements_sociaux
    return revenu_imposable, ir, ps


def _regime_micro_bic(
    loyer_annuel: float,
    params: AnalysisParams,
) -> tuple[float, float, float]:
    """Régime micro-BIC (meublé longue durée) — abattement 50 %, plafond 77 700 €.

    Si le loyer dépasse le plafond, le contribuable bascule au réel — on l'indique
    en renvoyant un revenu imposable peu compétitif (= la totalité, l'utilisateur
    le verra dans la comparaison et choisira LMNP réel).
    """
    if loyer_annuel <= PLAFOND_MICRO_BIC_LD:
        revenu_imposable = max(0.0, loyer_annuel * (1.0 - ABATTEMENT_MICRO_BIC))
    else:
        # Pénalisation explicite pour signaler que le régime n'est pas applicable
        revenu_imposable = loyer_annuel
    ir = _impot_revenu(revenu_imposable, params.tax.tmi)
    ps = revenu_imposable * params.tax.prelevements_sociaux
    return revenu_imposable, ir, ps


def amortissements_lmnp(
    prix: float,
    travaux: float,
    mobilier: float,
    frais_notaire: float,
    a: AmortissementParams,
) -> dict:
    """Dotations annuelles d'amortissement par composant (LMNP au réel)."""
    base_immobiliere = max(0.0, prix * (1.0 - a.part_terrain))
    return {
        "bati": base_immobiliere / a.duree_bati_annees if a.duree_bati_annees else 0.0,
        "mobilier": mobilier / a.duree_mobilier_annees if a.duree_mobilier_annees else 0.0,
        "notaire": frais_notaire / a.duree_notaire_annees if a.duree_notaire_annees else 0.0,
        "travaux": travaux / a.duree_travaux_annees if a.duree_travaux_annees else 0.0,
    }


def _regime_lmnp_reel(
    loyer_annuel: float,
    charges_deductibles: float,
    interets_annuels: float,
    assurance_credit_annuelle: float,
    amortissements: dict,
    params: AnalysisParams,
) -> tuple[float, float, float]:
    """LMNP au réel : déduction des charges + intérêts + assurance + amortissements.

    Règle clé (réforme fév. 2025) : les amortissements ne peuvent pas créer de
    déficit imputable sur le revenu global. Le déficit éventuel est reporté sur
    les revenus BIC des 10 années suivantes (non modélisé ici en simulation
    annuelle : on plafonne le revenu imposable à 0).
    """
    dotation_totale = sum(amortissements.values())
    base_avant_amort = loyer_annuel - charges_deductibles - interets_annuels - assurance_credit_annuelle
    # Amortissements ne peuvent pas créer de déficit -> plafonnés à la base
    amort_utilises = min(dotation_totale, max(0.0, base_avant_amort))
    revenu_imposable = max(0.0, base_avant_amort - amort_utilises)
    ir = _impot_revenu(revenu_imposable, params.tax.tmi)
    ps = revenu_imposable * params.tax.prelevements_sociaux
    return revenu_imposable, ir, ps


# ---------------------------------------------------------------------------
# Intérêts d'emprunt annuels — approximation moyenne sur la durée
# ---------------------------------------------------------------------------

def interets_annuels_moyens(
    capital: float, taux_annuel: float, duree_annees: int
) -> float:
    """Intérêts moyens annuels payés sur toute la durée du prêt.

    Sur un prêt amortissable, les intérêts varient (fortement en début, peu en fin).
    Pour une analyse "moyenne sur la durée" on calcule total intérêts / durée.
    Pour une analyse plus fine, fournir une fonction par année (non implémentée
    ici car le but est une comparaison de régimes).
    """
    if capital <= 0 or duree_annees <= 0:
        return 0.0
    mensualite = mensualite_pret(capital, taux_annuel, duree_annees)
    total_paye = mensualite * 12 * duree_annees
    total_interets = total_paye - capital
    return total_interets / duree_annees


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def analyser_bien(bien: BienInput, params: AnalysisParams | None = None) -> AnalysisResult:
    """Analyse complète d'un bien : finance + comparaison des 3 régimes fiscaux."""
    params = params or AnalysisParams()

    # --- Financement
    frais_notaire = bien.prix * params.frais.frais_notaire_pct
    cout_total = cout_total_operation(
        bien.prix, bien.travaux, bien.mobilier, params.frais.frais_notaire_pct
    )
    montant_emprunte = max(0.0, cout_total - params.credit.apport)
    mens_credit = mensualite_pret(
        montant_emprunte, params.credit.taux_annuel, params.credit.duree_annees
    )
    mens_assur = mensualite_assurance(
        montant_emprunte, params.credit.taux_assurance_annuel
    )
    mensualite_totale = mens_credit + mens_assur
    interets_moy = interets_annuels_moyens(
        montant_emprunte, params.credit.taux_annuel, params.credit.duree_annees
    )
    assur_annuelle = mens_assur * 12.0
    cout_total_credit = (mensualite_totale * 12 * params.credit.duree_annees) - montant_emprunte

    # --- Loyer & charges
    loyer_mensuel = estimer_loyer(bien)
    loyer_annuel = loyer_mensuel * 12.0
    charges_detail = calcul_charges_annuelles(bien, loyer_mensuel, params.frais)
    charges_proprio = charges_detail["total"]

    # --- Charges déductibles fiscalement (régimes réels)
    # = charges proprio + charges copro non récupérables déjà incluses
    charges_deductibles = charges_proprio

    # --- Régimes
    rev_nu, ir_nu, ps_nu = _regime_nu(
        loyer_annuel, charges_deductibles, interets_moy, params
    )
    rev_mb, ir_mb, ps_mb = _regime_micro_bic(loyer_annuel, params)
    amorts = amortissements_lmnp(
        bien.prix, bien.travaux, bien.mobilier, frais_notaire, params.amort
    )
    rev_lr, ir_lr, ps_lr = _regime_lmnp_reel(
        loyer_annuel, charges_deductibles, interets_moy, assur_annuelle, amorts, params
    )

    # --- Cash-flow annuel pour chaque régime
    # Cash-flow brut = loyer - charges proprio - mensualités totales annuelles
    cf_brut = loyer_annuel - charges_proprio - mensualite_totale * 12.0

    def _build(nom: Regime, rev: float, ir: float, ps: float) -> RegimeResult:
        impot_total = ir + ps
        cf_annuel = cf_brut - impot_total
        return RegimeResult(
            nom=nom,
            revenu_imposable=rev,
            impot_revenu=ir,
            prelevements_sociaux=ps,
            impot_total=impot_total,
            cashflow_annuel=cf_annuel,
            cashflow_mensuel=cf_annuel / 12.0,
            rendement_net_net=(cf_annuel / cout_total) if cout_total > 0 else 0.0,
        )

    regimes: dict[Regime, RegimeResult] = {
        "nu": _build("nu", rev_nu, ir_nu, ps_nu),
        "micro_bic": _build("micro_bic", rev_mb, ir_mb, ps_mb),
        "lmnp_reel": _build("lmnp_reel", rev_lr, ir_lr, ps_lr),
    }
    regime_optimal: Regime = max(
        regimes, key=lambda r: regimes[r].cashflow_annuel
    )

    rendement_brut = (loyer_annuel / cout_total) if cout_total > 0 else 0.0
    rendement_net = ((loyer_annuel - charges_proprio) / cout_total) if cout_total > 0 else 0.0

    return AnalysisResult(
        prix=bien.prix,
        surface_m2=bien.surface_m2,
        loyer_mensuel=loyer_mensuel,
        cout_total=cout_total,
        apport=params.credit.apport,
        montant_emprunte=montant_emprunte,
        mensualite_credit=mens_credit,
        mensualite_assurance=mens_assur,
        mensualite_totale=mensualite_totale,
        cout_total_credit=cout_total_credit,
        loyer_annuel=loyer_annuel,
        charges_annuelles_proprio=charges_proprio,
        charges_detail=charges_detail,
        rendement_brut=rendement_brut,
        rendement_net=rendement_net,
        regimes=regimes,
        regime_optimal=regime_optimal,
        cashflow_mensuel=regimes[regime_optimal].cashflow_mensuel,
        cashflow_annuel=regimes[regime_optimal].cashflow_annuel,
        impot_annuel=regimes[regime_optimal].impot_total,
        rendement_net_net=regimes[regime_optimal].rendement_net_net,
    )
