"""Service d'ingestion d'annonces (Couche B).

Accepte trois sources :
- texte collé (utilise core.parser)
- CSV (colonnes flexibles, mapping souple)
- connecteurs (sous-classes de BaseConnector)

Persiste les biens en base, déduplique par (source, source_id), et marque
les nouveautés pour permettre à `services/alertes.py` de les détecter.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from io import StringIO
from typing import Iterable

from connectors.base import BaseConnector, ConnectorResult, RawListing
from core.parser import parser_annonce
from data.database import session_scope
from data.models import Bien, ConnectorRun, Ville
from data.repositories import (
    get_ville_by_insee,
    log_connector_run,
    upsert_bien,
)
from services.villes_service import refresh_ville_by_insee

logger = logging.getLogger(__name__)


def _attach_ville(bien_fields: dict) -> dict:
    """Si possible, attache un ville_id en cherchant la commune via code postal/nom.

    Si aucune ville en base, déclenche un refresh DVF+geo pour cette commune.
    """
    code_postal = bien_fields.get("code_postal")
    ville_nom = bien_fields.get("ville_nom")
    if not (code_postal or ville_nom):
        return bien_fields

    with session_scope() as s:
        # On essaie d'abord par code postal exact
        q = s.query(Ville)
        if code_postal:
            v = q.filter(Ville.code_postal == code_postal).first()
            if v is not None:
                bien_fields["ville_id"] = v.id
                return bien_fields
        if ville_nom:
            v = (
                q.filter(Ville.nom.ilike(f"%{ville_nom}%"))
                .order_by(Ville.population.desc().nullslast())
                .first()
            )
            if v is not None:
                bien_fields["ville_id"] = v.id
                return bien_fields

    # Pas trouvé : on tente de découvrir via geo.api.gouv.fr puis on ré-attache
    from connectors import geo
    if code_postal:
        candidats = geo.search_communes_by_postal(code_postal)
    elif ville_nom:
        candidats = geo.search_communes_by_name(ville_nom)
    else:
        candidats = []

    if not candidats:
        return bien_fields

    # On prend la plus peuplée des candidates
    candidats.sort(key=lambda c: (c.population or 0), reverse=True)
    chosen = candidats[0]
    refresh_ville_by_insee(chosen.code_insee)
    with session_scope() as s:
        v = get_ville_by_insee(s, chosen.code_insee)
        if v is not None:
            bien_fields["ville_id"] = v.id
    return bien_fields


# ---------------------------------------------------------------------------
# Import texte collé
# ---------------------------------------------------------------------------

def ingest_texte(texte: str, source: str = "manuel") -> dict:
    """Parse une annonce collée et l'enregistre. Renvoie un récap."""
    parsed = parser_annonce(texte)
    fields = {
        k: v
        for k, v in parsed.to_dict().items()
        if k not in {"ges"}  # GES déjà stocké dans le champ DB
    }
    fields["ges"] = parsed.ges
    fields = _attach_ville(fields)
    with session_scope() as s:
        bien, is_new = upsert_bien(s, source=source, source_id=None, **fields)
        bien_id = bien.id
    return {
        "bien_id": bien_id,
        "nouveau": is_new,
        "parsed": parsed.to_dict(),
    }


# ---------------------------------------------------------------------------
# Import CSV
# ---------------------------------------------------------------------------

# Mapping des en-têtes CSV reconnues vers les champs du modèle Bien
_CSV_HEADERS = {
    "prix": ["prix", "price", "valeur"],
    "surface_m2": ["surface", "surface_m2", "m2", "superficie"],
    "nb_pieces": ["pieces", "nb_pieces", "rooms"],
    "nb_chambres": ["chambres", "nb_chambres", "bedrooms"],
    "type_bien": ["type", "type_bien", "type_local"],
    "dpe": ["dpe", "classe_energie"],
    "ges": ["ges"],
    "code_postal": ["code_postal", "cp", "postal"],
    "ville_nom": ["ville", "ville_nom", "commune"],
    "adresse": ["adresse", "address"],
    "charges_copro_annuelles": ["charges_copro", "charges", "charges_annuelles"],
    "taxe_fonciere_annuelle": ["taxe_fonciere", "tf"],
    "loyer_mensuel_estime": ["loyer", "loyer_mensuel"],
    "etage": ["etage", "floor"],
    "annee_construction": ["annee_construction", "year_built", "annee"],
    "titre": ["titre", "title"],
    "url": ["url", "lien"],
    "source_id": ["id", "source_id", "ref"],
}


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_")


def _map_csv_row(row: dict[str, str]) -> dict:
    """Convertit une ligne CSV (clés textuelles) en dict de champs Bien."""
    norm = {_normalize_header(k): v for k, v in row.items() if v not in (None, "")}
    out: dict = {}
    for target, aliases in _CSV_HEADERS.items():
        for a in aliases:
            if a in norm:
                val = norm[a].strip()
                if not val:
                    continue
                if target in {
                    "prix", "surface_m2", "charges_copro_annuelles",
                    "taxe_fonciere_annuelle", "loyer_mensuel_estime",
                }:
                    try:
                        out[target] = float(
                            val.replace(",", ".").replace(" ", "").replace("€", "")
                        )
                    except ValueError:
                        pass
                elif target in {"nb_pieces", "nb_chambres", "etage", "annee_construction"}:
                    try:
                        out[target] = int(float(val))
                    except ValueError:
                        pass
                else:
                    out[target] = val
                break
    return out


def ingest_csv(contenu_csv: str, source: str = "csv") -> dict:
    """Ingère un CSV. Renvoie un récap (nb lignes, nb nouveaux, erreurs)."""
    nb_lignes = nb_nouveaux = 0
    erreurs: list[str] = []
    reader = csv.DictReader(StringIO(contenu_csv))
    for i, row in enumerate(reader, start=1):
        try:
            fields = _map_csv_row(row)
            if not fields:
                continue
            fields = _attach_ville(fields)
            source_id = fields.pop("source_id", None) or f"csv_row_{i}_{datetime.utcnow().timestamp():.0f}"
            with session_scope() as s:
                _, is_new = upsert_bien(s, source=source, source_id=source_id, **fields)
            nb_lignes += 1
            if is_new:
                nb_nouveaux += 1
        except Exception as exc:  # un mauvais row ne casse pas l'import entier
            erreurs.append(f"ligne {i}: {exc}")
            logger.exception("Erreur import CSV ligne %s", i)
    return {"nb_lignes": nb_lignes, "nb_nouveaux": nb_nouveaux, "erreurs": erreurs}


# ---------------------------------------------------------------------------
# Connecteurs (Couche B)
# ---------------------------------------------------------------------------

def ingest_connector(connector: BaseConnector, **kwargs) -> dict:
    """Exécute un connecteur et persiste ses résultats. Toujours non bloquant."""
    result: ConnectorResult = connector.run(**kwargs)
    nb_nouveaux = 0
    if result.statut == "ok":
        for listing in result.listings:
            try:
                fields = _listing_to_fields(listing)
                fields = _attach_ville(fields)
                with session_scope() as s:
                    _, is_new = upsert_bien(
                        s,
                        source=listing.source,
                        source_id=listing.source_id,
                        **fields,
                    )
                if is_new:
                    nb_nouveaux += 1
            except Exception:
                logger.exception("Erreur persistance listing %s", listing.source_id)

    with session_scope() as s:
        log_connector_run(
            s,
            nom=connector.name,
            debut=result.debut,
            fin=result.fin,
            statut=result.statut,
            nb_recus=len(result.listings),
            nb_nouveaux=nb_nouveaux,
            message=result.message,
        )

    return {
        "connecteur": connector.name,
        "statut": result.statut,
        "nb_recus": len(result.listings),
        "nb_nouveaux": nb_nouveaux,
        "message": result.message,
    }


def _listing_to_fields(l: RawListing) -> dict:
    """Mappe une RawListing vers les champs Bien."""
    return {
        "url": l.url,
        "titre": l.titre,
        "description": l.description,
        "type_bien": l.type_bien,
        "prix": l.prix,
        "surface_m2": l.surface_m2,
        "nb_pieces": l.nb_pieces,
        "dpe": l.dpe,
        "code_postal": l.code_postal,
        "ville_nom": l.ville_nom,
        "adresse": l.adresse,
        "latitude": l.latitude,
        "longitude": l.longitude,
        "charges_copro_annuelles": l.charges_copro_annuelles,
        "taxe_fonciere_annuelle": l.taxe_fonciere_annuelle,
        "loyer_mensuel_estime": l.loyer_mensuel_estime,
        "travaux_estimes": l.travaux_estimes,
        "extra": l.extra or None,
    }
