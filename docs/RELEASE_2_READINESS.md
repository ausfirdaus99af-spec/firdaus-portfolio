# Release 2 readiness - Projects 02, 03 and 04

State at 10 Nov 2026: built, tested and verified locally. NOT pushed or deployed;
publication awaits explicit approval.

## What this release adds

| Path | Project |
|------|---------|
| `ecoflow/` (additions) | 01 - Engineering Improvement Advisor: rule engine, tests, methodology doc, dashboard section |
| `sng/` | 02 - Synthetic Natural Gas Plant Design (model, tests, docs, dashboard) |
| `manufacturing/` | 03 - Manufacturing Performance Analytics (generator, KPIs, SQLite, SQL, tests, docs, dashboard) |
| `mobility/` | 04 - KL Mobility Lab (fetch script, pipeline, SQLite, tests, docs, dashboard, simulator) |
| `css/dash.css` | shared dashboard stylesheet |
| `index.html` | home page updated with the four-project listing |
| `docs/VALIDATION_REPORT.md`, this file | reports |
| `requirements.txt` | adds pyarrow |

## GitHub Pages compatibility

- Static only: every dashboard reads precomputed JSON; no server-side code.
- All asset paths relative; `.nojekyll` already in the live repo.
- New payload sizes: sng_data.json 36 KB class, mfg_data.json ~450 KB,
  mobility_data.json ~25 KB, stops.json ~13 KB, manufacturing.db 452 KB and
  mobility.db 352 KB ship as downloadable artefacts, total addition well under 2 MB.
- `mobility/data_raw/` (7.7 MB of source downloads) is gitignored; the catalogue
  documents every source and `mobility/scripts/fetch_sources.py` re-downloads them.

## Pre-publication checklist

- [x] 163 automated tests pass across the four projects (incl. the EcoFlow
      Engineering Improvement Advisor added to this release)
- [x] EcoFlow regression: unchanged behaviour
- [x] No em dashes, no development-tool references, UK English throughout
- [x] Synthetic and modelled content clearly labelled on every page; observed data
      carries sources and licences (TomTom attributed, DOSM migration cite-only)
- [x] No credentials, personal data beyond the public email, or private files in
      the publication set; `_private/` and `mobility/data_raw/` stay out
- [x] Mobile layouts checked, no horizontal overflow
- [ ] Owner approval to publish (required before any push)
- [ ] After publishing: spot-check all four dashboards on the live URL

## Outstanding issues (known, accepted or deferred)

1. The SNG product purity (79%) is below pipeline-gas quality by design; the pages
   and docs explain why and what a real plant adds. Not a defect, but he should be
   ready to discuss it.
2. Putrajaya Line alightings are missing from the published OD data (upstream gap,
   documented); the OD charts understate that line.
3. The LRT Shah Alam ridership column is absent for May to late June 2026 in the
   source data; monthly sums use observed days only.
4. The bus network has no open travel-time or OD data, so the Mobility Lab's rail
   picture cannot be extended to buses.
5. Firefox/Safari and screen-reader passes remain untested.
6. The live site still lacks a social-preview image (affects link cards on
   LinkedIn/WhatsApp shares).

## Publication steps (when approved)

The repo exists and is live, so this release is an incremental upload: add the new
folders and replace `index.html` via the same web-upload flow (or any push access
that exists at the time), with a plain commit message such as
"Add SNG, manufacturing and mobility projects". GitHub Pages redeploys
automatically; verify the four dashboards on the live URL afterwards.
