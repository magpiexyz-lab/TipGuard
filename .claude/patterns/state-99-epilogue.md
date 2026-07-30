# STATE 99: EPILOGUE

Shared terminal state used by every lifecycle skill. Lives in
`.claude/patterns/` (not `.claude/skills/<skill>/`) and is dispatched
via the patterns-dir fallback in `lifecycle-next.sh` → `find_state_file`.

**PRECONDITIONS:**
- All manifest states (non-epilogue) completed — chain-check enforced by
  `state-completion-gate.sh` before `advance-state.sh <skill> 99` is allowed.
  See `.claude/patterns/state-completion-gate.md` for the chain-vs-sequential
  contract — chained edits + `advance-state.sh` in a single Bash invocation
  will DENY because the hook runs VERIFY *before* the chain executes.
- `.runs/<skill>-context.json` exists.
- This skill is NOT an embed (embeds auto-skip `"99"` via
  `embed_skip_epilogue` context flag — see `lifecycle-init.sh --embed`).

**ACTIONS:**

### Step 0 — Derive SKILL_KEY (shared across all steps)

Derive the active skill identity once at the top so every downstream step
(finalize, observation enforcement, advance-99) uses the same deterministic
value. Fix #1071/def1 — previously each step re-derived SKILL from an
indeterminate glob, picking stale spec-context.json when multiple contexts
existed in `.runs/`.

```bash
SKILL_KEY=$(python3 -c "
import json, glob, os, sys
best = None
best_ts = ''
for f in glob.glob('.runs/*-context.json'):
    if f.endswith('/epilogue-context.json'):
        continue
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if d.get('completed') is True:
        continue
    ts = d.get('timestamp', '') or ''
    if ts >= best_ts:
        best = d
        best_ts = ts
sys.stdout.write((best or {}).get('skill', ''))
")
[ -n "$SKILL_KEY" ] || { echo 'ERROR: state-99 could not derive SKILL_KEY from .runs/*-context.json' >&2; exit 1; }

# GRAIM v2 C1+C2: derive RUN_ID from the active skill's context so every
# observation-enforcement.json writer in this state can stamp identity.
RUN_ID=$(python3 -c "
import json
try:
    d = json.load(open('.runs/${SKILL_KEY}-context.json'))
    print(d.get('run_id', ''))
except Exception:
    print('')
")
[ -n "$RUN_ID" ] || { echo 'WARN: state-99 could not derive RUN_ID' >&2; }
```

### Step 1 — Delivery & recheck

Run finalize: delivers for code-writing skills (commit → push → PR →
auto-merge), no-ops for analysis-only skills that produced no delivery
artifacts, and treats analysis-only runs WITH artifacts as deliberate record
deliveries (the default-branch guard in finalize enforces PR-first — see
`.claude/patterns/auto-merge.md`). Writes `.runs/verify-recheck.json`.

```bash
bash .claude/scripts/lifecycle-finalize.sh "$SKILL_KEY"
```

Pass the `$SKILL_KEY` derived at Step 0 — finalize normalizes mode-qualified
keys (e.g. `iterate-cross`) down to the base skill internally when resolving
the manifest and command file.

Self-reference note: `lifecycle-finalize.sh` Step 2 reruns every state's
VERIFY as a warn-only audit. It explicitly skips `state_id == "99"`
because state 99 is currently in flight — its VERIFY checks artifacts
this step writes.

### Step 2 — Derive scope and run observation

Read `.claude/patterns/skill-epilogue.md` and follow its procedure,
**skipping Step 0** (finalize already verified state completion).

`skill-epilogue.md` derives observation scope from `skill.yaml`
(full | process | code | audit-only) and calls
`.claude/patterns/observation-phase.md`. That writes:
- `.runs/observe-result.json` (always for non-optimize-prompt skills)
- `.runs/compliance-audit-result.json` (full/process/code/audit-only)
- `.runs/retrospective-result.json` (full/process with agent traces)

### Step 2a — Deterministic artifact enforcement

```bash
bash .claude/scripts/check-observation-artifacts.sh "$SKILL_KEY"
```

Pass the active skill as `$1` (fix #1071/def1). Without the explicit arg, the
script falls back to an mtime-sorted glob of `.runs/*-context.json` — better
than the original indeterminate filesystem ordering, but still racy when
multiple contexts are touched in the same second. The explicit arg is the
deterministic source.

This script is intentionally non-blocking (always exits 0). It writes
`.runs/observation-enforcement.json` — trap-guaranteed on any exit path
— with fields `{pass, missing, scope, skill, run_id, fast_path, timestamp}` or
`{pass: False, error: "..."}` when the script itself crashes. The `skill`
and `run_id` fields are asserted by state-99 VERIFY against the active
`.runs/<skill>-context.json` (GRAIM v2 C1+C2 — rejects stale prior-skill
artifacts; see issue #1198).

### Step 3 — Remediation (conditional)

If `.runs/verify-recheck.json` contains `failed > 0` OR non-empty
`missing_states`:

```bash
# Read .claude/patterns/remediation-phase.md and execute its procedure.
```

Remediation may retry observation; do NOT advance state 99 until the
retry resolves.

### Step 3a — Legitimate skip path (service outage)

If observation fails twice and external-service unavailability is
confirmed (Anthropic API down, GitHub API down), write an explicit
skip artifact before advancing — VERIFY accepts `skipped=True`:

```bash
PAYLOAD=$(python3 -c "
import json, datetime
print(json.dumps({
    'pass': False, 'skipped': True, 'scope': 'unknown',
    'fast_path': False,
    'skip_reason': 'external_service_unavailable',
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
}))
")
# state-99 runs post-skill-completion via lifecycle-finalize.sh, so the
# active context's identity may already be marked completed=true. Pass
# --source-run-id and --source-skill explicitly (AOC v1.2 path) using
# SKILL_KEY/RUN_ID derived in Step 0.
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/observation-enforcement.json \
  --payload "$PAYLOAD" \
  --source-run-id "$RUN_ID" \
  --source-skill "$SKILL_KEY"
```

This is the ONLY legitimate manual skip. Any other observation failure
must trigger remediation-phase; VERIFY rejects bare `error` fields so
no silent skip is possible.

### Step 4 — Mark complete

Use the `$SKILL_KEY` derived at Step 0 (handles mode-qualified skills:
`iterate-check`, `iterate-cross`) and call `advance-state.sh` with that key
so `state-completion-gate.sh` resolves VERIFY against the right registry entry.

```bash
bash .claude/scripts/advance-state.sh "$SKILL_KEY" 99
```

The `state-completion-gate.sh` hook enforces the VERIFY below before
this command is allowed to execute.

**POSTCONDITIONS:**
- `.runs/verify-recheck.json` exists (written by Step 1).
- `.runs/observation-enforcement.json` exists (written by Step 2a).
- That JSON's `pass` field is `True` OR its `skipped` field is `True`.
  An `error` field does NOT satisfy — that path requires remediation
  (Step 3) or explicit `skipped=True` write (Step 3a).

**VERIFY:**
```bash
test -f .runs/verify-recheck.json && test -f .runs/observation-enforcement.json && python3 -c "import json,glob; d=json.load(open('.runs/observation-enforcement.json')); ctx=None
for f in glob.glob('.runs/*-context.json'):
    if 'epilogue' in f: continue
    try: c=json.load(open(f))
    except: continue
    if c.get('completed') is True: continue
    if ctx is None or (c.get('timestamp','') > (ctx.get('timestamp','') or '')): ctx=c
active_skill=ctx.get('skill','') if ctx else ''
active_run_id=ctx.get('run_id','') if ctx else ''
assert d.get('pass') is True or d.get('skipped') is True, 'observation enforcement failed: pass=%s skipped=%s missing=%s scope=%s error=%s' % (d.get('pass'), d.get('skipped'), d.get('missing'), d.get('scope'), d.get('error'))
assert d.get('skill') == active_skill, 'observation-enforcement.json skill=%r does not match active_skill=%r (stale prior-skill artifact)' % (d.get('skill'), active_skill)
assert d.get('run_id') == active_run_id, 'observation-enforcement.json run_id=%r does not match active_run_id=%r (stale artifact)' % (d.get('run_id'), active_run_id)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete
(see Step 4 above for `$SKILL_KEY` derivation):
```bash
bash .claude/scripts/advance-state.sh "$SKILL_KEY" 99
```

**NEXT:** `lifecycle-next.sh` returns `FINALIZE`. Skill terminates.
