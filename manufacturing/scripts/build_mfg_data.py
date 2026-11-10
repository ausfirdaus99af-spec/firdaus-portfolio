"""Build pipeline for Project 03 - Manufacturing Performance Analytics.

Synthetic data only. The pipeline:
1. generates the dataset (seed 42, deterministic),
2. creates data/manufacturing.db from sql/schema.sql and loads the data,
3. executes every query in sql/queries.sql and checks the results
   (analytical queries must return rows, qc_ checks must return none),
4. writes data/mfg_data.json, the fixed contract consumed by the public
   dashboard. The dashboard runs on this precomputed JSON alone, with no
   database server.

Run from anywhere:
    python scripts/build_mfg_data.py
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import kpis  # noqa: E402
from generate_data import (  # noqa: E402
    COMMISSIONED_YEAR,
    END_DATE,
    IDEAL_RATES_UPH,
    LINES,
    PLANNED_TIME_H,
    SEED,
    SHIFTS,
    START_DATE,
    generate,
)

BASE_DIR = SCRIPTS_DIR.parent
SQL_DIR = BASE_DIR / "sql"
DATA_DIR = BASE_DIR / "data"

CATEGORIES = ["Standard", "Premium"]

COST_ASSUMPTIONS = {
    "energy_rm_per_kwh": 0.08,
    "material_rm_per_kg": 1.2,
    "value_rm_per_good_unit": 2.5,
    "note": "illustrative only",
}

KPI_DEFINITIONS = {
    "production_achievement_pct": "actual_units / planned_units x 100",
    "capacity_utilisation_pct":
        "actual_units / (ideal_rate_uph x planned_time_h) x 100",
    "yield_pct": "good_units / actual_units x 100",
    "rejection_rate_pct": "rejected_units / actual_units x 100",
    "availability_pct":
        "run_time_h / planned_time_h x 100; planned time is 7.5 h per shift "
        "and excludes the 0.5 h planned break",
    "performance_pct":
        "(actual_units / run_time_h) / ideal_rate_uph x 100; not capped, "
        "values above 100 can occur when a line beats its nameplate rate",
    "quality_pct": "good_units / actual_units x 100",
    "oee_pct": "availability_pct x performance_pct x quality_pct / 10000",
    "energy_intensity_kwh_per_good_unit": "energy_kwh / good_units",
    "downtime_by_cause":
        "downtime hours grouped by reason with share of total and cumulative "
        "share for Pareto analysis; reason None (stops under 0.1 h) excluded",
}

ASSUMPTIONS = [
    "All data is synthetic and generated from a fixed random seed. No real "
    "plant, company or measurement is represented.",
    "Each shift is 8 hours with a 0.5 hour planned break. Planned production "
    "time is 7.5 hours and the planned break is excluded from every OEE "
    "denominator.",
    "Each line runs one product category per shift. Lines A and B mostly "
    "run Standard, Line C mostly runs Premium.",
    "Line B is the oldest line and carries roughly 1.5 times the breakdown "
    "downtime of the other lines.",
    "A major Line B breakdown occurs in the week of 9 to 15 March 2026.",
    "A plant maintenance programme starts on 1 July 2026 and cuts breakdown "
    "downtime by about 35 percent on all lines.",
    "The last three days of each month show a mild planning push with "
    "higher planned units.",
    "Cost assumptions are in Malaysian Ringgit (RM), are illustrative only "
    "and are never used to claim savings.",
    "Aggregated KPIs use time weighted sums. Row level percentages are "
    "never averaged.",
]

SCENARIO_NAME = "Changeover reduction programme (what-if)"
SCENARIO_DESCRIPTION = (
    "Models the effect of cutting changeover downtime by 40 percent and "
    "quality stop downtime by 20 percent, with the regained run time "
    "converted into units at each row's own production rate. The result is "
    "a modelled what-if, not a measured outcome."
)
SCENARIO_ASSUMPTIONS = [
    "Changeover downtime reduced 40% via SMED-style standardisation",
    "Quality stops reduced 20% via first-pass checks",
    "modelled, not measured",
]


# ---------------------------------------------------------------------------
# Database build
# ---------------------------------------------------------------------------

def create_database(df: pd.DataFrame, db_path: Path) -> None:
    """Create the SQLite database from schema.sql and load the dataset."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))

        line_ids = {name: i + 1 for i, name in enumerate(LINES)}
        product_ids = {cat: i + 1 for i, cat in enumerate(CATEGORIES)}

        con.executemany(
            "INSERT INTO lines (line_id, name, commissioned_year) VALUES (?, ?, ?)",
            [(line_ids[n], n, COMMISSIONED_YEAR[n]) for n in LINES],
        )
        con.executemany(
            "INSERT INTO products (product_id, category) VALUES (?, ?)",
            [(product_ids[c], c) for c in CATEGORIES],
        )
        con.executemany(
            "INSERT INTO line_products (line_id, product_id, ideal_rate_uph) "
            "VALUES (?, ?, ?)",
            [
                (line_ids[line], product_ids[cat], rate)
                for line, rates in IDEAL_RATES_UPH.items()
                for cat, rate in rates.items()
            ],
        )

        run_rows = []
        event_rows = []
        for idx, row in enumerate(df.itertuples(index=False), start=1):
            run_rows.append((
                idx, row.date, line_ids[row.line], product_ids[row.category],
                row.shift, int(row.planned_units), int(row.actual_units),
                int(row.good_units), int(row.rejected_units),
                float(row.planned_time_h), float(row.run_time_h),
                float(row.energy_kwh), float(row.material_kg),
                row.equipment_status,
            ))
            if row.downtime_h > 1e-9:
                event_rows.append((idx, row.downtime_reason, float(row.downtime_h)))

        con.executemany(
            "INSERT INTO production_runs (run_id, date, line_id, product_id, "
            "shift, planned_units, actual_units, good_units, rejected_units, "
            "planned_time_h, run_time_h, energy_kwh, material_kg, "
            "equipment_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            run_rows,
        )
        con.executemany(
            "INSERT INTO downtime_events (run_id, reason, hours) VALUES (?, ?, ?)",
            event_rows,
        )
        con.commit()
    finally:
        con.close()


def load_queries():
    """Parse queries.sql into (name, sql) pairs using the -- name: markers."""
    text = (SQL_DIR / "queries.sql").read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^-- name: ", text)
    queries = []
    for block in blocks[1:]:
        lines = block.splitlines()
        name = lines[0].strip()
        sql = "\n".join(lines[1:])
        queries.append((name, sql))
    return queries


def run_queries(db_path: Path) -> dict:
    """Execute every query. Analytical queries must return rows, quality
    checks (qc_ prefix) must return zero rows."""
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        results = {}
        for name, sql in load_queries():
            rows = con.execute(sql).fetchall()
            if name.startswith("qc_"):
                if rows:
                    raise AssertionError(
                        f"Quality check {name} returned {len(rows)} offending "
                        f"rows, expected zero"
                    )
            else:
                if not rows:
                    raise AssertionError(
                        f"Analytical query {name} returned no rows"
                    )
            results[name] = rows
        return results
    finally:
        con.close()


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_rows(df: pd.DataFrame) -> list:
    """Build the JSON row list with the fixed short keys.

    Floats are rounded to 1 decimal place and unit counts stay integers.
    run_time is derived from the rounded downtime so that pt = rt + dt holds
    exactly in the exported data.
    """
    rows = []
    for row in df.itertuples(index=False):
        dt = round(float(row.downtime_h), 1)
        rt = round(PLANNED_TIME_H - dt, 1)
        rows.append({
            "d": row.date,
            "line": row.line,
            "shift": row.shift,
            "cat": row.category,
            "plan": int(row.planned_units),
            "act": int(row.actual_units),
            "good": int(row.good_units),
            "rej": int(row.rejected_units),
            "pt": PLANNED_TIME_H,
            "rt": rt,
            "dt": dt,
            "reason": row.downtime_reason,
            "status": row.equipment_status,
            "kwh": round(float(row.energy_kwh), 1),
            "mat": round(float(row.material_kg), 1),
        })
    return rows


def rows_to_df(rows: list) -> pd.DataFrame:
    """Rebuild a KPI ready DataFrame from exported JSON rows.

    This mirrors what the dashboard does in JS, so KPI values computed here
    match a recomputation from the published rows.
    """
    frame = pd.DataFrame([
        {
            "date": r["d"],
            "line": r["line"],
            "shift": r["shift"],
            "category": r["cat"],
            "planned_units": r["plan"],
            "actual_units": r["act"],
            "good_units": r["good"],
            "rejected_units": r["rej"],
            "planned_time_h": r["pt"],
            "run_time_h": r["rt"],
            "downtime_h": r["dt"],
            "downtime_reason": r["reason"],
            "equipment_status": r["status"],
            "energy_kwh": r["kwh"],
            "material_kg": r["mat"],
            "ideal_rate": IDEAL_RATES_UPH[r["line"]][r["cat"]],
        }
        for r in rows
    ])
    return frame


def round_kpis(kpi_dict: dict, ndigits: int = 2) -> dict:
    return {k: round(float(v), ndigits) for k, v in kpi_dict.items()}


def apply_scenario(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the changeover reduction what-if to a KPI ready DataFrame.

    Changeover downtime drops 40 percent and quality stop downtime drops
    20 percent. The regained run time is converted into units at each row's
    own production rate (actual / run_time), and into good units at the
    row's own quality ratio. Energy rises by the per unit energy of the
    extra units.
    """
    out = df.copy()
    factor = pd.Series(1.0, index=out.index)
    factor[out["downtime_reason"] == "Changeover"] = 0.6
    factor[out["downtime_reason"] == "Quality stop"] = 0.8

    new_dt = out["downtime_h"] * factor
    regained = out["downtime_h"] - new_dt
    rate = out["actual_units"] / out["run_time_h"]
    extra_act = regained * rate
    good_ratio = out["good_units"] / out["actual_units"]
    extra_good = extra_act * good_ratio

    out["downtime_h"] = new_dt
    out["run_time_h"] = out["run_time_h"] + regained
    out["actual_units"] = out["actual_units"] + extra_act
    out["good_units"] = out["good_units"] + extra_good
    out["rejected_units"] = out["actual_units"] - out["good_units"]
    out["energy_kwh"] = out["energy_kwh"] + 0.35 * extra_act
    return out


def build_payload(df: pd.DataFrame) -> dict:
    """Assemble the full JSON contract from the generated dataset."""
    rows = export_rows(df)

    # KPIs are computed from the ROUNDED exported rows, because the public
    # dashboard recomputes them in JS from those same rows and the two sets
    # of numbers must match.
    export_df = rows_to_df(rows)
    kpis_overall = round_kpis(kpis.aggregate_kpis(export_df))

    pareto = [
        {
            "reason": p["reason"],
            "hours": round(p["hours"], 1),
            "pct": round(p["pct"], 2),
            "cum_pct": round(p["cum_pct"], 2),
        }
        for p in kpis.downtime_pareto(export_df)
    ]

    improved_df = apply_scenario(export_df)
    kpis_improved = round_kpis(kpis.aggregate_kpis(improved_df))

    return {
        "meta": {
            "project": "Manufacturing Performance Analytics",
            "synthetic": True,
            "seed": SEED,
            "date_range": {
                "start": START_DATE.isoformat(),
                "end": END_DATE.isoformat(),
            },
            "lines": list(LINES),
            "shifts": list(SHIFTS),
            "categories": list(CATEGORIES),
            "ideal_rates_uph": IDEAL_RATES_UPH,
            "planned_time_h_per_shift": PLANNED_TIME_H,
            "cost_assumptions": COST_ASSUMPTIONS,
            "definitions": KPI_DEFINITIONS,
            "assumptions": ASSUMPTIONS,
        },
        "rows": rows,
        "kpis_overall": kpis_overall,
        "downtime_pareto": pareto,
        "scenario": {
            "name": SCENARIO_NAME,
            "description": SCENARIO_DESCRIPTION,
            "assumptions": SCENARIO_ASSUMPTIONS,
            "kpis_baseline": kpis_overall,
            "kpis_improved": kpis_improved,
        },
    }


def build(db_path: Path, json_path: Path) -> dict:
    """Full pipeline: generate, load SQLite, run queries, export JSON.

    Returns a small summary dict for reporting and tests.
    """
    db_path = Path(db_path)
    json_path = Path(json_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    df = generate()
    create_database(df, db_path)
    query_results = run_queries(db_path)
    payload = build_payload(df)

    text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    json_path.write_text(text, encoding="utf-8")

    return {
        "rows": len(payload["rows"]),
        "queries": {name: len(r) for name, r in query_results.items()},
        "kpis_overall": payload["kpis_overall"],
        "downtime_pareto": payload["downtime_pareto"],
        "db_bytes": db_path.stat().st_size,
        "json_bytes": json_path.stat().st_size,
    }


def main():
    summary = build(DATA_DIR / "manufacturing.db", DATA_DIR / "mfg_data.json")
    print(f"Rows exported: {summary['rows']}")
    print("Query result counts:")
    for name, count in summary["queries"].items():
        print(f"  {name}: {count}")
    print("Overall KPIs (from exported rows):")
    for key, value in summary["kpis_overall"].items():
        print(f"  {key}: {value}")
    print("Top downtime causes:")
    for entry in summary["downtime_pareto"]:
        print(f"  {entry['reason']}: {entry['hours']} h "
              f"({entry['pct']}%, cumulative {entry['cum_pct']}%)")
    print(f"Database size: {summary['db_bytes']} bytes")
    print(f"JSON size: {summary['json_bytes']} bytes")


if __name__ == "__main__":
    main()
