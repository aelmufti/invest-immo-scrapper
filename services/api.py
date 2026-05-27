"""API FastAPI — expose les données et permet de déclencher manuellement les jobs.

Endpoints principaux :
- GET  /health                       — santé
- GET  /parametres                   — paramètres utilisateur
- PUT  /parametres                   — MAJ paramètres utilisateur
- GET  /villes                       — liste des villes en cache
- POST /villes/{code_insee}/refresh  — déclenche un refresh d'une ville
- GET  /biens                        — liste des biens
- GET  /biens/{id}                   — détail d'un bien + dernière analyse
- DELETE /biens/{id}                 — supprime un bien (cascade analyses)
- POST /biens/delete-batch           — supprime plusieurs biens d'un coup
- POST /biens/import/texte           — coller une annonce
- POST /biens/import/csv             — upload CSV
- POST /biens/import/page            — ingestion via bookmarklet (JSON-LD + OG + texte)
- POST /connectors/run               — passe tous les connecteurs activés
- POST /analyses/run                 — recalcule toutes les analyses + alertes
- GET  /alertes                      — journal des alertes
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc, select

from connectors.example import all_connectors
from core.settings import get_settings, setup_logging
from data.database import init_db, session_scope
from data.models import Analyse, Bien, Parametres, Ville, Alerte
from data.repositories import get_parametres
from services.alertes_service import detecter_alertes
from services.analyse_service import analyser_un_bien, reanalyser_tous
from services.ingest_service import ingest_connector, ingest_csv, ingest_texte
from services.notify import envoyer_alertes_en_attente
from services.page_ingest import ingest_page_payload
from services.scheduler import build_scheduler
from services.villes_service import (
    list_villes,
    refresh_ville_by_insee,
    refresh_villes_existantes,
)

logger = logging.getLogger(__name__)

# Scheduler référence partagée pour shutdown propre
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    setup_logging()
    init_db()
    global _scheduler
    _scheduler = build_scheduler()
    _scheduler.start()
    logger.info("API & scheduler démarrés")
    try:
        yield
    finally:
        if _scheduler:
            _scheduler.shutdown(wait=False)
        logger.info("API & scheduler arrêtés")


app = FastAPI(
    title="invest-immo-scrapper",
    version="0.1",
    description="API locale pour l'analyse d'investissement locatif (DVF + ingestion).",
    lifespan=lifespan,
)

# Le bookmarklet poste depuis le domaine du site visité vers 127.0.0.1.
# L'API n'écoute que sur la loopback : un site distant ne peut atteindre
# 127.0.0.1 que via le navigateur de l'utilisateur, qui contrôle la page.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------

class ParametresIn(BaseModel):
    revenus_nets_mensuels: float | None = None
    apport_disponible: float | None = None
    tmi: float | None = None
    taux_credit: float | None = None
    taux_assurance: float | None = None
    duree_credit_annees: int | None = None
    frais_notaire_pct: float | None = None
    vacance_locative_pct: float | None = None
    frais_gestion_pct: float | None = None
    assurance_pno_annuelle: float | None = None
    entretien_pct_loyer: float | None = None
    charges_copro_part_locataire: float | None = None
    distance_max_paris_km: float | None = None
    prix_max: float | None = None
    rendement_brut_min: float | None = None
    score_alerte_seuil: float | None = None
    exclure_dpe_fg: bool | None = None
    poids_cashflow: float | None = None
    poids_rendement: float | None = None
    poids_decote_dvf: float | None = None
    poids_dpe: float | None = None
    poids_tension: float | None = None
    poids_distance: float | None = None
    poids_travaux: float | None = None


def _parametres_to_dict(p: Parametres) -> dict:
    return {c.name: getattr(p, c.name) for c in p.__table__.columns}


@app.get("/parametres")
def get_parametres_api() -> dict:
    with session_scope() as s:
        return _parametres_to_dict(get_parametres(s))


@app.put("/parametres")
def put_parametres(payload: ParametresIn) -> dict:
    with session_scope() as s:
        p = get_parametres(s)
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(p, k, v)
        s.flush()
        return _parametres_to_dict(p)


# ---------------------------------------------------------------------------
# Villes
# ---------------------------------------------------------------------------

@app.get("/villes")
def get_villes() -> list[dict]:
    return list_villes()


@app.post("/villes/{code_insee}/refresh")
def post_refresh_ville(code_insee: str) -> dict:
    v = refresh_ville_by_insee(code_insee)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Commune {code_insee} introuvable")
    return v


@app.post("/villes/refresh-toutes")
def post_refresh_toutes() -> dict:
    n = refresh_villes_existantes()
    return {"villes_rafraichies": n}


# ---------------------------------------------------------------------------
# Biens
# ---------------------------------------------------------------------------

def _bien_to_dict(b: Bien) -> dict:
    return {c.name: getattr(b, c.name) for c in b.__table__.columns}


@app.get("/biens")
def get_biens(limit: int = Query(200, ge=1, le=2000), actif: bool = True) -> list[dict]:
    with session_scope() as s:
        q = select(Bien)
        if actif:
            q = q.where(Bien.actif.is_(True))
        q = q.order_by(desc(Bien.vu_le)).limit(limit)
        biens = list(s.scalars(q))
        out = []
        for b in biens:
            d = _bien_to_dict(b)
            # joindre la dernière analyse pour le tableau
            last = s.scalars(
                select(Analyse).where(Analyse.bien_id == b.id)
                .order_by(desc(Analyse.calcule_le)).limit(1)
            ).first()
            if last is not None:
                d["analyse"] = {
                    "score": last.score,
                    "cashflow_mensuel": last.cashflow_mensuel,
                    "rendement_brut": last.rendement_brut,
                    "regime_optimal": last.regime_optimal,
                    "calcule_le": last.calcule_le.isoformat() if last.calcule_le else None,
                }
            out.append(d)
        return out


@app.delete("/biens/{bien_id}")
def delete_bien(bien_id: int) -> dict:
    """Supprime définitivement un bien et ses analyses (cascade)."""
    with session_scope() as s:
        b = s.get(Bien, bien_id)
        if b is None:
            raise HTTPException(status_code=404, detail="Bien inconnu")
        s.delete(b)
    return {"supprime": bien_id}


class DeleteBatchIn(BaseModel):
    ids: list[int]


@app.post("/biens/delete-batch")
def delete_biens_batch(payload: DeleteBatchIn) -> dict:
    """Supprime plusieurs biens d'un coup."""
    if not payload.ids:
        return {"supprimes": 0, "ids": []}
    supprimes: list[int] = []
    with session_scope() as s:
        for i in payload.ids:
            b = s.get(Bien, i)
            if b is not None:
                s.delete(b)
                supprimes.append(i)
    return {"supprimes": len(supprimes), "ids": supprimes}


@app.get("/biens/{bien_id}")
def get_bien(bien_id: int) -> dict:
    with session_scope() as s:
        b = s.get(Bien, bien_id)
        if b is None:
            raise HTTPException(status_code=404, detail="Bien inconnu")
        d = _bien_to_dict(b)
        last = s.scalars(
            select(Analyse).where(Analyse.bien_id == b.id)
            .order_by(desc(Analyse.calcule_le)).limit(1)
        ).first()
        d["analyse"] = (
            {c.name: getattr(last, c.name) for c in last.__table__.columns}
            if last else None
        )
        return d


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

class ImportTexteIn(BaseModel):
    texte: str


@app.post("/biens/import/texte")
def post_import_texte(payload: ImportTexteIn) -> dict:
    return ingest_texte(payload.texte)


class ImportCsvIn(BaseModel):
    contenu_csv: str


@app.post("/biens/import/csv")
def post_import_csv(payload: ImportCsvIn) -> dict:
    return ingest_csv(payload.contenu_csv)


class ImportPageIn(BaseModel):
    url: str | None = None
    title: str | None = None
    text: str | None = None
    html: str | None = None
    json_ld: list[Any] | None = None
    og: dict[str, str] | None = None


@app.post("/biens/import/page")
def post_import_page(payload: ImportPageIn) -> dict:
    """Ingestion d'une page capturée par le bookmarklet.

    Le navigateur de l'utilisateur poste ici le contenu déjà chargé
    (JSON-LD + OpenGraph + innerText). Pas de requête sortante depuis
    le serveur — l'utilisateur reste l'agent qui consulte la page.
    """
    r = ingest_page_payload(payload.model_dump())
    # Analyse immédiate pour avoir un score dans la foulée
    try:
        analyser_un_bien(r["bien_id"])
    except Exception:
        logger.exception("Analyse post-ingestion échouée pour bien %s", r.get("bien_id"))
    return r


# ---------------------------------------------------------------------------
# Connecteurs
# ---------------------------------------------------------------------------

@app.post("/connectors/run")
def post_connectors_run() -> list[dict]:
    out = []
    for c in all_connectors():
        out.append(ingest_connector(c))
    return out


# ---------------------------------------------------------------------------
# Analyses & alertes
# ---------------------------------------------------------------------------

@app.post("/analyses/run")
def post_analyses_run() -> dict:
    recap = reanalyser_tous()
    alertes = detecter_alertes()
    envoi = envoyer_alertes_en_attente()
    return {"reanalyse": recap, "alertes_creees": len(alertes), "notif": envoi}


@app.post("/analyses/{bien_id}")
def post_analyse_bien(bien_id: int) -> dict:
    r = analyser_un_bien(bien_id)
    if r is None:
        raise HTTPException(status_code=400, detail="Bien ininterprétable (prix/surface manquants)")
    return r


@app.get("/alertes")
def get_alertes(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    with session_scope() as s:
        rows = list(
            s.scalars(select(Alerte).order_by(desc(Alerte.cree_le)).limit(limit))
        )
        return [
            {c.name: getattr(a, c.name) for c in a.__table__.columns} for a in rows
        ]
