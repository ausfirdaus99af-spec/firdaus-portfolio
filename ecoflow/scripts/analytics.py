"""Pure calculation functions for the EcoFlow portfolio project.

All functions are NaN-safe: invalid inputs (None, NaN, zero or negative
denominators, physically impossible values) return NaN rather than raising,
and no function ever divides by zero. Functions accept scalars or numpy
arrays; scalar inputs return a Python float.

IMPORTANT MODELLING CAVEAT, stated here and in the docs:

Concentration-based removal efficiency is NOT the same as mass-based
removal when inlet and outlet flows differ. This model ASSUMES effluent
flow equals influent flow (no evaporation, sludge wasting or other losses),
which is an explicit simplification. Under that assumption the
concentration-based and mass-based removal figures coincide.

Data cleaning happens BEFORE any KPI aggregation: `clean_hourly` (built on
`anomaly_mask`) removes tagged sensor artefacts and any reading that fails a
plausibility range check, and `daily_aggregate` applies that cleaning
internally before computing daily KPIs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Plausibility ranges used for cleaning, in the column's own units.
# Values outside these ranges, or NaN, are treated as anomalous readings.
# The ranges are deliberately wide so that genuine process upsets are kept
# while sensor artefacts (pH 14 spikes, COD x5 spikes, zero or negative
# readings) are caught even if the anomaly_type tag were lost.
PLAUSIBLE_RANGES = {
    "influent_flow_m3h": (1.0, 600.0),
    "influent_ph": (3.0, 12.0),
    "effluent_ph": (3.0, 12.0),
    "influent_cod_mgl": (1.0, 2000.0),
    "influent_bod_mgl": (1.0, 1500.0),
    "influent_tss_mgl": (1.0, 1500.0),
    "effluent_cod_mgl": (0.1, 1500.0),
    "effluent_bod_mgl": (0.1, 1200.0),
    "effluent_tss_mgl": (0.1, 1000.0),
    "electricity_kwh": (0.1, 2000.0),
    "chemical_dose_kg": (0.01, 100.0),
}

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


def _is_scalar(*values) -> bool:
    return all(np.ndim(v) == 0 for v in values)


def _as_float(value):
    """Coerce to float array; None becomes NaN."""
    return np.asarray(value, dtype=float)


def removal_efficiency(influent, effluent):
    """Concentration-based removal efficiency in percent.

    removal (%) = (influent - effluent) / influent x 100

    Returns NaN if influent <= 0 or either input is NaN or None. The result
    is NOT clipped: a negative value is possible when effluent exceeds
    influent (for example during a severe upset or a sensor fault) and is
    deliberately preserved so such cases remain visible.

    Note: this is a concentration ratio. It equals mass-based removal only
    under the model's assumption that effluent flow equals influent flow.
    """
    scalar = _is_scalar(influent, effluent)
    inf = _as_float(influent)
    eff = _as_float(effluent)
    safe_inf = np.where(inf > 0, inf, 1.0)  # placeholder, masked below
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(
            np.isnan(inf) | np.isnan(eff) | ~(inf > 0),
            np.nan,
            (inf - eff) / safe_inf * 100.0,
        )
    return float(result) if scalar else result


def pollutant_load_kg_per_h(flow_m3h, conc_mgl):
    """Pollutant mass load in kg/h.

    load (kg/h) = flow (m3/h) x concentration (mg/L) / 1000

    (1 mg/L = 1 g/m3, so flow x conc gives g/h; dividing by 1000 gives kg/h.)
    Returns NaN if either input is NaN, None or negative (negative flow or
    concentration is physically impossible).
    """
    scalar = _is_scalar(flow_m3h, conc_mgl)
    flow = _as_float(flow_m3h)
    conc = _as_float(conc_mgl)
    with np.errstate(invalid="ignore"):
        result = np.where(
            np.isnan(flow) | np.isnan(conc) | (flow < 0) | (conc < 0),
            np.nan,
            flow * conc / 1000.0,
        )
    return float(result) if scalar else result


def specific_energy_kwh_m3(energy_kwh, volume_m3):
    """Specific energy consumption in kWh per m3 treated.

    specific energy = energy (kWh) / volume (m3)

    Returns NaN if volume <= 0, energy < 0, or either input is NaN or None.
    """
    scalar = _is_scalar(energy_kwh, volume_m3)
    energy = _as_float(energy_kwh)
    volume = _as_float(volume_m3)
    safe_vol = np.where(volume > 0, volume, 1.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(
            np.isnan(energy) | np.isnan(volume) | ~(volume > 0) | (energy < 0),
            np.nan,
            energy / safe_vol,
        )
    return float(result) if scalar else result


def chemical_g_per_m3(chemical_kg, volume_m3):
    """Specific chemical dose in grams per m3 treated.

    dose (g/m3) = chemical (kg) x 1000 / volume (m3)

    Returns NaN if volume <= 0, chemical < 0, or either input is NaN or None.
    """
    scalar = _is_scalar(chemical_kg, volume_m3)
    chem = _as_float(chemical_kg)
    volume = _as_float(volume_m3)
    safe_vol = np.where(volume > 0, volume, 1.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(
            np.isnan(chem) | np.isnan(volume) | ~(volume > 0) | (chem < 0),
            np.nan,
            chem * 1000.0 / safe_vol,
        )
    return float(result) if scalar else result


def anomaly_mask(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of anomalous rows (True = anomalous).

    A row is anomalous when it is tagged (anomaly_type not empty) OR any
    monitored column is NaN or outside its plausibility range. Range checks
    run in addition to the tags, so untagged bad readings are still caught.
    """
    mask = pd.Series(False, index=df.index)
    if "anomaly_type" in df.columns:
        mask |= df["anomaly_type"].fillna("").astype(str).str.len() > 0
    for col, (lo, hi) in PLAUSIBLE_RANGES.items():
        if col in df.columns:
            values = pd.to_numeric(df[col], errors="coerce")
            mask |= values.isna() | (values < lo) | (values > hi)
    return mask


def clean_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with anomalous rows removed.

    Cleaning happens BEFORE KPI aggregation: every aggregate in this project
    is computed on the output of this function (daily_aggregate applies it
    internally), so sensor artefacts never contaminate the KPIs.
    """
    return df.loc[~anomaly_mask(df)].copy()


def anomaly_records(df: pd.DataFrame) -> list[dict]:
    """List tagged anomalies as dicts: timestamp, parameter, type, note.

    The affected parameter is inferred from the data itself (NaN column,
    out-of-range column, or the repeated value for stuck sensors), which
    doubles as a demonstration of anomaly detection logic.
    """
    records: list[dict] = []
    for _, group in df.groupby("scenario", sort=False) if "scenario" in df.columns else [(None, df)]:
        group = group.reset_index(drop=True)
        tagged = group.index[group["anomaly_type"].fillna("").astype(str).str.len() > 0]
        for i in tagged:
            row = group.loc[i]
            kind = str(row["anomaly_type"])
            parameter = "unknown"
            note = "anomalous reading"
            if kind == "missing":
                for col in SENSOR_COLUMNS:
                    if pd.isna(row[col]):
                        parameter = col
                        break
                note = "reading missing (empty value from sensor)"
            elif kind == "out_of_range":
                for col in SENSOR_COLUMNS:
                    if not pd.isna(row[col]) and float(row[col]) <= 0:
                        parameter = col
                        note = f"impossible value ({float(row[col]):.2f})"
                        break
            elif kind == "sensor_spike":
                for col, (lo, hi) in PLAUSIBLE_RANGES.items():
                    if col in row.index and not pd.isna(row[col]) and (float(row[col]) < lo or float(row[col]) > hi):
                        parameter = col
                        note = f"single absurd reading ({float(row[col]):.2f})"
                        break
            elif kind == "sensor_stuck":
                for col in SENSOR_COLUMNS:
                    prev_same = (
                        i - 1 in group.index
                        and str(group.loc[i - 1, "anomaly_type"]) == "sensor_stuck"
                        and group.loc[i - 1, col] == row[col]
                    )
                    next_same = (
                        i + 1 in group.index
                        and str(group.loc[i + 1, "anomaly_type"]) == "sensor_stuck"
                        and group.loc[i + 1, col] == row[col]
                    )
                    if prev_same or next_same:
                        parameter = col
                        note = "repeated identical reading (stuck sensor)"
                        break
            records.append(
                {
                    "timestamp": str(row["timestamp"]),
                    "parameter": parameter,
                    "type": kind,
                    "note": note,
                }
            )
    return records


def _flow_weighted_mean(conc: pd.Series, flow: pd.Series) -> float:
    """Flow-weighted mean concentration; NaN if no valid pairs."""
    valid = conc.notna() & flow.notna() & (flow > 0)
    if not bool(valid.any()):
        return float("nan")
    total_flow = float(flow[valid].sum())
    if total_flow <= 0:
        return float("nan")
    return float((conc[valid] * flow[valid]).sum() / total_flow)


def daily_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one scenario's hourly data to daily KPIs.

    Cleaning happens FIRST: anomalous rows (tagged plus range-check
    failures) are removed before every KPI below. Only anomaly_count,
    upset_hours and maintenance_hours are counted on the full raw data,
    because they describe the raw record itself.

    Daily removal efficiencies are computed from flow-weighted mean
    concentrations. Each hourly row represents one hour, so total volume is
    the sum of influent_flow_m3h x 1 h, and daily loads (kg/day) are sums of
    hourly loads over the clean hours available that day.
    """
    raw = df.copy()
    raw["_ts"] = pd.to_datetime(raw["timestamp"])
    raw["_date"] = raw["_ts"].dt.date
    raw["_anomalous"] = anomaly_mask(raw).to_numpy()

    rows = []
    for date, day_all in raw.groupby("_date", sort=True):
        day = day_all.loc[~day_all["_anomalous"]]
        flow = day["influent_flow_m3h"]
        volume = float(flow.sum()) if len(day) else float("nan")

        cod_in = _flow_weighted_mean(day["influent_cod_mgl"], flow)
        cod_out = _flow_weighted_mean(day["effluent_cod_mgl"], flow)
        bod_in = _flow_weighted_mean(day["influent_bod_mgl"], flow)
        bod_out = _flow_weighted_mean(day["effluent_bod_mgl"], flow)
        tss_in = _flow_weighted_mean(day["influent_tss_mgl"], flow)
        tss_out = _flow_weighted_mean(day["effluent_tss_mgl"], flow)

        energy = float(day["electricity_kwh"].sum()) if len(day) else float("nan")
        chemical = float(day["chemical_dose_kg"].sum()) if len(day) else float("nan")

        load_in = pollutant_load_kg_per_h(flow.to_numpy(), day["influent_cod_mgl"].to_numpy())
        load_out = pollutant_load_kg_per_h(flow.to_numpy(), day["effluent_cod_mgl"].to_numpy())

        rows.append(
            {
                "date": str(date),
                "volume_m3": volume,
                "flow_avg_m3h": float(flow.mean()) if len(day) else float("nan"),
                "cod_in_mgl": cod_in,
                "cod_out_mgl": cod_out,
                "bod_in_mgl": bod_in,
                "bod_out_mgl": bod_out,
                "tss_in_mgl": tss_in,
                "tss_out_mgl": tss_out,
                "ph_in_avg": float(day["influent_ph"].mean()) if len(day) else float("nan"),
                "ph_out_avg": float(day["effluent_ph"].mean()) if len(day) else float("nan"),
                "ph_out_min": float(day["effluent_ph"].min()) if len(day) else float("nan"),
                "ph_out_max": float(day["effluent_ph"].max()) if len(day) else float("nan"),
                "removal_cod_pct": removal_efficiency(cod_in, cod_out),
                "removal_bod_pct": removal_efficiency(bod_in, bod_out),
                "removal_tss_pct": removal_efficiency(tss_in, tss_out),
                "energy_kwh": energy,
                "specific_energy_kwh_m3": specific_energy_kwh_m3(energy, volume),
                "chemical_kg": chemical,
                "chemical_g_m3": chemical_g_per_m3(chemical, volume),
                "cod_load_in_kgd": float(np.nansum(load_in)) if len(day) else float("nan"),
                "cod_load_out_kgd": float(np.nansum(load_out)) if len(day) else float("nan"),
                "anomaly_count": int(day_all["_anomalous"].sum()),
                "upset_hours": int((day_all["treatment_status"] == "upset").sum()),
                "maintenance_hours": int((day_all["treatment_status"] == "maintenance").sum()),
            }
        )
    return pd.DataFrame(rows)
