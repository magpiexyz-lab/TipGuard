---
name: shared-dev-server-fragility
description: During parallel /verify runs, one sibling agent's syntax error 500s every route on the shared :3000 dev server, and Next 16 blocks a second dev server in the same directory
metadata:
  type: project
---

When design-critic agents run in parallel against the lead-supplied
`base_url` (`http://localhost:3000`, DEMO_MODE), the dev server is a **shared
single point of failure**. Next.js dev surfaces a compile error originating in
*any* route as an HTTP 500 on *every* route — so one sibling agent leaving a
file mid-edit blocks all other per-page critics from re-screenshotting their
own fixes.

**Why:** observed on the 2026-08-10 bootstrap-verify run. A JSX comment placed
as a bare sibling inside a ternary consequent in `src/app/staff/roster-import-card.tsx`
took `/violations` to 500 for ~35 minutes across two separate breakages.

**How to apply:**
- The documented escape hatch (start your own server on :3099) does **not**
  work here. Next 16 refuses with *"Another next dev server is already running"*
  when a dev server is already bound to the same project directory, regardless
  of port. `:3099` is also frequently already held by a sibling critic.
- So: screenshot **early**. Capture the full evidence set (desktop, mobile,
  dialogs, tab states, crops) in the FIRST Playwright run, before making edits.
  Do not plan on a leisurely second pass being available.
- Batch all edits, then do one re-verification run. If it is blocked, poll
  `fetch(base_url + route)` for a distinctive on-page string rather than
  status alone — a 200 is not proof, the error overlay also returns HTML.
- Never "temporarily fix" the sibling's broken file to unblock yourself; it
  flip-flops as they iterate and you will clobber their work. Record it under
  `shared_issues` and move on.

Related: [[feedback-scope-lock-boundary]]
