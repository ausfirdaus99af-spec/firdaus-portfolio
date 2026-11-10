# EcoFlow - Industrial Wastewater Treatment Analytics

*A demo monitoring dashboard for an imaginary wastewater treatment plant. All the
data is made up (synthetic).*

I am a chemical engineering graduate, and this project is my way of showing how I
think about a treatment process and its data. A computer model makes up 120 days of
realistic plant data; the dashboard then shows how well the plant cleans the water
and what that costs in electricity and chemicals.

**Nothing here is real.** The dataset comes from a seeded random model. No real
plant, company, client or employer data is used, and no real-world savings or
compliance is claimed.

Every formula and assumption is written down in [`docs/`](docs/) in plain
language, so I can explain and defend each number on the dashboard.

## What the project shows

- **Engineering thinking** - how much COD, BOD and suspended solids the plant
  removes, how much electricity and coagulant one m³ of treated water costs, and
  what those numbers do and do not tell you.
- **Data sense** - the model deliberately plants bad sensor readings (spikes, stuck
  sensors, missing values); a documented cleaning step removes them before any
  figure is calculated, because one stuck sensor can drag a whole day's average.
- **What-if thinking** - normal running is compared with an improved-settings
  scenario (speed-controlled blowers, more careful dosing) built on clearly stated
  assumptions.
- **Reproducibility** - the whole dataset regenerates exactly from a fixed seed,
  and the calculations are covered by automated tests (28 passing).

## How it is put together

```
scripts/generate_data.py        makes the synthetic data (hourly, 120 days,
                                two scenarios, process upsets, bad sensor readings)
scripts/analytics.py            the calculations, written to handle zero, missing
                                and invalid values safely
scripts/build_dashboard_data.py runs everything and writes:
                                  data/ecoflow_hourly.csv
                                  data/dashboard_data.json
tests/                          automated checks on every formula and on the data
docs/METHODOLOGY.md             how and why the data is made up
docs/ASSUMPTIONS_AND_FORMULAS.md  every formula, assumption and limitation
index.html + js/dashboard.js    the dashboard itself (plain JavaScript + Chart.js),
                                which reads the precomputed JSON - no server needed
```

The published site never runs Python: everything is precomputed into a static JSON
file, so the dashboard works on GitHub Pages.

## Running it

From the repository root:

```
pip install -r requirements.txt
python ecoflow/scripts/build_dashboard_data.py
python -m pytest ecoflow/tests
python -m http.server 8000
```

Then open http://localhost:8000/ecoflow/.

## Honest limitations

- The removal figures compare concentrations in and out, and the model assumes the
  same amount of water leaves as enters. A real plant loses water along the way,
  which changes the sums; the docs explain this.
- The improved-settings scenario is a what-if model of two stated changes, not a
  measurement.
- Values are realistic for a demonstration but not calibrated to any real plant,
  and nothing here is operational or dosing guidance.
