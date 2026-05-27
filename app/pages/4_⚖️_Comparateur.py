"""Page Comparateur — compare 2 à 3 biens côte à côte."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import desc, select

from data.database import session_scope
from data.models import Analyse, Bien

st.set_page_config(page_title="Comparateur", page_icon="⚖️", layout="wide")
st.title("⚖️ Comparateur de biens")

with session_scope() as s:
    biens = list(s.scalars(select(Bien).where(Bien.actif.is_(True))))
    biens_dicts = [
        {
            "id": b.id,
            "label": f"#{b.id} — {b.ville_nom or '?'} {b.prix or '?'} € {b.surface_m2 or '?'} m²",
        }
        for b in biens
    ]

if not biens_dicts:
    st.info("Aucun bien à comparer.")
    st.stop()

choix = st.multiselect(
    "Choisissez 2 ou 3 biens",
    [b["id"] for b in biens_dicts],
    format_func=lambda i: next(b["label"] for b in biens_dicts if b["id"] == i),
    max_selections=3,
)

if len(choix) < 2:
    st.info("Sélectionnez au moins 2 biens.")
    st.stop()

with session_scope() as s:
    data = {}
    for bid in choix:
        b = s.get(Bien, int(bid))
        last = s.scalars(
            select(Analyse).where(Analyse.bien_id == b.id)
            .order_by(desc(Analyse.calcule_le)).limit(1)
        ).first()
        col = {
            "Ville": b.ville_nom,
            "Code postal": b.code_postal,
            "Type": b.type_bien,
            "Prix": b.prix,
            "Surface m²": b.surface_m2,
            "€/m²": (b.prix / b.surface_m2) if b.prix and b.surface_m2 else None,
            "DPE": b.dpe,
            "Loyer estimé/mois": b.loyer_mensuel_estime,
            "Charges copro/an": b.charges_copro_annuelles,
            "Taxe foncière/an": b.taxe_fonciere_annuelle,
        }
        if last:
            col.update({
                "Mensualité crédit": last.mensualite_credit,
                "Cash-flow mensuel": last.cashflow_mensuel,
                "Cash-flow annuel": last.cashflow_annuel,
                "Rendement brut": last.rendement_brut,
                "Rendement net": last.rendement_net,
                "Rendement net-net": last.rendement_net_net,
                "Régime optimal": last.regime_optimal,
                "Impôt annuel": last.impot_annuel,
                "Score": last.score,
            })
        data[f"#{bid}"] = col

df = pd.DataFrame(data)
st.dataframe(df, use_container_width=True)
