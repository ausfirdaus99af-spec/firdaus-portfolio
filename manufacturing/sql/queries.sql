-- Project 03 - Manufacturing Performance Analytics
-- Analytical queries and data quality checks (SQLite). Synthetic data only.
--
-- Conventions:
-- - Each query starts with a "-- name:" marker so the build script can run
--   and check them one by one.
-- - Queries whose name starts with qc_ are data quality checks. They return
--   the offending rows, so a healthy database returns zero rows for each.
-- - All KPI aggregations are time weighted sums. Row level percentages are
--   never averaged, because that would weight a short run the same as a
--   long one.

-- name: monthly_oee_by_line
-- Monthly OEE per line. The CTE joins each run to its ideal rate, then the
-- aggregation uses the weighted convention: availability is
-- sum(run_time) / sum(planned_time), performance is
-- sum(actual) / sum(ideal_rate x run_time), quality is sum(good) / sum(actual),
-- and OEE is the product of the three.
WITH run_facts AS (
    SELECT
        substr(r.date, 1, 7)          AS month,
        l.name                        AS line,
        r.planned_time_h,
        r.run_time_h,
        r.actual_units,
        r.good_units,
        lp.ideal_rate_uph
    FROM production_runs r
    JOIN lines l
      ON l.line_id = r.line_id
    JOIN line_products lp
      ON lp.line_id = r.line_id
     AND lp.product_id = r.product_id
),
agg AS (
    SELECT
        month,
        line,
        SUM(planned_time_h)                 AS pt,
        SUM(run_time_h)                     AS rt,
        SUM(actual_units)                   AS act,
        SUM(good_units)                     AS good,
        SUM(ideal_rate_uph * run_time_h)    AS ideal_capacity
    FROM run_facts
    GROUP BY month, line
)
SELECT
    month,
    line,
    ROUND(100.0 * rt / pt, 2)                               AS availability_pct,
    ROUND(100.0 * act / ideal_capacity, 2)                  AS performance_pct,
    ROUND(100.0 * good / act, 2)                            AS quality_pct,
    ROUND((100.0 * rt / pt) * (100.0 * act / ideal_capacity)
          * (100.0 * good / act) / 10000.0, 2)              AS oee_pct
FROM agg
ORDER BY month, line;

-- name: downtime_pareto
-- Downtime hours by cause with a window function for the cumulative share.
-- Reason 'None' (micro stops under 0.1 hours) is excluded because it has no
-- attributable cause. Sorted descending so the cumulative column reads as a
-- classic Pareto curve.
WITH by_cause AS (
    SELECT reason, SUM(hours) AS hours
    FROM downtime_events
    WHERE reason <> 'None'
    GROUP BY reason
)
SELECT
    reason,
    ROUND(hours, 1) AS hours,
    ROUND(100.0 * hours / SUM(hours) OVER (), 2) AS pct,
    ROUND(100.0 * SUM(hours) OVER (
              ORDER BY hours DESC
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) / SUM(hours) OVER (), 2) AS cum_pct
FROM by_cause
ORDER BY hours DESC;

-- name: shift_comparison
-- Day versus Night shift using the same weighted aggregation as the monthly
-- query. Night runs with a slightly lower performance factor in the
-- synthetic data, and this query makes that visible.
WITH run_facts AS (
    SELECT
        r.shift,
        r.planned_time_h,
        r.run_time_h,
        r.planned_units,
        r.actual_units,
        r.good_units,
        lp.ideal_rate_uph
    FROM production_runs r
    JOIN line_products lp
      ON lp.line_id = r.line_id
     AND lp.product_id = r.product_id
)
SELECT
    shift,
    COUNT(*)                                                AS runs,
    ROUND(100.0 * SUM(actual_units) / SUM(planned_units), 2) AS production_achievement_pct,
    ROUND(100.0 * SUM(run_time_h) / SUM(planned_time_h), 2)  AS availability_pct,
    ROUND(100.0 * SUM(actual_units)
          / SUM(ideal_rate_uph * run_time_h), 2)             AS performance_pct,
    ROUND(100.0 * SUM(good_units) / SUM(actual_units), 2)    AS quality_pct,
    ROUND((100.0 * SUM(run_time_h) / SUM(planned_time_h))
          * (100.0 * SUM(actual_units) / SUM(ideal_rate_uph * run_time_h))
          * (100.0 * SUM(good_units) / SUM(actual_units))
          / 10000.0, 2)                                      AS oee_pct
FROM run_facts
GROUP BY shift
ORDER BY shift;

-- name: top10_worst_oee_days
-- The ten worst plant level OEE days across all lines and shifts. The Line B
-- breakdown week of March 2026 should dominate this list.
WITH run_facts AS (
    SELECT
        r.date,
        r.planned_time_h,
        r.run_time_h,
        r.actual_units,
        r.good_units,
        lp.ideal_rate_uph
    FROM production_runs r
    JOIN line_products lp
      ON lp.line_id = r.line_id
     AND lp.product_id = r.product_id
),
daily AS (
    SELECT
        date,
        SUM(planned_time_h)              AS pt,
        SUM(run_time_h)                  AS rt,
        SUM(actual_units)                AS act,
        SUM(good_units)                  AS good,
        SUM(ideal_rate_uph * run_time_h) AS ideal_capacity
    FROM run_facts
    GROUP BY date
)
SELECT
    date,
    ROUND(100.0 * rt / pt, 2)              AS availability_pct,
    ROUND(100.0 * act / ideal_capacity, 2) AS performance_pct,
    ROUND(100.0 * good / act, 2)           AS quality_pct,
    ROUND((100.0 * rt / pt) * (100.0 * act / ideal_capacity)
          * (100.0 * good / act) / 10000.0, 2) AS oee_pct
FROM daily
ORDER BY oee_pct ASC
LIMIT 10;

-- name: energy_intensity_by_line_month
-- Energy intensity (kWh per good unit) per line and month: total energy
-- divided by total good units, never an average of per row intensities.
SELECT
    substr(r.date, 1, 7)                              AS month,
    l.name                                            AS line,
    ROUND(SUM(r.energy_kwh), 1)                       AS energy_kwh,
    SUM(r.good_units)                                 AS good_units,
    ROUND(SUM(r.energy_kwh) / SUM(r.good_units), 4)   AS energy_intensity_kwh_per_good_unit
FROM production_runs r
JOIN lines l ON l.line_id = r.line_id
GROUP BY month, line
ORDER BY month, line;

-- name: qc_good_exceeds_actual
-- Data quality check: good units can never exceed actual units.
-- Expected result: zero rows.
SELECT run_id, date, line_id, shift, actual_units, good_units
FROM production_runs
WHERE good_units > actual_units;

-- name: qc_negative_values
-- Data quality check: no production, time, energy or material value may be
-- negative. Expected result: zero rows.
SELECT run_id, date, line_id, shift
FROM production_runs
WHERE planned_units < 0
   OR actual_units < 0
   OR good_units < 0
   OR rejected_units < 0
   OR planned_time_h < 0
   OR run_time_h < 0
   OR energy_kwh < 0
   OR material_kg < 0;

-- name: qc_runtime_exceeds_planned
-- Data quality check: run time can never exceed planned production time.
-- A tiny tolerance covers floating point storage. Expected result: zero rows.
SELECT run_id, date, line_id, shift, run_time_h, planned_time_h
FROM production_runs
WHERE run_time_h > planned_time_h + 0.000001;

-- name: qc_orphan_downtime_events
-- Data quality check: every downtime event must point at a real run.
-- Expected result: zero rows.
SELECT e.event_id, e.run_id, e.reason, e.hours
FROM downtime_events e
LEFT JOIN production_runs r ON r.run_id = e.run_id
WHERE r.run_id IS NULL;

-- name: qc_orphan_run_references
-- Data quality check: every run must reference a known line and a known
-- line and product rate pair. Expected result: zero rows.
SELECT r.run_id, r.date, r.line_id, r.product_id, r.shift
FROM production_runs r
LEFT JOIN lines l ON l.line_id = r.line_id
LEFT JOIN line_products lp
  ON lp.line_id = r.line_id AND lp.product_id = r.product_id
WHERE l.line_id IS NULL
   OR lp.line_id IS NULL;

-- name: qc_duplicate_date_line_shift
-- Data quality check: exactly one run per date x line x shift.
-- Expected result: zero rows.
SELECT date, line_id, shift, COUNT(*) AS n
FROM production_runs
GROUP BY date, line_id, shift
HAVING COUNT(*) > 1;
