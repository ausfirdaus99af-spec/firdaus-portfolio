# KL Mobility Lab: Methodology

Phase 2 documentation for `scripts/build_mobility_data.py`, which turns the raw files catalogued in `SOURCE_CATALOGUE.md` into `data/mobility_data.json`, `data/stops.json` and `data/mobility.db`. Every rule applied between a raw file and an exported number is recorded here. Nothing in the exports is modelled or imputed; the only non-observed block is `simulator_defaults`, which is labelled as stated assumptions inside the file itself.

Reproduce with:

```
python -I scripts/build_mobility_data.py
python -I -m pytest tests -q
```

## Provenance summary

| Export block | Raw file | Publisher | Licence |
|---|---|---|---|
| ridership | `data_raw/ridership_headline.parquet` | data.gov.my (Prasarana, MOT) | CC BY 4.0 |
| od | `data_raw/rapidrail_2026_daily.parquet` | data.gov.my (Prasarana, MOT) | CC BY 4.0 |
| registrations | `data_raw/cars_2026.parquet` | data.gov.my (JPJ, MOT) | CC BY 4.0 |
| population | `data_raw/population_district.parquet` | DOSM via data.gov.my | CC BY 4.0 |
| employment | `data_raw/lfs_qtr_state.parquet` | DOSM via data.gov.my | CC BY 4.0 |
| stops.json | `data_raw/gtfs_rapid_rail_kl/stops.txt` | data.gov.my (Prasarana) | CC BY 4.0 |
| citations | hard-coded from `SOURCE_CATALOGUE.md` | DOSM, TomTom, World Bank, SPAD | per source |

The `citations` block is deliberately hard-coded from the catalogue rather than re-derived, so the figures in the export match the figures verified during Phase 1 word for word. The TomTom figures carry their retrieval date (10 November 2026) because the pages change between editions.

## 1. Ridership (daily trips by service)

**Grain of the raw file:** one row per calendar day, 1 January 2019 to 31 August 2026 (2,800 days), with one integer column per service. Counts are trips (ticketing or gate transactions), not unique people.

**Service grouping.** Each of the 14 service columns is assigned to exactly one group; the mapping lives in `SERVICE_GROUPS` in the build script and a test fails if a raw column is ever unmapped or double-mapped:

- `rail`: `rail_lrt_ampang`, `rail_lrt_kj`, `rail_lrt_shah_alam`, `rail_monorail`, `rail_mrt_kajang`, `rail_mrt_pjy` (all Rapid Rail LRT, MRT and Monorail lines in the Klang Valley).
- `bus`: `bus_rkl`, `bus_rkn`, `bus_rpn` (all Rapid Bus services: Kuala Lumpur, Kuantan, Penang).
- `ktmb`: `rail_ets`, `rail_intercity`, `rail_komuter`, `rail_komuter_utara`, `rail_tebrau` (all KTMB services).

**Missing values are kept missing, never zeroed.** Series start on different dates in the raw file: bus on 1 January 2022, KTMB on 15 October 2020 (so October 2020 is a partial month), MRT Putrajaya on 16 June 2022, LRT Shah Alam on 1 April 2026. The daily group value is the sum of the services that reported that day; a day where no service in the group reported stays missing. Monthly totals use `min_count=1`, so a month with no observations exports as `null`. The dashboard contract allows `null` for `ktmb`; in practice `bus` is also `null` before 2022, and the notes in the JSON say so.

**Observed anomaly.** The LRT Shah Alam column has a gap: after reporting daily through April 2026 it is absent for all of May 2026 and most of June, resuming on 29 June 2026. This is in the published file, not an artefact of processing. It is left as published.

**Aggregations.**
- Monthly totals per group, 2019-01 to 2026-08 (92 months), as plain sums of daily values. A test asserts the monthly totals summed equal the raw daily sum per group, so no trips are gained or lost.
- Weekday profile 2026: the mean of the daily `rail` total by day of week, over the 243 observed days of 2026 (January to August).

## 2. Rail origin-destination matrix

**Grain of the raw file:** one row per date, origin station and destination station, 1 January to 8 November 2026 (312 days, 5,414,760 rows), `ridership` being trips on that pair that day.

### Marginal rows

The file contains a pseudo-station `A0: All Stations` used for published totals:

- rows with origin `A0: All Stations` are column totals (all boardings ending at that destination);
- rows with destination `A0: All Stations` are row totals (all boardings starting at that origin);
- there is no `A0 to A0` row.

Each set of marginals sums to exactly 188,708,443 trips, identical to the sum of the station-level rows, so the raw file's grand total (566,125,329) triple-counts every journey. The pipeline excludes marginal rows from all analysis, verifies that both marginal sets reconcile exactly with the station-level total, and uses **188,708,443 trips over 312 days** as the observed OD total. A spot check on 4 March 2026 confirmed each marginal row equals the corresponding row or column sum to the trip.

### Station name normalisation

Raw station labels have the form `<line code><number>: <name>`, for example `AG07: Masjid Jamek`. The same physical interchange appears once per line (for example `AG07: Masjid Jamek` and `KJ13: Masjid Jamek`; `MR01: KL Sentral` and `KJ15: KL Sentral`). Normalisation rules, in order, all implemented in `normalise_station`:

1. Strip the line code prefix: remove a leading match of `^[A-Z]+\d+:\s*`.
2. Trim leading and trailing whitespace.
3. Collapse runs of internal whitespace to a single space.
4. Apply the manual alias table `STATION_ALIASES`. For the 2026 file this table is empty, because after the prefix is stripped every cross-line variant of a station already shares one spelling. The table exists so later years with diverging spellings have a single place for corrections. Spellings are kept exactly as published, including `Bandar Tun Hussien Onn` and `Cgc Glenmarie`.

The full observed raw-to-clean mapping table is built at run time by `station_mapping` and is available to tests. Normalisation is checked to preserve the trip total exactly.

### The 167 versus 135 mismatch

The catalogue flagged 167 distinct origins against 135 distinct destinations and guessed at inconsistent naming. Investigation showed the real structure:

- One value on each side is the `A0: All Stations` marginal, leaving 166 origin and 134 destination station labels.
- After normalisation these collapse to 154 origin names and 126 destination names (interchange merging accounts for the drop).
- The remaining gap is a genuine coverage gap in the published file, not naming: **28 stations appear as origins but never as destinations**. All 28 carry MRT Putrajaya Line codes (PYL05 to PYL41, for example Kepong Baru, Jinjang, Conlay, Persiaran KLCC and Putrajaya Sentral); only PYL03 Kampung Selamat and PYL04 Sungai Buloh have destination rows. Boardings at these stations are complete (their row totals reconcile), but alightings there are not separately identified anywhere in the file, including the marginals.

This is documented in the JSON notes and means alighting counts understate stations on the Putrajaya Line. It cannot be repaired from this file; it is reported, not patched.

### Exclusions and aggregates

- **Same-station journeys** (origin name equals destination name after normalisation, which includes cross-line pairs at one interchange) are excluded from the top-pairs list: 47,736 rows and 5,831,212 trips, about 3.1 per cent of the total. They remain inside the network total and the boarding and alighting counts, since they are real taps.
- **Top 20 OD pairs** by average daily trips: pair total over 312 days. Pairs are directional; A to B and B to A are listed separately.
- **Top 10 origins** by boardings and **top 10 destinations** by alightings, as averages per observed day.
- `total_avg_daily_trips` is the station-level total divided by 312 observed days.

All averages state the observed period (1 January to 8 November 2026) in the export. Trips are not unique passengers, and this file describes rail users only.

## 3. Car registration transactions

**Grain of the raw file:** one row per registration transaction, 1 January to 30 September 2026 (640,875 rows). This grain is stated in the export notes because it is the main integrity caveat: **registrations are transactions, not vehicles in traffic**, and say nothing about where or how much a car is driven.

Monthly counts of rows by region bucket:

- `selangor`: state field `Selangor`;
- `kl`: state field `W.P. Kuala Lumpur`;
- `rakan_niaga`: state field `Rakan Niaga`, the JPJ partner sales channel. It is kept separate and labelled as a channel, not a place, because it carries about 87 per cent of 2026 transactions and would silently distort any geographic reading if merged;
- `other`: all remaining states summed.

A test asserts the monthly bucket counts sum to the raw row count exactly. No W.P. Putrajaya or W.P. Labuan rows appear in the 2026 file.

## 4. Population

From `population_district.parquet`, rows with `sex = both`, `age = overall`, `ethnicity = overall` are kept and district values are summed to state totals for Selangor and W.P. Kuala Lumpur, by year 2020 to 2026, in thousands rounded to one decimal place. 2020 is the census; later years are DOSM mid-year estimates. Residential population only; there is no daytime or workplace population.

## 5. Employment

From `lfs_qtr_state.parquet`, the `lf_employed` column for Selangor and W.P. Kuala Lumpur, 2017 Q1 to 2026 Q2 (38 quarters), in thousands, one decimal place. Quarter labels are derived from the date column (month 1 is Q1, month 4 is Q2, and so on). Employment is counted at the worker's state of residence, not the job location, so this series cannot locate jobs inside the region.

## 6. GTFS stops

`data/stops.json` is a direct export of `stop_name`, `stop_lat` and `stop_lon` from `data_raw/gtfs_rapid_rail_kl/stops.txt`: 187 entries, names exactly as published (upper case), WGS84 coordinates. No other GTFS table feeds the export. Interchange stations appear once per line in GTFS (25 duplicated names across different stop ids); the file is exported as is, since each entry is a distinct physical platform group with its own coordinates. Note the GTFS spelling occasionally differs from the OD file spelling (for example `BANDAR TUN HUSSEIN ONN` against the OD file's `Bandar Tun Hussien Onn`); no join between the two is performed in this phase, so no reconciliation is applied.

## SQLite layer

`data/mobility.db` is built from the same processed frames (never separately from raw, so the JSON and the database cannot disagree). Schema in `sql/schema.sql`; all analysis and quality-control queries in `sql/queries.sql` with `-- name:` markers. The build script runs every query and fails the build if an analytical query returns no rows or a `qc_` query returns any:

- `qc_no_negative_values`: no negative trips, transactions or counts in any table.
- `qc_duplicate_keys`: one row per natural key in every table.
- `qc_month_continuity`: within each service group's own observed span, every calendar month is present; registrations likewise. Continuity is per group because the bus and KTMB series legitimately start later than rail.

Days where a group did not report produce no row in `ridership_daily` (absent, not zero), consistent with the JSON's null handling.

## Rounding

Trip counts and daily averages are integers. Population and employment are in thousands with one decimal place, as published. The JSON is strict (no NaN or Infinity); missing observations are `null`.

## Limitations carried into every downstream use

1. Ridership and OD counts are trips, not people.
2. The OD matrix covers rail users only, station to station; most Klang Valley commuting is by car and is invisible here.
3. Alightings at 28 Putrajaya Line stations are missing from the published 2026 OD file (boardings are present).
4. Registrations are sales transactions; the Rakan Niaga channel detaches most of them from any state.
5. Employment is residence-based and state-level; population is residence-based; neither locates jobs.
6. 2020 and 2021 ridership is distorted by movement control orders.
7. The cited congestion figures (TomTom) and mode shares (World Bank, SPAD) are external headline numbers quoted with attribution, not datasets, and the simulator defaults built on them are stated assumptions, not observations.
