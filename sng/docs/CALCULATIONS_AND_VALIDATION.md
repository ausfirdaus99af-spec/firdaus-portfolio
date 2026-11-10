# Calculations and Validation - SNG Plant (Educational Case Study)

This document records every calculation method used in `scripts/sng_model.py`,
the data behind it, and the checks run to confirm the model behaves as
intended. All values are illustrative and chosen for an educational case
study; this is not a validated commercial design.

## 1. Conventions and data

- Molar flows n are in kmol/h. Mass flows are in kg/h. Duties are in kW.
- Mass flow of a stream: m = sum over species of (n_i x M_i), with molar
  masses M in kg/kmol: H2 2.016, CO 28.01, CO2 44.01, CH4 16.043, N2 28.014,
  H2O 18.015.
- Composition in mol percent: y_i = 100 x n_i / n_total.
- Element balances use atom counts per molecule and atomic masses
  H 1.008, C 12.011, O 15.999, N 14.007 kg/kmol.

## 2. Extent of reaction method

Each reactor is modelled with molar extents. For a reaction with extent e
(kmol/h), each species flow changes by its stoichiometric coefficient times e.
No kinetics or equilibrium are solved; conversions are inputs.

### 2.1 Water gas shift (U3)

Reaction: CO + H2O -> CO2 + H2, extent e.

The extent is chosen so the shifted gas hits a target H2 to CO molar ratio r:

    (H2 + e) / (CO - e) = r   =>   e = (r x CO - H2) / (1 + r)

with e held between 0 and the CO flow. For the base feed (H2 40, CO 25 per
100 kmol/h) and r = 3.0 this gives e = (75 - 40) / 4 = 8.75 kmol per 100 kmol
of feed.

Steam make-up: steam added = e x 1.05, that is the steam consumed by the
reaction plus 5 percent excess. The excess steam leaves in the shifted gas
and the steam mass appears on the inlet side of the overall mass balance.

**Balanced H2 ratio target (the fix scenario).** The fixed ratio r = 3.0
covers the CO reaction only, so the design case runs short of hydrogen for
the CO2 reaction (see 2.2). In the balanced_ratio scenario the extent is
instead chosen so the gas after the shift and the downstream CO2 removal
(removal fraction f) carries exactly enough hydrogen for both methanation
reactions at full conversion:

    H2 + e = 3 x (CO - e) + 4 x (1 - f) x (CO2 + e)

which solves to

    e = (3 x CO + 4 x (1 - f) x CO2 - H2) / (4 x f)

again held between 0 and the CO flow, with the same steam rule. For the base
feed and f = 0.9 this gives e = (75 + 8 - 40) / 3.6 = 11.944 kmol per 100
kmol of feed, against 8.75 in the design case.

### 2.2 Methanation (U5)

Reactions: CO + 3 H2 -> CH4 + H2O (extent e1) and CO2 + 4 H2 -> CH4 + 2 H2O
(extent e2). Requested conversions X_CO and X_CO2 give target extents
e1 = X_CO x CO and e2 = X_CO2 x CO2.

Hydrogen guard: CO reacts first (it adsorbs preferentially on the catalyst).
If hydrogen cannot support the targets, the extents are limited:

    e1 = min(X_CO x CO, H2 / 3)
    e2 = min(X_CO2 x CO2, (H2 - 3 x e1) / 4)

and the result is flagged hydrogen limited. No flow is ever negative and no
error is raised.

**Problem and fix.** Because the design shift target H2/CO = 3.0 is the
stoichiometric ratio for the CO reaction alone, the three design-ratio
scenarios are all hydrogen limited on the CO2 step: the achieved CO2
conversion is about 8.5 percent in the base case, 11.6 percent in the
hydrogen-rich case and 42.4 percent in the aged-catalyst case (where the
lower CO conversion frees hydrogen for CO2). The balanced_ratio scenario
applies the fix from section 2.1: with the retargeted shift extent the guard
does not trigger and the full 98 percent CO and 90 percent CO2 conversions
are achieved. The costs of the fix are a larger shift extent (more steam,
more CO turned into CO2 and removed) and unreacted hydrogen in the product,
so the SNG mass rate drops from 2,750 to 2,304 kg/h at the same feed.

### 2.3 CO2 removal (U4) and condenser (U6)

Simple splits: U4 removes a fixed fraction of the CO2 (90 percent in the base
case) as a pure CO2 by-product. U6 removes 99 percent of the water as a pure
water condensate. No other species leave in either by-product.

## 3. Energy method

Duties are reported as positive magnitudes in kW, tagged as electrical,
heating or cooling.

### 3.1 Sensible heat

    Q = sum(n_i x Cp_i) x (T_out - T_in) / 3600      [kW]

with n in kmol/h, Cp in J/(mol K) and T in C (only differences are used).
Fixed average molar heat capacities, treated as constant over the whole
range: H2 28.8, CO 29.1, CO2 37.1, CH4 35.3, N2 29.1, H2O (vapour) 33.6
J/(mol K).

### 3.2 Reaction heat

Standard heats of reaction at 298 K, treated as constant: WGS -41.2 kJ/mol,
CO methanation -206.2 kJ/mol, CO2 methanation -165.0 kJ/mol. Heat released:

    Q = |dH| x e x 1000 / 3600      [kW], e in kmol/h

### 3.3 Duties reported

| Duty | Method | Base case |
| --- | --- | --- |
| U1 feed compression (electrical) | 0.03 kWh per kg of feed gas, illustrative | 243.9 kW |
| U3 feed preheat 40 to 300 C (heating) | sensible heat on the clean syngas | 940.2 kW |
| U3 shift reactor heat removal (cooling) | reaction heat of the shift extent | 417.2 kW |
| U5 methanation cooling (cooling) | reaction heat of both extents, removed to hold the 350 C outlet | 3,847.2 kW |
| U6 product cooling 350 to 40 C (cooling) | sensible heat on the methanation outlet | 626.8 kW |

The latent heat of the condensing water is not included in the U6 duty, and
the amine reboiler duty is not modelled. Both are listed as limitations.

## 4. KPI definitions

- **co_conversion_pct**: CO conversion achieved in the methanation step,
  100 x e1 / CO entering the methanator.
- **ch4_yield_pct**: 100 x (CH4 in product - CH4 in feed) / (CO + CO2 in
  feed). CO2 removed in the amine unit stays in the denominator, so this is a
  whole-plant yield and is deliberately conservative.
- **ch4_purity_dry_molpct**: 100 x CH4 / (total - H2O) in the product. The
  wet purity uses the total including water.
- **annual_mt**: SNG kg/h x 8,000 h / 1,000.
- **cold_gas_efficiency_pct**: 100 x LHV of product gas / LHV of feed gas,
  with lower heating values in kJ/mol: H2 241.8, CO 283.0, CH4 802.3, all
  other species zero. Stream LHV = sum(n_i x LHV_i), the units cancel in the
  ratio.
- **specific_cooling_kwh_kg**: total cooling duty in kW divided by SNG kg/h,
  which is numerically kWh per kg of SNG.

## 5. Mass balance check

Overall balance: in = feed gas + shift steam; out = SNG product + CO2
by-product + condensate. Closure is reported as 100 x out / in. Element
balances for C, H, O and N are built from atom counts and atomic masses and
reported per scenario in the JSON.

Base case result: in 8,821.25 kg/h, out 8,821.28 kg/h, closure 100.00
percent. The 0.03 kg/h residual exists because the stated two-decimal molar
masses are not perfectly consistent across the shift reaction (CO + H2O gives
46.025 kg/kmol against CO2 + H2 at 46.026 kg/kmol). The element balances,
built from atomic masses, close exactly. Both are far inside the 0.1 percent
acceptance limit.

## 6. Validation checks performed

All checks live in `tests/test_sng_model.py` and run with pytest. Result:
35 passed, 0 failed.

1. **Hand example.** 100 kmol/h CO + 300 kmol/h H2 at full CO conversion
   gives exactly 100 kmol/h CH4 and 100 kmol/h H2O; mass in equals mass out
   at exactly 3,405.8 kg/h; feed LHV 100,840 MJ/h, product LHV 80,230 MJ/h,
   cold gas efficiency 79.56 percent, all matching paper calculations.
2. **Shift targets.** On the base feed the ratio formula returns exactly
   8.75 kmol per 100 kmol feed and the shifted gas has H2/CO = 3.0 to
   machine precision; the balanced target formula returns exactly 43 / 3.6 =
   11.944 kmol per 100 kmol feed and the gas after CO2 removal satisfies
   H2 = 3 x CO + 4 x CO2 to machine precision; steam equals 1.05 x extent in
   both modes; a feed already above the ratio target gives zero extent and
   zero steam.
3. **Element balances.** C, H, O and N close within 0.1 percent for all
   four scenarios (they close to machine precision in practice).
4. **Hydrogen guard, both ways.** A hydrogen-starved feed produces no
   negative flows anywhere in the flowsheet, is flagged as hydrogen limited,
   and a feed with no hydrogen converts nothing. In the balanced_ratio
   scenario the guard does not trigger and the achieved conversions equal
   the requested 98 and 90 percent.
5. **Bounds and signs.** Purities, conversions, yields and efficiencies sit
   between 0 and 100 for every scenario; every methanation duty is tagged as
   cooling with a positive magnitude; heating, cooling and electrical totals
   are all positive.
6. **Production target.** The base case makes 2,750.0 kg/h and 22,000 MT per
   year, inside the 2 percent band.
7. **JSON contract.** The dataset round-trips through strict JSON, has
   exactly the four top-level keys, four scenarios, units U1 to U6, streams
   S1 to S7 plus BP1 and BP2 in order, 30 CO-conversion sweep points from
   85.0 to 99.5 and 10 CO2-removal sweep points from 50 to 95.

## 7. Limitations

- Conversions and the shift extent are fixed inputs; no kinetics, catalyst
  models or chemical equilibrium are solved.
- Heat capacities and reaction heats are constants; real values change with
  temperature.
- The latent heat of condensing water is not included in the condenser duty,
  so the true cooling load at U6 is higher than reported.
- The amine unit is a simple split; its reboiler steam, solvent circulation
  and CO2 purity are not modelled.
- The compressor figure of 0.03 kWh per kg is a stated illustrative estimate,
  not a thermodynamic calculation.
- Pressure drops, heat losses, trace components and recycle streams are
  ignored.
- The product gas is not checked against any pipeline specification; with 4
  mol percent nitrogen in the feed the dry methane purity stays near 79
  percent, which a real project would address in the feed or with upgrading.
