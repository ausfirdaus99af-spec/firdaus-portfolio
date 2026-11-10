"""Tests for the KL Mobility Lab Evidence and Recommendations engine.

Run from the mobility folder:  python -I -m pytest tests -q

Each rule is tested with positive fixtures (the check fires) and negative
fixtures (the check clears), with shares and ratios checked against hand
computed values. The engine also runs once against the real pipeline
output to pin down the real findings and determinism.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import advisor  # noqa: E402
import build_advisor  # noqa: E402
import build_mobility_data as bm  # noqa: E402

STATUSES = {"action_recommended", "conditional", "informational", "no_action_justified"}

# ---------------------------------------------------------------------------
# Fixture builders (synthetic, for rule unit tests)
# ---------------------------------------------------------------------------

DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def make_profile(weekday: float, weekend: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"dow": DOWS, "rail_avg": [weekday] * 5 + [weekend] * 2}
    )


def make_od(dest_trips: dict, n_days: int = 10, raw_multiple: int = 1,
            missing: list | None = None) -> dict:
    detail = pd.DataFrame(
        {"d": list(dest_trips), "ridership": list(dest_trips.values())}
    )
    total = int(detail["ridership"].sum())
    return {
        "detail": detail,
        "detail_total": total,
        "raw_total": total * raw_multiple,
        "n_days": n_days,
        "missing_destination_names": missing or [],
        "period": {"start": "2026-01-01", "end": "2026-01-10", "days_observed": n_days},
    }


def make_shah_alam(dates: list, present: set) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "trips": [100.0 if d in present else None for d in dates],
        }
    )


def make_monthly(rail: dict) -> pd.DataFrame:
    return pd.DataFrame({"m": list(rail), "rail": list(rail.values())})


def make_registrations(selangor: int, kl: int, rakan: int, other: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "m": ["2026-01"],
            "selangor": [selangor],
            "kl": [kl],
            "rakan_niaga": [rakan],
            "other": [other],
        }
    )


GAPS_ALL = [
    "No door-to-door commuting origin-destination matrix exists as open data.",
    "No workplace location data below state level.",
    "No open time series of road traffic volumes or speeds.",
    "No bus origin-destination matrix and no realised bus journey times.",
]


# ---------------------------------------------------------------------------
# R1 weekend headroom
# ---------------------------------------------------------------------------

def test_r1_fires_when_weekend_below_threshold():
    f = advisor.rule_r1_weekend_headroom(make_profile(1000.0, 500.0))
    assert f["status"] == "conditional"
    # Hand value: 500 / 1000 = 50.0 percent.
    assert "50.0 percent" in f["evidence"]["summary"]
    bases = {c["basis"] for c in f["possible_causes"]}
    assert bases == {"observed", "hypothesis"}


def test_r1_clears_when_weekend_close_to_weekday():
    f = advisor.rule_r1_weekend_headroom(make_profile(1000.0, 900.0))
    assert f["status"] == "no_action_justified"
    assert f["severity"] is None
    assert "90.0 percent" in f["evidence"]["summary"]


def test_r1_boundary_at_exact_threshold_clears():
    f = advisor.rule_r1_weekend_headroom(make_profile(1000.0, 700.0))
    assert f["status"] == "no_action_justified"


# ---------------------------------------------------------------------------
# R2 OD concentration
# ---------------------------------------------------------------------------

def test_r2_fires_on_concentrated_destinations():
    # 2 big + 10 small destinations. Top 10 = 300+200+8x50 = 900 of 1000.
    dests = {"Alpha": 300, "Beta": 200}
    dests.update({f"S{i:02d}": 50 for i in range(10)})
    f = advisor.rule_r2_od_concentration(make_od(dests))
    assert f["status"] == "action_recommended"
    assert f["severity"] == "high"  # 90 percent > 40 percent
    assert "90.0 percent" in f["evidence"]["summary"]
    assert "Alpha" in f["recommendation"] and "Beta" in f["recommendation"]


def test_r2_clears_on_balanced_destinations():
    # 50 equal destinations: top 10 share = 10/50 = 20 percent < 25.
    dests = {f"S{i:02d}": 20 for i in range(50)}
    f = advisor.rule_r2_od_concentration(make_od(dests))
    assert f["status"] == "no_action_justified"
    assert "20.0 percent" in f["evidence"]["summary"]


def test_r2_notes_missing_destinations_when_present():
    dests = {"Alpha": 300, "Beta": 200}
    dests.update({f"S{i:02d}": 50 for i in range(10)})
    f = advisor.rule_r2_od_concentration(make_od(dests, missing=["Ghost"]))
    assert any("missing from the published file" in d for d in f["evidence"]["details"])


# ---------------------------------------------------------------------------
# R3 published data quality
# ---------------------------------------------------------------------------

def _full_dates(start: str, end: str) -> list:
    return list(pd.date_range(start, end, freq="D").strftime("%Y-%m-%d"))


def test_r3_clears_when_all_checks_pass():
    # Consistent file: no marginal inflation, every origin is a destination,
    # no gap inside the reporting span.
    od = make_od({"A": 100, "B": 100}, raw_multiple=1, missing=[])
    dates = _full_dates("2026-04-01", "2026-04-10")
    sa = make_shah_alam(dates, present=set(dates))
    f = advisor.rule_r3_published_data_quality(od, sa)
    assert f["status"] == "no_action_justified"
    assert any("No marginal total rows" in d for d in f["evidence"]["details"])


def test_r3_fires_on_triple_counted_marginals():
    od = make_od({"A": 100, "B": 100}, raw_multiple=3)
    dates = _full_dates("2026-04-01", "2026-04-10")
    sa = make_shah_alam(dates, present=set(dates))
    f = advisor.rule_r3_published_data_quality(od, sa)
    assert f["status"] == "action_recommended"
    assert "marginal_rows" in f["evidence"]["summary"]
    assert any("3.0 times too high" in d for d in f["evidence"]["details"])
    # The other two checks still pass and say so.
    assert any("Every origin station also appears" in d for d in f["evidence"]["details"])
    assert any("No reporting gap" in d for d in f["evidence"]["details"])


def test_r3_fires_on_reporting_gap_with_hand_counted_days():
    od = make_od({"A": 100, "B": 100}, raw_multiple=1)
    dates = _full_dates("2026-04-01", "2026-04-10")
    present = set(dates) - {"2026-04-04", "2026-04-05", "2026-04-06"}
    f = advisor.rule_r3_published_data_quality(od, make_shah_alam(dates, present))
    assert f["status"] == "action_recommended"
    assert any("3 of 10 days" in d for d in f["evidence"]["details"])
    assert any("2026-04-04 to 2026-04-06" in d for d in f["evidence"]["details"])


def test_r3_fires_on_missing_destinations():
    od = make_od({"A": 100, "B": 100}, raw_multiple=1, missing=["Ghost One", "Ghost Two"])
    dates = _full_dates("2026-04-01", "2026-04-03")
    f = advisor.rule_r3_published_data_quality(od, make_shah_alam(dates, set(dates)))
    assert f["status"] == "action_recommended"
    assert any("2 stations never appear as destinations" in d for d in f["evidence"]["details"])
    assert any("Ghost One, Ghost Two" in d for d in f["evidence"]["details"])


# ---------------------------------------------------------------------------
# R4 recovery trajectory
# ---------------------------------------------------------------------------

def _monthly_with_baseline(recent_value: float, dip_month: str | None = None) -> pd.DataFrame:
    rail = {f"2019-{m:02d}": 100.0 for m in range(1, 13)}
    for m in range(1, 13):
        ym = f"2025-{m:02d}"
        rail[ym] = 90.0 if ym == dip_month else recent_value
    return make_monthly(rail)


def test_r4_conditional_when_all_window_months_above_baseline():
    f = advisor.rule_r4_recovery_trajectory(_monthly_with_baseline(148.0))
    assert f["status"] == "conditional"
    # Hand value: every month 148 / 100 = 148.0 percent.
    assert "148.0 percent" in f["evidence"]["summary"]
    assert any("says nothing about car traffic" in d for d in f["evidence"]["details"])
    # The mode shift question must stay a hypothesis.
    shift = [c for c in f["possible_causes"] if "switching from cars" in c["cause"]]
    assert shift and shift[0]["basis"] == "hypothesis"


def test_r4_informational_when_a_month_dips_below():
    f = advisor.rule_r4_recovery_trajectory(_monthly_with_baseline(148.0, dip_month="2025-06"))
    assert f["status"] == "informational"
    assert "11 of 12" in f["evidence"]["summary"]


def test_r4_informational_when_no_baseline_exists():
    f = advisor.rule_r4_recovery_trajectory(make_monthly({"2025-01": 100.0}))
    assert f["status"] == "informational"
    assert "cannot be computed" in f["evidence"]["summary"]


# ---------------------------------------------------------------------------
# R5 registration limits
# ---------------------------------------------------------------------------

def test_r5_fires_on_dominant_no_geography_channel():
    # Hand value: 870 / 1000 = 87.0 percent, above the 75 percent high bar.
    f = advisor.rule_r5_registration_limits(make_registrations(50, 40, 870, 40))
    assert f["status"] == "action_recommended"
    assert f["severity"] == "high"
    assert "87.0 percent" in f["evidence"]["summary"]


def test_r5_medium_severity_between_floor_and_high_bar():
    # Hand value: 600 / 1000 = 60.0 percent.
    f = advisor.rule_r5_registration_limits(make_registrations(200, 100, 600, 100))
    assert f["status"] == "action_recommended"
    assert f["severity"] == "medium"


def test_r5_clears_on_small_channel_share():
    # Hand value: 100 / 1000 = 10.0 percent.
    f = advisor.rule_r5_registration_limits(make_registrations(500, 200, 100, 200))
    assert f["status"] == "no_action_justified"
    assert "10.0 percent" in f["evidence"]["summary"]


# ---------------------------------------------------------------------------
# R6 settling datasets
# ---------------------------------------------------------------------------

def test_r6_lists_four_datasets_from_full_gaps():
    f = advisor.rule_r6_settling_datasets(GAPS_ALL)
    assert f["status"] == "informational"
    assert len(f["validation_required"]) == 4
    assert all("How it would be used" in d for d in f["evidence"]["details"][:-1])


def test_r6_tracks_the_gaps_actually_documented():
    f = advisor.rule_r6_settling_datasets(GAPS_ALL[:2])
    assert len(f["validation_required"]) == 2


# ---------------------------------------------------------------------------
# Real data: findings, determinism, contract
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def real_inputs():
    built = bm.build_all(write=False)
    return build_advisor.assemble_inputs(built)


@pytest.fixture(scope="session")
def real_result(real_inputs):
    return advisor.run_advisor(**real_inputs)


def test_real_statuses_and_key_numbers(real_result):
    by_id = {f["id"]: f for f in real_result["findings"]}
    assert [f["id"] for f in real_result["findings"]] == ["R1", "R2", "R3", "R4", "R5", "R6"]

    assert by_id["R1"]["status"] == "conditional"
    assert "65.5 percent" in by_id["R1"]["evidence"]["summary"]

    assert by_id["R2"]["status"] == "action_recommended"
    assert by_id["R2"]["severity"] == "medium"
    assert "34.5 percent" in by_id["R2"]["evidence"]["summary"]
    assert "Bukit Bintang" in by_id["R2"]["recommendation"]

    assert by_id["R3"]["status"] == "action_recommended"
    assert "3 of 3" in by_id["R3"]["evidence"]["summary"]
    assert any("566,125,329" in d for d in by_id["R3"]["evidence"]["details"])
    assert any("188,708,443" in d for d in by_id["R3"]["evidence"]["details"])
    assert any("28 stations" in d for d in by_id["R3"]["evidence"]["details"])
    assert any("2026-05-01 to 2026-06-28" in d for d in by_id["R3"]["evidence"]["details"])

    assert by_id["R4"]["status"] == "conditional"
    assert "144.1 percent" in by_id["R4"]["evidence"]["summary"]

    assert by_id["R5"]["status"] == "action_recommended"
    assert by_id["R5"]["severity"] == "high"
    assert "87.3 percent" in by_id["R5"]["evidence"]["summary"]

    assert by_id["R6"]["status"] == "informational"


def test_real_r2_share_matches_independent_computation(real_inputs, real_result):
    od = real_inputs["od"]
    dests = od["detail"].groupby("d")["ridership"].sum().sort_values(ascending=False)
    share = float(dests.head(10).sum()) / od["detail_total"] * 100.0
    assert f"{round(share, 1)} percent" in real_result["findings"][1]["evidence"]["summary"]


def test_determinism_two_runs_identical(real_inputs):
    a = advisor.run_advisor(**real_inputs)
    b = advisor.run_advisor(**real_inputs)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_json_contract(real_result):
    keys = list(advisor._FINDING_KEYS)
    for f in real_result["findings"]:
        assert list(f.keys()) == keys
        assert f["status"] in STATUSES
        assert isinstance(f["evidence"], dict)
        assert set(f["evidence"]) == {"summary", "details"}
        for cause in f["possible_causes"]:
            assert set(cause) == {"cause", "basis"}
            assert cause["basis"] in {"observed", "hypothesis"}
        # Every finding cites a source inside its evidence.
        assert any(d.startswith("Source:") for d in f["evidence"]["details"])
    meta = real_result["meta"]
    assert "audience_note" in meta
    assert "thresholds" in meta and set(meta["thresholds"]) == {f"R{i}" for i in range(1, 7)}
    # Strict JSON: no NaN or Infinity anywhere.
    json.dumps(real_result, allow_nan=False)


def test_written_file_matches_engine_output(real_inputs, tmp_path):
    out = build_advisor.build(out_dir=tmp_path)
    data = json.loads(out.read_text(encoding="utf-8"))
    fresh = advisor.run_advisor(**real_inputs)
    assert data["findings"] == json.loads(json.dumps(fresh["findings"]))
    meta = dict(data["meta"])
    meta.pop("generated_at")
    assert meta == json.loads(json.dumps(fresh["meta"]))
