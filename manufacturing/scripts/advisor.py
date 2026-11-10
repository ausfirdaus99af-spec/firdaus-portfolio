"""Deterministic rule-based Operations Improvement Advisor.

Project 03 - Manufacturing Performance Analytics. All data is synthetic.

This module turns the exported production rows into six findings. Each
finding comes from an explicit rule with documented thresholds. The rules
are written up in docs/ADVISOR_METHODOLOGY.md. The thresholds live in
THRESHOLDS below and are copied into the output JSON.

Integrity rules this module is built around:

1. Nothing is hardcoded as a discovery. Every finding is computed from the
   dataframe passed in. When the data does not justify a recommendation
   the rule returns a cleared check (status "no_action_justified").
   Cleared checks stay in the output on purpose. With different data the
   same rules produce different findings.
2. Impact figures come from the actual rows, with stated assumptions and
   a sensitivity range (low, base, high). Never a fixed saving claim.
3. Every recommendation that adds output or cuts energy carries a quality
   gate. The gate states the quality check the saving depends on. The
   quality rate is never assumed to survive a speed-up.
4. Observed evidence (computed from this dataset) is kept separate from
   hypotheses that need further measurement. Every possible cause is
   tagged with its basis.

All public functions are pure: they take a dataframe and return dicts,
with no file or network access, so the engine is easy to test and reuse.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ANNUAL_DAYS = 365.0

# Every numeric decision point in the rules, in one place. These are
# engineering review thresholds, not discoveries: changing them changes
# which findings fire, and they are published in the output JSON.
THRESHOLDS = {
    "R1": {
        "dominant_share_pct": 25.0,
        "high_severity_share_pct": 40.0,
        "reduction_pct_low": 30.0,
        "reduction_pct_base": 40.0,
        "reduction_pct_high": 50.0,
    },
    "R2": {
        "gap_points": 2.0,
        "high_severity_gap_points": 4.0,
        "close_pct_low": 50.0,
        "close_pct_base": 75.0,
        "close_pct_high": 100.0,
    },
    "R3": {
        "gap_points": 1.5,
        "high_severity_gap_points": 3.0,
        "close_pct_low": 50.0,
        "close_pct_base": 75.0,
        "close_pct_high": 100.0,
    },
    "R4": {
        "programme_start": "2026-07-01",
        "meaningful_reduction_pct": 15.0,
        "z_score_floor": 2.0,
        "sustain_pct_low": 50.0,
        "sustain_pct_base": 75.0,
        "sustain_pct_high": 100.0,
    },
    "R5": {
        "idle_kwh_per_downtime_h_floor": 5.0,
        "t_stat_floor": 2.0,
        "high_severity_share_of_total_pct": 2.0,
        "avoidable_pct_low": 30.0,
        "avoidable_pct_base": 50.0,
        "avoidable_pct_high": 70.0,
    },
    "R6": {
        "excess_pp_floor": 0.3,
        "ratio_floor": 1.10,
        "high_severity_excess_pp": 1.0,
        "min_rows_per_cell": 50,
        "close_pct_low": 50.0,
        "close_pct_base": 75.0,
        "close_pct_high": 100.0,
    },
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

_REQUIRED_COLUMNS = (
    "date", "line", "shift", "category",
    "planned_units", "actual_units", "good_units", "rejected_units",
    "planned_time_h", "run_time_h", "downtime_h",
    "downtime_reason", "energy_kwh", "ideal_rate",
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
    """Validated, date-sorted copy with parsed _date and _week columns."""
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if len(df) == 0:
        raise ValueError("no rows to analyse")
    out = df.copy()
    out["_date"] = pd.to_datetime(out["date"])
    out["_week"] = out["_date"].dt.to_period("W").astype(str)
    return out.sort_values(["_date", "line", "shift"]).reset_index(drop=True)


def _annual_factor(raw: pd.DataFrame) -> float:
    """Scale factor from the record's span to a 365 day year."""
    days = _period_days(raw)
    return ANNUAL_DAYS / days if days > 0 else float("nan")


def _period_days(raw: pd.DataFrame) -> int:
    first = raw["_date"].iloc[0].normalize()
    last = raw["_date"].iloc[-1].normalize()
    return int((last - first).days) + 1


def _availability_pct(sub: pd.DataFrame) -> float:
    pt = float(sub["planned_time_h"].sum())
    return float(sub["run_time_h"].sum()) / pt * 100.0 if pt > 0 else float("nan")


def _performance_pct(sub: pd.DataFrame) -> float:
    den = float((sub["ideal_rate"] * sub["run_time_h"]).sum())
    return float(sub["actual_units"].sum()) / den * 100.0 if den > 0 else float("nan")


def _quality_pct(sub: pd.DataFrame) -> float:
    act = float(sub["actual_units"].sum())
    return float(sub["good_units"].sum()) / act * 100.0 if act > 0 else float("nan")


def _rejection_pct(sub: pd.DataFrame) -> float:
    act = float(sub["actual_units"].sum())
    return float(sub["rejected_units"].sum()) / act * 100.0 if act > 0 else float("nan")


def _realised_rate_uph(sub: pd.DataFrame) -> float:
    """Measured output speed: units made per hour actually run."""
    rt = float(sub["run_time_h"].sum())
    return float(sub["actual_units"].sum()) / rt if rt > 0 else float("nan")


def _sensitivity(low, base, high, unit: str, description: str) -> dict:
    return {
        "low": _r(low, 0),
        "base": _r(base, 0),
        "high": _r(high, 0),
        "unit": unit,
        "description": description,
    }


# --------------------------------------------------------------------- R1


def rule_r1_dominant_loss_cause(df: pd.DataFrame) -> dict:
    """R1: does one downtime cause dominate the lost hours (Pareto)?"""
    t = THRESHOLDS["R1"]
    raw = _prepare(df)
    annual = _annual_factor(raw)

    attributable = raw[raw["downtime_reason"] != "None"]
    by_cause = (
        attributable.groupby("downtime_reason")["downtime_h"].sum().sort_values(ascending=False)
    )
    total_hours = float(by_cause.sum())
    top_cause = str(by_cause.index[0]) if len(by_cause) else None
    top_hours = float(by_cause.iloc[0]) if len(by_cause) else 0.0
    top_share = top_hours / total_hours * 100.0 if total_hours > 0 else float("nan")

    problem = (
        "Ranks downtime causes by lost hours (Pareto). "
        f"Fires when one cause holds over {t['dominant_share_pct']:.0f} percent of lost hours. "
        "Micro stops with no recorded cause are excluded."
    )
    pareto_details = [
        f"{reason}: {_r(hours, 1)} hours, {_r(hours / total_hours * 100.0, 1)} percent of lost time."
        for reason, hours in by_cause.items()
    ]

    if not (top_share > t["dominant_share_pct"]):
        return _finding(
            id="R1",
            title="Dominant downtime cause",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"No single cause dominates. The top cause, {top_cause}, holds "
                    f"{_r(top_share, 1)} percent of {_r(total_hours, 1)} lost hours. "
                    f"The threshold is {t['dominant_share_pct']:.0f} percent."
                ),
                "details": pareto_details,
            },
            possible_causes=[],
            recommendation=(
                "No single-cause programme justified. The losses are spread. "
                "Keep the Pareto under monthly review."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    affected = raw[raw["downtime_reason"] == top_cause]
    rate = affected["actual_units"] / affected["run_time_h"]

    def units_at(reduction_pct: float) -> float:
        recovered = affected["downtime_h"] * reduction_pct / 100.0
        return float((recovered * rate).sum()) * annual

    hours_low = top_hours * t["reduction_pct_low"] / 100.0 * annual
    hours_high = top_hours * t["reduction_pct_high"] / 100.0 * annual
    units_base = units_at(t["reduction_pct_base"])
    plan_total = float(raw["planned_units"].sum())
    act_total = float(raw["actual_units"].sum())
    plan_points = (
        ((act_total + units_at(t["reduction_pct_base"]) / annual) / plan_total
         - act_total / plan_total) * 100.0
        if plan_total > 0 else float("nan")
    )

    if top_cause == "Changeover":
        action = (
            "Run a focused changeover programme. Standardise the steps "
            "(SMED style). Prepare tools, materials and labels before the "
            "line stops. Time and film a few changeovers first."
        )
        why = (
            "Changeovers may lack standard steps and prepared kits. "
            "The data shows the hours, not the reason they are long."
        )
    elif top_cause == "Equipment breakdown":
        action = (
            "Run a focused reliability programme. Move from repair on "
            "failure to planned maintenance. Start with the worst line."
        )
        why = (
            "Breakdowns may come from worn parts or missed servicing. "
            "The data shows the hours, not the failure modes."
        )
    else:
        action = (
            f"Run a focused reduction programme on {top_cause}. "
            "Map each stop, find the repeat patterns, remove the biggest."
        )
        why = (
            f"The data shows {top_cause} takes the most hours. "
            "It does not show why each stop happens."
        )

    severity = "high" if top_share > t["high_severity_share_pct"] else "medium"

    return _finding(
        id="R1",
        title="Dominant downtime cause",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{top_cause} is the biggest loss. It holds {_r(top_share, 1)} percent "
                f"of {_r(total_hours, 1)} lost hours. "
                f"The threshold is {t['dominant_share_pct']:.0f} percent."
            ),
            "details": pareto_details + [
                f"{len(affected)} shifts carry {top_cause} downtime.",
                f"Those shifts run at {_r(float(rate.mean()), 0)} units per hour on average "
                "(their own realised rates).",
            ],
        },
        possible_causes=[
            {
                "cause": (
                    f"The lost hours are measured by cause. {top_cause} leads with "
                    f"{_r(top_hours, 1)} hours."
                ),
                "basis": "observed",
            },
            {"cause": why, "basis": "hypothesis"},
        ],
        recommendation=action,
        expected_impact={
            "summary": (
                f"Cutting {top_cause} time by {t['reduction_pct_low']:.0f} to "
                f"{t['reduction_pct_high']:.0f} percent frees {_r(hours_low, 0)} to "
                f"{_r(hours_high, 0)} run hours a year. "
                f"That is about {_r(units_at(t['reduction_pct_low']), 0)} to "
                f"{_r(units_at(t['reduction_pct_high']), 0)} units a year, at the shifts' own rates. "
                f"The base case lifts plan achievement by about {_r(plan_points, 2)} points."
            ),
            "calculations": [
                {"label": f"{top_cause} hours in the record", "value": _r(top_hours, 1), "unit": "h"},
                {"label": "share of all lost hours", "value": _r(top_share, 1), "unit": "%"},
                {"label": "recovered hours at base case", "value": _r(top_hours * t["reduction_pct_base"] / 100.0 * annual, 0), "unit": "h/yr"},
                {"label": "extra units at base case", "value": _r(units_base, 0), "unit": "units/yr"},
                {"label": "plan achievement gain at base case", "value": _r(plan_points, 2), "unit": "points"},
            ],
            "assumptions": [
                "Each affected shift restarts at its own measured speed (realised rate).",
                f"A {t['reduction_pct_low']:.0f} to {t['reduction_pct_high']:.0f} percent cut is assumed, not measured.",
                "The period analysed repeats itself over a full year.",
            ],
            "sensitivity": _sensitivity(
                units_at(t["reduction_pct_low"]),
                units_base,
                units_at(t["reduction_pct_high"]),
                "units/yr",
                (
                    f"{top_cause} time cut by {t['reduction_pct_low']:.0f} percent (low), "
                    f"{t['reduction_pct_base']:.0f} percent (base) and "
                    f"{t['reduction_pct_high']:.0f} percent (high)."
                ),
            ),
        },
        tradeoffs=(
            "Faster changeovers or repairs must not skip cleaning, checks or "
            "safety steps. Cutting corners moves the loss into quality."
        ),
        quality_gate={
            "check": (
                "Extra output is counted at each shift's own quality rate. "
                "The quality rate is not assumed to survive faster working."
            ),
            "outcome": "conditional",
            "note": (
                "Track the reject rate through the first weeks of the programme. "
                "Stop and review if rejects rise."
            ),
        },
        validation_required=[
            "Time and film several of the affected stops to map the steps.",
            "Track reject rates while the new method beds in.",
        ],
    )


# --------------------------------------------------------------------- R2


def _common_mix(raw: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Rows restricted to date and shift slots that every line ran.

    Returns (subset, identical) where identical is True when no row was
    dropped, meaning every line already ran the same dates and shifts.
    """
    keys_by_line = {
        line: set(zip(sub["date"], sub["shift"]))
        for line, sub in raw.groupby("line")
    }
    common = set.intersection(*keys_by_line.values())
    mask = [pair in common for pair in zip(raw["date"], raw["shift"])]
    sub = raw[pd.Series(mask, index=raw.index)]
    return sub, len(sub) == len(raw)


def rule_r2_worst_line_availability(df: pd.DataFrame) -> dict:
    """R2: does any line trail the best line's availability by over 2 points?"""
    t = THRESHOLDS["R2"]
    raw = _prepare(df)
    annual = _annual_factor(raw)
    mix, identical = _common_mix(raw)

    avail = {line: _availability_pct(sub) for line, sub in mix.groupby("line")}
    best_line = max(avail, key=avail.get)
    worst_line = min(avail, key=avail.get)
    gaps = {line: avail[best_line] - a for line, a in avail.items() if line != best_line}
    offenders = sorted(
        (line for line, gap in gaps.items() if gap > t["gap_points"]),
        key=lambda line: -gaps[line],
    )

    def chronic_numbers(line: str):
        """Full gap, and the gap with the line's worst week set aside."""
        line_weeks = mix[mix["line"] == line].groupby("_week")["downtime_h"].sum()
        worst_week = str(line_weeks.idxmax())
        trimmed = mix[mix["_week"] != worst_week]
        chronic_gap = (
            _availability_pct(trimmed[trimmed["line"] == best_line])
            - _availability_pct(trimmed[trimmed["line"] == line])
        )
        return avail[best_line] - avail[line], chronic_gap, worst_week

    mix_note = (
        "Every line ran the same dates and shifts, so the period mix is identical."
        if identical else
        "Lines ran different slots. Only dates and shifts that every line ran are compared."
    )

    problem = (
        "Compares each line's availability with the best line on the same "
        "dates and shifts. "
        f"Fires when a line trails by more than {t['gap_points']:.0f} percentage points. "
        "One-off crash weeks are reported separately from the chronic gap."
    )

    full_gap_w, chronic_gap_w, worst_week_w = chronic_numbers(worst_line)
    base_details = [mix_note] + [
        f"{line}: availability {_r(a, 2)} percent." for line, a in sorted(avail.items())
    ] + [
        f"Widest gap: {worst_line} trails {best_line} by {_r(full_gap_w, 2)} points over the full period.",
        (
            f"{worst_line}'s worst week is {worst_week_w} "
            f"({_r(float(mix[(mix['line'] == worst_line) & (mix['_week'] == worst_week_w)]['downtime_h'].sum()), 1)} downtime hours). "
            f"With that week set aside the chronic gap is {_r(chronic_gap_w, 2)} points."
        ),
    ]

    if not offenders:
        return _finding(
            id="R2",
            title="Worst line availability gap",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"No line trails the best by more than {t['gap_points']:.0f} points. "
                    f"{best_line} leads at {_r(avail[best_line], 2)} percent. "
                    f"{worst_line} trails most, by {_r(full_gap_w, 2)} points. "
                    f"Set the one-off worst week aside and the chronic gap is {_r(chronic_gap_w, 2)} points."
                ),
                "details": base_details,
            },
            possible_causes=[],
            recommendation=(
                "No line-closing programme justified by this check. "
                "Keep watching the gap monthly, with crash weeks shown separately."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    details = list(base_details)
    calcs = []
    units_low = units_base = units_high = 0.0
    for line in offenders:
        full_gap, chronic_gap, worst_week = chronic_numbers(line)
        chronic_gap = max(chronic_gap, 0.0)
        sub = mix[mix["line"] == line]
        line_reasons = sub.groupby("downtime_reason")["downtime_h"].sum().sort_values(ascending=False)
        top_reason = str(line_reasons.index[0])
        planned_h = float(sub["planned_time_h"].sum())
        rate = _realised_rate_uph(sub)

        def close(share_pct: float) -> float:
            extra_h = chronic_gap / 100.0 * planned_h * share_pct / 100.0
            return extra_h * rate * annual

        units_low += close(t["close_pct_low"])
        units_base += close(t["close_pct_base"])
        units_high += close(t["close_pct_high"])
        details.append(
            f"{line}: full gap {_r(full_gap, 2)} points, chronic gap {_r(chronic_gap, 2)} points "
            f"(worst week {worst_week} set aside). "
            f"Most of its downtime goes to {top_reason} "
            f"({_r(float(line_reasons.iloc[0]), 1)} hours)."
        )
        calcs.append({"label": f"{line} chronic gap", "value": _r(chronic_gap, 2), "unit": "points"})
        calcs.append({"label": f"{line} realised rate", "value": _r(rate, 0), "unit": "units/h"})

    worst = offenders[0]
    severity = "high" if gaps[worst] > t["high_severity_gap_points"] else "medium"

    return _finding(
        id="R2",
        title="Worst line availability gap",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{worst} trails {best_line} by {_r(gaps[worst], 2)} points of availability. "
                f"The threshold is {t['gap_points']:.0f} points. "
                "The chronic gap and the one-off crash week are shown separately below."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": (
                    "Where the lost hours go is measured, by reason and line. "
                    "The details list the worst line's biggest downtime reason."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    "Older equipment could explain a chronic gap. That is a hypothesis. "
                    "The data shows where the hours go, not the age or condition of the kit."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            f"Investigate {worst}'s biggest downtime reason first. "
            "Treat the crash week as a separate one-off event with its own review. "
            "Target the chronic gap, not the headline gap."
        ),
        expected_impact={
            "summary": (
                f"Closing half to all of the chronic gap adds about {_r(units_low, 0)} to "
                f"{_r(units_high, 0)} units a year. "
                "Computed from the trailing lines' own planned hours and realised rates."
            ),
            "calculations": calcs,
            "assumptions": [
                "The chronic gap excludes each trailing line's single worst week.",
                "Extra run time produces at the line's own measured speed (realised rate).",
                "The period analysed repeats itself over a full year.",
            ],
            "sensitivity": _sensitivity(
                units_low, units_base, units_high, "units/yr",
                (
                    f"Chronic gap closed by {t['close_pct_low']:.0f} percent (low), "
                    f"{t['close_pct_base']:.0f} percent (base) and "
                    f"{t['close_pct_high']:.0f} percent (high)."
                ),
            ),
        },
        tradeoffs=(
            "Chasing availability with deferred maintenance backfires. "
            "Fix the downtime causes, do not skip the planned work."
        ),
        quality_gate={
            "check": (
                "Extra output is counted at the line's own quality rate. "
                "The quality rate is not assumed to survive more running time."
            ),
            "outcome": "conditional",
            "note": "Track the trailing line's reject rate while availability recovers.",
        },
        validation_required=[
            "Downtime event review on the trailing line, by reason and duration.",
            "Maintenance and equipment condition records, which this dataset does not hold.",
        ],
    )


# --------------------------------------------------------------------- R3


def rule_r3_shift_performance_gap(df: pd.DataFrame) -> dict:
    """R3: is night running slower than day on a like-for-like mix?"""
    t = THRESHOLDS["R3"]
    raw = _prepare(df)
    annual = _annual_factor(raw)
    day = raw[raw["shift"] == "Day"]
    night = raw[raw["shift"] == "Night"]
    raw_gap = _performance_pct(day) - _performance_pct(night)

    # Mix adjustment: compare day and night inside each line and product
    # cell, then weight the cell gaps together. A raw gap caused only by a
    # different line or product mix disappears under this adjustment.
    cell_rows = []
    num = den = 0.0
    night_den_by_cell = {}
    for (line, cat), cell in raw.groupby(["line", "category"]):
        d = cell[cell["shift"] == "Day"]
        n = cell[cell["shift"] == "Night"]
        if len(d) == 0 or len(n) == 0:
            continue
        gap = _performance_pct(d) - _performance_pct(n)
        weight = float((cell["ideal_rate"] * cell["run_time_h"]).sum())
        num += weight * gap
        den += weight
        night_den_by_cell[(line, cat)] = float((n["ideal_rate"] * n["run_time_h"]).sum())
        cell_rows.append((line, cat, gap))
    adjusted_gap = num / den if den > 0 else float("nan")
    positive_cells = sum(1 for _, _, g in cell_rows if g > 0)

    problem = (
        "Compares running speed (performance) between day and night shifts. "
        "The mix of lines and products is matched first (mix adjusted). "
        f"Fires when the adjusted gap passes {t['gap_points']} percentage points."
    )
    details = [
        f"Raw gap: day runs {_r(raw_gap, 2)} points faster than night, before mix adjustment.",
        f"Mix-adjusted gap: {_r(adjusted_gap, 2)} points, weighted across {len(cell_rows)} "
        "line and product cells present on both shifts.",
    ] + [
        f"{line} {cat}: day minus night performance gap {_r(gap, 2)} points."
        for line, cat, gap in cell_rows
    ]

    if not (adjusted_gap > t["gap_points"]):
        return _finding(
            id="R3",
            title="Day against night shift performance",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"After mix adjustment the day-to-night gap is {_r(adjusted_gap, 2)} points. "
                    f"The threshold is {t['gap_points']} points. "
                    f"The raw gap of {_r(raw_gap, 2)} points is explained by what each shift ran."
                ),
                "details": details,
            },
            possible_causes=[],
            recommendation=(
                "No shift investigation justified. Any raw gap here reflects "
                "the product and line mix, not the crews."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    def close(share_pct: float) -> float:
        extra = 0.0
        for line, cat, gap in cell_rows:
            if gap <= 0:
                continue
            extra += gap / 100.0 * night_den_by_cell[(line, cat)] * share_pct / 100.0
        return extra * annual

    units_base = close(t["close_pct_base"])
    day_quality = _quality_pct(day)
    night_quality = _quality_pct(night)
    severity = "high" if adjusted_gap > t["high_severity_gap_points"] else "medium"

    return _finding(
        id="R3",
        title="Day against night shift performance",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"Night runs {_r(adjusted_gap, 2)} points slower than day after mix adjustment. "
                f"The raw gap is {_r(raw_gap, 2)} points, so mix explains little of it. "
                f"Night is slower in {positive_cells} of {len(cell_rows)} cells."
            ),
            "details": details + [
                f"Quality today: day {_r(day_quality, 2)} percent, night {_r(night_quality, 2)} percent.",
            ],
        },
        possible_causes=[
            {
                "cause": (
                    f"The gap survives mix adjustment and shows in {positive_cells} of "
                    f"{len(cell_rows)} cells. It is a shift effect, not a product effect."
                ),
                "basis": "observed",
            },
            {"cause": "Night staffing levels may be thinner. A hypothesis to check on site.", "basis": "hypothesis"},
            {"cause": "Supervision and support cover may be lighter at night. A hypothesis to check.", "basis": "hypothesis"},
            {"cause": "Training and experience may differ across crews. A hypothesis to check.", "basis": "hypothesis"},
        ],
        recommendation=(
            "Do not change staffing on this data alone. "
            "Observe night shifts directly (time and motion study). "
            "Compare crewing, supervision and call-out support against day shifts. "
            "Act on what the observation shows."
        ),
        expected_impact={
            "summary": (
                f"Closing half to all of the adjusted gap adds about {_r(close(t['close_pct_low']), 0)} "
                f"to {_r(close(t['close_pct_high']), 0)} units a year. "
                "Computed per cell from the night shifts' own run hours and nameplate rates."
            ),
            "calculations": [
                {"label": "raw day-to-night gap", "value": _r(raw_gap, 2), "unit": "points"},
                {"label": "mix-adjusted gap", "value": _r(adjusted_gap, 2), "unit": "points"},
                {"label": "extra units at base case", "value": _r(units_base, 0), "unit": "units/yr"},
            ],
            "assumptions": [
                "Only cells where day is faster contribute. Cells where night is faster are left alone.",
                "Night lifts towards day speed at an unchanged quality rate; the gate below tests that.",
                "The period analysed repeats itself over a full year.",
            ],
            "sensitivity": _sensitivity(
                close(t["close_pct_low"]), units_base, close(t["close_pct_high"]), "units/yr",
                (
                    f"Adjusted gap closed by {t['close_pct_low']:.0f} percent (low), "
                    f"{t['close_pct_base']:.0f} percent (base) and "
                    f"{t['close_pct_high']:.0f} percent (high)."
                ),
            ),
        },
        tradeoffs=(
            "Pushing night crews to run faster without fixing the real cause "
            "risks fatigue, mistakes and rejects."
        ),
        quality_gate={
            "check": (
                f"Night quality is {_r(night_quality, 2)} percent today against "
                f"{_r(day_quality, 2)} on days. "
                "Quality at the higher speed must be measured, not assumed."
            ),
            "outcome": "conditional",
            "note": "Any night speed trial must track rejects shift by shift.",
        },
        validation_required=[
            "Time and motion observation on night shifts. Observation, not assumption.",
            "Crewing, supervision and call-out records for both shifts.",
        ],
    )


# --------------------------------------------------------------------- R4


def rule_r4_maintenance_verification(df: pd.DataFrame) -> dict:
    """R4: did breakdown downtime fall after the maintenance programme start?"""
    t = THRESHOLDS["R4"]
    raw = _prepare(df)
    annual = _annual_factor(raw)
    split = pd.Timestamp(t["programme_start"])

    bdown = np.where(raw["downtime_reason"] == "Equipment breakdown", raw["downtime_h"], 0.0)
    work = raw.assign(_bdown=bdown)
    before = work[work["_date"] < split]
    after = work[work["_date"] >= split]

    problem = (
        f"Checks whether breakdown downtime fell after the {t['programme_start']} "
        "maintenance programme start. Compares breakdown hours per shift before "
        "and after, per line. Recommends extending only if the fall is clear."
    )

    if len(before) == 0 or len(after) == 0:
        return _finding(
            id="R4",
            title="Maintenance programme check (before and after 2026-07-01)",
            status="informational",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    "The record does not cover both sides of the programme start date. "
                    "No before-and-after comparison is possible."
                ),
                "details": [
                    f"Rows before {t['programme_start']}: {len(before)}. Rows after: {len(after)}.",
                ],
            },
            possible_causes=[],
            recommendation="Collect data on both sides of the start date, then rerun this check.",
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=["A record spanning the programme start date."],
        )

    # One-off events must not be credited to the programme. The single
    # worst breakdown week in the before period is set aside for the
    # decision, and both versions of the numbers are reported.
    week_hours = before.groupby("_week")["_bdown"].sum()
    worst_week = str(week_hours.idxmax())
    before_trim = before[before["_week"] != worst_week]

    def stats(sub: pd.DataFrame):
        vals = sub["_bdown"].to_numpy(dtype=float)
        return float(vals.mean()), float(vals.std(ddof=1)) if len(vals) > 1 else 0.0, len(vals)

    mb_all, _, _ = stats(before)
    mb, sb, nb = stats(before_trim)
    ma, sa, na = stats(after)
    reduction_pct = (mb - ma) / mb * 100.0 if mb > 0 else float("nan")
    se = float(np.sqrt(sb ** 2 / nb + sa ** 2 / na)) if nb and na else float("nan")
    z = (mb - ma) / se if se and se > 0 else float("nan")
    meaningful = (
        np.isfinite(z) and z >= t["z_score_floor"]
        and np.isfinite(reduction_pct) and reduction_pct >= t["meaningful_reduction_pct"]
    )

    line_details = []
    for line, sub in work.groupby("line"):
        b = sub[sub["_date"] < split]["_bdown"]
        a = sub[sub["_date"] >= split]["_bdown"]
        line_details.append(
            f"{line}: breakdown time {_r(float(b.mean()), 3)} h per shift before, "
            f"{_r(float(a.mean()), 3)} h after. "
            f"Totals: {_r(float(b.sum()), 1)} h then {_r(float(a.sum()), 1)} h."
        )

    details = line_details + [
        (
            f"The worst breakdown week, {worst_week}, is set aside for the decision "
            f"({_r(float(week_hours.max()), 1)} breakdown hours). "
            "A one-off crash must not be credited to the programme."
        ),
        (
            f"Plant level with that week included: {_r(mb_all, 3)} h per shift before, "
            f"{_r(ma, 3)} after."
        ),
        (
            f"Plant level with that week set aside: {_r(mb, 3)} h per shift before, "
            f"{_r(ma, 3)} after. That is a {_r(reduction_pct, 1)} percent fall."
        ),
        (
            f"Noise check: z = {_r(z, 2)} (floor {t['z_score_floor']:.0f}). "
            f"Materiality floor: {t['meaningful_reduction_pct']:.0f} percent."
        ),
        "This is a before-and-after comparison only. There is no control group.",
    ]

    if not meaningful:
        return _finding(
            id="R4",
            title="Maintenance programme check (before and after 2026-07-01)",
            status="informational",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"Breakdown time per shift moved from {_r(mb, 3)} to {_r(ma, 3)} hours "
                    f"({_r(reduction_pct, 1)} percent, z = {_r(z, 2)}). "
                    "The fall is not clearly beyond noise, so no extension is recommended yet."
                ),
                "details": details,
            },
            possible_causes=[
                {
                    "cause": "The before-and-after difference is within noise on this record.",
                    "basis": "observed",
                },
            ],
            recommendation=(
                "Keep the programme running as planned. "
                "The evidence is not strong enough to widen it yet. "
                "Rerun this check when more months of data exist."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[
                "A breakdown log by line, reason and duration.",
                "A rerun of this check after six more months.",
            ],
        )

    avoided_per_row = mb - ma
    rows_per_year = len(raw) * annual

    def sustained(share_pct: float) -> float:
        return avoided_per_row * rows_per_year * share_pct / 100.0

    hours_base = sustained(t["sustain_pct_base"])
    rate = _realised_rate_uph(after)
    units_base = hours_base * rate

    return _finding(
        id="R4",
        title="Maintenance programme check (before and after 2026-07-01)",
        status="action_recommended",
        severity="low",
        problem=problem,
        evidence={
            "summary": (
                f"Breakdown time per shift fell {_r(reduction_pct, 1)} percent after "
                f"{t['programme_start']}. The one-off crash week is set aside. "
                f"The fall is clear of noise (z = {_r(z, 2)}). "
                "There is no control group, so the cause is likely but not proven."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": "Breakdown hours fell on every line after the programme start.",
                "basis": "observed",
            },
            {
                "cause": (
                    "The programme is the likely cause. Other changes in the same period "
                    "could also contribute. No control group exists."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Continue the maintenance programme. Extend it to the worst remaining "
            "breakdown sources. Keep logging breakdowns by line and reason so the "
            "trend can be confirmed."
        ),
        expected_impact={
            "summary": (
                f"If the fall holds, about {_r(hours_base, 0)} breakdown hours a year stay avoided "
                f"(base case). At the current realised rate that protects about "
                f"{_r(units_base, 0)} units a year."
            ),
            "calculations": [
                {"label": "breakdown h per shift, before (worst week aside)", "value": _r(mb, 3), "unit": "h"},
                {"label": "breakdown h per shift, after", "value": _r(ma, 3), "unit": "h"},
                {"label": "observed fall", "value": _r(reduction_pct, 1), "unit": "%"},
                {"label": "noise check", "value": _r(z, 2), "unit": "z score"},
                {"label": "hours avoided per year at base case", "value": _r(hours_base, 0), "unit": "h/yr"},
            ],
            "assumptions": [
                "The observed fall is assumed to hold. The sensitivity varies how much of it holds.",
                "Protected run time produces at the plant's current realised rate.",
                "No control group exists; the comparison is before and after only.",
            ],
            "sensitivity": _sensitivity(
                sustained(t["sustain_pct_low"]), hours_base, sustained(t["sustain_pct_high"]), "h/yr",
                (
                    f"The observed fall is sustained at {t['sustain_pct_low']:.0f} percent (low), "
                    f"{t['sustain_pct_base']:.0f} percent (base) and "
                    f"{t['sustain_pct_high']:.0f} percent (high)."
                ),
            ),
        },
        tradeoffs=(
            "Planned maintenance itself takes line time. Its slots must be "
            "scheduled, not stolen from production unplanned."
        ),
        quality_gate={
            "check": (
                "Protected run time is counted at current quality rates. "
                "Normal quality tracking must confirm that."
            ),
            "outcome": "conditional",
            "note": "No speed-up is involved, so the risk is low. Tracking still applies.",
        },
        validation_required=[
            "A breakdown log by line, reason and duration, which this dataset does not break down.",
            "A rerun of this check after six more months of data.",
        ],
    )


# --------------------------------------------------------------------- R5


def rule_r5_idle_energy(df: pd.DataFrame) -> dict:
    """R5: does energy keep flowing during downtime (idle energy)?"""
    t = THRESHOLDS["R5"]
    raw = _prepare(df)
    annual = _annual_factor(raw)

    y = raw["energy_kwh"].to_numpy(dtype=float)
    X = np.column_stack([
        np.ones(len(raw)),
        raw["actual_units"].to_numpy(dtype=float),
        raw["downtime_h"].to_numpy(dtype=float),
    ])
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    resid = y - pred
    dof = max(len(raw) - X.shape[1], 1)
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se_dt = float(np.sqrt(cov[2, 2]))
    b_dt = float(coef[2])
    t_stat = b_dt / se_dt if se_dt > 0 else float("nan")
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / ss_tot if ss_tot > 0 else float("nan")

    total_dt = float(raw["downtime_h"].sum())
    annual_idle_kwh = b_dt * total_dt * annual
    annual_total_kwh = float(raw["energy_kwh"].sum()) * annual
    idle_share_pct = annual_idle_kwh / annual_total_kwh * 100.0 if annual_total_kwh > 0 else float("nan")

    problem = (
        "Separates energy that follows output from energy that flows during stops. "
        "Fits energy on units made and downtime hours (a two-regressor fit). "
        f"Fires when the downtime term passes {t['idle_kwh_per_downtime_h_floor']:.0f} kWh "
        "per downtime hour and is clear of noise."
    )
    fit_details = [
        f"Fitted on {len(raw)} shifts: energy = {_r(float(coef[0]), 1)} + "
        f"{_r(float(coef[1]), 4)} x units + {_r(b_dt, 2)} x downtime hours.",
        f"Downtime term: {_r(b_dt, 2)} kWh per downtime hour "
        f"(t = {_r(t_stat, 1)}, floor {t['t_stat_floor']:.0f}). Fit R2 = {_r(r2, 3)}.",
        (
            "Units made and downtime hours move together, so the two terms are "
            "read with care. The t statistic reports how clear the downtime term is."
        ),
    ]

    fires = (
        b_dt > t["idle_kwh_per_downtime_h_floor"]
        and np.isfinite(t_stat) and t_stat >= t["t_stat_floor"]
    )

    if not fires:
        return _finding(
            id="R5",
            title="Energy used during downtime (idle energy)",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"The downtime term is {_r(b_dt, 2)} kWh per hour (t = {_r(t_stat, 1)}). "
                    f"That is not materially above the {t['idle_kwh_per_downtime_h_floor']:.0f} kWh "
                    "floor. Idle energy is too small to chase."
                ),
                "details": fit_details,
            },
            possible_causes=[],
            recommendation=(
                "No idle-energy programme justified by this fit. "
                "Rerun the check when new data arrives."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    def avoided(share_pct: float) -> float:
        return annual_idle_kwh * share_pct / 100.0

    base_kwh = avoided(t["avoidable_pct_base"])
    severity = (
        "high" if idle_share_pct > t["high_severity_share_of_total_pct"] else "medium"
    )

    return _finding(
        id="R5",
        title="Energy used during downtime (idle energy)",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"Each downtime hour draws about {_r(b_dt, 1)} kWh while nothing is made. "
                f"Across {_r(total_dt * annual, 0)} downtime hours a year, that is about "
                f"{_r(annual_idle_kwh, 0)} kWh. "
                f"That is {_r(idle_share_pct, 2)} percent of all energy."
            ),
            "details": fit_details + [
                f"Total downtime in the record: {_r(total_dt, 1)} hours.",
                f"Annual idle energy at the fitted rate: {_r(annual_idle_kwh, 0)} kWh.",
            ],
        },
        possible_causes=[
            {
                "cause": "Energy rises with downtime hours even at the same output. The fit measures this.",
                "basis": "observed",
            },
            {
                "cause": "Motors, heaters or compressed air may keep running during stops. A hypothesis to check.",
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Write simple idle-state shutdown steps for each line. "
            "Switch defined equipment off or to standby during stops. "
            "Start with stops longer than one hour."
        ),
        expected_impact={
            "summary": (
                f"Avoiding {t['avoidable_pct_low']:.0f} to {t['avoidable_pct_high']:.0f} percent of "
                f"idle energy saves about {_r(avoided(t['avoidable_pct_low']), 0)} to "
                f"{_r(avoided(t['avoidable_pct_high']), 0)} kWh a year."
            ),
            "calculations": [
                {"label": "fitted idle draw", "value": _r(b_dt, 2), "unit": "kWh per downtime hour"},
                {"label": "annual downtime", "value": _r(total_dt * annual, 0), "unit": "h/yr"},
                {"label": "annual idle energy", "value": _r(annual_idle_kwh, 0), "unit": "kWh/yr"},
                {"label": "saving at base case", "value": _r(base_kwh, 0), "unit": "kWh/yr"},
                {"label": "idle share of all energy", "value": _r(idle_share_pct, 2), "unit": "%"},
            ],
            "assumptions": [
                "The fitted downtime term reflects real idle draw; submetering must confirm which equipment.",
                f"An assumed {t['avoidable_pct_low']:.0f} to {t['avoidable_pct_high']:.0f} percent of it can be switched off safely.",
                "The period analysed repeats itself over a full year.",
            ],
            "sensitivity": _sensitivity(
                avoided(t["avoidable_pct_low"]), base_kwh, avoided(t["avoidable_pct_high"]), "kWh/yr",
                (
                    f"Idle energy avoided at {t['avoidable_pct_low']:.0f} percent (low), "
                    f"{t['avoidable_pct_base']:.0f} percent (base) and "
                    f"{t['avoidable_pct_high']:.0f} percent (high)."
                ),
            ),
        },
        tradeoffs=(
            "Some equipment must stay on for safety or product protection. "
            "The shutdown list must respect that."
        ),
        quality_gate={
            "check": (
                "Restarting after a shutdown can scrap the first units (restart scrap). "
                "Reject rates after restarts must be measured, not assumed."
            ),
            "outcome": "conditional",
            "note": "Trial the steps on one line first and count rejects on every restart.",
        },
        validation_required=[
            "Submetering on one line to confirm the fitted idle draw, which this dataset does not hold.",
            "A shutdown trial on one line with rejects counted at every restart.",
        ],
    )


# --------------------------------------------------------------------- R6


def rule_r6_rejection_concentration(df: pd.DataFrame) -> dict:
    """R6: does one line and product cell reject far more than the rest?"""
    t = THRESHOLDS["R6"]
    raw = _prepare(df)
    annual = _annual_factor(raw)

    cells = []
    for (line, cat), cell in raw.groupby(["line", "category"]):
        if len(cell) < t["min_rows_per_cell"]:
            continue
        rest = raw[(raw["line"] != line) | (raw["category"] != cat)]
        cells.append({
            "line": line,
            "category": cat,
            "rows": len(cell),
            "rate": _rejection_pct(cell),
            "rest_rate": _rejection_pct(rest),
            "actual": float(cell["actual_units"].sum()),
        })
    cells.sort(key=lambda c: -c["rate"])

    problem = (
        "Measures the reject rate for every line and product cell. "
        "Fires when one cell sits well above the rest. Well above means at least "
        f"{t['excess_pp_floor']} points higher and at least {t['ratio_floor']} times the rest. "
        f"Cells under {t['min_rows_per_cell']} shifts are skipped as too small."
    )
    table = [
        f"{c['line']} {c['category']}: reject rate {_r(c['rate'], 2)} percent "
        f"over {c['rows']} shifts."
        for c in cells
    ]
    by_cat = {
        cat: _rejection_pct(sub) for cat, sub in raw.groupby("category")
    }
    cat_note = ". ".join(
        f"{cat} overall: {_r(rate, 2)} percent" for cat, rate in sorted(by_cat.items())
    ) + "."

    if not cells:
        return _finding(
            id="R6",
            title="Rejection concentration by line and product",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"No cell reaches the minimum size of {t['min_rows_per_cell']} shifts. "
                    "The check cannot run on this record."
                ),
                "details": [cat_note],
            },
            possible_causes=[],
            recommendation="Collect more shifts per cell, then rerun this check.",
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    top = cells[0]
    excess_pp = top["rate"] - top["rest_rate"]
    ratio = top["rate"] / top["rest_rate"] if top["rest_rate"] > 0 else float("inf")
    fires = excess_pp >= t["excess_pp_floor"] and ratio >= t["ratio_floor"]

    if not fires:
        return _finding(
            id="R6",
            title="Rejection concentration by line and product",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"No cell stands out. The highest is {top['line']} {top['category']} at "
                    f"{_r(top['rate'], 2)} percent, {_r(excess_pp, 2)} points above the rest. "
                    f"The floors are {t['excess_pp_floor']} points and {t['ratio_floor']} times."
                ),
                "details": table + [cat_note],
            },
            possible_causes=[],
            recommendation=(
                "No single-cell investigation justified. Rejects are spread evenly. "
                "Keep the cell table under monthly review."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    def close(share_pct: float) -> float:
        return excess_pp / 100.0 * top["actual"] * share_pct / 100.0 * annual

    units_base = close(t["close_pct_base"])
    severity = "high" if excess_pp >= t["high_severity_excess_pp"] else "medium"

    premium_vs_standard = None
    if {"Premium", "Standard"} <= set(by_cat):
        if by_cat["Premium"] > by_cat["Standard"]:
            premium_vs_standard = {
                "cause": (
                    f"Premium rejects more than Standard overall "
                    f"({_r(by_cat['Premium'], 2)} against {_r(by_cat['Standard'], 2)} percent). "
                    "Measured across the whole record."
                ),
                "basis": "observed",
            }

    causes = [
        {
            "cause": (
                f"{top['line']} {top['category']} rejects {_r(top['rate'], 2)} percent against "
                f"{_r(top['rest_rate'], 2)} for the rest. Measured from the rows."
            ),
            "basis": "observed",
        },
    ]
    if premium_vs_standard:
        causes.append(premium_vs_standard)
    causes += [
        {"cause": "The product may be harder to pack right in that cell. A hypothesis to check.", "basis": "hypothesis"},
        {"cause": "Set-up, materials or inspection standards may differ there. A hypothesis to check.", "basis": "hypothesis"},
    ]

    return _finding(
        id="R6",
        title="Rejection concentration by line and product",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"{top['line']} {top['category']} rejects {_r(top['rate'], 2)} percent of units. "
                f"The rest of the plant rejects {_r(top['rest_rate'], 2)} percent. "
                f"The gap is {_r(excess_pp, 2)} points ({_r(ratio, 2)} times the rest)."
            ),
            "details": table + [cat_note],
        },
        possible_causes=causes,
        recommendation=(
            f"Run a first-pass quality investigation on {top['line']} {top['category']}. "
            "Compare its set-up, materials and checks against the matching cells elsewhere."
        ),
        expected_impact={
            "summary": (
                f"Bringing that cell down to the rest rate recovers about "
                f"{_r(close(100.0), 0)} good units a year. "
                f"Closing half the gap recovers about {_r(close(t['close_pct_low']), 0)}."
            ),
            "calculations": [
                {"label": "cell reject rate", "value": _r(top["rate"], 2), "unit": "%"},
                {"label": "rest-of-plant reject rate", "value": _r(top["rest_rate"], 2), "unit": "%"},
                {"label": "excess", "value": _r(excess_pp, 2), "unit": "points"},
                {"label": "cell output in the record", "value": _r(top["actual"], 0), "unit": "units"},
                {"label": "good units recovered at base case", "value": _r(units_base, 0), "unit": "units/yr"},
            ],
            "assumptions": [
                "The cell's output volume stays as recorded.",
                "The excess over the rest-of-plant rate is removable; the investigation must show how.",
                "The period analysed repeats itself over a full year.",
            ],
            "sensitivity": _sensitivity(
                close(t["close_pct_low"]), units_base, close(t["close_pct_high"]), "units/yr",
                (
                    f"Excess closed by {t['close_pct_low']:.0f} percent (low), "
                    f"{t['close_pct_base']:.0f} percent (base) and "
                    f"{t['close_pct_high']:.0f} percent (high)."
                ),
            ),
        },
        tradeoffs=(
            "Tighter checks must not just move rejects into rework. "
            "They must not slow the line without need."
        ),
        quality_gate=None,
        validation_required=[
            "First-pass quality investigation on the flagged cell.",
            "Reject reasons by cell. This dataset counts rejects but does not say why.",
        ],
    )


# ------------------------------------------------------------------ runner


def run_advisor(df: pd.DataFrame) -> dict:
    """Run all six rules on the exported rows.

    Returns {"meta": ..., "findings": [...]} with findings ordered R1 to R6.
    The meta carries no timestamp, so the result is fully deterministic for
    a given input. The build script adds generated_at when writing JSON.
    """
    raw = _prepare(df)
    findings = [
        rule_r1_dominant_loss_cause(raw),
        rule_r2_worst_line_availability(raw),
        rule_r3_shift_performance_gap(raw),
        rule_r4_maintenance_verification(raw),
        rule_r5_idle_energy(raw),
        rule_r6_rejection_concentration(raw),
    ]
    meta = {
        "method": "deterministic rule-based analysis, rules documented in docs/ADVISOR_METHODOLOGY.md",
        "scenario_analysed": "as-run exported rows (the what-if scenario is not applied)",
        "period": {
            "start": str(raw["date"].iloc[0])[:10],
            "end": str(raw["date"].iloc[-1])[:10],
            "days": _period_days(raw),
            "rows_in_record": int(len(raw)),
        },
        "thresholds": THRESHOLDS,
        "note": (
            "findings are computed from the data on every rebuild; with different data these findings "
            "change, including to no action justified"
        ),
    }
    return {"meta": meta, "findings": findings}
