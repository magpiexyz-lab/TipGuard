---
name: project-visual-review-environment
description: Two non-obvious gotchas when screenshotting this project on Windows — shared dev-server contention between parallel critics, and where /tmp actually lands
metadata:
  type: project
---

Visual review in this repo has two environment quirks that cost real turns if rediscovered.

**1. Parallel design-critic agents share one dev server, and Turbopack makes that fragile.**
`/verify` state-3a spawns one design-critic per page against a single DEMO_MODE server
(usually `http://localhost:3000`). Turbopack reports *any* module-graph syntax error as a
global 500, so while another agent has its page mid-edit, **every** route returns 500 —
including yours. This looks exactly like "the page I'm reviewing is broken."

**Why:** it is cross-agent contention, not a defect in the page under review.

**How to apply:** before concluding a page is broken, check whether the 500 body names a
file outside your FILE_BOUNDARY. If so, poll and retry — outages lasted ~15 min in one run.
If polling stalls, build a throwaway copy *inside* the project (e.g. `.dc-verify/`), delete
the offending out-of-boundary route folder from the copy only, and run `next dev` on a spare
port. Copy must live inside the project so `node_modules` resolves by walking up — Turbopack
rejects a cross-drive junction with "Symlink [project]/node_modules ... points out of the
filesystem root." Never edit or stash another agent's files. Clean up the copy afterward.
Also check the spare port is actually yours: another agent may already hold 3099.

**2. Playwright's `/tmp/visual-review` is not bash's `/tmp`.**
Node on Windows resolves a leading `/` against the *current drive*, so screenshots written to
`/tmp/visual-review/x.png` from a script run in `D:\...\TipGuard` land in `D:\tmp\visual-review\`.
Git Bash's `/tmp` points at `%LOCALAPPDATA%\Temp`, so `cp /tmp/visual-review/*.png` silently
copies nothing.

**How to apply:** when copying screenshots to `.verify-baseline/`, source them from
`D:/tmp/visual-review/`, and never suppress `cp` stderr — the failure is otherwise invisible.

See [[feedback-out-of-boundary-discipline]].
