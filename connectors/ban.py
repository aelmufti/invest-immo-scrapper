"""Connecteur Base Adresse Nationale (BAN — adresse.data.gouv.fr).

API publique gratuite. Doc : https://adresse.data.gouv.fr/api-doc/adresse
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BAN_BASE = "https://api-adresse.data.gouv.fr"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "invest-immo-scrapper/0.1 (+local; usage personnel)"


@dataclass
class GeocodeResult:
    label: str
    latitude: float
    longitude: float
    score: float
    code_insee: Optional[str]
    code_postal: Optional[str]
    ville: Optional[str]


def geocode(adresse: str, limit: int = 1) -> Optional[GeocodeResult]:
    """Géocode une adresse libre. Renvoie None si rien trouvé ou erreur réseau."""
    if not adresse or not adresse.strip():
        return None
    try:
        with httpx.Client(
            base_url=BAN_BASE,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as c:
            r = c.get("/search/", params={"q": adresse, "limit": limit})
        if r.status_code != 200:
            logger.warning("BAN /search -> HTTP %s", r.status_code)
            return None
        features = r.json().get("features", [])
        if not features:
            return None
        f = features[0]
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [None, None])
        if coords[0] is None or coords[1] is None:
            return None
        return GeocodeResult(
            label=props.get("label", adresse),
            latitude=coords[1],
            longitude=coords[0],
            score=props.get("score", 0.0),
            code_insee=props.get("citycode"),
            code_postal=props.get("postcode"),
            ville=props.get("city"),
        )
    except httpx.HTTPError as exc:
        logger.warning("BAN indisponible : %s", exc)
        return None
