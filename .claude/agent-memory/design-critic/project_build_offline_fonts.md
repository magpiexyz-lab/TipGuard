---
name: build-fails-offline-google-fonts
description: `npm run build` fails here on next/font fetching Fraunces + IBM Plex from Google Fonts — environmental, not a regression to chase.
metadata:
  type: project
---

`npm run build` fails in this environment with
`next/font: Failed to fetch <Fraunces|IBM Plex Sans|IBM Plex Mono> from Google
Fonts` traced to `src/app/layout.tsx`. The sandbox has no egress to
fonts.googleapis.com.

**Why:** the fonts are bound via `next/font/google` in `layout.tsx` (they must
stay on `<html>` — the `:root` rules in `globals.css` resolve empty otherwise).
The already-running dev server has them cached, so pages render correctly with
real Fraunces/IBM Plex even though a cold build cannot.

**How to apply:** the design-critic procedure's "run `npm run build` (must
pass)" step is unsatisfiable here. Do not treat this failure as caused by your
diff and do not "fix" it by switching to `next/font/local` — that is out of
scope for a visual review. Substitute two cheaper checks:
1. esbuild parse-check of your boundary files (exit 0),
2. visual verification against the running dev server at HTTP 200.
Record the build failure under `shared_issues` as environmental/pre-existing.

Also note: running `npm run build` while the dev server is live writes into the
same `.next/` directory it is serving from — avoid it for that reason too.

Related: [[verify-shared-dev-server]]
