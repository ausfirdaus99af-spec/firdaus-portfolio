"""Synthetic hourly data generator for the EcoFlow portfolio project.

EcoFlow - Industrial Wastewater Treatment Analytics.

This module generates 100 percent SYNTHETIC hourly operating data for an
illustrative industrial wastewater treatment plant (about 200 m3/h average
influent flow). No real plant, client or employer data is used or
represented. The generator is fully deterministic for a given seed.

Two scenarios are produced over the same 120 day window:

- "baseline": conventional operation.
- "optimised": modelled VFD aeration control (about 12 percent lower
  electricity per m3) and improved coagulant dose control (about 15 percent
  lower dose with about 1 percentage point better TSS removal).

Both scenarios share the same influent series, the same upset event times
and the same maintenance windows, so they are directly comparable.

Process events and sensor artefacts are kept separate on purpose:

- treatment_status: "normal", "upset" (degraded removal) or "maintenance"
  (reduced flow). These are process states.
- anomaly_type: "", "sensor_spike", "sensor_stuck", "missing" or
  "out_of_range". These are sensor or data-quality artefacts injected AFTER
  the physical values are computed, so they represent bad readings rather
  than real process changes. They are tagged so that downstream cleaning can
  detect and remove them before any KPI aggregation.

Run from anywhere, for example:

    python scripts/generate_data.py --seed 42
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

START_DATE = "2026-07-04"
N_DAYS = 120  # 2026-07-04 to 2026-10-31 inclusive
HOURS = N_DAYS * 24
SCENARIOS = ("baseline", "optimised")

COLUMNS = [
    "timestamp",
    "scenario",
    "influent_flow_m3h",
    "influent_ph",
    "influent_cod_mgl",
    "influent_bod_mgl",
    "influent_tss_mgl",
    "effluent_ph",
    "effluent_cod_mgl",
    "effluent_bod_mgl",
    "effluent_tss_mgl",
    "electricity_kwh",
    "chemical_dose_kg",
    "treatment_status",
    "anomaly_type",
]

SENSOR_COLUMNS = [
    "influent_flow_m3h",
    "influent_ph",
    "influent_cod_mgl",
    "influent_bod_mgl",
    "influent_tss_mgl",
    "effluent_ph",
    "effluent_cod_mgl",
    "effluent_bod_mgl",
    "effluent_tss_mgl",
]

# Anomaly plan per scenario: (type, number of events). A "sensor_stuck"
# event covers 3 to 6 consecutive rows, so the total anomalous row share
# lands at roughly 0.5 to 0.8 percent of the 2880 rows per scenario.
ANOMALY_PLAN = [
    ("sensor_spike", 4),
    ("sensor_stuck", 2),
    ("missing", 4),
    ("out_of_range", 3),
]


def _upset_windows(rng: np.random.Generator) -> list[tuple[int, int]]:
    """Return 4 to 6 (start_hour, end_hour) upset windows, 4 to 12 h each."""
    n_events = int(rng.integers(4, 7))
    starts = np.sort(rng.choice(np.arange(48, HOURS - 48), size=n_events, replace=False))
    windows = []
    for s in starts:
        duration = int(rng.integers(4, 13))
        windows.append((int(s), min(int(s) + duration, HOURS)))
    return windows


def _maintenance_windows() -> list[tuple[int, int]]:
    """Two planned maintenance windows (day 40 and day 85, 08:00 to 16:00)."""
    return [
        (40 * 24 + 8, 40 * 24 + 16),
        (85 * 24 + 8, 85 * 24 + 16),
    ]


def _build_status(upsets: list[tuple[int, int]]) -> np.ndarray:
    status = np.array(["normal"] * HOURS, dtype=object)
    for s, e in upsets:
        status[s:e] = "upset"
    for s, e in _maintenance_windows():
        status[s:e] = "maintenance"
    return status


def _inject_anomalies(arrays: dict, status: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Mutate sensor arrays in place with tagged artefacts; return tag array.

    Artefacts are only placed on "normal" status rows so that process events
    and sensor artefacts remain cleanly separable for testing and cleaning.
    """
    anomaly = np.array([""] * HOURS, dtype=object)
    used: set[int] = set()
    normal_idx = np.where(status == "normal")[0]

    def pick_free(span: int = 1) -> int | None:
        for _ in range(2000):
            i = int(rng.choice(normal_idx))
            span_ok = i + span <= HOURS and all(
                (j not in used) and status[j] == "normal" for j in range(i - 1, i + span + 1) if 0 <= j < HOURS
            )
            if span_ok:
                return i
        return None

    for kind, count in ANOMALY_PLAN:
        for _ in range(count):
            if kind == "sensor_stuck":
                length = int(rng.integers(3, 7))
                i = pick_free(length)
                if i is None:
                    continue
                col = str(rng.choice(["influent_flow_m3h", "influent_cod_mgl", "effluent_cod_mgl", "influent_tss_mgl"]))
                arrays[col][i : i + length] = arrays[col][i]
                anomaly[i : i + length] = "sensor_stuck"
                used.update(range(i, i + length))
            else:
                i = pick_free()
                if i is None:
                    continue
                if kind == "sensor_spike":
                    col = str(rng.choice(["influent_ph", "influent_cod_mgl", "effluent_ph"]))
                    if col.endswith("_ph"):
                        arrays[col][i] = 14.0
                    else:
                        arrays[col][i] = arrays[col][i] * 5.0
                elif kind == "missing":
                    col = str(rng.choice(SENSOR_COLUMNS))
                    arrays[col][i] = np.nan
                elif kind == "out_of_range":
                    col = str(rng.choice(["influent_flow_m3h", "effluent_tss_mgl", "influent_cod_mgl"]))
                    arrays[col][i] = 0.0 if rng.integers(0, 2) == 0 else -float(rng.uniform(1.0, 20.0))
                anomaly[i] = kind
                used.add(i)
    return anomaly


def generate(seed: int = 42) -> pd.DataFrame:
    """Generate the full two-scenario hourly dataset. Deterministic per seed."""
    master = np.random.default_rng(seed)
    event_rng = np.random.default_rng(int(master.integers(0, 2**31)))
    influent_rng = np.random.default_rng(int(master.integers(0, 2**31)))
    scenario_seeds = {s: int(master.integers(0, 2**31)) for s in SCENARIOS}

    timestamps = pd.date_range(START_DATE, periods=HOURS, freq="h")
    ts_strings = timestamps.strftime("%Y-%m-%dT%H:%M:%S")
    hour = timestamps.hour.to_numpy()
    dow = timestamps.dayofweek.to_numpy()

    # Shared process events (same in both scenarios for comparability).
    upsets = _upset_windows(event_rng)
    status = _build_status(upsets)
    maintenance_mask = status == "maintenance"
    upset_mask = status == "upset"
    n_upset = int(upset_mask.sum())

    # Shared influent series: diurnal pattern (higher daytime), weekly
    # pattern (lower at weekends), gaussian noise, mean about 200 m3/h.
    diurnal = 1.0 + 0.20 * np.sin(2.0 * np.pi * (hour - 9.0) / 24.0)
    weekly = np.where(dow >= 5, 0.88, 1.0)
    flow = 200.0 * diurnal * weekly + influent_rng.normal(0.0, 12.0, HOURS)
    flow = np.clip(flow, 120.0, 300.0)
    # Maintenance reduces throughput by about 40 percent.
    flow = np.where(maintenance_mask, flow * 0.6, flow)

    ph_in = np.clip(influent_rng.normal(7.2, 0.35, HOURS), 6.2, 8.8)
    # COD correlated with flow surges and dips.
    cod_in = np.clip(650.0 + 1.1 * (flow - 200.0) + influent_rng.normal(0.0, 55.0, HOURS), 450.0, 900.0)
    bod_ratio = influent_rng.uniform(0.45, 0.55, HOURS)
    bod_in = cod_in * bod_ratio
    tss_in = np.clip(290.0 + 0.5 * (flow - 200.0) + influent_rng.normal(0.0, 45.0, HOURS), 150.0, 450.0)

    frames = []
    for scenario in SCENARIOS:
        srng = np.random.default_rng(scenario_seeds[scenario])
        optimised = scenario == "optimised"

        # Removal efficiencies under normal operation.
        cod_eff = srng.uniform(0.85, 0.92, HOURS)
        bod_eff = srng.uniform(0.90, 0.96, HOURS)
        tss_eff = srng.uniform(0.90, 0.97, HOURS)
        if optimised:
            # Dose-control improvement: about 1 percentage point better TSS removal.
            tss_eff = np.clip(tss_eff + 0.01, None, 0.975)

        # Upsets degrade removal in both scenarios at the same times.
        cod_eff[upset_mask] = srng.uniform(0.55, 0.70, n_upset)
        bod_eff[upset_mask] = srng.uniform(0.60, 0.75, n_upset)
        tss_eff[upset_mask] = srng.uniform(0.50, 0.70, n_upset)

        cod_out = cod_in * (1.0 - cod_eff) * (1.0 + srng.normal(0.0, 0.04, HOURS))
        bod_out = bod_in * (1.0 - bod_eff) * (1.0 + srng.normal(0.0, 0.04, HOURS))
        # Physical invariant: effluent BOD never exceeds effluent COD.
        bod_out = np.minimum(bod_out, 0.9 * cod_out)
        tss_out = tss_in * (1.0 - tss_eff) * (1.0 + srng.normal(0.0, 0.05, HOURS))
        tss_out = np.maximum(tss_out, 0.5)
        ph_out = np.clip(srng.normal(7.2, 0.15, HOURS), 6.8, 7.6)

        # Electricity roughly proportional to flow, about 0.8 kWh/m3 baseline.
        energy = flow * 0.8 * (1.0 + srng.normal(0.0, 0.05, HOURS))
        if optimised:
            energy = energy * 0.88  # modelled VFD aeration control
        energy = np.maximum(energy, 1.0)

        # Coagulant about 60 g per m3 baseline (0.060 kg/m3).
        chemical = flow * 0.060 * (1.0 + srng.normal(0.0, 0.06, HOURS))
        if optimised:
            chemical = chemical * 0.85  # modelled dose-control improvement
        chemical = np.maximum(chemical, 0.1)

        arrays = {
            "influent_flow_m3h": flow.copy(),
            "influent_ph": ph_in.copy(),
            "influent_cod_mgl": cod_in.copy(),
            "influent_bod_mgl": bod_in.copy(),
            "influent_tss_mgl": tss_in.copy(),
            "effluent_ph": ph_out,
            "effluent_cod_mgl": cod_out,
            "effluent_bod_mgl": bod_out,
            "effluent_tss_mgl": tss_out,
        }

        # Sensor artefacts are injected AFTER the physics, so derived columns
        # (energy, chemical) still reflect the true process. They represent
        # bad readings, not process changes.
        anomaly = _inject_anomalies(arrays, status, srng)

        frame = pd.DataFrame(
            {
                "timestamp": ts_strings,
                "scenario": scenario,
                **arrays,
                "electricity_kwh": energy,
                "chemical_dose_kg": chemical,
                "treatment_status": status.copy(),
                "anomaly_type": anomaly,
            }
        )
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    return df[COLUMNS]


def default_output_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "ecoflow_hourly.csv"


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description="Generate synthetic EcoFlow hourly data.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    parser.add_argument("--out", type=str, default=None, help="Output CSV path.")
    args = parser.parse_args(argv)

    out_path = Path(args.out) if args.out else default_output_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = generate(seed=args.seed)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows ({df['scenario'].nunique()} scenarios) to {out_path}")
    return out_path


if __name__ == "__main__":
    main()
