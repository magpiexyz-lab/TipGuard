---
name: project-build-lock-contention
description: Parallel bootstrap fan-out means `next build` is usually lock-held; verify with tsc + eslint instead
metadata:
  type: project
---

During bootstrap Phase B2 fan-out, `next build` normally fails with "Another
next build process is already running" — sibling scaffold agents hold the
Next.js build lock. Verify page work with `npx tsc --noEmit -p tsconfig.json`
plus `npx eslint src/app/<page>`, and record honestly in the trace that the
build gate was not run and why.

**Why:** six scaffold-pages agents plus scaffold-landing/libs/wire run
concurrently against one working tree. Waiting on or retrying the build burns
the turn and still loses the race; the lead runs the real build post-fan-out.

**How to apply:** do not put `build_smoke` in `checks_performed` unless the
build actually ran. Use `typecheck_clean` / `eslint_clean` and add a
`build_not_run_reason` field. Also expect `tsc` to report errors from *other*
agents' half-written pages (e.g. `src/app/signup/`) — those are not yours; only
act on diagnostics pointing at your own page folder. Pairs with
[[feedback-trace-before-polish]].
