# Design Basis - Synthetic Natural Gas Plant (Educational Case Study)

This document sets out the basis for a simplified process design study of a
synthetic natural gas (SNG) plant. Every number in this study is an assumed,
illustrative value chosen for learning and demonstration. This is an
educational case study, not a validated commercial design.

## What SNG is

Synthetic natural gas, also called substitute natural gas, is a methane-rich
gas made from another feedstock such as coal, biomass or surplus electricity.
Once cleaned and dried it can be used in the same way as pipeline natural gas:
for heating, power generation or as a vehicle fuel. The core chemistry is
methanation, where carbon monoxide and carbon dioxide react with hydrogen over
a nickel catalyst to form methane and water.

## Why this feedstock and route

The study uses cleaned syngas from biomass gasification as the feed. Biomass
syngas is a common teaching example because it brings together several classic
process steps in one flowsheet: compression, gas cleaning, water gas shift,
acid gas removal, methanation and drying. It is also a route with practical
interest, since turning biomass into a pipeline-quality gas is one way to
store renewable carbon in an existing gas network.

## Basis

| Item | Value |
| --- | --- |
| Product | SNG, 22,000 metric tonnes per year |
| Operating hours | 8,000 h per year |
| Product rate | 2,750 kg/h of SNG |
| Feed pressure after compression | 15 bar |
| Methanation outlet temperature | 350 C |
| Product delivery temperature | 40 C |

The feed flow is scaled so that the base case makes exactly 2,750 kg/h of
SNG. The flowsheet is linear in the feed flow, so the model is run once at
100 kmol/h of feed, the SNG made per 100 kmol/h is read off, and the feed is
scaled by simple ratio. The resulting base feed is 416.67 kmol/h, which is
8,131.6 kg/h of syngas. At 8,000 hours this gives 22,000 MT per year of SNG
in the base case.

## Feed

Cleaned syngas from biomass gasification with this assumed base composition:

| Species | mol % |
| --- | --- |
| H2 | 40 |
| CO | 25 |
| CO2 | 20 |
| CH4 | 10 |
| N2 | 4 |
| H2O | 1 |

Three variations are studied alongside the base case: a hydrogen-rich feed
(H2 46, CO 22, CO2 17, CH4 10, N2 4, H2O 1 mol %), an aged-catalyst case
where the methanation conversions are lower, and a balanced H2 ratio case
that retargets the shift step to fix the hydrogen shortfall described under
U5 below. All variations keep the same feed molar flow as the base case, so
the production rate changes, which is the point of comparing them.

## Process units, in order

1. **U1 Feed compressor.** Raises the syngas to 15 bar for the downstream
   reactors. The composition does not change. The electrical load is
   estimated at 0.03 kWh per kg of feed gas, an illustrative figure.
2. **U2 Gas cleaning.** Removes trace contaminants, mainly sulphur
   compounds, that would poison the shift and methanation catalysts. In this
   simplified model the bulk composition passes through unchanged.
3. **U3 Water gas shift reactor.** Reacts CO with steam (CO + H2O -> CO2 +
   H2) to raise the hydrogen content. The extent of reaction is set so the
   shifted gas has a H2 to CO molar ratio of exactly 3.0, the stoichiometric
   ratio for CO methanation. Steam is added at the reaction requirement plus
   5 percent excess, and the excess leaves with the gas. The feed is
   preheated from 40 C to 300 C before this step.
4. **U4 CO2 removal.** An amine absorption unit removes 90 percent of the
   CO2 in the base case. The removed CO2 leaves as a by-product stream for
   vent or use. Removing CO2 here reduces the hydrogen demand in the
   methanation step and lifts the methane purity of the product.
5. **U5 Methanation reactor.** Converts CO (CO + 3 H2 -> CH4 + H2O, 98
   percent conversion in the base case) and CO2 (CO2 + 4 H2 -> CH4 + 2 H2O,
   90 percent conversion requested) into methane. Both reactions are strongly
   exothermic, so the reactor is cooled to hold a 350 C outlet. CO reacts
   first because it adsorbs preferentially on the catalyst. Because the shift
   step targets H2/CO = 3.0, which is the stoichiometric ratio for the CO
   reaction alone, there is little hydrogen left for the CO2 reaction. The
   model limits the CO2 conversion to the hydrogen actually available and
   flags the case as hydrogen limited. In the base case the achieved CO2
   conversion is about 8.5 percent, not the 90 percent requested. This is a
   deliberate teaching point: the shift ratio target and the CO2 slip
   together decide how much CO2 can be methanated. The balanced H2 ratio
   scenario is the matching fix: the shift extent is retargeted so the gas
   after CO2 removal carries enough hydrogen for both reactions, and the
   requested 98 and 90 percent conversions are then achieved in full.
6. **U6 Condenser and dryer.** Cools the gas from 350 C to 40 C and knocks
   out 99 percent of the water as condensate. The remaining gas is the SNG
   product.

In the base case the SNG product is 138.8 kmol/h at 2,750 kg/h, with a dry
methane purity of 79.0 mol percent and a cold gas efficiency of 85.1 percent.
The nitrogen in the feed is inert and ends up concentrated in the product,
which is one reason the purity is modest; a commercial design would use a
feed with less nitrogen or add an upgrading step.

## Problem and fix: the hydrogen shortfall

The base design shifts the gas to H2/CO = 3.0, the textbook ratio for CO
methanation. The mass balance then shows the flaw: after 98 percent of the
CO has reacted there is almost no hydrogen left, so the CO2 that slipped
through the amine unit cannot be methanated (about 8.5 percent conversion
instead of the 90 percent requested) and it stays in the product as inert
ballast. The balanced H2 ratio scenario repairs this by shifting further, so
that after CO2 removal the hydrogen covers the full stoichiometric demand of
both reactions, 3 mol per mol of CO plus 4 mol per mol of remaining CO2.
The CO2 in the dry product falls from about 7.9 to 1.0 mol percent and both
conversions are met. The trade-offs are also visible: more CO is shifted
away, so less SNG mass is made (2,304 kg/h against 2,750 kg/h at the same
feed), more steam is needed, and unreacted hydrogen now appears in the
product. Seeing both sides of that trade is the purpose of the pair.

## What this study is NOT

- It is **not** the original university design project. That project is
  described separately on the portfolio site; this study is a fresh,
  simplified model built only to demonstrate process calculation skills.
- It is **not** a validated commercial design. No vendor data, pilot data or
  plant data stand behind these numbers.
- It contains **no equipment sizing**: no reactor volumes, column heights,
  heat exchanger areas or compressor selections.
- It contains **no reaction kinetics**. Conversions and the shift extent are
  fixed inputs, not predictions from rate equations or equilibrium.
- It contains **no costs**, no economics and no safety or environmental
  assessment.

All data and assumptions are illustrative and chosen for teaching value. The
full list of assumptions is embedded in `data/sng_data.json` and the
calculation methods are set out in `CALCULATIONS_AND_VALIDATION.md`.
