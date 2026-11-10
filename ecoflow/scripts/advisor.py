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

All user-facing strings are written to be understood at one glance: short
sentences, one idea each, everyday words first with the technical term in
brackets where needed.

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
        "The plant sometimes stops cleaning properly. We flag any stretch of "
        f"{t['min_episode_hours']} hours or more where COD removal stays below "
        f"{t['removal_pct_floor']:.0f} percent. We use cleaned baseline data."
    )

    if not episodes:
        finite = removal[~np.isnan(removal)]
        return _finding(
            id="R1",
            title="Treatment upsets (hours of poor COD removal)",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"No upset found. We checked {n} cleaned hours. No stretch of "
                    f"{t['min_episode_hours']} hours or more fell below "
                    f"{t['removal_pct_floor']:.0f} percent COD removal."
                ),
                "details": [
                    f"Typical (median) hourly COD removal: {_r(reference, 1)} percent.",
                    f"Worst single hour: {_r(float(np.min(finite)), 1) if len(finite) else None} percent removal.",
                ],
            },
            possible_causes=[],
            recommendation=(
                "No action needed. Keep this check running so future upsets are caught early."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    in_episode = np.zeros(n, dtype=bool)
    details = []
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
        details.append(
            f"{seg['timestamp'].iloc[0]} to {seg['timestamp'].iloc[-1]}: {e - s + 1} h. "
            f"Removal fell to {_r(float(np.nanmin(seg_removal)), 1)} percent at worst. "
            f"About {_r(excess, 1)} kg of extra COD left the plant. "
            f"That is measured against the normal (median) removal of {_r(reference, 1)} percent, "
            "applied to the same incoming water."
        )

    # Observed test: was the influent unusually strong during the episodes?
    ep_cod = clean.loc[in_episode, "influent_cod_mgl"]
    free_cod = clean.loc[~in_episode, "influent_cod_mgl"]
    ep_med = float(ep_cod.median())
    free_med = float(free_cod.median())
    strength_pct = (ep_med / free_med - 1.0) * 100.0 if free_med > 0 else float("nan")
    unusually_strong = strength_pct > t["influent_strength_band_pct"]
    details.append(
        f"Incoming strength check: median influent COD was {_r(ep_med, 0)} mg/L during upsets. "
        f"Outside upsets it was {_r(free_med, 0)} mg/L. The difference is {_r(strength_pct, 1):+} percent. "
        f"We only call the influent 'unusually strong' above +{t['influent_strength_band_pct']:.0f} percent."
    )

    severity = "high" if total_excess > t["high_severity_excess_cod_kg"] else "medium"

    if unusually_strong:
        strength_cause = {
            "cause": (
                f"The incoming water was unusually strong during the upsets "
                f"({_r(strength_pct, 1):+} percent against normal). Load shocks are a plausible contributor."
            ),
            "basis": "observed",
        }
    else:
        strength_cause = {
            "cause": (
                "The incoming water was not unusually strong during the upsets. "
                f"Median influent COD was {_r(ep_med, 0)} against {_r(free_med, 0)} mg/L. "
                "So stronger influent does not explain them."
            ),
            "basis": "observed",
        }

    return _finding(
        id="R1",
        title="Treatment upsets (hours of poor COD removal)",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{len(episodes)} upsets, totalling {int(in_episode.sum())} hours below "
                f"{t['removal_pct_floor']:.0f} percent COD removal. "
                f"About {_r(total_excess, 0)} kg of extra COD was discharged. "
                f"That is measured against the plant's own normal removal of {_r(reference, 1)} percent. "
                f"The high-severity threshold is {t['high_severity_excess_cod_kg']:.0f} kg."
            ),
            "details": details,
        },
        possible_causes=[
            strength_cause,
            {
                "cause": "The treatment microbes (biomass) may have been stressed or poisoned. This needs measurement.",
                "basis": "hypothesis",
            },
            {
                "cause": "Aeration or other equipment may have failed during those hours. This needs checking.",
                "basis": "hypothesis",
            },
            {
                "cause": "Short-lived toxic compounds may have entered with the influent. COD alone cannot show this.",
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Write a simple upset response procedure. Trigger it when COD removal stays below "
            f"{t['removal_pct_floor']:.0f} percent for {t['min_episode_hours']} hours. "
            "Steps: confirm the readings with a hand sample. Check aeration and dosing equipment. "
            "Note the influent source at the time. Do the measurements listed below before buying anything. "
            "The current data cannot tell the possible causes apart."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Measure dissolved oxygen in the biological stage. The dataset has none.",
            "Examine the biomass under a microscope during and after an upset. The dataset has none.",
            "Screen the influent for toxic or inhibiting compounds. The dataset has none.",
        ],
    )


# --------------------------------------------------------------------- R2

_R2_RECOMMENDATIONS = {
    "stuck": "add it to a maintenance and cleaning schedule, with an alarm for repeated identical readings",
    "spike_above_range": "filter the signal (rolling median) and book a calibration check",
    "missing": "check the data logger and cable connectivity",
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
            f"{c['column']}: {c['count']} bad readings out of {n} ({_r(c['rate_pct'], 3)} percent). "
            f"The limit is {t['per_column_rate_pct']} percent. By check: {parts}. "
            f"Worst month: {c['worst_month']}. Examples: {', '.join(c['examples'])}."
        )
    zero_cols = [c["column"] for c in columns if c["count"] == 0]
    if zero_cols:
        details.append(f"No bad readings in: {', '.join(zero_cols)}.")
    details.append(
        f"The record's own tags show: {tag_counts if tag_counts else 'no tagged rows'}. "
        "Our checks and the tags are counted separately. One reading can trip more than one check."
    )

    problem = (
        "Sensors can give bad readings. We check each sensor column with the record's tags plus our own checks. "
        "We look for missing values, impossible values, and identical repeats "
        f"of {t['stuck_min_run_hours']} hours or more (stuck sensor). "
        f"A sensor fails when over {t['per_column_rate_pct']} percent of its readings are bad."
    )

    if not offending:
        return _finding(
            id="R2",
            title="Sensor health, per instrument",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"All {len(columns)} sensor columns are below the {t['per_column_rate_pct']} percent limit. "
                    f"We found {total_flagged} bad readings in total across {n} hours."
                ),
                "details": details,
            },
            possible_causes=[],
            recommendation=(
                "No sensor needs attention now. Keep the checks and routine calibration running. "
                "Bad readings are already removed before any KPI is computed."
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
        actions.append(f"{c['column']} (main fault: {c['dominant']}): {_R2_RECOMMENDATIONS[c['dominant']]}")

    return _finding(
        id="R2",
        title="Sensor health, per instrument",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{len(offending)} of {len(columns)} sensors are above the "
                f"{t['per_column_rate_pct']} percent bad-reading limit: "
                + ", ".join(f"{c['column']} ({_r(c['rate_pct'], 3)} percent)" for c in offending)
                + "."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": "The fault pattern is measured per sensor above. The main check type points at the failure mode.",
                "basis": "observed",
            },
            {
                "cause": "The root cause could be probe fouling, cabling or the logger. A field inspection is needed.",
                "basis": "hypothesis",
            },
        ],
        recommendation="Per instrument: " + "; ".join(actions) + ".",
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Inspect each offending instrument in the field. Pull its calibration records.",
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
        "Some electricity is used no matter how much water flows. "
        "We fit a straight line: kWh = a + b x flow. "
        "The intercept (a) is the always-on part, called base load. "
        f"We flag it when base load is over {t['baseload_share_pct']:.0f} percent of average hourly use."
    )
    fit_details = [
        f"Fitted on {len(normal)} cleaned normal hours.",
        f"Always-on part (intercept a): {_r(a, 2)} kWh per hour.",
        f"Flow-linked part (slope b): {_r(b, 4)} kWh per m3. Fit quality (R2): {_r(r2, 3)}.",
        f"Average use: {_r(mean_kwh, 1)} kWh per hour. Base-load share: {_r(share_pct, 1)} percent. "
        f"The limit is {t['baseload_share_pct']:.0f} percent.",
    ]

    if not (share_pct > t["baseload_share_pct"]):
        return _finding(
            id="R3",
            title="Always-on electricity use (base load)",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"Base load is only {_r(share_pct, 1)} percent of average hourly use. "
                    f"The limit is {t['baseload_share_pct']:.0f} percent. "
                    f"Electricity tracks flow well (R2 = {_r(r2, 3)})."
                ),
                "details": fit_details
                + [
                    "An intercept near or below zero means effectively no base load in this data."
                ],
            },
            possible_causes=[],
            recommendation=(
                "No investigation needed now. Re-run this check when new data arrives. "
                "Submeter the big drives if a finer breakdown is ever wanted."
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
        title="Always-on electricity use (base load)",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"Base load is {_r(share_pct, 1)} percent of average hourly use. "
                f"The limit is {t['baseload_share_pct']:.0f} percent. "
                f"About {_r(a, 1)} kWh is used every hour regardless of flow."
            ),
            "details": fit_details,
        },
        possible_causes=[
            {
                "cause": "Part of the electricity use does not change with flow. The fit measures how much. It cannot name the equipment.",
                "basis": "observed",
            },
            {
                "cause": "Aeration may be running at a fixed minimum regardless of load. This needs checking.",
                "basis": "hypothesis",
            },
            {
                "cause": "Lighting, HVAC, pumps or other auxiliaries may run all the time. This needs a site survey.",
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Survey what runs all the time: idle aeration, lighting, auxiliaries. "
            "Submeter the biggest drives. Attribute the base load before changing any setpoint."
        ),
        expected_impact={
            "summary": (
                f"Cutting the {_r(a, 1)} kWh per hour base load by "
                f"{t['reduction_pct_low']:.0f} to {t['reduction_pct_high']:.0f} percent saves roughly "
                f"{_r(saved(t['reduction_pct_low']), 0)} to {_r(saved(t['reduction_pct_high']), 0)} kWh a year."
            ),
            "calculations": [
                {"label": "always-on base load (intercept a)", "value": _r(a, 2), "unit": "kWh/h"},
                {"label": "flow-linked slope (b)", "value": _r(b, 4), "unit": "kWh/m3"},
                {"label": "fit quality (R2)", "value": _r(r2, 3), "unit": "dimensionless"},
                {"label": "base-load share of average use", "value": _r(share_pct, 1), "unit": "%"},
                {"label": "yearly saving, base case", "value": _r(base_saving, 0), "unit": "kWh/yr"},
                {
                    "label": "saving as share of yearly use",
                    "value": _r(base_saving / annual_total_kwh * 100.0, 1),
                    "unit": "%",
                },
            ],
            "assumptions": [
                f"We assume {t['reduction_pct_low']:.0f} to {t['reduction_pct_high']:.0f} percent of the base load "
                "can be removed. The real share is unknown until the load is attributed.",
                "We assume the intercept is real equipment, not a fitting artefact. Submetering must confirm this.",
                "We assume this period scales to 8760 hours a year.",
            ],
            "sensitivity": {
                "low": _r(saved(t["reduction_pct_low"]), 0),
                "base": _r(base_saving, 0),
                "high": _r(saved(t["reduction_pct_high"]), 0),
                "unit": "kWh/yr",
                "description": (
                    f"Base-load cut of {t['reduction_pct_low']:.0f} percent (low), "
                    f"{t['reduction_pct_base']:.0f} percent (base) and {t['reduction_pct_high']:.0f} percent (high)."
                ),
            },
        },
        tradeoffs=(
            "Never cut loads that protect the process. Minimum aeration, mixing and instruments must keep running."
        ),
        quality_gate={
            "check": "We assume treatment is unaffected because only flow-independent equipment would be cut.",
            "outcome": "conditional",
            "note": (
                "This is an assumption, not a verified result. Confirm the targeted equipment plays no "
                "treatment role. Watch the removal KPIs during a trial switch-off."
            ),
        },
        validation_required=[
            "Submeter the blowers and major drives to attribute the base load. The dataset has none.",
            "Run a supervised trial switch-off while watching the removal KPIs.",
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
        "We test whether more coagulant actually buys better solids removal (TSS removal). "
        "We use cleaned normal hours. "
        "We compare removal at the highest doses against the lowest doses (top against bottom quartile). "
        f"A difference under {t['quartile_removal_diff_pp']} percentage point counts as no visible response."
    )
    base_details = [
        f"Computed on {len(dose)} cleaned normal hours over {period_days} days.",
        f"Dose spread: P25 {_r(q25, 1)}, median {_r(q50, 1)}, P75 {_r(q75, 1)} g/m3.",
        f"Link (correlation) between dose and TSS removal: {_r(corr, 3)}.",
        f"Top dose quarter: {_r(top, 2)} percent removal. Bottom quarter: {_r(bottom, 2)} percent. "
        f"Difference: {_r(diff_pp, 2)} percentage points. "
        f"The limit for 'no response' is {t['quartile_removal_diff_pp']} point.",
    ]

    if diff_pp >= t["quartile_removal_diff_pp"]:
        return _finding(
            id="R4",
            title="Coagulant dose and what it buys (dose response)",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    "More dose buys more removal in this data. "
                    f"Top-minus-bottom quartile difference: {_r(diff_pp, 2)} percentage points. "
                    f"Correlation: {_r(corr, 3)}. Cutting the dose would likely cost removal."
                ),
                "details": base_details,
            },
            possible_causes=[
                {
                    "cause": "Higher doses go with measurably better TSS removal in this record.",
                    "basis": "observed",
                }
            ],
            recommendation=(
                "No dose reduction justified. The data shows removal still gains from dose. "
                "Revisit only if the dose range or the coagulant changes."
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
            "The slight negative link is more likely a shared driver (confounding) than a real effect. "
            "The trial below settles it."
        )

    return _finding(
        id="R4",
        title="Coagulant dose and what it buys (dose response)",
        status="conditional",
        severity="medium",
        problem=problem,
        evidence={
            "summary": (
                "Solids removal does not change with dose in this data. "
                f"Dose range tested: {_r(q25, 1)} to {_r(q75, 1)} g/m3 (middle half). "
                f"Quartile difference: {_r(diff_pp, 2)} percentage points. Correlation: {_r(corr, 3)}. "
                "The data cannot say why."
            ),
            "details": base_details + negative_note,
        },
        possible_causes=[
            {
                "cause": "Removal does not vary with dose across the doses actually used.",
                "basis": "observed",
            },
            {
                "cause": (
                    "Dosing may already be past the point of diminishing returns (saturation plateau). "
                    "The top of the range would then be wasted."
                ),
                "basis": "hypothesis",
            },
            {
                "cause": "A real response may be hidden by noise and the narrow dose range.",
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Run a controlled stepped-dose trial first. Vary the dose on purpose. "
            "Sample the effluent at each step (jar tests plus TSS samples). "
            "This separates a real plateau from noise. No dose reduction is justified today. "
            "The saving below applies only if the trial confirms the plateau."
        ),
        expected_impact={
            "summary": (
                "If the trial confirms a plateau: trim doses above the median down to the median. "
                f"That saves about {_r(base_saving, 0)} kg of coagulant a year. "
                "The figure comes from the actual dose record."
            ),
            "calculations": [
                {"label": "trim target: median dose, base case", "value": _r(target_base, 1), "unit": "g/m3"},
                {"label": "yearly coagulant saving, base case", "value": _r(base_saving, 0), "unit": "kg/yr"},
            ],
            "assumptions": [
                "The trial must confirm no loss of TSS removal at the trimmed doses. Without that, there is no saving.",
                "Savings use cleaned normal hours, scaled to a year by calendar days "
                f"(x {ANNUAL_DAYS:.0f}/{period_days}).",
                "We assume this period's influent and dosing represent a full year.",
            ],
            "sensitivity": {
                "low": _r(annual_saved_kg(target_low), 0),
                "base": _r(base_saving, 0),
                "high": _r(annual_saved_kg(target_high), 0),
                "unit": "kg/yr",
                "description": (
                    f"Trim target at the P{p_high} (low), P{p_base} (base) and P{p_low} (high) dose percentile. "
                    "A lower target trims more and saves more."
                ),
            },
        },
        tradeoffs=(
            "Cutting coagulant without trial evidence risks losing solids removal. "
            "The whole saving depends on the trial outcome."
        ),
        quality_gate={
            "check": "A stepped-dose trial must show TSS removal is unaffected at the trimmed doses.",
            "outcome": "conditional",
            "note": "This gate cannot pass on the current data. No reduction is justified today.",
        },
        validation_required=[
            "Run the stepped-dose trial with jar tests and effluent TSS samples. The dataset has none.",
            "Keep coagulant batch quality records for the trial period.",
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
        "Treated water should leave at a near-neutral pH. "
        f"We count cleaned hours outside pH {t['ph_low']} to {t['ph_high']}. "
        f"Under {t['cleared_below_hours']} such hours in {period_days} days, the check is cleared."
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
                    f"{hours} hour(s) outside pH {t['ph_low']} to {t['ph_high']}, out of {len(clean)} cleaned hours. "
                    f"That is below the {t['cleared_below_hours']} hour limit."
                ),
                "details": [
                    f"Observed effluent pH range: {_r(float(np.min(ph)), 2)} to {_r(float(np.max(ph)), 2)}."
                ],
            },
            possible_causes=[],
            recommendation="No action needed. Effluent pH is well controlled over this period.",
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
                f"{hours} cleaned hours outside pH {t['ph_low']} to {t['ph_high']} over {period_days} days. "
                f"Worst excursion: {_r(depth, 2)} pH units beyond the band. "
                f"{overlap} of those hours fall inside the upsets found by R1."
            ),
            "details": [
                f"Hours outside the band: {hours} ({_r(hours / max(len(clean), 1) * 100.0, 2)} percent of cleaned hours).",
                f"Examples: {', '.join(examples)}.",
                f"Overlap with R1 upsets: {overlap} hour(s). This is measured from the two checks' timestamps.",
            ],
        },
        possible_causes=[
            {
                "cause": (
                    f"{overlap} of {hours} excursion hours coincide with poor removal upsets. "
                    "Measured directly from this record."
                ),
                "basis": "observed",
            },
            {"cause": "The neutralisation dosing loop may be drifting or saturating.", "basis": "hypothesis"},
            {
                "cause": "The pH probe may be drifting. That would be a measurement fault, not a process fault.",
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Review the neutralisation control loop tuning. Alarm on sustained excursions. "
            "Verify the probe against a calibrated handheld meter before changing dosing."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Check the pH probe against a reference instrument.",
            "Pull the neutralisation reagent dosing records for the excursion hours. The dataset has none.",
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
            "Without it, upsets (R1) cannot be traced to aeration, overload or poisoning.",
            "Log dissolved oxygen in the aeration basin every 15 minutes.",
        ),
        (
            "Blower and aeration power submetering",
            absent("blower", "aeration"),
            "The energy check (R3) sees one total meter. The biggest consumer cannot be separated.",
            "Submeter the blowers and other big drives. Log them hourly.",
        ),
        (
            "Controlled dose-response trial data",
            absent("trial", "jar_test"),
            "The dose check (R4) cannot tell a plateau from noise without deliberately varied doses.",
            "Run a stepped-dose trial with jar tests across a wider dose range.",
        ),
        (
            "Design capacity and equipment ratings",
            absent("design", "capacity", "rating"),
            "Loads cannot be judged against design limits. Headroom and overload risk are unknown.",
            "Record nameplate capacities and design flows next to the operating data.",
        ),
        (
            "Laboratory-verified samples",
            absent("lab_", "laboratory"),
            "Online COD, TSS and pH readings are never checked against lab values here.",
            "Take periodic lab samples paired to timestamps. Use them to audit the online instruments.",
        ),
    ]

    details = [f"{name}. Why it matters: {why} What to measure: {what}" for name, is_absent, why, what in gaps if is_absent]
    present = [name for name, is_absent, _, _ in gaps if not is_absent]
    n_gaps = len(details)
    if present:
        details.append(f"Already present in the dataset: {', '.join(present)}.")

    return _finding(
        id="R6",
        title="Missing measurements (data gaps)",
        status="informational",
        severity=None,
        problem=(
            "Some measurements are missing from this dataset. The gaps limit how far the other checks can go. "
            "Nothing is invented to fill them, and the simulation is not extended."
        ),
        evidence={
            "summary": (
                f"{n_gaps} measurement gaps found by checking the dataset's columns. "
                "Several causes in R1 to R4 stay unproven until these are measured."
            ),
            "details": details,
        },
        possible_causes=[],
        recommendation=(
            "Add these measurements before committing to equipment or dosing changes. "
            "They turn the hypotheses in the other findings into testable evidence."
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
