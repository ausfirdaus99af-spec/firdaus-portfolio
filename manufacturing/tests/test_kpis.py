"""Tests for the pure KPI functions. All figures are synthetic hand examples."""

import math

import pandas as pd
import pytest

import kpis


# Hand example used throughout: planned 100, actual 90, good 85, rejected 5,
# planned time 7.5 h, run time 7.0 h, ideal rate 1200 units per hour.
PLAN, ACT, GOOD, REJ = 100, 90, 85, 5
PT, RT, IDEAL = 7.5, 7.0, 1200


class TestScalarKpis:
    def test_production_achievement(self):
        assert kpis.production_achievement_pct(ACT, PLAN) == pytest.approx(90.0)

    def test_capacity_utilisation(self):
        # 90 / (1200 x 7.5) x 100 = 1.0
        assert kpis.capacity_utilisation_pct(ACT, IDEAL, PT) == pytest.approx(1.0)

    def test_yield(self):
        assert kpis.yield_pct(GOOD, ACT) == pytest.approx(85 / 90 * 100)

    def test_rejection_rate(self):
        assert kpis.rejection_rate_pct(REJ, ACT) == pytest.approx(5 / 90 * 100)

    def test_yield_plus_rejection_is_100(self):
        total = kpis.yield_pct(GOOD, ACT) + kpis.rejection_rate_pct(REJ, ACT)
        assert total == pytest.approx(100.0)

    def test_availability(self):
        assert kpis.availability_pct(RT, PT) == pytest.approx(7.0 / 7.5 * 100)

    def test_performance(self):
        # (90 / 7.0) / 1200 x 100
        expected = (ACT / RT) / IDEAL * 100
        assert kpis.performance_pct(ACT, RT, IDEAL) == pytest.approx(expected)

    def test_performance_realistic_example(self):
        # 7700 units in 7.0 h at ideal 1200 uph: (1100 / 1200) x 100
        assert kpis.performance_pct(7700, 7.0, 1200) == pytest.approx(
            7700 / 7.0 / 1200 * 100
        )

    def test_performance_is_not_capped(self):
        # 10000 units in 7.0 h at ideal 1200 uph beats nameplate.
        value = kpis.performance_pct(10000, 7.0, 1200)
        assert value > 100.0

    def test_quality(self):
        assert kpis.quality_pct(GOOD, ACT) == pytest.approx(85 / 90 * 100)

    def test_oee(self):
        avail = kpis.availability_pct(RT, PT)
        perf = kpis.performance_pct(7700, RT, IDEAL)
        qual = kpis.quality_pct(GOOD, ACT)
        expected = avail * perf * qual / 10000.0
        assert kpis.oee_pct(avail, perf, qual) == pytest.approx(expected)

    def test_oee_known_value(self):
        # 93.33 x 91.67 x 98.70 / 10000 = 84.44 (to 2 decimal places)
        assert kpis.oee_pct(93.33, 91.67, 98.70) == pytest.approx(84.44, abs=0.01)

    def test_energy_intensity(self):
        assert kpis.energy_intensity_kwh_per_good_unit(3000.0, 7600) == (
            pytest.approx(3000.0 / 7600)
        )


class TestZeroDenominators:
    def test_zero_planned(self):
        assert math.isnan(kpis.production_achievement_pct(90, 0))

    def test_zero_capacity(self):
        assert math.isnan(kpis.capacity_utilisation_pct(90, 0, 7.5))
        assert math.isnan(kpis.capacity_utilisation_pct(90, 1200, 0))

    def test_zero_actual(self):
        assert math.isnan(kpis.yield_pct(0, 0))
        assert math.isnan(kpis.rejection_rate_pct(0, 0))
        assert math.isnan(kpis.quality_pct(0, 0))

    def test_zero_planned_time(self):
        assert math.isnan(kpis.availability_pct(7.0, 0))

    def test_zero_run_time_or_rate(self):
        assert math.isnan(kpis.performance_pct(90, 0, 1200))
        assert math.isnan(kpis.performance_pct(90, 7.0, 0))

    def test_oee_propagates_nan(self):
        assert math.isnan(kpis.oee_pct(math.nan, 90.0, 95.0))
        assert math.isnan(kpis.oee_pct(90.0, math.nan, 95.0))
        assert math.isnan(kpis.oee_pct(90.0, 95.0, math.nan))

    def test_zero_good_units(self):
        assert math.isnan(kpis.energy_intensity_kwh_per_good_unit(3000.0, 0))


def _frame(rows):
    return pd.DataFrame(rows)


class TestWeightedAggregation:
    def test_weighted_quality_beats_naive_mean(self):
        """Counterexample: a naive mean of row percentages is wrong.

        Row 1: 1000 actual, 900 good (90 percent).
        Row 2: 10 actual, 10 good (100 percent).
        Naive mean quality: 95 percent. Correct weighted quality:
        910 / 1010 = 90.099 percent.
        """
        df = _frame([
            {"planned_units": 1000, "actual_units": 1000, "good_units": 900,
             "rejected_units": 100, "planned_time_h": 7.5, "run_time_h": 7.5,
             "downtime_h": 0.0, "energy_kwh": 500.0, "ideal_rate": 1200},
            {"planned_units": 10, "actual_units": 10, "good_units": 10,
             "rejected_units": 0, "planned_time_h": 7.5, "run_time_h": 7.5,
             "downtime_h": 0.0, "energy_kwh": 160.0, "ideal_rate": 1200},
        ])
        result = kpis.aggregate_kpis(df)
        naive = (90.0 + 100.0) / 2
        correct = 910 / 1010 * 100
        assert result["quality_pct"] == pytest.approx(correct)
        assert abs(result["quality_pct"] - naive) > 4.0

    def test_weighted_performance_beats_naive_mean(self):
        """Row 1 runs 7 h at 100 percent of ideal, row 2 runs 1 h at
        50 percent. Naive mean is 75 percent; the time weighted figure is
        9000 / 9600 = 93.75 percent."""
        df = _frame([
            {"planned_units": 8400, "actual_units": 8400, "good_units": 8400,
             "rejected_units": 0, "planned_time_h": 7.5, "run_time_h": 7.0,
             "downtime_h": 0.5, "energy_kwh": 3000.0, "ideal_rate": 1200},
            {"planned_units": 1200, "actual_units": 600, "good_units": 600,
             "rejected_units": 0, "planned_time_h": 7.5, "run_time_h": 1.0,
             "downtime_h": 6.5, "energy_kwh": 400.0, "ideal_rate": 1200},
        ])
        result = kpis.aggregate_kpis(df)
        assert result["performance_pct"] == pytest.approx(9000 / 9600 * 100)
        naive = ((8400 / 7.0 / 1200) + (600 / 1.0 / 1200)) / 2 * 100
        assert abs(result["performance_pct"] - naive) > 10.0

    def test_aggregate_matches_scalar_functions_on_one_row(self):
        df = _frame([
            {"planned_units": 8280, "actual_units": 7700, "good_units": 7600,
             "rejected_units": 100, "planned_time_h": 7.5, "run_time_h": 7.0,
             "downtime_h": 0.5, "energy_kwh": 3000.0, "ideal_rate": 1200},
        ])
        result = kpis.aggregate_kpis(df)
        assert result["availability_pct"] == pytest.approx(
            kpis.availability_pct(7.0, 7.5))
        assert result["performance_pct"] == pytest.approx(
            kpis.performance_pct(7700, 7.0, 1200))
        assert result["quality_pct"] == pytest.approx(
            kpis.quality_pct(7600, 7700))
        assert result["oee_pct"] == pytest.approx(kpis.oee_pct(
            result["availability_pct"], result["performance_pct"],
            result["quality_pct"]))
        assert result["capacity_utilisation_pct"] == pytest.approx(
            kpis.capacity_utilisation_pct(7700, 1200, 7.5))
        assert result["downtime_hours_total"] == pytest.approx(0.5)

    def test_aggregate_oee_is_product_of_components(self):
        df = _frame([
            {"planned_units": 8280, "actual_units": 7700, "good_units": 7600,
             "rejected_units": 100, "planned_time_h": 7.5, "run_time_h": 7.0,
             "downtime_h": 0.5, "energy_kwh": 3000.0, "ideal_rate": 1200},
            {"planned_units": 6210, "actual_units": 5000, "good_units": 4900,
             "rejected_units": 100, "planned_time_h": 7.5, "run_time_h": 6.0,
             "downtime_h": 1.5, "energy_kwh": 2100.0, "ideal_rate": 900},
        ])
        r = kpis.aggregate_kpis(df)
        assert r["oee_pct"] == pytest.approx(
            r["availability_pct"] * r["performance_pct"] * r["quality_pct"]
            / 10000.0
        )


class TestDowntimePareto:
    def test_pareto_shares_and_order(self):
        df = _frame([
            {"downtime_reason": "Changeover", "downtime_h": 6.0},
            {"downtime_reason": "Cleaning", "downtime_h": 3.0},
            {"downtime_reason": "Changeover", "downtime_h": 0.0},
            {"downtime_reason": "Quality stop", "downtime_h": 1.0},
            {"downtime_reason": "None", "downtime_h": 0.05},
        ])
        pareto = kpis.downtime_pareto(df)
        reasons = [p["reason"] for p in pareto]
        assert reasons == ["Changeover", "Cleaning", "Quality stop"]
        assert pareto[0]["hours"] == pytest.approx(6.0)
        assert pareto[0]["pct"] == pytest.approx(60.0)
        assert pareto[0]["cum_pct"] == pytest.approx(60.0)
        assert pareto[1]["cum_pct"] == pytest.approx(90.0)
        assert pareto[2]["cum_pct"] == pytest.approx(100.0)

    def test_pareto_excludes_none(self):
        df = _frame([
            {"downtime_reason": "None", "downtime_h": 0.05},
            {"downtime_reason": "Cleaning", "downtime_h": 2.0},
        ])
        pareto = kpis.downtime_pareto(df)
        assert [p["reason"] for p in pareto] == ["Cleaning"]
        assert pareto[0]["pct"] == pytest.approx(100.0)
