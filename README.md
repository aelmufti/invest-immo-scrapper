# Invest-Immo-Scrapper

Outil local d'aide à la décision pour l'investissement locatif en France.
Tourne en continu sur votre machine (service de fond + interface web).

> ⚠️ **Outil d'aide à la décision**, pas un conseil financier, fiscal ou juridique.
> Les estimations s'appuient sur des moyennes (DVF, ratios locatifs). Faites toujours
> valider une opération par un courtier, un notaire et un expert-comptable LMNP.

## Aperçu

L'application est découpée en deux couches **volontairement indépendantes** :

- **Couche A — Données légales et robustes** (priorité) : agrège les prix réels
  de vente (DVF / data.gouv.fr), le géocodage (BAN — adresse.data.gouv.fr) et
  la cartographie administrative (geo.api.gouv.fr). Permet de calculer prix au m²,
  rendement et cash-flow théoriques sans aucun scraping.
- **Couche B — Annonces (optionnelle)** : import manuel (coller le texte d'une
  annonce / CSV) **toujours fonctionnel**, et connecteurs par site désactivés
  par défaut, isolés derrière une interface commune (`BaseConnector`).

Le moteur financier compare 3 régimes (nu, micro-BIC meublé, LMNP au réel avec
amortissement par composants) et calcule le **cash-flow mensuel net-net** après
impôt et prélèvements sociaux.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate    # ou .venv\Scripts\activate sous Windows
pip install -r requirements.txt
cp .env.example .env         # adapter au besoin
```

## Lancement

Point d'entrée unique qui démarre l'API FastAPI + le scheduler **et** l'UI Streamlit :

```bash
python run.py
```

- API : http://127.0.0.1:8765 (docs : `/docs`)
- UI  : http://127.0.0.1:8501

Pour ne lancer qu'un composant :

```bash
python run.py --api        # API + scheduler uniquement
python run.py --ui         # UI uniquement (la base doit déjà exister)
```

## Tests

```bash
pytest -v
```

33 tests couvrent `finance.py`, `scoring.py` et `core/parser.py`
(cas chiffrés vérifiables — voir `tests/test_finance.py`).

## Démo rapide

1. `python run.py` → ouvre `http://127.0.0.1:8501`.
2. Page **🗺️ Villes** → ajoutez par exemple `72000` (Le Mans) puis `Rafraîchir`
   → la médiane DVF s'affiche (~2 000 €/m² sur ~2 400 mutations 2025).
3. Page **📦 Annonces** → onglet *Coller une annonce*, collez :
   ```
   T3 65 m² 2e étage, DPE D, construit en 1985. Prix 79 000 €.
   Charges 900 €/an. Taxe foncière 800 €. Loyer 825 €/mois. 72000 Le Mans.
   ```
   → bien #N créé, scoré ~75/100, cash-flow LMNP ~+135 €/mois, alerte
   "nouveau bien à fort potentiel" dans `/alertes`.
4. Page **⚖️ Comparateur** → sélectionnez 2-3 biens pour les juxtaposer.
5. Le scheduler tourne en tâche de fond et recalcule scores + alertes
   selon les fréquences de `.env`.

## API REST

L'API expose les mêmes données que l'UI à `http://127.0.0.1:8765`
(documentation interactive : `/docs`). Endpoints clés :
- `GET /health`, `GET /parametres`, `PUT /parametres`
- `GET /villes`, `POST /villes/{insee}/refresh`
- `GET /biens`, `GET /biens/{id}`, `POST /biens/import/{texte,csv}`
- `POST /analyses/run` (force un cycle complet)
- `GET /alertes`

## Structure

```
app/         # interface Streamlit (pages)
core/        # logique métier : finance.py, scoring.py, parser.py
data/        # accès base : models.py, database.py, repositories.py
connectors/  # ingestion : dvf.py, ban.py, geo.py, base.py, example.py
services/    # scheduler.py, notify.py, api.py
tests/       # pytest
scripts/     # scripts d'amorçage / maintenance
```

## Limites & légalité

- **DVF** : données officielles de l'État, publiées avec un trimestre de décalage.
  Couvre les ventes ; les biens neufs (VEFA) y sont peu représentés.
- **Estimations de loyer** : reposent sur des ratios loyer/m² par ville
  paramétrables. À recouper avec une étude de marché locale.
- **Scraping (couche B)** : peut violer les CGU des sites tiers
  (SeLoger, LeBonCoin, etc.). C'est **désactivé par défaut**, à activer
  sous votre responsabilité. L'outil respecte `robots.txt`, throttle ses
  requêtes et n'embarque aucun système de contournement anti-bot (pas de
  solveur de captcha, pas de proxy furtif). Si un site bloque, le connecteur
  est marqué "indisponible" et n'impacte pas le reste de l'app.
- **Fiscalité 2026** : micro-BIC meublé longue durée = 50 % d'abattement,
  plafond 77 700 € ; LMNP au réel = amortissements non créateurs de déficit
  imputable sur le revenu global, réintégrés dans la plus-value à la revente
  (depuis février 2025).

## Licence

Usage personnel.
