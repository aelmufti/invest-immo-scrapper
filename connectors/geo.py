"""Connecteur geo.api.gouv.fr (découpage administratif, communes, INSEE).

API publique gratuite, sans clé. Doc : https://geo.api.gouv.fr/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GEO_BASE = "https://geo.api.gouv.fr"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "invest-immo-scrapper/0.1 (+local; usage personnel)"


@dataclass
class CommuneInfo:
    code_insee: str
    nom: str
    code_postal: Optional[str]
    code_departement: Optional[str]
    code_region: Optional[str]
    population: Optional[int]
    latitude: Optional[float]
    longitude: Optional[float]


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=GEO_BASE,
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )


def fetch_commune(code_insee: str) -> CommuneInfo | None:
    """Récupère les infos d'une commune par son code INSEE."""
    try:
        with _client() as c:
            r = c.get(
                f"/communes/{code_insee}",
                params={
                    "fields": "nom,code,codesPostaux,codeDepartement,"
                              "codeRegion,centre,population"
                },
            )
        if r.status_code != 200:
            logger.warning("geo.api.gouv.fr /communes/%s -> HTTP %s",
                           code_insee, r.status_code)
            return None
        data = r.json()
        centre = data.get("centre") or {}
        coords = centre.get("coordinates") or [None, None]
        codes_postaux = data.get("codesPostaux") or []
        return CommuneInfo(
            code_insee=data["code"],
            nom=data["nom"],
            code_postal=codes_postaux[0] if codes_postaux else None,
            code_departement=data.get("codeDepartement"),
            code_region=data.get("codeRegion"),
            population=data.get("population"),
            latitude=coords[1],
            longitude=coords[0],
        )
    except httpx.HTTPError as exc:
        logger.warning("geo.api.gouv.fr indisponible : %s", exc)
        return None


def search_communes_by_name(nom: str, limit: int = 10) -> list[CommuneInfo]:
    """Recherche par nom (auto-complétion)."""
    try:
        with _client() as c:
            r = c.get(
                "/communes",
                params={
                    "nom": nom,
                    "limit": limit,
                    "fields": "nom,code,codesPostaux,codeDepartement,"
                              "codeRegion,centre,population",
                },
            )
        r.raise_for_status()
        out: list[CommuneInfo] = []
        for data in r.json():
            centre = data.get("centre") or {}
            coords = centre.get("coordinates") or [None, None]
            codes_postaux = data.get("codesPostaux") or []
            out.append(
                CommuneInfo(
                    code_insee=data["code"],
                    nom=data["nom"],
                    code_postal=codes_postaux[0] if codes_postaux else None,
                    code_departement=data.get("codeDepartement"),
                    code_region=data.get("codeRegion"),
                    population=data.get("population"),
                    latitude=coords[1],
                    longitude=coords[0],
                )
            )
        return out
    except httpx.HTTPError as exc:
        logger.warning("geo.api.gouv.fr recherche échouée : %s", exc)
        return []


def search_communes_by_postal(code_postal: str) -> list[CommuneInfo]:
    """Recherche par code postal."""
    try:
        with _client() as c:
            r = c.get(
                "/communes",
                params={
                    "codePostal": code_postal,
                    "fields": "nom,code,codesPostaux,codeDepartement,"
                              "codeRegion,centre,population",
                },
            )
        r.raise_for_status()
        out = []
        for data in r.json():
            centre = data.get("centre") or {}
            coords = centre.get("coordinates") or [None, None]
            out.append(
                CommuneInfo(
                    code_insee=data["code"],
                    nom=data["nom"],
                    code_postal=code_postal,
                    code_departement=data.get("codeDepartement"),
                    code_region=data.get("codeRegion"),
                    population=data.get("population"),
                    latitude=coords[1],
                    longitude=coords[0],
                )
            )
        return out
    except httpx.HTTPError as exc:
        logger.warning("geo.api.gouv.fr recherche CP échouée : %s", exc)
        return []
