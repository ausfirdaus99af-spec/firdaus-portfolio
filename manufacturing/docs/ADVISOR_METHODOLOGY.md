# Operations Improvement Advisor: Methodology

Project 03 - Manufacturing Performance Analytics. All data is synthetic.

The advisor reads the exported production rows and produces six findings.
Every finding comes from an explicit rule with documented thresholds.
Nothing is hardcoded as a discovery. Rebuild the data and the findings
change with it, including to "no action justified".

- Engine: `scripts/advisor.py` (pure functions, no file access)
- Builder: `scripts/build_advisor.py` writes `data/advisor_findings.json`
- The builder also runs at the end of `scripts/build_mfg_data.py`
- Tests: `tests/test_advisor.py`

## How to read a finding

Each finding carries the same fields.

- `status`: one of four values.
  - `action_recommended`: the data justifies an action now.
  - `conditional`: an action only if a named check passes first.
  - `no_action_justified`: the check ran and cleared. Kept on purpose.
  - `informational`: context, not a call to act.
- `severity`: high, medium, low, or null when cleared.
- `evidence`: the computed numbers. Summary first, details after.
- `possible_causes`: each tagged `observed` or `hypothesis`.
  Observed means computed from this dataset. Hypothesis means it needs
  a measurement the dataset does not hold.
- `expected_impact`: computed from the actual rows. Always a range
  (low, base, high), never a fixed saving claim.
- `quality_gate`: the quality check a throughput or energy saving
  depends on. The quality rate is never assumed to survive a speed-up.
- `validation_required`: what to measure before spending money.

All thresholds below also sit in `THRESHOLDS` in `scripts/advisor.py`.
They are copied into the output JSON so every number can be traced.

## R1: Dominant downtime cause

What it does. Ranks downtime causes by lost hours (Pareto). Micro stops
with no recorded cause are excluded.

Fires when one cause holds over 25 percent of lost hours. Severity is
high above a 40 percent share.

Impact. Assume the top cause shrinks by 30 to 50 percent (sensitivity
range, base 40). The freed hours become units at each affected shift's
own measured speed (realised rate = actual units / run hours). Extra
units also convert to plan-achievement points. No fixed percentages:
the figures come from the affected rows.

Recommendation depends on the cause. Changeover: standardised changeover
work (SMED style). Breakdown: planned maintenance. Anything else: a
focused reduction programme on that cause.

Quality gate. Extra output is counted at each shift's own quality rate.
Faster working must not raise rejects. The gate stays conditional.

## R2: Worst line availability gap

What it does. Compares each line's availability with the best line.
Only dates and shifts that every line ran are compared, so the period
mix is identical. In this dataset every line runs every date and shift.

Fires when a line trails the best by more than 2 percentage points over
the full period. Severity is high above 4 points.

Crash weeks. One bad week can hide the real story. For each trailing
line the rule finds its single worst downtime week. It then reports two
numbers: the full-period gap and the chronic gap with that week set
aside. The impact uses the chronic gap only. The crash week deserves its
own one-off review, not a line programme.

Impact. Closing 50 to 100 percent of the chronic gap (base 75). Extra
run hours become units at the trailing line's own realised rate.

Causes. Where the hours go is observed, by reason and line. Equipment
age is a hypothesis. The data shows the hours, not the kit's condition.

Quality gate. Conditional, as in R1.

On the current dataset this check clears. The widest gap is 1.96 points,
just under the 2 point threshold. The cleared finding still reports the
chronic and crash-week numbers.

## R3: Day against night shift performance

What it does. Compares running speed (performance against nameplate)
between day and night shifts.

Mix adjustment. A raw day-to-night gap can be pure product mix. So the
rule compares day and night inside each line and product cell first.
Cell gaps are then weighted together by each cell's share of ideal
output (ideal rate x run hours). Cells present on only one shift are
excluded. A gap that is pure mix disappears under this adjustment, and
a test proves it.

Fires when the mix-adjusted gap passes 1.5 percentage points. Severity
is high above 3 points.

Impact. Closing 50 to 100 percent of the gap (base 75). Computed per
cell from the night shifts' own run hours and nameplate rates. Only
cells where day is faster contribute.

Causes. The gap itself is observed. Staffing, supervision and training
are stated as hypotheses. Validation is a time and motion observation,
not an assumption.

Quality gate. Night quality at the higher speed must be measured during
any trial. Conditional.

## R4: Maintenance programme check

What it does. This rule verifies an improvement instead of proposing
one. A maintenance programme started on 2026-07-01. The rule compares
breakdown hours per shift before and after that date, per line and for
the plant.

One-off events are not credited to the programme. The single worst
breakdown week before the start date is set aside for the decision.
Both versions of the numbers are reported.

Decision. The fall must be at least 15 percent and clear of noise
(z score of 2 or more, two-sample comparison of per-shift breakdown
hours). If it is, the status is `action_recommended`: continue and
extend the programme. If not, the status is `informational` and no
extension is recommended.

Honesty limits. This is a before-and-after comparison only. There is no
control group, so the cause is likely but not proven. The finding says
so in plain words.

Impact. The observed fall, projected over a year, sustained at 50 to
100 percent (base 75). Reported in avoided hours and protected units.

## R5: Energy used during downtime

What it does. Fits hourly energy on two regressors: units made and
downtime hours (ordinary least squares). The downtime coefficient is
the idle draw: energy that flows while nothing is made.

Fires when the downtime coefficient passes 5 kWh per downtime hour and
its t statistic passes 2. Severity is high when idle energy passes
2 percent of all energy.

A caution on the fit. Units made and downtime hours move together by
construction (more downtime means fewer units). The t statistic reports
how clearly the two effects separate. The cleared finding still shows
the fitted values.

Impact. Annual idle energy = coefficient x annual downtime hours.
Assume 30 to 70 percent of it can be switched off safely (base 50).
Validation is submetering and a one-line trial.

Quality gate. Restarting after a shutdown can scrap the first units
(restart scrap). Reject rates at restart must be measured, not assumed.
Conditional.

## R6: Rejection concentration

What it does. Measures the reject rate for every line and product cell
(weighted: rejected units / actual units). Cells under 50 shifts are
skipped as too small.

Fires when the top cell sits at least 0.3 percentage points above the
rest of the plant and at least 1.10 times its rate. Severity is high
from 1.0 point of excess.

Impact. Bring the hot cell down to the rest-of-plant rate. Recovered
good units = excess rate x the cell's own output. Closing 50 to 100
percent of the excess (base 75).

Validation. A first-pass quality investigation on the flagged cell. The
dataset counts rejects but does not record reject reasons. That gap is
stated, not papered over.

## Determinism and rebuilds

`run_advisor` adds no timestamps, so the same rows always give the same
findings. The builder adds `generated_at` when writing the JSON. Tests
check determinism, the JSON contract, and a positive and a negative
case for every rule.

Rebuild everything with:

    python scripts/build_mfg_data.py

That regenerates the dataset, the database, the dashboard JSON and the
advisor findings in one run.
