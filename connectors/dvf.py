"""Connecteur DVF (Demandes de Valeurs Foncières) — Etalab.

Source officielle : https://files.data.gouv.fr/geo-dvf/latest/csv/<YEAR>/communes/<DEPT>/<INSEE>.csv

Téléchargement par commune, sans clé d'API, données ouvertes.
On en extrait des statistiques de prix/m² pour les biens d'habitation
(appartements et maisons) sur l'année la plus récente disponible.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from core.settings import get_settings

logger = logging.getLogger(__name__)

DVF_BASE = "https://files.data.gouv.fr/geo-dvf/latest/csv"
DEFAULT_TIMEOUT = 60.0
USER_AGENT = "invest-immo-scrapper/0.1 (+local; usage personnel)"

# Filtres : on garde les mutations "Vente" sur appartements / maisons,
# avec surface et prix renseignés, prix au m² dans une fourchette raisonnable.
TYPES_LOCAUX_RETENUS = {"Appartement", "Maison"}
NATURES_RETENUES = {"Vente"}
PRIX_M2_MIN = 200.0
PRIX_M2_MAX = 25000.0


@dataclass
class DvfStats:
    """Statistiques DVF agrégées pour une commune sur une année."""

    code_insee: str
    annee: int
    nb_mutations: int
    prix_m2_moyen: float | None
    prix_m2_median: float | None
    prix_m2_q25: float | None
    prix_m2_q75: float | None
    # Détail par type
    prix_m2_median_appart: float | None = None
    prix_m2_median_maison: float | None = None


def _cache_path(code_insee: str, annee: int) -> Path:
    settings = get_settings()
    cache_dir = settings.root_dir / "data" / "cache" / "dvf"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{annee}_{code_insee}.csv"


def _fetch_csv(code_insee: str, annee: int) -> Optional[pd.DataFrame]:
    """Télécharge le CSV DVF d'une commune pour une année. Cache local 30 jours."""
    if len(code_insee) < 3:
        return None
    dept = code_insee[:3] if code_insee.startswith("97") else code_insee[:2]

    cache = _cache_path(code_insee, annee)
    if cache.exists():
        age = datetime.utcnow() - datetime.utcfromtimestamp(cache.stat().st_mtime)
        if age < timedelta(days=30):
            try:
                return pd.read_csv(cache, low_memory=False)
            except Exception as exc:
                logger.warning("Cache DVF illisible (%s), refetch : %s", cache, exc)

    url = f"{DVF_BASE}/{annee}/communes/{dept}/{code_insee}.csv"
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT,
                          headers={"User-Agent": USER_AGENT},
                          follow_redirects=True) as c:
            r = c.get(url)
        if r.status_code == 404:
            logger.info("DVF : aucune donnée pour %s en %s (404)", code_insee, annee)
            return None
        if r.status_code != 200:
            logger.warning("DVF HTTP %s pour %s", r.status_code, url)
            return None
        cache.write_bytes(r.content)
        return pd.read_csv(io.BytesIO(r.content), low_memory=False)
    except httpx.HTTPError as exc:
        logger.warning("DVF indisponible : %s", exc)
        return None


def _compute_stats(df: pd.DataFrame, code_insee: str, annee: int) -> DvfStats | None:
    """Calcule les stats prix/m² à partir du CSV DVF d'une commune."""
    if df is None or df.empty:
        return None

    needed = {"nature_mutation", "type_local", "valeur_fonciere", "surface_reelle_bati"}
    if not needed.issubset(df.columns):
        logger.warning("Colonnes DVF inattendues : %s", df.columns.tolist())
        return None

    df = df[df["nature_mutation"].isin(NATURES_RETENUES)]
    df = df[df["type_local"].isin(TYPES_LOCAUX_RETENUS)]
    df = df.dropna(subset=["valeur_fonciere", "surface_reelle_bati"])
    df = df[(df["surface_reelle_bati"] > 9) & (df["valeur_fonciere"] > 0)]

    # Une mutation peut concerner plusieurs locaux : agréger par id_mutation
    # pour éviter de gonfler les chiffres. On garde la surface totale bâtie.
    if "id_mutation" in df.columns:
        agg = (
            df.groupby("id_mutation", as_index=False)
            .agg(
                valeur_fonciere=("valeur_fonciere", "first"),
                surface_reelle_bati=("surface_reelle_bati", "sum"),
                type_local=("type_local", "first"),
            )
        )
    else:
        agg = df.copy()

    agg["prix_m2"] = agg["valeur_fonciere"] / agg["surface_reelle_bati"]
    agg = agg[(agg["prix_m2"] >= PRIX_M2_MIN) & (agg["prix_m2"] <= PRIX_M2_MAX)]
    if agg.empty:
        return None

    by_type = agg.groupby("type_local")["prix_m2"].median()

    return DvfStats(
        code_insee=code_insee,
        annee=annee,
        nb_mutations=int(len(agg)),
        prix_m2_moyen=float(agg["prix_m2"].mean()),
        prix_m2_median=float(agg["prix_m2"].median()),
        prix_m2_q25=float(agg["prix_m2"].quantile(0.25)),
        prix_m2_q75=float(agg["prix_m2"].quantile(0.75)),
        prix_m2_median_appart=float(by_type.get("Appartement", None))
        if "Appartement" in by_type
        else None,
        prix_m2_median_maison=float(by_type.get("Maison", None))
        if "Maison" in by_type
        else None,
    )


def get_dvf_stats(code_insee: str, prefer_year: int | None = None) -> DvfStats | None:
    """Récupère les stats DVF de la commune sur la dernière année disponible.

    On essaie de l'année préférée à 3 ans en arrière. Renvoie None si rien.
    """
    current_year = datetime.utcnow().year
    # DVF est publié avec ~1 trimestre de retard : commencer à year-1
    start = prefer_year or (current_year - 1)
    for annee in (start, start - 1, start - 2, start - 3):
        if annee < 2014:
            break
        df = _fetch_csv(code_insee, annee)
        if df is None or df.empty:
            continue
        stats = _compute_stats(df, code_insee, annee)
        if stats is not None and stats.nb_mutations >= 3:
            logger.info(
                "DVF %s (%s) : %d mutations, médiane %.0f €/m²",
                code_insee, annee, stats.nb_mutations, stats.prix_m2_median or 0,
            )
            return stats
    return None
