# STATE 0: BRANCH_SETUP

**PRECONDITIONS:**
- Git repository exists in working directory
- Current branch is `main` (or resuming on existing `feat/bootstrap*` branch)

**ACTIONS:**

Follow the branch setup procedure in `.claude/patterns/branch.md`. Use branch prefix `feat` and branch name `feat/bootstrap`.

Clean up stale skill-specific artifacts from prior runs:
- `rm -f externals-decisions.json`

> **If resuming from a failed bootstrap:** see `.claude/patterns/recovery.md` for recovery options.

### Sub-step 0.5: Pre-flight template coherence check (warn-only)

Run `verify-linter.sh` against the synced template files. Non-blocking —
warnings only — but surfaces template drift early so users can pull a
fresh upgrade before bootstrap wastes time on a broken template state.

```bash
bash .claude/scripts/verify-linter.sh --warn-only --cache .runs/bootstrap-precheck.json >&2 || true
echo "Template coherence pre-check completed (warn-only). See .runs/bootstrap-precheck.json for details." >&2
```

This pre-check:
- **Does NOT block bootstrap** — the cache file just records findings for review
- Production gating happens via `make lint-template` (CI) and finalize-time
  Step 4.5 (`lifecycle-finalize.sh`)
- Cost is bounded: ~50ms cache-hit, ~1s cache-miss
- Surfaces #931-class drift (state contradictions) and #1024-class drift
  (golden_path consumer drift) before bootstrap runs anything expensive

**POSTCONDITIONS:**
- Current branch is `feat/bootstrap` (or `feat/bootstrap-N` if prior branch exists)
- Branch is not `main`
- `.runs/bootstrap-context.json` exists

> Sub-step 0.5 may write a coherence pre-check artifact, but it's intentionally
> warn-only and not part of POSTCONDITIONS — the cache file may be absent if
> SKIP_COHERENCE_LINT is set, and that's not a failure.

**VERIFY:**
```bash
test -f .runs/bootstrap-context.json && git branch --show-current | grep -q 'feat/bootstrap'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 0
```

**NEXT:** Read [state-1-read-context.md](state-1-read-context.md) to continue.
