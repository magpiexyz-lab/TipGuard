# STATE 6: PRESENT_PLAN

**PRECONDITIONS:**
- Preconditions passed (STATE 5 POSTCONDITIONS met)
- Classification and verification scope determined
- Solve-reasoning output available in working memory

**ACTIONS:**

DO NOT write any code, create any files, or run any install commands during this phase (except validation artifacts below).

Present the plan using the template for the classified type (REF: `.claude/procedures/change-plans.md`). Populate "How" sections using exploration results from Step 2.

CALL: `.claude/procedures/plan-validation.md` — **validate the plan against the codebase**. Execute all 5 checks before presenting the plan to the user. If validation flags conflicts, adjust the plan or add items to the Questions section prefixed with "[Validation]". Write the validation result artifact:
```bash
PAYLOAD=$(python3 -c "
import json
validation = {
    'route_conflict': {'checked': True, 'result': '<pass|fail|skip>', 'details': '<explanation>'},
    'schema_conflict': {'checked': True, 'result': '<pass|fail|skip>', 'details': '<explanation>'},
    'import_availability': {'checked': True, 'result': '<pass|fail|skip>', 'details': '<explanation>'},
    'component_reuse': {'checked': True, 'result': '<pass|fail|skip>', 'details': '<explanation>'},
    'analytics_naming': {'checked': True, 'result': '<pass|fail|skip>', 'details': '<explanation>'}
}
print(json.dumps(validation))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/plan-validation.json \
  --payload "$PAYLOAD" \
  --skill change
```

**Plan structure validation** (before presenting for approval):
- Feature plans classified as Multi-layer: verify `## Approaches` section exists
- All plans: if `.runs/iterate-manifest.json` exists, verify the plan's Why section references the iterate bottleneck
- Production plans: verify each task with business logic has a unit test in its description
- All plans: verify `## Exploration Summary` section exists (shows files scanned, patterns found, conflicts detected)
If validation fails, fix the plan before presenting.

- **G2 Plan Gate**: Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute G2 Plan Gate. Verify: on a feature branch (not main), current-plan.md exists with YAML frontmatter, classification is one of [Feature/Upgrade/Fix/Polish/Analytics/Test], verification scope matches classification, no source code files modified yet (only .claude/ and experiment/ files), plan contains '## Exploration Summary' section." If gate-keeper returns BLOCK, fix blocking items before presenting plan.

**Full mode STOP augmentation**: If `solve_depth = "full"` in Step 2b, prepend
to the approval prompt:

> **Open questions from deep analysis:**
> [Phase 5 TYPE C concerns — assumptions only the user can validate]

**Plan display requirement**: Display the plan body (all sections from the type-specific
template — "What I'll Add" / "Bug Diagnosis" / "Planned Changes" / etc. through "Questions")
in your response text ABOVE the STOP prompt below. The user must be able to read the full
plan without requesting it separately. Do NOT include the YAML frontmatter (that is for
machine consumption only). If the plan exceeds 100 lines, include a summary table of
contents at the top.

**POSTCONDITIONS:**
- Plan generated from type-specific template
- Plan validated against codebase (plan-validation.md)
- `.runs/plan-validation.json` exists with all 5 checks having `checked` field
- Plan structure validation passed
- G2 Plan Gate passed
- Plan displayed to user in response text

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/plan-validation.json')); checks=['route_conflict','schema_conflict','import_availability','component_reuse','analytics_naming']; missing=[c for c in checks if c not in d]; assert not missing,'plan-validation.json missing: %s'%missing; no_checked=[c for c in checks if d[c].get('checked') is None]; assert not no_checked,'checks without checked field: %s'%no_checked"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 6
```

**NEXT:** Read [state-7-user-approval.md](state-7-user-approval.md) to continue.
