"""Tests for the EcoFlow Engineering Improvement Advisor.

The negative cases matter as much as the positive ones: every rule is
tested both where it should fire and where it should return a cleared
check, proving the findings follow the data rather than being hardcoded.
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import advisor  # noqa: E402
import build_advisor  # noqa: E402
import generate_data as gd  # noqa: E402


# ------------------------------------------------------------- fixtures


def make_frame(hours: int = 240, seed: int = 0) -> pd.DataFrame:
    """A small, well-formed baseline frame with deterministic noise.

    Noise is needed so the stuck-sensor run detector does not flag
    deliberately constant columns.
    """
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-07-04", periods=hours, freq="h")
    flow = 200.0 + rng.normal(0.0, 15.0, hours)
    cod_in = 650.0 + rng.normal(0.0, 40.0, hours)
    tss_in = 290.0 + rng.normal(0.0, 25.0, hours)
    return pd.DataFrame(
        {
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "scenario": "baseline",
            "influent_flow_m3h": flow,
            "influent_ph": 7.2 + rng.normal(0.0, 0.1, hours),
            "influent_cod_mgl": cod_in,
            "influent_bod_mgl": cod_in * 0.5,
            "influent_tss_mgl": tss_in,
            "effluent_ph": 7.2 + rng.normal(0.0, 0.05, hours),
            "effluent_cod_mgl": cod_in * 0.10 * (1.0 + rng.normal(0.0, 0.03, hours)),
            "effluent_bod_mgl": cod_in * 0.05 * (1.0 + rng.normal(0.0, 0.03, hours)),
            "effluent_tss_mgl": tss_in * (1.0 - rng.uniform(0.90, 0.97, hours)),
            "electricity_kwh": flow * 0.8 * (1.0 + rng.normal(0.0, 0.03, hours)),
            "chemical_dose_kg": flow * 0.060 * (1.0 + rng.normal(0.0, 0.06, hours)),
            "treatment_status": "normal",
            "anomaly_type": "",
        }
    )


@pytest.fixture(scope="module")
def real_baseline():
    df = gd.generate(seed=42)
    return df[df["scenario"] == "baseline"].reset_index(drop=True)


@pytest.fixture(scope="module")
def real_result(real_baseline):
    return advisor.run_advisor(real_baseline)


def _get(result, rule_id):
    return next(f for f in result["findings"] if f["id"] == rule_id)


# ------------------------------------------------------------------- R1


def test_r1_detects_upset_episode():
    df = make_frame()
    # 6 contiguous hours at about 60 percent removal (below the 75 floor).
    df.loc[30:35, "effluent_cod_mgl"] = df.loc[30:35, "influent_cod_mgl"] * 0.40
    finding = advisor.rule_r1_process_upsets(df)
    assert finding["status"] == "action_recommended"
    assert finding["severity"] in ("high", "medium")
    assert any("6 h" in d for d in finding["evidence"]["details"])
    # Evidence and hypotheses are both present and labelled.
    bases = {c["basis"] for c in finding["possible_causes"]}
    assert bases == {"observed", "hypothesis"}
    assert finding["validation_required"]


def test_r1_absent_is_cleared():
    finding = advisor.rule_r1_process_upsets(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["severity"] is None
    assert finding["expected_impact"] is None


def test_r1_short_dip_below_min_duration_is_cleared():
    df = make_frame()
    df.loc[30:31, "effluent_cod_mgl"] = df.loc[30:31, "influent_cod_mgl"] * 0.40  # only 2 h
    finding = advisor.rule_r1_process_upsets(df)
    assert finding["status"] == "no_action_justified"


def test_r1_excess_cod_positive_and_summed():
    df = make_frame()
    df.loc[30:35, "effluent_cod_mgl"] = df.loc[30:35, "influent_cod_mgl"] * 0.40
    finding = advisor.rule_r1_process_upsets(df)
    # Excess mass appears as a real number in the evidence text.
    assert "extra COD left the plant" in finding["evidence"]["details"][0]


# ------------------------------------------------------------------- R2


def test_r2_fires_above_threshold_missing():
    df = make_frame()
    df.loc[10:24, "influent_cod_mgl"] = np.nan  # 15 of 240 readings, far over 0.3 percent
    finding = advisor.rule_r2_sensor_reliability(df)
    assert finding["status"] == "action_recommended"
    assert "influent_cod_mgl" in finding["evidence"]["summary"]
    assert "connectivity" in finding["recommendation"]  # missing-specific advice


def test_r2_fires_on_stuck_with_maintenance_advice():
    df = make_frame()
    df.loc[50:59, "influent_flow_m3h"] = float(df.loc[50, "influent_flow_m3h"])  # 10 identical readings
    finding = advisor.rule_r2_sensor_reliability(df)
    assert finding["status"] == "action_recommended"
    assert "influent_flow_m3h" in finding["recommendation"]
    assert "maintenance" in finding["recommendation"]


def test_r2_below_threshold_is_cleared():
    finding = advisor.rule_r2_sensor_reliability(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["severity"] is None


# ------------------------------------------------------------------- R3


def test_r3_large_intercept_fires_with_sensitivity_and_gate():
    df = make_frame()
    rng = np.random.default_rng(1)
    df["electricity_kwh"] = 100.0 + 0.3 * df["influent_flow_m3h"] + rng.normal(0.0, 2.0, len(df))
    finding = advisor.rule_r3_energy_baseload(df)
    assert finding["status"] == "action_recommended"
    impact = finding["expected_impact"]
    assert impact is not None
    sens = impact["sensitivity"]
    assert sens["low"] < sens["base"] < sens["high"]
    assert sens["unit"] == "kWh/yr"
    assert impact["assumptions"]
    # Energy reduction must carry a quality gate that is not an unverified pass.
    assert finding["quality_gate"] is not None
    assert finding["quality_gate"]["outcome"] != "passes"
    # Fitted intercept is reported close to the constructed 100 kWh/h.
    a = next(c["value"] for c in impact["calculations"] if c["label"] == "always-on base load (intercept a)")
    assert 90.0 < a < 110.0


def test_r3_near_zero_intercept_is_cleared_with_fitted_values():
    finding = advisor.rule_r3_energy_baseload(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["expected_impact"] is None
    # The cleared check still reports the fitted values.
    assert any("slope" in d or "Intercept" in d for d in finding["evidence"]["details"])


# ------------------------------------------------------------------- R4


def test_r4_flat_response_is_conditional_with_trial_first():
    df = make_frame(hours=480)
    finding = advisor.rule_r4_dose_response(df)  # dose and removal independent by construction
    assert finding["status"] == "conditional"
    assert "trial" in finding["recommendation"].lower()
    assert "no dose reduction is justified today" in finding["recommendation"].lower()
    impact = finding["expected_impact"]
    assert impact is not None
    assert impact["sensitivity"]["low"] < impact["sensitivity"]["base"] < impact["sensitivity"]["high"]
    assert impact["sensitivity"]["unit"] == "kg/yr"
    assert finding["quality_gate"]["outcome"] == "conditional"


def test_r4_positive_response_does_not_recommend_reduction():
    df = make_frame(hours=480)
    dose_gm3 = df["chemical_dose_kg"] * 1000.0 / df["influent_flow_m3h"]
    eff = np.clip(0.80 + 0.003 * dose_gm3, None, 0.99)
    df["effluent_tss_mgl"] = df["influent_tss_mgl"] * (1.0 - eff)
    finding = advisor.rule_r4_dose_response(df)
    assert finding["status"] == "no_action_justified"
    assert finding["expected_impact"] is None
    assert "no dose reduction justified" in finding["recommendation"].lower()


# ------------------------------------------------------------------- R5


def test_r5_excursions_fire():
    df = make_frame()
    df.loc[10:39, "effluent_ph"] = 8.5  # 30 hours outside 6.5 to 7.8
    finding = advisor.rule_r5_ph_control(df)
    assert finding["status"] == "action_recommended"
    assert finding["severity"] == "medium"
    assert "30" in finding["evidence"]["summary"]


def test_r5_absent_is_cleared():
    finding = advisor.rule_r5_ph_control(make_frame())
    assert finding["status"] == "no_action_justified"
    assert finding["severity"] is None


# ------------------------------------------------------------------- R6


def test_r6_always_informational(real_result):
    finding = _get(real_result, "R6")
    assert finding["status"] == "informational"
    assert finding["severity"] is None
    assert len(finding["evidence"]["details"]) >= 5
    assert finding["validation_required"]


# ----------------------------------------------------- integrity checks


def test_determinism_identical_json(real_baseline):
    first = advisor.run_advisor(real_baseline)
    second = advisor.run_advisor(real_baseline.copy())
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


def test_findings_follow_the_data_r1(real_baseline, real_result):
    # On the real baseline the upset rule fires...
    assert _get(real_result, "R1")["status"] == "action_recommended"
    # ...and on a copy with the upset rows removed it must clear.
    modified = real_baseline[real_baseline["treatment_status"] != "upset"].reset_index(drop=True)
    cleared = advisor.rule_r1_process_upsets(modified)
    assert cleared["status"] == "no_action_justified"


def test_quality_gates_on_saving_findings(real_result):
    for finding in real_result["findings"]:
        if finding["expected_impact"] is not None and finding["id"] in ("R3", "R4"):
            gate = finding["quality_gate"]
            assert gate is not None, f"{finding['id']} reduces consumption without a quality gate"
            assert gate["outcome"] in ("conditional", "fails"), (
                f"{finding['id']} gate cannot pass: treatment performance is not verifiable from this dataset"
            )


def test_r4_is_conditional_on_real_data(real_result):
    finding = _get(real_result, "R4")
    assert finding["status"] == "conditional"
    assert finding["quality_gate"]["outcome"] == "conditional"


def test_real_data_statuses_are_computed_not_assumed(real_result):
    statuses = {f["id"]: f["status"] for f in real_result["findings"]}
    # The advisor must be able to clear checks: at least one cleared check
    # exists on the real data, proving cleared results are a real outcome.
    assert "no_action_justified" in statuses.values()
    assert statuses["R6"] == "informational"


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
    real_csv = Path(__file__).resolve().parents[1] / "data" / "ecoflow_hourly.csv"
    if real_csv.exists():
        shutil.copy(real_csv, out_dir / "ecoflow_hourly.csv")
    else:
        gd.generate(seed=42).to_csv(out_dir / "ecoflow_hourly.csv", index=False)
    return build_advisor.build(out_dir=out_dir)


def test_json_is_strict(built_json):
    text = built_json.read_text(encoding="utf-8")
    assert "NaN" not in text
    assert "Infinity" not in text

    def reject(token):
        raise AssertionError(f"non-strict JSON token: {token}")

    data = json.loads(text, parse_constant=reject)
    assert isinstance(data, dict)


def test_json_contract(built_json):
    data = json.loads(built_json.read_text(encoding="utf-8"))
    assert list(data) == ["meta", "findings"]
    assert list(data["meta"]) == META_KEYS
    assert data["meta"]["scenario_analysed"] == "baseline"
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
