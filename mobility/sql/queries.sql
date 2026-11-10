-- KL Mobility Lab: analysis and quality-control queries.
-- Each query starts with a "-- name:" marker. The build script runs all of
-- them: analytical queries must return rows, qc_ queries must return none.

-- name: yoy_monthly_rail_recovery_vs_2019
-- Monthly Rapid Rail trips against the same calendar month of 2019.
-- FIRST_VALUE over each calendar month ordered by year gives the 2019
-- baseline (2019 is the first year of the rail series). pct_of_2019 above
-- 100 means the month beat its 2019 counterpart.
WITH monthly AS (
    SELECT substr(date, 1, 7)  AS ym,
           substr(date, 1, 4)  AS y,
           substr(date, 6, 2)  AS mo,
           SUM(trips)          AS trips
    FROM ridership_daily
    WHERE service_group = 'rail'
    GROUP BY 1, 2, 3
)
SELECT ym,
       trips,
       FIRST_VALUE(trips) OVER (PARTITION BY mo ORDER BY y) AS trips_2019,
       ROUND(100.0 * trips / FIRST_VALUE(trips) OVER (PARTITION BY mo ORDER BY y), 1)
           AS pct_of_2019
FROM monthly
ORDER BY ym;

-- name: top_growth_months
-- Ten months with the strongest year-on-year rail growth (LAG window over
-- the same calendar month). Early post-pandemic months dominate because the
-- 2021 base was suppressed by movement control orders.
WITH monthly AS (
    SELECT substr(date, 1, 7) AS ym,
           substr(date, 1, 4) AS y,
           substr(date, 6, 2) AS mo,
           SUM(trips)         AS trips
    FROM ridership_daily
    WHERE service_group = 'rail'
    GROUP BY 1, 2, 3
),
yoy AS (
    SELECT ym,
           trips,
           LAG(trips) OVER (PARTITION BY mo ORDER BY y) AS trips_prev_year
    FROM monthly
)
SELECT ym,
       trips,
       trips_prev_year,
       ROUND(100.0 * (trips - trips_prev_year) / trips_prev_year, 1) AS yoy_growth_pct
FROM yoy
WHERE trips_prev_year IS NOT NULL
ORDER BY yoy_growth_pct DESC
LIMIT 10;

-- name: weekday_weekend_ratio_by_year
-- Average weekday rail trips divided by average weekend rail trips, per
-- year. strftime('%w') returns 0 for Sunday and 6 for Saturday. A high
-- ratio means commuting dominates; a ratio near 1 means leisure use.
SELECT substr(date, 1, 4) AS year,
       ROUND(AVG(CASE WHEN strftime('%w', date) NOT IN ('0', '6') THEN trips END), 0)
           AS weekday_avg,
       ROUND(AVG(CASE WHEN strftime('%w', date) IN ('0', '6') THEN trips END), 0)
           AS weekend_avg,
       ROUND(AVG(CASE WHEN strftime('%w', date) NOT IN ('0', '6') THEN trips END)
             / AVG(CASE WHEN strftime('%w', date) IN ('0', '6') THEN trips END), 2)
           AS weekday_weekend_ratio
FROM ridership_daily
WHERE service_group = 'rail'
GROUP BY 1
ORDER BY 1;

-- name: registrations_region_share
-- Each region bucket's share of car registration transactions per month.
-- Transactions, not vehicles in traffic; rakan_niaga is a sales channel,
-- not a place, and it carries most transactions.
SELECT month,
       region,
       transactions,
       ROUND(100.0 * transactions / SUM(transactions) OVER (PARTITION BY month), 1)
           AS share_pct
FROM registrations_monthly
ORDER BY month, region;

-- name: population_growth_by_state
-- Year-on-year population growth rate by state using LAG.
SELECT state,
       year,
       persons_k,
       ROUND(100.0 * (persons_k - LAG(persons_k) OVER (PARTITION BY state ORDER BY year))
             / LAG(persons_k) OVER (PARTITION BY state ORDER BY year), 2)
           AS growth_pct
FROM population
ORDER BY state, year;

-- name: qc_no_negative_values
-- Must return zero rows: no negative trips, transactions or counts anywhere.
SELECT 'ridership_daily' AS tbl, date AS k1, service_group AS k2, trips AS v
FROM ridership_daily WHERE trips < 0
UNION ALL
SELECT 'registrations_monthly', month, region, transactions
FROM registrations_monthly WHERE transactions < 0
UNION ALL
SELECT 'population', CAST(year AS TEXT), state, persons_k
FROM population WHERE persons_k < 0
UNION ALL
SELECT 'employment_qtr', quarter, state, employed_k
FROM employment_qtr WHERE employed_k < 0;

-- name: qc_duplicate_keys
-- Must return zero rows: one row per natural key in every table.
SELECT 'ridership_daily' AS tbl, date AS k1, service_group AS k2, COUNT(*) AS n
FROM ridership_daily GROUP BY 2, 3 HAVING COUNT(*) > 1
UNION ALL
SELECT 'registrations_monthly', month, region, COUNT(*)
FROM registrations_monthly GROUP BY 2, 3 HAVING COUNT(*) > 1
UNION ALL
SELECT 'population', CAST(year AS TEXT), state, COUNT(*)
FROM population GROUP BY 2, 3 HAVING COUNT(*) > 1
UNION ALL
SELECT 'employment_qtr', quarter, state, COUNT(*)
FROM employment_qtr GROUP BY 2, 3 HAVING COUNT(*) > 1;

-- name: qc_month_continuity
-- Must return zero rows: within each service group's own observed span,
-- every calendar month is present (series legitimately start on different
-- dates, so continuity is checked per group, not from a global start).
-- Registrations are checked the same way.
WITH rid AS (
    SELECT service_group, substr(date, 1, 7) AS ym
    FROM ridership_daily
    GROUP BY 1, 2
),
rid_agg AS (
    SELECT service_group,
           COUNT(*) AS months_present,
           (CAST(substr(MAX(ym), 1, 4) AS INTEGER) * 12 + CAST(substr(MAX(ym), 6, 2) AS INTEGER))
         - (CAST(substr(MIN(ym), 1, 4) AS INTEGER) * 12 + CAST(substr(MIN(ym), 6, 2) AS INTEGER))
         + 1 AS months_expected
    FROM rid
    GROUP BY 1
),
reg AS (
    SELECT 'registrations' AS service_group,
           COUNT(DISTINCT month) AS months_present,
           (CAST(substr(MAX(month), 1, 4) AS INTEGER) * 12 + CAST(substr(MAX(month), 6, 2) AS INTEGER))
         - (CAST(substr(MIN(month), 1, 4) AS INTEGER) * 12 + CAST(substr(MIN(month), 6, 2) AS INTEGER))
         + 1 AS months_expected
    FROM registrations_monthly
)
SELECT * FROM rid_agg WHERE months_present <> months_expected
UNION ALL
SELECT * FROM reg WHERE months_present <> months_expected;
