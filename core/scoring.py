"""Module de scoring — note un bien sur 100 en agrégeant des sous-scores transparents.

Chaque sous-score est exprimé sur [0, 100] et accompagné d'un détail explicable
(la liste `details` permet d'afficher exactement pourquoi le bien obtient sa note).
Les pondérations sont configurables (cf. `ScoringWeights`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .finance import AnalysisResult


# ---------------------------------------------------------------------------
# Pondérations & contexte
# ---------------------------------------------------------------------------

@dataclass
class ScoringWeights:
    """Pondérations relatives — somme normalisée à la volée."""

    cashflow: float = 30.0
    rendement: float = 20.0
    decote_dvf: float = 15.0
    dpe: float = 10.0
    tension: float = 10.0
    distance: float = 10.0
    travaux: float = 5.0

    def as_dict(self) -> dict:
        return {
            "cashflow": self.cashflow,
            "rendement": self.rendement,
            "decote_dvf": self.decote_dvf,
            "dpe": self.dpe,
            "tension": self.tension,
            "distance": self.distance,
            "travaux": self.travaux,
        }


@dataclass
class ScoringContext:
    """Données d'environnement nécessaires pour scorer (peuvent être None)."""

    # Marché : prix médian DVF de la commune (€/m²)
    dvf_prix_m2_median: Optional[float] = None
    # Demande locative : population, % d'étudiants, etc.
    population: Optional[int] = None
    # Distance / temps depuis Paris (préférence du brief)
    distance_paris_km: Optional[float] = None
    temps_train_paris_min: Optional[int] = None
    # Tension : note brute fournie par l'utilisateur (0-100) si pas d'INSEE
    tension_locative: Optional[float] = None
    # Préférences utilisateur
    rendement_brut_cible: float = 0.07
    distance_max_paris_km: Optional[float] = 400.0
    exclure_dpe_fg: bool = True


@dataclass
class ScoreBreakdown:
    """Détail d'un sous-score."""

    nom: str
    points_bruts: float   # sur 100
    poids: float          # pondération relative
    contribution: float   # points bruts * poids normalisé (sur le total)
    raison: str


@dataclass
class ScoreResult:
    score: float          # total sur 100
    exclu: bool           # True si une règle d'exclusion s'applique (ex DPE F/G)
    raison_exclusion: Optional[str]
    details: list[ScoreBreakdown]

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "exclu": self.exclu,
            "raison_exclusion": self.raison_exclusion,
            "details": [
                {
                    "nom": d.nom,
                    "points_bruts": d.points_bruts,
                    "poids": d.poids,
                    "contribution": d.contribution,
                    "raison": d.raison,
                }
                for d in self.details
            ],
        }


# ---------------------------------------------------------------------------
# Sous-scores — chacun renvoie (points sur 100, raison textuelle)
# ---------------------------------------------------------------------------

def _score_cashflow(cf_mensuel: float) -> tuple[float, str]:
    """+100 si CF >= 300 €/mois ; 50 à 0 € ; 0 si <= -300 €/mois."""
    if cf_mensuel >= 300:
        pts = 100.0
    elif cf_mensuel >= 0:
        pts = 50.0 + (cf_mensuel / 300) * 50.0
    elif cf_mensuel >= -300:
        pts = 50.0 + (cf_mensuel / 300) * 50.0  # symétrique
    else:
        pts = 0.0
    return pts, f"Cash-flow mensuel net-net = {cf_mensuel:+.0f} €"


def _score_rendement(rdt_brut: float, cible: float) -> tuple[float, str]:
    """100 à rendement >= 2x la cible, 50 au niveau de la cible, 0 si nul."""
    if rdt_brut <= 0:
        return 0.0, f"Rendement brut nul ou négatif ({rdt_brut:.1%})"
    if rdt_brut >= 2 * cible:
        return 100.0, f"Rendement brut {rdt_brut:.1%} (>= 2× cible {cible:.1%})"
    # Linéaire : 0 -> 0pts, cible -> 50pts, 2*cible -> 100pts
    pts = (rdt_brut / cible) * 50.0
    pts = max(0.0, min(100.0, pts))
    return pts, f"Rendement brut {rdt_brut:.1%} (cible {cible:.1%})"


def _score_decote_dvf(
    prix_m2_bien: float | None, prix_m2_marche: float | None
) -> tuple[float, str]:
    """100 si décote >= 20 %, 50 si prix au prix du marché, 0 si surcote >= 20 %."""
    if not prix_m2_bien or not prix_m2_marche or prix_m2_marche <= 0:
        return 50.0, "Pas de référence DVF disponible — score neutre"
    ecart = (prix_m2_bien - prix_m2_marche) / prix_m2_marche
    # ecart = +20 % -> 0 pts ; 0 % -> 50 pts ; -20 % -> 100 pts
    pts = 50.0 - (ecart * 250.0)
    pts = max(0.0, min(100.0, pts))
    if ecart < 0:
        msg = f"Bien à {prix_m2_bien:.0f} €/m², décote {abs(ecart):.1%} vs DVF ({prix_m2_marche:.0f} €/m²)"
    else:
        msg = f"Bien à {prix_m2_bien:.0f} €/m², surcote {ecart:.1%} vs DVF ({prix_m2_marche:.0f} €/m²)"
    return pts, msg


_DPE_POINTS = {
    "A": 100.0, "B": 90.0, "C": 75.0, "D": 60.0, "E": 35.0, "F": 10.0, "G": 0.0,
}


def _score_dpe(dpe: str | None) -> tuple[float, str]:
    if not dpe:
        return 50.0, "DPE non renseigné — score neutre"
    code = dpe.strip().upper()[:1]
    pts = _DPE_POINTS.get(code, 50.0)
    return pts, f"DPE {code}"


def _score_tension(
    population: int | None, tension: float | None
) -> tuple[float, str]:
    """Si une note de tension est fournie, on l'utilise. Sinon, on déduit de la population."""
    if tension is not None:
        pts = max(0.0, min(100.0, float(tension)))
        return pts, f"Tension locative utilisateur : {pts:.0f}/100"
    if not population:
        return 50.0, "Population inconnue — score neutre"
    # Heuristique grossière : >150k = très tendu, >50k = tendu, >20k = moyen, <20k = faible
    if population >= 150_000:
        pts, niveau = 90.0, "très tendu"
    elif population >= 50_000:
        pts, niveau = 75.0, "tendu"
    elif population >= 20_000:
        pts, niveau = 55.0, "moyen"
    elif population >= 5_000:
        pts, niveau = 35.0, "faible"
    else:
        pts, niveau = 15.0, "très faible"
    return pts, f"Population {population:,} hab. — marché {niveau}".replace(",", " ")


def _score_distance(
    distance_km: float | None, distance_max: float | None
) -> tuple[float, str]:
    """Distance depuis Paris : 0 km = 100 pts, distance_max = 0 pts (linéaire)."""
    if distance_km is None:
        return 50.0, "Distance Paris inconnue — score neutre"
    if not distance_max or distance_max <= 0:
        return 50.0, "Pas de distance maximale définie — score neutre"
    if distance_km <= 0:
        return 100.0, "À Paris même"
    if distance_km >= distance_max:
        return 0.0, f"Distance {distance_km:.0f} km > seuil {distance_max:.0f} km"
    pts = 100.0 * (1.0 - distance_km / distance_max)
    return pts, f"Distance Paris {distance_km:.0f} km (seuil {distance_max:.0f} km)"


def _score_travaux(annee_construction: int | None) -> tuple[float, str]:
    """Proxy de risque travaux par âge du bien (renseigné via extra)."""
    if not annee_construction:
        return 50.0, "Année de construction inconnue — score neutre"
    from datetime import datetime
    age = datetime.utcnow().year - int(annee_construction)
    if age <= 10:
        return 95.0, f"Construction récente ({age} ans)"
    if age <= 30:
        return 75.0, f"Construction moderne ({age} ans)"
    if age <= 60:
        return 55.0, f"Construction des années {annee_construction} ({age} ans)"
    if age <= 100:
        return 35.0, f"Bien ancien ({age} ans) — risque travaux"
    return 15.0, f"Bien très ancien ({age} ans) — risque travaux élevé"


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def scorer_bien(
    *,
    analyse: AnalysisResult,
    prix_m2_bien: float | None,
    ctx: ScoringContext,
    weights: ScoringWeights | None = None,
    dpe: str | None = None,
    annee_construction: int | None = None,
) -> ScoreResult:
    """Calcule un score global sur 100 pour un bien analysé.

    Renvoie aussi le détail des sous-scores pour transparence.
    """
    weights = weights or ScoringWeights()

    # --- Règles d'exclusion dures
    if ctx.exclure_dpe_fg and dpe and dpe.strip().upper()[:1] in {"F", "G"}:
        return ScoreResult(
            score=0.0, exclu=True,
            raison_exclusion=f"DPE {dpe.strip().upper()[:1]} exclu par préférence utilisateur",
            details=[],
        )

    # --- Sous-scores
    pts_cf, raison_cf = _score_cashflow(analyse.cashflow_mensuel)
    pts_rdt, raison_rdt = _score_rendement(analyse.rendement_brut, ctx.rendement_brut_cible)
    pts_decote, raison_decote = _score_decote_dvf(prix_m2_bien, ctx.dvf_prix_m2_median)
    pts_dpe, raison_dpe = _score_dpe(dpe)
    pts_tension, raison_tension = _score_tension(ctx.population, ctx.tension_locative)
    pts_dist, raison_dist = _score_distance(ctx.distance_paris_km, ctx.distance_max_paris_km)
    pts_travaux, raison_travaux = _score_travaux(annee_construction)

    w = weights.as_dict()
    total_w = sum(w.values()) or 1.0

    bruts = {
        "cashflow": (pts_cf, raison_cf),
        "rendement": (pts_rdt, raison_rdt),
        "decote_dvf": (pts_decote, raison_decote),
        "dpe": (pts_dpe, raison_dpe),
        "tension": (pts_tension, raison_tension),
        "distance": (pts_dist, raison_dist),
        "travaux": (pts_travaux, raison_travaux),
    }

    details: list[ScoreBreakdown] = []
    score_total = 0.0
    for nom, (pts, raison) in bruts.items():
        poids = w[nom]
        contrib = pts * (poids / total_w)
        score_total += contrib
        details.append(
            ScoreBreakdown(
                nom=nom,
                points_bruts=round(pts, 1),
                poids=poids,
                contribution=round(contrib, 2),
                raison=raison,
            )
        )

    return ScoreResult(
        score=round(score_total, 1),
        exclu=False,
        raison_exclusion=None,
        details=details,
    )
