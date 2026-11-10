"""Tests for the EcoFlow synthetic data generator."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_data as gd  # noqa: E402

NUMERIC_COLUMNS = [
    "influent_flow_m3h",
    "influent_ph",
    "influent_cod_mgl",
    "influent_bod_mgl",
    "influent_tss_mgl",
    "effluent_ph",
    "effluent_cod_mgl",
    "effluent_bod_mgl",
    "effluent_tss_mgl",
    "electricity_kwh",
    "chemical_dose_kg",
]

STRING_COLUMNS = ["timestamp", "scenario", "treatment_status", "anomaly_type"]


@pytest.fixture(scope="module")
def df():
    return gd.generate(seed=42)


@pytest.fixture(scope="module")
def good(df):
    """Non-anomalous rows only."""
    return df[df["anomaly_type"] == ""]


def test_same_seed_identical(df):
    again = gd.generate(seed=42)
    pd.testing.assert_frame_equal(df, again)


def test_different_seed_differs(df):
    other = gd.generate(seed=7)
    assert not df[NUMERIC_COLUMNS].equals(other[NUMERIC_COLUMNS])


def test_schema_columns_and_dtypes(df):
    assert list(df.columns) == gd.COLUMNS
    for col in NUMERIC_COLUMNS:
        assert pd.api.types.is_float_dtype(df[col]), f"{col} should be float"
    for col in STRING_COLUMNS:
        assert df[col].dtype == object, f"{col} should be object (string)"


def test_both_scenarios_and_span(df):
    assert set(df["scenario"].unique()) == {"baseline", "optimised"}
    per_scenario = df.groupby("scenario").size()
    assert (per_scenario == gd.HOURS).all()
    days = pd.to_datetime(df["timestamp"]).dt.date.nunique()
    assert days >= 90
    assert days == 120
    assert df["timestamp"].min() == "2026-07-04T00:00:00"
    assert df["timestamp"].max() == "2026-10-31T23:00:00"


def test_value_ranges_on_non_anomalous_rows(good):
    for col in ["influent_ph", "effluent_ph"]:
        assert good[col].between(0, 14).all(), f"{col} outside 0-14"
    for col in [
        "influent_cod_mgl",
        "influent_bod_mgl",
        "influent_tss_mgl",
        "effluent_cod_mgl",
        "effluent_bod_mgl",
        "effluent_tss_mgl",
    ]:
        assert (good[col] > 0).all(), f"{col} not strictly positive"
    assert (good["influent_flow_m3h"] > 0).all()
    assert (good["electricity_kwh"] > 0).all()
    assert (good["chemical_dose_kg"] > 0).all()
    assert not good[NUMERIC_COLUMNS].isna().any().any()


def test_effluent_cod_below_influent_for_normal(good):
    normal = good[good["treatment_status"] == "normal"]
    assert (normal["effluent_cod_mgl"] < normal["influent_cod_mgl"]).all()


def test_bod_never_exceeds_cod_on_non_anomalous(good):
    assert (good["influent_bod_mgl"] <= good["influent_cod_mgl"]).all()
    assert (good["effluent_bod_mgl"] <= good["effluent_cod_mgl"]).all()


def test_upsets_exist_and_match_across_scenarios(df):
    for scenario in ("baseline", "optimised"):
        sub = df[df["scenario"] == scenario]
        assert (sub["treatment_status"] == "upset").any(), f"no upsets in {scenario}"
    base_upsets = set(df[(df["scenario"] == "baseline") & (df["treatment_status"] == "upset")]["timestamp"])
    opt_upsets = set(df[(df["scenario"] == "optimised") & (df["treatment_status"] == "upset")]["timestamp"])
    assert base_upsets == opt_upsets, "upset times must match across scenarios"


def test_maintenance_windows_exist(df):
    sub = df[df["scenario"] == "baseline"]
    assert (sub["treatment_status"] == "maintenance").sum() == 16  # two 8 h windows


def test_anomalies_exist_and_are_tagged(df):
    for scenario in ("baseline", "optimised"):
        sub = df[df["scenario"] == scenario]
        types = set(sub["anomaly_type"].unique()) - {""}
        assert types == {"sensor_spike", "sensor_stuck", "missing", "out_of_range"}

    missing_rows = df[df["anomaly_type"] == "missing"]
    assert missing_rows[NUMERIC_COLUMNS].isna().any(axis=1).all()

    oor_rows = df[df["anomaly_type"] == "out_of_range"]
    assert (oor_rows[NUMERIC_COLUMNS] <= 0).any(axis=1).all()

    share = (df["anomaly_type"] != "").mean()
    assert 0.002 < share < 0.012, f"anomaly share {share:.4f} outside expected band"


def test_optimised_uses_less_energy_and_chemical(good):
    base = good[good["scenario"] == "baseline"]
    opt = good[good["scenario"] == "optimised"]
    assert opt["electricity_kwh"].mean() < base["electricity_kwh"].mean() * 0.92
    assert opt["chemical_dose_kg"].mean() < base["chemical_dose_kg"].mean() * 0.90
