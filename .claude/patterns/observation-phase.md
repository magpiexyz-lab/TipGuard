# Observation Phase — Unified Template Observation Procedure

> **Single entry point for all observation across all 16 lifecycle skills.**
> Called by `skill-epilogue.md` after `lifecycle-finalize.sh` completes.
> Replaces verify STATE 6 (AUTO_OBSERVE) + STATE 6b (LEAD_RETROSPECTIVE)
> and skill-epilogue Strategy A/B with one parameterized procedure.

## Parameters

Received from the caller (skill-epilogue.md or /observe skill):

- **scope**: `full` | `code` | `process` | `audit-only`
- **skill**: the active skill name (from `*-context.json`)

### Scope Derivation (performed by caller)

The caller reads `.claude/skills/<skill>/skill.yaml` and derives scope:

```
if skill.yaml has embed with skill: verify → scope = "full"
elif skill.yaml has critic/challenger agents AND diffs exist → scope = "full"
elif skill.yaml has critic/challenger agents AND no diffs → scope = "process"
elif diffs exist → scope = "code"
else → scope = "audit-only"
```

**Critic/challenger agents** are agents whose role is to challenge or evaluate
quality: `solve-critic`, `resolve-challenger`, `review-challenger`.
**Operational agents** like `provision-scanner` do not trigger process observation.

| Skill | Scope | Rationale |
|-------|-------|-----------|
| bootstrap | full | embed:verify — agents + diffs |
| change | full | embed:verify — agents + diffs |
| distribute | full | embed:verify — agents + diffs |
| resolve | full | solve-critic + resolve-challenger + diffs |
| review | full | review-challenger + diffs |
| deploy | code | operational agent only, has diffs |
| spec | code | diffs, no agents |
| upgrade | code | diffs, no agents |
| solve | process | solve-critic, no diffs |
| audit | audit-only | no agents, no diffs |
| iterate | audit-only | no agents, no diffs |
| retro | audit-only | no agents, no diffs |
| rollback | audit-only | no agents, no diffs |
| teardown | audit-only | no agents, no diffs |

## Step 1: Idempotency Guard

If `.runs/observe-result.json` already exists, **STOP**. Another mechanism
already wrote it. Do not overwrite.

## Step 2: Evidence Collection

Collect all available evidence (shared across all scopes):

```bash
# a. Collect branch diffs — IDEMPOTENT with lifecycle-finalize.sh and
# skill-epilogue.md. finalize writes observer-diffs.txt PRE-merge; this step
# runs within skill-epilogue POST-merge when HEAD is already on main and
# `git merge-base main HEAD == HEAD` (empty diff). Only collect when the file
# is absent or empty — otherwise re-running clobbers the finalize evidence.
if [ ! -s .runs/observer-diffs.txt ]; then
  if git log --oneline $(git merge-base main HEAD)..HEAD 2>/dev/null | grep -q .; then
    git diff $(git merge-base main HEAD)...HEAD > .runs/observer-diffs.txt
  else
    git diff --cached > .runs/observer-diffs.txt
    git diff >> .runs/observer-diffs.txt
  fi
fi

# b. Read fix-log (if exists)
# .runs/fix-log.md — created during skill execution when retries/failures occur

# c. Generate template file list
cat .claude/template-owned-dirs.txt | grep -v '^#' | grep -v '^$' | xargs -I{} find {} -type f 2>/dev/null | sort

# d. Refresh hook-friction-summary.json (#1895 tail fix). lifecycle-finalize.sh
#    Step 2.6 remains the canonical FIRST aggregation, but friction keeps
#    accruing after finalize returns (epilogue steps, evidence-envelope
#    writes). Re-running here — idempotent, full rebuild, strictly scoped to
#    the active run_id — makes the summary the observer reads at Step 4 cover
#    everything up to just before the envelope is written. The observer's own
#    spawn still lands after this instant; check-observation-artifacts.sh
#    reports those as rows_after_cutoff (vs the summary's aggregated_at)
#    instead of letting the truncation pass silently. The summary is the 4th
#    evidence channel for the Step 5a Q2 retrospective; its absence is a hard
#    failure surfaced by check-observation-artifacts.sh and compliance-audit's
#    check_q2_evidence_complete.
python3 .claude/scripts/aggregate-hook-friction.py >/dev/null 2>&1 || true

# e. (#1255) Expanded evidence sources — the observer must consult these
#    when present. The observer agent's trace MUST list paths it consulted
#    in `evidence_consulted[]` (validated by
#    .claude/scripts/validate-observer-evidence-coverage.py).
#    - .runs/hook-friction-summary.json:
#        contains `normalized_groups` (#1255 round-2 C6) — recurring denial
#        patterns with paths/IDs stripped, surfacing template-rooted issues
#        that varied per call site.
#    - .runs/hook-friction.jsonl: raw audit trail (sample if needed)
#    - .runs/agent-traces/scaffold-*.json `template_recommendations[]` field:
#        structured template-gap recommendations from scaffold-* agents
#        (#1252 contract). When non-empty, the observer marks consultation
#        with `"scaffold-template-recommendations"` in evidence_consulted[].
#        Entries whose `file` is template-rooted may be auto-filed via
#        file-retrospective-finding.py.
```

### Fallback: belt-and-suspenders consolidate (AOC v1 FLS v1)

`lifecycle-finalize.sh` Step 2.5 invokes both `write-fix-ledger.py` and
`render-fix-log.py` unconditionally on every skill termination (closes
#1449), so by the time observation-phase runs (state-99) `fix-log.md` is
already populated from the ledger. The fallback below is belt-and-suspenders
for fast-path skills that skip finalize (legitimate per
`lifecycle-init.sh --skip-finalize` flow) or standalone `/observe`
invocations. The consolidator writes `.runs/fix-ledger.jsonl` from agent
trace `fixes[]` arrays (covering ALL verdict_agents); the renderer
regenerates `fix-log.md` from the ledger via atomic temp+rename. Both are
idempotent. Eliminates the count-drift class documented in #1048.

```bash
RUN_ID=$(python3 -c "
import json, glob
for f in glob.glob('.runs/*-context.json'):
    if 'epilogue' in f: continue
    try:
        print(json.load(open(f)).get('run_id', ''))
        break
    except Exception:
        continue
" 2>/dev/null || echo "")
python3 .claude/scripts/write-fix-ledger.py --run-id "$RUN_ID"
python3 .claude/scripts/render-fix-log.py
```

Authoritative count is `wc -l .runs/fix-ledger.jsonl`. If the ledger is
empty after consolidation, the run had no fixes (equivalent to the old
`NO_FIXES` branch). `fix-log.md` is always regenerated by the renderer;
other writers are forbidden by AOC v1 R2 and the runtime
`fix-ledger-write-guard.sh` hook.

## Step 2.5: Write Evidence Check Artifact

Record proof that the evidence scan was performed:

```bash
python3 -c "
import json, os, glob, datetime, sys
fix_log_lines = 0
if os.path.exists('.runs/fix-log.md'):
    with open('.runs/fix-log.md') as f:
        fix_log_lines = max(0, len([l for l in f.readlines() if l.strip()]) - 1)
# fix_log_entries counts the WHOLE-HISTORY render (informational; the ledger
# is append-only across runs). The run-scoped sibling below is what the
# Step 3 fast path keys on.
current_run_rows = -1
try:
    sys.path.insert(0, '.claude/scripts/lib')
    from runs_reader import read_jsonl
    # state-99 Step 0 exports RUN_ID; Step 2.6 later derives SOURCE_RUN_ID —
    # accept either (informational field, best-effort).
    rid = os.environ.get('SOURCE_RUN_ID') or os.environ.get('RUN_ID', '')
    if rid:
        current_run_rows = len(read_jsonl('.runs/fix-ledger.jsonl',
                                          scope='current-run',
                                          current_run_id=rid).rows)
except Exception:
    pass
trace_fixes = 0
for tf in glob.glob('.runs/agent-traces/*.json'):
    try:
        data = json.load(open(tf))
        if isinstance(data.get('fixes'), list) and len(data['fixes']) > 0:
            trace_fixes += 1
    except: pass
json.dump({
    'fix_log_entries': fix_log_lines,
    'fix_ledger_rows_current_run': current_run_rows,
    'trace_fixes_found': trace_fixes,
    'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
}, open('.runs/observe-evidence-check.json', 'w'), indent=2)
"
```

(`fix_ledger_rows_current_run` is `-1` when the active run_id could not be
resolved — informational only, never a gate input.)

## Step 2.6: Write Observation Evidence Envelope (AOC v1.2 — closes #1259)

Produce `.runs/observation-evidence.json` — the unified input contract the
observer reads in Step 4. Every present canonical evidence family is
referenced; the schema is defined by the writer + the shared family
manifest at `.claude/scripts/lib/observer_evidence_families.py`. No
exclusion mechanism — adding a family requires editing that constant
(visible in PR diff).

**Identity-resolution path** — observation-phase typically runs from
skill-epilogue.md AFTER lifecycle-finalize.sh has marked the active
context `completed:true`. In that case `resolve_active_identity` returns
empty and the canonical writer needs explicit source flags. Read the
epilogue context for the source identity:

```bash
# Derive source identity from the skill-epilogue context. SKILL_KEY is
# typically already exported by state-99-epilogue.md Step 0.
SKILL_KEY="${SKILL_KEY:-$(python3 -c "
import json, glob
best = None; best_ts = ''
for f in glob.glob('.runs/*-context.json'):
    if f.endswith('/epilogue-context.json'): continue
    try: d = json.load(open(f))
    except: continue
    ts = d.get('timestamp','') or ''
    if ts >= best_ts: best=d; best_ts=ts
print((best or {}).get('skill',''))
")}"
SOURCE_RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/${SKILL_KEY}-context.json')).get('run_id',''))")

# Try the no-override path first (works pre-completion, e.g., embedded
# observation-phase calls from /verify or /resolve mid-skill). If that
# fails (post-completion: all *-context.json have completed:true), fall
# back to explicit source flags.
python3 .claude/scripts/write-observation-evidence.py 2>/dev/null \
  || python3 .claude/scripts/write-observation-evidence.py \
       --source-run-id "$SOURCE_RUN_ID" \
       --source-skill "$SKILL_KEY"
```

The envelope schema includes:
  - All present `*-summary.json`, `*-merge.json`, `*-evidence*.json`,
    `*-result.json`, `agent-traces/*.json` paths
  - `fix_ledger_path`, `fix_log_path`, `hook_friction_summary_path`,
    `observer-diffs.txt`, `build-result.json`, `e2e-result.json`
  - `template_recommendations[]` flattened from agent traces (AOC v1.2
    optional field on scaffold-* agents — closes #1252 anti-pattern)
  - `skipped_fixer_traces[]` listing any `provenance:lead-skipped` traces
    (PR3 sanctioned-skip output — surfaced for observer convenience so it
    can correlate with the audit-skip path)
  - `fix_ledger_lead_fix_count` (count of `provenance:lead` ledger rows)

Under post-completion conditions, supply `--source-run-id <ID>
--source-skill <NAME>` (validator R1-R4 enforced).

## Step 3: Fast-Path Evaluation

If `.runs/observer-diffs.txt` is empty AND `.runs/fix-ledger.jsonl` has no
rows for the ACTIVE run_id AND no agent traces contain fixes:

Write `.runs/observe-result.json`:
```json
{
  "skill": "<skill-name>",
  "timestamp": "<ISO 8601>",
  "friction_detected": false,
  "observations_filed": 0,
  "verdict": "clean"
}
```

If scope is `process` or `audit-only`, also add `"strategy": "execution-audit"`.

**DONE.** Zero overhead on the happy path.

**Why the fix condition is run_id-scoped (issue #2009):** the ledger is
append-only across runs by design (registered `fix-ledger` channel in
`cross-run-channels.json`) and `fix-log.md` is a whole-history render that
lifecycle-finalize.sh regenerates at every termination — so `fix-log.md` MAY
be non-empty on a perfectly clean fast path, and testing it would disable the
fast path forever after the first run that recorded a fix. Count ledger rows
instead, scoped to the active run:

```bash
CURRENT_RUN_FIXES=$(python3 -c "
import sys
sys.path.insert(0, '.claude/scripts/lib')
from runs_reader import read_jsonl
rid = '$SOURCE_RUN_ID'  # from Step 2.6; empty when unresolvable
if rid:
    r = read_jsonl('.runs/fix-ledger.jsonl', scope='current-run', current_run_id=rid)
else:
    # Degraded identity: require an entirely empty ledger (the pre-#2009
    # behavior) — the fast path is a privilege, never fail-open.
    r = read_jsonl('.runs/fix-ledger.jsonl', scope='cross-run-by-design',
                   cross_run_channel='fix-ledger')
print(len(r.rows))
")
```

Rows with an empty/missing `run_id` are historical (HC2 — skipped by the
current-run scope). This condition MUST stay semantically identical to the
`FAST_PATH` derivation in `check-observation-artifacts.sh` (state-99 Step 2a
re-derives it independently; divergence means Step 3 fires the fast path
while the checker demands the Step 5a/5b artifacts and flips `pass=false`).

## Step 4: Code Observation

**Activates when:** scope is `full` or `code` AND diffs exist (non-empty
`.runs/observer-diffs.txt`).

**Skip when:** scope is `process` or `audit-only`, OR no diffs exist.

### Collect targeted diffs

```bash
python3 -c "
import re, subprocess, os
# Skip targeted-diff regex when comprehensive diff already populated by
# lifecycle-finalize.sh:218 — overwriting it would strip .py/.sh files (#1128 L1).
if os.path.isfile('.runs/observer-diffs.txt') and os.path.getsize('.runs/observer-diffs.txt') > 0:
    print('observer-diffs.txt already populated; skipping targeted regex collection')
else:
    fixes = open('.runs/fix-log.md').read() if os.path.exists('.runs/fix-log.md') else ''
    # Widened extension allowlist (#1128 L1) — previous filter stripped .py and .sh.
    files = sorted(set(re.findall(
        r'\x60([^\x60]+\.(?:ts|tsx|js|jsx|json|css|py|sh|md|yaml|yml|toml))\x60',
        fixes,
    )))
    diffs = []
    for f in files:
        r = subprocess.run(['git', 'diff', 'HEAD', '--', f], capture_output=True, text=True)
        if r.stdout.strip():
            diffs.append(f'=== {f} ===\n{r.stdout}')
        elif os.path.exists(f):
            r2 = subprocess.run(['git', 'diff', '--no-index', '/dev/null', f], capture_output=True, text=True)
            if r2.stdout.strip():
                diffs.append(f'=== {f} (new file) ===\n{r2.stdout}')
    with open('.runs/observer-diffs.txt', 'w') as out:
        out.write('\n'.join(diffs) if diffs else '(no diffs captured)')
    print(f'Collected diffs for {len(diffs)} files -> .runs/observer-diffs.txt')
"
```

### Spawn observer agent

> REF: The observer agent implements `.claude/patterns/observe.md` Path 1
> (Observer Agent with diff). The decision framework, redaction rules, dedup
> logic, and issue filing format are defined there.

1. Spawn the `observer` agent (`subagent_type: observer`).
   Pass ONLY: the path `.runs/observation-evidence.json` (envelope written
   by Step 2.6) + template file list from Step 2c. The envelope IS the
   observer input contract — every present canonical evidence family is
   referenced inside it (diffs, fix-log, fix-ledger, hook-friction summary,
   all agent traces, build/e2e results, template_recommendations[],
   skipped_fixer_traces[], etc.). Observer reads from the envelope; it
   should NOT separately glob `.runs/*` (closes #1259).
   Do NOT include experiment.yaml content, project name, or feature descriptions.

2. Report the observer's result.

3. Verify `.runs/agent-traces/observer.json` exists; if agent returned output
   but trace is missing, write a recovery trace with `"recovery":true` via
   `bash .claude/scripts/write-recovery-trace.sh observer --reason "<cause>"`.

4. (#1255) Validate observer consulted the expanded evidence-set:
   ```bash
   python3 .claude/scripts/validate-observer-evidence-coverage.py
   ```
   This asserts the observer trace's `evidence_consulted[]` lists all
   non-empty evidence sources (hook-friction.jsonl, hook-friction-summary.json,
   scaffold-* template_recommendations[]). Default MODE=warn during rollout;
   becomes blocking after 1-2 real cycles confirm zero false positives.

### Write `observe-result.json` (lead-side, HC4)
<!-- sanctioned-manual-write: .runs/observe-result.json -->

#1381 D2: the non-fast-path Step 4 must explicitly write `.runs/observe-result.json`
once the observer agent returns. The lead owns this artifact — the observer
agent writes its own trace at `.runs/agent-traces/observer.json` and files
GitHub issues, but does NOT write `observe-result.json` (HC4 — graceful
degradation when observer fails or is skipped; check-observation-artifacts.sh
asserts the file exists in state-99 epilogue, so the procedure cannot leave
this implicit).

After the observer returns successfully (and evidence coverage validates),
the lead extracts the observer's verdict + filing counts from the trace and
writes the canonical result via `write-gate-artifact.sh` (NO direct Write):

```bash
PAYLOAD=$(python3 -c "
import json, datetime
t = json.load(open('.runs/agent-traces/observer.json'))
print(json.dumps({
    'skill': '<active skill>',
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'friction_detected': t.get('friction_detected', False),
    'observations_filed': t.get('observations_filed', 0),
    'verdict': t.get('verdict', 'clean'),
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/observe-result.json \
  --payload "$PAYLOAD" \
  --skill <active-skill>
```

If observer spawning fails, retry once with reduced scope (pass only fix-log
summaries, omit full diffs). If it still fails, the lead agent must perform
inline evaluation of fix-log entries using the 3-condition test (Step 6) —
do NOT skip to writing a clean verdict. Write `observe-result.json` with
`"verdict": "error"` and `"error_reason": "<failure description>"` only if
inline evaluation also fails.

### Cross-skill / post-completion recovery (AOC v1.1)

When `/observe` runs as a standalone skill (not embedded in `/verify`) and
discovers a stub trace from a *preceding* skill's completed run, the default
recovery path is blocked because `resolve_active_identity` returns the
current `/observe` context, not the source skill's run_id.

AOC v1.1 (PR3) adds `--run-id <ID>` to `write-recovery-trace.sh` for exactly
this case:

```bash
# Identify the source run from the spawn-log
SOURCE_RUN_ID=$(python3 -c "
import json
for line in open('.runs/agent-spawn-log.jsonl'):
    e = json.loads(line)
    if e.get('agent') == '<agent>' and e.get('hook') == 'skill-agent-gate':
        print(e['run_id'])
        break
")

# Recover the stub from a different skill's run
bash .claude/scripts/write-recovery-trace.sh <agent> \
  --run-id "$SOURCE_RUN_ID" \
  --reason "post-completion epilogue audit"
```

Preconditions enforced (defense-in-depth):
1. `--reason` mandatory (existing #963 forgery defense)
2. Supplied `<RUN_ID>` must appear in some `.runs/*-context.json.run_id`
3. Spawn-log must have an entry for `<agent>` + `<RUN_ID>`
4. The supplied context's `skill` MUST differ from the currently-active
   skill — same-skill recovery via `--run-id` is forbidden (use the
   no-override path instead). Double-empty (both skills empty) fails closed.

Same-skill recovery during an active run continues to use the no-override
path, which `resolve_active_identity` resolves correctly.

## Step 5: Process Observation

Split into three sub-steps with scope-controlled activation.

### Step 5a: Agent Instruction Compliance

**Activates when:** scope is `full` or `process` AND agent traces exist in
`.runs/agent-traces/`.

**Skip when:** scope is `code` or `audit-only`, OR no agent traces exist.

> **NEVER delegate Step 5a to a spawned Agent.** This step requires the
> lead's in-memory execution context (hook-friction events, deviation reasoning,
> workarounds absorbed by changing approach) — context that does not exist in
> any artifact and CANNOT be reconstructed from agent traces alone. Lead writes
> `.runs/retrospective-result.json` directly via the Write tool. Observer
> agents (or any other spawned subagent) must not be passed this artifact path
> in their prompt. Enforced at three layers:
>   1. `lead-deliverable-gate.sh` (PreToolUse Agent matcher) — denies any
>      Agent invocation whose prompt mentions `retrospective-result.json`.
>   2. `retrospective-content-gate.sh` (PreToolUse Write/Edit matcher) — requires
>      `step_5a_executor: "lead"` to be present in the file content.
>   3. `compliance-audit.py check_lead_deliverable_compliance` — post-write
>      block on missing/wrong field, or missing `observation-evidence.json` sibling.
> See `.claude/patterns/lead-only-artifacts.json` for the canonical manifest.

The lead agent answers 3 structured questions using its full execution context
(agent traces, fix-log, verify-context or skill-context, in-memory knowledge):

**Question 1: Flow Compliance**

> "Did execution strictly follow the state machine flow defined in skill files?
> State ordering, gate triggers, transitions — were any states skipped, reordered,
> or handled incorrectly?"

Review:
- `completed_states` in `*-context.json` vs expected states in state-registry.json
- Whether any hard gate was triggered and handled correctly

*(Q1 covers the macro flow only. Per-step executor correctness is Q2.)*

**Question 2: Per-step Executor Compliance**

> "For each step within the state machine, did each executor (spawned agent
> OR lead acting on the state machine) execute its defined procedure correctly?
> If a lead action was blocked or rerouted by a hook (per
> `.runs/hook-friction-summary.json`), or the lead/agent patched a template file
> (per `.runs/fix-ledger.jsonl` rows where `entry_type == \"template-edit\"`)
> — was the template instruction wrong/incomplete/ambiguous, or did the
> executor simply not follow it?"

Review:
- Each agent trace in `.runs/agent-traces/*.json` — verdict, checks_performed, fixes
- Lead actions: hook-friction summary (per-hook count + sample reasons) and
  template-edit ledger rows (which template files the lead patched and why)
- Whether agent outputs were usable by downstream consumers
- Whether any agent exhausted turns or produced recovery traces

**Question 3: Trace Fidelity**

> "Do the written traces accurately reflect actual execution, or are there
> omissions or inconsistencies?"

Review:
- Are all expected agent traces present?
- Do trace verdicts match observed behavior?
- Are fix-log entries consistent with agent trace fixes arrays?

#### Evaluate findings

For each finding from Q1-Q3, apply the 3-condition test (observe.md):
- **Condition A**: Template file is the root cause
- **Condition B**: NOT caused by environment issues
- **Condition C**: NOT specific to this project

#### File qualifying observations

For findings passing all 3 conditions, follow observe.md's Redaction, Dedup,
and Issue Creation sections.

#### Hard gate required path

Read the skill's context JSON. If `hard_gate_failure` is true AND the Step 5a
scope gate above activates (scope in {full, process}):

Hard-gate trips are the **strongest** trigger for the 3-question retrospective,
not a reason to skip it. The lead has full causality context (hook blocks
applied, workarounds accumulated, which specific gate fired and why); only this
step can convert that context into template-rooted observations. Skipping it
self-silences the diagnostic exactly when it would be most valuable (#1066).

- Execute the full Q1/Q2/Q3 retrospective above with the failing gate as the
  central causal question. Identify which hard gate fired
  (design-critic unresolved, ux-journeyer blocked, security-fixer partial,
  quality-fixer exhausted, etc.) and cross-reference with completed_states,
  each agent trace's verdict/checks_performed/fixes[], hook log entries, and
  any recovery trace.
- File diagnostic observations for findings passing the 3-condition test.
- Write `.runs/retrospective-result.json` with `skipped: false` and populated
  `process_compliance`, `agent_instruction_compliance` (non-empty array),
  `trace_fidelity` fields. **Degraded-evidence tolerance:** when specific
  agent traces are missing/malformed (often the cause of the hard gate), use
  sentinel entries so the array stays non-empty:
  ```json
  {"agent": "<name>", "compliant": "unknown", "finding": null, "root_cause": "trace-unavailable"}
  ```
  This keeps Step 5a observable even when traces themselves are the defect.

When scope is `code` or `audit-only`, retrospective is skipped per the Step 5a
scope gate above (not overridden by hard_gate_failure).

- Proceed to Step 5b after writing the full retrospective artifact.

#### Programmatic candidate enumeration (#1276 hard-block)

> **Why this exists:** prior fixes #1066/#1226/#1258/#1270 attempted to enforce
> retrospective filing via prose, schema fields, and WARN logs — all bypassed
> by lead self-judgment under turn-budget pressure. This step replaces lead
> self-judgment of "what to file" with programmatic candidate generation
> (lead retains semantic judgment per candidate but cannot silently drop them).

Before writing the retrospective, run:

```bash
python3 .claude/scripts/enumerate-pending-retrospective-findings.py
```

This writes `.runs/retrospective-pending-findings.json` containing all
candidates derivable from runtime evidence (hook-friction-summary.json,
fix-ledger.jsonl template-edit rows, template-coherence-cache.json findings,
agent traces with recovery_validated, agent-trace `workarounds[]` and
`template_gap_observed[]` entries (GECR #1470), and verify-recheck.json
failed states (GECR #1470)). Each candidate has a stable `candidate_id`
(12-char hash of kind+key) used for disposition tracking.

GECR candidate kinds (#1470 — Gate Evidence Cross-Reference Protocol):

- **`agent-workaround`** — non-empty `workarounds[]` or `template_gap_observed[]`
  in any `.runs/agent-traces/*.json`. Per AOC v1.3 (`#1449`), every trace-
  writing agent emits these arrays; before #1470 they were inert because the
  enumerator never consumed them. Entries with explicit
  `root_cause_unresolved: false` are skipped (agent self-marked as
  in-PR-resolved). Dedup key collapses paraphrased descriptions across agents
  touching the same `(file, line, type)` location. Confidence: `high` when
  `root_cause_unresolved: true` was explicit; `low` when absent (defensive
  default — surface for lead triage).
- **`verify-failure`** — each `verify_results[].passed == false` row in
  `.runs/verify-recheck.json`. Per-check granularity (one candidate per failed
  state, NOT one aggregate). Dedup key uses `(state, hash(error))` so:
    - A failure that persists across reruns collapses to the same candidate
    - A transient flake (rerun passes) does NOT propagate

Both new kinds honor the same suppression mechanism as existing kinds: file
via `file-retrospective-finding.py` OR suppress via
`.runs/retrospective-result.json` `suppressions[]` with closed-enum reason
(see below).

For EACH candidate, the lead chooses one of:
  (a) **File**: invoke `python3 .claude/scripts/file-retrospective-finding.py
      --candidate-id <id> --title "<title>" --body "<body>"` — this is the
      sole sanctioned writer for [observe] issues from retrospective context.
      Idempotent + dedup-aware.
  (b) **Suppress**: add an entry to retrospective-result.json:
      ```json
      "suppressions": [
        {"candidate_id": "<id>", "reason": "<enum>", "justification": "<why>"}
      ]
      ```
      Suppression `reason` is a **closed enum** (round-2 critic Concern 3):
      - `not-template-rooted` — symptom is project-specific, not in template
      - `env-issue-out-of-scope` — env failure (CLI absent, network, etc.)
      - `duplicate-of-#NNNN` — same as already-open issue NNNN
      - `already-tracked-in-#NNNN` — covered by tracking issue NNNN
      - `defer-with-followup-#NNNN` — real finding, deferred under tracking issue NNNN

After writing retrospective-result.json, the completeness gate runs:

```bash
python3 .claude/scripts/validate-retrospective-completeness.py
```

It is invoked from `.claude/scripts/check-observation-artifacts.sh` (state-99
Step 2a, AFTER this Step 5a completes). Every pending candidate must have
either a filed entry in `.runs/retrospective-filed-findings.json` OR a valid
suppression. Missing disposition flips `observation-enforcement.json.pass=false`
in deny mode, blocking state-99 advancement; warn mode logs only during
rollout. This fenced reference makes observation-phase.md a second
integration_point for the validator (per `hard-block-validators-integration-required`
with `minimum_integration_count: 2`, #1307).

#### Write result
<!-- sanctioned-manual-write: .runs/retrospective-result.json -->

The lead writes `.runs/retrospective-result.json` DIRECTLY via the Write tool
(NOT as a deliverable to a spawned Agent). The required top-level field
`step_5a_executor` must be `"lead"` — enforced by `retrospective-content-gate.sh`
and post-validated by `compliance-audit.py`.

```json
{
  "step_5a_executor": "lead",
  "schema_version": 2,
  "process_compliance": "<summary or 'clean'>",
  "agent_instruction_compliance": [
    {"agent": "<name>", "executor": "agent", "compliant": true, "finding": null, "root_cause": "n-a"}
  ],
  "trace_fidelity": "<summary or 'clean'>",
  "observations_filed": 0,
  "suppressions": [],
  "skipped": false
}
```

The per-agent `executor` field (inside `agent_instruction_compliance` list)
records who executed each agent's procedure: `"agent"` for spawned agents,
`"lead"` for procedures the lead executed inline. The top-level
`step_5a_executor` records who answered Q1/Q2/Q3 — must be `"lead"` per the
inclusion criterion in `lead-only-artifacts.json`.

The `suppressions[]` field (added in schema v2) records explicit dispositions
for candidates from `retrospective-pending-findings.json` that the lead chose
NOT to file. See "Programmatic candidate enumeration" above.

### Step 5b-coherence: Cross-File Coherence Findings

**Activates:** when `.runs/template-coherence-cache.json` exists (written by
`lifecycle-finalize.sh` Step 4.5) AND contains non-empty findings.

**Skip when:** cache absent (no template files changed since last run) OR all
finding categories are empty.

The cache contains static cross-file analysis from `verify-linter.sh`,
including the `cross_file_contradiction` category populated by rules in
`.claude/patterns/template-coherence-rules.json` (e.g., `field_role_map`,
`artifact_lifecycle`). These findings catch defects #931 / #1024 (template
file A says X, template file B says ¬X) that runtime artifacts cannot
surface.

```bash
python3 - <<'PYEOF'
import json, os
cache = '.runs/template-coherence-cache.json'
if not os.path.isfile(cache):
    print('NO_COHERENCE_CACHE')
else:
    d = json.load(open(cache))
    findings = d.get('cross_file_contradiction', [])
    if findings:
        print(f'COHERENCE_FINDINGS={len(findings)}')
        for f in findings:
            print(f'  {f}')
    else:
        print('COHERENCE_CLEAN')
PYEOF
```

**For each finding** that emerges from this step, apply the standard
3-condition test from `.claude/patterns/observe.md`:
- **A.** Template file is root cause (yes — coherence rules only fire on `.claude/` files)
- **B.** Not an environment issue (yes — static analysis, no runtime dependency)
- **C.** Not a user code issue (yes — operates only on template files)

All cross-file contradictions trivially satisfy A/B/C. Apply the standard
**Redaction** and **Dedup** procedures from observe.md, then file qualifying
findings via the observer agent in Step 6 (Unified Filing).

**Counted in `observe-result.json`:** each filed finding increments
`observations_filed`.

### Step 5b: Deterministic Compliance Audit

**Activates:** Always (all scopes).

Run cross-artifact consistency checks:
```bash
_ACTIVE_CTX=$(python3 -c "
# #1268: pick the active skill context.
#  1. Exclude epilogue-context.json (always a derived artifact, not a skill).
#  2. Among remaining contexts, partition into non-completed vs completed.
#  3. Sort each partition by mtime descending (most-recently-touched first).
#  4. Prefer the newest non-completed; fall back to newest completed.
#  5. Staleness floor: if newest non-completed is older than newest completed
#     by more than 60 minutes, prefer the completed (defends against stale
#     crashed contexts being treated as active vs a fresh completed sibling).
#  6. Print 'skill\trun_id' so two values can be parsed in one subprocess call
#     (avoids two separate filter-rewrites drifting out of sync).
import json, glob, os, sys
candidates = []
for f in glob.glob('.runs/*-context.json'):
    if os.path.basename(f) == 'epilogue-context.json':
        continue
    try:
        ctx = json.load(open(f))
    except Exception:
        continue
    try:
        mtime = os.path.getmtime(f)
    except OSError:
        continue
    candidates.append((f, mtime, bool(ctx.get('completed', False)), ctx))
non_completed = sorted([c for c in candidates if not c[2]], key=lambda x: x[1], reverse=True)
completed     = sorted([c for c in candidates if c[2]],     key=lambda x: x[1], reverse=True)
chosen = None
if non_completed:
    chosen = non_completed[0]
    if completed and completed[0][1] - chosen[1] > 3600:
        chosen = completed[0]
elif completed:
    chosen = completed[0]
if chosen is None:
    print('unknown\t')
else:
    ctx = chosen[3]
    print((ctx.get('skill') or 'unknown') + '\t' + (ctx.get('run_id') or ''))
" 2>/dev/null || echo "unknown\t")
SKILL="${_ACTIVE_CTX%%$'\t'*}"
RUN_ID="${_ACTIVE_CTX#*$'\t'}"
python3 .claude/scripts/compliance-audit.py --skill "$SKILL" --run-id "$RUN_ID"
```

Read `.runs/compliance-audit-result.json`. Record `anomaly_count`.

### Step 5c: Adaptive LLM Audit

<!-- prose-gate:observation-phase-step5c-anomaly-audit -->

**Runs unconditionally.** Phase A (prose-gate `observation-phase-step5c-anomaly-audit`):
`audit-sample.py` is invoked every time observation-phase runs, regardless of
anomaly count or Q-score. The script writes `.runs/audit-sample-result.json`
unconditionally — the `triggered` field records whether a deep LLM audit
should follow. `anomaly-audit-evidence.py` is invoked at state-99 epilogue to
validate the artifact exists and is well-formed (see step 5c-validate below).

```bash
Q_SCORE=$(python3 -c "
import json
try:
    with open('.runs/verify-history.jsonl') as f:
        lines = f.readlines()
    last = json.loads(lines[-1]) if lines else {}
    print(last.get('q_skill', 1.0))
except: print('1.0')
" 2>/dev/null || echo "1.0")
ANOMALIES=$(python3 -c "import json;print(json.load(open('.runs/compliance-audit-result.json')).get('anomaly_count',0))" 2>/dev/null || echo "0")
python3 .claude/scripts/audit-sample.py --anomaly-count "$ANOMALIES" --q-score "$Q_SCORE" --run-id "$RUN_ID"
```

Read the JSON output from stdout (the same payload is also written to
`.runs/audit-sample-result.json`). If `trigger` is `true`:
- Perform **inline** comparison-based evaluation (do NOT spawn a subagent):
- For each failing check in `compliance-audit-result.json`:
  1. Read the spec (state-registry.json section)
  2. Read the artifact (trace/challenge file)
  3. Compare spec vs artifact
  4. Classify root cause: template-spec-deficiency vs execution-omission vs
     expected-edge-case
  5. For template-spec-deficiency: apply 3-condition test to determine filing

### Step 5c-validate: Anomaly-Audit Evidence Gate

```bash
python3 .claude/scripts/lib/anomaly-audit-evidence.py
```

The validator asserts `.runs/audit-sample-result.json` exists and carries
`{triggered, audit_outcome, anomaly_count_observed}`. When `triggered==true`,
`audit_outcome` must be non-empty. Failure logs to `.runs/lead-deviation-log.jsonl`
with `gate_layer:prose-gates-v1` (warn mode in Phase A; deny in Phase C).

## Step 6: Action — Unified Filing

> REF: This step implements the decision framework, redaction, dedup, and
> issue filing defined in `.claude/patterns/observe.md`.

For any findings from Steps 4 and 5 that qualify as template observations,
follow the unified procedure:

### 3-Condition Test (from observe.md)

**A. Template file is root cause.** The fix required changing — or would ideally
change — a file in the template file list.

**B. Not an environment issue.** NOT caused by: missing CLI tools, network
failures, Node version mismatches, missing env vars, or auth failures.

**C. Not a user code issue.** NOT caused by: business logic bugs, project-specific
dependency conflicts, or code that doesn't follow template guidance.

**Heuristic:** "Would another developer using this template with a different
experiment.yaml hit this same problem?" If yes → file it.

### Redaction

- Replace project name with `<project>`
- Replace experiment.yaml content with `<redacted>`
- Replace full stack traces with error message only
- Replace project-specific paths with generic paths
- Keep: template file name, generic symptom, fix diff (template-relevant only)

### Dedup

```bash
TEMPLATE_REPO="magpiexyz-lab/mvp-template"
gh issue list --repo $TEMPLATE_REPO --label observation \
  --search "[observe] <template-file-basename>:" --state open --limit 20
```

If duplicate found: comment instead of creating new issue.

### Issue Filing

Title: `[observe] <template-file-basename>: <symptom-in-imperative-form>`

Follow observe.md "Issue Creation" section for body format, file version
metadata, and error handling.

## Step 7: Write Final Results

Write `.runs/observe-result.json`:
```json
{
  "skill": "<skill-name>",
  "timestamp": "<ISO 8601>",
  "friction_detected": true,
  "observations_filed": <N>,
  "verdict": "filed" | "no-template-issues"
}
```

**Strategy field mapping** (for lib-verdict-consistency.sh compatibility):
- scope = `full` or `code` → do NOT set `"strategy"` field (observer should
  have run; lib-verdict-consistency.sh treats absent strategy as code observation)
- scope = `process` or `audit-only` → set `"strategy": "execution-audit"`

Verdict values:
- `"filed"` — observer or lead created/commented on GitHub issues
- `"no-template-issues"` — evaluated but found no template-rooted issues
- `"error"` — observation was attempted but failed (observer spawn failure
  after retry, inline evaluation failure, or other unrecoverable error).
  Includes `"error_reason"` field. Blocked by commit gate — re-run the skill
  to retry. Note: if evaluation completed successfully but only GitHub filing
  failed, use the evaluation's natural verdict (`"no-template-issues"` or
  `"filed"`), not `"error"`.

## Constraints

- **Mandatory execution, graceful degradation.** Observation evaluation must
  always be attempted. If a step fails, retry once. If it still fails, write
  `observe-result.json` with `"verdict": "error"` and `"error_reason"` — do
  NOT silently write `"clean"`. External service failures (GitHub API, template
  repo access) degrade filing to local logging but do not skip the evaluation.
  The commit gate blocks on `"error"` — re-run the skill to retry.
- **Max 1 observer spawn.** Combine all evidence into a single evaluation.
- **Max 1 issue per session.** Multiple fixes → combine into one issue.
- **No project-specific data in observer prompt.** Follow observe.md redaction.
- **Idempotency.** Step 1 prevents double-observation across mechanisms.
