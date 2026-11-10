# EcoFlow - Advisor Methodology

The Engineering Improvement Advisor is a rule engine. It lives in `scripts/advisor.py`. It reads the cleaned baseline hourly record. It produces six findings. `scripts/build_advisor.py` writes them to `data/advisor_findings.json`. This document defines every rule, threshold, formula, assumption and limitation. The data is the same 100 percent synthetic record described in `METHODOLOGY.md`. Nothing here is a real plant.

## Integrity principles

1. **Nothing is hardcoded as a discovery.** Every finding is computed from the data by an explicit rule. The thresholds are listed below. They are also copied into the JSON (`meta.thresholds`), so every number can be traced.
2. **Cleared checks are a feature.** Sometimes the data does not justify a recommendation. The rule then returns `no_action_justified`, and the result stays in the output. Different data gives different findings, including cleared ones.
3. **Impact figures carry assumptions and a range.** Savings come from fitted or measured values. They are reported as low, base and high cases. There are no fixed claims.
4. **Quality gates.** Some recommendations would cut electricity or chemicals. Each one carries a check that treatment must stay acceptable. That check cannot be completed from this dataset. So the gate stays `conditional`, and the finding says so.
5. **Evidence against hypothesis.** Every possible cause is tagged. `observed` means computed from this record. `hypothesis` means it needs further measurement. Wording never upgrades a hypothesis.

## Data basis

- Scenario analysed: **baseline** only. The optimised scenario is a modelled comparison, not an operating record to advise on.
- Cleaning: rules R1 and R3 to R5 run on cleaned data (`analytics.clean_hourly`). Cleaning removes tagged sensor artefacts. It also removes readings outside the plausibility ranges in `analytics.PLAUSIBLE_RANGES`. R2 runs on the raw record on purpose. Unreliable readings are exactly what R2 measures.
- The record covers 120 days (2,880 hours) of hourly values. Yearly scaling factors are documented per rule.

## How to read a finding

- `status`: `action_recommended` means the data justifies acting. `conditional` means an action exists but waits on a measurement or trial. `no_action_justified` means the check is cleared. `informational` is context only.
- `severity`: `high`, `medium` or `low`, by each rule's stated criterion. It is `null` for cleared and informational findings.
- `evidence.details`: strings with the actual numbers and dates the rule computed.
- `quality_gate.outcome`: `passes`, `conditional` or `fails`. No gate in this project can reach `passes`. Treatment performance under a changed setpoint is not measurable from this dataset.

## R1 - Treatment upsets (hours of poor COD removal)

**Rule.** On cleaned baseline data, compute hourly COD removal:

    removal (%) = (influent COD - effluent COD) / influent COD x 100

Find stretches of consecutive clock hours where removal stays below the floor. A stretch counts as an upset when it lasts the minimum duration or longer.

**Thresholds.** Removal floor: 75 percent. Minimum length: 3 hours. Severity is `high` when the summed extra COD exceeds 500 kg, otherwise `medium`. Why 75? The normal band in this record sits around 88 percent (median). The floor sits well below it, so only real departures qualify. Why 500 kg? It was chosen from the data distribution. One long upset produces roughly that much extra COD.

**Extra COD mass.** For each upset hour:

    expected effluent COD = influent COD x (1 - reference removal / 100)
    extra (kg) = flow (m3/h) x (actual effluent COD - expected effluent COD) (mg/L) / 1000

The reference removal is the **median hourly removal over all upset-free cleaned hours**. So each upset is charged only against the plant's own normal performance. It is not charged against a theoretical ideal.

**Incoming strength test (observed).** The rule compares median influent COD during upsets against upset-free hours. The influent counts as unusually strong only above +10 percent. The result is reported either way. "The influent did not cause this" is then evidence, not an assumption.

**Hypotheses needing measurement.** Stressed or poisoned biomass. Failed aeration or equipment. Toxic compounds in the influent. The dataset has no dissolved oxygen, microscopy or influent screening data. So the rule cannot choose between these, and says so (see R6).

**Limitations.** A cleaned-out (bad) hour breaks the stretch. One long upset can then count as two. That is conservative for counting and neutral for the mass total. Removal is concentration-based. The project assumes effluent flow equals influent flow.

## R2 - Sensor health

**Rule.** Check each of the nine sensor columns. Count bad readings from the record's tags **plus independent checks**. Compare the per-column rate with the threshold. The independent checks are:

- `missing`: the reading is empty.
- `spike_above_range`: the reading is above the column's plausible maximum.
- `impossible_low`: the reading is below the plausible minimum. Zero or negative counts where that is physically impossible.
- `stuck`: the reading sits in a run of 3 or more identical consecutive values. Real sensor noise makes such exact repeats implausible on continuous signals.

A reading can trip more than one check. The per-column count is the union, so the rate never double-counts.

**Thresholds.** A column fails above 0.3 percent bad readings. That is about one bad reading per fortnight at hourly resolution. It is a practical maintenance trigger. Severity is `high` above 1 percent, otherwise `medium`.

**Evidence.** Counts by check type. Up to three example timestamps. The column's worst month. The record's own tags are reported alongside as a cross-check.

**Recommendation mapping.** The main fault type selects the action. Stuck: maintenance and cleaning schedule, plus repeat-value alarms. Spikes: signal filtering plus a calibration check. Missing: logger and connectivity investigation. Impossible-low: zero-drift and calibration check. If every column is below the limit, the finding is a cleared check.

**Limitations.** The stuck check assumes noisy continuous signals. A genuinely quantised instrument would need a different rule. The plausibility ranges are deliberately wide. Small drift inside the range is not caught. Lab verification would catch it (see R6).

## R3 - Always-on electricity use (base load)

**Rule.** On cleaned, normal-status hours, fit a straight line (ordinary least squares):

    electricity (kWh/h) = a + b x flow (m3/h)

Report the fit quality (R2). The intercept `a` is use that does not scale with flow. The base-load share is:

    share (%) = a / mean(kWh per hour) x 100

**Thresholds.** The check fires above a 15 percent share. That is a practical screening level for always-on use worth surveying. Severity is `high` above twice the threshold (30 percent), otherwise `medium`. At or below 15 percent the finding is a cleared check. A negative intercept also clears; it is statistically the same as zero here. The cleared check still reports `a`, `b` and R2.

**Impact (when fired).** Model a cut of the fitted intercept by an assumed 20 to 50 percent:

    saving (kWh/yr) = a x cut x 8760

Reported as low (20 percent), base (35 percent) and high (50 percent). Also reported: the base saving as a share of yearly use (mean hourly kWh x 8760). The achievable cut is an assumption until submetering attributes the base load.

**Quality gate.** The cut is assumed not to affect treatment. Only flow-independent equipment would be cut. That is an assumption, not a verified result. So the gate is `conditional`. Confirm the targets play no treatment role. Watch removal KPIs during a trial switch-off.

**Limitations.** A straight line in flow is a screening model. It cannot separate aeration from auxiliaries; no submetering exists (see R6). The intercept also absorbs any curve shape at low flow.

## R4 - Coagulant dose response

**Rule.** On cleaned, normal-status hours, compute the specific dose (g/m3 = kg x 1000 / flow). Compute hourly TSS removal. Test the link two ways. First: the correlation coefficient. Second: mean removal in the top dose quartile against the bottom dose quartile.

**Thresholds.** The response counts as invisible when the top-minus-bottom difference is under 1.0 percentage point. One point is the smallest difference that would matter operationally here. It also sits comfortably above this record's quartile-mean noise floor.

**Branch 1: the data shows a positive response** (difference at or above +1.0 point). The finding is `no_action_justified` for dose reduction. Cutting dose would be expected to cost removal. The finding says exactly that. No impact is computed.

**Branch 2: removal does not change with dose.** The finding is `conditional`. The data cannot pick between two explanations, and the finding lists both:

- dosing already sits past the point of diminishing returns (saturation plateau), a hypothesis; or
- a real response is hidden by noise and the narrow operating range, also a hypothesis.

The recommendation is a **controlled stepped-dose trial first**. No reduction is justified today. An apparent negative difference is treated the same way. It is noted as more likely a shared driver (confounding) than a real effect.

**Impact (conditional, only if the trial confirms the plateau).** Trim doses above the median down to the median:

    period saving (kg) = sum over hours of max(0, dose - target) x flow / 1000
    yearly saving (kg/yr) = period saving x 365 / period days

Computed from the actual dose distribution. Sensitivity: trim target at the P60 (low), P50 (base) and P40 (high) dose percentile. A lower target trims more and saves more.

**Quality gate.** `conditional`. The trial must show TSS removal unaffected at the trimmed doses. The gate cannot pass on the current data.

**Limitations.** The observed dose range is narrow; the plant was not experimenting. That is exactly why the rule refuses to conclude. Savings assume this period represents a full year. The calculation uses cleaned normal-status hours only.

## R5 - Effluent pH control

**Rule.** Count cleaned hours with effluent pH outside 6.5 to 7.8. Record the worst excursion depth (pH units beyond the nearer bound). Compare the excursion hours with the R1 upset hours and report the overlap. The overlap is observed evidence. It links, or separates, pH problems and treatment upsets.

**Thresholds.** Under 20 excursion hours in the 120 day period, the check is cleared. When fired: severity is `high` above 100 hours, or above a 1.0 pH unit depth. Otherwise `medium`. The 6.5 to 7.8 band is a typical expectation for neutralised discharge. This project models no regulatory limit.

**Limitations.** Cleaning removes pH sensor spikes first. So this rule measures process control, not instrument faults; R2 covers those. Depth is per hour. Cumulative exceedance is not modelled.

## R6 - Missing measurements (always informational)

The rule checks the dataset's columns. It lists measurements that are absent, why each matters, and what to measure. Nothing is invented to fill the gaps. The simulation is not extended.

- **Dissolved oxygen** in the biological stage. Without it, R1 upsets cannot be traced to aeration, overload or poisoning.
- **Blower and aeration power submetering.** R3 sees one total meter. The biggest consumer cannot be separated.
- **Controlled dose-response trial data.** R4 cannot tell a plateau from noise without varied doses.
- **Design capacity and equipment ratings.** Loads cannot be judged against design limits.
- **Laboratory-verified samples.** Online COD, TSS and pH readings are never checked against lab values here.

## Output contract

`data/advisor_findings.json` holds `meta` and `findings`. The meta carries the generation time, method, scenario, period, the full threshold table and a rebuild note. The findings are ordered R1 to R6. Each finding has: id, title, status, severity, problem, evidence (summary plus detail strings with real numbers and dates), possible_causes (each tagged observed or hypothesis), recommendation, expected_impact (null, or summary, calculations, assumptions and a low/base/high sensitivity), tradeoffs, quality_gate and validation_required. The JSON is strict: no NaN or Infinity, numbers rounded sensibly. The engine is deterministic for a given input. Only `generated_at` changes between rebuilds on the same data.

## Rebuild

`python scripts/build_dashboard_data.py` regenerates the dataset and dashboard JSON. It then rebuilds the advisor findings. `python scripts/build_advisor.py` rebuilds the findings alone from the existing CSV. The test suite in `tests/test_advisor.py` exercises every rule in both its firing and cleared states. It proves determinism. It also proves the findings change when the data changes.
