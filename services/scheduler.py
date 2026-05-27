"""Scheduler APScheduler — orchestre les jobs périodiques.

Jobs :
- refresh DVF (toutes les villes en base) : `SCHED_DVF_REFRESH_MIN`
- passage des connecteurs activés : `SCHED_CONNECTORS_MIN`
- recalcul des analyses + détection d'alertes + notifications : `SCHED_RESCORE_MIN`

Tout job échoué est juste loggué — jamais fatal.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.settings import get_settings
from services.alertes_service import detecter_alertes
from services.analyse_service import reanalyser_tous
from services.ingest_service import ingest_connector
from services.notify import envoyer_alertes_en_attente
from services.villes_service import refresh_villes_existantes

logger = logging.getLogger(__name__)


def job_refresh_dvf() -> None:
    try:
        n = refresh_villes_existantes()
        logger.info("[JOB] DVF refresh : %d villes traitées", n)
    except Exception:
        logger.exception("Job refresh_dvf en erreur")


def job_connectors() -> None:
    try:
        from connectors.example import all_connectors
        for c in all_connectors():
            # `enabled` est lu via .env donc paramétré au démarrage ; on respecte ça.
            r = ingest_connector(c)
            logger.info("[JOB] connecteur %s : %s", c.name, r)
    except Exception:
        logger.exception("Job connecteurs en erreur")


def job_rescore_et_alertes() -> None:
    try:
        recap = reanalyser_tous()
        logger.info("[JOB] Réanalyse : %s", recap)
        alertes_ids = detecter_alertes()
        logger.info("[JOB] %d alertes créées", len(alertes_ids))
        notif = envoyer_alertes_en_attente()
        logger.info("[JOB] Notifications : %s", notif)
    except Exception:
        logger.exception("Job rescore en erreur")


def build_scheduler() -> BackgroundScheduler:
    s = get_settings()
    sched = BackgroundScheduler(daemon=True, timezone="Europe/Paris")

    # On exécute aussi chaque job une fois au démarrage (sauf DVF qui est lourd)
    sched.add_job(
        job_connectors,
        trigger=IntervalTrigger(minutes=s.sched_connectors_min),
        id="connectors",
        name="Passage des connecteurs",
        max_instances=1,
        coalesce=True,
        next_run_time=None,  # géré explicitement à l'init
    )
    sched.add_job(
        job_refresh_dvf,
        trigger=IntervalTrigger(minutes=s.sched_dvf_refresh_min),
        id="dvf_refresh",
        name="Rafraîchissement DVF",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        job_rescore_et_alertes,
        trigger=IntervalTrigger(minutes=s.sched_rescore_min),
        id="rescore",
        name="Recalcul scores + alertes",
        max_instances=1,
        coalesce=True,
    )
    return sched
