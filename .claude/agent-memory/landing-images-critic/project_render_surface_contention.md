---
name: render-surface-contention
description: In parallel verify runs the documented copy-into-public + next start -p 3099 swap protocol is unusable; use Playwright route interception instead
metadata:
  type: project
---

During a parallel `/verify` round this project runs several design critics at once
against one shared dev server plus a lead-owned production server on **port 3099**.
The Step 5.5 Candidate Image Swap Protocol as written (copy candidate into
`public/images/`, `next start -p 3099`, screenshot, kill) breaks down there:

- `next start -p 3099` dies with `EADDRINUSE`, but the readiness poll still sees
  HTTP 200 from the *lead's* server, so the review silently binds to a stale build
  (missing CSS chunks -> unstyled page, and you may not notice at thumbnail size).
- Copying into `public/images/` mutates state the other critics are screenshotting.
- `rm -rf .next/cache/images` and any `npm run build` clobber `.next` for everyone.
- One agent's mid-edit syntax error in an unrelated route (e.g. `src/app/staff/*`)
  takes down the shared dev server and every build, with no cross-agent signal.

**Why:** the protocol predates the #1468 parallel-critic split and assumes the
critic owns the render surface.

**How to apply:** swap candidates with Playwright `page.route()` interception of
`**/_next/image**` (match the decoded `url` param against `/images/<slot>.`) and of
direct `/images/<slot>.svg`. Pre-process candidate bytes with sharp to the published
dimensions from `.runs/image-manifest.json` so what you score matches what would ship.
Nothing in `public/` is touched, no cache to bust, no server to restart. Always
assert the capture is styled before accepting it - check the `<html>` class carries
the Fraunces font-module variable and `getComputedStyle(body).backgroundColor` is
`rgb(243, 240, 230)` (`--paper`). If only a stale server is reachable, its missing
Tailwind chunk can be substituted by intercepting the 404/500 CSS URL and serving
the current file from `.next/static/chunks/*.css`. See [[step55-evidence-gotchas]].
