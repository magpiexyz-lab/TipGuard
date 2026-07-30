# Silent-Failure Prevention

A catalog of guards that close silent-failure defect classes — places where a
tool, hook, or skill returns "success" while the underlying intent never
took effect. Each entry is paired with a recurrence-prevention lint so the
defect cannot reappear silently in a future template change.

The canonical fix shape is **runtime fail-loud guard + lint-based recurrence
prevention**: a hook (or wrapper) that exits non-zero when the silent-failure
condition is detected, plus a standalone python lint wired into
`lifecycle-finalize.sh` that asserts the guard is wired everywhere it must be.

## Catalogued Issues

### #1170 — env-gated stack files lack production observability prescriptions
- **Symptom:** stack files declared optional capabilities behind env vars; when
  the var was unset in prod, the capability silently degraded with no log.
- **Runtime guard:** stack files now prescribe explicit `console.warn` /
  log-once telemetry when an env-gated path falls through.
- **Recurrence lint:** `check-env-gated-prescriptions.*` (per closeout PRs).

### #1222 — `.claude/scripts/lib/` Bash sourcing
- **Symptom:** lib files sourced via `bash -c source ...` swallowed errors.
- **Runtime guard:** wrapper scripts use `set -euo pipefail` + explicit error
  propagation.
- **Recurrence lint:** verify-linter rule asserts all `lib/*.sh` sources use
  the `set -euo pipefail` preamble.

### #1224 — agent-trace write fall-through
- **Symptom:** Write/Edit on `.runs/agent-traces/*.json` bypassed
  `write-agent-trace.sh` and produced un-augmented trace files.
- **Runtime guard:** `agent-trace-write-gate.sh` PreToolUse hook on Write/Edit.
- **Recurrence lint:** `check-agent-trace-gate-registered.py` (lifecycle-finalize).

### #1225 — worktree-boundary on Edit/Write
- **Symptom:** From inside a `/solve`/`/resolve`/`/change` worktree, Edit/Write
  with a main-repo absolute `file_path` succeeded silently against the main
  repo. `git status` from the worktree showed clean while `git status` from
  main showed modifications. Recovery required `git diff > /tmp/patch;
  git checkout --; git apply /tmp/patch`. Sibling defect to #1170 / #1222 / #1224.
- **Runtime guard:** `.claude/hooks/worktree-boundary-gate.sh` — PreToolUse hook
  on Write / Edit / MultiEdit / NotebookEdit. From inside a non-primary
  worktree, denies any `file_path` outside the active worktree root with a
  corrective-suggestion line. Allowlist: `/tmp/*`, `/private/tmp/*`,
  `/var/tmp/*`, `/private/var/tmp/*`, `~/.claude/projects/*/memory/*`.
- **Recurrence lint:** `check-worktree-boundary-hook-registered.py` — asserts
  the hook exists, is executable, and is registered under all four matchers
  in `settings.json`. Wired blocking in `lifecycle-finalize.sh`.

## Explicit Non-Coverage (#1225)

These defect modes are out of scope for `worktree-boundary-gate.sh`. They are
listed here so a future audit doesn't mistake the gap for a missed case:

1. **Bash-redirect writes** — `cat > <main>/foo`, `tee`, `cp`, `mv`, `> file`,
   `>> file`, `dd of=...` from inside a worktree to a main-repo path. These
   bypass the Edit/Write tool entirely and would require a separate `Bash`
   matcher hook with command-pattern scanning. Tracked for future work; the
   defect class is the same shape but the surface is different.

2. **Parent-cwd-writes-to-stale-worktree** — when the parent session's cwd is
   in main and the agent writes to a stale worktree path that no longer
   exists. This is a different defect class (stale context, not "forgot
   worktree prefix"). Blocking it would harm legitimate user workflows
   (e.g., manually editing files in a worktree from a main-cwd shell).
   Out of scope.

3. **Allowlist coverage of `~/.claude/cache`, `~/.claude/plugins`,
   `~/.claude/sessions`, `~/.claude/settings.local.json`** — narrowed to
   `~/.claude/projects/*/memory/*` only. None of these other paths have
   observed legitimate writers from in-worktree skills, and a broad
   allowlist would mask real defects. Widen with a one-line `case` addition
   plus a corresponding test if telemetry shows legitimate writes blocked.

## Pattern Maintenance

When adding a new entry to this catalog:
- Pair every runtime guard with a lint that asserts the guard is wired.
- Wire the lint blocking in `.claude/scripts/lifecycle-finalize.sh`
  (mirroring the #1200 worktree-ownership block).
- Add a unit-test suite under `.claude/scripts/tests/` and register it in
  `run-all.sh`'s `SUITES` array.
- Document explicit non-coverage so future audits don't mistake gaps for
  missed cases.
