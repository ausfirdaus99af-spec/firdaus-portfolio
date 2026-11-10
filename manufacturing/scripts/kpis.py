"""Pure KPI functions for Project 03 - Manufacturing Performance Analytics.

All inputs are synthetic data. The functions here are pure: they take plain
numbers (or a DataFrame for the aggregation helpers), have no side effects,
and return floats. Any calculation with a zero or invalid denominator
returns NaN rather than raising or returning a misleading zero.

Denominator conventions:
- Planned production time per shift is 7.5 hours (8 hour shift minus a
  0.5 hour planned break). The planned break is excluded from every OEE
  denominator.
- Aggregations over many rows are time weighted. Availability over a set of
  rows is sum(run_time) / sum(planned_time), performance is
  sum(actual) / sum(ideal_rate x run_time per row), and quality is
  sum(good) / sum(actual). Row level percentages are never averaged,
  because a plain average gives every row equal weight regardless of how
  long it ran or how many units it made.
"""

import math


def _ratio(numerator, denominator):
    """Safe division. Returns NaN when the denominator is zero or NaN."""
    try:
        num = float(numerator)
        den = float(denominator)
    except (TypeError, ValueError):
        return math.nan
    if den == 0.0 or math.isnan(den) or math.isnan(num):
        return math.nan
    return num / den


def production_achievement_pct(actual_units, planned_units):
    """actual / planned x 100."""
    return _ratio(actual_units, planned_units) * 100.0


def capacity_utilisation_pct(actual_units, ideal_rate_uph, planned_time_h):
    """actual / (ideal_rate x planned_time) x 100."""
    return _ratio(actual_units, float(ideal_rate_uph) * float(planned_time_h)) * 100.0


def yield_pct(good_units, actual_units):
    """good / actual x 100."""
    return _ratio(good_units, actual_units) * 100.0


def rejection_rate_pct(rejected_units, actual_units):
    """rejected / actual x 100."""
    return _ratio(rejected_units, actual_units) * 100.0


def availability_pct(run_time_h, planned_time_h):
    """run_time / planned_time x 100. Planned time excludes the planned break."""
    return _ratio(run_time_h, planned_time_h) * 100.0


def performance_pct(actual_units, run_time_h, ideal_rate_uph):
    """(actual / run_time) / ideal_rate x 100.

    Deliberately NOT capped at 100. The ideal rate is a nameplate figure,
    and a line can genuinely run faster than nameplate for a shift, for
    example after a tuning improvement or with an easy product mix. Capping
    would hide that signal and silently distort OEE, so values above 100
    are allowed and documented.
    """
    rate = _ratio(actual_units, run_time_h)
    return _ratio(rate, ideal_rate_uph) * 100.0


def quality_pct(good_units, actual_units):
    """good / actual x 100."""
    return _ratio(good_units, actual_units) * 100.0


def oee_pct(availability, performance, quality):
    """availability x performance x quality / 10000 (inputs in percent)."""
    try:
        a = float(availability)
        p = float(performance)
        q = float(quality)
    except (TypeError, ValueError):
        return math.nan
    if math.isnan(a) or math.isnan(p) or math.isnan(q):
        return math.nan
    return a * p * q / 10000.0


def energy_intensity_kwh_per_good_unit(energy_kwh, good_units):
    """energy / good units."""
    return _ratio(energy_kwh, good_units)


def aggregate_kpis(df):
    """Time weighted KPI set for a DataFrame of production rows.

    Required columns: planned_units, actual_units, good_units,
    rejected_units, planned_time_h, run_time_h, downtime_h, energy_kwh,
    ideal_rate.

    Weighted aggregation, never an average of row percentages:
    - availability = sum(run_time) / sum(planned_time)
    - performance  = sum(actual) / sum(ideal_rate x run_time per row)
    - quality      = sum(good) / sum(actual)
    - oee          = availability x performance x quality
    """
    plan = float(df["planned_units"].sum())
    act = float(df["actual_units"].sum())
    good = float(df["good_units"].sum())
    rej = float(df["rejected_units"].sum())
    pt = float(df["planned_time_h"].sum())
    rt = float(df["run_time_h"].sum())
    energy = float(df["energy_kwh"].sum())
    ideal_rt = float((df["ideal_rate"] * df["run_time_h"]).sum())
    ideal_pt = float((df["ideal_rate"] * df["planned_time_h"]).sum())

    avail = _ratio(rt, pt) * 100.0
    perf = _ratio(act, ideal_rt) * 100.0
    qual = _ratio(good, act) * 100.0

    return {
        "production_achievement_pct": _ratio(act, plan) * 100.0,
        "capacity_utilisation_pct": _ratio(act, ideal_pt) * 100.0,
        "yield_pct": qual,
        "rejection_rate_pct": _ratio(rej, act) * 100.0,
        "availability_pct": avail,
        "performance_pct": perf,
        "quality_pct": qual,
        "oee_pct": oee_pct(avail, perf, qual),
        "energy_intensity_kwh_per_good_unit": _ratio(energy, good),
        "downtime_hours_total": float(df["downtime_h"].sum()),
    }


def downtime_pareto(df, exclude=("None",)):
    """Downtime hours by cause, sorted descending, with Pareto shares.

    Returns a list of dicts: reason, hours, pct (share of total attributable
    downtime) and cum_pct (cumulative share). Rows whose reason is "None"
    (micro stops under 0.1 hours) are excluded by default because they have
    no attributable cause.
    """
    sub = df[~df["downtime_reason"].isin(exclude)]
    grouped = (
        sub.groupby("downtime_reason")["downtime_h"]
        .sum()
        .sort_values(ascending=False)
    )
    total = float(grouped.sum())
    out = []
    cumulative = 0.0
    for reason, hours in grouped.items():
        hours = float(hours)
        cumulative += hours
        out.append({
            "reason": str(reason),
            "hours": hours,
            "pct": _ratio(hours, total) * 100.0,
            "cum_pct": _ratio(cumulative, total) * 100.0,
        })
    return out
