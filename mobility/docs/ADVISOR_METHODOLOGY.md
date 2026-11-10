# KL Mobility Lab: Evidence and Recommendations Methodology

This documents `scripts/advisor.py` and `scripts/build_advisor.py`. They turn the processed open data into `data/advisor_findings.json`. Every rule, threshold and status decision is recorded here.

Reproduce from the `mobility` folder:

```
python -I scripts/build_mobility_data.py   (full pipeline, advisor included)
python -I scripts/build_advisor.py          (advisor alone)
python -I -m pytest tests -q
```

## What this engine is

It is a deterministic rule engine. Six rules read the processed frames from the pipeline. Each rule has fixed, published thresholds. The same data always gives the same findings. Different data gives different findings, including cleared checks. Cleared checks stay in the output on purpose.

This project uses real open data. The evidence bar is therefore highest here. The engine computes every number it reports. It never claims a congestion impact. No open dataset measures one. Most recommendations are honest next steps: study something, or publish missing data.

## Who the recommendations address

Some findings address data publishers and researchers, not transport operators. The output says so in `meta.audience_note`. R3 and parts of R5 are addressed to the publisher. R1, R4 and R6 mostly name research or publication steps. That is what the evidence supports, and no more.

## Facts, hypotheses and arithmetic

Three kinds of statement appear, always labelled:

- **Observed facts.** Computed from the published files. Tagged `"basis": "observed"`.
- **Hypotheses.** Plausible explanations the data cannot confirm. Tagged `"basis": "hypothesis"`.
- **Arithmetic on observed numbers.** Ratios, shares and percentages. Each states its inputs, so anyone can recheck it.

Every finding cites its source dataset inside the evidence.

## Output contract

Same structure as the EcoFlow advisor. `meta` holds the method, periods, thresholds, a determinism note and `audience_note`. Each finding has exactly these keys: id, title, status, severity, problem, evidence, possible_causes, recommendation, expected_impact, tradeoffs, quality_gate, validation_required. Statuses: `action_recommended`, `conditional`, `informational`, `no_action_justified`. `expected_impact` is null in every mobility finding. No saving or impact figure can be computed honestly from this data. The JSON is strict: no NaN or Infinity.

`generated_at` is added by the build script at write time. The engine itself is timestamp free, so its output is fully deterministic.

## The rules

Thresholds live in `THRESHOLDS` in `scripts/advisor.py`. They are analysis choices, not discoveries. They are copied into the output JSON.

### R1: Weekend service headroom

- **Input:** the 2026 day-of-week rail profile from the pipeline.
- **Computation:** mean of Monday to Friday averages, and mean of Saturday and Sunday averages. The ratio is weekend over weekday.
- **Threshold:** fires when the ratio is below 0.70.
- **Status when fired:** `conditional`, severity medium. The observed gap shows a commuting-dominated demand pattern. The recommendation is a research action only. Off-peak fare and service trials exist in other cities. Evaluating one for KL needs cost and elasticity data. This project does not hold that data, and says so.
- **On the current data:** fired. The ratio is 0.655 (65.5 percent).

### R2: Destination concentration

- **Input:** the cleaned station-level origin-destination detail from the pipeline.
- **Computation:** total recorded alightings per destination. Share of the top 10 destinations against all recorded trips.
- **Thresholds:** fires above a 25 percent share. Severity high above 40 percent, otherwise medium.
- **Status when fired:** `action_recommended`. The action is where to focus further study: last-mile access, crowding and interchange capacity at the named stations. The finding never names an investment.
- **Caveat carried in the evidence:** 28 stations have no alighting records in the published file. True shares may differ slightly.
- **On the current data:** fired at 34.5 percent, severity medium. Busiest: Bukit Bintang, KL Sentral, Tun Razak Exchange.

### R3: Published data quality (addressed to the publisher)

Three checks on the source files. The finding fires when any check fails. Severity is fixed at medium. The audience is the data publisher, and the finding says so.

1. **Hidden marginal rows.** The OD file holds `All Stations` total rows. A naive sum of the file is exactly three times the true total. The pipeline reconciles both marginal sets against the station rows. The check fires when the raw total exceeds the station-level total.
2. **Missing alighting records.** Stations that appear as origins but never as destinations. On the current file: 28 stations, all on the Putrajaya Line.
3. **Reporting gap.** Missing days inside a ridership column's own reporting span. On the current file: LRT Shah Alam, missing 59 of 153 days, 1 May to 28 June 2026.

Recommendations: publish marginals separately or flag them, complete the alighting records, document the gap. Every number comes from the pipeline's reconciliation. Anyone can rerun it and check.

- **On the current data:** fired, 3 of 3 checks fail.

### R4: Ridership recovery against 2019

- **Input:** monthly rail trips from the pipeline.
- **Computation:** each of the last 12 comparable months against the same month of 2019. A month is comparable when its 2019 same month exists.
- **Threshold:** "consistently above" means every window month at or above 100 percent of its baseline.
- **Status:** `conditional` when consistently above, otherwise `informational`. The observed fact is demand growth beyond pre-pandemic levels. The recommendation is a publication request: capacity and reliability monitoring data, which is not open today. The finding explicitly refuses the mode shift claim. No open data measures switching from cars. That stays a tagged hypothesis.
- **On the current data:** fired as conditional. All 12 months above 2019. Range 131.9 to 153.9 percent, average 144.1 percent.

### R5: Car registration data limits

- **Input:** monthly registration transaction counts by region bucket.
- **Computation:** share of 2026 transactions in the Rakan Niaga channel. That channel is a sales channel, not a place.
- **Thresholds:** fires above a 50 percent share. Severity high above 75 percent.
- **Status when fired:** `action_recommended`, two audiences. Analysts: do not use 2026 state counts as a traffic or demand proxy. Publisher: publish a channel-to-state mapping, or add the buyer's state.
- **On the current data:** fired at 87.3 percent (559,794 of 640,875 transactions), severity high.

### R6: What would settle the live-work hypothesis

Always `informational`. It lists the datasets that would let the hypothesis be tested properly. Each entry says how it would be used. The list is grounded in the pipeline's documented gaps:

1. A commuting origin-destination survey, all modes, door to door. It would test the question directly.
2. Workplace geography: jobs by district. With district population, it measures live-work separation on both sides.
3. Road traffic counts and speeds as open time series. They give a congestion outcome to test against.
4. A bus origin-destination matrix and realised bus travel times. They cover the non-rail public transport side.

## Limitations

1. Trips are counted, not people. All rail findings inherit this.
2. The OD file covers rail riders only. Most Klang Valley commuting is by car and is invisible here.
3. Missing Putrajaya Line alightings slightly distort destination shares. R2 and R3 both state this.
4. Thresholds are review choices. The output publishes them so the choice is visible.
5. No congestion impact is claimed anywhere. No open data would support one.

## Testing

`tests/test_advisor.py` covers every rule with firing and cleared fixtures. Shares and ratios are checked against hand-computed values. A balanced destination fixture clears R2. A consistent-marginals fixture clears the triple-count check in R3. The real pipeline output is pinned: statuses, key numbers and the JSON contract. Two runs on the same input must produce byte-identical results.
