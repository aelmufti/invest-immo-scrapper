"""Service d'orchestration pour les villes (Couche A).

Combine geo.api.gouv.fr (infos commune) + DVF (prix réels) et persiste en base.
Renvoie des dicts pour éviter les problèmes de session SQLAlchemy.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from connectors import dvf as dvf_api
from connectors import geo as geo_api
from data.database import session_scope
from data.models import Ville
from data.repositories import upsert_ville

logger = logging.getLogger(__name__)


def _ville_to_dict(v: Ville) -> dict:
    return {
        "id": v.id,
        "code_insee": v.code_insee,
        "code_postal": v.code_postal,
        "nom": v.nom,
        "departement": v.departement,
        "region": v.region,
        "population": v.population,
        "latitude": v.latitude,
        "longitude": v.longitude,
        "dvf_prix_m2_median": v.dvf_prix_m2_median,
        "dvf_prix_m2_moyen": v.dvf_prix_m2_moyen,
        "dvf_nb_mutations": v.dvf_nb_mutations,
        "dvf_annee_ref": v.dvf_annee_ref,
        "dvf_derniere_maj": v.dvf_derniere_maj,
        "loyer_m2_estime": v.loyer_m2_estime,
        "distance_paris_km": v.distance_paris_km,
        "temps_train_paris_min": v.temps_train_paris_min,
    }


def refresh_ville_by_insee(code_insee: str) -> Optional[dict]:
    """Crée/MAJ une ville (geo + DVF). Renvoie un dict (détaché). None si échec total."""
    info = geo_api.fetch_commune(code_insee)
    if info is None:
        logger.warning("Impossible de récupérer la commune %s", code_insee)
        return None

    stats = dvf_api.get_dvf_stats(code_insee)

    fields = dict(
        code_insee=info.code_insee,
        nom=info.nom,
        code_postal=info.code_postal,
        departement=info.code_departement,
        region=info.code_region,
        population=info.population,
        latitude=info.latitude,
        longitude=info.longitude,
    )
    if stats is not None:
        fields.update(
            dvf_prix_m2_median=stats.prix_m2_median,
            dvf_prix_m2_moyen=stats.prix_m2_moyen,
            dvf_nb_mutations=stats.nb_mutations,
            dvf_annee_ref=stats.annee,
            dvf_derniere_maj=datetime.utcnow(),
        )

    with session_scope() as s:
        v = upsert_ville(s, **fields)
        s.flush()
        return _ville_to_dict(v)


def refresh_villes_existantes() -> int:
    """Rafraîchit toutes les villes déjà en base. Renvoie le nombre traité."""
    with session_scope() as s:
        codes = [v.code_insee for v in s.query(Ville).all()]
    count = 0
    for code in codes:
        try:
            refresh_ville_by_insee(code)
            count += 1
        except Exception:
            logger.exception("Erreur refresh ville %s", code)
    return count


def list_villes() -> list[dict]:
    with session_scope() as s:
        return [_ville_to_dict(v) for v in s.query(Ville).order_by(Ville.nom).all()]
