---
name: parallel-dev-server-500
description: Parallel design-critic agents share one dev server; any agent's syntax error 500s every route, so keep an independent render harness ready
metadata:
  type: project
---

During `/verify` state-3a, all per-page design-critic agents review against a
single shared dev server (`base_url` in the spawn prompt). Turbopack returns
HTTP 500 for **every** route when any file in the graph has a syntax error, so
one agent mid-edit on an out-of-boundary page blocks every other agent's
screenshots.

**Why:** observed 2026-08-10 on `verify-2026-08-10T05:35:29Z` — a `{/* */}`
comment placed in expression position in `src/app/staff/roster-import-card.tsx`
took `/signup` (and every other route) to 500 for ~3 minutes mid-review.

**How to apply:** do not fix the other agent's file (boundary violation) and do
not kill/restart the shared server. Instead:
1. Background-poll `curl -o /dev/null -w "%{http_code}"` on your route, and
2. meanwhile verify class-level changes against a standalone harness — compile
   the project's real CSS with the installed PostCSS plugin
   (`postcss([require('@tailwindcss/postcss')]).process(globals.css)`), point a
   static HTML replica of your JSX at it, and screenshot that with Playwright.
   Custom-property scopes (`.dark`), `background-image` collisions, and grid
   track geometry all reproduce faithfully.
3. Re-verify on the live route once the server recovers, then record the
   blocker under `shared_issues` and the harness under `workarounds`.

Run temp `.mjs` scripts from the **repo root**, not the scratchpad — Node
resolves `playwright` from the script's own directory.

Related: [[trace-before-polish]]
