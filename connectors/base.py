"""Interface commune aux connecteurs (Couche A & B).

Un connecteur "rate" toujours proprement : il renvoie un objet `ConnectorResult`
avec un statut, jamais d'exception non gérée vers l'orchestrateur.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RawListing:
    """Annonce brute renvoyée par un connecteur.

    Champs minimums attendus côté ingestion ; le reste va dans `extra`.
    """

    source: str
    source_id: str | None = None
    url: str | None = None
    titre: str | None = None
    description: str | None = None
    type_bien: str | None = None
    prix: float | None = None
    surface_m2: float | None = None
    nb_pieces: int | None = None
    dpe: str | None = None
    code_postal: str | None = None
    ville_nom: str | None = None
    adresse: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    charges_copro_annuelles: float | None = None
    taxe_fonciere_annuelle: float | None = None
    loyer_mensuel_estime: float | None = None
    travaux_estimes: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorResult:
    """Résultat d'un passage de connecteur."""

    statut: str  # "ok", "erreur", "bloque", "desactive"
    listings: list[RawListing] = field(default_factory=list)
    message: str | None = None
    debut: datetime = field(default_factory=datetime.utcnow)
    fin: datetime | None = None


class BaseConnector(ABC):
    """Interface des connecteurs d'annonces (Couche B).

    Sous-classe : implémenter `fetch_listings()`. Le wrapper `run()` capture
    toutes les exceptions et renvoie un `ConnectorResult` propre.
    """

    name: str = "base"
    enabled: bool = False
    # Throttling : délai minimum entre 2 requêtes HTTP (secondes).
    request_delay_s: float = 2.0
    # User-Agent identifiable.
    user_agent: str = "invest-immo-scrapper/0.1 (+local; usage personnel)"

    @abstractmethod
    def fetch_listings(self, **kwargs) -> list[RawListing]:
        """Récupère une liste d'annonces brutes."""

    def run(self, **kwargs) -> ConnectorResult:
        result = ConnectorResult(statut="ok")
        if not self.enabled:
            result.statut = "desactive"
            result.message = f"Connecteur {self.name} désactivé (cf .env)."
            result.fin = datetime.utcnow()
            return result
        try:
            result.listings = self.fetch_listings(**kwargs)
            result.message = f"{len(result.listings)} annonce(s) récupérée(s)."
        except BlockedError as exc:
            logger.warning("Connecteur %s bloqué : %s", self.name, exc)
            result.statut = "bloque"
            result.message = str(exc)
        except Exception as exc:  # garde-fou large : on ne crashe jamais
            logger.exception("Connecteur %s en erreur", self.name)
            result.statut = "erreur"
            result.message = f"{type(exc).__name__}: {exc}"
        finally:
            result.fin = datetime.utcnow()
        return result


class BlockedError(RuntimeError):
    """Levée quand un connecteur reçoit un 403/429 ou un challenge anti-bot."""
