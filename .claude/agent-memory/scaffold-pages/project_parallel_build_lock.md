---
name: project-parallel-build-lock
description: During bootstrap Phase B2 fan-out, `npm run build` fails fast with "Another next build process is already running" because parallel scaffold-pages agents share one Next build lock.
metadata:
  type: project
---

`npm run build` is not safely concurrent during bootstrap Phase B2. Next.js 16
holds a single per-project build lock, so when several scaffold-pages agents are
spawned in parallel the losers exit immediately with
`Another next build process is already running` — an exit that looks like a real
build failure but is not.

**Why:** bootstrap STATE 11c fans out ~5 scaffold-pages agents at once (one per
page pair), and each one wants to verify its own work with a production build.

**How to apply:** verify with `npx tsc --noEmit` + `npx eslint <your page dirs>`
first — those are concurrency-safe and catch nearly everything. Run the full
build through a retry loop (backgrounded, ~60s between attempts) rather than
treating the first lock message as a failure. Do not report a build failure in
the trace on the strength of a lock message alone.

Related: [[project-scaffold-wire-boundary]]
