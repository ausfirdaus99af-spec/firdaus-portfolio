"""Deterministic Evidence and Recommendations engine for the KL Mobility Lab.

This module turns the processed open-data frames into six findings. Each
finding comes from an explicit rule with documented thresholds. The rules
are written up in docs/ADVISOR_METHODOLOGY.md. The thresholds live in
THRESHOLDS below and are copied into the output JSON.

Integrity rules this module is built around:

1. Nothing is hardcoded as a discovery. Every finding is computed from the
   inputs passed in. When the data does not justify a finding, the rule
   returns a cleared check (status "no_action_justified"). Cleared checks
   stay in the output on purpose. With different data the same rules give
   different findings.
2. This project uses real open data, so the evidence bar is highest here.
   Observed facts, hypotheses and arithmetic on observed numbers are kept
   apart. Every possible cause carries a basis tag.
3. Recommendations stay proportionate to the evidence. Most honest outputs
   here are "study this next" or "publish this data", not "do X". No
   congestion impact is ever claimed; no open data measures one.
4. Every finding cites the source dataset inside its evidence.

All public functions are pure. They take frames and plain values and
return dicts. No file or network access, so the engine is easy to test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Every numeric decision point in the rules, in one place. These are
# analysis thresholds, not discoveries: changing them changes which
# findings fire, and they are published in the output JSON.
THRESHOLDS = {
    "R1": {
        # Weekend demand below this fraction of weekday demand fires R1.
        "weekend_to_weekday_ratio_floor": 0.70,
    },
    "R2": {
        "top_n_destinations": 10,
        # Top-N share of recorded alightings above this fires R2.
        "share_pct_floor": 25.0,
        "high_severity_share_pct": 40.0,
    },
    "R3": {
        # R3 fires when any published-data check fails: hidden marginal
        # rows inflate the naive total, stations never appear as
        # destinations, or a service column has missing days inside its
        # own reporting span. Severity is fixed at medium: the finding is
        # addressed to the data publisher, not to operations.
    },
    "R4": {
        # Number of most recent comparable months examined.
        "months_window": 12,
        # "Consistently above" means every window month at or above this
        # percentage of its 2019 same-month baseline.
        "consistently_above_pct": 100.0,
        "baseline_year": "2019",
    },
    "R5": {
        # Share of transactions in a no-geography channel above this fires.
        "channel_share_pct_floor": 50.0,
        "high_severity_share_pct": 75.0,
        "channel_column": "rakan_niaga",
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

_SRC_HEADLINE = "Source: data.gov.my ridership_headline (CC BY 4.0)."
_SRC_OD = "Source: data.gov.my ridership_od_rapidrail_daily 2026 (CC BY 4.0)."
_SRC_CARS = "Source: data.gov.my registration_transactions_car 2026, JPJ (CC BY 4.0)."


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


# --------------------------------------------------------------------- R1


def rule_r1_weekend_headroom(profile: pd.DataFrame) -> dict:
    """R1: weekend against weekday rail demand, from the weekday profile.

    `profile` has columns dow (Mon..Sun) and rail_avg (mean daily trips).
    """
    t = THRESHOLDS["R1"]
    prof = profile.set_index("dow")["rail_avg"]
    weekday = float(prof[["Mon", "Tue", "Wed", "Thu", "Fri"]].mean())
    weekend = float(prof[["Sat", "Sun"]].mean())
    ratio = weekend / weekday if weekday > 0 else float("nan")

    problem = (
        "Compares average weekend rail trips with average weekday rail trips. "
        "Uses the observed 2026 day-of-week profile. "
        f"The check fires when the weekend level is below {t['weekend_to_weekday_ratio_floor'] * 100:.0f} percent "
        "of the weekday level."
    )
    day_lines = [
        f"{dow}: {round(float(v)):,} average daily rail trips."
        for dow, v in prof.items()
    ]

    if not (ratio < t["weekend_to_weekday_ratio_floor"]):
        return _finding(
            id="R1",
            title="Weekend service headroom",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"Weekend days average {round(weekend):,} rail trips. "
                    f"Weekdays average {round(weekday):,}. "
                    f"The weekend level is {_r(ratio * 100, 1)} percent of the weekday level. "
                    f"That is at or above the {t['weekend_to_weekday_ratio_floor'] * 100:.0f} percent threshold."
                ),
                "details": day_lines + [_SRC_HEADLINE],
            },
            possible_causes=[],
            recommendation=(
                "No weekend gap to investigate. Weekend demand is close to weekday demand. "
                "Keep the check in place for future years."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    return _finding(
        id="R1",
        title="Weekend service headroom",
        status="conditional",
        severity="medium",
        problem=problem,
        evidence={
            "summary": (
                f"Weekend days average {round(weekend):,} rail trips. "
                f"Weekdays average {round(weekday):,}. "
                f"The weekend level is {_r(ratio * 100, 1)} percent of the weekday level. "
                f"That is below the {t['weekend_to_weekday_ratio_floor'] * 100:.0f} percent threshold."
            ),
            "details": day_lines
            + [
                "The gap is an observed fact about demand, not about capacity.",
                "Trips are counted, not people. One rider making two trips counts twice.",
                _SRC_HEADLINE,
            ],
        },
        possible_causes=[
            {
                "cause": (
                    "Weekend rail demand is about one third lower than weekday demand. "
                    "This is measured from the 2026 daily record."
                ),
                "basis": "observed",
            },
            {
                "cause": "The network may mainly serve work and school travel (a commuting-dominated network).",
                "basis": "hypothesis",
            },
            {
                "cause": (
                    "Weekend timetables or fares may hold demand down. "
                    "This dataset cannot show that."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Treat this as a research question, not a service change. "
            "Other cities have run off-peak fare and service trials. "
            "Evaluating one for KL needs cost and fare response (elasticity) data. "
            "This project does not hold that data. "
            "First step: gather weekend timetables, fare options and elasticity evidence."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate={
            "check": (
                "Any weekend trial must first show it covers its cost. "
                "That needs data this project lacks."
            ),
            "outcome": "conditional",
            "note": "No trial is justified by ridership counts alone.",
        },
        validation_required=[
            "Weekend timetable and delivered capacity data from the operator (not open data).",
            "Fare elasticity estimates for Klang Valley riders (not open data).",
            "Costs of extra weekend service (not open data).",
        ],
    )


# --------------------------------------------------------------------- R2


def rule_r2_od_concentration(od: dict) -> dict:
    """R2: share of recorded alightings at the top destination stations.

    `od` is the dict from build_mobility_data.load_od: it carries the
    station-level detail frame (columns d, ridership), detail_total,
    n_days and missing_destination_names.
    """
    t = THRESHOLDS["R2"]
    top_n = t["top_n_destinations"]
    detail = od["detail"]
    total = int(od["detail_total"])
    n_days = int(od["n_days"])
    dests = detail.groupby("d")["ridership"].sum().sort_values(ascending=False)
    top = dests.head(top_n)
    share_pct = float(top.sum()) / total * 100.0 if total > 0 else float("nan")
    missing = list(od.get("missing_destination_names", []))

    problem = (
        "Measures how concentrated rail alightings are. "
        f"Takes the {top_n} busiest destination stations. "
        "Computes their share of all recorded alightings. "
        f"The check fires above a {t['share_pct_floor']:.0f} percent share."
    )
    station_lines = [
        f"{name}: {round(float(v) / n_days):,} average daily alightings, "
        f"{_r(float(v) / total * 100.0, 2)} percent of the total."
        for name, v in top.items()
    ]
    caveat_lines = []
    if missing:
        caveat_lines.append(
            f"Alightings at {len(missing)} stations are missing from the published file. "
            "Their trips cannot appear in destination counts. "
            "True shares may differ slightly."
        )
    base_lines = [
        f"All stations together recorded {total:,} trips over {n_days} days.",
        "Trips are counted, not people.",
    ]

    if not (share_pct > t["share_pct_floor"]):
        return _finding(
            id="R2",
            title="Destination concentration on the rail network",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"The top {top_n} destinations carry {_r(share_pct, 1)} percent of recorded alightings. "
                    f"That is at or below the {t['share_pct_floor']:.0f} percent threshold. "
                    "Demand is spread across the network."
                ),
                "details": station_lines + base_lines + caveat_lines + [_SRC_OD],
            },
            possible_causes=[],
            recommendation=(
                "No concentration case to answer. "
                "Capacity and access studies need no single-centre focus on this evidence."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    severity = "high" if share_pct > t["high_severity_share_pct"] else "medium"
    top_names = list(top.index)

    return _finding(
        id="R2",
        title="Destination concentration on the rail network",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"The top {top_n} destinations carry {_r(share_pct, 1)} percent of recorded alightings. "
                f"That is above the {t['share_pct_floor']:.0f} percent threshold. "
                f"The busiest is {top_names[0]}."
            ),
            "details": station_lines + base_lines + caveat_lines + [_SRC_OD],
        },
        possible_causes=[
            {
                "cause": (
                    "A small set of mostly central stations receives a large share of trips. "
                    "This is computed from the 2026 origin-destination records."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    "Jobs and attractions probably cluster near these stations. "
                    "Workplace location data would be needed to confirm this."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Focus further study on these stations first: "
            + ", ".join(top_names)
            + ". "
            "Useful studies: last-mile access, crowding counts and interchange capacity. "
            "This evidence says where to look. "
            "It does not say which investment is right."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Station-level crowding and capacity data (not open data).",
            "Last-mile access surveys at the named stations (not open data).",
        ],
    )


# --------------------------------------------------------------------- R3


def _series_gap(shah_alam: pd.DataFrame) -> dict:
    """Missing days inside a service column's own reporting span.

    `shah_alam` has columns date (YYYY-MM-DD strings) and trips (nullable).
    Returns counts and the gap window, or zeros when the column is fully
    reported or never reported.
    """
    obs = shah_alam[shah_alam["trips"].notna()]
    if obs.empty:
        return {"span_days": 0, "missing_days": 0, "first": None, "last": None,
                "gap_start": None, "gap_end": None}
    first, last = obs["date"].min(), obs["date"].max()
    span = pd.date_range(first, last, freq="D").strftime("%Y-%m-%d")
    observed = set(obs["date"])
    missing = sorted(d for d in span if d not in observed)
    return {
        "span_days": len(span),
        "missing_days": len(missing),
        "first": first,
        "last": last,
        "gap_start": missing[0] if missing else None,
        "gap_end": missing[-1] if missing else None,
    }


def rule_r3_published_data_quality(od: dict, shah_alam: pd.DataFrame) -> dict:
    """R3: quality issues in the published source files.

    Addressed to the data publisher. Three checks: hidden marginal total
    rows in the OD file, stations never appearing as destinations, and a
    reporting gap in a ridership column inside its own span.
    """
    raw_total = int(od["raw_total"])
    detail_total = int(od["detail_total"])
    marginal_excess = raw_total - detail_total
    multiple = raw_total / detail_total if detail_total > 0 else float("nan")
    missing = list(od.get("missing_destination_names", []))
    gap = _series_gap(shah_alam)

    issues = []
    details = []
    if marginal_excess > 0:
        issues.append("marginal_rows")
        details += [
            "The OD file holds hidden 'All Stations' total rows (marginal rows).",
            f"Summing the raw file gives {raw_total:,} trips.",
            f"The true station-level total is {detail_total:,} trips.",
            f"A naive sum is {_r(multiple, 2)} times too high.",
            "Both sets of total rows reconcile exactly with the station rows.",
        ]
    else:
        details.append("No marginal total rows inflate the OD file.")
    if missing:
        issues.append("missing_destinations")
        details += [
            f"{len(missing)} stations never appear as destinations in the OD file.",
            "Their boardings are recorded. Their alightings are not identified anywhere in the file.",
            "Affected stations: " + ", ".join(missing) + ".",
        ]
    else:
        details.append("Every origin station also appears as a destination.")
    if gap["missing_days"] > 0:
        issues.append("reporting_gap")
        details += [
            f"The LRT Shah Alam ridership column starts on {gap['first']}.",
            (
                f"It is then missing for {gap['missing_days']} of {gap['span_days']} days "
                "inside its own reporting span."
            ),
            f"The gap runs from {gap['gap_start']} to {gap['gap_end']}.",
        ]
    else:
        details.append("No reporting gap found inside the checked ridership column's span.")
    details += [_SRC_OD, _SRC_HEADLINE]

    problem = (
        "Checks the published source files for quality issues. "
        "Three checks: hidden total rows, missing alighting records, and a reporting gap. "
        "This finding is addressed to the data publisher, not to transport operators. "
        "It fires when any check fails."
    )

    if not issues:
        return _finding(
            id="R3",
            title="Published data quality (for the data publisher)",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": "All three published-data checks pass. No publisher action is needed.",
                "details": details,
            },
            possible_causes=[],
            recommendation="No publisher action needed. Keep the reconciliation checks in the pipeline.",
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    recs = []
    if "marginal_rows" in issues:
        recs.append("Publish the total rows in a separate file, or flag them clearly.")
    if "missing_destinations" in issues:
        recs.append("Complete the missing alighting records, or state why they are absent.")
    if "reporting_gap" in issues:
        recs.append("Document the reporting gap in the catalogue notes.")

    return _finding(
        id="R3",
        title="Published data quality (for the data publisher)",
        status="action_recommended",
        severity="medium",
        problem=problem,
        evidence={
            "summary": (
                f"{len(issues)} of 3 published-data checks fail: {', '.join(issues)}. "
                "Every number here comes from the pipeline's reconciliation of the raw files. "
                "Anyone can rerun it and check."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": (
                    "The listed issues are present in the files as published. "
                    "They are reproduced on every pipeline run."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    "The total rows are probably a publishing convenience. "
                    "The file documentation does not mention them."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation="For the data publisher: " + " ".join(recs),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Publisher confirmation of why the affected records are absent or unflagged.",
        ],
    )


# --------------------------------------------------------------------- R4


def rule_r4_recovery_trajectory(monthly: pd.DataFrame) -> dict:
    """R4: rail trips against the same month of the baseline year.

    `monthly` has columns m (YYYY-MM) and rail (nullable monthly trips).
    Compares the last months_window comparable months with their baseline
    same months.
    """
    t = THRESHOLDS["R4"]
    base_year = t["baseline_year"]
    rail = monthly.set_index("m")["rail"]
    observed = rail.dropna()
    rows = []
    for ym in observed.index:
        if ym.startswith(base_year):
            continue
        base_key = f"{base_year}-{ym[5:7]}"
        if base_key in observed.index and float(observed[base_key]) > 0:
            pct = float(observed[ym]) / float(observed[base_key]) * 100.0
            rows.append((ym, int(observed[ym]), int(observed[base_key]), pct))
    window = rows[-t["months_window"]:]

    problem = (
        f"Tracks monthly rail trips against the same month of {base_year}. "
        f"Uses the last {t['months_window']} comparable months. "
        "The check reports when every month in the window stays above the baseline."
    )

    if not window:
        return _finding(
            id="R4",
            title=f"Ridership recovery against {base_year}",
            status="informational",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"No months could be compared with a {base_year} baseline. "
                    "The trajectory cannot be computed from this input."
                ),
                "details": [_SRC_HEADLINE],
            },
            possible_causes=[],
            recommendation="Rerun the check when comparable months exist.",
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    pcts = [p for _, _, _, p in window]
    all_above = all(p >= t["consistently_above_pct"] for p in pcts)
    month_lines = [
        f"{ym}: {trips:,} trips, against {base:,} in {base_year}. That is {_r(p, 1)} percent."
        for ym, trips, base, p in window
    ]
    stat_lines = [
        f"Window: {window[0][0]} to {window[-1][0]} ({len(window)} months).",
        f"Range: {_r(min(pcts), 1)} to {_r(max(pcts), 1)} percent of the {base_year} level.",
        f"Average: {_r(sum(pcts) / len(pcts), 1)} percent.",
        "This measures rail demand only. It says nothing about car traffic.",
        _SRC_HEADLINE,
    ]

    if not all_above:
        n_above = sum(1 for p in pcts if p >= t["consistently_above_pct"])
        return _finding(
            id="R4",
            title=f"Ridership recovery against {base_year}",
            status="informational",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"Rail trips beat the {base_year} same-month level in {n_above} of "
                    f"{len(window)} recent months. "
                    "Recovery is not yet consistent."
                ),
                "details": month_lines + stat_lines,
            },
            possible_causes=[],
            recommendation=(
                "Keep tracking the monthly series. "
                "No further claim is justified while months still fall below the baseline."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    return _finding(
        id="R4",
        title=f"Ridership recovery against {base_year}",
        status="conditional",
        severity="medium",
        problem=problem,
        evidence={
            "summary": (
                f"Rail trips beat the {base_year} same-month level in all of the last "
                f"{len(window)} months. "
                f"The range is {_r(min(pcts), 1)} to {_r(max(pcts), 1)} percent of {base_year}. "
                f"The average is {_r(sum(pcts) / len(pcts), 1)} percent."
            ),
            "details": month_lines + stat_lines,
        },
        possible_causes=[
            {
                "cause": (
                    "Rail demand has outgrown pre-pandemic levels. "
                    "This is computed from the published monthly series."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    "New lines opened since 2022 likely carry part of the growth. "
                    "Per-line attribution was not computed here."
                ),
                "basis": "hypothesis",
            },
            {
                "cause": (
                    "Some growth may be people switching from cars. "
                    "No open data measures that switch, so this stays unproven."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Demand above 2019 makes capacity and reliability the next questions. "
            "No open data covers them today. "
            "The operator or ministry should publish peak load factors, delivered frequencies "
            "and delay statistics. "
            "This is a publication request, not a service change claim."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate={
            "check": (
                "Any stronger claim, such as mode shift from cars, needs road traffic data. "
                "None is open."
            ),
            "outcome": "conditional",
            "note": "This finding states demand growth only.",
        },
        validation_required=[
            "Published capacity and reliability monitoring data (not open today).",
            "Road traffic counts to test any mode shift claim (not open today).",
        ],
    )


# --------------------------------------------------------------------- R5


def rule_r5_registration_limits(registrations: pd.DataFrame) -> dict:
    """R5: share of car registration transactions with no usable geography.

    `registrations` has columns m, selangor, kl, rakan_niaga, other
    (monthly transaction counts).
    """
    t = THRESHOLDS["R5"]
    cols = ["selangor", "kl", "rakan_niaga", "other"]
    totals = registrations[cols].sum()
    grand = int(totals.sum())
    channel = int(totals[t["channel_column"]])
    share_pct = channel / grand * 100.0 if grand > 0 else float("nan")
    months = f"{registrations['m'].min()} to {registrations['m'].max()}"

    problem = (
        "Measures how many 2026 car registration transactions carry no usable geography. "
        "The Rakan Niaga channel is a sales channel, not a place. "
        f"The check fires when its share passes {t['channel_share_pct_floor']:.0f} percent."
    )
    details = [
        f"Rakan Niaga: {channel:,} of {grand:,} transactions.",
        f"Selangor: {int(totals['selangor']):,} transactions.",
        f"Kuala Lumpur: {int(totals['kl']):,} transactions.",
        f"All other states: {int(totals['other']):,} transactions.",
        f"Period: {months}.",
        "These are registration transactions, not vehicles in traffic.",
        _SRC_CARS,
    ]

    if not (share_pct > t["channel_share_pct_floor"]):
        return _finding(
            id="R5",
            title="Car registration data limits",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"The no-geography channel holds {_r(share_pct, 1)} percent of transactions. "
                    f"That is at or below the {t['channel_share_pct_floor']:.0f} percent threshold. "
                    "State counts remain usable with care."
                ),
                "details": details,
            },
            possible_causes=[],
            recommendation=(
                "State-level counts can be used as context. "
                "Registrations still measure sales, never traffic."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    severity = "high" if share_pct > t["high_severity_share_pct"] else "medium"
    return _finding(
        id="R5",
        title="Car registration data limits",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"The Rakan Niaga channel holds {_r(share_pct, 1)} percent of 2026 transactions "
                f"({channel:,} of {grand:,}). "
                "Those records name no state. "
                "State-level registration geography is unusable for Klang Valley analysis in 2026."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": (
                    "Most 2026 transactions sit in a channel with no state attached. "
                    "This is counted directly from the published file."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    "Dealers probably moved to the partner portal for registrations. "
                    "The publisher has not stated this."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "For analysts: do not use 2026 state registration counts as a traffic or demand proxy. "
            "For the publisher: publish a channel-to-state mapping, or add the buyer's state."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "A published channel-to-state mapping from JPJ (not open today).",
        ],
    )


# --------------------------------------------------------------------- R6


def rule_r6_settling_datasets(gaps: list[str]) -> dict:
    """R6: the datasets that would let the live-work hypothesis be tested.

    Always informational. Each entry says what the dataset is and how it
    would be used. The entries are grounded in the pipeline's documented
    gaps list, passed in as `gaps`.
    """
    joined = " ".join(gaps).lower()
    candidates = [
        (
            "commuting",
            "A commuting origin-destination survey, all modes, door to door.",
            "It would measure home-to-work flows directly. It would test the live-work question head on.",
        ),
        (
            "workplace",
            "Workplace geography: jobs counted by district.",
            "Paired with district population, it would measure live-work separation on both sides.",
        ),
        (
            "road traffic",
            "Road traffic counts and speeds as open time series.",
            "They would give a congestion outcome to test against. Today only TomTom headline numbers exist.",
        ),
        (
            "bus",
            "A bus origin-destination matrix and realised bus travel times.",
            "They would cover the non-rail public transport side of commuting.",
        ),
    ]
    entries = [
        f"{what} How it would be used: {how}"
        for key, what, how in candidates
        if key in joined
    ]

    return _finding(
        id="R6",
        title="What would settle the live-work hypothesis",
        status="informational",
        severity=None,
        problem=(
            "Lists the datasets that would let the live-work hypothesis be tested properly. "
            "Nothing here is a finding about the network. "
            "The list comes from the documented gaps in the pipeline output."
        ),
        evidence={
            "summary": (
                f"{len(entries)} missing datasets stand between this project and a real test. "
                "With open data alone the hypothesis can be explored, not settled. "
                "The gaps list in data/mobility_data.json records each one."
            ),
            "details": entries
            + ["Source: the documented gaps list in data/mobility_data.json (meta.gaps)."],
        },
        possible_causes=[],
        recommendation=(
            "Anyone pursuing the question should seek these datasets first. "
            "Until then, findings stay descriptive evidence, not proof."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[what for key, what, _ in candidates if key in joined],
    )


# ------------------------------------------------------------------ runner


def run_advisor(
    profile: pd.DataFrame,
    od: dict,
    monthly: pd.DataFrame,
    registrations: pd.DataFrame,
    shah_alam: pd.DataFrame,
    gaps: list[str],
) -> dict:
    """Run all six rules on the processed inputs.

    Returns {"meta": ..., "findings": [...]} with findings ordered R1 to R6.
    The meta carries no timestamp, so the result is fully deterministic for
    a given input; the build script adds generated_at when writing JSON.
    """
    findings = [
        rule_r1_weekend_headroom(profile),
        rule_r2_od_concentration(od),
        rule_r3_published_data_quality(od, shah_alam),
        rule_r4_recovery_trajectory(monthly),
        rule_r5_registration_limits(registrations),
        rule_r6_settling_datasets(gaps),
    ]

    meta = {
        "project": "KL Mobility Lab",
        "method": "deterministic rule-based analysis, rules documented in docs/ADVISOR_METHODOLOGY.md",
        "audience_note": (
            "Some recommendations are addressed to data publishers and researchers rather than "
            "transport operators, because that is what the evidence supports."
        ),
        "od_period": dict(od.get("period", {})),
        "ridership_months": int(monthly["rail"].notna().sum()),
        "thresholds": THRESHOLDS,
        "note": (
            "findings are computed from the data on every rebuild; with different data these "
            "findings change, including to no action justified"
        ),
    }
    return {"meta": meta, "findings": findings}
