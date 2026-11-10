"""Deterministic rule-based Design Improvement Advisor for the SNG plant study.

This module reviews one flowsheet scenario as the design under review. Five
rules turn the model outputs into findings. Each rule has explicit numeric
thresholds. They live in THRESHOLDS and are copied into the output JSON.
The rules and formulas are written up in docs/ADVISOR_METHODOLOGY.md.

Integrity rules this module is built around:

1. Nothing is hardcoded as a discovery. Every finding is computed from model
   runs for the scenario under review. When the design is fine the rule
   returns a cleared check (status "no_action_justified"). Cleared checks
   are kept in the output on purpose.
2. Impact figures come from model runs of the changed design. They carry
   stated assumptions and a sensitivity range (low, base, high). There are
   no fixed saving percentages.
3. Every recommendation that changes the process carries a quality gate on
   product quality. The gate value is computed where the model allows it.
4. Evidence computed from the model is kept apart from hypotheses. Every
   possible cause is tagged with its basis.

All public functions are pure: no file or network access.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Standard layout, no reliance on the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_sng_data as build  # noqa: E402
import sng_model as m  # noqa: E402

OPERATING_HOURS = 8000.0

# Every numeric decision point in the rules, in one place. These are
# engineering review thresholds, not discoveries: changing them changes
# which findings fire, and they are published in the output JSON.
THRESHOLDS = {
    "R1": {
        "co2_shortfall_fire_pp": 5.0,
        "co2_shortfall_high_severity_pp": 30.0,
        "h2_slip_low_molpct": 0.5,
        "co2_removal_sensitivity_fractions": [0.85, 0.90, 0.95],
    },
    "R2": {
        "recoverable_fraction_low": 0.60,
        "recoverable_fraction_base": 0.725,
        "recoverable_fraction_high": 0.85,
        "operating_hours_per_year": OPERATING_HOURS,
    },
    "R3": {
        "spec_basis": "illustrative pipeline quality values, dry basis, not a contract spec",
        "ch4_min_dry_molpct": 95.0,
        "co_max_dry_molpct": 0.1,
        "inerts_max_dry_molpct": 4.0,
    },
    "R4": {
        "co_limit_molpct": 0.1,
        "margin_pp": 1.0,
        "search_range_conversion_pct": [85.0, 100.0],
    },
    "R5": {
        "latent_heat_kj_per_kg": 2400.0,
    },
}

_FINDING_KEYS = (
    "id",
    "title",
    "status",
    "severity",
    "problem",
    "evidence",
    "possible_causes",
    "recommendation",
    "expected_impact",
    "tradeoffs",
    "quality_gate",
    "validation_required",
)


def _finding(**kwargs) -> dict:
    """Build a finding dict with the contract's exact key order."""
    unknown = set(kwargs) - set(_FINDING_KEYS)
    if unknown:
        raise ValueError(f"unknown finding keys: {sorted(unknown)}")
    out = {key: kwargs.get(key) for key in _FINDING_KEYS}
    if out["possible_causes"] is None:
        out["possible_causes"] = []
    if out["validation_required"] is None:
        out["validation_required"] = []
    return out


def _r(value, ndigits: int = 2):
    """Round to ndigits; None and non-finite values become None (JSON null)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return round(v, ndigits) + 0.0


def _n(value, ndigits: int = 1) -> str:
    """Format a rounded number for text, with thousands separators."""
    v = _r(value, ndigits)
    if v is None:
        return "n/a"
    return f"{v:,.{ndigits}f}"


def _dry_molpct(flows) -> dict:
    """Composition in mol percent on a dry basis (water excluded)."""
    dry_total = m.total_flow_kmol_h(flows) - float(flows.get("H2O", 0.0))
    if dry_total <= 0.0:
        return {sp: 0.0 for sp in m.SPECIES}
    out = {}
    for sp in m.SPECIES:
        if sp == "H2O":
            out[sp] = 0.0
        else:
            out[sp] = 100.0 * float(flows.get(sp, 0.0)) / dry_total
    return out


# --------------------------------------------------------------------- context


def build_context(scenario_key: str = "base", dataset: dict | None = None,
                  settings: dict | None = None, feed_kmol_h: float | None = None) -> dict:
    """Run the model for one scenario and gather everything the rules need.

    settings and feed_kmol_h can override the named scenario, which lets
    tests review constructed designs through the same code path. dataset
    supplies the sensitivity sweeps and the other scenarios as evidence.
    """
    if dataset is None:
        dataset = build.build_dataset()
    if settings is None:
        settings = build.SCENARIO_SETTINGS[scenario_key]
    if feed_kmol_h is None:
        feed_kmol_h = build.find_base_feed_kmol_h()
    feed = build.feed_flows_from_composition(settings["composition"], feed_kmol_h)

    def run_variant(**overrides):
        kwargs = dict(
            co_conversion=settings["co_conversion"],
            co2_conversion=settings["co2_conversion"],
            co2_removal_fraction=build.CO2_REMOVAL_FRACTION,
            water_knockout_fraction=build.WATER_KNOCKOUT_FRACTION,
            wgs_target=settings["wgs_target"],
        )
        kwargs.update(overrides)
        return m.run_flowsheet(feed, **kwargs)

    result = run_variant()
    energy, total_cooling_kw = build.energy_summary(result)
    return {
        "scenario_key": scenario_key,
        "label": settings.get("label", scenario_key),
        "settings": settings,
        "feed_kmol_h": feed_kmol_h,
        "feed": feed,
        "result": result,
        "energy": energy,
        "total_cooling_kw": total_cooling_kw,
        "run_variant": run_variant,
        "sweep_co_conversion": dataset["sensitivity"]["co_conversion"],
        "sweep_co2_removal": dataset["sensitivity"]["co2_removal"],
        "scenarios": dataset["scenarios"],
    }


# --------------------------------------------------------------------- R1


def rule_r1_hydrogen_stoichiometry(context: dict) -> dict:
    """R1: is the methanation step starved of hydrogen by the shift target?"""
    t = THRESHOLDS["R1"]
    settings = context["settings"]
    result = context["result"]
    meth = result["methanation"]

    requested_co = 100.0 * settings["co_conversion"]
    requested_co2 = 100.0 * settings["co2_conversion"]
    achieved_co = 100.0 * meth["co_conversion_achieved"]
    achieved_co2 = 100.0 * meth["co2_conversion_achieved"]
    shortfall_pp = requested_co2 - achieved_co2
    h2_out_kmol = float(result["after_methanation"].get("H2", 0.0))
    sng_dry = _dry_molpct(result["sng"])

    problem = (
        "Checks whether the methanation step runs short of hydrogen. "
        "The model flags this itself (h2_limited). "
        f"The check fires when the flag is set and achieved CO2 conversion "
        f"falls over {t['co2_shortfall_fire_pp']:.0f} points short."
    )

    fired = bool(meth["h2_limited"]) and shortfall_pp > t["co2_shortfall_fire_pp"]
    if not fired:
        return _finding(
            id="R1",
            title="Hydrogen supply to the methanation step",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    "The methanation step has enough hydrogen. "
                    "Achieved conversions match the catalyst capability set in the model."
                ),
                "details": [
                    f"Requested CO conversion {_n(requested_co)} percent; achieved {_n(achieved_co)} percent.",
                    f"Requested CO2 conversion {_n(requested_co2)} percent; achieved {_n(achieved_co2)} percent.",
                    f"Hydrogen leaving the reactor: {_n(h2_out_kmol)} kmol/h.",
                    "The model's hydrogen shortage flag (h2_limited) is not set.",
                ],
            },
            possible_causes=[],
            recommendation=(
                "No action justified by this check. "
                "Keep the hydrogen check in the model for future design changes."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    # Impact: run the balanced shift target in the same model, same feed.
    run = context["run_variant"]
    balanced = run(wgs_target="stoichiometric")
    bal_energy, _ = build.energy_summary(balanced)
    des_energy = context["energy"]

    def duty(energy, unit, kind=None):
        for d in energy["duties"]:
            if d["unit"] == unit and (kind is None or d["kind"] == kind):
                return float(d["duty_kw"])
        return 0.0

    des_sng_kg = m.stream_mass_kg_h(result["sng"])
    bal_sng_kg = m.stream_mass_kg_h(balanced["sng"])
    sng_change = bal_sng_kg - des_sng_kg
    des_steam = result["steam_kmol_h"] * m.MOLAR_MASS["H2O"]
    bal_steam = balanced["steam_kmol_h"] * m.MOLAR_MASS["H2O"]
    steam_change = bal_steam - des_steam
    des_co2_dry = sng_dry["CO2"]
    bal_dry = _dry_molpct(balanced["sng"])
    bal_co2_dry = bal_dry["CO2"]
    bal_h2_dry = bal_dry["H2"]
    bal_co_dry = bal_dry["CO"]
    bal_achieved_co2 = 100.0 * balanced["methanation"]["co2_conversion_achieved"]
    shift_cool_change = duty(bal_energy, "U3", "cooling") - duty(des_energy, "U3", "cooling")
    total_cool_change = bal_energy["total_cooling_kw"] - des_energy["total_cooling_kw"]
    annual_change_mt = m.annual_production_mt(sng_change, OPERATING_HOURS)

    # Sensitivity: production loss at three CO2 removal fractions, with the
    # retargeted design compared against the design case at the same removal.
    losses = []
    for f in t["co2_removal_sensitivity_fractions"]:
        design_f = run(co2_removal_fraction=f)
        balanced_f = run(wgs_target="stoichiometric", co2_removal_fraction=f)
        losses.append(m.stream_mass_kg_h(design_f["sng"]) - m.stream_mass_kg_h(balanced_f["sng"]))
    base_loss = losses[1]
    low_loss, high_loss = min(losses), max(losses)

    severity = "high" if shortfall_pp > t["co2_shortfall_high_severity_pp"] else "medium"

    co_limit = THRESHOLDS["R3"]["co_max_dry_molpct"]
    gate_passes = bal_co_dry <= co_limit
    gate_note_pass = (
        f"Computed CO after the change: {_n(bal_co_dry, 2)} mol percent dry. "
        f"That is within the {co_limit} limit."
    )
    gate_note_fail = (
        f"Computed CO after the change: {_n(bal_co_dry, 2)} mol percent dry "
        f"(was {_n(sng_dry['CO'], 2)}). "
        f"It improves but stays above the {co_limit} limit. "
        "Closing that gap needs the separate measures in R3 and R4."
    )

    return _finding(
        id="R1",
        title="Hydrogen supply to the methanation step",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"The catalyst can convert {_n(requested_co2)} percent of the CO2. "
                f"The gas only lets it reach {_n(achieved_co2)} percent. "
                f"Hydrogen runs out first: {_n(h2_out_kmol, 2)} kmol/h of H2 leaves the reactor. "
                f"CO2 left in the dry product: {_n(des_co2_dry, 2)} mol percent."
            ),
            "details": [
                f"Requested CO conversion {_n(requested_co)} percent; achieved {_n(achieved_co)} percent.",
                (
                    f"Requested CO2 conversion {_n(requested_co2)} percent; achieved "
                    f"{_n(achieved_co2)} percent. Shortfall {_n(shortfall_pp)} points "
                    f"(fires above {t['co2_shortfall_fire_pp']:.0f}; high severity above "
                    f"{t['co2_shortfall_high_severity_pp']:.0f})."
                ),
                (
                    f"Hydrogen leaving the reactor: {_n(h2_out_kmol, 2)} kmol/h. "
                    f"Near-zero slip (under {t['h2_slip_low_molpct']} mol percent) confirms the shortage."
                ),
                (
                    "Cause in the model: the shift step targets H2/CO = 3. "
                    "That ratio feeds the CO reaction only. "
                    "It leaves no hydrogen for the CO2 reaction."
                ),
            ],
        },
        possible_causes=[
            {
                "cause": (
                    "The shift extent target covers CO methanation only. "
                    "This is read straight from the model settings and flows."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    "In a real plant, shift catalyst decay or bypassing could add to the shortfall."
                ),
                "basis": "hypothesis",
            },
        ],
        recommendation=(
            "Retarget the shift extent to full methanation stoichiometry "
            "(the model's wgs_target \"stoichiometric\" mode). "
            "It makes exactly enough hydrogen for both methanation reactions. "
            "Review the trade-offs below before adopting it."
        ),
        expected_impact={
            "summary": (
                "The retargeted design was run in the same model, same feed. "
                f"CO2 in the dry product falls from {_n(des_co2_dry, 2)} to {_n(bal_co2_dry, 2)} mol percent. "
                f"Achieved CO2 conversion rises from {_n(achieved_co2)} to {_n(bal_achieved_co2)} percent. "
                f"SNG production falls by {_n(-sng_change)} kg/h. "
                f"Steam use rises by {_n(steam_change)} kg/h."
            ),
            "calculations": [
                {"label": "CO2 in dry product, design", "value": _r(des_co2_dry), "unit": "mol %"},
                {"label": "CO2 in dry product, after retarget", "value": _r(bal_co2_dry), "unit": "mol %"},
                {"label": "achieved CO2 conversion after retarget", "value": _r(bal_achieved_co2, 1), "unit": "%"},
                {"label": "SNG production change", "value": _r(sng_change, 1), "unit": "kg/h"},
                {"label": "annual production change", "value": _r(annual_change_mt, 1), "unit": "MT/yr"},
                {"label": "shift steam change", "value": _r(steam_change, 1), "unit": "kg/h"},
                {"label": "shift reactor cooling change", "value": _r(shift_cool_change, 1), "unit": "kW"},
                {"label": "total cooling change", "value": _r(total_cool_change, 1), "unit": "kW"},
                {"label": "H2 in dry product after retarget", "value": _r(bal_h2_dry), "unit": "mol %"},
            ],
            "assumptions": [
                "Both designs run at the same feed rate and the same catalyst conversions.",
                f"Annual figures assume {OPERATING_HOURS:,.0f} operating hours per year.",
                "The CO2 removal step keeps its design removal fraction in the base comparison.",
            ],
            "sensitivity": {
                "low": _r(low_loss, 1),
                "base": _r(base_loss, 1),
                "high": _r(high_loss, 1),
                "unit": "kg/h SNG production loss",
                "description": (
                    "Production loss from the retarget, computed at CO2 removal of "
                    + ", ".join(f"{100 * f:.0f}" for f in t["co2_removal_sensitivity_fractions"])
                    + " percent. Each point compares the two designs at the same removal."
                ),
            },
        },
        tradeoffs=(
            f"The fix costs product. SNG output falls by {_n(-sng_change)} kg/h "
            f"({_n(-100.0 * sng_change / des_sng_kg)} percent). "
            f"Steam demand rises by {_n(steam_change)} kg/h "
            f"({_n(100.0 * steam_change / des_steam)} percent). "
            f"Unreacted hydrogen ({_n(bal_h2_dry)} mol percent dry) leaves in the product. "
            f"Shift reactor cooling rises by {_n(shift_cool_change)} kW."
        ),
        quality_gate={
            "check": (
                f"CO in the dry product must stay within {co_limit} mol percent after the change."
            ),
            "outcome": "passed" if gate_passes else "conditional",
            "note": gate_note_pass if gate_passes else gate_note_fail,
        },
        validation_required=[
            "A shift reactor check that the larger extent is feasible at the catalyst's conditions.",
            "A steam supply check for the higher make-up rate.",
        ],
    )


# --------------------------------------------------------------------- R2


def rule_r2_heat_integration(context: dict) -> dict:
    """R2: can methanation reaction heat replace the external feed preheat?"""
    t = THRESHOLDS["R2"]
    energy = context["energy"]
    preheat_kw = next(float(d["duty_kw"]) for d in energy["duties"] if d["kind"] == "heating")
    meth_kw = next(float(d["duty_kw"]) for d in energy["duties"] if d["unit"] == "U5")

    fractions = {
        "low": t["recoverable_fraction_low"],
        "base": t["recoverable_fraction_base"],
        "high": t["recoverable_fraction_high"],
    }
    recoverable = {k: f * meth_kw for k, f in fractions.items()}
    saving = {k: min(v, preheat_kw) for k, v in recoverable.items()}
    hours = t["operating_hours_per_year"]

    problem = (
        "The methanation reactor gives off a lot of heat. "
        "The feed needs heating before the shift reactor. "
        "This check compares the two duties from the energy block. "
        f"It fires when recoverable reactor heat "
        f"({100 * fractions['low']:.0f} to {100 * fractions['high']:.0f} percent assumed) "
        "exceeds the preheat duty at the base estimate."
    )
    base_details = [
        f"Methanation reactor cooling duty: {_n(meth_kw)} kW.",
        f"Feed preheat duty (40 to 300 C): {_n(preheat_kw)} kW.",
        (
            f"Recoverable heat: {_n(recoverable['low'])} kW at {100 * fractions['low']:.0f} percent, "
            f"{_n(recoverable['base'])} kW at {100 * fractions['base']:.1f} percent, "
            f"{_n(recoverable['high'])} kW at {100 * fractions['high']:.0f} percent."
        ),
    ]

    if not (recoverable["base"] > preheat_kw):
        return _finding(
            id="R2",
            title="Heat integration: reactor heat against feed preheat",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"Recoverable reactor heat ({_n(recoverable['base'])} kW at the base estimate) "
                    f"does not exceed the preheat duty ({_n(preheat_kw)} kW). "
                    "A feed-effluent exchanger is not justified by this check."
                ),
                "details": base_details,
            },
            possible_causes=[],
            recommendation=(
                "No action justified by this check. "
                "Re-run it if the reactor duty or the preheat target changes."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    severity = "high" if recoverable["low"] > preheat_kw else "medium"
    annual_kwh = saving["base"] * hours
    remaining_cool = meth_kw - saving["base"]
    all_capped = all(recoverable[k] >= preheat_kw for k in fractions)

    return _finding(
        id="R2",
        title="Heat integration: reactor heat against feed preheat",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"Reactor cooling duty is {_n(meth_kw)} kW. "
                f"Feed preheat duty is {_n(preheat_kw)} kW. "
                f"Even the low recovery estimate ({_n(recoverable['low'])} kW) covers the preheat."
            ),
            "details": base_details,
        },
        possible_causes=[
            {
                "cause": (
                    "The design heats the feed with outside utility. "
                    "At the same time it rejects far more reactor heat to cooling. "
                    "Both duties are computed in the energy block."
                ),
                "basis": "observed",
            },
        ],
        recommendation=(
            "Add a feed-effluent heat exchanger (gas-gas interchanger). "
            "Let the hot reactor outlet heat the incoming feed. "
            "This removes the external preheat duty."
        ),
        expected_impact={
            "summary": (
                f"The exchanger removes the whole preheat duty: {_n(saving['base'])} kW. "
                f"That is {_n(annual_kwh, 0)} kWh per year at {hours:,.0f} hours. "
                f"Reactor cooling still needed after recovery: {_n(remaining_cool)} kW."
            ),
            "calculations": [
                {"label": "methanation reactor cooling duty", "value": _r(meth_kw, 1), "unit": "kW"},
                {"label": "feed preheat duty", "value": _r(preheat_kw, 1), "unit": "kW"},
                {
                    "label": f"recoverable heat at {100 * fractions['low']:.0f} percent",
                    "value": _r(recoverable["low"], 1),
                    "unit": "kW",
                },
                {
                    "label": f"recoverable heat at {100 * fractions['high']:.0f} percent",
                    "value": _r(recoverable["high"], 1),
                    "unit": "kW",
                },
                {"label": "preheat duty eliminated", "value": _r(saving["base"], 1), "unit": "kW"},
                {"label": "annual heating saved", "value": _r(annual_kwh, 0), "unit": "kWh/yr"},
                {"label": "reactor cooling remaining after recovery", "value": _r(remaining_cool, 1), "unit": "kW"},
            ],
            "assumptions": [
                (
                    f"Between {100 * fractions['low']:.0f} and {100 * fractions['high']:.0f} percent "
                    "of the reactor heat is recoverable at useful temperature."
                ),
                f"The plant runs {hours:,.0f} hours per year.",
                "The exchanger can be sized to deliver the full preheat duty.",
            ],
            "sensitivity": {
                "low": _r(saving["low"], 1),
                "base": _r(saving["base"], 1),
                "high": _r(saving["high"], 1),
                "unit": "kW",
                "description": (
                    "Saving equals the smaller of recoverable heat and the preheat duty."
                    + (
                        " All three recovery estimates exceed the preheat duty here. "
                        "So the saving is capped at the preheat duty in every case."
                        if all_capped
                        else " Lower recovery fractions cover only part of the preheat duty."
                    )
                ),
            },
        },
        tradeoffs=(
            "An exchanger adds capital cost and pressure drop. "
            "Start-up needs a separate heater until the reactor is hot."
        ),
        quality_gate={
            "check": "Product quality must not change. Heat exchange moves heat only, not mass.",
            "outcome": "conditional",
            "note": (
                "In this model the product composition is unchanged by the exchanger. "
                "A real design must still hold the reactor inlet temperature. "
                "Confirm product purity during commissioning."
            ),
        },
        validation_required=[
            "Exchanger sizing with real approach temperatures (not in this model).",
            "A start-up heater sized for cold starts.",
        ],
    )


# --------------------------------------------------------------------- R3


def rule_r3_product_specification(context: dict) -> dict:
    """R3: compare the dry product against an illustrative pipeline spec."""
    t = THRESHOLDS["R3"]
    sng = context["result"]["sng"]
    dry = _dry_molpct(sng)
    feed_comp = m.composition_molpct(context["feed"])

    ch4 = dry["CH4"]
    co = dry["CO"]
    inerts = dry["CO2"] + dry["N2"]
    ch4_gap = max(0.0, t["ch4_min_dry_molpct"] - ch4)
    co_gap = max(0.0, co - t["co_max_dry_molpct"])
    inerts_gap = max(0.0, inerts - t["inerts_max_dry_molpct"])
    misses = [g > 0.0 for g in (ch4_gap, co_gap, inerts_gap)]

    problem = (
        "Compares the dry product with an illustrative pipeline specification. "
        f"The spec is CH4 above {t['ch4_min_dry_molpct']:.0f}, CO below "
        f"{t['co_max_dry_molpct']}, inert gas (CO2 plus N2) below "
        f"{t['inerts_max_dry_molpct']:.0f} mol percent. "
        "These are illustrative values, not a contract spec. "
        "The check fires when any component is out."
    )

    if not any(misses):
        return _finding(
            id="R3",
            title="Product gas against pipeline quality",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    "The dry product meets all three illustrative limits. "
                    f"CH4 {_n(ch4)}, CO {_n(co, 2)}, inert gas {_n(inerts)} mol percent."
                ),
                "details": [
                    f"CH4: {_n(ch4)} against above {t['ch4_min_dry_molpct']:.0f} mol percent.",
                    f"CO: {_n(co, 2)} against below {t['co_max_dry_molpct']} mol percent.",
                    f"Inert gas (CO2 plus N2): {_n(inerts)} against below {t['inerts_max_dry_molpct']:.0f} mol percent.",
                ],
            },
            possible_causes=[],
            recommendation=(
                "No action justified by this check. "
                "Re-check it after any change to the feed or the flowsheet."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    severity = "high" if (ch4_gap > 0.0 or inerts_gap > 0.0) else "medium"
    n_missed = sum(misses)

    details = []
    if ch4_gap > 0.0:
        details.append(
            f"CH4 is {_n(ch4)} mol percent against above {t['ch4_min_dry_molpct']:.0f}. "
            f"Gap: {_n(ch4_gap)} points. "
            "Closing it means removing inert gas and slip, see the items below."
        )
    else:
        details.append(f"CH4 is {_n(ch4)} mol percent and meets the limit.")
    if co_gap > 0.0:
        details.append(
            f"CO is {_n(co, 2)} mol percent against below {t['co_max_dry_molpct']}. "
            f"Gap: {_n(co_gap, 2)} points. "
            "Candidates: hydrogen recycle, a polishing methanation stage, or a membrane. "
            "Each is a hypothesis to evaluate, not a sized design."
        )
    else:
        details.append(f"CO is {_n(co, 2)} mol percent and meets the limit.")
    if inerts_gap > 0.0:
        details.append(
            f"Inert gas is {_n(inerts)} mol percent against below {t['inerts_max_dry_molpct']:.0f}. "
            f"N2 alone is {_n(dry['N2'])} points and CO2 is {_n(dry['CO2'])} points. "
            "Deeper CO2 removal addresses the CO2 share. "
            "N2 must be managed at the gasifier, for example oxygen or indirect gasification. "
            "Both are hypotheses to evaluate, not sized designs."
        )
    else:
        details.append(f"Inert gas is {_n(inerts)} mol percent and meets the limit.")

    sweep = context.get("sweep_co2_removal") or []
    if sweep and ch4_gap > 0.0:
        deepest = max(sweep, key=lambda p: p["x"])
        details.append(
            "Evidence from the CO2 removal sweep: deeper removal helps but cannot close the CH4 gap alone. "
            f"At {_n(deepest['x'], 0)} percent removal the purity reaches "
            f"{_n(deepest['ch4_purity_dry_pct'])} percent CH4."
        )

    return _finding(
        id="R3",
        title="Product gas against pipeline quality",
        status="action_recommended",
        severity=severity,
        problem=problem,
        evidence={
            "summary": (
                f"The dry product misses {n_missed} of 3 illustrative limits. "
                f"CH4 {_n(ch4)} (wants above {t['ch4_min_dry_molpct']:.0f}), "
                f"CO {_n(co, 2)} (limit {t['co_max_dry_molpct']}), "
                f"inert gas {_n(inerts)} (limit {t['inerts_max_dry_molpct']:.0f}) mol percent."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": (
                    f"N2 enters at {_n(feed_comp['N2'])} mol percent of the feed. "
                    f"It passes through untouched and concentrates to {_n(dry['N2'])} in the dry product."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    "CO2 slips past the removal step and past the hydrogen-starved methanation (see R1)."
                ),
                "basis": "observed",
            },
            {
                "cause": (
                    f"CO slips through at the design conversion "
                    f"({_n(100.0 * context['settings']['co_conversion'])} percent), see R4."
                ),
                "basis": "observed",
            },
        ],
        recommendation=(
            "Evaluate three design additions as studies, not sized equipment. "
            "One: deeper CO2 removal, to cut the CO2 share of the inerts. "
            "Two: hydrogen recycle or a membrane, to cut CO and H2 slip. "
            "Three: nitrogen management at the gasifier, such as oxygen or indirect gasification. "
            "Each needs its own balance, cost and quality case before adoption."
        ),
        expected_impact=None,
        tradeoffs=(
            "Each addition adds cost and complexity. "
            "Deeper CO2 removal also cuts the product mass flow."
        ),
        quality_gate=None,
        validation_required=[
            "A gasification study for low-nitrogen syngas (oxygen or indirect gasification).",
            "A CO2 removal depth study with product purity and energy balanced.",
            "A CO and H2 slip study (recycle, polishing stage or membrane).",
        ],
    )


# --------------------------------------------------------------------- R4


def _bisect_required_conversion(run_variant, limit_molpct: float,
                                lo: float = 0.85, hi: float = 1.0,
                                iterations: int = 60):
    """Lowest CO conversion (percent) that keeps product CO within the limit.

    Deterministic bisection on the model. Returns None when even full
    conversion cannot meet the limit.
    """

    def co_at(x: float) -> float:
        res = run_variant(co_conversion=x)
        return m.composition_molpct(res["sng"])["CO"]

    if co_at(hi) > limit_molpct:
        return None
    if co_at(lo) <= limit_molpct:
        return 100.0 * lo
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if co_at(mid) <= limit_molpct:
            hi = mid
        else:
            lo = mid
    return 100.0 * hi


def rule_r4_co_slip(context: dict) -> dict:
    """R4: CO in the product against the limit, across the conversion sweep."""
    t = THRESHOLDS["R4"]
    limit = t["co_limit_molpct"]
    margin = t["margin_pp"]
    sweep = context.get("sweep_co_conversion") or []
    design_pct = 100.0 * context["settings"]["co_conversion"]
    current_co = m.composition_molpct(context["result"]["sng"])["CO"]

    passing = [p for p in sweep if p["co_in_product_molpct"] <= limit]
    sweep_min_safe = min((p["x"] for p in passing), default=None)
    run = context.get("run_variant")

    required_pct = sweep_min_safe
    solve_note = "from the conversion sweep"
    if required_pct is None and run is not None:
        required_pct = _bisect_required_conversion(run, limit)
        solve_note = "from a direct model solve by bisection"

    problem = (
        f"Finds the lowest CO conversion that keeps product CO within {limit} mol percent. "
        "Uses the conversion sweep, plus a direct model solve when the sweep never passes. "
        f"A safe design sits at least {_n(margin)} points above that minimum."
    )

    sweep_lo = min(sweep, key=lambda p: p["x"]) if sweep else None
    sweep_hi = max(sweep, key=lambda p: p["x"]) if sweep else None
    details = []
    if sweep_lo and sweep_hi:
        details.append(
            f"Sweep range: CO in product falls from {_n(sweep_lo['co_in_product_molpct'], 2)} "
            f"at {_n(sweep_lo['x'])} to {_n(sweep_hi['co_in_product_molpct'], 2)} "
            f"at {_n(sweep_hi['x'])} percent conversion."
        )
    if required_pct is not None:
        details.append(
            f"Minimum conversion for the {limit} limit: {_n(required_pct, 2)} percent ({solve_note})."
        )
    else:
        details.append("Even full conversion cannot meet the limit in this design.")
    details.append(
        f"The design runs at {_n(design_pct)} percent conversion. "
        f"Its product holds {_n(current_co, 2)} mol percent CO."
    )
    aged = (context.get("scenarios") or {}).get("aged_catalyst")
    if aged:
        aged_s7 = next(s for s in aged["streams"] if s["id"] == "S7")
        details.append(
            f"Aged catalyst evidence: at {_n(aged['kpis']['co_conversion_pct'])} percent conversion "
            f"the product holds {_n(aged_s7['composition_molpct']['CO'], 2)} mol percent CO."
        )
    details.append(
        "Values are mol percent of the product gas, which holds about half a percent water."
    )

    cleared = (
        required_pct is not None
        and design_pct >= required_pct + margin
        and current_co <= limit
    )
    if cleared:
        return _finding(
            id="R4",
            title="CO slip risk as the catalyst ages",
            status="no_action_justified",
            severity=None,
            problem=problem,
            evidence={
                "summary": (
                    f"The limit is met from {_n(required_pct, 2)} percent conversion. "
                    f"The design runs at {_n(design_pct)} percent. "
                    f"The margin is at least {_n(margin)} points."
                ),
                "details": details,
            },
            possible_causes=[],
            recommendation=(
                f"No design change justified. "
                f"Alarm when CO conversion falls below {_n(required_pct + margin, 2)} percent."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[],
        )

    if required_pct is not None and current_co <= limit:
        # In spec today, but the margin above the minimum is too thin.
        return _finding(
            id="R4",
            title="CO slip risk as the catalyst ages",
            status="conditional",
            severity="medium",
            problem=problem,
            evidence={
                "summary": (
                    f"The product meets the {limit} limit today. "
                    f"But the design sits under {_n(margin)} points above the minimum "
                    f"({_n(required_pct, 2)} percent conversion)."
                ),
                "details": details,
            },
            possible_causes=[
                {
                    "cause": "Any conversion loss, for example ageing, would push CO past the limit.",
                    "basis": "observed",
                },
            ],
            recommendation=(
                f"Fit a product CO analyser with an alarm at {limit} mol percent. "
                f"Alarm too when conversion falls below {_n(required_pct, 2)} percent. "
                "Plan catalyst change-out before conversion decays to that point."
            ),
            expected_impact=None,
            tradeoffs=None,
            quality_gate=None,
            validation_required=[
                "Catalyst vendor data for end-of-run conversion (not in the model).",
            ],
        )

    rec_sentences = [
        f"Fit a product CO analyser with an alarm at {limit} mol percent."
    ]
    if required_pct is not None:
        rec_sentences.append(
            f"Treat CO conversion below {_n(required_pct, 2)} percent as out of spec for this limit."
        )
        rec_sentences.append(
            f"The design at {_n(design_pct)} percent cannot hold that with a "
            f"{_n(margin)} point margin."
        )
    else:
        rec_sentences.append("Conversion alone can never meet the limit in this design.")
    rec_sentences.append(
        "So pair monitoring with a design addition from R3, such as hydrogen recycle."
    )

    return _finding(
        id="R4",
        title="CO slip risk as the catalyst ages",
        status="action_recommended",
        severity="high" if current_co > limit else "medium",
        problem=problem,
        evidence={
            "summary": (
                (
                    f"No sweep point keeps CO within {limit} mol percent. "
                    if sweep_min_safe is None
                    else f"The sweep meets the limit only from {_n(sweep_min_safe)} percent conversion. "
                )
                + (
                    f"The model solve needs {_n(required_pct, 2)} percent conversion. "
                    if required_pct is not None
                    else "Even full conversion cannot meet the limit. "
                )
                + f"The design runs at {_n(design_pct)} percent and gives {_n(current_co, 2)} CO."
            ),
            "details": details,
        },
        possible_causes=[
            {
                "cause": "Unconverted CO passes straight to the product. Nothing downstream removes it.",
                "basis": "observed",
            },
            {
                "cause": "In a real plant, ageing, poisoning or channelling would pull conversion down further.",
                "basis": "hypothesis",
            },
        ],
        recommendation=" ".join(rec_sentences),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "Catalyst vendor data for end-of-run conversion (not in the model).",
            "A product gas analyser specification and calibration plan.",
        ],
    )


# --------------------------------------------------------------------- R5


def rule_r5_model_validation_gaps(context: dict) -> dict:
    """R5: what the model leaves out; always informational, never fabricated."""
    t = THRESHOLDS["R5"]
    result = context["result"]
    energy = context["energy"]
    cond_kg_h = m.stream_mass_kg_h(result["condensate"])
    latent_kw = cond_kg_h * t["latent_heat_kj_per_kg"] / 3600.0
    u6_kw = next(float(d["duty_kw"]) for d in energy["duties"] if d["unit"] == "U6")

    details = [
        (
            "Kinetics and reactor sizing: conversions are inputs, not computed. "
            "A real step solves rate equations and equilibrium at 350 C. "
            "Then it sizes the catalyst bed."
        ),
        (
            "Recycle: there is no product gas recycle. "
            "Real SNG plants recycle gas to control the temperature rise. "
            "Recycle changes conversion per pass and the cooling split."
        ),
        (
            "Condenser duty: only sensible heat is counted. "
            f"The condensed water ({_n(cond_kg_h)} kg/h) also releases latent heat. "
            f"At about {t['latent_heat_kj_per_kg']:,.0f} kJ/kg that is roughly {_n(latent_kw, 0)} kW more cooling. "
            f"The reported condenser duty ({_n(u6_kw)} kW) is therefore understated."
        ),
        (
            "Costs: no capital or operating costs are modelled. "
            "A real step adds equipment costing and utility prices. "
            "Without costs, the findings rank engineering effort, not money."
        ),
    ]

    return _finding(
        id="R5",
        title="What this model leaves out",
        status="informational",
        severity=None,
        problem=(
            "Lists what the model leaves out and what a real design step would add. "
            "Nothing is invented to fill these gaps."
        ),
        evidence={
            "summary": (
                "Four model gaps limit the findings above. "
                "One gap is quantified: the condenser duty misses the latent heat of the water."
            ),
            "details": details,
        },
        possible_causes=[],
        recommendation=(
            "Treat every finding as a screening result. "
            "Close these gaps before committing to equipment: kinetics, recycle, "
            "condenser latent heat and costs."
        ),
        expected_impact=None,
        tradeoffs=None,
        quality_gate=None,
        validation_required=[
            "A kinetic reactor model and bed sizing at the 350 C outlet.",
            "A recycle flowsheet study for reactor temperature control.",
            f"A condenser rating that includes latent heat (about {_n(latent_kw, 0)} kW extra here).",
            "Capital and operating cost estimates for every recommendation.",
        ],
    )


# ------------------------------------------------------------------ runner


def run_advisor(scenario_key: str = "base", dataset: dict | None = None) -> dict:
    """Run all five rules with the named scenario as the design under review.

    Returns {"meta": ..., "findings": [...]} with findings ordered R1 to R5.
    The meta here carries no timestamp, so the result is fully deterministic
    for a given input; the build script adds generated_at when writing JSON.
    """
    context = build_context(scenario_key, dataset)
    findings = [
        rule_r1_hydrogen_stoichiometry(context),
        rule_r2_heat_integration(context),
        rule_r3_product_specification(context),
        rule_r4_co_slip(context),
        rule_r5_model_validation_gaps(context),
    ]
    meta = {
        "method": "deterministic rule-based analysis, rules documented in docs/ADVISOR_METHODOLOGY.md",
        "scenario_analysed": scenario_key,
        "design_basis": {
            "target_sng_kg_h": build.TARGET_SNG_KG_H,
            "operating_hours_per_year": OPERATING_HOURS,
            "feed_kmol_h": _r(context["feed_kmol_h"], 2),
        },
        "thresholds": THRESHOLDS,
        "note": (
            "findings are recomputed from the model on every rebuild; with a different design "
            "they change, including to no action justified. All numbers are synthetic and "
            "educational. The pipeline specification is illustrative only."
        ),
    }
    return {"meta": meta, "findings": findings}
