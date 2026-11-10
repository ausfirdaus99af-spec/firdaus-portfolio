# Firdaus Zakaria - Portfolio

Personal portfolio website of **Firdaus Zakaria**, a Chemical Engineering
graduate from UiTM (Bachelor, Shah Alam; Diploma, Pasir Gudang), based in Kuala Lumpur.

The site presents his education, verified skills and experience, and four complete,
runnable projects:

> **01 - EcoFlow: Industrial Wastewater Treatment Analytics** - a synthetic-data
> case study in environmental process monitoring ([`ecoflow/`](ecoflow/README.md))
>
> **02 - Synthetic Natural Gas Plant Design** - an educational process-design case
> study with tested mass and energy balances ([`sng/`](sng/))
>
> **03 - Manufacturing Performance Analytics** - OEE, downtime Pareto and SQL
> analysis on synthetic plant records ([`manufacturing/`](manufacturing/))
>
> **04 - KL Mobility Lab** - an open-data investigation of Klang Valley congestion
> and commuting, with a clearly labelled what-if simulator ([`mobility/`](mobility/))

## What is in this repository

| Path | Contents |
|------|----------|
| `index.html`, `css/`, `js/`, `assets/` | The portfolio website (static HTML, CSS and JavaScript) |
| `ecoflow/` | Project 01: dashboard, Python data pipeline, tests and documentation |
| `sng/` | Project 02: process model, tests, design basis and dashboard |
| `manufacturing/` | Project 03: data generator, KPI engine, SQLite + SQL, tests and dashboard |
| `mobility/` | Project 04: source catalogue, data pipeline, SQL, tests, dashboard and simulator |
| `docs/` | Deployment guide, checklists, testing and validation reports |
| `requirements.txt` | Python dependencies for regenerating the datasets |

## Honesty and data policy

- Every dataset in this repository is **made up (synthetic)**, produced by a seeded
  Python generator (`ecoflow/scripts/`). No real plant, company or regulatory data
  appears anywhere.
- The website lists only real, verifiable skills, education and experience.
- EcoFlow is a learning project. The formulas, assumptions and limitations are
  written down in plain language in [`ecoflow/docs/`](ecoflow/docs/) so every
  number on the dashboard can be explained and reproduced.

## Running the site locally

The site is fully static. From the repository root:

```
python -m http.server 8000
```

Then open http://localhost:8000 (the EcoFlow dashboard is at `/ecoflow/`).
Opening `index.html` directly from disk works for the portfolio pages, but the
dashboard loads its dataset with `fetch`, which requires HTTP.

## Regenerating the datasets

```
pip install -r requirements.txt
python ecoflow/scripts/build_dashboard_data.py
python sng/scripts/build_sng_data.py
python manufacturing/scripts/build_mfg_data.py
python mobility/scripts/fetch_sources.py
python -I mobility/scripts/build_mobility_data.py
```

Every generator is deterministic (seeds documented in each project), so the
published datasets reproduce exactly; the mobility pipeline additionally re-downloads
its open-data sources. Each project's tests live in its `tests/` folder and run with
`python -m pytest <project>/tests` (142 tests in total).

## Deployment

The site is designed for GitHub Pages (project site, relative asset paths, no build
step and no server-side code). See [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md).

## Licence

MIT - see [`LICENSE`](LICENSE).
