"""Interface Streamlit — accueil + navigation.

Lit directement la base SQLite (les pages de l'app sont dans `app/pages/`).
"""

from __future__ import annotations

import streamlit as st

from core.settings import setup_logging
from data.database import init_db

# Logging + init DB une seule fois
setup_logging("WARNING")
init_db()

st.set_page_config(
    page_title="invest-immo-scrapper",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 invest-immo-scrapper")
st.caption(
    "Aide à la décision pour l'investissement locatif en France — "
    "DVF (données légales) + ingestion d'annonces optionnelle."
)

with st.container(border=True):
    st.markdown(
        """
        **⚠️ Outil d'aide à la décision** — pas un conseil financier, fiscal ou juridique.

        Les estimations s'appuient sur des moyennes (prix DVF, ratios locatifs).
        Faites valider toute opération par un courtier, un notaire et un
        expert-comptable LMNP.
        """
    )

st.subheader("Navigation")
st.markdown(
    """
    Utilisez la barre latérale (à gauche) ou les boutons ci-dessous pour
    accéder aux pages.
    """
)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.page_link("pages/1_⚙️_Paramètres.py", label="⚙️ Paramètres", use_container_width=True)
with c2:
    st.page_link("pages/2_🗺️_Villes.py", label="🗺️ Explorer les villes", use_container_width=True)
with c3:
    st.page_link("pages/3_📦_Annonces.py", label="📦 Annonces", use_container_width=True)
with c4:
    st.page_link("pages/4_⚖️_Comparateur.py", label="⚖️ Comparateur", use_container_width=True)

st.divider()

# Stats globales rapides
from sqlalchemy import func, select
from data.database import session_scope
from data.models import Alerte, Analyse, Bien, Ville

with session_scope() as s:
    n_villes = s.scalar(select(func.count(Ville.id))) or 0
    n_biens = s.scalar(select(func.count(Bien.id))) or 0
    n_analyses = s.scalar(select(func.count(Analyse.id))) or 0
    n_alertes_non_lues = (
        s.scalar(select(func.count(Alerte.id)).where(Alerte.lu.is_(False))) or 0
    )

m1, m2, m3, m4 = st.columns(4)
m1.metric("Villes en cache", n_villes)
m2.metric("Biens", n_biens)
m3.metric("Analyses", n_analyses)
m4.metric("Alertes non lues", n_alertes_non_lues)
