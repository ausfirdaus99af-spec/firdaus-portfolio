# KPI Definitions

Project 03 - Manufacturing Performance Analytics. All figures in this
document are synthetic examples.

## Conventions that apply to every KPI

**Planned break exclusion.** Each shift is 8 hours with a 0.5 hour planned
break. Planned production time is 7.5 hours, and that 7.5 hours is the
denominator for availability and capacity. The planned break is excluded
because OEE measures losses against the time the plant intended to run,
not against the clock.

**Zero denominators return NaN.** A KPI with a zero denominator (for
example quality on a shift with zero actual units) is undefined. The
functions in `scripts/kpis.py` return NaN rather than zero, because zero
would look like a terrible result instead of a missing one. The exported
JSON never contains NaN; the full dataset has no zero denominators.

**Percentages are never averaged.** Aggregating over many rows always uses
time weighted sums, never the mean of row level percentages. A plain
average gives a 1 hour run the same weight as a 7.5 hour run and produces
a wrong answer. Worked counterexample: one run makes 1,000 units with 900
good (90 percent quality) and another makes 10 units with 10 good (100
percent). The naive average says 95 percent; the true quality is
910 / 1,010 = 90.1 percent.

Weighted aggregation over a set of rows:

- availability = sum(run_time) / sum(planned_time)
- performance = sum(actual) / sum(ideal_rate x run_time, per row)
- quality = sum(good) / sum(actual)
- OEE = availability x performance x quality

## Worked mini example

One shift: planned 8,280 units, actual 7,700, good 7,600, rejected 100,
planned time 7.5 h, run time 7.0 h (0.5 h downtime), ideal rate 1,200
units per hour, energy 3,000 kWh.

## The ten KPIs

### 1. Production achievement (%)

`actual_units / planned_units x 100`

How much of the plan was delivered. Example: 7,700 / 8,280 = 93.0%.

### 2. Capacity utilisation (%)

`actual_units / (ideal_rate_uph x planned_time_h) x 100`

Output against the theoretical maximum for the planned time. Example:
7,700 / (1,200 x 7.5) = 85.6%.

### 3. Yield (%)

`good_units / actual_units x 100`

Share of production that is good. Example: 7,600 / 7,700 = 98.7%.

### 4. Rejection rate (%)

`rejected_units / actual_units x 100`

Share of production rejected. Yield plus rejection rate always equals
100. Example: 100 / 7,700 = 1.3%.

### 5. Availability (%)

`run_time_h / planned_time_h x 100`

Share of planned production time actually spent running. The 7.5 hour
denominator already excludes the planned break. Example: 7.0 / 7.5 =
93.3%.

### 6. Performance (%)

`(actual_units / run_time_h) / ideal_rate_uph x 100`

Actual speed against nameplate speed while running. Example:
(7,700 / 7.0) / 1,200 = 91.7%.

**Deliberately not capped at 100.** Some conventions cap performance at
100, but the ideal rate is a nameplate figure and a line can genuinely
beat it for a shift, for example after a tuning improvement or with an
easy product mix. Capping would hide that signal and silently understate
OEE, so values above 100 are allowed and simply mean the line ran faster
than nameplate.

### 7. Quality (%)

`good_units / actual_units x 100`

Identical to yield by construction; both names are kept because yield is
the production term and quality is the OEE term. Example: 98.7%.

### 8. OEE (%)

`availability_pct x performance_pct x quality_pct / 10000`

Overall equipment effectiveness, the product of the three OEE components.
Example: 93.3 x 91.7 x 98.7 / 10,000 = 84.4%.

### 9. Energy intensity (kWh per good unit)

`energy_kwh / good_units`

Energy consumed per saleable unit. Good units, not actual units, because
energy spent on rejected product is a loss. Example: 3,000 / 7,600 =
0.39 kWh per good unit.

### 10. Downtime by cause (Pareto)

Downtime hours grouped by reason, sorted descending, with each cause's
share of total downtime and the cumulative share. The cumulative column
reads as a classic Pareto curve: a few causes usually account for most of
the hours. Rows with reason None (micro stops under 0.1 hours) are
excluded because they have no attributable cause. The overall KPI set also
carries `downtime_hours_total`, the plain sum of all downtime hours.
