"""Détection des opportunités à signaler.

Stratégie : à chaque cycle de recalcul, on parcourt les biens et on lève une
alerte si :
- nouveau bien (`vu_le` récent) ET score >= seuil
- ou si le score du bien franchit le seuil pour la première fois (sa dernière
  alerte score_eleve éventuelle est plus ancienne que la dernière fois où le
  score était sous le seuil)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import desc, select

from data.database import session_scope
from data.models import Alerte, Analyse, Bien, Parametres
from data.repositories import add_alerte, get_parametres

logger = logging.getLogger(__name__)


def detecter_alertes(fenetre_nouveaute_heures: int = 48) -> list[int]:
    """Analyse les biens et crée des alertes si nécessaire. Renvoie les IDs créés."""
    crees: list[int] = []
    seuil_par_defaut = 70.0
    fenetre = timedelta(hours=fenetre_nouveaute_heures)
    now = datetime.utcnow()

    with session_scope() as s:
        p = get_parametres(s)
        seuil = p.score_alerte_seuil or seuil_par_defaut

        biens = list(s.scalars(select(Bien).where(Bien.actif.is_(True))))
        for b in biens:
            # Dernière analyse
            last = s.scalars(
                select(Analyse).where(Analyse.bien_id == b.id)
                .order_by(desc(Analyse.calcule_le)).limit(1)
            ).first()
            if last is None or last.score is None:
                continue

            score_eleve = last.score >= seuil
            est_nouveau = (now - b.vu_le) <= fenetre

            # 1) Nouveauté à score élevé
            if est_nouveau and score_eleve:
                deja = s.scalars(
                    select(Alerte).where(
                        Alerte.bien_id == b.id, Alerte.type == "nouveau_bien"
                    ).limit(1)
                ).first()
                if deja is None:
                    a = add_alerte(
                        s,
                        bien_id=b.id,
                        type="nouveau_bien",
                        titre=f"Nouveau bien à fort potentiel — score {last.score:.0f}",
                        message=(
                            f"{b.titre or b.ville_nom or 'Bien'} : {b.prix or '?'} €, "
                            f"{b.surface_m2 or '?'} m². Cash-flow {last.cashflow_mensuel:+.0f} €/mois."
                        ),
                        score=last.score,
                    )
                    crees.append(a.id)
                    continue  # un seul type d'alerte par bien / cycle

            # 2) Score qui passe au-dessus du seuil sans alerte précédente
            if score_eleve:
                deja = s.scalars(
                    select(Alerte).where(
                        Alerte.bien_id == b.id, Alerte.type == "score_eleve"
                    ).order_by(desc(Alerte.cree_le)).limit(1)
                ).first()
                # Si dernière alerte score_eleve > 30 jours, on peut re-déclencher
                if deja is None or (now - deja.cree_le) > timedelta(days=30):
                    a = add_alerte(
                        s,
                        bien_id=b.id,
                        type="score_eleve",
                        titre=f"Bien franchit le seuil — score {last.score:.0f}",
                        message=(
                            f"{b.titre or b.ville_nom or 'Bien'} : score {last.score:.0f} "
                            f"(seuil {seuil:.0f})."
                        ),
                        score=last.score,
                    )
                    crees.append(a.id)

    if crees:
        logger.info("Alertes créées : %s", crees)
    return crees
