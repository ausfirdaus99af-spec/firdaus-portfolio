"""Educational synthetic natural gas (SNG) plant model.

Pure calculation functions for a simplified flowsheet that converts cleaned
biomass syngas into SNG. All numbers here are illustrative values chosen for
an educational case study. This is not a validated commercial design and it
does not reproduce any specific university or industrial project.

This module performs no file or network access. Molar flows are plain dicts
in kmol/h keyed by species name. Functions return new dicts and never modify
their inputs.

Reactions used (extent of reaction method):
    Water gas shift:     CO + H2O -> CO2 + H2
    CO methanation:      CO + 3 H2 -> CH4 + H2O
    CO2 methanation:     CO2 + 4 H2 -> CH4 + 2 H2O
"""

from __future__ import annotations

SPECIES = ("H2", "CO", "CO2", "CH4", "N2", "H2O")

# Molar masses, kg/kmol
MOLAR_MASS = {
    "H2": 2.016,
    "CO": 28.01,
    "CO2": 44.01,
    "CH4": 16.043,
    "N2": 28.014,
    "H2O": 18.015,
}

# Atom counts per molecule, used for element (C, H, O, N) balances
ATOMS = {
    "H2": {"H": 2},
    "CO": {"C": 1, "O": 1},
    "CO2": {"C": 1, "O": 2},
    "CH4": {"C": 1, "H": 4},
    "N2": {"N": 2},
    "H2O": {"H": 2, "O": 1},
}
ATOMIC_MASS = {"H": 1.008, "C": 12.011, "O": 15.999, "N": 14.007}
ELEMENTS = ("C", "H", "O", "N")

# Fixed average molar heat capacities, J/(mol K), treated as constant
# over the whole temperature range of this study (an illustrative
# simplification, stated in the documentation).
CP_J_MOL_K = {
    "H2": 28.8,
    "CO": 29.1,
    "CO2": 37.1,
    "CH4": 35.3,
    "N2": 29.1,
    "H2O": 33.6,  # water vapour
}

# Standard heats of reaction at 298 K, kJ/mol (negative = exothermic)
DH_WGS_KJ_MOL = -41.2
DH_CO_METHANATION_KJ_MOL = -206.2
DH_CO2_METHANATION_KJ_MOL = -165.0

# Lower heating values, kJ/mol (combustible species only)
LHV_KJ_MOL = {"H2": 241.8, "CO": 283.0, "CO2": 0.0, "CH4": 802.3, "N2": 0.0, "H2O": 0.0}

# Steam for the shift reactor: reaction requirement plus 5 percent excess.
STEAM_EXCESS_FRACTION = 0.05

# Illustrative compressor estimate: 0.03 kWh of electricity per kg of feed gas.
COMPRESSOR_KWH_PER_KG_FEED = 0.03


# ---------------------------------------------------------------------------
# Stream helpers
# ---------------------------------------------------------------------------

def _get(flows, species):
    """Molar flow of one species in kmol/h, zero if absent."""
    return float(flows.get(species, 0.0))


def clean_flows(flows):
    """Return a new dict with every species present and no negative flows.

    Tiny negative values from floating point arithmetic are set to zero.
    """
    out = {}
    for sp in SPECIES:
        n = _get(flows, sp)
        out[sp] = 0.0 if n < 0.0 else n
    return out


def total_flow_kmol_h(flows):
    """Total molar flow in kmol/h."""
    return sum(_get(flows, sp) for sp in SPECIES)


def stream_mass_kg_h(flows):
    """Total mass flow in kg/h from molar flows and molar masses."""
    return sum(_get(flows, sp) * MOLAR_MASS[sp] for sp in SPECIES)


def composition_molpct(flows):
    """Composition in mol percent for all species. Zeros if the stream is empty."""
    total = total_flow_kmol_h(flows)
    if total <= 0.0:
        return {sp: 0.0 for sp in SPECIES}
    return {sp: 100.0 * _get(flows, sp) / total for sp in SPECIES}


def element_mass_kg_h(flows):
    """Mass flow of each element (C, H, O, N) in kg/h carried by the stream."""
    out = {el: 0.0 for el in ELEMENTS}
    for sp in SPECIES:
        n = _get(flows, sp)
        for el, count in ATOMS[sp].items():
            out[el] += n * count * ATOMIC_MASS[el]
    return out


def add_flows(a, b):
    """Sum of two molar flow dicts."""
    return {sp: _get(a, sp) + _get(b, sp) for sp in SPECIES}


# ---------------------------------------------------------------------------
# Unit operations
# ---------------------------------------------------------------------------

def wgs_extent(feed_flows, target_h2_co_ratio=3.0):
    """Shift extent and steam make-up to reach a target H2/CO molar ratio.

    For CO + H2O -> CO2 + H2 with extent e:
        (H2 + e) / (CO - e) = target  =>  e = (target * CO - H2) / (1 + target)

    The extent is kept between zero and the CO flow. Steam added equals the
    steam consumed by the reaction plus 5 percent excess; the excess leaves
    in the shifted gas.

    Returns a dict with extent_kmol_h and steam_kmol_h.
    """
    h2 = _get(feed_flows, "H2")
    co = _get(feed_flows, "CO")
    if co <= 0.0:
        return {"extent_kmol_h": 0.0, "steam_kmol_h": 0.0}
    extent = (target_h2_co_ratio * co - h2) / (1.0 + target_h2_co_ratio)
    extent = min(max(extent, 0.0), co)
    steam = extent * (1.0 + STEAM_EXCESS_FRACTION)
    return {"extent_kmol_h": extent, "steam_kmol_h": steam}


def wgs_extent_for_methanation(feed_flows, co2_removal_fraction):
    """Shift extent and steam make-up for full methanation stoichiometry.

    Instead of a fixed H2/CO ratio, the extent e is chosen so the gas after
    the shift and the downstream CO2 removal (removal fraction f) carries
    exactly enough hydrogen for both methanation reactions at full
    conversion:

        H2 + e = 3 (CO - e) + 4 (1 - f) (CO2 + e)

    Solving for e:

        e = (3 CO + 4 (1 - f) CO2 - H2) / (4 f)

    The extent is kept between zero and the CO flow. Steam added equals the
    steam consumed by the reaction plus 5 percent excess, exactly as in
    wgs_extent.

    Returns a dict with extent_kmol_h and steam_kmol_h.
    """
    h2 = _get(feed_flows, "H2")
    co = _get(feed_flows, "CO")
    co2 = _get(feed_flows, "CO2")
    if co <= 0.0 or co2_removal_fraction <= 0.0:
        return {"extent_kmol_h": 0.0, "steam_kmol_h": 0.0}
    extent = (3.0 * co + 4.0 * (1.0 - co2_removal_fraction) * co2 - h2) / (
        4.0 * co2_removal_fraction
    )
    extent = min(max(extent, 0.0), co)
    steam = extent * (1.0 + STEAM_EXCESS_FRACTION)
    return {"extent_kmol_h": extent, "steam_kmol_h": steam}


def apply_wgs(feed_flows, extent_kmol_h, steam_kmol_h):
    """Shifted gas after adding steam and reacting CO + H2O -> CO2 + H2."""
    e = extent_kmol_h
    out = clean_flows(feed_flows)
    out["H2O"] += steam_kmol_h
    out["CO"] -= e
    out["H2O"] -= e
    out["CO2"] += e
    out["H2"] += e
    return clean_flows(out)


def remove_co2(flows, removal_fraction):
    """Split the stream at the amine unit.

    Returns (gas_out, co2_removed). Only CO2 is removed in this model.
    """
    gas = clean_flows(flows)
    removed = {sp: 0.0 for sp in SPECIES}
    removed["CO2"] = gas["CO2"] * removal_fraction
    gas["CO2"] -= removed["CO2"]
    return clean_flows(gas), clean_flows(removed)


def methanation(flows, co_conversion, co2_conversion):
    """Methanation with a hydrogen availability guard.

    CO + 3 H2 -> CH4 + H2O at the requested CO conversion.
    CO2 + 4 H2 -> CH4 + 2 H2O at the requested CO2 conversion.

    CO reacts first because it adsorbs preferentially on the catalyst. If the
    hydrogen in the feed cannot support the requested conversions, the extents
    are limited by the hydrogen available (CO step first, then the CO2 step
    with whatever hydrogen remains) and the result is flagged h2_limited.
    No exception is raised and no flow goes negative.

    Returns a dict with:
        flows, extent_co_kmol_h, extent_co2_kmol_h,
        co_conversion_achieved, co2_conversion_achieved, h2_limited
    """
    gas = clean_flows(flows)
    co = gas["CO"]
    co2 = gas["CO2"]
    h2 = gas["H2"]

    e1_target = co_conversion * co
    e1 = min(e1_target, h2 / 3.0)
    h2_left = max(h2 - 3.0 * e1, 0.0)

    e2_target = co2_conversion * co2
    e2 = min(e2_target, h2_left / 4.0)

    tol = 1e-9
    h2_limited = (e1_target - e1 > tol * max(1.0, e1_target)) or (
        e2_target - e2 > tol * max(1.0, e2_target)
    )

    out = dict(gas)
    out["CO"] = co - e1
    out["CO2"] = co2 - e2
    out["H2"] = h2 - 3.0 * e1 - 4.0 * e2
    out["CH4"] = gas["CH4"] + e1 + e2
    out["H2O"] = gas["H2O"] + e1 + 2.0 * e2

    return {
        "flows": clean_flows(out),
        "extent_co_kmol_h": e1,
        "extent_co2_kmol_h": e2,
        "co_conversion_achieved": (e1 / co) if co > 0.0 else 0.0,
        "co2_conversion_achieved": (e2 / co2) if co2 > 0.0 else 0.0,
        "h2_limited": h2_limited,
    }


def condense_water(flows, knockout_fraction=0.99):
    """Knock out a fraction of the water as liquid condensate.

    Returns (gas_out, condensate). The condensate is pure water.
    """
    gas = clean_flows(flows)
    condensate = {sp: 0.0 for sp in SPECIES}
    condensate["H2O"] = gas["H2O"] * knockout_fraction
    gas["H2O"] -= condensate["H2O"]
    return clean_flows(gas), clean_flows(condensate)


# ---------------------------------------------------------------------------
# Energy functions (duties reported as positive magnitudes in kW)
# ---------------------------------------------------------------------------

def sensible_duty_kw(flows, t_in_c, t_out_c):
    """Sensible heat duty in kW to take the stream from t_in_c to t_out_c.

    Positive means heat added (heating), negative means heat removed
    (cooling). Uses the fixed average molar heat capacities.
    kmol/h * J/(mol K) * K = kJ/h, and kJ/h / 3600 = kW.
    """
    ncp = sum(_get(flows, sp) * CP_J_MOL_K[sp] for sp in SPECIES)  # kJ/(h K)
    return ncp * (t_out_c - t_in_c) / 3600.0


def reaction_heat_release_kw(extent_kmol_h, dh_kj_mol):
    """Heat released by a reaction extent, in kW (positive for exothermic).

    kmol/h * kJ/mol * 1000 mol/kmol = kJ/h, and kJ/h / 3600 = kW.
    """
    return -dh_kj_mol * extent_kmol_h * 1000.0 / 3600.0


def compressor_power_kw(feed_mass_kg_h):
    """Illustrative compressor electrical load: 0.03 kWh per kg of feed gas."""
    return COMPRESSOR_KWH_PER_KG_FEED * feed_mass_kg_h


def lhv_mj_h(flows):
    """Lower heating value carried by the stream, MJ/h (kmol/h * kJ/mol)."""
    return sum(_get(flows, sp) * LHV_KJ_MOL[sp] for sp in SPECIES)


# ---------------------------------------------------------------------------
# KPI functions
# ---------------------------------------------------------------------------

def co_conversion_pct(methanation_result):
    """CO conversion achieved in the methanation step, percent."""
    return 100.0 * methanation_result["co_conversion_achieved"]


def ch4_yield_pct(feed_flows, product_flows):
    """CH4 made across the plant per mol of (CO + CO2) in the feed, percent.

    CH4 already present in the feed is not counted as yield. CO2 removed in
    the amine unit counts in the denominator, so this is a whole plant yield.
    """
    carbon_in = _get(feed_flows, "CO") + _get(feed_flows, "CO2")
    if carbon_in <= 0.0:
        return 0.0
    ch4_made = _get(product_flows, "CH4") - _get(feed_flows, "CH4")
    return 100.0 * ch4_made / carbon_in


def ch4_purity_molpct(flows, dry=False):
    """CH4 purity of the stream in mol percent, wet or on a dry basis."""
    total = total_flow_kmol_h(flows)
    if dry:
        total -= _get(flows, "H2O")
    if total <= 0.0:
        return 0.0
    return 100.0 * _get(flows, "CH4") / total


def annual_production_mt(sng_kg_h, operating_hours=8000.0):
    """Annual production in metric tonnes."""
    return sng_kg_h * operating_hours / 1000.0


def cold_gas_efficiency_pct(feed_flows, product_flows):
    """LHV in the product gas as a percentage of LHV in the feed gas."""
    feed_lhv = lhv_mj_h(feed_flows)
    if feed_lhv <= 0.0:
        return 0.0
    return 100.0 * lhv_mj_h(product_flows) / feed_lhv


def specific_cooling_kwh_per_kg(total_cooling_kw, sng_kg_h):
    """Cooling duty per kg of SNG product. kW / (kg/h) = kWh/kg."""
    if sng_kg_h <= 0.0:
        return 0.0
    return total_cooling_kw / sng_kg_h


# ---------------------------------------------------------------------------
# Mass and element balance check
# ---------------------------------------------------------------------------

def mass_balance(feed_flows, steam_kmol_h, outlet_streams):
    """Overall mass and element balance for the plant.

    In: feed gas plus shift steam. Out: the listed outlet streams (SNG
    product, CO2 by-product, condensate). Returns totals in kg/h, the
    closure in percent (out / in * 100) and element balances for C, H,
    O and N.
    """
    steam = {sp: 0.0 for sp in SPECIES}
    steam["H2O"] = steam_kmol_h
    mass_in = stream_mass_kg_h(feed_flows) + stream_mass_kg_h(steam)
    mass_out = sum(stream_mass_kg_h(s) for s in outlet_streams)

    el_in = element_mass_kg_h(add_flows(feed_flows, steam))
    el_out = {el: 0.0 for el in ELEMENTS}
    for s in outlet_streams:
        for el, kg in element_mass_kg_h(s).items():
            el_out[el] += kg

    closure_pct = 100.0 * mass_out / mass_in if mass_in > 0.0 else 0.0
    return {
        "in_kg_h": mass_in,
        "out_kg_h": mass_out,
        "closure_pct": closure_pct,
        "elements_in_kg_h": el_in,
        "elements_out_kg_h": el_out,
    }


# ---------------------------------------------------------------------------
# Flowsheet
# ---------------------------------------------------------------------------

def run_flowsheet(
    feed_flows,
    co_conversion=0.98,
    co2_conversion=0.90,
    co2_removal_fraction=0.90,
    target_h2_co_ratio=3.0,
    water_knockout_fraction=0.99,
    wgs_target="ratio",
):
    """Run the whole flowsheet from syngas feed to SNG product.

    Unit order: feed compressor (U1), gas cleaning (U2), water gas shift
    (U3), CO2 removal (U4), methanation (U5), condenser and dryer (U6).
    Compression and cleaning pass the composition through unchanged.

    wgs_target selects how the shift extent is set: "ratio" targets the
    fixed H2/CO ratio (the design case), "stoichiometric" targets full
    methanation stoichiometry after CO2 removal (see
    wgs_extent_for_methanation).

    Returns a dict with every stream, the steam make-up, the reaction
    extents and the overall mass balance.
    """
    feed = clean_flows(feed_flows)

    after_compressor = dict(feed)   # U1: composition unchanged
    after_cleaning = dict(feed)     # U2: trace removal only, pass-through

    if wgs_target == "stoichiometric":
        wgs = wgs_extent_for_methanation(after_cleaning, co2_removal_fraction)
    else:
        wgs = wgs_extent(after_cleaning, target_h2_co_ratio)
    after_wgs = apply_wgs(after_cleaning, wgs["extent_kmol_h"], wgs["steam_kmol_h"])

    after_co2_removal, co2_removed = remove_co2(after_wgs, co2_removal_fraction)

    meth = methanation(after_co2_removal, co_conversion, co2_conversion)
    after_methanation = meth["flows"]

    sng, condensate = condense_water(after_methanation, water_knockout_fraction)

    balance = mass_balance(
        feed, wgs["steam_kmol_h"], [sng, co2_removed, condensate]
    )

    return {
        "feed": feed,
        "steam_kmol_h": wgs["steam_kmol_h"],
        "after_compressor": after_compressor,
        "after_cleaning": after_cleaning,
        "after_wgs": after_wgs,
        "after_co2_removal": after_co2_removal,
        "after_methanation": after_methanation,
        "sng": sng,
        "co2_removed": co2_removed,
        "condensate": condensate,
        "wgs": wgs,
        "methanation": meth,
        "mass_balance": balance,
    }
