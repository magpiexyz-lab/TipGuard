# STATE 3b: CAUSAL_ANALYSIS

**PRECONDITIONS:**
- Reproduction complete (STATE 3 POSTCONDITIONS met)
- `.runs/resolve-reproduction.json` exists with at least one divergence point

**ACTIONS:**

This state inspects recent git history at each divergence_point to detect
oscillation (repeated flip-back fixes) and anti-pattern matches before any
code is touched. It never halts automatically — when the evidence warrants a
halt it presents the user with three options and waits for the user's reply.

### Step 1 — Run the headless analyzer

The analyzer reads `.runs/resolve-reproduction.json`, checks each divergence
point against git history and `anti_pattern: true` entries in every Stack
Knowledge surface enumerated by `scripts/lib/stack_knowledge_parser.iter_stack_knowledge_files()`
(currently `.claude/stacks/**/*.md` plus `.claude/scripts/lib/README.md`),
and writes `.runs/resolve-causal-analysis.json`.
A 30-second wall-clock timeout (from `convergence-config.json`) protects
against slow `git log -L` calls.

Per divergence point, the analyzer performs four checks:

1. **Time-trace** — `git log -L <line>,<line>:<file>` enumerates the most
   recent commits that touched the exact line range. Each commit's message
   is regex-scanned for `#<num>` issue references; `gh pr view <num>` reads
   labels so the analyzer can distinguish /resolve-authored fixes (label
   `resolve`) from ordinary edits.
2. **Reversal detection** — whitespace-normalized diff comparison between
   the most recent /resolve fix at this location and the currently proposed
   change direction. When the "delete" set of the prior fix matches the
   "add" set of the proposed fix (and vice versa), `reversal_detected=true`.
3. **Oscillation counting** — the number of reversal pairs within a 90-day
   sliding window becomes `oscillation_count`. `oscillation_count >= 2`
   triggers `halt_required=true`.
4. **Anti-pattern match** — the current fix's composite identity is looked
   up against every `anti_pattern: true` entry in the matching stack file's
   Stack Knowledge section. A match also sets `halt_required=true`.

```bash
python3 .claude/scripts/resolve-causal-analyzer.py
```

On shallow clones or empty history at the target line the artifact is
written with `causal_unavailable: true` and analysis proceeds as a no-op
(halt is impossible without history).

### Step 2 — Read the artifact

```bash
python3 -c "
import json
a = json.load(open('.runs/resolve-causal-analysis.json'))
print('halt_required:', a['halt_required'])
print('causal_unavailable:', a['causal_unavailable'])
for dp in a['divergence_points_analyzed']:
    print('  ', dp['divergence_point'], 'oscillation=', dp['oscillation_count'], 'anti=', dp['anti_pattern_match'])
"
```

### Step 3 — Branch on halt_required

**If `causal_unavailable == true` OR `halt_required == false`:**
advance to STATE 4.

**If `halt_required == true`:** STOP. Present the diagnosis and wait for the
user's reply (1, 2, or 3). Format the diagnosis exactly like this, filling in
evidence from the artifact (one block per divergence point that triggered
the halt):

```
⚠️  OSCILLATION / ANTI-PATTERN DETECTED

Location: <file:line>
Evidence:
  - Flip count (last 90d): <oscillation_count>
  - Last reverting commit: <touching_commits[0].hash> (#<issue>, <date>)
  - Recent touching commits: <list of top 3 hashes + subjects>
  - Anti-pattern match: <anti_pattern_match.id or null>

Options:
  (1) Escalate to /solve — file architecture issue, halt this /resolve run
  (2) Override with justification — log reason, proceed to STATE 4
  (3) Abort — exit /resolve

Type 1/2/3:
```

### Step 4 — Handle user's reply

**Reply `1` (Escalate):**

1. File a single escalation issue on the template repo and capture the URL
   so STATE 11's defensive duplicate-filer short-circuits correctly:
   ```bash
   ESCALATION_URL=$(gh issue create --repo magpiexyz-lab/mvp-template \
     --label oscillation-escalation \
     --title "[escalation] /resolve halted: oscillation at <file:line>" \
     --body "<evidence block + linked prior commits + run_id from resolve-context.json>" 2>/dev/null || true)
   PAYLOAD=$(ESCALATION_URL_ENV="$ESCALATION_URL" python3 -c "
   import json, os
   url = os.environ['ESCALATION_URL_ENV'].strip()
   a = json.load(open('.runs/resolve-causal-analysis.json'))
   a['escalation_issue_url'] = url
   a['gh_failed'] = (url == '')
   print(json.dumps(a))
   ")
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/resolve-causal-analysis.json \
     --payload "$PAYLOAD" \
     --skill resolve
   ```
   `gh` auto-creates the `oscillation-escalation` label on first use. On
   `gh` failure the artifact records `gh_failed=true` and an empty URL;
   STATE 11 will file a defensive issue when it sees an empty URL.

2. Mark skip states in `.runs/resolve-context.json`:
   ```bash
   PAYLOAD=$(python3 -c "
   import json
   ctx = json.load(open('.runs/resolve-context.json'))
   ctx['skip_states'] = ['4','4b','5','5d','6','7','8','8b','9','9a','10']
   ctx['halted_at'] = '3b'
   print(json.dumps(ctx))
   ")
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/resolve-context.json \
     --payload "$PAYLOAD" \
     --skill resolve
   ```

3. Write `.runs/delivery-skip.flag` so STATE 11 and `lifecycle-finalize.sh`
   bypass PR creation:
   ```bash
   printf 'halted:oscillation-or-antipattern\n' > .runs/delivery-skip.flag
   ```

4. Mark the causal-analysis artifact as halted (the URL was already written
   in Step 1):
   ```bash
   PAYLOAD=$(python3 -c "
   import json
   a = json.load(open('.runs/resolve-causal-analysis.json'))
   a['halted'] = True
   print(json.dumps(a))
   ")
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/resolve-causal-analysis.json \
     --payload "$PAYLOAD" \
     --skill resolve
   ```

5. Advance STATE 3b — `lifecycle-next.sh` will jump to STATE 11 via
   `skip_states`.

**Reply `2` (Override):**

1. Prompt the user for a one-line justification ("Please justify the
   override — one sentence on why this fix will converge:"). Wait for the
   user's reply.

2. Log the justification to both the artifact and context:
   ```bash
   REASON="<user-supplied justification>"
   # Update resolve-causal-analysis.json
   PAYLOAD_A=$(REASON_ENV="$REASON" python3 -c "
   import json, os
   a = json.load(open('.runs/resolve-causal-analysis.json'))
   a['halt_override_reason'] = os.environ['REASON_ENV']
   print(json.dumps(a))
   ")
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/resolve-causal-analysis.json \
     --payload "$PAYLOAD_A" \
     --skill resolve
   # Update resolve-context.json
   PAYLOAD_B=$(REASON_ENV="$REASON" python3 -c "
   import json, os
   ctx = json.load(open('.runs/resolve-context.json'))
   ctx['halt_override_reason'] = os.environ['REASON_ENV']
   print(json.dumps(ctx))
   ")
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/resolve-context.json \
     --payload "$PAYLOAD_B" \
     --skill resolve
   ```

3. Advance to STATE 4 normally. Do NOT re-gate the override at STATE 7 —
   STATE 7's per-fix approval already covers per-fix control.

**Reply `3` (Abort):**

Exit `/resolve` immediately (non-zero). Do NOT write `delivery-skip.flag`,
do NOT set `skip_states`, do NOT file any issue. The user wants the run
discarded.

**POSTCONDITIONS:**
- `.runs/resolve-causal-analysis.json` exists with `analysis_complete: true`
  (or `halted: true` when the user escalated)
- On escalate: `.runs/delivery-skip.flag` exists and `ctx.skip_states`
  targets STATE 11
- On override: `halt_override_reason` populated in artifact and context
- `causal_unavailable: true` is accepted as a terminal state for this step
  (no halt possible without history)

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/resolve-causal-analysis.json')); assert d.get('analysis_complete')==True or d.get('halted')==True, 'analysis or halt not complete'; assert d.get('causal_unavailable')==True or isinstance(d.get('divergence_points_analyzed'), list), 'missing divergence_points_analyzed'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 3b
```

**NEXT:** Read [state-4-blast-radius.md](state-4-blast-radius.md) to continue. On escalate, `lifecycle-next.sh` jumps directly to [state-11-commit-pr.md](state-11-commit-pr.md) via `skip_states`.
