"""Page Bookmarklet — installation + code source du favori navigateur.

Le bookmarklet est un favori JavaScript que l'utilisateur clique
quand il consulte une page d'annonce dans son propre navigateur.
Il collecte ce qui est déjà chargé (JSON-LD + OpenGraph + innerText)
et le poste à l'API locale. Aucune requête HTTP n'est faite côté
serveur vers le site source — l'utilisateur reste l'agent humain
qui consulte la page selon ses propres CGU.
"""

from __future__ import annotations

import urllib.parse

import streamlit as st

from core.settings import get_settings

st.set_page_config(page_title="Bookmarklet", page_icon="🔖", layout="wide")
st.title("🔖 Bookmarklet — capture d'annonces depuis votre navigateur")

settings = get_settings()
api_url = f"http://{settings.api_host}:{settings.api_port}/biens/import/page"

st.markdown(
    f"""
Ce favori (*bookmarklet*) capture la page d'annonce que vous êtes
**en train de consulter** dans votre navigateur et l'envoie à votre
API locale ({api_url}).

> Concrètement : vous ouvrez une fiche sur Bien'ici / SeLoger / Leboncoin
> dans votre navigateur habituel, vous cliquez le favori, et le bien
> apparaît dans `📦 Annonces` avec son score.

**Pourquoi c'est différent du scraping côté serveur :**
- L'application ne fait *aucune* requête sortante vers le site source.
- C'est votre propre navigateur, déjà authentifié à vos CGU, qui charge la page.
- Vous gardez la décision humaine (un clic = un import).
"""
)

# ---------------------------------------------------------------------------
# Le code JS source (lisible)
# ---------------------------------------------------------------------------

bookmarklet_js_lisible = f"""
(function () {{
  const API = "{api_url}";
  try {{
    // 1) JSON-LD : tous les <script type="application/ld+json">
    const lds = [];
    document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {{
      try {{ lds.push(JSON.parse(s.textContent)); }} catch (e) {{ /* ignore JSON cassé */ }}
    }});

    // 2) OpenGraph + Twitter meta
    const og = {{}};
    document.querySelectorAll('meta[property], meta[name]').forEach(m => {{
      const k = m.getAttribute('property') || m.getAttribute('name');
      const v = m.getAttribute('content');
      if (k && v) og[k] = v;
    }});

    // 3) Texte visible
    const text = (document.body.innerText || "").slice(0, 100000);

    const payload = {{
      url: location.href,
      title: document.title,
      text: text,
      json_ld: lds,
      og: og
    }};

    fetch(API, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(payload)
    }})
      .then(r => r.json())
      .then(j => {{
        const id = j.bien_id;
        const nouveau = j.nouveau ? "nouveau" : "mis à jour";
        alert("✅ Bien #" + id + " " + nouveau + " (source: " + j.source + ")");
      }})
      .catch(e => alert("❌ Échec import : " + e));
  }} catch (e) {{
    alert("❌ Erreur bookmarklet : " + e);
  }}
}})();
"""

# Version minifiée -> URL-encodée pour usage javascript:
# (on ne touche pas aux guillemets dans les strings JS, mais on enlève
# les sauts de ligne pour que ça tienne en une seule URL)
def _to_bookmarklet(js: str) -> str:
    # Nettoyage léger : retire les commentaires `// ...` simples et resserre les blancs
    lines = []
    for line in js.splitlines():
        # Retire les commentaires en fin de ligne (heuristique simple : "// " hors string)
        # Ici on garde simple : on supprime juste les commentaires sur leur propre ligne
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(line)
    compact = " ".join(l.strip() for l in lines if l.strip())
    return "javascript:" + urllib.parse.quote(compact, safe="")


bookmarklet_href = _to_bookmarklet(bookmarklet_js_lisible)

# ---------------------------------------------------------------------------
# Étape 1 — installation
# ---------------------------------------------------------------------------

st.subheader("1. Installer le favori")

st.markdown(
    """
**Sur ordinateur (Chrome, Firefox, Safari, Edge) :**
1. Affichez la barre des favoris (Ctrl/⌘ + Maj + B).
2. **Glissez-déposez le lien ci-dessous** dans votre barre de favoris.
3. Renommez-le si vous voulez (ex: « 📥 Importer cette annonce »).
"""
)

# Streamlit ne laisse pas insérer de `javascript:` href dans un st.link_button.
# On utilise un st.markdown avec unsafe_allow_html pour l'ancre draggable.
st.markdown(
    f'''
<a href="{bookmarklet_href}"
   style="display:inline-block;padding:0.6em 1.1em;background:#1f77b4;
          color:white;border-radius:6px;text-decoration:none;font-weight:600;
          font-family:system-ui,sans-serif;">
   📥 Importer cette annonce
</a>
<p style="color:#888;font-size:0.85em;margin-top:0.5em;">
   ↑ glissez ce bouton dans votre barre de favoris.
</p>
''',
    unsafe_allow_html=True,
)

st.info(
    "Si votre navigateur refuse le drag (rare), copiez le code ci-dessous "
    "et créez un favori manuellement avec ce contenu comme URL."
)

with st.expander("Code à copier-coller (URL du favori)"):
    st.code(bookmarklet_href, language="text")

# ---------------------------------------------------------------------------
# Étape 2 — utilisation
# ---------------------------------------------------------------------------

st.subheader("2. Utilisation")

st.markdown(
    """
1. Lancez l'app (`python run.py`) et laissez-la tourner.
2. Dans **votre navigateur habituel**, ouvrez la fiche d'une annonce qui vous intéresse.
3. Cliquez le favori « 📥 Importer cette annonce ».
4. Une alerte « ✅ Bien #N créé » s'affiche.
5. Le bien apparaît dans `📦 Annonces` avec son score et son cash-flow.

**Sites qui marchent bien** (embarquent du JSON-LD `Product` / `RealEstateListing`) :
Bien'ici, SeLoger, Leboncoin (souvent), Logic-Immo, Orpi, Century 21, Laforêt, Guy Hoquet…

Si un site ne fournit pas de JSON-LD, le fallback texte récupèrera quand même
prix, surface et DPE depuis l'innerText visible — moins fiable mais utilisable.
"""
)

# ---------------------------------------------------------------------------
# Étape 3 — code source (transparence)
# ---------------------------------------------------------------------------

st.subheader("3. Code source du bookmarklet")

st.markdown(
    "Pour transparence — voici exactement ce que le favori exécute dans votre navigateur :"
)

st.code(bookmarklet_js_lisible.strip(), language="javascript")

st.caption(
    "Aucune donnée ne quitte votre machine : la requête `fetch` cible "
    f"`{api_url}` (127.0.0.1), votre serveur local."
)
