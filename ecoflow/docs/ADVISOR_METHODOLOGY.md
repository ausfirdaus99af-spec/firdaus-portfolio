# EcoFlow - Advisor Methodology

The Engineering Improvement Advisor (`scripts/advisor.py`) is a deterministic, rule-based engine that reads the cleaned baseline hourly record and produces six findings, written to `data/advisor_findings.json` by `scripts/build_advisor.py`. This document defines every rule, threshold, formula, assumption and limitation. The data is the same 100 percent synthetic record described in `METHODOLOGY.md`; nothing here is a real plant.

## Integrity principles

1. **Nothing is hardcoded as a discovery.** Every finding is computed from the data by an explicit rule with the thresholds listed below. The thresholds are also copied into the JSON (`meta.thresholds`) so each number can be traced.
2. **Cleared checks are a feature.** When the data does not justify a recommendation, the rule returns `no_action_justified` and the result stays in the output. Rebuilding with different data changes the findings, including to cleared.
3. **Impact figures carry assumptions and a sensitivity range.** Savings are computed from fitted or measured values, reported as low, base and high cases, never as a fixed claim.
4. **Quality gates.** Any recommendation that would reduce electricity or chemical use carries an explicit check that predicted treatment performance stays acceptable. Where that check cannot be completed from this dataset, the gate is `conditional` and the finding says so.
5. **Evidence against hypothesis.** Every possible cause is tagged `observed` (computed from this record) or `hypothesis` (needs further measurement). Hypotheses are never upgraded by wording.

## Data basis

- Scenario analysed: **baseline** only. The optimised scenario is a modelled comparison, not an operating record to advise on.
- Cleaning: all rules except R2 run on the output of `analytics.clean_hourly`, which removes rows tagged as sensor artefacts plus any reading failing the plausibility ranges in `analytics.PLAUSIBLE_RANGES`. R2 deliberately runs on the raw record because unreliable readings are exactly what it measures.
- The record covers 120 days (2,880 hours) of hourly values. Annualisation factors are documented per rule.

## How to read a finding

- `status`: `action_recommended` (the data justifies acting), `conditional` (an action exists but is gated on a measurement or trial), `no_action_justified` (cleared check) or `informational`.
- `severity`: `high`, `medium` or `low` by each rule's documented criterion; `null` for cleared and informational findings.
- `evidence.details`: strings containing the actual numbers and dates the rule computed.
- `quality_gate.outcome`: `passes`, `conditional` or `fails`. In this project no gate can reach `passes`, because treatment performance under a changed setpoint is not measurable from the current dataset.

## R1 - Process upsets (episodes of low COD removal)

**Rule.** On cleaned baseline data, compute hourly COD removal:

    removal (%) = (influent COD - effluent COD) / influent COD x 100

Find contiguous windows of consecutive clock hours where removal stays below the floor. A window qualifies as an episode when it lasts the minimum duration or longer.

**Thresholds.** Removal floor 75 percent; minimum episode length 3 hours; severity is `high` when the summed excess COD mass exceeds 500 kg, otherwise `medium`. The 75 percent floor sits well below the normal operating band observed in this record (median removal about 88 percent), so only genuine departures qualify; 500 kg was chosen from the data distribution as roughly the excess a single long episode produces.

**Excess COD mass.** For each episode hour:

    expected effluent COD = influent COD x (1 - reference removal / 100)
    excess (kg) = flow (m3/h) x (actual effluent COD - expected effluent COD) (mg/L) / 1000

where the reference removal is the **median hourly removal over all episode-free cleaned hours**. This charges each episode only for the shortfall against the plant's own demonstrated performance on the same influent, not against a theoretical ideal.

**Influent strength test (observed).** The rule compares median influent COD during episodes against episode-free hours. Influent counts as unusually strong only when the episode median is more than 10 percent above normal. The result is reported either way, so "the influent did not cause this" is evidence, not an assumption.

**Hypotheses needing measurement.** Biological stress or toxic shock, aeration or mechanical failure, and inhibitory compounds are listed as hypotheses. The dataset contains no dissolved oxygen, microscopy or influent screening data, so the rule cannot choose between them, and says so (see R6).

**Limitations.** A cleaned-out (anomalous) hour breaks contiguity, which can split one long episode into two; this is conservative for episode counting and neutral for the mass total. Removal is concentration-based under the project's stated equal-flow assumption.

## R2 - Sensor reliability

**Rule.** For each of the nine sensor columns, count flagged readings from the record's anomaly tags **plus independent plausibility checks**, then compare the per-column rate with the threshold. The independent checks are:

- `missing`: the reading is empty.
- `spike_above_range`: the reading exceeds the column's plausible maximum.
- `impossible_low`: the reading is below the plausible minimum (zero or negative where that is impossible).
- `stuck`: the reading belongs to a run of 3 or more identical consecutive values. On continuous signals with real sensor noise, exact repeats of that length are implausible.

A reading can trip more than one check; the per-column count is the union, so nothing is double-counted in the rate.

**Thresholds.** A column fails when more than 0.3 percent of its readings are flagged (about 1 bad reading per fortnight at hourly resolution, a practical maintenance trigger). Severity is `high` above 1 percent, otherwise `medium`.

**Evidence.** Counts by check type, up to three example timestamps, and the column's worst month. The record's own tags are reported alongside as a cross-check.

**Recommendation mapping.** The dominant fault type selects the action: stuck leads to a preventive maintenance and cleaning schedule with repeat-value alarms; spikes lead to signal filtering plus a calibration check; missing leads to logger and connectivity investigation; impossible-low leads to a zero-drift and calibration check. If every column is below threshold the finding is a cleared check.

**Limitations.** The stuck check assumes noisy continuous signals; a genuinely quantised instrument would need a different rule. Plausibility ranges are deliberately wide, so marginal drift within range is not caught (lab verification would be, see R6).

## R3 - Energy base load

**Rule.** On cleaned, normal-status hours, fit ordinary least squares:

    electricity (kWh/h) = a + b x flow (m3/h)

and report the fit quality R2. The intercept `a` is consumption that does not scale with flow. The base-load share is:

    share (%) = a / mean(kWh per hour) x 100

**Thresholds.** The check fires when the share exceeds 15 percent (a practical screening level for flow-independent consumption worth surveying). Severity is `high` above twice the threshold, otherwise `medium`. At or below 15 percent (including a negative intercept, which is statistically indistinct from zero here) the finding is a cleared check that still reports `a`, `b` and R2.

**Impact (when fired).** Modelled reduction of the fitted intercept by an assumed 20 to 50 percent:

    saving (kWh/yr) = a x reduction x 8760

reported as sensitivity low (20 percent), base (35 percent) and high (50 percent), plus the base saving as a share of modelled annual consumption (mean hourly kWh x 8760). The achievable reduction is explicitly an assumption until the base load is attributed by submetering.

**Quality gate.** Base-load cuts are assumed not to affect treatment because only flow-independent consumers would be cut. That is an assumption, not a verified result, so the gate is `conditional`: confirm the targeted consumers play no treatment role and watch removal KPIs during a trial switch-off.

**Limitations.** A straight line in flow is a screening model; it cannot separate aeration from auxiliaries (no submetering exists, see R6), and the intercept absorbs any nonlinearity at low flow.

## R4 - Chemical dose response

**Rule.** On cleaned, normal-status hours, compute the specific dose (g/m3 = kg x 1000 / flow) and hourly TSS removal, then test whether removal responds to dose two ways: the correlation coefficient, and a binned comparison of mean removal in the top dose quartile against the bottom dose quartile.

**Thresholds.** The response counts as insensitive when the top-minus-bottom quartile difference is below 1.0 percentage point. (One percentage point is the smallest effect that would matter operationally here and is comfortably above the quartile-mean noise floor of this record.)

**Branch 1: the data shows a positive response** (difference at or above +1.0 percentage point). The finding is `no_action_justified` for dose reduction, because cutting dose would be expected to cost removal, and the finding says exactly that. No impact is computed.

**Branch 2: removal is insensitive across the observed range.** The finding is `conditional`. The data cannot distinguish two explanations, and the finding lists both:

- dosing already sits above the saturation plateau (hypothesis), or
- a real response is hidden by noise and the narrow operating range (hypothesis).

The recommendation is a **controlled stepped-dose trial first**; no reduction is justified today. An apparent negative quartile difference is treated the same way, noted as more plausibly confounding (for example both dose and removal tracking flow) than causal.

**Impact (conditional, only if the trial confirms the plateau).** Trim doses above the median to the median:

    period saving (kg) = sum over hours of max(0, dose - target) x flow / 1000
    annual saving (kg/yr) = period saving x 365 / period days

computed from the actual dose distribution. Sensitivity: trim target at the P60 (low), P50 (base) and P40 (high) dose percentile; a lower target removes more of the distribution and saves more.

**Quality gate.** `conditional`: TSS removal must be shown unaffected at the trimmed doses in the trial. The gate cannot pass on the current data.

**Limitations.** The observed dose range is narrow (the plant was not experimenting), which is precisely why the rule refuses to conclude; savings assume the period's influent and dose distribution represent a full year; the calculation uses cleaned normal-status hours only.

## R5 - Effluent pH control

**Rule.** Count cleaned hours with effluent pH outside 6.5 to 7.8 and the maximum excursion depth (pH units beyond the nearer bound). Compare the excursion hours with the R1 episode hours and report the overlap, which is observed evidence linking (or separating) pH excursions and process upsets.

**Thresholds.** Below 20 excursion hours over the 120 day period the check is cleared. When fired, severity is `high` above 100 hours or a depth greater than 1.0 pH unit, otherwise `medium`. The 6.5 to 7.8 band is a typical neutralised-discharge expectation for this kind of plant; this project models no regulatory limit.

**Limitations.** Cleaning removes pH sensor spikes first, so this rule measures process control, not instrument faults (R2 covers those). Depth is per-hour; cumulative exceedance is not modelled.

## R6 - Data gaps (always informational)

The rule checks the dataset's columns and lists measurements that are absent, why each matters, and what to measure. No values are fabricated and the simulation is not extended to fill them:

- **Dissolved oxygen** in the biological stage: without it, R1 episodes cannot be attributed to aeration shortfall, overload or toxicity.
- **Blower and aeration power submetering**: R3 sees one total meter, so the largest consumer cannot be separated or verified.
- **Controlled dose-response trial data**: R4 cannot distinguish a dosing plateau from noise without deliberately varied doses.
- **Design capacity and equipment ratings**: observed loads cannot be judged against design limits.
- **Laboratory-verified samples**: online COD, TSS and pH readings are not cross-checked against reference values.

## Output contract

`data/advisor_findings.json` contains `meta` (generation time, method, scenario, period, the full threshold table and a rebuild note) and `findings` ordered R1 to R6, each with: id, title, status, severity, problem, evidence (summary plus detail strings with real numbers and dates), possible_causes (each tagged observed or hypothesis), recommendation, expected_impact (null, or summary, calculations, assumptions and a low/base/high sensitivity), tradeoffs, quality_gate and validation_required. The JSON is strict: no NaN or Infinity, numbers rounded sensibly. The engine itself is deterministic for a given input; only `generated_at` changes between rebuilds on the same data.

## Rebuild

`python scripts/build_dashboard_data.py` regenerates the dataset and dashboard JSON and then rebuilds the advisor findings; `python scripts/build_advisor.py` rebuilds the findings alone from the existing CSV. The test suite in `tests/test_advisor.py` exercises every rule in both its firing and cleared states, proves determinism, and proves the findings change when the data changes.
