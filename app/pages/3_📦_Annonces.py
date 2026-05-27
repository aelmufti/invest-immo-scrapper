"""Page Annonces — import, tableau triable, détail par bien."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st
from sqlalchemy import desc, select

from connectors.example import all_connectors
from data.database import session_scope
from data.models import Analyse, Bien
from services.alertes_service import detecter_alertes
from services.analyse_service import analyser_un_bien, reanalyser_tous
from services.ingest_service import ingest_connector, ingest_csv, ingest_texte


def _supprimer_biens(ids: list[int]) -> int:
    """Supprime des biens et leurs analyses (cascade SQLAlchemy)."""
    if not ids:
        return 0
    n = 0
    with session_scope() as s:
        for i in ids:
            b = s.get(Bien, int(i))
            if b is not None:
                s.delete(b)
                n += 1
    return n

st.set_page_config(page_title="Annonces", page_icon="📦", layout="wide")
st.title("📦 Annonces")

# ----------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["📋 Coller une annonce", "📤 Importer un CSV", "🔌 Connecteurs"])

with tab1:
    texte = st.text_area("Collez le texte de l'annonce ici", height=200)
    if st.button("➕ Importer le texte", disabled=not texte.strip()):
        with st.spinner("Parsing…"):
            r = ingest_texte(texte)
            analyser_un_bien(r["bien_id"])
        st.success(f"Bien #{r['bien_id']} importé. Nouveau : {r['nouveau']}.")
        with st.expander("Détails extraits"):
            st.json(r["parsed"])

with tab2:
    st.caption("Colonnes reconnues : prix, surface, pieces, type, dpe, code_postal, ville, "
               "charges_copro, taxe_fonciere, loyer, etage, annee_construction, url, id.")
    f = st.file_uploader("CSV", type=["csv"])
    if f and st.button("➕ Importer le CSV"):
        contenu = f.read().decode("utf-8", errors="ignore")
        with st.spinner("Import…"):
            r = ingest_csv(contenu)
            reanalyser_tous()
        st.success(f"Lignes : {r['nb_lignes']} — nouveaux : {r['nb_nouveaux']}")
        if r["erreurs"]:
            st.warning("Erreurs : " + " ; ".join(r["erreurs"][:5]))

with tab3:
    st.warning(
        "⚠️ Les connecteurs scrapers peuvent violer les CGU des sites tiers. "
        "Activez-les dans `.env` (CONNECTOR_*_ENABLED=true) sous votre responsabilité. "
        "L'app respecte robots.txt, throttle, n'embarque aucun contournement anti-bot."
    )
    cs = all_connectors()
    for c in cs:
        st.markdown(f"- **{c.name}** — {'activé' if c.enabled else 'désactivé'}")
    if st.button("▶️ Lancer un cycle des connecteurs activés"):
        with st.spinner("Lecture…"):
            for c in cs:
                r = ingest_connector(c)
                st.write(r)
            reanalyser_tous()
            detecter_alertes()

st.divider()

# ----------------------------------------------------------------------
# Tableau des biens + dernière analyse
# ----------------------------------------------------------------------

st.subheader("Tableau des biens")

with session_scope() as s:
    rows = []
    for b in s.scalars(select(Bien).where(Bien.actif.is_(True)).order_by(desc(Bien.vu_le))):
        last = s.scalars(
            select(Analyse).where(Analyse.bien_id == b.id)
            .order_by(desc(Analyse.calcule_le)).limit(1)
        ).first()
        rows.append({
            "id": b.id,
            "ville": b.ville_nom,
            "cp": b.code_postal,
            "type": b.type_bien,
            "prix": b.prix,
            "surface": b.surface_m2,
            "pieces": b.nb_pieces,
            "dpe": b.dpe,
            "source": b.source,
            "score": last.score if last else None,
            "cashflow_mensuel": last.cashflow_mensuel if last else None,
            "rdt_brut": last.rendement_brut if last else None,
            "regime": last.regime_optimal if last else None,
            "vu_le": b.vu_le,
        })

if not rows:
    st.info("Aucun bien en base. Importez-en un dans les onglets ci-dessus.")
    st.stop()

df = pd.DataFrame(rows)

# Filtres
c1, c2, c3, c4 = st.columns(4)
with c1:
    score_min = st.slider("Score minimum", 0, 100, 0)
with c2:
    cf_min = st.number_input("CF mensuel min (€)", value=-1000, step=50)
with c3:
    dpe_excl = st.multiselect("Exclure DPE", ["F", "G"])
with c4:
    sources = st.multiselect("Sources", sorted(df["source"].dropna().unique()))

mask = pd.Series(True, index=df.index)
mask &= df["score"].fillna(-1) >= score_min
mask &= df["cashflow_mensuel"].fillna(-9999) >= cf_min
if dpe_excl:
    mask &= ~df["dpe"].isin(dpe_excl)
if sources:
    mask &= df["source"].isin(sources)

df_show = df[mask].sort_values("score", ascending=False, na_position="last")

# Tableau éditable avec colonne "Supprimer" cochable
df_edit = df_show.copy()
df_edit.insert(0, "supprimer", False)

edited = st.data_editor(
    df_edit,
    hide_index=True,
    use_container_width=True,
    disabled=[c for c in df_edit.columns if c != "supprimer"],
    column_config={
        "supprimer": st.column_config.CheckboxColumn(
            "🗑️", help="Cocher pour sélectionner les biens à supprimer", default=False
        ),
    },
    key="biens_editor",
)

ids_a_supprimer = edited.loc[edited["supprimer"], "id"].tolist()

col_a, col_b = st.columns([1, 4])
with col_a:
    confirmer = st.checkbox(
        f"Confirmer la suppression ({len(ids_a_supprimer)})",
        disabled=not ids_a_supprimer,
        key="confirm_del",
    )
with col_b:
    if st.button(
        "🗑️ Supprimer la sélection",
        type="primary",
        disabled=not ids_a_supprimer or not confirmer,
    ):
        n = _supprimer_biens(ids_a_supprimer)
        st.success(f"{n} bien(s) supprimé(s).")
        st.rerun()

# Export
csv_bytes = df_show.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Export CSV", csv_bytes, "biens.csv", "text/csv")

try:
    import openpyxl  # noqa
    buf = io.BytesIO()
    df_show.to_excel(buf, index=False)
    st.download_button("⬇️ Export Excel", buf.getvalue(), "biens.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
except Exception:
    pass

st.divider()

# ----------------------------------------------------------------------
# Détail d'un bien
# ----------------------------------------------------------------------
st.subheader("🔍 Détail d'un bien")
sel = st.selectbox(
    "Choisir un bien",
    df_show["id"].tolist(),
    format_func=lambda i: f"#{i} — {df_show.loc[df_show['id']==i, 'ville'].iloc[0]} — "
                          f"{df_show.loc[df_show['id']==i, 'prix'].iloc[0]} €",
)

if sel:
    with session_scope() as s:
        b = s.get(Bien, int(sel))
        last = s.scalars(
            select(Analyse).where(Analyse.bien_id == b.id)
            .order_by(desc(Analyse.calcule_le)).limit(1)
        ).first()
        bien_dict = {c.name: getattr(b, c.name) for c in b.__table__.columns}
        # Matérialise les attributs nécessaires AVANT la fermeture de la session
        if last is not None:
            last_dict = {
                "score": last.score,
                "cashflow_mensuel": last.cashflow_mensuel,
                "rendement_brut": last.rendement_brut,
                "regime_optimal": last.regime_optimal,
                "snapshot": last.snapshot,
            }
        else:
            last_dict = None
        analyse_snap = last_dict["snapshot"] if last_dict else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score", "—" if last_dict is None else f"{last_dict['score']:.0f}/100")
    c2.metric("Cash-flow mensuel", f"{last_dict['cashflow_mensuel']:+.0f} €" if last_dict and last_dict['cashflow_mensuel'] is not None else "—")
    c3.metric("Rendement brut", f"{last_dict['rendement_brut']*100:.1f} %" if last_dict and last_dict['rendement_brut'] else "—")
    c4.metric("Régime optimal", last_dict['regime_optimal'] if last_dict else "—")

    st.write("**Caractéristiques**")
    st.json({k: v for k, v in bien_dict.items() if v is not None and k not in {"description", "extra"}})

    if analyse_snap:
        with st.expander("Détail financier (3 régimes)"):
            regimes = analyse_snap.get("finance", {}).get("regimes", {})
            df_reg = pd.DataFrame.from_dict(regimes, orient="index")
            st.dataframe(df_reg, use_container_width=True)
        with st.expander("Détail du scoring"):
            details = analyse_snap.get("scoring", {}).get("details", [])
            if details:
                st.dataframe(pd.DataFrame(details), hide_index=True, use_container_width=True)

    col_re, col_del = st.columns(2)
    with col_re:
        if st.button("🔁 Re-analyser ce bien"):
            analyser_un_bien(int(sel))
            st.rerun()
    with col_del:
        confirm_one = st.checkbox(f"Confirmer suppression du bien #{sel}", key=f"confirm_del_{sel}")
        if st.button("🗑️ Supprimer ce bien", type="primary", disabled=not confirm_one):
            n = _supprimer_biens([int(sel)])
            st.success(f"Bien #{sel} supprimé." if n else "Rien à supprimer.")
            st.rerun()
