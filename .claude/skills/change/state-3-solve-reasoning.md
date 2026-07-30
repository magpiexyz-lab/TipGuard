# STATE 3: SOLVE_REASONING

**PRECONDITIONS:**
- Context read (STATE 2 POSTCONDITIONS met)
- Preliminary classification determined from `$ARGUMENTS` keywords

**ACTIONS:**

Before classifying the change, run a structured solution design pass using
`.claude/patterns/solve-reasoning.md` with adaptive depth.

### Complexity assessment

Determine solve-reasoning depth using the preliminary classification from Step 2:

```
solve_depth = "light"  # default
if preliminary_type in [Feature, Upgrade] AND affected_areas >= 3:
    solve_depth = "full"
if $ARGUMENTS contains "--light":
    solve_depth = "light"  # user override
if $ARGUMENTS contains "--full":
    solve_depth = "full"   # user override
```

**Persist solve_depth** to `change-context.json`:
```bash
PAYLOAD=$(python3 -c "
import json
ctx = json.load(open('.runs/change-context.json'))
ctx['solve_depth'] = '<light|full>'  # result of the formula above
print(json.dumps(ctx))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/change-context.json \
  --payload "$PAYLOAD" \
  --skill change
```

State the depth selection with rationale. If the formula selects "full" but the affected
areas appear independent (no shared state, no shared imports), suggest to the user:
"3+ affected areas trigger full mode, but these areas look independent. Re-run with
`--light` if you want to skip deep analysis."

### Prevention activation

If `preliminary_type = "Fix"`: set `problem_type = "defect"` when calling solve-reasoning.
This activates the prevention dimension (root cause + recurrence + scope checks).

For all other preliminary_types: do not set `problem_type`.

### RMG v2 Phase 1a Dossier (when `preliminary_type = "Fix"`)

When `problem_type = "defect"` is set, solve-reasoning Phase 1a builds a Prior-Failure
Dossier via `.claude/scripts/lib/dossier_builder.py`. For `/change`, derive the
inputs from the change context:

- `divergence_files` = the union of `affected_files` from
  `.runs/exploration-trace.json` (Phase 2 plan-exploration output).
- `symptom_signature` = `canonicalize_symptom("$ARGUMENTS")` — i.e., the
  user's bug report. The canonicalizer at
  `.claude/scripts/lib/symptom_canonicalizer.py` collapses line/column
  positions, PR/issue numbers, ISO timestamps, absolute paths, and short
  SHAs so equivalent reports collide.

The dossier flows transparently into Phase 4b — the designer must emit a
`prior_failure_response[]` for every dossier entry citing a concrete delta
step or guard artifact absent from the prior commit (R2-A2).

### Step 0 — Build Prior-Failure Dossier (when `preliminary_type == "Fix"`; Issue #1415)

`state-registry.json` `change.3` VERIFY asserts `.runs/prior-failure-dossier.json`
exists when `preliminary_type=Fix`. Build before invoking Light/Full mode below:

```bash
PT=$(python3 -c "import json; print(json.load(open('.runs/change-context.json')).get('preliminary_type',''))")
if [ "$PT" = "Fix" ]; then
  # $ARGUMENTS is the canonical symptom source per "RMG v2 Phase 1a Dossier"
  # prose above. Pass via env var to avoid shell-quoting traps inside python -c.
  DOSSIER=$(CHANGE_ARGS="$ARGUMENTS" python3 -c "
import json, os, sys
sys.path.insert(0, '.claude/scripts/lib')
from dossier_builder import build_dossier
from symptom_canonicalizer import canonicalize_symptom
expl = json.load(open('.runs/exploration-trace.json'))
files = sorted(expl.get('affected_files', []))
symptom = canonicalize_symptom(os.environ.get('CHANGE_ARGS',''))
d = build_dossier(divergence_files=files, symptom_signature=symptom, project_dir='.')
print(json.dumps(d))
")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/prior-failure-dossier.json \
    --payload "$DOSSIER" \
    --skill change
fi
```

For non-Fix `preliminary_type`, the dossier is not built (Phase 1a is skipped —
see `solve-reasoning.md` "Caller conventions").

### Light mode path

CALL: `.claude/patterns/solve-reasoning.md` — execute light mode (Steps 1-5).

- **Inputs**: `$ARGUMENTS` as problem, exploration results from Step 2 as constraints
- **Output**: stored in working memory, feeds into plan "How" sections in Phase 1

### Full mode path

CALL: `.claude/patterns/solve-reasoning.md` — execute full mode (Phases 1-6).

- **Phase 1 agent customization**:
  - Agent 1 = change problem space (what needs to change, for whom, and why)
  - Agent 2 = reuse/prior art (extends plan-exploration — find existing patterns, components, utilities that partially solve this)
  - Agent 3 = hard constraints (archetype restrictions, stack limitations, behavior scope from experiment.yaml)
- **Phase 3 gap resolution**: autonomous — AI self-answers research gaps using first-principles reasoning
- **Phase 5 Critic**: reviews plan mechanism choices (no extra domain vectors)
- **Output feeds**:
  - "Recommended Solution" + "Implementation Checklist" -> plan "How" sections
  - "Remaining Risks" -> Risks & Mitigations section
  - "Alternatives" -> Approaches table (if multi-layer Feature)
  - "Constraint Space" -> informs Step 3 classification and Step 4 prerequisite checks

### Write solve trace artifact

After completing the solve-reasoning pass (light or full), write `.runs/solve-trace.json`:
```bash
PAYLOAD=$(python3 -c "
import json
trace = {
    'mode': '<light|full>',
    'problem_decomposition': '<What/Why/Constraints summary>',
    'constraint_enumeration': '<executor/mechanisms/hard/soft constraints>',
    'solution_design': '<chosen mechanisms and rationale>',
    'self_check': '<revision pass results>',
    'output': '<recommended solution summary>'
}
# Add prevention_analysis only when preliminary_type is Fix
if preliminary_type == 'Fix':
    trace['prevention_analysis'] = {
        'problem_type': 'defect',
        'root_cause_addressed': True,
        'recurrence_risk': '<none|guarded|unguarded>',
        # RMG v2 typed schema — see .claude/scripts/lib/recurrence_guard_parser.py.
        # None when recurrence_risk == 'none'; otherwise a dict:
        #   {"kind": "test|lint|hook|invariant|none",
        #    "artifact": "<path-or-rule-id>" | None,
        #    "rationale": "<≤200ch>",
        #    "unguardability_rationale": "<≥80ch, only when kind == 'none'>"}
        'recurrence_guard': None,
        'scope': {'all_covered': True, 'instance_count': 0},
        # Falsification Gate (required when problem_type=='defect', any kind).
        # Parsed by .claude/scripts/lib/recurrence_guard_parser.parse_falsification.
        # Schema: prediction / opposite_prediction / observable_signal each
        # ≥40 chars; strength in {high, low, untestable}; token-Jaccard
        # between prediction and opposite_prediction must be < 0.8.
        'falsification': {
            'prediction': '<≥40 chars: signal H predicts to observe>',
            'opposite_prediction': '<≥40 chars: signal ¬H would predict instead>',
            'observable_signal': '<≥40 chars: actual observation cited from evidence>',
            'strength': '<high|low|untestable>'
        }
    }
    # RMG v2 Phase C: Prior-Failure Response. One entry per Phase 1a dossier
    # entry; each cites a concrete delta absent from the prior commit (R2-A2).
    # Empty when dossier was empty.
    trace['prior_failure_response'] = []
print(json.dumps(trace))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/solve-trace.json \
  --payload "$PAYLOAD" \
  --skill change
```

### Write challenge artifact

After completing the solve-reasoning pass, write `.runs/change-challenge.json`:

If `solve_depth = "full"`:
```bash
python3 -c "
import json
challenge = {
    'critic_rounds': 0,           # 1 or 2 — actual rounds executed
    'round_1_type_a_count': 0,    # TYPE A concerns from round 1
    'round_2_type_a_count': 0,    # TYPE A concerns from round 2 (always emit; 0 when critic_rounds <= 1) — required by state-registry.json challenge_fields.when_rounds_gt_1
    'concerns': [
        # {'type': '<A|B|C>', 'description': '<text>'}
    ]
}
json.dump(challenge, open('.runs/change-challenge.json', 'w'), indent=2)
"
```

If `solve_depth = "light"` (no critic ran):
```bash
python3 -c "
import json
json.dump({'critic_rounds': 0, 'round_1_type_a_count': 0, 'round_2_type_a_count': 0, 'concerns': []}, open('.runs/change-challenge.json', 'w'), indent=2)
"
```

**POSTCONDITIONS:**
- `solve_depth` determined and stated with rationale
- `solve_depth` persisted to `.runs/change-context.json` and matches formula
- Solve-reasoning pass completed (light or full)
- Output stored in working memory for plan generation
- `.runs/solve-trace.json` exists with 5 required fields (`mode`, `problem_decomposition`, `constraint_enumeration`, `solution_design`, `self_check`, `output`)
- `.runs/change-challenge.json` exists with `critic_rounds`, `round_1_type_a_count`, `round_2_type_a_count`, `concerns`

**VERIFY:**
```bash
python3 .claude/scripts/verify-change-solve.py && python3 -c "import json; json.load(open('.runs/prior-failure-dossier.json'))"  # change-context.json, solve-trace.json, change-challenge.json, prior-failure-dossier.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 3
```

**NEXT:** Read [state-4-classify.md](state-4-classify.md) to continue.
