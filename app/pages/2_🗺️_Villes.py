"""Page Villes — carte + tableau + ajout d'une ville par code INSEE/CP/nom."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from connectors.geo import search_communes_by_name, search_communes_by_postal
from services.villes_service import list_villes, refresh_ville_by_insee

st.set_page_config(page_title="Villes", page_icon="🗺️", layout="wide")
st.title("🗺️ Explorer les villes")

# --- Ajout d'une ville
with st.expander("➕ Ajouter / rafraîchir une commune", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        cp = st.text_input("Code postal", placeholder="ex : 72000")
        if cp:
            res = search_communes_by_postal(cp.strip())
            if not res:
                st.warning("Aucune commune trouvée.")
            else:
                choix = st.selectbox(
                    "Choisir une commune",
                    res,
                    format_func=lambda r: f"{r.nom} ({r.code_insee}) — {r.population or '?'} hab.",
                )
                if st.button("Rafraîchir cette ville", key="btn_cp"):
                    with st.spinner("Chargement DVF…"):
                        v = refresh_ville_by_insee(choix.code_insee)
                    if v:
                        st.success(f"OK : {v['nom']} — médiane {v['dvf_prix_m2_median']:.0f} €/m²"
                                   if v.get("dvf_prix_m2_median") else f"OK : {v['nom']} (DVF indisponible)")
                    else:
                        st.error("Echec.")
    with c2:
        nom = st.text_input("Recherche par nom", placeholder="ex : Le Mans")
        if nom and len(nom) >= 2:
            res = search_communes_by_name(nom.strip())
            if not res:
                st.warning("Aucune commune trouvée.")
            else:
                choix = st.selectbox(
                    "Choisir une commune",
                    res,
                    format_func=lambda r: f"{r.nom} ({r.code_insee}) — {r.population or '?'} hab.",
                    key="sel_nom",
                )
                if st.button("Rafraîchir cette ville", key="btn_nom"):
                    with st.spinner("Chargement DVF…"):
                        v = refresh_ville_by_insee(choix.code_insee)
                    if v:
                        st.success(f"OK : {v['nom']}")
                    else:
                        st.error("Echec.")

# --- Tableau
villes = list_villes()
if not villes:
    st.info("Aucune ville en cache. Ajoutez-en une ci-dessus.")
    st.stop()

df = pd.DataFrame(villes)

cols_show = [
    "code_insee", "nom", "code_postal", "departement", "population",
    "dvf_prix_m2_median", "dvf_prix_m2_moyen", "dvf_nb_mutations", "dvf_annee_ref",
    "loyer_m2_estime", "distance_paris_km",
]
existing = [c for c in cols_show if c in df.columns]
df_show = df[existing].copy()

# Filtres
c1, c2, c3 = st.columns(3)
with c1:
    dept_filter = st.multiselect(
        "Département(s)", sorted([d for d in df["departement"].dropna().unique()])
    )
with c2:
    prix_min, prix_max = st.slider(
        "Prix €/m² (médiane DVF)",
        min_value=0, max_value=int(df["dvf_prix_m2_median"].max() or 10000) + 500,
        value=(0, int(df["dvf_prix_m2_median"].max() or 10000) + 500),
    )
with c3:
    pop_min = st.number_input("Population min", value=0, step=1000)

mask = pd.Series(True, index=df.index)
if dept_filter:
    mask &= df["departement"].isin(dept_filter)
mask &= df["dvf_prix_m2_median"].fillna(0).between(prix_min, prix_max)
mask &= df["population"].fillna(0) >= pop_min

st.subheader(f"Villes ({mask.sum()}/{len(df)})")
st.dataframe(df_show[mask], hide_index=True, use_container_width=True)

# --- Carte
if "latitude" in df.columns and "longitude" in df.columns:
    df_map = df[mask & df["latitude"].notna() & df["longitude"].notna()][
        ["latitude", "longitude", "nom"]
    ]
    if not df_map.empty:
        st.subheader("Carte")
        st.map(df_map, latitude="latitude", longitude="longitude")
