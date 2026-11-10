# Publication checklist

To be completed manually before the repository is pushed or Pages is enabled.
Status below reflects the state at hand-off on 10 Nov 2026.

## Content and honesty

- [x] All data is synthetic and labelled as such (banner on the dashboard, notes in
      footers, READMEs and methodology docs)
- [x] No confidential or employer data anywhere in the repository
- [x] No fabricated internships, titles, skills or project ownership; internship
      titles say "Intern"; skills limited to the verified list
- [x] EcoFlow is presented as a learning project built on clearly labelled
      synthetic data
- [ ] Firdaus has read the methodology and can explain every KPI (owner action)
- [ ] Owner has approved the published email address and the "available on request"
      resume approach, or supplied a final PDF (see _private/VERIFICATION_TODO.md,
      which stays out of the public repository)

## Privacy and security

- [x] No phone number, postcode or home address on the site; no full legal name
      (site uses "Firdaus Zakaria") and no CGPA
- [x] The `_private/` folder (owner checklist) is excluded from publication
- [x] No credentials, tokens or API keys in any source file
- [x] No private files in the publication folder (checked at QA)
- [x] External dependencies limited to Google Fonts and the pinned Chart.js CDN
      build; no analytics, trackers or form endpoints

## Assets and licensing

- [x] All graphics are original SVG created for this project (hero illustration,
      favicon); no stock photography, no third-party images
- [x] Chart.js is MIT licensed; fonts served by Google Fonts under open licences
- [x] Repository carries an MIT LICENSE in the owner's name

## Technical

- [x] Static site, no backend, works on GitHub Pages project hosting
- [x] All asset paths relative; `.nojekyll` present
- [x] Automated tests pass (see docs/TESTING_REPORT.md for the executed results)
- [x] Dashboard loads its data over HTTP with a clear error message when opened
      from disk
- [ ] Final visual check on a phone after Pages goes live (owner action)

## Publication steps (manual, in order)

1. Resolve the two open owner actions above
2. Follow docs/DEPLOYMENT_GUIDE.md sections 1 to 3
3. Verify the live site, including the dashboard data load
4. Add the link to LinkedIn (guide sections 5 and 6)
