---
name: parallel-dev-server-hazard
description: In verify runs the shared Next server is a PRODUCTION build (next dev cannot run at all here); a syntax error in ANY parallel agent's file breaks every route, and there is no HMR.
metadata:
  type: project
---

During `/verify` state-3a, every per-page design-critic shares the single
`DEMO_MODE` dev server the lead started (`:3000`). Next 16 + Turbopack surfaces
compilation errors **globally**: a JSX syntax error another agent leaves in, say,
`src/app/staff/roster-import-card.tsx` makes `/dashboard` return HTTP 500 too.
The escape hatch does not exist — `npx next dev -p <other>` exits with
"Another next dev server is already running" for the same directory, and the
spawn prompt forbids killing the shared one.

**Why:** observed on the 2026-08-10 bootstrap verify run — the staff critic left
its file unparseable and `/dashboard` stayed 500 for ~70 minutes, blocking
post-fix re-screenshots. `npm run build` is equally blocked (same parse error).

**`next dev` does not work in this project at all** (confirmed 2026-08-11): there
is no network egress, so `next/font/google` cannot reach `fonts.gstatic.com` and
Turbopack 500s every route. The `:3000` server the lead starts is a PRODUCTION
build (`DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run build` + `npm start`).
Do not try to start `next dev` — one design-critic run was lost to exactly that.

**How to apply:**
- **There is no HMR.** Screenshot first, decide every fix, apply them together,
  then rebuild once (~2 min) and restart. Batching is correct here — this
  inverts the "screenshot immediately after each edit" advice below, which only
  applies if a dev server is ever available again.
- Playwright resolves only from the project root, not the scratchpad: write
  throwaway `.tmp-*.mjs` capture scripts into the repo root and `rm` them before
  finishing, or `node` exits with ERR_MODULE_NOT_FOUND.
- Take the post-fix screenshot **immediately** after each edit batch rather than
  batching all edits and re-screenshotting once at the end.
- When the server 500s, confirm blame with
  `curl -s http://localhost:3000/<route> | grep -oE '"message":"[^"]{0,220}'` —
  it names the offending file. If it is outside your FILE_BOUNDARY, do not fix it.
- Fall back to `npx tsc --noEmit` filtered to your own directory plus a
  design-token existence check in `src/app/globals.css` (`--color-*` entries) to
  validate an unverifiable last edit, and record the gap in the trace under
  `shared_issues` + a `verification_caveat` field rather than inflating the verdict.
