# Design Improvement Advisor - Methodology (SNG Plant)

This document explains `scripts/advisor.py`. The advisor reviews one model
scenario as the design under review. It writes `data/advisor_findings.json`.
All numbers are synthetic and educational. The pipeline specification used
here is illustrative, not a contract spec.

## 1. How it works

The advisor is deterministic. It runs the flowsheet model and applies five
fixed rules. Each rule has numeric thresholds. They live in one place
(`THRESHOLDS`) and are copied into the output JSON. The same inputs always
give the same findings. There is no randomness and no hidden tuning.

The build script `scripts/build_advisor.py` writes the JSON. It also runs
automatically at the end of `scripts/build_sng_data.py`, so one rebuild
refreshes both files.

Run it alone with:

    python scripts/build_advisor.py

Pick another scenario with `--scenario`, for example `balanced_ratio`.

## 2. Integrity rules

1. Nothing is hardcoded as a discovery. Every finding is computed from model
   runs. A fine design clears the rule (status `no_action_justified`).
   Cleared checks stay in the output on purpose.
2. Impact figures come from model runs of the changed design. Each one
   states its assumptions and a sensitivity range (low, base, high).
   There are no fixed saving percentages.
3. A recommendation that changes the process carries a quality gate. The
   gate checks product quality, computed where the model allows it.
4. Computed evidence is kept apart from hypotheses. Every possible cause is
   tagged `observed` or `hypothesis`.

## 3. The rules

### R1: hydrogen supply to the methanation step

Trigger. The model's own flag `h2_limited` is set. And the achieved CO2
conversion falls more than 5 points below the requested value. The
requested value is the catalyst capability set in the model.

Evidence. Requested against achieved conversions. Hydrogen leaving the
reactor (near zero confirms the shortage). CO2 left in the dry product.

Impact. The advisor reruns the model with the balanced shift target
(`wgs_target="stoichiometric"`). Same feed, same conversions. It reports
the computed changes: product CO2, production, steam, cooling. Sensitivity:
the production loss at CO2 removal of 85, 90 and 95 percent. Each point
compares the two designs at the same removal.

Quality gate. CO in the dry product after the change, against the 0.1 mol
percent limit from R3. The gate is `passed` only when the computed value is
within the limit. Otherwise it is `conditional` and says why.

Severity. `high` when the shortfall exceeds 30 points, else `medium`.

Clears when the flag is not set, or the shortfall is 5 points or less.
The `balanced_ratio` scenario clears this rule.

### R2: heat integration

Trigger. The methanation cooling duty and the feed preheat duty come from
the energy block. Recoverable heat is assumed to be 60 to 85 percent of the
reactor duty. The rule fires when the base estimate (72.5 percent) exceeds
the preheat duty.

Recommendation. A feed-effluent heat exchanger (gas-gas interchanger).

Impact. The preheat duty eliminated, in kW and in kWh per year at 8,000
hours. Also the reactor cooling still needed after recovery. Sensitivity:
the saving at each recovery fraction, capped at the preheat duty.

Quality gate. Heat exchange moves heat only, not mass, so the modelled
composition is unchanged. The gate stays `conditional`: a real design must
hold the reactor inlet temperature and confirm purity at commissioning.

Severity. `high` when even the 60 percent estimate covers the preheat,
else `medium`.

Clears when the base estimate does not exceed the preheat duty.

### R3: product gas against pipeline quality

Trigger. The dry product is compared with three illustrative limits:
CH4 above 95, CO below 0.1, inert gas (CO2 plus N2) below 4 mol percent.
The rule fires when any component is out.

Evidence. The gap per component, in points. Plus sweep evidence: at 95
percent CO2 removal the purity still misses the CH4 limit.

Recommendation. Three design additions, each a hypothesis to evaluate, not
a sized design. Deeper CO2 removal for the CO2 share. Hydrogen recycle or
a membrane for CO and H2 slip. Nitrogen management at the gasifier for N2.

No impact figure is claimed, because nothing is sized. Severity is `high`
when CH4 or inerts are out, `medium` when only CO is out.

Clears when all three components are within the limits.

### R4: CO slip risk as the catalyst ages

Trigger. The rule finds the lowest CO conversion that keeps product CO
within 0.1 mol percent. It scans the conversion sweep first. When no sweep
point passes, it solves the model directly by bisection (fixed iterations,
deterministic). A safe design sits at least 1 point above that minimum.

Statuses. `no_action_justified` when the design holds the margin.
`conditional` when the product is in spec but the margin is thin.
`action_recommended` when the product is out of spec, or the limit is out
of reach. The aged catalyst scenario is quoted as evidence of decay.

Recommendation. A product CO analyser alarm at the limit, plus a
conversion threshold. When conversion alone cannot hold the limit, the
rule points to the design additions in R3.

### R5: what the model leaves out (informational)

Always `informational`. It lists four model gaps and what a real design
step would add. No kinetics or reactor sizing. No recycle. A condenser
duty without latent heat; the missing duty is computed from the condensate
flow at an assumed 2,400 kJ/kg. No costs. Nothing is invented to fill
these gaps.

## 4. Output contract

The JSON has two top-level keys: `meta` and `findings`. `meta` carries the
generation time, the method, the scenario analysed, the design basis, the
full threshold table and a note. Each finding has exactly these keys, in
this order: `id`, `title`, `status`, `severity`, `problem`, `evidence`,
`possible_causes`, `recommendation`, `expected_impact`, `tradeoffs`,
`quality_gate`, `validation_required`.

Statuses are `action_recommended`, `conditional`, `no_action_justified` or
`informational`. Severity is `high`, `medium`, `low` or null. The JSON is
strict: no NaN or Infinity; a missing number becomes null.

## 5. Tests

`tests/test_advisor.py` checks every rule both ways: a case where it fires
and a case where it clears. R1 must clear on the `balanced_ratio`
scenario. R2 must clear on a constructed low-exotherm design. Impact
numbers are compared against independent model runs made inside the tests.
Determinism is tested by running the advisor twice and comparing the JSON.

## 6. Limitations

The advisor only sees the model, so it inherits every model limitation
listed in `docs/CALCULATIONS_AND_VALIDATION.md`. The recovery fractions,
the pipeline limits and the margins are stated review assumptions, not
measurements. The findings rank engineering effort. They do not rank money,
because the model carries no costs.
