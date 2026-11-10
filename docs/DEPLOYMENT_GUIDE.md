# Deployment guide - GitHub Pages and LinkedIn

A step-by-step guide for Firdaus. Nothing in this guide has been executed; publishing
is a manual decision. Account: **github.com/ausfirdaus99af-spec**.

## 1. Create the repository

1. Sign in to GitHub and open https://github.com/new
2. Repository name: `firdaus-portfolio` (the site URL becomes
   `https://ausfirdaus99af-spec.github.io/firdaus-portfolio/`)
3. Visibility: **Public** (required for free GitHub Pages)
4. Do not add a README, .gitignore or licence on GitHub (this folder already has them)
5. Click **Create repository**

## 2. Push this folder

From a terminal inside the `Firdaus Portfolio` folder:

```
git init
git add .
git commit -m "Portfolio website and EcoFlow project"
git branch -M main
git remote add origin https://github.com/ausfirdaus99af-spec/firdaus-portfolio.git
git push -u origin main
```

(Requires git and a GitHub sign-in on this machine; GitHub will prompt in the
browser on the first push.)

## 3. Turn on GitHub Pages

1. In the repository, open **Settings → Pages**
2. Under **Build and deployment**, set Source to **Deploy from a branch**
3. Branch: `main`, folder: `/ (root)`, then **Save**
4. Wait a minute or two, then visit
   `https://ausfirdaus99af-spec.github.io/firdaus-portfolio/`
5. Check the EcoFlow dashboard loads at `.../firdaus-portfolio/ecoflow/`

The site uses only relative paths and includes a `.nojekyll` file, so no further
configuration is needed.

## 4. Before announcing the link

Work through `docs/PUBLICATION_CHECKLIST.md`, including the items in
`docs/VERIFICATION_TODO.md`. In particular, Firdaus should read
`ecoflow/docs/ASSUMPTIONS_AND_FORMULAS.md` until he can explain every KPI in an
interview.

## 5. Add the site to LinkedIn

1. LinkedIn → profile → **Contact info → Edit → Add website** → paste the Pages URL,
   type "Portfolio"
2. Also add it to the **Featured** section: profile → Add profile section →
   Recommended → Featured → Add link

## 6. Add EcoFlow as a LinkedIn project

Profile → Add profile section → Recommended → **Add projects**:

- Name: `EcoFlow - Industrial Wastewater Treatment Analytics (synthetic-data case study)`
- Description (suggested, edit to taste): built an interactive analytics dashboard
  for an illustrative wastewater treatment plant using a reproducible synthetic
  dataset; covers COD/BOD/TSS removal efficiency, specific energy (kWh/m³) and
  chemical dosing KPIs, sensor-anomaly handling and a baseline vs optimised scenario
  comparison. Clearly labelled synthetic data; methodology and assumptions documented
  in the repository.
- Project URL: the dashboard URL (`.../firdaus-portfolio/ecoflow/`)

## 7. Updating the site later

- Edit the files locally, then `git add . && git commit -m "..." && git push`
- GitHub Pages redeploys automatically within a few minutes
- To change the dataset: edit the generator, rerun
  `python ecoflow/scripts/build_dashboard_data.py`, run the tests, commit the
  regenerated files in `ecoflow/data/`
