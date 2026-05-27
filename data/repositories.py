"""Couche de persistance — encapsule les requêtes courantes.

On ne met PAS de logique métier ici, juste l'accès aux objets.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Alerte, Analyse, Bien, ConnectorRun, Parametres, Ville


# -------------------- Ville --------------------

def get_ville_by_insee(s: Session, code_insee: str) -> Ville | None:
    return s.scalars(select(Ville).where(Ville.code_insee == code_insee)).first()


def upsert_ville(s: Session, **fields) -> Ville:
    """Crée ou met à jour une ville par son code INSEE."""
    code_insee = fields["code_insee"]
    v = get_ville_by_insee(s, code_insee)
    if v is None:
        v = Ville(**fields)
        s.add(v)
    else:
        for k, val in fields.items():
            if val is not None:
                setattr(v, k, val)
    s.flush()
    return v


def list_villes(s: Session) -> list[Ville]:
    return list(s.scalars(select(Ville).order_by(Ville.nom)))


# -------------------- Bien --------------------

def get_bien_by_source(s: Session, source: str, source_id: str) -> Bien | None:
    return s.scalars(
        select(Bien).where(Bien.source == source, Bien.source_id == source_id)
    ).first()


def upsert_bien(
    s: Session, source: str, source_id: str | None, **fields
) -> tuple[Bien, bool]:
    """Crée ou met à jour un bien.

    Retourne (bien, est_nouveau).
    Quand source_id est None, on crée toujours un nouveau bien (import manuel).
    """
    is_new = False
    bien: Bien | None = None
    if source_id is not None:
        bien = get_bien_by_source(s, source, source_id)
    if bien is None:
        bien = Bien(source=source, source_id=source_id, **fields)
        s.add(bien)
        is_new = True
    else:
        for k, val in fields.items():
            if val is not None:
                setattr(bien, k, val)
    s.flush()
    return bien, is_new


def list_biens(s: Session, actif_only: bool = True) -> list[Bien]:
    q = select(Bien)
    if actif_only:
        q = q.where(Bien.actif.is_(True))
    return list(s.scalars(q.order_by(Bien.vu_le.desc())))


# -------------------- Analyse --------------------

def add_analyse(s: Session, bien_id: int, **fields) -> Analyse:
    a = Analyse(bien_id=bien_id, **fields)
    s.add(a)
    s.flush()
    return a


def latest_analyse(s: Session, bien_id: int) -> Analyse | None:
    return s.scalars(
        select(Analyse)
        .where(Analyse.bien_id == bien_id)
        .order_by(Analyse.calcule_le.desc())
        .limit(1)
    ).first()


# -------------------- Parametres --------------------

def get_parametres(s: Session) -> Parametres:
    p = s.get(Parametres, 1)
    if p is None:
        p = Parametres(id=1)
        s.add(p)
        s.flush()
    return p


# -------------------- Alertes --------------------

def add_alerte(s: Session, **fields) -> Alerte:
    a = Alerte(**fields)
    s.add(a)
    s.flush()
    return a


def list_alertes(s: Session, non_lues: bool = False, limit: int = 100) -> list[Alerte]:
    q = select(Alerte).order_by(Alerte.cree_le.desc()).limit(limit)
    if non_lues:
        q = q.where(Alerte.lu.is_(False))
    return list(s.scalars(q))


def alertes_a_notifier(s: Session) -> list[Alerte]:
    return list(s.scalars(select(Alerte).where(Alerte.notifie.is_(False))))


# -------------------- ConnectorRun --------------------

def log_connector_run(s: Session, **fields) -> ConnectorRun:
    r = ConnectorRun(**fields)
    s.add(r)
    s.flush()
    return r
