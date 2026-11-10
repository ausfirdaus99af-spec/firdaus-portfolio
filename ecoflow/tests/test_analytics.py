"""Tests for the EcoFlow analytics functions and the dashboard JSON contract."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import analytics  # noqa: E402
import build_dashboard_data as bdd  # noqa: E402
import generate_data as gd  # noqa: E402


# ---------------------------------------------------------------- formulas


def test_removal_efficiency_known_values():
    assert analytics.removal_efficiency(500, 50) == 90.0
    assert analytics.removal_efficiency(100, 0) == 100.0
    assert analytics.removal_efficiency(200, 100) == 50.0


def test_removal_efficiency_negative_result_preserved():
    # Effluent above influent gives a negative efficiency, not clipped.
    assert analytics.removal_efficiency(100, 150) == -50.0


def test_removal_efficiency_invalid_inputs():
    assert math.isnan(analytics.removal_efficiency(0, 10))
    assert math.isnan(analytics.removal_efficiency(-5, 10))
    assert math.isnan(analytics.removal_efficiency(float("nan"), 10))
    assert math.isnan(analytics.removal_efficiency(500, float("nan")))
    assert math.isnan(analytics.removal_efficiency(None, 10))
    assert math.isnan(analytics.removal_efficiency(500, None))


def test_pollutant_load_known_values():
    # 200 m3/h at 500 mg/L = 100 kg/h
    assert analytics.pollutant_load_kg_per_h(200, 500) == 100.0
    assert analytics.pollutant_load_kg_per_h(0, 500) == 0.0


def test_pollutant_load_invalid_inputs():
    assert math.isnan(analytics.pollutant_load_kg_per_h(-1, 500))
    assert math.isnan(analytics.pollutant_load_kg_per_h(200, -5))
    assert math.isnan(analytics.pollutant_load_kg_per_h(float("nan"), 500))
    assert math.isnan(analytics.pollutant_load_kg_per_h(None, 500))


def test_specific_energy_known_values():
    assert analytics.specific_energy_kwh_m3(160, 200) == 0.8
    assert math.isnan(analytics.specific_energy_kwh_m3(100, 0))
    assert math.isnan(analytics.specific_energy_kwh_m3(100, -10))
    assert math.isnan(analytics.specific_energy_kwh_m3(-1, 200))
    assert math.isnan(analytics.specific_energy_kwh_m3(float("nan"), 200))
    assert math.isnan(analytics.specific_energy_kwh_m3(None, 200))


def test_chemical_g_per_m3_known_values():
    assert analytics.chemical_g_per_m3(12, 200) == 60.0
    assert math.isnan(analytics.chemical_g_per_m3(12, 0))
    assert math.isnan(analytics.chemical_g_per_m3(-1, 200))
    assert math.isnan(analytics.chemical_g_per_m3(None, 200))


def test_vectorised_inputs():
    result = analytics.removal_efficiency(np.array([500.0, 0.0, 100.0]), np.array([50.0, 10.0, np.nan]))
    assert result[0] == 90.0
    assert math.isnan(result[1])
    assert math.isnan(result[2])


# ---------------------------------------------------------------- cleaning


def _tiny_frame():
    return pd.DataFrame(
        {
            "timestamp": [f"2026-07-04T0{i}:00:00" for i in range(5)],
            "scenario": ["baseline"] * 5,
            "influent_flow_m3h": [200.0, 210.0, -4.0, 190.0, 205.0],
            "influent_ph": [7.2, 14.0, 7.1, 7.3, 7.2],
            "influent_cod_mgl": [650.0, 640.0, 655.0, np.nan, 660.0],
            "influent_bod_mgl": [320.0, 315.0, 322.0, 318.0, 325.0],
            "influent_tss_mgl": [290.0, 285.0, 292.0, 288.0, 291.0],
            "effluent_ph": [7.1, 7.2, 7.0, 7.2, 7.1],
            "effluent_cod_mgl": [70.0, 72.0, 69.0, 71.0, 70.5],
            "effluent_bod_mgl": [15.0, 16.0, 14.0, 15.5, 15.2],
            "effluent_tss_mgl": [12.0, 11.0, 12.5, 11.8, 12.2],
            "electricity_kwh": [160.0, 165.0, 158.0, 150.0, 162.0],
            "chemical_dose_kg": [12.0, 12.4, 11.8, 11.5, 12.1],
            "treatment_status": ["normal"] * 5,
            "anomaly_type": ["", "sensor_spike", "out_of_range", "missing", ""],
        }
    )


def test_anomaly_mask_catches_tags_and_ranges():
    df = _tiny_frame()
    mask = analytics.anomaly_mask(df)
    assert list(mask) == [False, True, True, True, False]
    # Range checks work even when the tag is removed.
    untagged = df.copy()
    untagged["anomaly_type"] = ""
    mask2 = analytics.anomaly_mask(untagged)
    assert list(mask2) == [False, True, True, True, False]


def test_clean_hourly_removes_anomalies():
    df = _tiny_frame()
    clean = analytics.clean_hourly(df)
    assert len(clean) == 2
    assert (clean["anomaly_type"] == "").all()


def test_anomaly_records_identify_parameters():
    records = analytics.anomaly_records(_tiny_frame())
    by_type = {r["type"]: r for r in records}
    assert by_type["sensor_spike"]["parameter"] == "influent_ph"
    assert by_type["out_of_range"]["parameter"] == "influent_flow_m3h"
    assert by_type["missing"]["parameter"] == "influent_cod_mgl"
    for r in records:
        assert set(r) == {"timestamp", "parameter", "type", "note"}


# ------------------------------------------------- generated-data invariants


@pytest.fixture(scope="module")
def generated():
    return gd.generate(seed=42)


def test_bod_le_cod_invariant_on_clean_generated_data(generated):
    clean = analytics.clean_hourly(generated)
    assert (clean["effluent_bod_mgl"] <= clean["effluent_cod_mgl"]).all()
    assert (clean["influent_bod_mgl"] <= clean["influent_cod_mgl"]).all()


def test_daily_aggregate_shape_and_sanity(generated):
    base = generated[generated["scenario"] == "baseline"]
    daily = analytics.daily_aggregate(base)
    assert len(daily) == 120
    assert (daily["volume_m3"] > 0).all()
    assert daily["removal_cod_pct"].between(40, 100).all()
    assert daily["removal_bod_pct"].between(40, 100).all()
    assert daily["removal_tss_pct"].between(40, 100).all()
    assert (daily["cod_load_in_kgd"] > daily["cod_load_out_kgd"]).all()
    assert daily["anomaly_count"].sum() >= 10
    assert (daily["upset_hours"].sum()) > 0
    assert (daily["maintenance_hours"].sum()) == 16


# ----------------------------------------------------------- JSON contract


DAILY_KEYS = {
    "date", "volume_m3", "flow_avg_m3h",
    "cod_in_mgl", "cod_out_mgl", "bod_in_mgl", "bod_out_mgl",
    "tss_in_mgl", "tss_out_mgl",
    "ph_in_avg", "ph_out_avg", "ph_out_min", "ph_out_max",
    "removal_cod_pct", "removal_bod_pct", "removal_tss_pct",
    "energy_kwh", "specific_energy_kwh_m3",
    "chemical_kg", "chemical_g_m3",
    "cod_load_in_kgd", "cod_load_out_kgd",
    "anomaly_count", "upset_hours", "maintenance_hours",
}

KPI_KEYS = {
    "total_volume_m3", "avg_removal_cod_pct", "avg_removal_bod_pct",
    "avg_removal_tss_pct", "avg_specific_energy_kwh_m3",
    "avg_chemical_g_m3", "total_energy_kwh", "total_chemical_kg",
    "anomaly_count", "upset_days",
}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("data")
    json_path = bdd.build(seed=42, out_dir=out_dir)
    return json_path


def test_json_is_strict(built):
    text = built.read_text(encoding="utf-8")
    assert "NaN" not in text
    assert "Infinity" not in text

    def reject(token):
        raise AssertionError(f"non-strict JSON token: {token}")

    data = json.loads(text, parse_constant=reject)
    assert isinstance(data, dict)


def test_json_contract_structure(built):
    data = json.loads(built.read_text(encoding="utf-8"))
    assert set(data) == {"meta", "scenarios"}
    meta = data["meta"]
    assert set(meta) == {"project", "synthetic", "seed", "generated_at", "date_range", "units", "assumptions"}
    assert meta["project"] == "EcoFlow"
    assert meta["synthetic"] is True
    assert meta["seed"] == 42
    assert meta["date_range"] == {"start": "2026-07-04", "end": "2026-10-31"}
    assert 5 <= len(meta["assumptions"]) <= 10

    assert set(data["scenarios"]) == {"baseline", "optimised"}
    for scenario in ("baseline", "optimised"):
        block = data["scenarios"][scenario]
        assert set(block) == {"daily", "kpis", "anomalies"}
        assert len(block["daily"]) == 120
        for entry in block["daily"]:
            assert set(entry) == DAILY_KEYS
        assert set(block["kpis"]) == KPI_KEYS
        assert block["kpis"]["anomaly_count"] > 0
        assert block["kpis"]["upset_days"] >= 4
        for anomaly in block["anomalies"]:
            assert set(anomaly) == {"timestamp", "parameter", "type", "note"}


def test_json_csv_written_alongside(built):
    csv_path = built.parent / "ecoflow_hourly.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert len(df) == 2 * gd.HOURS


def test_optimised_kpis_improve_on_baseline(built):
    data = json.loads(built.read_text(encoding="utf-8"))
    base = data["scenarios"]["baseline"]["kpis"]
    opt = data["scenarios"]["optimised"]["kpis"]
    assert opt["avg_specific_energy_kwh_m3"] < base["avg_specific_energy_kwh_m3"]
    assert opt["avg_chemical_g_m3"] < base["avg_chemical_g_m3"]
    assert opt["avg_removal_tss_pct"] >= base["avg_removal_tss_pct"]
