"""Connecteur d'exemple — DESACTIVE PAR DEFAUT.

Sert de squelette/témoin pour montrer comment un connecteur d'annonces s'intègre.
NE FAIT AUCUNE REQUETE HTTP : il renvoie 2 annonces statiques de démonstration.

Pour développer un vrai connecteur (SeLoger, LeBonCoin, etc.) :
1. Hériter de BaseConnector.
2. Respecter `robots.txt`, mettre un User-Agent identifiable.
3. Throttle (`time.sleep(self.request_delay_s)` entre 2 requêtes).
4. Lever `BlockedError` si HTTP 403/429 ou challenge anti-bot — JAMAIS de
   contournement (pas de solveur de captcha, pas de rotation d'IP furtive).
5. Toute autre exception est interceptée par `BaseConnector.run()` : le
   connecteur tombe en statut "erreur" sans casser le reste de l'app.
6. L'activer via la variable d'env (cf .env.example) — désactivé par défaut.

AVERTISSEMENT : le scraping de sites comme SeLoger/LeBonCoin peut violer leurs
CGU. C'est à votre charge et sous votre responsabilité.
"""

from __future__ import annotations

from typing import Any

from connectors.base import BaseConnector, RawListing
from core.settings import get_settings


class ExampleConnector(BaseConnector):
    """Connecteur de démonstration. Activable via CONNECTOR_EXAMPLE_ENABLED=true."""

    name = "example"

    def __init__(self) -> None:
        self.enabled = get_settings().connector_example_enabled

    def fetch_listings(self, **kwargs: Any) -> list[RawListing]:
        # En conditions réelles, ferait des requêtes HTTP avec throttling.
        # Ici, on renvoie deux exemples statiques pour valider le pipeline.
        return [
            RawListing(
                source=self.name,
                source_id="demo-1",
                url="https://example.invalid/annonce/demo-1",
                titre="DEMO — T3 Le Mans centre 65 m²",
                type_bien="appartement",
                prix=165_000,
                surface_m2=65,
                nb_pieces=3,
                dpe="D",
                code_postal="72000",
                ville_nom="Le Mans",
                charges_copro_annuelles=1200,
                taxe_fonciere_annuelle=850,
                loyer_mensuel_estime=750,
                extra={"demo": True},
            ),
            RawListing(
                source=self.name,
                source_id="demo-2",
                url="https://example.invalid/annonce/demo-2",
                titre="DEMO — Studio Rennes 25 m²",
                type_bien="appartement",
                prix=110_000,
                surface_m2=25,
                nb_pieces=1,
                dpe="E",
                code_postal="35000",
                ville_nom="Rennes",
                charges_copro_annuelles=600,
                taxe_fonciere_annuelle=500,
                loyer_mensuel_estime=540,
                extra={"demo": True},
            ),
        ]


def all_connectors() -> list[BaseConnector]:
    """Retourne la liste de tous les connecteurs configurés (activés ou non).

    Pour ajouter un connecteur supplémentaire, l'instancier ici.
    """
    return [ExampleConnector()]
