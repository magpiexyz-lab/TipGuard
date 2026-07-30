# STATE 10: POST_FIX_REVIEW

**PRECONDITIONS:**
- External stack graduation complete (STATE 9a POSTCONDITIONS met)

**ACTIONS:**

Review all implemented fixes against original issues to catch implementation gaps
that validators cannot detect (wrong conditions, partial fixes, missed files in blast radius).

### Step 1 — Gather review inputs

Collect the context the reviewer needs:

```bash
# Actual code changes
git diff main...HEAD

# Original issues, root causes, designed fixes
cat .runs/resolve-context.json

# Adversarial challenge results from STATE 5d
cat .runs/resolve-challenge.json

# Validator results from STATE 8
cat .runs/resolve-validation.json
```

Build a per-issue summary for the reviewer prompt:
- Issue number and title
- Root cause (from `resolve-context.json`)
- Designed fix plan (from `solve-trace.json`)
- Blast radius files (from `resolve-context.json`)
- The subset of the git diff that touches files related to this issue

### Step 2 — Spawn review agent

Spawn the `resolve-reviewer` Named agent (`subagent_type: resolve-reviewer`).

This is a first-class agent with implementation-review vectors. The agent is registered
in `.claude/skills/resolve/skill.yaml` `agents:` block and in
`agent-registry.json` (verdict_agents, verdict_agents_schema, non_fixer_agents,
hard_gates with `allow_predicates: [pass_clean, pass_self_pass_or_fail,
validated_fallback, legacy_pass_no_recovery]`).

Prior to AOC v1.1 PR4 (closes #1055), this state used an alias pattern: spawned via
`subagent_type: resolve-challenger` with a `init-trace.py resolve-reviewer` filename
override. That alias drifted with `skill-agent-gate.sh` (spawn-log recorded
`resolve-challenger`, trace written as `resolve-reviewer.json`) and `agent-trace-write-guard.sh`
refused completion writes — leaving the trace as a stub. The first-class promotion
eliminates that drift entirely.

Include in the agent prompt:
- The full `git diff main...HEAD` output
- The per-issue summary from Step 1
- Explicit instruction: "You are reviewing IMPLEMENTATION correctness, not design correctness.
  The design was already approved in STATE 5d. Your job is to verify the code changes
  faithfully and completely implement the approved design."
- The resolve-reviewer agent's procedure file at `.claude/agents/resolve-reviewer.md`
  contains the canonical First Action and trace-write template.

**Three review vectors** (defined in the agent definition; pass them as part of the prompt
context):

1. **Completeness**: Does the diff fully address the root cause? Are there files in the
   blast radius that should have been modified but weren't? Is the fix applied to all
   instances of the pattern, or only some?

2. **Correctness**: Does the code change match the designed fix? Look for subtle errors:
   wrong condition logic, partial pattern replacement, mismatched variable names,
   off-by-one in repeated patterns, copy-paste artifacts.

3. **Consistency**: When the same fix applies to multiple files, is it applied identically
   (modulo file-specific differences)? Are there inconsistencies between how different
   issues' fixes interact?

4. **RMG v2 guard-presence** (when `prevention_analysis.problem_type=defect`):
   For each fix's `recurrence_guard` with `kind in {test, lint, hook, invariant}`,
   confirm the `artifact` path is touched in the PR diff (`git diff main...HEAD
   --name-only`). For `kind=none`, confirm `unguardability_rationale` is present
   and substantive. The reviewer cross-checks against
   `.claude/scripts/verify-rmg-guard-artifact-in-diff.py`; if the helper exits
   non-zero, the reviewer surfaces the gap as a `needs-revision` verdict for
   the matching issue. The same helper runs as a hard gate at
   `lifecycle-finalize.sh` Step 4.6, so a failure here is also a delivery
   blocker — STATE 10 makes the gap visible to the user instead of letting
   delivery break silently.

The agent writes its trace to `.runs/agent-traces/resolve-reviewer.json` via the AOC v1.1
centralized writer. Trace shape:

```json
{
    "agent": "resolve-reviewer",
    "timestamp": "<ISO 8601>",
    "verdict": "pass",
    "result": "count_summary",
    "checks_performed": ["completeness", "correctness", "consistency"],
    "confirmed_count": <N>,
    "disputed_count": <M>,
    "verdicts": [
        {
            "issue": "<N>",
            "label": "<sound|needs-revision|challenged>",
            "vector": "<completeness|correctness|consistency>",
            "gap": "<description of gap found, or empty>",
            "evidence": "<file:line or diff excerpt>",
            "revision": "<specific change or null>"
        }
    ],
    "run_id": "<from resolve-context.json>"
}
```

### Step 3 — Process review results

Read `.runs/agent-traces/resolve-reviewer.json`.

For each verdict:
- **sound** → no action needed
- **needs-revision** → fix the identified gap (apply the minimal change), then re-run
  all 3 validators to confirm no regressions. Maximum 2 revision rounds total across
  all issues. If round 2 still produces needs-revision verdicts, escalate to challenged.
- **challenged** → do not attempt to fix; present to user at STOP gate

### Step 4 — Re-validate if fixes were made

If any fixes were applied in Step 3:

1. Re-run all 3 validators
2. Compare error counts against `.runs/resolve-validation.json` (STATE 8 baseline)
3. If error count increased (regression): revert the Step 3 fix with
   `git checkout -- <modified files>`, reclassify as "challenged" for user review

### Step 5 — Write review artifact

- **Write review artifact** (`.runs/resolve-review.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  review = {
      'reviewed_count': 0,
      'sound_count': 0,
      'revised_count': 0,
      'challenged_count': 0,
      'revision_rounds': 0,
      'verdicts': [
          {
              'issue': 0,
              'label': '<sound|needs-revision|challenged>',
              'gap': '<description or empty>',
              'evidence': '<file:line or empty>',
              'revision': '<what was fixed, or null>'
          }
      ]
  }
  print(json.dumps(review))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-review.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

If `challenged_count > 0`:

**STOP. Present challenged items to the user:**

```
## Post-Fix Review: Challenged Items

| Issue | Gap | Evidence | Recommendation |
|-------|-----|----------|----------------|
| #N    | <gap description> | <file:line> | <what the reviewer suggests> |

These items require your judgment. Approve to proceed, or provide guidance to fix.
```

Wait for user approval before proceeding.

**POSTCONDITIONS:**
- All implemented fixes reviewed against original issues (completeness, correctness, consistency)
- Revision fixes (if any) pass all 3 validators with no regressions
- `.runs/resolve-review.json` exists with `reviewed_count > 0`
- No unresolved challenged items (user has approved any challenged items)

<!-- VERIFY=registry: resolve-review.json artifact validation -->
**VERIFY:**
```bash
python3 -c "import json,os; d=json.load(open('.runs/resolve-review.json')); assert d.get('reviewed_count',0)>0, 'reviewed_count missing'; assert d.get('challenged_count',0)==0, 'unresolved challenged items'; trace_path='.runs/agent-traces/resolve-reviewer.json'; assert os.path.exists(trace_path), 'resolve-reviewer trace missing (PR4 — closes #1055 alias drift)'; t=json.load(open(trace_path)); assert t.get('status') != 'started' and 'verdict' in t, 'resolve-reviewer trace is a stub (no verdict) — alias drift may have re-emerged'" && python3 .claude/scripts/verify-rmg-guard-artifact-in-diff.py --trace .runs/solve-trace.json --merge-base "$(git merge-base origin/main HEAD 2>/dev/null || echo main)"  # .runs/solve-trace.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 10
```

**NEXT:** Read [state-11-commit-pr.md](state-11-commit-pr.md) to continue.
