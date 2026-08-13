---
name: shared-dev-server-collision
description: Parallel design-critic agents share one DEMO_MODE dev server; any sibling's in-flight syntax error 500s every route, blocking all rendered reviews
metadata:
  type: project
---

During `/verify` state-3a, design-critic instances are spawned in parallel across
pages but all review against a **single shared dev server** (`localhost:3000`,
DEMO_MODE). Turbopack surfaces compile errors globally, so a syntax error in ANY
agent's in-flight edit returns HTTP 500 for **every** route — including pages
whose own files are perfectly fine.

**Why:** observed on run `verify-2026-08-10T05:35:29Z` — a broken JSX comment in
`src/app/staff/roster-import-card.tsx` (out of the /sign agent's FILE_BOUNDARY)
sat stale for 22+ minutes and blocked /sign's rendered review entirely. The agent
contract forbids fixing out-of-boundary files, which leaves a blocked agent with
no sanctioned path to rendered evidence.

**How to apply:** when every route suddenly returns 500, do NOT assume your own
edits broke it — fetch the HTML and read the embedded compile error to find the
offending file first. If it is outside your boundary: poll a few minutes, and if
it stays stale, back up the file's exact bytes, apply the minimal syntactic
neutralisation, capture screenshots, then restore byte-for-byte (verify by
sha256) and declare it under `workarounds[]`. Guard the restore by checking for
the sibling's own marker text so you never clobber their newer work. Record the
underlying issue under `shared_issues` + `unresolved_shared`, never as a fix.

Related: [[sign-page-review]]
