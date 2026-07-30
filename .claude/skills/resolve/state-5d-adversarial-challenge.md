# STATE 5d: ADVERSARIAL_CHALLENGE

**PRECONDITIONS:**
- Fix design complete (STATE 5 POSTCONDITIONS met)

**ACTIONS:**

The adversarial challenge adapts based on `solve_depth`.

#### Learned-pattern vector (optional)

Before spawning the challenger/critic, check `.runs/resolve-triage.json.pattern_hints`.
If non-empty, include a `Learned Patterns` block in the agent prompt listing
each hint's `id`, `maturity`, `occurrence_count`, and `root_cause_class`. The
challenger uses these as an extra challenge vector: "pattern &lt;id&gt; has recurred
&lt;occurrence_count&gt; times — does the proposed fix target its stated
`root_cause_class` or merely its `symptom_keywords`?". When `pattern_hints` is
empty (the common case when Stack Knowledge has no matches), skip this block.

#### Light mode adversarial challenge

Spawn the `resolve-challenger` Named agent (`subagent_type: resolve-challenger`).

Pass in the agent prompt: all fix plans from Step 5 (root cause, fix plan,
blast radius, prevention_analysis), plus the Learned Patterns block above when
present. The agent definition at `.claude/agents/resolve-challenger.md` contains
the full challenge protocol (3 vectors: configuration counterexample, blast
radius gap, regression vector).

After the agent returns:
1. Read the agent's trace at `.runs/agent-traces/resolve-challenger.json`
2. For each fix, transcribe the trace's `verdicts[i].label` to `agent_label`
3. Set `final_label = agent_label` by default
4. If overriding (setting a different `final_label`), provide `override_reason`

Label handling:
- **sound**: proceed as designed
- **needs-revision**: incorporate revision, note in diagnosis report
- **challenged**: present to user at STOP gate; let user decide

When any `agent_label != final_label`, the STOP gate must display both labels,
the override reason, and the raw agent output so the user can see the override.

#### Full mode adversarial challenge

Spawn the `solve-critic` Named agent (`subagent_type: solve-critic`).
Pass `--context .runs/resolve-context.json` and `problem_type = "defect"` in the
agent prompt. Include the 3 domain-specific challenge vectors (configuration
counterexample, blast radius gap, regression vector) plus the Learned Patterns
block from above (when `pattern_hints` non-empty) as additional instructions in
the critic prompt.

The solve-critic writes its trace to `.runs/agent-traces/solve-critic.json`.
If round 2 is needed (TYPE A count > 0):

1. **Archive the round-1 trace** via the canonical writer (sidecar path is
   outside `.runs/agent-traces/` so trace-write-guard does not block it;
   registered in `.claude/patterns/gate-readable-artifacts-canonical.json`):
   ```bash
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/solve-critic-round1.json \
     --payload "$(cat .runs/agent-traces/solve-critic.json)" \
     --skill resolve
   ```
   The archive remains as the audit-trail source for vector 5
   (`within-run-round1-concern-unaddressed`). `lifecycle-init.sh` wipes
   `.runs/solve-critic-round1.json` on each new skill run so a stale archive
   cannot satisfy the runtime postcondition in `verify-resolve-challenge.py`
   for a future run.

2. **Re-spawn solve-critic** with round 2 instructions. The round-2 spawn
   prompt MUST include `round_1_concerns` (the full `concerns[]` array from
   the archived round-1 trace, with stable `concern_id` values) under a
   `## Round 1 Concerns to Cross-Check` header — see
   `.claude/agents/solve-critic.md` "Round 2 Prompt Contract".

The agent overwrites the live trace at `.runs/agent-traces/solve-critic.json`
with `round: 2` and updated counts; the round-1 archive is preserved.

Critic output mapping to report sections:
- **TYPE A round 1** -> revision to `fix_plan` (already applied)
- **TYPE A round 2** (unresolved) -> caveats in diagnosis report
- **TYPE B** -> system constraints in diagnosis report
- **TYPE C** -> merged into STOP gate questions (see below)

**Full mode `agent_label` derivation** (per fix):
- No TYPE A/B concerns targeting this fix -> `agent_label = "sound"`
- TYPE A concerns targeting this fix, all resolved by round 2 -> `agent_label = "needs-revision"`
- Unresolved TYPE A or any TYPE B targeting this fix -> `agent_label = "challenged"`
- Only TYPE C targeting this fix -> `agent_label = "sound"` (TYPE C defers to user, does not dispute the fix)

Present a diagnosis report for all actionable issues:

```
## Issue #N: <title>

**Root cause:** <1-2 sentences>
**Divergence point:** <file:line>
**Reproduction:** <cite | grep | exec | validator-fed> + evidence: <one-line summary>  (legacy `validator-confirmed`/`simulation-only` accepted with deprecation warning during one release cycle)
**Blast radius:** N files affected (M confirmed, K potential)
**Fix plan:**
- <file>: <what changes>
**Proposed validator check:** <name> in <script> | none
**Prevention:** root cause [addressed/not] | recurrence [none/guarded/unguarded] | scope [N instances, all covered]
**Adversarial check:** sound | revised (<what changed>) | challenged (<summary>)
```

**Full mode STOP augmentation**: If `solve_depth = "full"` for any issue, append
to the diagnosis report before presenting:

```
### Open Questions
[Phase 5 TYPE C concerns — assumptions only the user can validate]

### System Constraints
[Phase 5 TYPE B items — immutable constraints the fix must work around, or "None"]
```

**STOP. Present the diagnosis report to the user and wait for approval before
proceeding to Phase 3.** The user may adjust fix plans or scope.

- **Write challenge artifact** (`.runs/resolve-challenge.json`):
  ```bash
  python3 -c "
  import json
  challenge = {
      'challenges': [
          {
              'issue': 0,
              'agent_label': '<label from adversarial trace verdicts[i].label>',
              'final_label': '<sound|challenged|needs-revision>',
              'override_reason': '<if agent_label != final_label, explain why; empty string if labels match>',
              'challenge': '<what was tried>',
              'evidence': '<file:line or fixture>',
              'revision': '<if not sound>'
          }
      ],
      'critic_rounds': 0,           # 1 or 2 — actual rounds executed (see solve-reasoning.md)
      'round_1_type_a_count': 0,    # TYPE A concerns from round 1
      'round_2_type_a_count': 0     # TYPE A concerns from round 2 (always emit; 0 when critic_rounds <= 1) — required by state-registry.json challenge_fields.when_rounds_gt_1
  }
  json.dump(challenge, open('.runs/resolve-challenge.json', 'w'), indent=2)
  "
  ```

**POSTCONDITIONS:**
- Diagnosis report presented to user for all actionable issues
- Adversarial challenge completed for each fix
- User has approved the diagnosis before proceeding
- `.runs/resolve-challenge.json` exists

**VERIFY:**
```bash
python3 .claude/scripts/verify-resolve-challenge.py  # resolve-challenge.json, resolve-challenger.json, solve-critic.json
```

**Ring 3 skip:** If `resolve-context.json` has `"ring": 3`, write `skip_states` before advancing:
```bash
SHOULD_WRITE=$(python3 -c "import json; ctx=json.load(open('.runs/resolve-context.json')); print('yes' if ctx.get('ring') == 3 else 'no')")
if [ "$SHOULD_WRITE" = "yes" ]; then
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/resolve-context.json'))
  ctx['skip_states'] = ['6','7','8','8b','9','9a','10']
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-context.json \
    --payload "$PAYLOAD" \
    --skill resolve
fi
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 5d
```

**NEXT:** If `resolve-context.json` has `"ring": 3`, skip to [state-11-commit-pr.md](state-11-commit-pr.md). Otherwise, read [state-6-branch-setup.md](state-6-branch-setup.md) to continue.
