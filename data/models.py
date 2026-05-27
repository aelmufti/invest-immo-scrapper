"""Modèles SQLAlchemy.

Schéma conçu pour SQLite mais sans dépendance spécifique : passage à PostgreSQL
possible sans modification (types portables, pas de JSONB, pas d'array).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base déclarative SQLAlchemy."""


def _now() -> datetime:
    return datetime.utcnow()


class Ville(Base):
    """Cache enrichi d'une commune : DVF + données INSEE/géo."""

    __tablename__ = "villes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_insee: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    code_postal: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    nom: Mapped[str] = mapped_column(String(200), index=True)
    departement: Mapped[Optional[str]] = mapped_column(String(5), index=True)
    region: Mapped[Optional[str]] = mapped_column(String(5))
    population: Mapped[Optional[int]] = mapped_column(Integer)

    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    # Statistiques DVF (moyennes calculées sur les dernières mutations connues)
    dvf_prix_m2_median: Mapped[Optional[float]] = mapped_column(Float)
    dvf_prix_m2_moyen: Mapped[Optional[float]] = mapped_column(Float)
    dvf_nb_mutations: Mapped[Optional[int]] = mapped_column(Integer)
    dvf_annee_ref: Mapped[Optional[int]] = mapped_column(Integer)
    dvf_derniere_maj: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Loyer moyen estimé (€/m²/mois) — saisi manuellement ou enrichi
    loyer_m2_estime: Mapped[Optional[float]] = mapped_column(Float)

    # Distance/temps depuis Paris (renseignable manuellement)
    distance_paris_km: Mapped[Optional[float]] = mapped_column(Float)
    temps_train_paris_min: Mapped[Optional[int]] = mapped_column(Integer)

    cree_le: Mapped[datetime] = mapped_column(DateTime, default=_now)
    maj_le: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    biens: Mapped[list["Bien"]] = relationship(back_populates="ville")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Ville {self.code_insee} {self.nom}>"


class Bien(Base):
    """Une annonce ou un bien identifié (importé, scrapé, ou saisi)."""

    __tablename__ = "biens"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_bien_source"),
        Index("ix_bien_ville_actif", "ville_id", "actif"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source: Mapped[str] = mapped_column(String(50), index=True)   # "manuel", "csv", "example"...
    source_id: Mapped[Optional[str]] = mapped_column(String(200)) # id natif chez la source
    url: Mapped[Optional[str]] = mapped_column(Text)

    titre: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)

    type_bien: Mapped[Optional[str]] = mapped_column(String(30))  # appartement, maison...
    prix: Mapped[Optional[float]] = mapped_column(Float)          # €
    surface_m2: Mapped[Optional[float]] = mapped_column(Float)
    nb_pieces: Mapped[Optional[int]] = mapped_column(Integer)
    nb_chambres: Mapped[Optional[int]] = mapped_column(Integer)
    etage: Mapped[Optional[int]] = mapped_column(Integer)
    annee_construction: Mapped[Optional[int]] = mapped_column(Integer)

    dpe: Mapped[Optional[str]] = mapped_column(String(2))  # A..G
    ges: Mapped[Optional[str]] = mapped_column(String(2))

    charges_copro_annuelles: Mapped[Optional[float]] = mapped_column(Float)
    taxe_fonciere_annuelle: Mapped[Optional[float]] = mapped_column(Float)
    loyer_mensuel_estime: Mapped[Optional[float]] = mapped_column(Float)
    travaux_estimes: Mapped[Optional[float]] = mapped_column(Float)

    adresse: Mapped[Optional[str]] = mapped_column(Text)
    code_postal: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    ville_nom: Mapped[Optional[str]] = mapped_column(String(200))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    ville_id: Mapped[Optional[int]] = mapped_column(ForeignKey("villes.id"))
    ville: Mapped[Optional[Ville]] = relationship(back_populates="biens")

    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    vu_le: Mapped[datetime] = mapped_column(DateTime, default=_now)   # 1ère fois
    maj_le: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    extra: Mapped[Optional[dict]] = mapped_column(JSON)

    analyses: Mapped[list["Analyse"]] = relationship(
        back_populates="bien", cascade="all, delete-orphan"
    )


class Analyse(Base):
    """Historique des résultats financiers + scoring pour un bien.

    Une nouvelle ligne à chaque recalcul (suivi de l'évolution dans le temps).
    """

    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyse_bien_date", "bien_id", "calcule_le"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bien_id: Mapped[int] = mapped_column(ForeignKey("biens.id", ondelete="CASCADE"))

    calcule_le: Mapped[datetime] = mapped_column(DateTime, default=_now)
    parametres_hash: Mapped[Optional[str]] = mapped_column(String(64))

    cout_total: Mapped[Optional[float]] = mapped_column(Float)
    mensualite_credit: Mapped[Optional[float]] = mapped_column(Float)
    loyer_mensuel: Mapped[Optional[float]] = mapped_column(Float)
    charges_annuelles: Mapped[Optional[float]] = mapped_column(Float)
    rendement_brut: Mapped[Optional[float]] = mapped_column(Float)
    rendement_net: Mapped[Optional[float]] = mapped_column(Float)

    # Régime fiscal retenu (meilleur des 3)
    regime_optimal: Mapped[Optional[str]] = mapped_column(String(30))
    impot_annuel: Mapped[Optional[float]] = mapped_column(Float)
    cashflow_mensuel: Mapped[Optional[float]] = mapped_column(Float)
    cashflow_annuel: Mapped[Optional[float]] = mapped_column(Float)
    rendement_net_net: Mapped[Optional[float]] = mapped_column(Float)

    # Scoring
    score: Mapped[Optional[float]] = mapped_column(Float)
    score_details: Mapped[Optional[dict]] = mapped_column(JSON)

    # Snapshot complet (pour debug et exploration)
    snapshot: Mapped[Optional[dict]] = mapped_column(JSON)

    bien: Mapped[Bien] = relationship(back_populates="analyses")


class Parametres(Base):
    """Singleton des paramètres utilisateur (id=1 unique)."""

    __tablename__ = "parametres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Profil financier
    revenus_nets_mensuels: Mapped[float] = mapped_column(Float, default=3900.0)
    apport_disponible: Mapped[float] = mapped_column(Float, default=30000.0)
    tmi: Mapped[float] = mapped_column(Float, default=0.30)  # tranche marginale d'imposition

    # Crédit
    taux_credit: Mapped[float] = mapped_column(Float, default=0.0326)
    taux_assurance: Mapped[float] = mapped_column(Float, default=0.0034)
    duree_credit_annees: Mapped[int] = mapped_column(Integer, default=20)

    # Hypothèses
    frais_notaire_pct: Mapped[float] = mapped_column(Float, default=0.08)  # ancien
    vacance_locative_pct: Mapped[float] = mapped_column(Float, default=0.04)  # 1 mois sur 2 ans
    frais_gestion_pct: Mapped[float] = mapped_column(Float, default=0.07)
    assurance_pno_annuelle: Mapped[float] = mapped_column(Float, default=180.0)
    entretien_pct_loyer: Mapped[float] = mapped_column(Float, default=0.05)
    charges_copro_part_locataire: Mapped[float] = mapped_column(Float, default=0.75)

    # Préférences
    distance_max_paris_km: Mapped[Optional[float]] = mapped_column(Float, default=400.0)
    prix_max: Mapped[Optional[float]] = mapped_column(Float, default=200000.0)
    rendement_brut_min: Mapped[float] = mapped_column(Float, default=0.07)
    score_alerte_seuil: Mapped[float] = mapped_column(Float, default=70.0)
    exclure_dpe_fg: Mapped[bool] = mapped_column(Boolean, default=True)

    # Pondérations scoring (somme libre, normalisée à la volée)
    poids_cashflow: Mapped[float] = mapped_column(Float, default=30.0)
    poids_rendement: Mapped[float] = mapped_column(Float, default=20.0)
    poids_decote_dvf: Mapped[float] = mapped_column(Float, default=15.0)
    poids_dpe: Mapped[float] = mapped_column(Float, default=10.0)
    poids_tension: Mapped[float] = mapped_column(Float, default=10.0)
    poids_distance: Mapped[float] = mapped_column(Float, default=10.0)
    poids_travaux: Mapped[float] = mapped_column(Float, default=5.0)

    maj_le: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Alerte(Base):
    """Journal des opportunités détectées (score >= seuil, ou nouveauté)."""

    __tablename__ = "alertes"
    __table_args__ = (Index("ix_alerte_lu_date", "lu", "cree_le"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bien_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("biens.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(30))  # "nouveau_bien", "score_eleve"...
    titre: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    score: Mapped[Optional[float]] = mapped_column(Float)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=_now)
    lu: Mapped[bool] = mapped_column(Boolean, default=False)
    notifie: Mapped[bool] = mapped_column(Boolean, default=False)


class ConnectorRun(Base):
    """Journal des passages des connecteurs (Couche B) — utile pour debug."""

    __tablename__ = "connector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    debut: Mapped[datetime] = mapped_column(DateTime, default=_now)
    fin: Mapped[Optional[datetime]] = mapped_column(DateTime)
    statut: Mapped[str] = mapped_column(String(30))  # "ok", "erreur", "bloque"
    nb_recus: Mapped[int] = mapped_column(Integer, default=0)
    nb_nouveaux: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(Text)
