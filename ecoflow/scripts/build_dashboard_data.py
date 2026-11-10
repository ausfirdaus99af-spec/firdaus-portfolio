"""Build pipeline for the EcoFlow portfolio project.

Runs the synthetic generator, applies cleaning and analytics, and writes:

1. data/ecoflow_hourly.csv - the full hourly dataset (both scenarios).
2. data/dashboard_data.json - a fixed-contract JSON file consumed by the
   JavaScript dashboard. The key names and structure are a contract and must
   not be renamed.

The JSON is strict: missing numbers are written as null, never NaN or
Infinity. Floats are rounded to 2 decimal places (percentages to 1).
All KPI aggregates are computed on CLEANED data (sensor artefacts removed
before aggregation) and are volume-weighted where appropriate.

Run from anywhere:

    python scripts/build_dashboard_data.py --seed 42
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

# Standard layout, no reliance on the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analytics  # noqa: E402
import generate_data  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

UNITS = {
    "influent_flow_m3h": "m3/h",
    "flow_avg_m3h": "m3/h",
    "volume_m3": "m3",
    "cod_in_mgl": "mg/L",
    "cod_out_mgl": "mg/L",
    "bod_in_mgl": "mg/L",
    "bod_out_mgl": "mg/L",
    "tss_in_mgl": "mg/L",
    "tss_out_mgl": "mg/L",
    "ph_in_avg": "pH units",
    "ph_out_avg": "pH units",
    "ph_out_min": "pH units",
    "ph_out_max": "pH units",
    "removal_cod_pct": "%",
    "removal_bod_pct": "%",
    "removal_tss_pct": "%",
    "energy_kwh": "kWh",
    "specific_energy_kwh_m3": "kWh/m3",
    "chemical_kg": "kg",
    "chemical_g_m3": "g/m3",
    "cod_load_in_kgd": "kg/day",
    "cod_load_out_kgd": "kg/day",
    "upset_hours": "h",
    "maintenance_hours": "h",
}

ASSUMPTIONS = [
    "All data is 100 percent synthetic; no real plant, client or employer data is used or represented.",
    "Effluent flow is assumed equal to influent flow (no evaporation, sludge wasting or other losses), so concentration-based removal equals mass-based removal only under this simplification.",
    "Influent BOD is modelled as 0.45 to 0.55 times influent COD, so BOD never exceeds COD.",
    "Baseline specific energy is about 0.8 kWh per m3 treated; the optimised scenario models VFD aeration control at about 12 percent lower energy.",
    "Baseline coagulant dose is about 60 g per m3; the optimised scenario models dose control at about 15 percent lower dose with about 1 percentage point better TSS removal.",
    "Upset events and maintenance windows occur at identical times in both scenarios so they are directly comparable.",
    "Sensor anomalies are injected after the physical values are computed; they represent bad readings, not process changes, and are removed before any KPI aggregation.",
    "Each hourly record represents a one hour average; sub-hourly dynamics are not modelled.",
]


def _round(value, ndigits: int):
    """Round to ndigits; NaN, None and infinities become None (JSON null)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, ndigits)


def _daily_entry(row: dict) -> dict:
    pct = {"removal_cod_pct", "removal_bod_pct", "removal_tss_pct"}
    ints = {"anomaly_count", "upset_hours", "maintenance_hours"}
    entry = {"date": row["date"]}
    for key, value in row.items():
        if key == "date":
            continue
        if key in ints:
            entry[key] = int(value)
        elif key in pct:
            entry[key] = _round(value, 1)
        else:
            entry[key] = _round(value, 2)
    return entry


def _scenario_payload(df_scenario) -> dict:
    daily_df = analytics.daily_aggregate(df_scenario)
    daily = [_daily_entry(row) for row in daily_df.to_dict(orient="records")]

    # KPI aggregates on CLEANED data, volume-weighted where appropriate.
    clean = analytics.clean_hourly(df_scenario)
    flow = clean["influent_flow_m3h"]
    total_volume = float(flow.sum())
    total_energy = float(clean["electricity_kwh"].sum())
    total_chemical = float(clean["chemical_dose_kg"].sum())

    fw = analytics._flow_weighted_mean
    kpis = {
        "total_volume_m3": _round(total_volume, 2),
        "avg_removal_cod_pct": _round(
            analytics.removal_efficiency(fw(clean["influent_cod_mgl"], flow), fw(clean["effluent_cod_mgl"], flow)), 1
        ),
        "avg_removal_bod_pct": _round(
            analytics.removal_efficiency(fw(clean["influent_bod_mgl"], flow), fw(clean["effluent_bod_mgl"], flow)), 1
        ),
        "avg_removal_tss_pct": _round(
            analytics.removal_efficiency(fw(clean["influent_tss_mgl"], flow), fw(clean["effluent_tss_mgl"], flow)), 1
        ),
        "avg_specific_energy_kwh_m3": _round(analytics.specific_energy_kwh_m3(total_energy, total_volume), 2),
        "avg_chemical_g_m3": _round(analytics.chemical_g_per_m3(total_chemical, total_volume), 2),
        "total_energy_kwh": _round(total_energy, 2),
        "total_chemical_kg": _round(total_chemical, 2),
        "anomaly_count": int(analytics.anomaly_mask(df_scenario).sum()),
        "upset_days": int(sum(1 for d in daily if d["upset_hours"] > 0)),
    }

    anomalies = analytics.anomaly_records(df_scenario)
    return {"daily": daily, "kpis": kpis, "anomalies": anomalies}


def build(seed: int = 42, out_dir: Path | str | None = None) -> Path:
    """Run the full pipeline; return the path of the dashboard JSON."""
    out = Path(out_dir) if out_dir else PROJECT_ROOT / "data"
    out.mkdir(parents=True, exist_ok=True)

    df = generate_data.generate(seed=seed)
    csv_path = out / "ecoflow_hourly.csv"
    df.to_csv(csv_path, index=False)

    dates = sorted(df["timestamp"].str[:10].unique())
    payload = {
        "meta": {
            "project": "EcoFlow",
            "synthetic": True,
            "seed": seed,
            "generated_at": date.today().isoformat(),
            "date_range": {"start": dates[0], "end": dates[-1]},
            "units": UNITS,
            "assumptions": ASSUMPTIONS,
        },
        "scenarios": {
            scenario: _scenario_payload(df[df["scenario"] == scenario])
            for scenario in ("baseline", "optimised")
        },
    }

    json_path = out / "dashboard_data.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
    return json_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build EcoFlow dashboard data.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    parser.add_argument("--out", type=str, default=None, help="Output directory (default data/).")
    args = parser.parse_args(argv)
    json_path = build(seed=args.seed, out_dir=args.out)
    print(f"Pipeline complete. Wrote {json_path.parent / 'ecoflow_hourly.csv'} and {json_path}")


if __name__ == "__main__":
    main()
