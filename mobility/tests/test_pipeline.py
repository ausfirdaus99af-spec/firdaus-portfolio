"""Tests for the KL Mobility Lab pipeline.

Run from the mobility folder:  python -I -m pytest tests -q

The whole pipeline (including the SQLite build and all SQL queries) runs
once per session against the real raw files, then every test checks a
different invariant of the outputs.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_mobility_data as bm  # noqa: E402


@pytest.fixture(scope="session")
def built():
    return bm.build_all(write=True)


# ---------------------------------------------------------------------------
# Ridership
# ---------------------------------------------------------------------------

def test_group_mapping_covers_every_service_column_exactly_once():
    raw = pd.read_parquet(bm.RAW / "ridership_headline.parquet")
    service_cols = [c for c in raw.columns if c != "date"]
    mapped = [c for cols in bm.SERVICE_GROUPS.values() for c in cols]
    assert len(mapped) == len(set(mapped)), "a column appears in two groups"
    assert sorted(mapped) == sorted(service_cols)


def test_monthly_totals_equal_raw_daily_sums(built):
    raw = pd.read_parquet(bm.RAW / "ridership_headline.parquet")
    monthly = built["monthly"].set_index("m")
    for group, cols in bm.SERVICE_GROUPS.items():
        raw_sum = int(raw[cols].sum(axis=1).sum())
        monthly_sum = int(monthly[group].sum())
        assert monthly_sum == raw_sum, f"{group}: {monthly_sum} != raw {raw_sum}"


def test_monthly_covers_2019_01_to_2026_08(built):
    months = [r["m"] for r in built["data"]["ridership"]["monthly"]]
    assert months[0] == "2019-01"
    assert months[-1] == "2026-08"
    assert len(months) == 92
    assert months == sorted(months)


def test_weekday_profile_shape(built):
    prof = built["data"]["ridership"]["weekday_profile_2026"]
    assert [p["dow"] for p in prof] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert all(p["rail_avg"] > 0 for p in prof)


# ---------------------------------------------------------------------------
# Rail OD
# ---------------------------------------------------------------------------

def test_od_top_list_lengths(built):
    od = built["data"]["od"]
    assert len(od["top_pairs"]) == 20
    assert len(od["top_origins"]) == 10
    assert len(od["top_destinations"]) == 10


def test_od_no_same_station_pairs(built):
    for p in built["data"]["od"]["top_pairs"]:
        assert p["o"] != p["d"], f"same-station pair in top list: {p}"


def test_normalisation_collapses_known_variants():
    # Two real interchange stations that appear in the raw 2026 file under
    # two line codes each.
    assert bm.normalise_station("AG07: Masjid Jamek") == "Masjid Jamek"
    assert bm.normalise_station("KJ13: Masjid Jamek") == "Masjid Jamek"
    assert bm.normalise_station("MR01: KL Sentral") == "KL Sentral"
    assert bm.normalise_station("KJ15: KL Sentral") == "KL Sentral"


def test_normalisation_variants_present_in_raw_data(built):
    o_map = built["od"]["origin_map"]
    assert o_map["AG07: Masjid Jamek"] == o_map["KJ13: Masjid Jamek"]
    assert o_map["MR01: KL Sentral"] == o_map["KJ15: KL Sentral"]


def test_od_totals_preserved(built):
    od = built["od"]
    # Normalisation must not change the station-level trip total.
    assert int(od["detail"]["ridership"].sum()) == od["detail_total"]
    # The published marginals (origin or destination "All Stations") each
    # duplicate the station-level total, so the raw file grand total is
    # exactly three times the real OD total.
    assert od["raw_total"] == 3 * od["detail_total"]
    # Top lists derive from the same total: every exported average must be
    # positive and no larger than the network-wide daily average.
    daily_avg = od["detail_total"] / od["n_days"]
    for entry in od["top_origins"] + od["top_destinations"]:
        assert 0 < entry["avg_daily"] < daily_avg


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

def test_registrations_monthly_sums_equal_raw_row_count(built):
    raw = pd.read_parquet(bm.RAW / "cars_2026.parquet")
    monthly = built["data"]["registrations"]["monthly"]
    total = sum(
        r["selangor"] + r["kl"] + r["rakan_niaga"] + r["other"] for r in monthly
    )
    assert total == len(raw)


def test_registrations_months_2026(built):
    months = [r["m"] for r in built["data"]["registrations"]["monthly"]]
    assert months == [f"2026-{m:02d}" for m in range(1, 10)]


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def test_sql_qc_queries_empty_and_analytical_non_empty(built):
    results = built["query_results"]
    qc = [k for k in results if k.startswith("qc_")]
    analytical = [k for k in results if not k.startswith("qc_")]
    assert len(qc) >= 3
    assert len(analytical) >= 5
    for k in qc:
        assert results[k] == [], f"{k} returned rows"
    for k in analytical:
        assert results[k], f"{k} returned no rows"


def test_sql_yoy_query_matches_pandas(built):
    """Cross-check the recovery query against an independent pandas
    computation of monthly rail trips and the 2019 baseline."""
    rows = built["query_results"]["yoy_monthly_rail_recovery_vs_2019"]
    sql = {ym: (trips, base) for ym, trips, base, _pct in rows}
    monthly = built["monthly"].set_index("m")["rail"]
    for ym, (trips, base) in sql.items():
        assert trips == int(monthly[ym]), f"trips mismatch for {ym}"
        assert base == int(monthly[f"2019-{ym[5:7]}"]), f"baseline mismatch for {ym}"
    assert len(sql) == 92


# ---------------------------------------------------------------------------
# JSON contract and stops
# ---------------------------------------------------------------------------

def test_json_contract_keys_and_strict_parse(built):
    path = bm.OUT / "mobility_data.json"
    text = path.read_text(encoding="utf-8")

    def reject(const):
        raise AssertionError(f"non-strict JSON constant in file: {const}")

    data = json.loads(text, parse_constant=reject)
    assert set(data.keys()) == {
        "meta", "ridership", "od", "registrations", "population",
        "employment", "citations", "simulator_defaults",
    }
    assert set(data["meta"]) >= {
        "project", "generated_at", "observed_vs_modelled", "licences", "gaps"
    }
    assert 6 <= len(data["meta"]["gaps"]) <= 8
    for row in data["ridership"]["monthly"]:
        assert set(row) == {"m", "rail", "bus", "ktmb"}
    for p in data["od"]["top_pairs"]:
        assert set(p) == {"o", "d", "avg_daily"}
    for r in data["registrations"]["monthly"]:
        assert set(r) == {"m", "selangor", "kl", "rakan_niaga", "other"}
    assert set(data["citations"]) == {
        "migration", "tomtom", "worldbank_2015", "spad_mode_share"
    }
    sim = data["simulator_defaults"]
    assert sim["car_commuters"] == 1500000
    assert sim["co2_kg_per_l"] == 2.31
    assert "assumptions" in sim["note"]


def test_stops_json_contract(built):
    stops = json.loads((bm.OUT / "stops.json").read_text(encoding="utf-8"))
    assert len(stops) == 187
    for s in stops:
        assert set(s) == {"name", "lat", "lon"}
        assert isinstance(s["name"], str) and s["name"]
        # Klang Valley bounding box.
        assert 2.5 <= s["lat"] <= 3.6, s
        assert 101.0 <= s["lon"] <= 102.0, s
