# Engineering validation report

## Update: Improvement Advisors on all four projects (10 Nov 2026)

Each project now carries a deterministic, rule-based improvement advisor. An
independent review re-derived the evidence numbers from the raw data and model
runs (zero mismatches), probed every engine with misleading, incomplete and
contradictory datasets (no unsupported recommendation appeared; cleared and
conditional outcomes occur in practice), and re-ran all suites: **235 tests
passed, 0 failed** (EcoFlow 49, SNG 59, Manufacturing 89, Mobility 38).
Browser checks: all advisor sections render on desktop and mobile with no
horizontal overflow and no console errors; pre-existing dashboards unchanged.
Known robustness limits are documented per project in the methodology docs:
pathological inputs (impossible plants, missing columns, fractions above one)
fail loudly at build time rather than producing quiet wrong advice.

# Earlier report - Projects 02, 03 and 04

Date: 10 Nov 2026. Environment: Windows 11, Python 3.10 (pandas 2.3.3, numpy 2.2.6,
pyarrow, pytest 9.1.1), site served with `python -m http.server`, browser checks in
a Chromium-based browser. This report covers the three projects added after EcoFlow;
EcoFlow's own report is docs/TESTING_REPORT.md.

## Automated tests (executed, final counts)

| Suite | Command | Result |
|-------|---------|--------|
| EcoFlow (incl. Improvement Advisor) | `python -m pytest ecoflow/tests -q` | 49 passed |
| SNG | `python -m pytest sng/tests -q` | 35 passed |
| Manufacturing | `python -m pytest manufacturing/tests -q` | 64 passed |
| Mobility | `python -I -m pytest mobility/tests -q` | 15 passed |
| **Total** | | **163 passed, 0 failed** |

## EcoFlow Engineering Improvement Advisor (added after the first release of this report)

- Six deterministic rules with published thresholds; on the real baseline data:
  upsets action_recommended at high severity (6 episodes, 54 h, 1,794 kg excess
  COD, influent load shock ruled out by an observed comparison), dose response
  conditional (no detectable response, correlation -0.019, so a stepped-dose trial
  is required before any reduction; savings quoted only as conditional, 1,696 to
  3,101 kg/yr sensitivity), and three honestly cleared checks (sensors 0.21% worst
  column, energy base load 0.7% of mean with R2 0.914, zero pH excursion hours).
- Integrity verified by tests, not claimed: a positive dose-response fixture does
  NOT produce a reduction recommendation; removing the upset rows from the real
  data flips the upset finding to no_action_justified; two runs give byte-identical
  output; every consumption-reducing finding carries a treatment-quality gate that
  is never a free pass.
- Dashboard section verified in the browser: all five cards render with correct
  statuses, evidence expanders work, data gaps listed, the pre-existing dashboard
  above is unchanged, zero console errors.

## Project 02 - SNG Plant Design

- Hand-calculated example verified: 100 kmol/h CO + 300 kmol/h H2 at full conversion
  gives 100 CH4 + 100 H2O with mass in = mass out exactly (3,405.8 kg/h both sides)
  and cold gas efficiency matching the paper calculation.
- Shift extent reproduces the target H2/CO = 3.0 exactly; the balanced-ratio extent
  matches the hand-derived value e = (3 CO + 4(1 - f) CO2 - H2) / (4 f) = 43/3.6
  per 100 kmol feed.
- Element balances (C, H, O, N) close within 0.1% in all four scenarios; total mass
  closure reports 100.00% (a 0.03 kg/h residual from 2 dp molar masses is documented).
- Honest engineering finding, kept visible: with the naive H2/CO = 3 shift target
  the gas runs out of hydrogen for CO2 methanation (achieved CO2 conversion 8.5%,
  not the intended 90%). The balanced-ratio scenario fixes the stoichiometry
  (98%/90% achieved), CO2 in the dry product falls from about 8 to 1 mol%, and the
  documentation explains why overall purity still only reaches 79.4% (unreacted H2
  and inert N2) and what a real plant would add.
- Base case hits the 22,000 MT/yr basis exactly (2,750.0 kg/h at 8,000 h/yr).

## Project 03 - Manufacturing Performance Analytics

- All 10 KPI formulas verified against hand examples; zero denominators return NaN;
  a counterexample test proves naive averaging of percentages would be wrong and the
  time-weighted aggregation is used instead.
- The dashboard recomputes KPIs in JavaScript from the exported rows; a parity check
  against the Python values runs on page load and reported no mismatch (OEE 81.8%,
  availability 93.2%, performance 90.4%, quality 97.1%).
- SQLite layer: 5 analytical queries return data; all 6 data-quality checks
  (impossible values, broken references, duplicates) return zero rows; the monthly
  OEE SQL result is cross-checked against the pandas computation.
- The three planted story arcs are visible in the dashboard and confirmed by
  filters: Line B breakdown week (March 2026), post-July maintenance improvement,
  and the day/night performance gap.

## Project 04 - KL Mobility Lab

- All observed figures reconcile to their raw sources exactly: monthly ridership
  equals daily sums, registration buckets sum to the raw row count, and the OD
  totals reconcile after a significant data discovery: the published OD file
  contains "All Stations" marginal rows that triple-count the grand total. The
  pipeline detects and excludes them, documented in mobility/docs/METHODOLOGY.md.
- A real coverage gap is reported rather than patched: 28 Putrajaya Line stations
  never appear as destinations in the published 2026 file, so alightings on that
  line are understated.
- Research integrity: observed data and modelled outputs are separated throughout;
  the simulator carries a permanent "modelled, not observed" label, shows a ±30%
  band, and deliberately shows no "minutes saved in traffic" figure because no
  validated traffic model exists in this project. Licences and attribution are
  listed per source (TomTom figures quoted with attribution; DOSM migration report
  is cite-only and its tables are not redistributed).
- Simulator arithmetic verified by hand for preset E (1.00 m trips/week avoided,
  318.8 k t CO2/yr at the stated assumptions).

## Frontend checks (executed in browser)

- All four dashboards load over HTTP with zero console errors from the site's own
  pages; scenario selectors, filters, presets, the SNG process-diagram inspector
  and the simulator sliders all respond correctly.
- Mobile (375 x 812): no horizontal overflow on any page; menus and controls usable.
- EcoFlow regression after all changes: identical KPIs and chart behaviour.
- Content sweep: no em dashes and no development-tool references anywhere in the
  published content (the one grep hit is the test that enforces the rule).

## Known limitations (honest list)

- Browser checks ran in Chromium only; Firefox/Safari untested.
- Accessibility reviewed by construction (landmarks, labels, contrast, keyboard
  paths, reduced motion); no screen-reader pass or automated audit executed.
- Performance: the largest payload is the manufacturing JSON (about 450 KB);
  charts render 12 to 92 points and interactions are immediate; no formal
  profiling or large-dataset stress run beyond the 5.4 M-row offline OD processing.
- GitHub Pages behaviour verified by construction, not on a live deployment, since
  publishing awaits approval.
