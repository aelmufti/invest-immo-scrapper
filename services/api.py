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
from fastapi.responses import HTMLResponse
from urllib.parse import quote as _urlquote
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
# Bookmarklet — page HTML autonome (hors iframe Streamlit) pour permettre
# le drag du favori vers la barre du navigateur.
# ---------------------------------------------------------------------------

_BOOKMARKLET_JS = """
(function () {
  var API = "__API__";
  try {
    var lds = [];
    document.querySelectorAll('script[type="application/ld+json"]').forEach(function(s){
      try { lds.push(JSON.parse(s.textContent)); } catch(e) {}
    });
    var og = {};
    document.querySelectorAll('meta[property], meta[name]').forEach(function(m){
      var k = m.getAttribute('property') || m.getAttribute('name');
      var v = m.getAttribute('content');
      if (k && v) og[k] = v;
    });
    var text = (document.body.innerText || "").slice(0, 100000);
    var payload = { url: location.href, title: document.title, text: text, json_ld: lds, og: og };
    fetch(API, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) })
      .then(function(r){ return r.json(); })
      .then(function(j){ alert("\\u2705 Bien #" + j.bien_id + " " + (j.nouveau ? "nouveau" : "mis a jour") + " (source: " + j.source + ")"); })
      .catch(function(e){ alert("\\u274C Echec import : " + e); });
  } catch (e) {
    alert("\\u274C Erreur bookmarklet : " + e);
  }
})();
""".strip()


_BOOKMARKLET_LIST_JS = """
(function () {
  var API = "__API__";
  var IMMO = ["Product","Offer","RealEstateListing","Apartment","House","Residence","SingleFamilyResidence","Accommodation"];
  try {
    // 1) Collecte tous les blocs JSON-LD
    var lds = [];
    document.querySelectorAll('script[type="application/ld+json"]').forEach(function(s){
      try { lds.push(JSON.parse(s.textContent)); } catch(e) {}
    });

    // 2) Walk recursif pour trouver tous les noeuds immo avec contenu utile
    var items = [];
    function walk(o) {
      if (Array.isArray(o)) o.forEach(walk);
      else if (o && typeof o === 'object') {
        var t = o['@type'];
        if (typeof t === 'string') t = [t];
        if (Array.isArray(t) && t.some(function(x){ return IMMO.indexOf(x) >= 0; })) {
          if (o.price || o.offers || o.floorSize || o.numberOfRooms) items.push(o);
        }
        Object.keys(o).forEach(function(k){ walk(o[k]); });
      }
    }
    lds.forEach(walk);

    // 3) Dedupe sur url|name|hash
    var seen = {};
    items = items.filter(function(it){
      var k = (it.url || it.name || JSON.stringify(it).slice(0, 80));
      if (seen[k]) return false; seen[k] = 1; return true;
    });

    // 4) Fallback DOM si rien trouve : detecte les cards repetitives
    //    avec un lien interne et un prix visible.
    if (items.length < 2) {
      var cards = [];
      var hostname = location.hostname.replace(/^www\\./,'');
      document.querySelectorAll('a[href]').forEach(function(a){
        var href = a.href;
        if (!href || !href.indexOf) return;
        // garde les liens internes ressemblant a une fiche detail
        if (href.indexOf(hostname) < 0 && href.indexOf('://') >= 0) return;
        if (!/annonce|bien|detail|listing|/.test(href)) {/*pass*/}
        var card = a.closest('article, li, div, section');
        if (!card) return;
        var txt = (card.innerText || '').slice(0, 2000);
        var mPrix = txt.match(/(\\d[\\d\\s.]{2,8})\\s*\\u20AC/);
        if (!mPrix) return;
        if (cards.length && cards[cards.length-1].href === href) return;
        cards.push({ href: href, text: txt });
      });
      // dedupe par href
      var seenH = {};
      cards = cards.filter(function(c){ if(seenH[c.href]) return false; seenH[c.href]=1; return true; });
      if (cards.length >= 2) {
        items = cards.map(function(c){
          return { '@type':'RealEstateListing', url: c.href, name: c.text.split('\\n')[0].slice(0,120), description: c.text };
        });
      }
    }

    if (items.length === 0) {
      alert("\\u26A0\\uFE0F Aucune annonce detectee sur cette page.\\nUtilisez plutot le bookmarklet 'Importer cette annonce' sur une fiche detail.");
      return;
    }

    if (!confirm("Importer " + items.length + " annonce(s) detectee(s) sur cette page ?")) return;

    var ok = 0, ko = 0, done = 0;
    function finish() {
      done++;
      if (done === items.length) {
        alert("\\u2705 Import liste : " + ok + " OK, " + ko + " echec(s) sur " + items.length + ".");
      }
    }

    items.forEach(function(it){
      var hasText = !!(it.description && it.description.length > 80);
      var payload = {
        url: it.url || location.href,
        title: it.name || document.title,
        text: hasText ? it.description : null,
        json_ld: [it],
        og: {}
      };
      fetch(API, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload) })
        .then(function(r){ return r.json(); })
        .then(function(j){ if (j && j.bien_id) ok++; else ko++; finish(); })
        .catch(function(){ ko++; finish(); });
    });
  } catch (e) {
    alert("\\u274C Erreur bookmarklet liste : " + e);
  }
})();
""".strip()


def _make_bookmarklet_href(js_src: str, api_url: str) -> str:
    js_compact = " ".join(line.strip() for line in js_src.splitlines() if line.strip())
    js_compact = js_compact.replace("__API__", api_url)
    return "javascript:" + _urlquote(js_compact, safe="")


@app.get("/bookmarklet", response_class=HTMLResponse)
def bookmarklet_page() -> str:
    """Page HTML autonome avec les favoris draggables.

    Servie hors iframe Streamlit pour que le drag-and-drop fonctionne.
    """
    settings = get_settings()
    api_url = f"http://{settings.api_host}:{settings.api_port}/biens/import/page"
    href_one = _make_bookmarklet_href(_BOOKMARKLET_JS, api_url)
    href_list = _make_bookmarklet_href(_BOOKMARKLET_LIST_JS, api_url)
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>Bookmarklets — Invest-Immo</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 760px; margin: 2em auto; padding: 0 1em; color: #222; }}
  a.btn {{ display:inline-block; padding:0.8em 1.4em; color:white;
          border-radius:6px; text-decoration:none; font-weight:600; font-size:1.05em; margin-right: 0.6em; }}
  a.btn1 {{ background:#1f77b4; }}
  a.btn2 {{ background:#ff7f0e; }}
  code {{ background:#f4f4f4; padding:0.1em 0.4em; border-radius:3px; }}
  .url-box {{ background:#f9f9f9; border:1px solid #ddd; padding:1em; border-radius:6px;
             word-break:break-all; font-family: monospace; font-size:0.75em; max-height: 8em; overflow: auto; }}
  .ok {{ color:#1a7f37; }} .warn {{ color:#9a6700; }}
  h2 {{ margin-top: 2em; border-top: 1px solid #eee; padding-top: 1em; }}
  details {{ margin: 1em 0; }}
</style></head>
<body>
<h1>🔖 Bookmarklets — Invest-Immo</h1>

<p><strong>Glissez ces boutons dans votre barre de favoris</strong> (⌘+Maj+B pour l'afficher) :</p>

<p>
  <a class="btn btn1" href="{href_one}">📥 Importer cette annonce</a>
  <a class="btn btn2" href="{href_list}">📋 Importer toute la liste</a>
</p>

<p class="warn">⚠️ Si le drag ne marche pas, voir « Installation manuelle » en bas.</p>

<h2>📥 « Importer cette annonce »</h2>
<p>À utiliser sur une <strong>fiche détail</strong> d'annonce (Bien'ici, SeLoger, Leboncoin, Castorus…).
Capture JSON-LD + OpenGraph + texte de la page, importe <strong>un</strong> bien.</p>
<ol>
  <li>Ouvrez une fiche détail dans ce navigateur.</li>
  <li>Cliquez le favori.</li>
  <li>Alerte « ✅ Bien #N créé » → visible dans <em>📦 Annonces</em>.</li>
</ol>

<h2>📋 « Importer toute la liste »</h2>
<p>À utiliser sur une <strong>page de résultats</strong> (recherche Castorus, liste Bien'ici, etc.).
Détecte automatiquement toutes les annonces visibles (via JSON-LD multi-items ou fallback DOM heuristique),
demande confirmation (« Importer N annonces ? »), puis envoie un POST par bien.</p>
<ol>
  <li>Faites une recherche filtrée sur le site (ex: Castorus 72000, prix max 110k, DPE A-D).</li>
  <li>Cliquez le favori.</li>
  <li>Confirmez le nombre détecté.</li>
  <li>Alerte finale : « ✅ Import liste : N OK, M échec(s) ».</li>
</ol>
<p class="warn">⚠️ Limitations connues : les pages liste contiennent souvent moins de champs par carte
(pas toujours de DPE, charges, taxe foncière). Pour enrichir un bien, retournez sur sa fiche détail
et utilisez « 📥 Importer cette annonce » — il fera un <em>upsert</em> sur la même URL.</p>

<h2>Installation manuelle</h2>
<p>Si le drag-and-drop ne marche pas dans votre navigateur :</p>
<ol>
  <li>Clic droit sur la barre de favoris → <em>Ajouter une page…</em></li>
  <li>Nom : <code>📥 Importer cette annonce</code> (ou <code>📋 Importer la liste</code>)</li>
  <li>URL : coller la chaîne <code>javascript:…</code> correspondante ci-dessous.</li>
</ol>
<details><summary>URL « 📥 Importer cette annonce »</summary>
<div class="url-box">{href_one}</div></details>
<details><summary>URL « 📋 Importer toute la liste »</summary>
<div class="url-box">{href_list}</div></details>

<h2 class="ok">Tout reste local</h2>
<p>L'API ({api_url}) écoute sur <code>127.0.0.1</code>. Aucune donnée ne sort de votre machine.</p>

</body></html>"""


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
