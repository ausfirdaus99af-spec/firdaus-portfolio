# Firdaus Zakaria - Portfolio

Personal portfolio website of **Firdaus Zakaria**, a Chemical Engineering
graduate from UiTM (Bachelor, Shah Alam; Diploma, Pasir Gudang), based in Kuala Lumpur.

The site presents his education, verified skills and experience, and one complete,
runnable featured project:

> **EcoFlow - Industrial Wastewater Treatment Analytics**
> A synthetic-data case study in environmental process monitoring.
> See [`ecoflow/README.md`](ecoflow/README.md) for the full project write-up.

## What is in this repository

| Path | Contents |
|------|----------|
| `index.html`, `css/`, `js/`, `assets/` | The portfolio website (static HTML, CSS and JavaScript) |
| `ecoflow/` | The EcoFlow project: dashboard page, Python data pipeline, tests and documentation |
| `docs/` | Deployment guide, publication checklist, QA/testing report, owner verification list |
| `requirements.txt` | Python dependencies for regenerating the EcoFlow dataset |

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

## Regenerating the EcoFlow dataset

```
pip install -r requirements.txt
python ecoflow/scripts/build_dashboard_data.py
```

The generator is deterministic (seed 42 by default), so the published dataset can be
reproduced exactly. Tests live in `ecoflow/tests/` and run with `python -m pytest ecoflow/tests`.

## Deployment

The site is designed for GitHub Pages (project site, relative asset paths, no build
step and no server-side code). See [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md).

## Licence

MIT - see [`LICENSE`](LICENSE).
