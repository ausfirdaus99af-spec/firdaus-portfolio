# Testing and QA report

Date: 10 Nov 2026. Environment: Windows 11, Python 3.10 (pandas 2.3.3, numpy 2.2.6,
pytest 9.1.1), site served with `python -m http.server`, tested in a Chromium-based
browser.

## Automated tests (executed)

Command: `python -m pytest ecoflow/tests -q` from the repository root.

**Result: 28 passed, 0 failed (2.6 s), run twice on separate occasions.**

Coverage:
- Formula examples with known inputs/outputs for every analytics function
  (e.g. removal_efficiency(500, 50) = 90.0)
- Zero denominators, negative, None and NaN inputs return NaN instead of raising
- Generator reproducibility: same seed produces identical dataframes
- Schema: column names, dtypes, both scenarios present, at least 90 days
- Range checks on non-anomalous rows: pH within 0 to 14, positive concentrations
  and flows, effluent COD below influent COD in normal operation, BOD never above COD
- Upset and anomaly rows exist and are tagged by type
- JSON contract: strict JSON (no NaN/Infinity), exact top-level keys, 120 daily
  entries per scenario

During development one test failure was found and fixed: the strict-JSON check
caught the literal string "NaN" inside an anomaly note; the note was reworded.

## Data engineering checks (executed)

- Hourly CSV: 5,760 rows (2,880 per scenario, 120 days x 24 h, 2026-07-04 to
  2026-10-31)
- Anomalies: 21 (baseline) / 23 (optimised) flagged rows across all four types;
  8 upset days; two 8-hour maintenance windows
- Dashboard KPIs match the Python pipeline output exactly (checked value-by-value
  in the browser: COD 88.0%, BOD 92.5%, TSS 93.0%, 550,145 m³, 0.80 kWh/m³,
  60.1 g/m³, 21 anomalies, 8 upset days for baseline, full period)
- Optimised scenario deltas land where the model intends: specific energy -11.9%,
  chemical dose -15.1%
- Mistaken-for-real risk: dataset is tagged `"synthetic": true` in the JSON,
  the CSV lives under a project labelled synthetic everywhere, and no real company
  names, sites or IDs appear

## Frontend and UI/UX (executed in browser)

- Home page and dashboard load with **zero console errors**
- Navigation: all header links, hero buttons, feature-card buttons and contact
  cards point at real targets; anchor jumps respect the sticky header
  (scroll-margin fix applied after testing found the overlap)
- Mobile (375x812): hamburger menu opens, closes on selection and on Escape;
  dashboard header wraps cleanly (fixed after testing found the overflow);
  preset buttons no longer wrap mid-label (fixed)
- Desktop and mid-width layouts checked by screenshot; no overflowing cards or
  clipped text found after fixes
- Interactions tested on the dashboard: scenario switch, parameter tabs
  (COD/BOD/TSS), 30/60-day presets, custom date range; KPIs and charts recompute
  correctly (e.g. 31-day optimised window: 0.70 kWh/m³, 51.1 g/m³)
- Reduced motion: CSS media query disables transitions; chart animation is turned
  off when `prefers-reduced-motion: reduce` is set (code path present; not
  exercised with an OS-level setting)
- Dashboard shows a clear error message when the dataset cannot be fetched
  (file:// or network failure)

## Accessibility (reviewed, partially executed)

- Semantic landmarks, skip link, single h1 per page, labelled form controls,
  aria-expanded on the menu toggle, keyboard focus styles throughout
- Contrast: body text #F3F5EF and secondary #B5C6BF on #091F1C both exceed
  WCAG AA (roughly 15:1 and 9:1); lime-on-dark accents far exceed AA
- Not executed: a full screen-reader pass and axe-style automated audit

## Security and privacy (executed)

- Regex sweep for credentials, tokens, API keys: none (matches were test-helper
  code and checklist prose only)
- Personal data: email address only (owner to confirm); no phone, postcode or
  address anywhere
- Dependencies: Chart.js 4.4.1 (pinned CDN build) and Google Fonts; no other
  third-party code, no analytics or trackers
- All graphics are original SVG; no third-party images to license

## Not tested / known limitations (honest list)

- Stress testing with much larger datasets was not performed; the published
  dashboard renders 120 points per series and is fast, but the charts have not
  been profiled with, say, hourly-resolution plotting
- No cross-browser pass beyond Chromium (Firefox/Safari untested)
- GitHub Pages behaviour verified by construction (relative paths, .nojekyll,
  static only) but not on a live Pages deployment, since publishing awaits approval
- Live phone hardware untested (only viewport emulation)
