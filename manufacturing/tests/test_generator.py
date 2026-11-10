"""Tests for the synthetic data generator."""

import numpy as np
import pandas as pd
import pytest

import generate_data
from generate_data import (
    CRASH_END,
    CRASH_START,
    DOWNTIME_REASONS,
    IDEAL_RATES_UPH,
    LINES,
    MAINTENANCE_FROM,
    PLANNED_TIME_H,
    SHIFTS,
    generate,
)


@pytest.fixture(scope="module")
def df():
    return generate()


class TestDeterminism:
    def test_same_seed_identical(self, df):
        again = generate(seed=42)
        pd.testing.assert_frame_equal(df, again)

    def test_different_seed_differs(self, df):
        other = generate(seed=7)
        assert not df.equals(other)


class TestShape:
    def test_row_count(self, df):
        assert len(df) == 2190

    def test_columns(self, df):
        assert list(df.columns) == generate_data.COLUMNS

    def test_dtypes(self, df):
        for col in ("planned_units", "actual_units", "good_units",
                    "rejected_units", "ideal_rate"):
            assert np.issubdtype(df[col].dtype, np.integer), col
        for col in ("planned_time_h", "run_time_h", "downtime_h",
                    "energy_kwh", "material_kg"):
            assert np.issubdtype(df[col].dtype, np.floating), col
        for col in ("date", "line", "shift", "category",
                    "downtime_reason", "equipment_status"):
            assert df[col].dtype == object, col

    def test_date_range(self, df):
        assert df["date"].min() == "2025-11-01"
        assert df["date"].max() == "2026-10-31"
        assert df["date"].nunique() == 365

    def test_all_lines_and_shifts_present(self, df):
        assert sorted(df["line"].unique()) == sorted(LINES)
        assert sorted(df["shift"].unique()) == sorted(SHIFTS)
        # Exactly one row per date x line x shift.
        assert not df.duplicated(subset=["date", "line", "shift"]).any()
        counts = df.groupby(["line", "shift"]).size()
        assert (counts == 365).all()

    def test_categories_and_line_mix(self, df):
        assert set(df["category"].unique()) == {"Standard", "Premium"}
        share_standard = (
            df.groupby("line")["category"]
            .apply(lambda s: (s == "Standard").mean())
        )
        assert share_standard["Line A"] > 0.7
        assert share_standard["Line B"] > 0.7
        assert share_standard["Line C"] < 0.3


class TestInvariants:
    def test_good_never_exceeds_actual(self, df):
        assert (df["good_units"] <= df["actual_units"]).all()

    def test_rejected_is_actual_minus_good(self, df):
        assert (df["rejected_units"]
                == df["actual_units"] - df["good_units"]).all()

    def test_time_balance(self, df):
        gap = (df["run_time_h"] + df["downtime_h"] - df["planned_time_h"]).abs()
        assert (gap < 1e-6).all()

    def test_planned_time_constant(self, df):
        assert (df["planned_time_h"] == PLANNED_TIME_H).all()

    def test_non_negative(self, df):
        for col in ("planned_units", "actual_units", "good_units",
                    "rejected_units", "run_time_h", "downtime_h",
                    "energy_kwh", "material_kg"):
            assert (df[col] >= 0).all(), col

    def test_run_time_never_exceeds_planned(self, df):
        assert (df["run_time_h"] <= PLANNED_TIME_H + 1e-9).all()

    def test_reasons_valid(self, df):
        valid = set(DOWNTIME_REASONS) | {"None"}
        assert set(df["downtime_reason"].unique()) <= valid

    def test_none_reason_iff_tiny_downtime(self, df):
        is_none = df["downtime_reason"] == "None"
        assert (df.loc[is_none, "downtime_h"] < 0.1).all()
        assert (df.loc[~is_none, "downtime_h"] >= 0.1).all()

    def test_status_valid(self, df):
        assert set(df["equipment_status"].unique()) <= {
            "running", "degraded", "breakdown"}
        breakdown_reason = df["downtime_reason"] == "Equipment breakdown"
        assert (df.loc[breakdown_reason, "equipment_status"]
                == "breakdown").all()

    def test_ideal_rate_matches_line_and_category(self, df):
        expected = df.apply(
            lambda r: IDEAL_RATES_UPH[r["line"]][r["category"]], axis=1)
        assert (df["ideal_rate"] == expected).all()


class TestStoryArcs:
    def test_line_b_has_more_breakdown_hours_than_line_a(self, df):
        breakdown = df[df["downtime_reason"] == "Equipment breakdown"]
        hours = breakdown.groupby("line")["downtime_h"].sum()
        assert hours["Line B"] > hours["Line A"]

    def test_crash_week_crushes_line_b_availability(self, df):
        crash = df[
            (df["line"] == "Line B")
            & (df["date"] >= CRASH_START.isoformat())
            & (df["date"] <= CRASH_END.isoformat())
        ]
        assert len(crash) == 14  # 7 days x 2 shifts
        assert (crash["downtime_reason"] == "Equipment breakdown").all()
        assert (crash["downtime_h"] >= 3.5).all()

    def test_maintenance_programme_cuts_breakdown_downtime(self, df):
        breakdown = df[df["downtime_reason"] == "Equipment breakdown"]
        cutoff = MAINTENANCE_FROM.isoformat()
        before = breakdown[breakdown["date"] < cutoff]["downtime_h"]
        after = breakdown[breakdown["date"] >= cutoff]["downtime_h"]
        assert len(before) > 0 and len(after) > 0
        assert after.mean() < before.mean()

    def test_month_end_push_raises_planned_units(self, df):
        day = pd.to_datetime(df["date"])
        last_day = day.dt.days_in_month
        month_end = (last_day - day.dt.day) < 3
        ratio = df["planned_units"] / (df["ideal_rate"] * PLANNED_TIME_H)
        assert ratio[month_end].mean() > ratio[~month_end].mean()


class TestPlausibility:
    def test_night_shift_performance_lower(self, df):
        perf = df["actual_units"] / (df["ideal_rate"] * df["run_time_h"])
        day = perf[df["shift"] == "Day"].mean()
        night = perf[df["shift"] == "Night"].mean()
        assert night < day

    def test_premium_quality_slightly_lower(self, df):
        qual = df["good_units"] / df["actual_units"]
        standard = qual[df["category"] == "Standard"].mean()
        premium = qual[df["category"] == "Premium"].mean()
        assert premium < standard

    def test_downtime_within_expected_range(self, df):
        crash = (
            (df["line"] == "Line B")
            & (df["date"] >= CRASH_START.isoformat())
            & (df["date"] <= CRASH_END.isoformat())
        )
        assert (df.loc[~crash, "downtime_h"] <= 2.5 + 1e-9).all()
        assert (df.loc[crash, "downtime_h"] <= 6.5 + 1e-9).all()
