"""Build data/sng_data.json for the educational SNG plant case study.

Runs the pure model in sng_model.py for the three scenarios and the two
sensitivity sweeps, then writes a single JSON file for the dashboard.
All numbers are illustrative values for an educational case study.
"""

from __future__ import annotations

import datetime
import json
import os

import sng_model as m

TARGET_SNG_KG_H = 2750.0        # 22,000 MT per year at 8,000 operating hours
OPERATING_HOURS = 8000.0

BASE_COMPOSITION_MOLPCT = {
    "H2": 40.0, "CO": 25.0, "CO2": 20.0, "CH4": 10.0, "N2": 4.0, "H2O": 1.0,
}
H2_RICH_COMPOSITION_MOLPCT = {
    "H2": 46.0, "CO": 22.0, "CO2": 17.0, "CH4": 10.0, "N2": 4.0, "H2O": 1.0,
}

SCENARIO_SETTINGS = {
    "base": {
        "label": "Base case",
        "description": "Design feed and design conversions for the 22,000 MT per year educational basis.",
        "composition": BASE_COMPOSITION_MOLPCT,
        "co_conversion": 0.98,
        "co2_conversion": 0.90,
        "wgs_target": "ratio",
    },
    "h2_rich": {
        "label": "Hydrogen rich feed",
        "description": "Hydrogen rich syngas with the same conversions, showing how feed quality changes the product.",
        "composition": H2_RICH_COMPOSITION_MOLPCT,
        "co_conversion": 0.98,
        "co2_conversion": 0.90,
        "wgs_target": "ratio",
    },
    "aged_catalyst": {
        "label": "Aged catalyst",
        "description": "Base feed with lower methanation conversions to mimic an aged catalyst bed.",
        "composition": BASE_COMPOSITION_MOLPCT,
        "co_conversion": 0.90,
        "co2_conversion": 0.70,
        "wgs_target": "ratio",
    },
    "balanced_ratio": {
        "label": "Balanced H2 ratio (improved design)",
        "description": "The shift step is retargeted so there is enough hydrogen for the carbon dioxide as well, the fix for the hydrogen shortfall seen in the design case.",
        "composition": BASE_COMPOSITION_MOLPCT,
        "co_conversion": 0.98,
        "co2_conversion": 0.90,
        "wgs_target": "stoichiometric",
    },
}

CO2_REMOVAL_FRACTION = 0.90
WATER_KNOCKOUT_FRACTION = 0.99

PROCESS_UNITS = [
    {
        "id": "U1",
        "name": "Feed compressor",
        "description": "Raises the cleaned syngas from near atmospheric pressure to 15 bar for the downstream reactors. The gas composition does not change here.",
    },
    {
        "id": "U2",
        "name": "Gas cleaning",
        "description": "Removes trace contaminants such as sulphur compounds that would poison the catalysts. The bulk composition passes through unchanged in this simplified model.",
    },
    {
        "id": "U3",
        "name": "Water gas shift reactor",
        "description": "Reacts CO with steam to make more hydrogen until the gas reaches a H2 to CO molar ratio of 3. Steam is added at the reaction requirement plus 5 percent excess.",
    },
    {
        "id": "U4",
        "name": "CO2 removal",
        "description": "An amine absorption unit that removes 90 percent of the CO2 in the base case. The removed CO2 leaves as a by-product stream for vent or use.",
    },
    {
        "id": "U5",
        "name": "Methanation reactor",
        "description": "Converts CO and CO2 with hydrogen into methane and water over a nickel catalyst. The reactions are strongly exothermic, so the reactor is cooled to hold a 350 C outlet.",
    },
    {
        "id": "U6",
        "name": "Condenser and dryer",
        "description": "Cools the product gas to 40 C and knocks out 99 percent of the water as condensate. The remaining gas is the SNG product.",
    },
]

ASSUMPTIONS = [
    "All numbers are illustrative values chosen for an educational case study, not measured plant data.",
    "Steady state operation for 8,000 hours per year with no start-up or shutdown effects.",
    "Ideal gas behaviour and perfect mixing are assumed in every unit.",
    "Gas cleaning removes trace contaminants only and does not change the bulk composition.",
    "Shift steam is dosed at the reaction requirement plus 5 percent excess, and the excess leaves with the shifted gas.",
    "The amine unit removes carbon dioxide only; solvent losses and reboiler duty are not modelled.",
    "Standard heats of reaction at 298 K are treated as constant over the operating range.",
    "Sensible heat uses a fixed average molar heat capacity per species over the whole temperature range.",
    "The latent heat of the condensed water is not included in the condenser cooling duty.",
    "Compressor power is estimated at 0.03 kWh per kg of feed gas, an illustrative figure for a rough electrical load.",
    "Pressure drops across units are ignored.",
    "When hydrogen runs short in the methanation step, CO reacts first and CO2 conversion is limited by the hydrogen that remains.",
]

REFERENCES = [
    "Perry's Chemical Engineers' Handbook, McGraw-Hill: standard heats of reaction and physical property data.",
    "Smith, Van Ness and Abbott, Introduction to Chemical Engineering Thermodynamics, McGraw-Hill: extent of reaction and energy balance methods.",
    "Kopyscinski, Schildhauer and Biollaz, Production of synthetic natural gas (SNG) from coal and dry biomass, Fuel (2010): general SNG process background.",
]


def r2(x):
    """Round to 2 decimal places, avoiding negative zero."""
    return round(float(x), 2) + 0.0


def r1(x):
    """Round to 1 decimal place, avoiding negative zero."""
    return round(float(x), 1) + 0.0


def feed_flows_from_composition(composition_molpct, total_kmol_h):
    """Molar flows in kmol/h from a mol percent composition and a total flow."""
    return {sp: composition_molpct.get(sp, 0.0) / 100.0 * total_kmol_h for sp in m.SPECIES}


def find_base_feed_kmol_h(target_sng_kg_h=TARGET_SNG_KG_H):
    """Scale the base feed so the base case makes the target SNG mass flow.

    The flowsheet is linear in the feed flow, so one run at 100 kmol/h gives
    the SNG made per 100 kmol/h of feed, and a simple ratio gives the feed
    needed for the 2,750 kg/h target.
    """
    probe = m.run_flowsheet(feed_flows_from_composition(BASE_COMPOSITION_MOLPCT, 100.0))
    sng_per_100 = m.stream_mass_kg_h(probe["sng"])
    return 100.0 * target_sng_kg_h / sng_per_100


def stream_entry(stream_id, name, after_unit, flows):
    comp = m.composition_molpct(flows)
    return {
        "id": stream_id,
        "name": name,
        "after_unit": after_unit,
        "flow_kmol_h": r2(m.total_flow_kmol_h(flows)),
        "flow_kg_h": r2(m.stream_mass_kg_h(flows)),
        "composition_molpct": {sp: r2(comp[sp]) for sp in m.SPECIES},
    }


def energy_summary(result):
    """Duty list and totals for one flowsheet result. Duties in kW, 1 dp."""
    feed_mass = m.stream_mass_kg_h(result["feed"])
    preheat = m.sensible_duty_kw(result["after_cleaning"], 40.0, 300.0)
    wgs_cooling = m.reaction_heat_release_kw(
        result["wgs"]["extent_kmol_h"], m.DH_WGS_KJ_MOL
    )
    meth_cooling = m.reaction_heat_release_kw(
        result["methanation"]["extent_co_kmol_h"], m.DH_CO_METHANATION_KJ_MOL
    ) + m.reaction_heat_release_kw(
        result["methanation"]["extent_co2_kmol_h"], m.DH_CO2_METHANATION_KJ_MOL
    )
    product_cooling = -m.sensible_duty_kw(result["after_methanation"], 350.0, 40.0)
    electrical = m.compressor_power_kw(feed_mass)

    duties = [
        {"unit": "U1", "label": "Feed compression", "duty_kw": r1(electrical), "kind": "electrical"},
        {"unit": "U3", "label": "Feed preheat 40 to 300 C", "duty_kw": r1(preheat), "kind": "heating"},
        {"unit": "U3", "label": "Shift reactor heat removal", "duty_kw": r1(wgs_cooling), "kind": "cooling"},
        {"unit": "U5", "label": "Methanation reactor cooling", "duty_kw": r1(meth_cooling), "kind": "cooling"},
        {"unit": "U6", "label": "Product cooling 350 to 40 C", "duty_kw": r1(product_cooling), "kind": "cooling"},
    ]
    total_cooling = wgs_cooling + meth_cooling + product_cooling
    return {
        "duties": duties,
        "total_heating_kw": r1(preheat),
        "total_cooling_kw": r1(total_cooling),
        "total_electrical_kw": r1(electrical),
    }, total_cooling


def kpi_summary(result, total_cooling_kw):
    sng = result["sng"]
    sng_kg_h = m.stream_mass_kg_h(sng)
    return {
        "co_conversion_pct": r2(m.co_conversion_pct(result["methanation"])),
        "ch4_yield_pct": r2(m.ch4_yield_pct(result["feed"], sng)),
        "ch4_purity_dry_molpct": r2(m.ch4_purity_molpct(sng, dry=True)),
        "sng_kg_h": r2(sng_kg_h),
        "annual_mt": r2(m.annual_production_mt(sng_kg_h, OPERATING_HOURS)),
        "cold_gas_efficiency_pct": r2(
            m.cold_gas_efficiency_pct(result["feed"], sng)
        ),
        "specific_cooling_kwh_kg": r2(
            m.specific_cooling_kwh_per_kg(total_cooling_kw, sng_kg_h)
        ),
    }


def build_scenario(settings, feed_kmol_h):
    feed = feed_flows_from_composition(settings["composition"], feed_kmol_h)
    result = m.run_flowsheet(
        feed,
        co_conversion=settings["co_conversion"],
        co2_conversion=settings["co2_conversion"],
        co2_removal_fraction=CO2_REMOVAL_FRACTION,
        water_knockout_fraction=WATER_KNOCKOUT_FRACTION,
        wgs_target=settings["wgs_target"],
    )

    streams = [
        stream_entry("S1", "Syngas feed", None, result["feed"]),
        stream_entry("S2", "Compressed syngas", "U1", result["after_compressor"]),
        stream_entry("S3", "Clean syngas", "U2", result["after_cleaning"]),
        stream_entry("S4", "Shifted gas", "U3", result["after_wgs"]),
        stream_entry("S5", "CO2 lean gas", "U4", result["after_co2_removal"]),
        stream_entry("S6", "Methanation outlet", "U5", result["after_methanation"]),
        stream_entry("S7", "SNG product", "U6", result["sng"]),
        stream_entry("BP1", "CO2 to vent/use", "U4", result["co2_removed"]),
        stream_entry("BP2", "Process condensate", "U6", result["condensate"]),
    ]

    balance = result["mass_balance"]
    by_species = [
        {
            "species": el,
            "in": r2(balance["elements_in_kg_h"][el]),
            "out": r2(balance["elements_out_kg_h"][el]),
        }
        for el in m.ELEMENTS
    ]

    energy, total_cooling_kw = energy_summary(result)
    feed_comp = m.composition_molpct(result["feed"])

    return {
        "label": settings["label"],
        "description": settings["description"],
        "feed": {
            "flow_kmol_h": r2(m.total_flow_kmol_h(result["feed"])),
            "flow_kg_h": r2(m.stream_mass_kg_h(result["feed"])),
            "composition_molpct": {sp: r2(feed_comp[sp]) for sp in m.SPECIES},
        },
        "steam_kg_h": r2(result["steam_kmol_h"] * m.MOLAR_MASS["H2O"]),
        "streams": streams,
        "mass_balance": {
            "in_kg_h": r2(balance["in_kg_h"]),
            "out_kg_h": r2(balance["out_kg_h"]),
            "closure_pct": r2(balance["closure_pct"]),
            "by_species_kg_h": by_species,
        },
        "energy": energy,
        "kpis": kpi_summary(result, total_cooling_kw),
    }


def build_sensitivity(feed_kmol_h):
    """Both sweeps on the base feed at the base feed scale."""
    feed = feed_flows_from_composition(BASE_COMPOSITION_MOLPCT, feed_kmol_h)

    co_points = []
    x = 85.0
    while x <= 99.5 + 1e-9:
        result = m.run_flowsheet(
            feed,
            co_conversion=x / 100.0,
            co2_conversion=0.90,
            co2_removal_fraction=CO2_REMOVAL_FRACTION,
        )
        sng = result["sng"]
        sng_comp = m.composition_molpct(sng)
        co_points.append({
            "x": r2(x),
            "ch4_purity_dry_pct": r2(m.ch4_purity_molpct(sng, dry=True)),
            "sng_kg_h": r2(m.stream_mass_kg_h(sng)),
            "co_in_product_molpct": r2(sng_comp["CO"]),
        })
        x += 0.5

    co2_points = []
    for removal in range(50, 100, 5):
        result = m.run_flowsheet(
            feed,
            co_conversion=0.98,
            co2_conversion=0.90,
            co2_removal_fraction=removal / 100.0,
        )
        sng = result["sng"]
        sng_kg_h = m.stream_mass_kg_h(sng)
        _, total_cooling_kw = energy_summary(result)
        co2_points.append({
            "x": r2(removal),
            "ch4_purity_dry_pct": r2(m.ch4_purity_molpct(sng, dry=True)),
            "sng_kg_h": r2(sng_kg_h),
            "specific_cooling_kwh_kg": r2(
                m.specific_cooling_kwh_per_kg(total_cooling_kw, sng_kg_h)
            ),
        })

    return {"co_conversion": co_points, "co2_removal": co2_points}


def build_dataset():
    feed_kmol_h = find_base_feed_kmol_h()
    scenarios = {
        key: build_scenario(settings, feed_kmol_h)
        for key, settings in SCENARIO_SETTINGS.items()
    }
    return {
        "meta": {
            "project": "SNG Plant Design",
            "synthetic": True,
            "basis": "22,000 MT per year educational case study",
            "generated_at": datetime.date.today().isoformat(),
            "units": {
                "flow": "kmol/h",
                "mass_flow": "kg/h",
                "duty": "kW",
                "temperature": "C",
                "pressure": "bar",
            },
            "assumptions": ASSUMPTIONS,
            "references": REFERENCES,
        },
        "process": {"units": PROCESS_UNITS},
        "scenarios": scenarios,
        "sensitivity": build_sensitivity(feed_kmol_h),
    }


def main():
    data = build_dataset()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.abspath(os.path.join(out_dir, "sng_data.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    base = data["scenarios"]["base"]["kpis"]
    print(f"Wrote {out_path}")
    print(f"Base feed: {data['scenarios']['base']['feed']['flow_kmol_h']} kmol/h, "
          f"{data['scenarios']['base']['feed']['flow_kg_h']} kg/h")
    print(f"Base SNG: {base['sng_kg_h']} kg/h, {base['annual_mt']} MT per year")
    print(f"Base CH4 purity (dry): {base['ch4_purity_dry_molpct']} mol pct, "
          f"cold gas efficiency: {base['cold_gas_efficiency_pct']} pct")
    print(f"Mass balance closure: {data['scenarios']['base']['mass_balance']['closure_pct']} pct")


if __name__ == "__main__":
    main()
