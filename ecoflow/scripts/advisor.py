"""Deterministic rule-based Engineering Improvement Advisor for EcoFlow.

This module turns the cleaned baseline hourly record into six findings,
each produced by an explicit rule with documented thresholds. The rules,
formulas, assumptions and limitations are written up in
docs/ADVISOR_METHODOLOGY.md; the thresholds live in THRESHOLDS below and
are copied into the output JSON so every number can be traced.

Integrity rules this module is built around:

1. Nothing is hardcoded as a discovery. Every finding is computed from the
   dataframe passed in. When the data does not justify a recommendation the
   rule returns a cleared check (status "no_action_justified"), and cleared
   checks are kept in the output on purpose: with different data the same
   rules produce different findings.
2. Impact figures are computed from fitted or measured values with stated
   assumptions and a sensitivity range (low, base, high), never a fixed
   saving claim.
3. Every recommendation that would reduce electricity or chemical use
   carries a quality gate: an explicit statement of the treatment
   performance check it depends on. If that check cannot be completed from
   the data available, the gate stays "conditional" and says so.
4. Observed evidence (computed from this dataset) is kept separate from
   hypotheses that need further measurement; every possible cause is tagged
   with its basis.

All public functions are pure: they take dataframes and return dicts, with
no file or network access, so the engine is easy to test and reuse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Standard layout, no reliance on the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analytics  # noqa: E402

ANNUAL_DAYS = 365.0
ANNUAL_HOURS = 8760.0

# Every numeric decision point in the rules, in one place. These are
# engineering review thresholds, not discoveries: changing them changes
# which findings fire, and they are published in the output JSON.
THRESHOLDS = {
    "R1": {
        "removal_pct_floor": 75.0,
        "min_episode_hours": 3,
        "high_severity_excess_cod_kg": 500.0,
        "influent_strength_band_pct": 10.0,
    },
    "R2": {
        "per_column_rate_pct": 0.3,
        "high_severity_rate_pct": 1.0,
        "stuck_min_run_hours": 3,
    },
    "R3": {
        "baseload_share_pct": 15.0,
        "reduction_pct_low": 20.0,
        "reduction_pct_base": 35.0,
        "reduction_pct_high": 50.0,
    },
    "R4": {
        "quartile_removal_diff_pp": 1.0,
        "trim_percentiles": [40, 50, 60],
    },
    "R5": {
        "ph_low": 6.5,
        "ph_high": 7.8,
        "cleared_below_hours": 20,
        "high_severity_hours": 100,
        "high_severity_depth_ph": 1.0,
    },
    "R6": {},
}

_FINDING_KEYS = (
    "id",
    "title",
    "status",
    "severity",
    "problem",
    "evidence",
    "possible_causes",
    "recommendation",
    "expected_impact",
    "tradeoffs",
    "quality_gate",
    "validation_required",
)


def _finding(**kwargs) -> dict:
    """Build a finding dict with the contract's exact key order."""
    unknown = set(kwargs) - set(_FINDING_KEYS)
    if unknown:
        raise ValueError(f"unknown finding keys: {sorted(unknown)}")
    out = {key: kwargs.get(key) for key in _FINDING_KEYS}
    if out["possible_causes"] is None:
        out["possible_causes"] = []
    if out["validation_required"] is None:
        out["validation_required"] = []
    return out


def _r(value, ndigits: int = 2):
    """Round to ndigits; NaN, None and infinities become None (JSON null)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(v) or np.isinf(v):
        return None
    return round(v, ndigits)


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Return the baseline scenario, time-sorted, with a parsed _ts column."""
    out = df.copy()
    if "scenario" in out.columns:
        out = out[out["scenario"] == "baseline"]
    if len(out) == 0:
        raise ValueError("no baseline rows to analyse")
    if "anomaly_type" in out.columns:
        out["anomaly_type"] = out["anomaly_type"].fillna("")
    else:
        out["anomaly_type"] = ""
    out["_ts"] = pd.to_datetime(out["timestamp"])
    return out.sort_values("_ts").reset_index(drop=True)


def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Cleaned copy of a prepared frame (sensor artefacts removed)."""
    return analytics.clean_hourly(raw).reset_index(drop=True)


def _period_days(raw: pd.DataFrame) -> int:
    first = raw["_ts"].iloc[0].normalize()
    last = raw["_ts"].iloc[-1].normalize()
    return int((last - first).days) + 1


# --------------------------------------------------------------------- R1


def _low_removal_episodes(clean: pd.DataFrame):
    """Find contiguous low COD removal episodes on cleaned data.

    Returns (episodes, removal, reference) where episodes is a list of
    (start_index, end_index) into `clean`, removal is the hourly COD removal
    array in percent, and reference is the episode-free median removal.
    Contiguity means consecutive clock hours; a cleaned-out (anomalous) hour
    breaks contiguity, which is conservative and documented.
    """
    t = THRESHOLDS["R1"]
    removal = analytics.removal_efficiency(
        clean["influent_cod_mgl"].to_numpy(), clean["effluent_cod_mgl"].to_numpy()
    )
    removal = np.asarray(removal, dtype=float)
    with np.errstate(invalid="ignore"):
        below = removal < t["removal_pct_floor"]
    below = np.where(np.isnan(removal), False, below)

    ts = clean["_ts"]
    episodes: list[tuple[int, int]] = []
    i, n = 0, len(clean)
    while i < n:
        if not below[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and below[j + 1] and (ts.iloc[j + 1] - ts.iloc[j]) == pd.Timedelta(hours=1):
            j += 1
        if j - i + 1 >= t["min_episode_hours"]:
            episodes.append((i, j))
        i = j + 1

    in_episode = np.zeros(n, dtype=bool)
    for s, e in episodes:
        in_episode[s : e + 1] = True
    free = removal[~in_episode]
    free = free[~np.isnan(free)]
    reference = float(np.median(free)) if len(free) else float(t["removal_pct_floor"])
    return episodes, removal, reference


def rule_r1_process_upsets(df: pd.DataFrame) -> dict:
    """R1: contiguous episodes (3 h or more) of hourly COD removal below 75 percent."""
    t = THRESHOLDS["R1"]
    raw = _prepare(df)
    clean = _clean(raw)
    episodes, removal, reference = _low_removal_episodes(clean)
    n = len(clean)

    problem = (
        "Checks the cleaned baseline record for contiguous episodes of "
        f"{t['min_episode_hours']} or more hours in which hourly COD removal "
        f"falls below {t['removal_pct_floor']:.0f} percent."
    )

    if not episodes:
        finite = removal[~np.isnan(removal)]
        return _finding(
            id="R1",
            title="Process upsets: episodes of low COD removal",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"No episode of {t['min_episode_hours']} or more consecutive hours below "
                    f"{t['removal_pct_floor']:.0f} percent COD removal was found in {n} cleaned hours."
                ),
                "details": [
                    f"Median hourly COD removal over the period: {_r(reference, 1)} percent.",
                    f"Lowest single-hour COD removal: {_r(float(np.min(finite)), 1) if len(finite) else None} percent.",
                ],
            },
            possible_causes=[],
            recommendation=(
                "No action justified by this check. Keep the hourly removal check in place so "
                "future episodes are caught early."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    in_episode = np.zeros(n, dtype=bool)
    details = []
    episode_rows = []
    total_excess = 0.0
    for s, e in episodes:
        in_episode[s : e + 1] = True
        seg = clean.iloc[s : e + 1]
        seg_removal = removal[s : e + 1]
        expected_out = seg["influent_cod_mgl"].to_numpy() * (1.0 - reference / 100.0)
        excess = float(
            ((seg["effluent_cod_mgl"].to_numpy() - expected_out) * seg["influent_flow_m3h"].to_numpy() / 1000.0).sum()
        )
        total_excess += excess
        episode_rows.append(excess)
        details.append(
            f"{seg['timestamp'].iloc[0]} to {seg['timestamp'].iloc[-1]}: {e - s + 1} h, "
            f"minimum COD removal {_r(float(np.nanmin(seg_removal)), 1)} percent, "
            f"excess COD discharged {_r(excess, 1)} kg against the episode-free median removal "
            f"of {_r(reference, 1)} percent applied to the same influent."
        )

    # Observed test: was the influent unusually strong during the episodes?
    ep_cod = clean.loc[in_episode, "influent_cod_mgl"]
    free_cod = clean.loc[~in_episode, "influent_cod_mgl"]
    ep_med = float(ep_cod.median())
    free_med = float(free_cod.median())
    strength_pct = (ep_med / free_med - 1.0) * 100.0 if free_med > 0 else float("nan")
    unusually_strong = strength_pct > t["influent_strength_band_pct"]
    details.append(
        f"Influent strength comparison: median influent COD {_r(ep_med, 0)} mg/L during episodes "
        f"against {_r(free_med, 0)} mg/L outside them ({_r(strength_pct, 1):+} percent difference, "
        f"band for 'unusually strong' is +{t['influent_strength_band_pct']:.0f} percent)."
    )

    severity = "high" if total_excess > t["high_severity_excess_cod_kg"] else "medium"

    if unusually_strong:
        strength_cause = {
            "cause": (
                f"Influent was unusually strong during the episodes (median COD "
                f"{_r(strength_pct, 1):+} percent against normal), so load shocks are a "
                "plausible contributor."
            ),
            "basis": "observed",
        }
    else:
        strength_cause = {
            "cause": (
                f"Influent strength does not explain the episodes: median influent COD during "
                f"episodes was within {t['influent_strength_band_pct']:.0f} percent of normal "
                f"({_r(ep_med, 0)} against {_r(free_med, 0)} mg/L)."
            ),
            "basis": "observed",
        }

    return _finding(
        id="R1",
        title="Process upsets: episodes of low COD removal",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{len(episodes)} episode(s) totalling {int(in_episode.sum())} hours below "
                f"{t['removal_pct_floor']:.0f} percent COD removal; about {_r(total_excess, 0)} kg of "
                f"excess COD discharged compared with the episode-free median removal of "
                f"{_r(reference, 1)} percent (severity threshold "
                f"{t['high_severity_excess_cod_kg']:.0f} kg)."
            ),
            "details": details,
        },
        possible_causes=[
            strength_cause,
            {"cause": "Biological stress or toxic shock to the treatment biomass.", "basis": "hypothesis"},
            {"cause": "Aeration or mechanical equipment failure during the episode hours.", "basis": "hypothesis"},
            {"cause": "Short-lived inhibitory compounds in the influent that COD alone cannot identify.", "basis": "hypothesis"},
        ],
        recommendation=(
            "Adopt a written upset response procedure triggered when hourly COD removal stays below "
            f"{t['removal_pct_floor']:.0f} percent for {t['min_episode_hours']} hours: verify the readings "
            "against a grab sample, inspect aeration and dosing equipment, and log the influent source at "
            "the time. Carry out the validation measurements below before spending on equipment changes, "
            "because this dataset cannot separate the candidate causes."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Dissolved oxygen profiling in the biological stage (not in the current dataset).",
            "Microscopy of the biomass during and after an episode (not in the current dataset).",
            "Influent screening for inhibitory or toxic compounds (not in the current dataset).",
        ],
    )


# --------------------------------------------------------------------- R2

_R2_RECOMMENDATIONS = {
    "stuck": "put the instrument on a preventive maintenance and cleaning schedule and alarm on repeated identical readings",
    "spike_above_range": "apply signal filtering (for example a rolling median) and book a calibration check",
    "missing": "investigate data logger and connectivity faults on the channel",
    "impossible_low": "book a zero-drift and calibration check",
}


def rule_r2_sensor_reliability(df: pd.DataFrame) -> dict:
    """R2: per-sensor anomaly rate from tags plus independent plausibility checks."""
    t = THRESHOLDS["R2"]
    raw = _prepare(df)
    n = len(raw)
    month = raw["_ts"].dt.strftime("%Y-%m")
    tag_counts = {
        str(k): int(v)
        for k, v in raw.loc[raw["anomaly_type"] != "", "anomaly_type"].value_counts().sort_index().items()
    }

    columns = []
    for col in analytics.SENSOR_COLUMNS:
        if col not in raw.columns:
            continue
        vals = pd.to_numeric(raw[col], errors="coerce")
        lo, hi = analytics.PLAUSIBLE_RANGES[col]
        missing = vals.isna()
        spike = vals.notna() & (vals > hi)
        low = vals.notna() & (vals < lo)
        # Stuck detection: runs of identical consecutive readings of at
        # least stuck_min_run_hours. Real sensor noise makes exact repeats
        # of that length implausible on these continuous signals.
        change = vals.ne(vals.shift()) | vals.isna() | vals.shift().isna()
        grp = change.cumsum()
        sizes = grp.map(grp.value_counts())
        stuck = vals.notna() & (sizes >= t["stuck_min_run_hours"]) & ~spike & ~low
        flagged = missing | spike | low | stuck
        count = int(flagged.sum())
        by_type = {
            "missing": int(missing.sum()),
            "spike_above_range": int(spike.sum()),
            "impossible_low": int(low.sum()),
            "stuck": int(stuck.sum()),
        }
        dominant = max(by_type, key=lambda k: (by_type[k], k)) if count else None
        flagged_months = month[flagged]
        worst_month = None
        if count:
            counts_by_month = flagged_months.value_counts().sort_index()
            worst_month = str(counts_by_month.idxmax())
        columns.append(
            {
                "column": col,
                "count": count,
                "rate_pct": count / n * 100.0,
                "by_type": by_type,
                "dominant": dominant,
                "examples": [str(x) for x in raw.loc[flagged, "timestamp"].head(3)],
                "worst_month": worst_month,
            }
        )

    offending = [c for c in columns if c["rate_pct"] > t["per_column_rate_pct"]]
    total_flagged = sum(c["count"] for c in columns)

    details = []
    for c in columns:
        if c["count"] == 0:
            continue
        parts = ", ".join(f"{k} {v}" for k, v in c["by_type"].items() if v)
        details.append(
            f"{c['column']}: {c['count']} flagged of {n} readings ({_r(c['rate_pct'], 3)} percent; "
            f"threshold {t['per_column_rate_pct']} percent), by check: {parts}; worst month "
            f"{c['worst_month']}; example timestamps: {', '.join(c['examples'])}."
        )
    zero_cols = [c["column"] for c in columns if c["count"] == 0]
    if zero_cols:
        details.append(f"No flagged readings in: {', '.join(zero_cols)}.")
    details.append(
        f"Cross-check against the record's own anomaly tags: {tag_counts if tag_counts else 'no tagged rows'} "
        f"(tags and independent plausibility checks are counted separately; a reading can trip more than one check)."
    )

    problem = (
        "Checks each sensor column for unreliable readings using the record's anomaly tags plus "
        "independent plausibility checks (missing values, readings outside the plausible range, "
        f"and runs of {t['stuck_min_run_hours']} or more identical consecutive readings). A column "
        f"fails when more than {t['per_column_rate_pct']} percent of its readings are flagged."
    )

    if not offending:
        return _finding(
            id="R2",
            title="Sensor reliability per instrument",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"All {len(columns)} monitored sensor columns are below the "
                    f"{t['per_column_rate_pct']} percent flagged-reading threshold "
                    f"({total_flagged} flagged readings in total across {n} hours)."
                ),
                "details": details,
            },
            possible_causes=[],
            recommendation=(
                "No instrument-specific action justified. Keep the plausibility checks running and "
                "keep routine calibration in place; flagged readings are already removed before any KPI."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    worst_rate = max(c["rate_pct"] for c in offending)
    severity = "high" if worst_rate > t["high_severity_rate_pct"] else "medium"
    actions = []
    for c in offending:
        actions.append(f"{c['column']} (dominant fault: {c['dominant']}): {_R2_RECOMMENDATIONS[c['dominant']]}")

    return _finding(
        id="R2",
        title="Sensor reliability per instrument",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{len(offending)} of {len(columns)} sensor columns exceed the "
                f"{t['per_column_rate_pct']} percent flagged-reading threshold: "
                + ", ".join(f"{c['column']} ({_r(c['rate_pct'], 3)} percent)" for c in offending)
                + "."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": "Fault patterns computed per column above; the dominant check type points at the failure mode.",
                "basis": "observed",
            },
            {"cause": "Probe fouling, cabling or logger faults; which one needs a field inspection.", "basis": "hypothesis"},
        ],
        recommendation="Per instrument: " + "; ".join(actions) + ".",
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Field inspection and calibration records for each offending instrument.",
        ],
    )


# --------------------------------------------------------------------- R3


def rule_r3_energy_baseload(df: pd.DataFrame) -> dict:
    """R3: fit kWh = a + b x flow on cleaned normal hours; test the base-load share."""
    t = THRESHOLDS["R3"]
    raw = _prepare(df)
    clean = _clean(raw)
    normal = clean[clean["treatment_status"] == "normal"]
    x = normal["influent_flow_m3h"].to_numpy(dtype=float)
    y = normal["electricity_kwh"].to_numpy(dtype=float)
    b, a = np.polyfit(x, y, 1)
    pred = a + b * x
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    mean_kwh = float(y.mean())
    share_pct = a / mean_kwh * 100.0 if mean_kwh > 0 else float("nan")

    problem = (
        "Fits hourly electricity against influent flow (kWh = a + b x flow) on cleaned normal-status "
        "hours. The intercept a is consumption that does not scale with flow (base load). The check "
        f"fires when the base-load share a / mean(kWh) exceeds {t['baseload_share_pct']:.0f} percent."
    )
    fit_details = [
        f"Fitted on {len(normal)} cleaned normal-status hours.",
        f"Intercept a = {_r(a, 2)} kWh per hour; slope b = {_r(b, 4)} kWh per m3; R2 = {_r(r2, 3)}.",
        f"Mean hourly consumption {_r(mean_kwh, 1)} kWh; base-load share {_r(share_pct, 1)} percent "
        f"(threshold {t['baseload_share_pct']:.0f} percent).",
    ]

    if not (share_pct > t["baseload_share_pct"]):
        return _finding(
            id="R3",
            title="Energy base load (flow-independent consumption)",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"Base-load share is {_r(share_pct, 1)} percent of mean hourly consumption, at or below "
                    f"the {t['baseload_share_pct']:.0f} percent threshold; consumption tracks flow "
                    f"(R2 = {_r(r2, 3)})."
                ),
                "details": fit_details
                + [
                    "An intercept near or below zero is statistically indistinct from no base load on this data."
                ],
            },
            possible_causes=[],
            recommendation=(
                "No base-load investigation justified by this fit. Re-run the check when new data arrives, "
                "and submeter major drives if a finer breakdown is ever needed."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    annual_total_kwh = mean_kwh * ANNUAL_HOURS

    def saved(reduction_pct: float) -> float:
        return a * reduction_pct / 100.0 * ANNUAL_HOURS

    base_saving = saved(t["reduction_pct_base"])
    severity = "high" if share_pct > 2 * t["baseload_share_pct"] else "medium"

    return _finding(
        id="R3",
        title="Energy base load (flow-independent consumption)",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"Base-load share is {_r(share_pct, 1)} percent of mean hourly consumption, above the "
                f"{t['baseload_share_pct']:.0f} percent threshold: about {_r(a, 1)} kWh every hour is "
                "consumed regardless of flow."
            ),
            "details": fit_details,
        },
        possible_causes=[
            {
                "cause": "A flow-independent component of consumption exists; the fit quantifies it but cannot name the equipment.",
                "basis": "observed",
            },
            {"cause": "Aeration running at a fixed minimum regardless of load.", "basis": "hypothesis"},
            {"cause": "Lighting, HVAC, pumps or other auxiliaries left running continuously.", "basis": "hypothesis"},
        ],
        recommendation=(
            "Survey constant consumers (idle aeration, lighting, auxiliaries) and submeter the largest "
            "drives to attribute the fitted base load before changing any setpoint."
        ),
        expected_impact={
            "summary": (
                f"Reducing the fitted base load of {_r(a, 1)} kWh/h by "
                f"{t['reduction_pct_low']:.0f} to {t['reduction_pct_high']:.0f} percent would save roughly "
                f"{_r(saved(t['reduction_pct_low']), 0)} to {_r(saved(t['reduction_pct_high']), 0)} kWh per year."
            ),
            "calculations": [
                {"label": "fitted base load a", "value": _r(a, 2), "unit": "kWh/h"},
                {"label": "fitted slope b", "value": _r(b, 4), "unit": "kWh/m3"},
                {"label": "fit quality R2", "value": _r(r2, 3), "unit": "dimensionless"},
                {"label": "base-load share of mean consumption", "value": _r(share_pct, 1), "unit": "%"},
                {"label": "annual saving at base assumption", "value": _r(base_saving, 0), "unit": "kWh/yr"},
                {
                    "label": "annual saving as share of total consumption",
                    "value": _r(base_saving / annual_total_kwh * 100.0, 1),
                    "unit": "%",
                },
            ],
            "assumptions": [
                f"An assumed {t['reduction_pct_low']:.0f} to {t['reduction_pct_high']:.0f} percent of the fitted "
                "intercept can be removed; the achievable share is unknown until the base load is attributed.",
                "The fitted intercept represents real equipment, not a fitting artefact; submetering must confirm this.",
                "Period behaviour scales to 8760 hours per year.",
            ],
            "sensitivity": {
                "low": _r(saved(t["reduction_pct_low"]), 0),
                "base": _r(base_saving, 0),
                "high": _r(saved(t["reduction_pct_high"]), 0),
                "unit": "kWh/yr",
                "description": (
                    f"Intercept reduction of {t['reduction_pct_low']:.0f} percent (low), "
                    f"{t['reduction_pct_base']:.0f} percent (base) and {t['reduction_pct_high']:.0f} percent (high)."
                ),
            },
        },
        tradeoffs=(
            "Base-load cuts must not touch loads that protect the process, such as minimum aeration, "
            "mixing or instrumentation supplies."
        ),
        quality_gate={
            "check": "Treatment performance is assumed unaffected because only flow-independent consumers would be cut.",
            "outcome": "conditional",
            "note": (
                "This is an assumption, not a verified result: before any cut, confirm the targeted "
                "consumers play no treatment role and watch removal KPIs during a trial switch-off."
            ),
        },
        validation_required=[
            "Submetering of blowers and major drives to attribute the fitted base load (not in the current dataset).",
            "A supervised trial switch-off with removal KPIs monitored.",
        ],
    )


# --------------------------------------------------------------------- R4


def rule_r4_dose_response(df: pd.DataFrame) -> dict:
    """R4: does TSS removal respond to coagulant dose across the observed range?"""
    t = THRESHOLDS["R4"]
    raw = _prepare(df)
    clean = _clean(raw)
    normal = clean[clean["treatment_status"] == "normal"]
    dose = np.asarray(
        analytics.chemical_g_per_m3(normal["chemical_dose_kg"].to_numpy(), normal["influent_flow_m3h"].to_numpy()),
        dtype=float,
    )
    rem = np.asarray(
        analytics.removal_efficiency(normal["influent_tss_mgl"].to_numpy(), normal["effluent_tss_mgl"].to_numpy()),
        dtype=float,
    )
    flow = normal["influent_flow_m3h"].to_numpy(dtype=float)
    ok = np.isfinite(dose) & np.isfinite(rem) & np.isfinite(flow)
    dose, rem, flow = dose[ok], rem[ok], flow[ok]

    corr = float(np.corrcoef(dose, rem)[0, 1]) if len(dose) > 2 else float("nan")
    q25, q50, q75 = (float(q) for q in np.quantile(dose, [0.25, 0.50, 0.75]))
    bottom = float(rem[dose <= q25].mean())
    top = float(rem[dose >= q75].mean())
    diff_pp = top - bottom
    period_days = _period_days(raw)

    problem = (
        "Tests, on cleaned normal-status hours, whether TSS removal responds to coagulant dose (g/m3): "
        "correlation plus a binned comparison of removal in the top against the bottom dose quartile. "
        f"A quartile difference below {t['quartile_removal_diff_pp']} percentage point counts as "
        "insensitive across the observed range."
    )
    base_details = [
        f"Computed on {len(dose)} cleaned normal-status hours over {period_days} days.",
        f"Dose distribution: P25 {_r(q25, 1)}, median {_r(q50, 1)}, P75 {_r(q75, 1)} g/m3.",
        f"Correlation between dose and TSS removal: {_r(corr, 3)}.",
        f"Mean TSS removal in top dose quartile {_r(top, 2)} percent against {_r(bottom, 2)} percent in the "
        f"bottom quartile: difference {_r(diff_pp, 2)} percentage points "
        f"(insensitivity threshold {t['quartile_removal_diff_pp']} percentage point).",
    ]

    if diff_pp >= t["quartile_removal_diff_pp"]:
        return _finding(
            id="R4",
            title="Chemical dose response (coagulant against TSS removal)",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"TSS removal responds positively to dose across the observed range "
                    f"(top-minus-bottom quartile difference {_r(diff_pp, 2)} percentage points, "
                    f"correlation {_r(corr, 3)}), so cutting dose would be expected to cost removal."
                ),
                "details": base_details,
            },
            possible_causes=[
                {
                    "cause": "Higher doses are associated with measurably better TSS removal in this record.",
                    "basis": "observed",
                }
            ],
            recommendation=(
                "No dose reduction justified: the data shows removal still gains from dose across the "
                "observed range. Revisit only if the dose range or coagulant changes."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    def annual_saved_kg(target: float) -> float:
        period_kg = float((np.clip(dose - target, 0.0, None) * flow / 1000.0).sum())
        return period_kg * ANNUAL_DAYS / period_days

    p_low, p_base, p_high = t["trim_percentiles"]
    target_low = float(np.quantile(dose, p_high / 100.0))  # trim to P60: least saving
    target_base = float(np.quantile(dose, p_base / 100.0))
    target_high = float(np.quantile(dose, p_low / 100.0))  # trim to P40: most saving
    base_saving = annual_saved_kg(target_base)

    negative_note = []
    if diff_pp <= -t["quartile_removal_diff_pp"]:
        negative_note.append(
            "The apparent negative association between dose and removal is more plausibly confounding "
            "(for example both tracking flow) than a causal effect; the trial below resolves it."
        )

    return _finding(
        id="R4",
        title="Chemical dose response (coagulant against TSS removal)",
        status="conditional",
        severity="medium",
        problem=problem,
        evidence={
            "summary": (
                f"TSS removal is insensitive to dose across the observed range "
                f"({_r(q25, 1)} to {_r(q75, 1)} g/m3 interquartile): quartile difference "
                f"{_r(diff_pp, 2)} percentage points, correlation {_r(corr, 3)}. The data cannot say why."
            ),
            "details": base_details + negative_note,
        },
        possible_causes=[
            {
                "cause": "Removal does not vary with dose across the doses actually used in this record.",
                "basis": "observed",
            },
            {
                "cause": "Dosing already sits above the saturation plateau, so the top of the range is wasted.",
                "basis": "hypothesis",
            },
            {
                "cause": "A real dose response exists but is hidden by noise and the narrow operating range.",
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Run a controlled stepped-dose trial FIRST (deliberate dose steps with jar tests and effluent "
            "TSS sampling) to distinguish a plateau from noise. No dose reduction is justified today; the "
            "impact below applies only if the trial confirms the plateau."
        ),
        expected_impact={
            "summary": (
                f"IF the trial confirms a plateau, trimming doses above the median to the median would save "
                f"about {_r(base_saving, 0)} kg of coagulant per year, computed from the actual dose "
                "distribution in this record."
            ),
            "calculations": [
                {"label": "median dose (trim target, base case)", "value": _r(target_base, 1), "unit": "g/m3"},
                {"label": "annual coagulant saving at base case", "value": _r(base_saving, 0), "unit": "kg/yr"},
            ],
            "assumptions": [
                "The stepped-dose trial confirms no TSS removal loss at the trimmed doses; without that, no saving exists.",
                "Savings are computed on cleaned normal-status hours and scaled to a year by calendar days "
                f"(x {ANNUAL_DAYS:.0f}/{period_days}).",
                "The influent and dose distribution of this period are representative of a full year.",
            ],
            "sensitivity": {
                "low": _r(annual_saved_kg(target_low), 0),
                "base": _r(base_saving, 0),
                "high": _r(annual_saved_kg(target_high), 0),
                "unit": "kg/yr",
                "description": (
                    f"Trim target at the P{p_high} (low), P{p_base} (base) and P{p_low} (high) dose percentile; "
                    "a lower trim target removes more of the dose distribution and saves more."
                ),
            },
        },
        tradeoffs=(
            "Cutting coagulant without trial evidence risks losing TSS removal; the whole saving is "
            "conditional on the trial outcome."
        ),
        quality_gate={
            "check": "TSS removal must be shown unaffected at the trimmed doses in a controlled stepped-dose trial.",
            "outcome": "conditional",
            "note": "This gate cannot pass on the current data; no reduction is justified today.",
        },
        validation_required=[
            "Controlled stepped-dose trial with jar tests and effluent TSS sampling (not in the current dataset).",
            "Coagulant batch quality records for the trial period.",
        ],
    )


# --------------------------------------------------------------------- R5


def rule_r5_ph_control(df: pd.DataFrame, upset_timestamps: set | None = None) -> dict:
    """R5: hours with effluent pH outside the control band on cleaned data."""
    t = THRESHOLDS["R5"]
    raw = _prepare(df)
    clean = _clean(raw)
    ph = clean["effluent_ph"].to_numpy(dtype=float)
    low_mask = ph < t["ph_low"]
    high_mask = ph > t["ph_high"]
    out_mask = low_mask | high_mask
    hours = int(out_mask.sum())
    depth = 0.0
    if hours:
        depths = np.where(low_mask, t["ph_low"] - ph, 0.0) + np.where(high_mask, ph - t["ph_high"], 0.0)
        depth = float(depths.max())
    period_days = _period_days(raw)

    problem = (
        f"Counts cleaned hours with effluent pH outside {t['ph_low']} to {t['ph_high']}. Below "
        f"{t['cleared_below_hours']} such hours over the {period_days} day period the check is cleared."
    )

    if hours < t["cleared_below_hours"]:
        return _finding(
            id="R5",
            title="Effluent pH control",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"{hours} cleaned hour(s) outside pH {t['ph_low']} to {t['ph_high']} in {len(clean)} hours, "
                    f"below the {t['cleared_below_hours']} hour threshold."
                ),
                "details": [
                    f"Observed effluent pH range on cleaned data: {_r(float(np.min(ph)), 2)} to "
                    f"{_r(float(np.max(ph)), 2)}."
                ],
            },
            possible_causes=[],
            recommendation="No action justified: effluent pH is well controlled over the period.",
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    overlap = 0
    if upset_timestamps:
        ts_strings = clean["timestamp"].astype(str).to_numpy()
        overlap = int(sum(1 for i in np.where(out_mask)[0] if ts_strings[i] in upset_timestamps))
    severity = "high" if hours > t["high_severity_hours"] or depth > t["high_severity_depth_ph"] else "medium"
    excursion_idx = np.where(out_mask)[0]
    examples = [str(clean["timestamp"].iloc[i]) for i in excursion_idx[:3]]

    return _finding(
        id="R5",
        title="Effluent pH control",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{hours} cleaned hours outside pH {t['ph_low']} to {t['ph_high']} over {period_days} days, "
                f"maximum excursion depth {_r(depth, 2)} pH units; {overlap} of those hours fall inside the "
                "low COD removal episodes found by R1."
            ),
            "details": [
                f"Excursion hours: {hours} ({_r(hours / max(len(clean), 1) * 100.0, 2)} percent of cleaned hours).",
                f"Example timestamps: {', '.join(examples)}.",
                f"Overlap with R1 upset episodes: {overlap} hour(s) (observed from the two checks' timestamps).",
            ],
        },
        possible_causes=[
            {
                "cause": (
                    f"{overlap} of {hours} excursion hours coincide with low removal episodes, "
                    "measured directly from this record."
                ),
                "basis": "observed",
            },
            {"cause": "Neutralisation dosing control loop drifting or saturating.", "basis": "hypothesis"},
            {"cause": "pH probe drift (a measurement fault rather than a process fault).", "basis": "hypothesis"},
        ],
        recommendation=(
            "Review the neutralisation control loop tuning and alarm on sustained excursions; verify the "
            "probe against a calibrated handheld meter before changing dosing."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "pH probe calibration verification against a reference instrument.",
            "Neutralisation reagent dosing records for the excursion hours (not in the current dataset).",
        ],
    )


# --------------------------------------------------------------------- R6


def rule_r6_data_gaps(df: pd.DataFrame) -> dict:
    """R6: measurements the dataset lacks; always informational, never fabricated."""
    raw = _prepare(df)
    cols = [c.lower() for c in raw.columns]

    def absent(*needles: str) -> bool:
        return not any(any(n in c for n in needles) for c in cols)

    gaps = [
        (
            "Dissolved oxygen in the biological stage",
            absent("dissolved", "oxygen", "do_"),
            "Without it, low removal episodes (R1) cannot be attributed to aeration shortfall, overload or toxicity.",
            "Log DO in the aeration basin at 15 minute resolution alongside the hourly record.",
        ),
        (
            "Blower and aeration power submetering",
            absent("blower", "aeration"),
            "The energy model (R3) sees one total meter, so the largest single consumer cannot be separated or verified.",
            "Submeter the blowers and other major drives and log them hourly.",
        ),
        (
            "Controlled dose-response trial data",
            absent("trial", "jar_test"),
            "R4 cannot distinguish a dosing plateau from noise without deliberately varied doses.",
            "Run a stepped-dose trial with jar tests and effluent TSS sampling across a wider dose range.",
        ),
        (
            "Design capacity and equipment ratings",
            absent("design", "capacity", "rating"),
            "Observed loads and flows cannot be judged against design limits, so headroom and overload risk are unknown.",
            "Record nameplate capacities and design flows next to the operating data.",
        ),
        (
            "Laboratory-verified samples",
            absent("lab_", "laboratory"),
            "Online COD, TSS and pH readings are not cross-checked against laboratory reference values in this record.",
            "Schedule periodic lab samples paired to timestamps so online instruments can be audited.",
        ),
    ]

    details = [f"{name}: why it matters: {why} What to measure: {what}" for name, is_absent, why, what in gaps if is_absent]
    present = [name for name, is_absent, _, _ in gaps if not is_absent]
    if present:
        details.append(f"Already present in the dataset: {', '.join(present)}.")

    return _finding(
        id="R6",
        title="Data gaps limiting the analysis",
        status="informational",
        severity=None,
        problem=(
            "Lists measurements absent from the dataset that limit how far the other rules can go. "
            "Nothing is fabricated to fill these gaps and the simulation is not extended."
        ),
        evidence={
            "summary": (
                f"{len(details) - (1 if present else 0)} measurement gaps identified by checking the dataset's "
                "columns; several hypotheses in R1 to R4 stay hypotheses until these are measured."
            ),
            "details": details,
        },
        possible_causes=[],
        recommendation=(
            "Add the listed measurements before committing to equipment or dosing changes; they convert the "
            "hypotheses in the other findings into testable evidence."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[what for _, is_absent, _, what in gaps if is_absent],
    )


# ------------------------------------------------------------------ runner


def run_advisor(df: pd.DataFrame) -> dict:
    """Run all six rules on the baseline scenario of df.

    Returns {"meta": ..., "findings": [...]} with findings ordered R1 to R6.
    The meta here carries no timestamp, so the result is fully deterministic
    for a given input; the build script adds generated_at when writing JSON.
    """
    raw = _prepare(df)
    clean = _clean(raw)
    episodes, _, _ = _low_removal_episodes(clean)
    upset_ts = {
        str(clean["timestamp"].iloc[i]) for s, e in episodes for i in range(s, e + 1)
    }

    findings = [
        rule_r1_process_upsets(raw),
        rule_r2_sensor_reliability(raw),
        rule_r3_energy_baseload(raw),
        rule_r4_dose_response(raw),
        rule_r5_ph_control(raw, upset_timestamps=upset_ts),
        rule_r6_data_gaps(raw),
    ]

    meta = {
        "method": "deterministic rule-based analysis, rules documented in docs/ADVISOR_METHODOLOGY.md",
        "scenario_analysed": "baseline",
        "period": {
            "start": str(raw["timestamp"].iloc[0])[:10],
            "end": str(raw["timestamp"].iloc[-1])[:10],
            "days": _period_days(raw),
            "hours_in_record": int(len(raw)),
            "hours_after_cleaning": int(len(clean)),
        },
        "thresholds": THRESHOLDS,
        "note": (
            "findings are computed from the data on every rebuild; with different data these findings "
            "change, including to no action justified"
        ),
    }
    return {"meta": meta, "findings": findings}
