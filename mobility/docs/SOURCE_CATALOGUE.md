# KL Mobility Lab: Source Catalogue

Phase 1 deliverable: discovery and assessment of real, open data sources for the research question:

> **Would congestion improve if more people lived and worked in the same region?**

All files in `data_raw/` were downloaded on 10 November 2026 with `scripts/fetch_sources.py`. Row counts and date ranges below are what was actually observed in the downloaded files, not what the catalogue pages claim. Where a source could not be downloaded or is proprietary, that is recorded honestly.

Total size of `data_raw/`: approximately 7.5 MB plus the extracted GTFS folder.

---

## 1. Daily public transport ridership by mode (ridership_headline)

- **Publisher:** data.gov.my (Government of Malaysia open data portal). Data sources: Prasarana Malaysia and the Ministry of Transport.
- **Dataset URL:** https://data.gov.my/data-catalogue/ridership_headline
- **Publication / observation dates:** Data observed in file runs 1 January 2019 to 31 August 2026. Page states last updated 12 September 2026, next update 12 October 2026, so publication lags by roughly six weeks.
- **Geographic coverage:** Malaysia, by service. Klang Valley services are identifiable by column (Rapid Bus KL, all LRT, MRT and Monorail lines, KTM Komuter).
- **Frequency / grain:** One row per calendar day (daily grain, despite the dataset often being described as monthly; it is published monthly after audit). Counts are trips per service, not unique passengers.
- **Columns:** `date` (YYYY-MM-DD); then integer trip counts per service: `bus_rkl`, `bus_rkn`, `bus_rpn` (Rapid Bus KL, Kuantan, Penang), `rail_lrt_ampang`, `rail_lrt_kj`, `rail_lrt_shah_alam`, `rail_monorail`, `rail_mrt_kajang`, `rail_mrt_pjy`, `rail_ets`, `rail_intercity`, `rail_komuter`, `rail_komuter_utara`, `rail_tebrau`. Unit: number of trips (tap-in/tap-out or ticketing transactions).
- **Licence:** Page states: "This data is made open under the Creative Commons Attribution 4.0 International License (CC BY 4.0)." Attribution to data.gov.my / the data providers is required on reuse.
- **Download method:** `https://storage.data.gov.my/transportation/ridership_headline.parquet` (CSV also available at the same path with `.csv`). An API also exists: `https://api.data.gov.my/data-catalogue?id=ridership_headline&limit=N`.
- **File saved:** `data_raw/ridership_headline.parquet`, 0.11 MB, 2,800 rows x 15 columns, dates 2019-01-01 to 2026-08-31.
- **Limitations:** Trips, not people; one commuter making two train trips a day counts twice. No station or corridor detail. Covers Prasarana and KTMB services only, so no private buses, e-hailing or cars. The 2020 to 2021 period is distorted by movement control orders.
- **Suitability verdict:** Strong supporting dataset. It gives the public transport side of the congestion story: a long daily series showing how demand for KL rail and bus has grown, recovered after the pandemic, and responded to new lines (Putrajaya Line, Shah Alam Line appear as new columns). It cannot answer the live-work question alone, but it is the best open measure of how many motorised trips the Klang Valley shifts onto rail, which is the main alternative to road congestion.

## 2. Daily origin-destination ridership, Rapid Rail Klang Valley (ridership_od_rapidrail_daily)

- **Publisher:** data.gov.my. Data sources: Prasarana Malaysia and the Ministry of Transport.
- **Dataset URL:** https://data.gov.my/data-catalogue/ridership_od_rapidrail_daily
- **Publication / observation dates:** Updated roughly daily (page showed last update 9 November 2026). Yearly files exist since 2023. Observed data in the 2026 file runs 1 January 2026 to 8 November 2026.
- **Geographic coverage:** Entire Rapid Rail network in the Klang Valley (LRT, MRT, Monorail station pairs).
- **Frequency / grain:** One row per date x origin station x destination station. Derived from anonymous tap-in/tap-out gate transactions.
- **Columns:** `origin` (string, station where the journey began), `destination` (string, station where it ended), `date` (YYYY-MM-DD), `ridership` (integer, trips on that pair that day; the page warns this may exceed the number of distinct passengers).
- **Licence:** CC BY 4.0, stated on the page as for source 1.
- **Download method:** Yearly files at `https://storage.data.gov.my/transportation/rail/rapidrail_<year>_daily.parquet` (also `.csv`). There is **no API** for this dataset; the page states it is unsuitable for API access, so date filtering must be done after download. Size was checked before downloading: the 2026 parquet is about 5 MB, well under the 80 MB guard, so the full 2026 file was taken rather than a slice. Earlier years (2023, 2024, 2025) can be fetched by substituting the year in the URL.
- **File saved:** `data_raw/rapidrail_2026_daily.parquet`, 5.07 MB, 5,414,760 rows x 4 columns, dates 2026-01-01 to 2026-11-08. Observed 167 distinct origin values and 135 distinct destination values; total ridership in file 566,125,329 trips.
- **Limitations:** Rail only, so it describes where rail users travel, not where all commuters travel. Station-to-station, not door-to-door: access and egress legs are invisible. The mismatch between 167 origins and 135 destinations observed in the data suggests inconsistent station naming that needs cleaning against the GTFS stop list before analysis. Trips, not persons.
- **Suitability verdict:** The most valuable open dataset found for this project. It is a genuine origin-destination matrix at daily grain, which allows direct measurement of how far across the region rail commuters travel, which corridors are longest and heaviest, and whether weekday flows are dominated by suburb-to-centre movement. It is a proxy for the live-work separation of rail users specifically, and the central empirical object for the research question, with the caveat that car commuters, the majority, are not in it.

## 3. GTFS static feeds (Prasarana, KTMB)

- **Publisher:** data.gov.my real-time API, feeds supplied by Prasarana and KTMB.
- **Dataset URL:** https://developer.data.gov.my/realtime-api/gtfs-static
- **Publication / observation dates:** Feeds are refreshed as required (Prasarana) or daily at 00:01 (KTMB). Downloaded 10 November 2026.
- **Geographic coverage:** Downloaded feed covers the Rapid Rail KL network (all Klang Valley LRT, MRT, Monorail lines).
- **Frequency / grain:** Standard GTFS static tables; stops are point locations with coordinates, routes are lines, stop_times and frequencies define scheduled service.
- **Endpoint list (recorded, not all downloaded):** all under `https://api.data.gov.my/gtfs-static/`:
  - `prasarana?category=rapid-rail-kl` (downloaded), `rapid-bus-kl`, `rapid-bus-mrtfeeder`, `rapid-bus-penang`
  - `ktmb`
  - BAS.MY town bus feeds: `mybas-kangar`, `mybas-alor-setar`, `mybas-kota-bharu`, `mybas-kuala-terengganu`, `mybas-ipoh`, `mybas-seremban-a`, `mybas-seremban-b`, `mybas-melaka`, `mybas-johor`, `mybas-kuching`
  - Documented caveat: about 2% of `rapid-bus-kl` trips are removed from `stop_times.txt` for operational reasons.
- **Columns:** Standard GTFS: `stops.txt` (stop_id, stop_name, stop_lat, stop_lon), `routes.txt` (route ids and names), plus agency, calendar, frequencies, shapes, stop_times, trips. Coordinates in WGS84 decimal degrees.
- **Licence:** Page states all GTFS static feeds are licensed under CC BY 4.0.
- **Download method:** `https://api.data.gov.my/gtfs-static/prasarana?category=rapid-rail-kl` (returns a zip).
- **File saved:** `data_raw/gtfs_rapid_rail_kl.zip`, 0.08 MB, extracted to `data_raw/gtfs_rapid_rail_kl/` (data files only, nothing executed). Observed: 187 stops, 8 routes (Ampang Line, Sri Petaling Line, Kelana Jaya Line, Kajang Line, Putrajaya Line, KL Monorail Line, Sunway Line, Shah Alam Line). The zip also contains spurious `__MACOSX/` metadata entries, which should be ignored.
- **Limitations:** Schedule and geometry only, no ridership, no travel times as experienced. The KTMB and bus feeds were not downloaded in this phase; KTM Komuter stations would be needed to map the full rail footprint of the region.
- **Suitability verdict:** Essential companion to source 2. The stop coordinates let the station-pair OD matrix be mapped, distances between pairs computed, and stations assigned to districts or municipalities, which is what turns raw OD counts into a statement about how far people travel across the region. On its own it says nothing about congestion, but sources 2 and 3 together are the backbone of the analysis.

## 4. Car registration transactions (registration_transactions_car)

- **Publisher:** data.gov.my. Data sources: Road Transport Department (JPJ) and the Ministry of Transport.
- **Dataset URL:** https://data.gov.my/data-catalogue/registration_transactions_car
- **Publication / observation dates:** Series runs from 2000; updated monthly (last update 10 October 2026, data as of 30 September 2026). Observed 2026 file covers 1 January 2026 to 30 September 2026.
- **Geographic coverage:** Malaysia, by state field (see limitations).
- **Frequency / grain:** One row per individual registration transaction (not an aggregate). This is new registrations, by registration date.
- **Columns:** `date_reg` (date of registration, which may differ from purchase date), `type` (motokar, motokar_pelbagai_utiliti, jip, pick_up, window_van), `maker`, `model`, `colour`, `fuel` (petrol, diesel, hybrid_petrol, electric and others), `state` (one of 16 states or `Rakan Niaga` for registrations through a JPJ partner portal; the page notes it does not relate to the number plate).
- **Licence:** CC BY 4.0, stated on the page.
- **Download method:** Yearly files at `https://storage.data.gov.my/transportation/cars_<year>.parquet` (also `.csv`). The page states this catalogue is **not** available through the API, so the plan to pull monthly state totals via the API was not possible; instead the full 2026 transaction file was downloaded (it is small) and monthly state aggregates can be computed locally.
- **File saved:** `data_raw/cars_2026.parquet`, 0.48 MB, 640,875 rows x 7 columns, `date_reg` 2026-01-01 to 2026-09-30. Observed state values: the 13 states plus W.P. Kuala Lumpur and `Rakan Niaga`; no W.P. Putrajaya or W.P. Labuan rows appear in the 2026 file.
- **Limitations:** **Vehicle registrations are not traffic counts.** A registration says a car was added to the fleet, not where or how much it is driven. The state field reflects where the transaction was registered, and the `Rakan Niaga` channel detaches a large share of transactions from any state, so state totals understate true geographic demand. No deregistrations, so net fleet size cannot be derived. Cars only (motorcycles and goods vehicles are separate catalogues).
- **Suitability verdict:** Useful context, nothing more. It can show that private car supply in Selangor and KL keeps growing while rail ridership also grows, which frames the congestion problem, and the fuel column tracks electrification. It cannot measure road use, congestion or commuting, and any analysis must say so plainly. Treat as a motorisation indicator alongside, never instead of, traffic or travel data.

## 5. DOSM Migration Survey Report, Malaysia, 2024

- **Publisher:** Department of Statistics Malaysia (DOSM).
- **Dataset URL:** https://www.dosm.gov.my/portal-main/release-content/migration-survey-report-malaysia-2024
- **Publication / observation dates:** Released 18 December 2025; reference period 2023 to 2024 (survey conducted 2024).
- **Geographic coverage:** Malaysia, state level. W.P. Labuan suppressed for high relative standard error; several states flagged as high RSE.
- **Frequency / grain:** Biennial sample survey. Figures are survey estimates of persons aged one year and over who changed locality of usual residence within one year, state by state. **Migration is not commuting:** these are changes of home address, not daily journeys to work.
- **Headline statistics recorded (all from the official press statement PDF, pages 1 to 3, saved in `data_raw/`):**
  - Total migrants 2024: **301.1 thousand** persons, migration rate **0.9%** (2022: 158.8 thousand, 0.5%).
  - Internal migration share: **63.5%** (2022: 62.3%). Inter-state share 30.2%, international 6.3%.
  - **Selangor** was the top destination with **97.6 thousand in-migrants** and the main net recipient at **+8.4 thousand** (2022: -8.8 thousand). Largest inflows to Selangor came from W.P. Kuala Lumpur (13.8 thousand), Negeri Sembilan (2.6 thousand) and Pulau Pinang (2.0 thousand). Selangor also had the highest out-migration (89.2 thousand), mostly to W.P. Kuala Lumpur (6.6 thousand) and Johor (3.0 thousand).
  - **W.P. Kuala Lumpur** was a net sending state at **-7.6 thousand** (2022: -1.7 thousand).
  - Reasons for internal migration 2024: following family **46.2%**, environment **26.1%**, **career 17.2%** (the work-related share), marriage and divorce 3.7%, education 3.0%, others 3.8%.
  - Intra-state flows were 84.6% urban to urban; Selangor's intra-state moves were 96.2% urban to urban.
  - Age 25 to 34 dominated internal migration at 47.7%.
- **Licence:** The release page states only "©Copyright Department Of Statistics Malaysia (DOSM) All Rights Reserved"; no open licence is stated on this page, unlike DOSM datasets republished on data.gov.my. Figures should be cited with attribution to DOSM; the tables should not be redistributed as if openly licensed.
- **Download method:** Table files via `https://www.dosm.gov.my/portal-main/release-document-log?release_document_id=<id>` (17706: Tables 1 to 9 internal migration; 17707: Tables 10 to 16 demographic; 17708: Tables 17 to 21 socioeconomic; 17711: press statement; 17712: technical notes).
- **Files saved:** `data_raw/dosm_migration_2024_tables_1_9_internal_migration.xlsx` (0.81 MB, 13 sheets, Jadual 1 to 9), `data_raw/dosm_migration_2024_tables_17_21_socioeconomic.xlsx` (0.27 MB, 5 sheets, Jadual 17 to 21), `data_raw/dosm_migration_2024_press_statement.pdf` (0.22 MB). All verified to open.
- **Limitations:** State grain only, small sample (several states flagged high RSE), biennial, and again: residential moves, not commuting. The KL-to-Selangor flow is consistent with people moving home outward while possibly keeping jobs in KL, but the survey does not record workplace, so that reading cannot be confirmed from this source.
- **Suitability verdict:** Directly relevant context for the "lived and worked in the same region" framing. It quantifies the churn of residence between KL and Selangor (people leaving KL for Selangor far outnumber the reverse) and shows work (career, 17.2%) is a minority stated reason for moving. It supports the claim that residential location and job location are drifting apart, but because workplace is not captured, it can motivate the hypothesis, not test it.

## 6. TomTom Traffic Index, Kuala Lumpur (proprietary, metadata only)

- **Publisher:** TomTom International BV.
- **Dataset URL:** https://www.tomtom.com/traffic-index/city/kuala-lumpur/ and https://www.tomtom.com/traffic-index/ranking/
- **Publication / observation dates:** 2025 edition (full-year 2025 data). Figures below retrieved from the live pages on **10 November 2026**. The pages are JavaScript-rendered, so a plain HTTP fetch returns no figures; values were read from the rendered pages.
- **Geographic coverage:** Kuala Lumpur "city" and "metro" definitions as drawn by TomTom; figures below are the default city view.
- **Published headline metrics recorded (2025, Kuala Lumpur, city view):**
  - Average travel time for a 10 km drive: **17 min 55 s** (22 s more than 2024).
  - Average congestion level: **43.4%** (+0.9 percentage points on 2024).
  - Time lost in rush hour per year: **84 hours** (3 h 50 min more than 2024).
  - Rank: **172nd of 492 cities** worldwide in the 2025 ranking (city view).
  - Morning rush hour: 20 min 50 s per 10 km, 68.4% congestion, 28.8 km/h. Evening rush hour: 26 min 12 s per 10 km, **102.1%** congestion, 22.9 km/h.
  - Average speed 33.5 km/h; average distance driven in 15 min 8.4 km; highway trip ratio 24.1%; worst day 4 December 2025.
  - Other Malaysian cities in the 2025 ranking for comparison: George Town 44th (56.7%), Kota Bharu 112th, Seberang Perai 188th, Johor Bahru 239th, Ipoh 331st, Kajang 404th (29.4%, with a 71.6% highway trip ratio).
- **Licence and reuse:** Proprietary. The Traffic Index pages are free to read and TomTom permits citing the published headline figures **with attribution to TomTom**; map imagery is marked ©TomTom, ©OpenStreetMap. The underlying trip data is a commercial product (TomTom Traffic Stats / MOVE) and is **not openly licensed**; no dataset was or should be scraped.
- **Download method:** None (deliberately). No file saved beyond this record.
- **Limitations:** Methodology (city boundary, trip weighting) is TomTom's and changes between editions, so year-on-year comparisons should quote TomTom's own stated change figures. Car-centric: it measures driving conditions, not total travel.
- **Suitability verdict:** The only consistent, public congestion outcome measure found for KL, so it supplies the dependent variable of the research question, but only as a handful of annual headline numbers, not a dataset. The evening peak congestion of 102.1% (travel takes roughly double free-flow time) is the cleanest single statement of the problem. Any model linking land use or transit to congestion can use these figures as anchors or sanity checks, not as estimation data.

## 7. Population at administrative district level (population_district)

- **Publisher:** data.gov.my / DOSM (OpenDOSM).
- **Dataset URL:** https://data.gov.my/data-catalogue/population_district
- **Publication / observation dates:** Annual, 2020 (census) to 2026 (mid-year estimates); last updated 7 October 2026.
- **Geographic coverage:** All Malaysian administrative districts (page says 160 districts across 16 states; the file contains 166 distinct district values, so name variants or new districts should be checked before joining).
- **Frequency / grain:** Annual, district x sex x five-year age group x ethnicity. Unit: population in thousands (float).
- **Columns:** `state`, `district`, `date` (year as YYYY-01-01), `sex` (both, male, female), `age` (overall or 5-year bands to 85+), `ethnicity` (overall plus six groups), `population` ('000).
- **Licence:** CC BY 4.0, stated on the page.
- **Download method:** `https://storage.dosm.gov.my/population/population_district.parquet` (note: hosted on storage.dosm.gov.my, not storage.data.gov.my; the first guess at the data.gov.my path returned 404). API: `https://api.data.gov.my/data-catalogue?id=population_district`.
- **File saved:** `data_raw/population_district.parquet`, 0.25 MB, 451,668 rows x 7 columns, years 2020 to 2026. Observed 2026 totals (both sexes, overall): Selangor 7,454.3 thousand, W.P. Kuala Lumpur 2,082.3 thousand, W.P. Putrajaya 121.4 thousand.
- **Limitations:** Residential population only; no daytime population, no workplace population, which is exactly the half of the live-work equation that is missing everywhere. Intercensal years are estimates.
- **Suitability verdict:** Necessary denominator data. District populations let ridership and registrations be normalised per resident and let growth of outer Klang Valley districts (Petaling, Ulu Langat, Klang, Gombak) be compared with the core. Combined with station locations it supports a coarse "where people live" layer. It cannot say where those people work.

## 8. Quarterly labour force statistics by state (lfs_qtr_state)

- **Publisher:** data.gov.my / DOSM.
- **Dataset URL:** https://data.gov.my/data-catalogue/lfs_qtr_state
- **Publication / observation dates:** Quarterly; observed file covers 2017 Q1 to 2026 Q2; last updated 11 August 2026.
- **Geographic coverage:** 16 states.
- **Frequency / grain:** Quarterly, state level. Units: thousands of persons; rates in per cent.
- **Columns:** `date`, `state`, `lf` (labour force, '000), `lf_employed` ('000), `lf_unemployed` ('000), `lf_outside` ('000), `p_rate` (participation rate, %), `u_rate` (unemployment rate, %).
- **Licence:** CC BY 4.0, stated on the page.
- **Download method:** `https://storage.dosm.gov.my/labour/lfs_qtr_state.parquet`.
- **File saved:** `data_raw/lfs_qtr_state.parquet`, 0.01 MB, 608 rows x 8 columns, 2017-01-01 to 2026-04-01 (Q2 2026).
- **Limitations:** Employment is counted at the worker's state of residence, not the location of the job, and the grain is state, far too coarse to describe employment geography inside the Klang Valley. No open DOSM dataset at district or finer grain for jobs was found (the Economic Census has establishment counts by state; MyCensus district tables cover population, not workplaces).
- **Suitability verdict:** Weak but included for completeness. It documents that Selangor plus KL hold the country's largest labour force and lets per-worker normalisations be made at state level. It does not locate jobs within the region, so it cannot support the work half of the live-work question beyond state totals.

## 9. World Bank, Malaysia Economic Monitor, June 2015: Transforming Urban Transport (metadata only)

- **Publisher:** World Bank Group.
- **Dataset URL:** https://openknowledge.worldbank.org/entities/publication/b84a12db-6515-53c7-b5d4-0169f9efdd28 (DOI 10.1596/22038); PDF at https://www.worldbank.org/content/dam/Worldbank/document/EAP/malaysia/Malaysia_Economic_Monitor_June_2015.pdf
- **Publication / observation dates:** June 2015; underlying surveys circa 2010 to 2014.
- **Geographic coverage:** Malaysia, with a focus chapter on Greater Kuala Lumpur urban transport.
- **Licence:** CC BY 3.0 IGO (per the Open Knowledge Repository record), so the report may be quoted and redistributed with attribution to the World Bank.
- **Key figure verified from World Bank materials:** the report states that about **17% of Kuala Lumpur commuters used public transport, against 62% in Singapore and 89% in Hong Kong** (figure as quoted in the World Bank's own publication page and press release of 16 June 2015). The press release also argues congestion imposes high economic costs and recommends metropolitan transport authorities and congestion pricing. A frequently cited congestion-cost share of GDP circulates in secondary sources, but the exact figure was not verified against the report text in this phase, so it is deliberately not quoted here.
- **Download method / file saved:** Not downloaded in this phase (report PDF, not a dataset). The PDF link above is the reproducible source.
- **Limitations:** A decade old; pre-MRT. Its numbers describe the 2010s baseline, not today.
- **Suitability verdict:** Best open analytical treatment of KL congestion and its causes, and useful for framing: it documents the historical low transit share and the policy diagnosis (fragmented governance, car-oriented land use). Use as citable context and for before-and-after framing against the post-MRT ridership data in source 1, not as current data.

## 10. Searched for but absent, paywalled or not open

These were investigated for item 7 of the discovery brief; recording their status honestly:

- **DOSM commuting or journey-to-work statistics:** No DOSM release titled "Statistics of Commuting" and no census journey-to-work table was found. MyCensus 2020 publishes district population tables but no residence-to-workplace cross-tabulation. Malaysia's census does not publish a commuting OD product the way the UK or Australian censuses do. **Status: absent as open data.**
- **Klang Valley household travel surveys (SPAD / APAD):** The Greater KL / Klang Valley Land Public Transport Master Plan (SPAD, 2011 to 2013) and its annual reports quote morning-peak public transport mode shares (around 17% in 2010, 20.8% in 2013, against a 40% urban target for 2030 in the National Land Public Transport Master Plan), and these documents are readable online (for example via SPAD annual report PDFs mirrored at govdocs.sinarproject.org). The underlying household travel survey microdata and OD matrices were never published. **Status: headline figures citable from reports; microdata not open.**
- **Road traffic counts:** The Highway Planning Division (Ministry of Works) publishes the Road Traffic Volume Malaysia (RTVM) reports as PDFs, not machine-readable open data, and they were not fetched in this phase; no traffic-count catalogue exists on data.gov.my. **Status: PDF reports only, not open data.**
- **Employment by district / workplace geography:** No open DOSM dataset locates jobs below state level (see source 8). **Status: absent as open data.**
- **TomTom bulk data, Google/Waze travel times:** Commercial; not openly licensed. **Status: paywalled.**

---

## DATA GAPS

What the research question needs, and what no open Malaysian dataset currently provides:

1. **A door-to-door commuting origin-destination matrix.** The single most important missing object. There is no census journey-to-work table, no published household travel survey microdata, and no open OD data for car trips. The Rapid Rail OD matrix (source 2) covers only rail riders, station to station, in a region where most commuting is by car.
2. **Workplace locations.** Population is available at district level (source 7), but employment is only available at state level and is counted at the worker's residence (source 8). Without a "jobs by district" layer, "lived and worked in the same region" cannot be measured on both sides.
3. **Road traffic counts and road travel times as data.** Congestion outcomes exist only as TomTom's annual headline numbers (source 6) and as RTVM PDF reports. There is no open time series of link-level traffic volumes or speeds for the Klang Valley.
4. **Mode shares over time.** The morning-peak mode share figures are scattered across SPAD-era reports with differing definitions; there is no maintained open series.
5. **Bus travel times and bus OD.** Prasarana publishes bus GTFS schedules and (separately) some ridership, but no bus OD matrix and no realised journey times.

**Honest consequence:** with open data alone, the hypothesis "congestion would improve if more people lived and worked in the same region" can be **explored but not conclusively tested**. The rail OD matrix, station locations, district populations, migration flows and ridership series can establish that residences have shifted outward while jobs and rail flows still point at the centre, and TomTom's figures establish that congestion is worsening slightly despite record rail ridership. But without a full commuting OD matrix, workplace geography and road traffic measurements, the counterfactual (what congestion would be if live-work separation shrank) cannot be estimated with confidence. Any write-up should state this limit plainly and frame conclusions as descriptive evidence consistent with the hypothesis, not proof of it.

---

## Attribution notes for reuse

- data.gov.my datasets (sources 1, 2, 3, 4, 7, 8): CC BY 4.0; credit "data.gov.my / Department of Statistics Malaysia / Prasarana Malaysia / JPJ / Ministry of Transport" as appropriate per dataset.
- DOSM Migration Survey (source 5): all rights reserved; quote figures with citation to DOSM, do not redistribute tables as open data.
- TomTom (source 6): cite "TomTom Traffic Index 2025, retrieved 10 November 2026"; no bulk reuse.
- World Bank (source 9): CC BY 3.0 IGO; cite "World Bank, Malaysia Economic Monitor, June 2015: Transforming Urban Transport, DOI 10.1596/22038".
