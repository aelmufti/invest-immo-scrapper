"""Page Paramètres — profil, hypothèses, pondérations du scoring."""

from __future__ import annotations

import streamlit as st

from data.database import session_scope
from data.repositories import get_parametres

st.set_page_config(page_title="Paramètres", page_icon="⚙️", layout="wide")
st.title("⚙️ Paramètres")

with session_scope() as s:
    p = get_parametres(s)
    # snapshot pour rendu
    values = {c.name: getattr(p, c.name) for c in p.__table__.columns}

with st.form("form_params"):
    st.subheader("Profil financier")
    c = st.columns(3)
    revenus = c[0].number_input("Revenus nets mensuels (€)", value=float(values["revenus_nets_mensuels"]), step=100.0)
    apport = c[1].number_input("Apport disponible (€)", value=float(values["apport_disponible"]), step=1000.0)
    tmi = c[2].number_input("TMI (tranche marginale, ex 0.30)", value=float(values["tmi"]), step=0.01, format="%.2f")

    st.subheader("Crédit")
    c = st.columns(3)
    taux = c[0].number_input("Taux crédit (ex 0.0326)", value=float(values["taux_credit"]), step=0.0005, format="%.4f")
    assur = c[1].number_input("Taux assurance (ex 0.0034)", value=float(values["taux_assurance"]), step=0.0005, format="%.4f")
    duree = c[2].number_input("Durée (années)", value=int(values["duree_credit_annees"]), step=1, min_value=5, max_value=30)

    st.subheader("Hypothèses d'exploitation")
    c = st.columns(3)
    fn = c[0].number_input("Frais notaire (% prix)", value=float(values["frais_notaire_pct"]), step=0.01, format="%.3f")
    vac = c[1].number_input("Vacance locative (%)", value=float(values["vacance_locative_pct"]), step=0.01, format="%.3f")
    gest = c[2].number_input("Frais gestion (% loyer)", value=float(values["frais_gestion_pct"]), step=0.01, format="%.3f")
    c = st.columns(3)
    pno = c[0].number_input("Assurance PNO annuelle (€)", value=float(values["assurance_pno_annuelle"]), step=10.0)
    ent = c[1].number_input("Entretien (% loyer)", value=float(values["entretien_pct_loyer"]), step=0.01, format="%.3f")
    copro_loc = c[2].number_input("Part charges copro récupérable", value=float(values["charges_copro_part_locataire"]), step=0.05, format="%.2f")

    st.subheader("Préférences & filtres")
    c = st.columns(3)
    dist = c[0].number_input("Distance max Paris (km)", value=float(values["distance_max_paris_km"] or 400.0), step=10.0)
    pmax = c[1].number_input("Prix max (€)", value=float(values["prix_max"] or 200000.0), step=5000.0)
    rdt_min = c[2].number_input("Rendement brut min", value=float(values["rendement_brut_min"]), step=0.005, format="%.3f")
    c = st.columns(3)
    seuil = c[0].number_input("Seuil alerte (score)", value=float(values["score_alerte_seuil"]), step=5.0)
    excl = c[1].checkbox("Exclure DPE F/G", value=bool(values["exclure_dpe_fg"]))

    st.subheader("Pondérations du scoring (somme normalisée)")
    c = st.columns(7)
    w_cf = c[0].number_input("Cash-flow", value=float(values["poids_cashflow"]), step=5.0)
    w_rdt = c[1].number_input("Rendement", value=float(values["poids_rendement"]), step=5.0)
    w_dec = c[2].number_input("Décote DVF", value=float(values["poids_decote_dvf"]), step=5.0)
    w_dpe = c[3].number_input("DPE", value=float(values["poids_dpe"]), step=5.0)
    w_ten = c[4].number_input("Tension", value=float(values["poids_tension"]), step=5.0)
    w_dst = c[5].number_input("Distance", value=float(values["poids_distance"]), step=5.0)
    w_trv = c[6].number_input("Travaux", value=float(values["poids_travaux"]), step=5.0)

    submit = st.form_submit_button("💾 Enregistrer")

if submit:
    with session_scope() as s:
        p = get_parametres(s)
        p.revenus_nets_mensuels = revenus
        p.apport_disponible = apport
        p.tmi = tmi
        p.taux_credit = taux
        p.taux_assurance = assur
        p.duree_credit_annees = int(duree)
        p.frais_notaire_pct = fn
        p.vacance_locative_pct = vac
        p.frais_gestion_pct = gest
        p.assurance_pno_annuelle = pno
        p.entretien_pct_loyer = ent
        p.charges_copro_part_locataire = copro_loc
        p.distance_max_paris_km = dist
        p.prix_max = pmax
        p.rendement_brut_min = rdt_min
        p.score_alerte_seuil = seuil
        p.exclure_dpe_fg = excl
        p.poids_cashflow = w_cf
        p.poids_rendement = w_rdt
        p.poids_decote_dvf = w_dec
        p.poids_dpe = w_dpe
        p.poids_tension = w_ten
        p.poids_distance = w_dst
        p.poids_travaux = w_trv
    st.success("Paramètres enregistrés. Pensez à relancer une analyse pour appliquer.")
    if st.button("🔁 Relancer l'analyse maintenant"):
        from services.analyse_service import reanalyser_tous
        recap = reanalyser_tous()
        st.info(f"Réanalyse terminée : {recap}")
