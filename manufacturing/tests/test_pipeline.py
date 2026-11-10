"""Tests for the SQLite pipeline and the JSON contract.

Builds the database and JSON once into a temporary folder, then checks the
SQL quality gates, the SQL versus Python KPI agreement, and the exported
JSON contract.
"""

import json
import math
import sqlite3

import pandas as pd
import pytest

import build_mfg_data as build_mod
import kpis
from generate_data import IDEAL_RATES_UPH, generate


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    folder = tmp_path_factory.mktemp("mfg")
    db_path = folder / "manufacturing.db"
    json_path = folder / "mfg_data.json"
    summary = build_mod.build(db_path, json_path)
    return {"db": db_path, "json": json_path, "summary": summary}


@pytest.fixture(scope="module")
def payload(built):
    return json.loads(built["json"].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw_df():
    return generate()


class TestDatabase:
    def test_row_counts(self, built):
        con = sqlite3.connect(built["db"])
        try:
            runs = con.execute(
                "SELECT COUNT(*) FROM production_runs").fetchone()[0]
            lines = con.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
            products = con.execute(
                "SELECT COUNT(*) FROM products").fetchone()[0]
            rates = con.execute(
                "SELECT COUNT(*) FROM line_products").fetchone()[0]
            events = con.execute(
                "SELECT COUNT(*) FROM downtime_events").fetchone()[0]
        finally:
            con.close()
        assert runs == 2190
        assert lines == 3
        assert products == 2
        assert rates == 6
        assert 0 < events <= 2190

    def test_quality_checks_return_zero_rows(self, built):
        con = sqlite3.connect(built["db"])
        try:
            qc_names = []
            for name, sql in build_mod.load_queries():
                if name.startswith("qc_"):
                    qc_names.append(name)
                    rows = con.execute(sql).fetchall()
                    assert rows == [], f"{name} returned offending rows"
        finally:
            con.close()
        assert len(qc_names) == 6

    def test_analytical_queries_return_rows(self, built):
        con = sqlite3.connect(built["db"])
        try:
            analytical = 0
            for name, sql in build_mod.load_queries():
                if not name.startswith("qc_"):
                    analytical += 1
                    assert len(con.execute(sql).fetchall()) > 0, name
        finally:
            con.close()
        assert analytical == 5

    def test_monthly_oee_query_matches_python_kpis(self, built, raw_df):
        """The SQL monthly OEE for one month and line must equal the kpis.py
        aggregation on the same slice of the raw data."""
        month, line = "2026-03", "Line B"
        con = sqlite3.connect(built["db"])
        try:
            sql = dict(build_mod.load_queries())["monthly_oee_by_line"]
            rows = con.execute(sql).fetchall()
        finally:
            con.close()
        sql_row = next(r for r in rows if r[0] == month and r[1] == line)

        sliced = raw_df[(raw_df["date"].str.startswith(month))
                        & (raw_df["line"] == line)]
        expected = kpis.aggregate_kpis(sliced)

        # The SQL query rounds to 2 decimal places.
        assert sql_row[2] == pytest.approx(expected["availability_pct"], abs=0.005)
        assert sql_row[3] == pytest.approx(expected["performance_pct"], abs=0.005)
        assert sql_row[4] == pytest.approx(expected["quality_pct"], abs=0.005)
        assert sql_row[5] == pytest.approx(expected["oee_pct"], abs=0.01)


class TestJsonContract:
    def test_strict_parse_no_nan_or_infinity(self, built):
        text = built["json"].read_text(encoding="utf-8")

        def reject(constant):
            raise AssertionError(f"Non finite constant in JSON: {constant}")

        parsed = json.loads(text, parse_constant=reject)
        assert isinstance(parsed, dict)

    def test_top_level_keys(self, payload):
        assert set(payload.keys()) == {
            "meta", "rows", "kpis_overall", "downtime_pareto", "scenario"}

    def test_meta_contract(self, payload):
        meta = payload["meta"]
        assert meta["project"] == "Manufacturing Performance Analytics"
        assert meta["synthetic"] is True
        assert meta["seed"] == 42
        assert meta["date_range"] == {"start": "2025-11-01",
                                      "end": "2026-10-31"}
        assert meta["lines"] == ["Line A", "Line B", "Line C"]
        assert meta["shifts"] == ["Day", "Night"]
        assert meta["categories"] == ["Standard", "Premium"]
        assert meta["ideal_rates_uph"] == IDEAL_RATES_UPH
        assert meta["planned_time_h_per_shift"] == 7.5
        assert meta["cost_assumptions"]["energy_rm_per_kwh"] == 0.08
        assert meta["cost_assumptions"]["material_rm_per_kg"] == 1.2
        assert meta["cost_assumptions"]["value_rm_per_good_unit"] == 2.5
        assert meta["cost_assumptions"]["note"] == "illustrative only"
        assert len(meta["definitions"]) == 10
        assert 6 <= len(meta["assumptions"]) <= 10

    def test_rows_contract(self, payload):
        rows = payload["rows"]
        assert len(rows) == 2190
        keys = {"d", "line", "shift", "cat", "plan", "act", "good", "rej",
                "pt", "rt", "dt", "reason", "status", "kwh", "mat"}
        for row in rows:
            assert set(row.keys()) == keys
            assert isinstance(row["plan"], int)
            assert isinstance(row["act"], int)
            assert isinstance(row["good"], int)
            assert isinstance(row["rej"], int)
            assert row["pt"] == 7.5
            assert row["rt"] + row["dt"] == pytest.approx(7.5)
            assert row["good"] <= row["act"]

    def test_kpis_overall_matches_recomputation_from_rows(self, payload):
        """The dashboard recomputes the overall KPIs in JS from the rows.
        The published kpis_overall must match that recomputation."""
        df = build_mod.rows_to_df(payload["rows"])
        recomputed = build_mod.round_kpis(kpis.aggregate_kpis(df))
        assert payload["kpis_overall"] == recomputed
        for value in payload["kpis_overall"].values():
            assert not math.isnan(value)

    def test_kpi_keys(self, payload):
        expected = {
            "production_achievement_pct", "capacity_utilisation_pct",
            "yield_pct", "rejection_rate_pct", "availability_pct",
            "performance_pct", "quality_pct", "oee_pct",
            "energy_intensity_kwh_per_good_unit", "downtime_hours_total"}
        assert set(payload["kpis_overall"].keys()) == expected
        assert set(payload["scenario"]["kpis_baseline"].keys()) == expected
        assert set(payload["scenario"]["kpis_improved"].keys()) == expected

    def test_downtime_pareto_contract(self, payload):
        pareto = payload["downtime_pareto"]
        assert len(pareto) >= 3
        hours = [p["hours"] for p in pareto]
        assert hours == sorted(hours, reverse=True)
        assert pareto[-1]["cum_pct"] == pytest.approx(100.0, abs=0.05)
        assert sum(p["pct"] for p in pareto) == pytest.approx(100.0, abs=0.1)
        for entry in pareto:
            assert set(entry.keys()) == {"reason", "hours", "pct", "cum_pct"}
            assert entry["reason"] != "None"

    def test_scenario_contract(self, payload):
        scenario = payload["scenario"]
        assert scenario["name"] == "Changeover reduction programme (what-if)"
        assert scenario["description"]
        assert "modelled, not measured" in scenario["assumptions"]
        assert scenario["kpis_baseline"] == payload["kpis_overall"]
        improved = scenario["kpis_improved"]
        baseline = scenario["kpis_baseline"]
        # Less downtime, higher availability and OEE in the what-if.
        assert improved["downtime_hours_total"] < baseline["downtime_hours_total"]
        assert improved["availability_pct"] > baseline["availability_pct"]
        assert improved["oee_pct"] > baseline["oee_pct"]

    def test_no_em_dash_in_json(self, built):
        text = built["json"].read_text(encoding="utf-8")
        assert "—" not in text  # em dash
        assert "–" not in text  # en dash
