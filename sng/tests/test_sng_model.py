"""Tests for the educational SNG plant model.

The hand calculation values in these tests were worked out on paper from
the stated stoichiometry, molar masses and heating values, so the model is
checked against numbers it did not produce itself.
"""

import json
import math

import pytest

import build_sng_data as build
import sng_model as m


def flows(**kwargs):
    out = {sp: 0.0 for sp in m.SPECIES}
    out.update({k: float(v) for k, v in kwargs.items()})
    return out


# ---------------------------------------------------------------------------
# Hand example: 100 kmol/h CO + 300 kmol/h H2, full CO conversion, no CO2
# ---------------------------------------------------------------------------

class TestHandExample:
    def setup_method(self):
        self.feed = flows(CO=100.0, H2=300.0)
        self.result = m.methanation(self.feed, co_conversion=1.0, co2_conversion=0.90)

    def test_product_flows(self):
        product = self.result["flows"]
        assert math.isclose(product["CH4"], 100.0, abs_tol=1e-9)
        assert math.isclose(product["H2O"], 100.0, abs_tol=1e-9)
        assert math.isclose(product["CO"], 0.0, abs_tol=1e-9)
        assert math.isclose(product["H2"], 0.0, abs_tol=1e-9)
        assert not self.result["h2_limited"]

    def test_mass_in_equals_mass_out_exactly(self):
        # 100 * 28.01 + 300 * 2.016 = 3405.8 kg/h in
        # 100 * 16.043 + 100 * 18.015 = 3405.8 kg/h out
        mass_in = m.stream_mass_kg_h(self.feed)
        mass_out = m.stream_mass_kg_h(self.result["flows"])
        assert math.isclose(mass_in, 3405.8, abs_tol=1e-9)
        assert math.isclose(mass_out, mass_in, abs_tol=1e-9)

    def test_lhv_and_cold_gas_efficiency_match_hand_calculation(self):
        # Feed LHV = 100 * 283.0 + 300 * 241.8 = 100,840 MJ/h
        # Product LHV = 100 * 802.3 = 80,230 MJ/h
        # Cold gas efficiency = 80,230 / 100,840 * 100 = 79.5617...
        assert math.isclose(m.lhv_mj_h(self.feed), 100840.0, abs_tol=1e-9)
        assert math.isclose(m.lhv_mj_h(self.result["flows"]), 80230.0, abs_tol=1e-9)
        cge = m.cold_gas_efficiency_pct(self.feed, self.result["flows"])
        assert math.isclose(cge, 100.0 * 80230.0 / 100840.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Water gas shift
# ---------------------------------------------------------------------------

class TestWgs:
    def test_base_feed_reaches_h2_co_ratio_of_exactly_3(self):
        feed = flows(H2=40.0, CO=25.0, CO2=20.0, CH4=10.0, N2=4.0, H2O=1.0)
        wgs = m.wgs_extent(feed, target_h2_co_ratio=3.0)
        shifted = m.apply_wgs(feed, wgs["extent_kmol_h"], wgs["steam_kmol_h"])
        assert math.isclose(shifted["H2"] / shifted["CO"], 3.0, rel_tol=1e-12)
        # Hand value: e = (3 * 25 - 40) / 4 = 8.75
        assert math.isclose(wgs["extent_kmol_h"], 8.75, abs_tol=1e-12)

    def test_steam_is_extent_plus_5_percent_excess(self):
        feed = flows(H2=40.0, CO=25.0, H2O=1.0)
        wgs = m.wgs_extent(feed, target_h2_co_ratio=3.0)
        assert math.isclose(
            wgs["steam_kmol_h"], 1.05 * wgs["extent_kmol_h"], rel_tol=1e-12
        )

    def test_extent_is_zero_when_feed_is_already_rich_enough(self):
        feed = flows(H2=80.0, CO=10.0, H2O=1.0)  # ratio 8, above target 3
        wgs = m.wgs_extent(feed, target_h2_co_ratio=3.0)
        assert wgs["extent_kmol_h"] == 0.0
        assert wgs["steam_kmol_h"] == 0.0

    def test_stoichiometric_target_extent_matches_hand_value(self):
        # e = (3 CO + 4 (1 - f) CO2 - H2) / (4 f)
        # Base feed, f = 0.9: e = (75 + 8 - 40) / 3.6 = 11.9444...
        feed = flows(H2=40.0, CO=25.0, CO2=20.0, CH4=10.0, N2=4.0, H2O=1.0)
        wgs = m.wgs_extent_for_methanation(feed, co2_removal_fraction=0.90)
        assert math.isclose(wgs["extent_kmol_h"], 43.0 / 3.6, rel_tol=1e-12)
        assert math.isclose(
            wgs["steam_kmol_h"], 1.05 * wgs["extent_kmol_h"], rel_tol=1e-12
        )

    def test_stoichiometric_target_leaves_enough_hydrogen_for_methanation(self):
        # After the shift and 90 percent CO2 removal the hydrogen must cover
        # full methanation stoichiometry: H2 = 3 CO + 4 CO2.
        feed = flows(H2=40.0, CO=25.0, CO2=20.0, CH4=10.0, N2=4.0, H2O=1.0)
        result = m.run_flowsheet(feed, wgs_target="stoichiometric")
        gas = result["after_co2_removal"]
        assert math.isclose(
            gas["H2"], 3.0 * gas["CO"] + 4.0 * gas["CO2"], rel_tol=1e-12
        )
        meth = result["methanation"]
        assert not meth["h2_limited"]
        assert math.isclose(meth["co_conversion_achieved"], 0.98, rel_tol=1e-12)
        assert math.isclose(meth["co2_conversion_achieved"], 0.90, rel_tol=1e-12)


# ---------------------------------------------------------------------------
# Hydrogen limited guard
# ---------------------------------------------------------------------------

class TestH2LimitedGuard:
    def test_low_hydrogen_feed_gives_no_negative_flows(self):
        feed = flows(H2=1.0, CO=50.0, CO2=20.0, CH4=2.0, N2=3.0, H2O=1.0)
        result = m.methanation(feed, co_conversion=0.98, co2_conversion=0.90)
        assert result["h2_limited"]
        for sp, n in result["flows"].items():
            assert n >= 0.0, f"{sp} went negative: {n}"

    def test_zero_hydrogen_feed_converts_nothing(self):
        feed = flows(CO=50.0, CO2=20.0)
        result = m.methanation(feed, co_conversion=0.98, co2_conversion=0.90)
        assert result["h2_limited"]
        assert result["extent_co_kmol_h"] == 0.0
        assert result["extent_co2_kmol_h"] == 0.0

    def test_whole_flowsheet_never_produces_negative_flows(self):
        feed = build.feed_flows_from_composition(
            {"H2": 5.0, "CO": 60.0, "CO2": 30.0, "CH4": 2.0, "N2": 2.0, "H2O": 1.0},
            100.0,
        )
        result = m.run_flowsheet(feed)
        for key in ("after_wgs", "after_co2_removal", "after_methanation", "sng"):
            for sp, n in result[key].items():
                assert n >= 0.0, f"{key}/{sp} went negative: {n}"


# ---------------------------------------------------------------------------
# Element and mass balances for every scenario
# ---------------------------------------------------------------------------

ALL_SCENARIOS = ["base", "h2_rich", "aged_catalyst", "balanced_ratio"]


@pytest.fixture(scope="module")
def dataset():
    return build.build_dataset()


@pytest.mark.parametrize("key", ALL_SCENARIOS)
def test_element_balances_close_within_point_1_percent(key):
    settings = build.SCENARIO_SETTINGS[key]
    feed = build.feed_flows_from_composition(
        settings["composition"], build.find_base_feed_kmol_h()
    )
    result = m.run_flowsheet(
        feed,
        co_conversion=settings["co_conversion"],
        co2_conversion=settings["co2_conversion"],
        wgs_target=settings["wgs_target"],
    )
    balance = result["mass_balance"]
    for el in m.ELEMENTS:
        el_in = balance["elements_in_kg_h"][el]
        el_out = balance["elements_out_kg_h"][el]
        if el_in > 0.0:
            assert abs(el_out - el_in) / el_in <= 0.001, f"{key}/{el} did not close"


@pytest.mark.parametrize("key", ALL_SCENARIOS)
def test_total_mass_balance_closes_within_point_1_percent(dataset, key):
    balance = dataset["scenarios"][key]["mass_balance"]
    assert abs(balance["closure_pct"] - 100.0) <= 0.1
    assert abs(balance["out_kg_h"] - balance["in_kg_h"]) / balance["in_kg_h"] <= 0.001


# ---------------------------------------------------------------------------
# KPI sanity: purity bounds, production target, energy signs
# ---------------------------------------------------------------------------

def test_base_case_hits_production_target_within_2_percent(dataset):
    kpis = dataset["scenarios"]["base"]["kpis"]
    assert abs(kpis["sng_kg_h"] - 2750.0) / 2750.0 <= 0.02
    assert abs(kpis["annual_mt"] - 22000.0) / 22000.0 <= 0.02


@pytest.mark.parametrize("key", ALL_SCENARIOS)
def test_purities_and_efficiencies_are_between_0_and_100(dataset, key):
    kpis = dataset["scenarios"][key]["kpis"]
    for name in ("ch4_purity_dry_molpct", "co_conversion_pct",
                 "ch4_yield_pct", "cold_gas_efficiency_pct"):
        assert 0.0 <= kpis[name] <= 100.0, f"{key}/{name} out of bounds"


@pytest.mark.parametrize("key", ALL_SCENARIOS)
def test_energy_signs_and_methanation_duty_is_cooling(dataset, key):
    energy = dataset["scenarios"][key]["energy"]
    meth_duties = [d for d in energy["duties"] if d["unit"] == "U5"]
    assert meth_duties, "no methanation duty reported"
    for duty in meth_duties:
        assert duty["kind"] == "cooling"
        assert duty["duty_kw"] > 0.0
    for duty in energy["duties"]:
        assert duty["duty_kw"] >= 0.0
        assert duty["kind"] in ("electrical", "heating", "cooling")
    assert energy["total_cooling_kw"] > 0.0
    assert energy["total_heating_kw"] > 0.0
    assert energy["total_electrical_kw"] > 0.0


# ---------------------------------------------------------------------------
# JSON contract
# ---------------------------------------------------------------------------

class TestJsonContract:
    def test_strict_json_round_trip_and_top_level_keys(self, dataset):
        parsed = json.loads(json.dumps(dataset))
        assert set(parsed.keys()) == {"meta", "process", "scenarios", "sensitivity"}

    def test_meta_block(self, dataset):
        meta = dataset["meta"]
        assert meta["project"] == "SNG Plant Design"
        assert meta["synthetic"] is True
        assert 8 <= len(meta["assumptions"]) <= 12
        assert 2 <= len(meta["references"]) <= 4
        assert set(meta["units"].keys()) == {
            "flow", "mass_flow", "duty", "temperature", "pressure"
        }

    def test_exactly_four_scenarios_with_expected_keys(self, dataset):
        assert set(dataset["scenarios"].keys()) == {
            "base", "h2_rich", "aged_catalyst", "balanced_ratio"
        }
        for scenario in dataset["scenarios"].values():
            assert set(scenario.keys()) == {
                "label", "description", "feed", "steam_kg_h",
                "streams", "mass_balance", "energy", "kpis",
            }

    def test_process_units_u1_to_u6(self, dataset):
        units = dataset["process"]["units"]
        assert [u["id"] for u in units] == ["U1", "U2", "U3", "U4", "U5", "U6"]

    def test_streams_cover_every_unit_plus_by_products(self, dataset):
        for key, scenario in dataset["scenarios"].items():
            ids = [s["id"] for s in scenario["streams"]]
            assert ids == ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "BP1", "BP2"], key
            after = [s["after_unit"] for s in scenario["streams"]]
            assert after[0] is None
            assert after[1:7] == ["U1", "U2", "U3", "U4", "U5", "U6"]

    def test_sweep_point_counts(self, dataset):
        assert len(dataset["sensitivity"]["co_conversion"]) == 30
        assert len(dataset["sensitivity"]["co2_removal"]) == 10

    def test_sweep_ranges_and_fields(self, dataset):
        co_sweep = dataset["sensitivity"]["co_conversion"]
        assert co_sweep[0]["x"] == 85.0
        assert co_sweep[-1]["x"] == 99.5
        for point in co_sweep:
            assert set(point.keys()) == {
                "x", "ch4_purity_dry_pct", "sng_kg_h", "co_in_product_molpct"
            }
        co2_sweep = dataset["sensitivity"]["co2_removal"]
        assert co2_sweep[0]["x"] == 50.0
        assert co2_sweep[-1]["x"] == 95.0
        for point in co2_sweep:
            assert set(point.keys()) == {
                "x", "ch4_purity_dry_pct", "sng_kg_h", "specific_cooling_kwh_kg"
            }
