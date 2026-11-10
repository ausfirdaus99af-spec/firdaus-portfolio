# SQL Workflow

Project 03 - Manufacturing Performance Analytics. Synthetic data only.

This document explains how the SQLite database is built, what each query
does, how the data quality checks work, and how the public JSON file is
produced.

## Pipeline overview

```
scripts/generate_data.py      seeded synthetic dataset (2,190 rows)
        |
        v
scripts/build_mfg_data.py     creates data/manufacturing.db from
        |                     sql/schema.sql, loads the data, runs every
        |                     query in sql/queries.sql and checks the
        |                     results
        v
data/mfg_data.json            fixed contract consumed by the dashboard
```

Run it with:

```
python scripts/build_mfg_data.py
```

## Schema (text diagram)

```
lines                      products
-----                      --------
line_id (PK)               product_id (PK)
name (UNIQUE)              category (UNIQUE)
commissioned_year
     |                          |
     +----------+---------------+
                |
         line_products
         -------------
         line_id  (FK -> lines)
         product_id (FK -> products)
         ideal_rate_uph            one nameplate rate per line and
         PK (line_id, product_id)  product pair

production_runs
---------------
run_id (PK)
date, shift
line_id    (FK -> lines)
product_id (FK -> products)
planned_units, actual_units, good_units, rejected_units
planned_time_h, run_time_h
energy_kwh, material_kg
equipment_status
UNIQUE (date, line_id, shift)      exactly one run per date x line x shift
     |
     v
downtime_events
---------------
event_id (PK)
run_id (FK -> production_runs)
reason, hours
```

Foreign keys are switched on for every connection. The ideal rate lives in
`line_products` because it belongs to the line and product pair: Line A
packs Standard at 1,200 units per hour but Premium at 1,000.

## Analytical queries (sql/queries.sql)

Each query carries a `-- name:` marker so the build script can run and
check it individually.

- **monthly_oee_by_line.** A CTE joins each run to its ideal rate, then a
  second CTE sums the components per month and line. Availability,
  performance, quality and OEE are computed from those sums using the
  weighted convention, never by averaging row percentages. 36 rows (12
  months x 3 lines).
- **downtime_pareto.** Sums downtime hours by cause, then uses window
  functions (`SUM(...) OVER ()` and a running `SUM ... ROWS BETWEEN
  UNBOUNDED PRECEDING AND CURRENT ROW`) for each cause's share and the
  cumulative Pareto share. Reason None (micro stops under 0.1 h) is
  excluded.
- **shift_comparison.** The same weighted aggregation grouped by shift. It
  surfaces the planted pattern that Night shifts run about two performance
  points below Day shifts.
- **top10_worst_oee_days.** Plant level OEE per date, sorted ascending,
  limit 10. The Line B crash week of March 2026 dominates this list.
- **energy_intensity_by_line_month.** Total energy divided by total good
  units per line and month. Again a ratio of sums, not an average of
  ratios.

## Data quality checks

Queries whose name starts with `qc_` are quality gates. Each one selects
the offending rows, so a healthy database returns zero rows for every
check. The build script fails if any check returns anything.

- **qc_good_exceeds_actual**: good units can never exceed actual units.
- **qc_negative_values**: no unit count, time, energy or material value
  may be negative.
- **qc_runtime_exceeds_planned**: run time can never exceed planned
  production time (tiny tolerance for floating point storage).
- **qc_orphan_downtime_events**: every downtime event must point at a real
  run.
- **qc_orphan_run_references**: every run must reference a known line and
  a known line and product rate pair.
- **qc_duplicate_date_line_shift**: exactly one run per date x line x
  shift.

## JSON export

After the queries pass, `build_mfg_data.py` writes `data/mfg_data.json`:

- `meta`: project facts, seed, date range, ideal rates, cost assumptions
  (RM, illustrative only), KPI definitions and modelling assumptions.
- `rows`: all 2,190 rows with short keys, floats rounded to 1 decimal
  place and unit counts as integers.
- `kpis_overall`: the ten overall KPIs, computed from the rounded exported
  rows with the weighted aggregation and rounded to 2 decimal places. The
  dashboard recomputes the same numbers in JS from `rows`, and because
  both sides start from the same rounded data they match exactly.
- `downtime_pareto`: cause, hours, share and cumulative share.
- `scenario`: a what-if that cuts changeover downtime 40 percent and
  quality stop downtime 20 percent, converting the regained run time into
  units at each row's own rate. Clearly labelled modelled, not measured.

The file is strict JSON with no NaN or Infinity values.

## Why the dashboard needs no database server

The public dashboard is a static page. It loads the precomputed
`mfg_data.json` once and does every filter and recalculation in the
browser. SQLite is used at build time only, as the analytical and quality
gate layer; nothing at serving time connects to a database. This keeps the
published project free of credentials, servers and real infrastructure,
which suits a portfolio project built entirely on synthetic data.
