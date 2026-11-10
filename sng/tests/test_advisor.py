"""Tests for the deterministic Design Improvement Advisor.

Every rule is tested both ways: a case where it fires and a case where it
clears. The firing numbers are checked against values computed here from
the same model, so the advisor cannot hardcode a discovery unnoticed.
"""

import json

import pytest

import advisor
import build_advisor
import build_sng_data as build
import sng_model as m

ALLOWED_STATUSES = {
    "action_recommended", "conditional", "no_action_justified", "informational"
}


@pytest.fixture(scope="module")
def dataset():
    return build.build_dataset()


@pytest.fixture(scope="module")
def base_run(dataset):
    return advisor.run_advisor("base", dataset)


@pytest.fixture(scope="module")
def balanced_run(dataset):
    return advisor.run_advisor("balanced_ratio", dataset)


def get_finding(run, rule_id):
    return next(f for f in run["findings"] if f["id"] == rule_id)


def calc_value(finding, label):
    for item in finding["expected_impact"]["calculations"]:
        if item["label"] == label:
            return item["value"]
    raise AssertionError(f"no calculation labelled {label!r}")


# ---------------------------------------------------------------------------
# R1 hydrogen stoichiometry
# ---------------------------------------------------------------------------

class TestR1:
    def test_fires_on_base_with_computed_impact(self, base_run, dataset):
        f = get_finding(base_run, "R1")
        assert f["status"] == "action_recommended"
        assert f["severity"] == "high"
        # Impact numbers must match an independent pair of model runs here.
        feed = build.feed_flows_from_composition(
            build.BASE_COMPOSITION_MOLPCT, build.find_base_feed_kmol_h()
        )
        design = m.run_flowsheet(feed, wgs_target="ratio")
        balanced = m.run_flowsheet(feed, wgs_target="stoichiometric")
        expected_sng_change = (
            m.stream_mass_kg_h(balanced["sng"]) - m.stream_mass_kg_h(design["sng"])
        )
        expected_steam_change = (
            balanced["steam_kmol_h"] - design["steam_kmol_h"]
        ) * m.MOLAR_MASS["H2O"]
        assert calc_value(f, "SNG production change") == pytest.approx(
            expected_sng_change, abs=1.0
        )
        assert calc_value(f, "shift steam change") == pytest.approx(
            expected_steam_change, abs=1.0
        )
        # The retarget restores the full requested CO2 conversion.
        assert calc_value(f, "achieved CO2 conversion after retarget") == pytest.approx(
            90.0, abs=0.1
        )

    def test_quality_gate_is_computed_and_honest_on_base(self, base_run):
        f = get_finding(base_run, "R1")
        gate = f["quality_gate"]
        # The balanced product still carries CO above the 0.1 limit,
        # so the gate must not claim a pass.
        assert gate["outcome"] == "conditional"
        assert "0.1" in gate["check"]

    def test_sensitivity_is_ordered_and_from_model_runs(self, base_run):
        f = get_finding(base_run, "R1")
        s = f["expected_impact"]["sensitivity"]
        assert s["low"] <= s["base"] <= s["high"]
        assert s["low"] > 0.0  # production loss is real at every removal fraction
        assert f["expected_impact"]["assumptions"]

    def test_clears_on_balanced_ratio_scenario(self, balanced_run):
        f = get_finding(balanced_run, "R1")
        assert f["status"] == "no_action_justified"
        assert f["severity"] is None
        assert f["expected_impact"] is None


# ---------------------------------------------------------------------------
# R2 heat integration
# ---------------------------------------------------------------------------

class TestR2:
    def test_fires_on_base_with_duties_from_energy_block(self, base_run, dataset):
        f = get_finding(base_run, "R2")
        assert f["status"] == "action_recommended"
        assert f["severity"] == "high"
        duties = dataset["scenarios"]["base"]["energy"]["duties"]
        preheat = next(d["duty_kw"] for d in duties if d["kind"] == "heating")
        meth = next(d["duty_kw"] for d in duties if d["unit"] == "U5")
        assert calc_value(f, "feed preheat duty") == pytest.approx(preheat, abs=0.5)
        assert calc_value(f, "methanation reactor cooling duty") == pytest.approx(meth, abs=0.5)
        assert calc_value(f, "preheat duty eliminated") == pytest.approx(preheat, abs=0.5)
        assert calc_value(f, "annual heating saved") == pytest.approx(
            preheat * 8000.0, rel=0.01
        )
        assert calc_value(f, "reactor cooling remaining after recovery") == pytest.approx(
            meth - preheat, abs=1.0
        )

    def test_saving_is_capped_at_preheat_in_every_sensitivity_case(self, base_run, dataset):
        f = get_finding(base_run, "R2")
        duties = dataset["scenarios"]["base"]["energy"]["duties"]
        preheat = next(d["duty_kw"] for d in duties if d["kind"] == "heating")
        s = f["expected_impact"]["sensitivity"]
        for key in ("low", "base", "high"):
            assert s[key] == pytest.approx(preheat, abs=0.5)

    def test_quality_gate_present_because_rule_changes_the_process(self, base_run):
        f = get_finding(base_run, "R2")
        assert f["quality_gate"] is not None
        assert f["quality_gate"]["outcome"] in ("passed", "conditional")

    def test_clears_on_low_exotherm_fixture(self, dataset):
        settings = {
            "label": "Low exotherm fixture",
            "description": "Constructed design with almost no methanation heat.",
            "composition": build.BASE_COMPOSITION_MOLPCT,
            "co_conversion": 0.02,
            "co2_conversion": 0.0,
            "wgs_target": "ratio",
        }
        context = advisor.build_context("base", dataset, settings=settings)
        f = advisor.rule_r2_heat_integration(context)
        assert f["status"] == "no_action_justified"
        assert f["severity"] is None
        assert f["expected_impact"] is None


# ---------------------------------------------------------------------------
# R3 product specification gap
# ---------------------------------------------------------------------------

class TestR3:
    def test_fires_on_base_with_computed_gaps(self, base_run, dataset):
        f = get_finding(base_run, "R3")
        assert f["status"] == "action_recommended"
        assert f["severity"] == "high"
        summary = f["evidence"]["summary"]
        ch4_dry = dataset["scenarios"]["base"]["kpis"]["ch4_purity_dry_molpct"]
        assert f"{ch4_dry:.1f}" in summary  # the computed purity appears as evidence
        assert "misses 3 of 3" in summary
        # One design addition hypothesis per out-of-spec component.
        text = " ".join(f["evidence"]["details"]) + " " + f["recommendation"]
        assert "CO2 removal" in text
        assert "recycle" in text or "membrane" in text
        assert "gasifi" in text  # gasifier or gasification

    def test_no_sized_design_is_claimed(self, base_run):
        f = get_finding(base_run, "R3")
        assert f["expected_impact"] is None
        assert len(f["validation_required"]) == 3

    def test_clears_on_in_spec_fixture(self, dataset):
        settings = {
            "label": "In-spec fixture",
            "description": "Constructed feed that is already almost pure methane.",
            "composition": {"H2": 2.0, "CO": 0.0, "CO2": 1.0,
                            "CH4": 96.0, "N2": 0.5, "H2O": 0.5},
            "co_conversion": 0.98,
            "co2_conversion": 0.90,
            "wgs_target": "ratio",
        }
        context = advisor.build_context(
            "base", dataset, settings=settings, feed_kmol_h=100.0
        )
        f = advisor.rule_r3_product_specification(context)
        assert f["status"] == "no_action_justified"
        assert f["severity"] is None


# ---------------------------------------------------------------------------
# R4 CO slip risk
# ---------------------------------------------------------------------------

class TestR4:
    def test_fires_on_base_and_reports_required_conversion(self, base_run, dataset):
        f = get_finding(base_run, "R4")
        assert f["status"] == "action_recommended"
        assert f["severity"] == "high"
        # No sweep point reaches 0.1 mol percent CO in the base design.
        sweep = dataset["sensitivity"]["co_conversion"]
        assert all(p["co_in_product_molpct"] > 0.1 for p in sweep)
        # The model solve must land between the sweep top and full conversion.
        context = advisor.build_context("base", dataset)
        required = advisor._bisect_required_conversion(context["run_variant"], 0.1)
        assert required is not None
        assert 99.5 < required < 100.0
        assert f"{required:.2f}" in f["evidence"]["summary"]

    def test_uses_aged_catalyst_scenario_as_evidence(self, base_run, dataset):
        f = get_finding(base_run, "R4")
        aged_s7 = next(
            s for s in dataset["scenarios"]["aged_catalyst"]["streams"] if s["id"] == "S7"
        )
        aged_co = aged_s7["composition_molpct"]["CO"]
        assert any(f"{aged_co:.2f}" in d for d in f["evidence"]["details"])

    def test_clears_on_sweep_that_meets_the_limit_with_margin(self):
        sng = {sp: 0.0 for sp in m.SPECIES}
        sng.update({"CH4": 96.0, "CO": 0.05, "CO2": 0.45,
                    "N2": 1.0, "H2": 2.0, "H2O": 0.5})
        context = {
            "settings": {"co_conversion": 0.98},
            "result": {"sng": sng},
            "sweep_co_conversion": [
                {"x": 95.0, "co_in_product_molpct": 0.30},
                {"x": 96.0, "co_in_product_molpct": 0.08},
                {"x": 97.0, "co_in_product_molpct": 0.05},
            ],
        }
        f = advisor.rule_r4_co_slip(context)
        assert f["status"] == "no_action_justified"
        assert "97.00" in f["recommendation"]  # alarm at minimum plus margin

    def test_conditional_when_in_spec_but_margin_is_thin(self):
        sng = {sp: 0.0 for sp in m.SPECIES}
        sng.update({"CH4": 96.0, "CO": 0.05, "CO2": 0.45,
                    "N2": 1.0, "H2": 2.0, "H2O": 0.5})
        context = {
            "settings": {"co_conversion": 0.98},
            "result": {"sng": sng},
            "sweep_co_conversion": [
                {"x": 97.5, "co_in_product_molpct": 0.09},
                {"x": 98.0, "co_in_product_molpct": 0.05},
            ],
        }
        f = advisor.rule_r4_co_slip(context)
        assert f["status"] == "conditional"
        assert f["severity"] == "medium"


# ---------------------------------------------------------------------------
# R5 model validation gaps
# ---------------------------------------------------------------------------

class TestR5:
    def test_informational_with_computed_latent_heat(self, base_run, dataset):
        f = get_finding(base_run, "R5")
        assert f["status"] == "informational"
        assert f["severity"] is None
        condensate = next(
            s for s in dataset["scenarios"]["base"]["streams"] if s["id"] == "BP2"
        )
        latent_kw = condensate["flow_kg_h"] * 2400.0 / 3600.0
        assert any(f"{latent_kw:,.0f}" in d for d in f["evidence"]["details"])
        assert len(f["validation_required"]) == 4

    def test_informational_on_every_scenario(self, balanced_run):
        f = get_finding(balanced_run, "R5")
        assert f["status"] == "informational"


# ---------------------------------------------------------------------------
# Determinism and JSON contract
# ---------------------------------------------------------------------------

class TestContract:
    FINDING_KEYS = [
        "id", "title", "status", "severity", "problem", "evidence",
        "possible_causes", "recommendation", "expected_impact", "tradeoffs",
        "quality_gate", "validation_required",
    ]

    def test_identical_output_on_repeated_runs(self, dataset):
        first = advisor.run_advisor("base", dataset)
        second = advisor.run_advisor("base", dataset)
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_deterministic_across_fresh_datasets(self):
        first = advisor.run_advisor("base", build.build_dataset())
        second = advisor.run_advisor("base", build.build_dataset())
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_top_level_shape_and_meta(self, base_run):
        assert set(base_run.keys()) == {"meta", "findings"}
        meta = base_run["meta"]
        assert set(meta["thresholds"].keys()) == {"R1", "R2", "R3", "R4", "R5"}
        assert "note" in meta
        assert meta["scenario_analysed"] == "base"
        assert "ADVISOR_METHODOLOGY" in meta["method"]

    def test_findings_follow_the_contract(self, base_run):
        assert [f["id"] for f in base_run["findings"]] == ["R1", "R2", "R3", "R4", "R5"]
        for f in base_run["findings"]:
            assert list(f.keys()) == self.FINDING_KEYS
            assert f["status"] in ALLOWED_STATUSES
            assert f["severity"] in ("high", "medium", "low", None)
            assert isinstance(f["evidence"], dict)
            assert set(f["evidence"].keys()) == {"summary", "details"}
            for cause in f["possible_causes"]:
                assert set(cause.keys()) == {"cause", "basis"}
                assert cause["basis"] in ("observed", "hypothesis")
            if f["expected_impact"] is not None:
                impact = f["expected_impact"]
                assert set(impact.keys()) == {
                    "summary", "calculations", "assumptions", "sensitivity"
                }
                s = impact["sensitivity"]
                assert {"low", "base", "high", "unit", "description"} <= set(s.keys())
            if f["quality_gate"] is not None:
                assert set(f["quality_gate"].keys()) == {"check", "outcome", "note"}

    def test_strict_json_round_trip(self, base_run):
        text = json.dumps(base_run, allow_nan=False)
        assert json.loads(text) == base_run

    def test_build_advisor_writes_valid_file(self, tmp_path):
        path = build_advisor.build(out_dir=tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "generated_at" in payload["meta"]
        assert len(payload["findings"]) == 5

    def test_statuses_on_base_match_the_design_problems(self, base_run):
        statuses = {f["id"]: f["status"] for f in base_run["findings"]}
        assert statuses == {
            "R1": "action_recommended",
            "R2": "action_recommended",
            "R3": "action_recommended",
            "R4": "action_recommended",
            "R5": "informational",
        }
