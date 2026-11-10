"""Tests for the Operations Improvement Advisor.

The negative cases matter as much as the positive ones: every rule is
tested both where it should fire and where it should return a cleared
check, proving the findings follow the data rather than being hardcoded.
"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import advisor
import build_advisor
import build_mfg_data as build_mod
from generate_data import generate

REASONS = [
    "Changeover", "Equipment breakdown", "Material shortage",
    "Cleaning", "Quality stop",
]
IDEALS = {
    "Line A": {"Standard": 1000, "Premium": 900},
    "Line B": {"Standard": 1100, "Premium": 950},
}


# ------------------------------------------------------------- fixtures


def make_frame(
    days: int = 60,
    lines=("Line A", "Line B"),
    start: date = date(2026, 1, 5),  # a Monday, so weeks align
    seed: int = 0,
    perf: dict | None = None,       # {(line, shift): factor}, default 0.92
    quality: dict | None = None,    # {(line, category): rate}, default 0.97
    downtime=None,                  # callable(d, d_index, i, line, shift) -> (reason, hours)
    idle_kwh_per_h: float = 0.0,    # energy added per downtime hour
    category_for=None,              # callable(d_index, line, shift) -> category
) -> pd.DataFrame:
    """A small, well-formed production frame with deterministic noise.

    The default downtime cycles the five reasons evenly, with hours that
    depend only on the day, so no cause dominates (R1 clears) and every
    line has identical availability (R2 clears). Day and night run at the
    same speed by default (R3 clears).
    """
    perf = perf or {}
    quality = quality or {}
    rng = np.random.default_rng(seed)
    records = []
    i = 0
    for d_index in range(days):
        d = start + timedelta(days=d_index)
        for line in lines:
            for shift in ("Day", "Night"):
                cat = category_for(d_index, line, shift) if category_for else "Standard"
                ideal = IDEALS.get(line, IDEALS["Line A"])[cat]
                if downtime:
                    reason, dt = downtime(d, d_index, i, line, shift)
                else:
                    reason = REASONS[i % 5]
                    dt = 0.2 + 0.2 * (d_index % 4)
                rt = 7.5 - dt
                p = perf.get((line, shift), 0.92) + rng.normal(0.0, 0.005)
                act = int(round(ideal * rt * p))
                q = quality.get((line, cat), 0.97) + rng.normal(0.0, 0.002)
                good = min(int(round(act * q)), act)
                kwh = 150.0 + 0.35 * act + idle_kwh_per_h * dt + rng.normal(0.0, 3.0)
                records.append({
                    "date": d.isoformat(),
                    "line": line,
                    "shift": shift,
                    "category": cat,
                    "planned_units": int(round(ideal * 7.5 * 0.92)),
                    "actual_units": act,
                    "good_units": good,
                    "rejected_units": act - good,
                    "planned_time_h": 7.5,
                    "run_time_h": rt,
                    "downtime_h": dt,
                    "downtime_reason": reason,
                    "energy_kwh": kwh,
                    "ideal_rate": ideal,
                })
                i += 1
    return pd.DataFrame.from_records(records)


@pytest.fixture(scope="module")
def real_df():
    """The exported rows the advisor actually runs on."""
    path = Path(__file__).resolve().parents[1] / "data" / "mfg_data.json"
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    else:
        rows = build_mod.export_rows(generate())
    return build_mod.rows_to_df(rows)


@pytest.fixture(scope="module")
def real_result(real_df):
    return advisor.run_advisor(real_df)


def _get(result, rule_id):
    return next(f for f in result["findings"] if f["id"] == rule_id)


# ------------------------------------------------------------------- R1


def test_r1_changeover_dominance_fires_with_smed_advice():
    def dt(d, d_index, i, line, shift):
        reason = REASONS[i % 5]
        return reason, 2.0 if reason == "Changeover" else 0.3
    finding = advisor.rule_r1_dominant_loss_cause(make_frame(downtime=dt))
    assert finding["status"] == "action_recommended"
    assert finding["severity"] == "high"  # 62.5 percent share
    assert "Changeover" in finding["evidence"]["summary"]
    assert "SMED" in finding["recommendation"]
    impact = finding["expected_impact"]
    assert impact["sensitivity"]["low"] < impact["sensitivity"]["base"] < impact["sensitivity"]["high"]
    assert impact["sensitivity"]["unit"] == "units/yr"
    # Plan achievement gain is computed and positive.
    gain = next(c["value"] for c in impact["calculations"]
                if c["label"] == "plan achievement gain at base case")
    assert gain > 0
    bases = {c["basis"] for c in finding["possible_causes"]}
    assert bases == {"observed", "hypothesis"}


def test_r1_breakdown_dominance_recommends_planned_maintenance():
    def dt(d, d_index, i, line, shift):
        reason = REASONS[i % 5]
        return reason, 2.0 if reason == "Equipment breakdown" else 0.3
    finding = advisor.rule_r1_dominant_loss_cause(make_frame(downtime=dt))
    assert finding["status"] == "action_recommended"
    assert "planned maintenance" in finding["recommendation"]


def test_r1_even_spread_is_cleared():
    finding = advisor.rule_r1_dominant_loss_cause(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["severity"] is None
    assert finding["expected_impact"] is None


def test_r1_impact_uses_affected_rows_own_rates():
    """The impact must come from the affected rows, not a fixed percentage."""
    def dt(d, d_index, i, line, shift):
        reason = REASONS[i % 5]
        return reason, 2.0 if reason == "Changeover" else 0.3
    frame = make_frame(downtime=dt)
    finding = advisor.rule_r1_dominant_loss_cause(frame)
    affected = frame[frame["downtime_reason"] == "Changeover"]
    rate = affected["actual_units"] / affected["run_time_h"]
    expected_base = float((affected["downtime_h"] * 0.40 * rate).sum()) * (365.0 / 60.0)
    got = next(c["value"] for c in finding["expected_impact"]["calculations"]
               if c["label"] == "extra units at base case")
    assert got == pytest.approx(expected_base, rel=0.01)


# ------------------------------------------------------------------- R2


def test_r2_large_gap_fires_with_gate_and_sensitivity():
    def dt(d, d_index, i, line, shift):
        if line == "Line B":
            return "Equipment breakdown", 1.5
        return "Cleaning", 0.4
    finding = advisor.rule_r2_worst_line_availability(make_frame(downtime=dt))
    assert finding["status"] == "action_recommended"
    assert finding["severity"] == "high"  # gap near 14.7 points
    assert "Line B" in finding["evidence"]["summary"]
    impact = finding["expected_impact"]
    assert impact["sensitivity"]["low"] < impact["sensitivity"]["base"] < impact["sensitivity"]["high"]
    assert impact["sensitivity"]["unit"] == "units/yr"
    assert finding["quality_gate"]["outcome"] != "passes"


def test_r2_separates_crash_week_from_chronic_gap():
    def dt(d, d_index, i, line, shift):
        if line == "Line B":
            if 7 <= d_index <= 13:  # one full calendar week crashes
                return "Equipment breakdown", 5.0
            return "Equipment breakdown", 0.9
        return "Cleaning", 0.4
    frame = make_frame(downtime=dt)
    finding = advisor.rule_r2_worst_line_availability(frame)
    assert finding["status"] == "action_recommended"
    calcs = {c["label"]: c["value"] for c in finding["expected_impact"]["calculations"]}
    chronic = calcs["Line B chronic gap"]
    full_gap = (
        frame[frame["line"] == "Line A"]["run_time_h"].sum()
        - frame[frame["line"] == "Line B"]["run_time_h"].sum()
    ) / frame[frame["line"] == "Line A"]["planned_time_h"].sum() * 100.0
    # The chronic gap excludes the crash week, so it is clearly smaller.
    assert chronic < full_gap - 1.0
    # The steady-state gap is (0.9 - 0.4) / 7.5 = 6.67 points.
    assert chronic == pytest.approx(6.67, abs=0.2)


def test_r2_equal_lines_cleared_but_both_numbers_still_reported():
    finding = advisor.rule_r2_worst_line_availability(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["expected_impact"] is None
    # The cleared check still separates the chronic gap from the worst week.
    assert any("chronic gap" in d for d in finding["evidence"]["details"])


# ------------------------------------------------------------------- R3


def test_r3_real_shift_gap_fires_with_hypotheses_and_gate():
    perf = {}
    for line in ("Line A", "Line B"):
        perf[(line, "Day")] = 0.95
        perf[(line, "Night")] = 0.91
    finding = advisor.rule_r3_shift_performance_gap(make_frame(perf=perf))
    assert finding["status"] == "action_recommended"
    assert finding["severity"] == "high"  # about 4 points
    # Staffing talk is framed as hypothesis, validated by observation.
    hyp = [c["cause"].lower() for c in finding["possible_causes"] if c["basis"] == "hypothesis"]
    assert any("staffing" in c for c in hyp)
    assert any("time and motion" in v.lower() for v in finding["validation_required"])
    assert finding["quality_gate"]["outcome"] == "conditional"
    impact = finding["expected_impact"]
    assert impact["sensitivity"]["low"] < impact["sensitivity"]["base"] < impact["sensitivity"]["high"]


def test_r3_pure_mix_gap_must_clear():
    """Raw gap built only from product mix: the adjustment must remove it."""
    perf = {}
    for line in ("Line A", "Line B"):
        for shift in ("Day", "Night"):
            perf[(line, shift)] = 0.92  # same speed day and night in every cell

    def category_for(d_index, line, shift):
        # Line B: day mostly Standard (fast cell), night mostly Premium.
        if line != "Line B":
            return "Standard"
        if shift == "Day":
            return "Premium" if d_index % 5 == 0 else "Standard"
        return "Standard" if d_index % 5 == 0 else "Premium"

    # Premium runs slower in absolute units but the same against nameplate,
    # so make the Premium cells genuinely slower against nameplate too.
    perf[("Line B", "Day")] = 0.92
    perf[("Line B", "Night")] = 0.92
    frame = make_frame(days=100, category_for=category_for)
    # Premium rows run slower against nameplate, identically on both shifts.
    premium = frame["category"] == "Premium"
    frame.loc[premium, "actual_units"] = (
        frame.loc[premium, "actual_units"] * 0.90
    ).round().astype(int)
    frame.loc[premium, "good_units"] = np.minimum(
        frame.loc[premium, "good_units"], frame.loc[premium, "actual_units"]
    )
    frame.loc[premium, "rejected_units"] = (
        frame.loc[premium, "actual_units"] - frame.loc[premium, "good_units"]
    )

    # The raw gap is real and above the threshold...
    raw = advisor._prepare(frame)
    day = raw[raw["shift"] == "Day"]
    night = raw[raw["shift"] == "Night"]
    raw_gap = advisor._performance_pct(day) - advisor._performance_pct(night)
    assert raw_gap > advisor.THRESHOLDS["R3"]["gap_points"]
    # ...but it is pure mix, so the mix-adjusted rule must clear.
    finding = advisor.rule_r3_shift_performance_gap(frame)
    assert finding["status"] == "no_action_justified"


def test_r3_no_gap_is_cleared():
    finding = advisor.rule_r3_shift_performance_gap(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["severity"] is None


# ------------------------------------------------------------------- R4


def _r4_frame(improved: bool) -> pd.DataFrame:
    split = date(2026, 7, 1)

    def dt(d, d_index, i, line, shift):
        if improved and d >= split:
            return "Equipment breakdown", 0.15 + 0.1 * (d_index % 2)
        return "Equipment breakdown", 0.5 + 0.2 * (d_index % 2)

    return make_frame(days=120, start=date(2026, 5, 1), downtime=dt)


def test_r4_observed_improvement_recommends_extension():
    finding = advisor.rule_r4_maintenance_verification(_r4_frame(improved=True))
    assert finding["status"] == "action_recommended"
    assert "continue" in finding["recommendation"].lower()
    assert "extend" in finding["recommendation"].lower()
    # The check acknowledges there is no control group.
    assert any("control group" in d.lower() for d in finding["evidence"]["details"])
    impact = finding["expected_impact"]
    assert impact["sensitivity"]["unit"] == "h/yr"
    assert impact["sensitivity"]["low"] < impact["sensitivity"]["base"] < impact["sensitivity"]["high"]


def test_r4_flips_to_informational_when_improvement_removed():
    finding = advisor.rule_r4_maintenance_verification(_r4_frame(improved=False))
    assert finding["status"] == "informational"
    assert "extend" not in finding["recommendation"].lower()
    assert finding["expected_impact"] is None


def test_r4_informational_when_record_misses_the_start_date():
    frame = make_frame(days=30, start=date(2026, 1, 5))  # all before 2026-07-01
    finding = advisor.rule_r4_maintenance_verification(frame)
    assert finding["status"] == "informational"
    assert finding["expected_impact"] is None


# ------------------------------------------------------------------- R5


def test_r5_idle_draw_fires_with_restart_scrap_gate():
    finding = advisor.rule_r5_idle_energy(make_frame(idle_kwh_per_h=30.0))
    assert finding["status"] == "action_recommended"
    # The fitted coefficient recovers the constructed 30 kWh per hour.
    coef = next(c["value"] for c in finding["expected_impact"]["calculations"]
                if c["label"] == "fitted idle draw")
    assert 25.0 < coef < 35.0
    assert "restart" in finding["quality_gate"]["check"].lower()
    assert finding["quality_gate"]["outcome"] == "conditional"
    sens = finding["expected_impact"]["sensitivity"]
    assert sens["low"] < sens["base"] < sens["high"]
    assert sens["unit"] == "kWh/yr"


def test_r5_no_idle_draw_is_cleared():
    finding = advisor.rule_r5_idle_energy(make_frame(idle_kwh_per_h=0.0))
    assert finding["status"] == "no_action_justified"
    assert finding["expected_impact"] is None
    # The cleared check still reports the fitted values.
    assert any("Downtime term" in d for d in finding["evidence"]["details"])


# ------------------------------------------------------------------- R6


def test_r6_hot_cell_fires_with_computed_impact():
    frame = make_frame(quality={("Line B", "Standard"): 0.94})
    finding = advisor.rule_r6_rejection_concentration(frame)
    assert finding["status"] == "action_recommended"
    assert finding["severity"] == "high"  # about 3 points excess
    assert "Line B Standard" in finding["evidence"]["summary"]
    assert any("first-pass quality" in v.lower() for v in finding["validation_required"])
    impact = finding["expected_impact"]
    assert impact["sensitivity"]["low"] < impact["sensitivity"]["base"] < impact["sensitivity"]["high"]
    # Impact follows the actual cell volume, not a fixed figure.
    cell = frame[(frame["line"] == "Line B") & (frame["category"] == "Standard")]
    rest = frame[(frame["line"] != "Line B") | (frame["category"] != "Standard")]
    excess = (cell["rejected_units"].sum() / cell["actual_units"].sum()
              - rest["rejected_units"].sum() / rest["actual_units"].sum()) * 100.0
    expected_full = excess / 100.0 * cell["actual_units"].sum() * (365.0 / 60.0)
    assert impact["sensitivity"]["high"] == pytest.approx(expected_full, rel=0.02)


def test_r6_even_rejects_cleared():
    finding = advisor.rule_r6_rejection_concentration(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["expected_impact"] is None


# ----------------------------------------------------- integrity checks


def test_determinism_identical_json(real_df):
    first = advisor.run_advisor(real_df)
    second = advisor.run_advisor(real_df.copy())
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


def test_real_data_statuses_follow_the_planted_arcs(real_result):
    statuses = {f["id"]: f["status"] for f in real_result["findings"]}
    # Changeover leads the Pareto, so R1 fires on it.
    assert statuses["R1"] == "action_recommended"
    assert "Changeover" in _get(real_result, "R1")["evidence"]["summary"]
    # The availability gap sits under 2 points: a genuine cleared check,
    # proving cleared results are a real outcome of the rules.
    assert statuses["R2"] == "no_action_justified"
    # The planted night performance arc survives mix adjustment.
    assert statuses["R3"] == "action_recommended"
    # The maintenance programme shows a clear fall, so extension is recommended.
    assert statuses["R4"] == "action_recommended"
    assert statuses["R5"] == "action_recommended"
    assert statuses["R6"] == "action_recommended"


def test_quality_gates_on_throughput_and_energy_findings(real_result):
    for finding in real_result["findings"]:
        if finding["id"] in ("R1", "R2", "R3", "R5") and finding["expected_impact"] is not None:
            gate = finding["quality_gate"]
            assert gate is not None, f"{finding['id']} adds output or cuts energy without a quality gate"
            assert gate["outcome"] != "passes", (
                f"{finding['id']} gate cannot pass: quality is not verifiable in advance"
            )


def test_impacts_never_fixed_percent_of_nothing(real_result):
    """Every fired impact carries computed calculations and a sensitivity."""
    for finding in real_result["findings"]:
        impact = finding["expected_impact"]
        if impact is None:
            continue
        assert impact["calculations"], finding["id"]
        assert impact["assumptions"], finding["id"]
        sens = impact["sensitivity"]
        assert sens["low"] <= sens["base"] <= sens["high"], finding["id"]


def test_r2_gap_flips_when_a_gap_is_planted(real_df):
    """R2 clears on the real data but must fire when the gap widens."""
    modified = real_df.copy()
    mask = modified["line"] == "Line B"
    modified.loc[mask, "downtime_h"] = modified.loc[mask, "downtime_h"] + 0.5
    modified.loc[mask, "run_time_h"] = 7.5 - modified.loc[mask, "downtime_h"]
    finding = advisor.rule_r2_worst_line_availability(modified)
    assert finding["status"] == "action_recommended"


# ------------------------------------------------------- JSON contract


FINDING_KEYS = [
    "id", "title", "status", "severity", "problem", "evidence",
    "possible_causes", "recommendation", "expected_impact", "tradeoffs",
    "quality_gate", "validation_required",
]
META_KEYS = ["generated_at", "method", "scenario_analysed", "period", "thresholds", "note"]
STATUSES = {"action_recommended", "conditional", "no_action_justified", "informational"}
SEVERITIES = {"high", "medium", "low", None}


@pytest.fixture(scope="module")
def built_json(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("advisor")
    real_json = Path(__file__).resolve().parents[1] / "data" / "mfg_data.json"
    if real_json.exists():
        shutil.copy(real_json, out_dir / "mfg_data.json")
    else:
        rows = build_mod.export_rows(generate())
        (out_dir / "mfg_data.json").write_text(
            json.dumps({"rows": rows}), encoding="utf-8"
        )
    return build_advisor.build(out_dir=out_dir)


def test_json_is_strict(built_json):
    text = built_json.read_text(encoding="utf-8")
    assert "NaN" not in text
    assert "Infinity" not in text

    def reject(token):
        raise AssertionError(f"non-strict JSON token: {token}")

    data = json.loads(text, parse_constant=reject)
    assert isinstance(data, dict)


def test_json_has_no_em_or_en_dashes(built_json):
    text = built_json.read_text(encoding="utf-8")
    assert "—" not in text  # em dash
    assert "–" not in text  # en dash


def test_json_contract(built_json):
    data = json.loads(built_json.read_text(encoding="utf-8"))
    assert list(data) == ["meta", "findings"]
    assert list(data["meta"]) == META_KEYS
    assert list(data["meta"]["period"]) == ["start", "end", "days", "rows_in_record"]
    assert set(data["meta"]["thresholds"]) == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert "no action justified" in data["meta"]["note"]

    assert [f["id"] for f in data["findings"]] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    for finding in data["findings"]:
        assert list(finding) == FINDING_KEYS, f"key order broken in {finding['id']}"
        assert finding["status"] in STATUSES
        assert finding["severity"] in SEVERITIES
        assert set(finding["evidence"]) == {"summary", "details"}
        assert isinstance(finding["evidence"]["details"], list)
        for cause in finding["possible_causes"]:
            assert set(cause) == {"cause", "basis"}
            assert cause["basis"] in ("observed", "hypothesis")
        impact = finding["expected_impact"]
        if impact is not None:
            assert set(impact) == {"summary", "calculations", "assumptions", "sensitivity"}
            for calc in impact["calculations"]:
                assert set(calc) == {"label", "value", "unit"}
            assert set(impact["sensitivity"]) == {"low", "base", "high", "unit", "description"}
        gate = finding["quality_gate"]
        if gate is not None:
            assert set(gate) == {"check", "outcome", "note"}
            assert gate["outcome"] in ("passes", "conditional", "fails")
        assert isinstance(finding["validation_required"], list)
