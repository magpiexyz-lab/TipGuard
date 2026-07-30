# STATE 7: USER_APPROVAL


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Reads archetype from experiment.yaml; saves to plan frontmatter for resume continuity. -->

**PRECONDITIONS:**
- Plan presented (STATE 6 POSTCONDITIONS met)

**ACTIONS:**

Follow checkpoint-resumption protocol per `patterns/checkpoint-resumption.md`.

### STOP. End your response here. Say:
> Plan ready. How would you like to proceed?
> 1. **approve** — continue implementation now
> 2. **approve and clear** — save plan, then clear context for a fresh start
> 3. **skip** — cancel this change and delete the feature branch
> 4. Or tell me what to change

DO NOT proceed to Phase 2 until the user explicitly replies with approval.
If the user selects "skip": switch to main and delete the feature branch by running `git checkout main`, then `git branch -D <branch-name>`. If both commands succeed, tell the user "Change cancelled. Branch deleted. Run `/change` again when ready." If either command fails (e.g., uncommitted changes blocking checkout, or branch deletion refused), report the manual-fallback message per `.claude/patterns/branch-cleanup-error-template.md` Variant C (substitute `<skill>` = `change`). Stop in both cases.
If the user requests changes instead of approving, revise the plan to address their feedback and present it again. Repeat until approved.

Save the approved plan to `.runs/current-plan.md` with YAML frontmatter:

```yaml
---
skill: change
type: [classification from Step 3]
scope: [verification scope from Step 3]
archetype: [from experiment.yaml type, default web-app]
branch: [current git branch name]
stack: { [category]: [value], ... }
checkpoint: phase2-gate
context_files:
  - experiment/experiment.yaml
  - experiment/EVENTS.yaml
  - .claude/archetypes/[archetype].md
  - [each .claude/stacks/<category>/<value>.md read in Step 2]
acceptance_criteria:   # OPTIONAL — omit if no verifiable behaviors
  - id: AC1
    behavior: "<verifiable behavior extracted from plan body>"
    verify_method: behavior-verifier | unit-test
    test_file: "<relative path, only when verify_method is unit-test>"
  - id: AC2
    behavior: "..."
    verify_method: behavior-verifier
---
```

**Generating `acceptance_criteria`:** Before saving the plan, extract verifiable behaviors from the plan body:
- Scan "What I'll Add", "Bug Diagnosis", "Planned Changes", or equivalent sections for concrete, testable behaviors
- Each behavior becomes one AC entry with `id` format `AC1`, `AC2`, ...
- Choose `verify_method`: pure logic (sorting, calculations, data transforms) → `unit-test` + specify `test_file`; UI/page rendering, navigation, visual output → `behavior-verifier`
- Typical count: Feature 3-5 ACs, Fix 1-2, Polish 1-3
- If no verifiable behaviors can be extracted (rare), omit the `acceptance_criteria` field entirely

Then append the plan body. The frontmatter enables resume-after-clear without re-deriving classification, scope, or stack.

If the user replied **"approve and clear"** or **"2"**:
  1. Save the plan with frontmatter (same as above)
  2. Tell the user: "Plan saved to `.runs/current-plan.md`. Start a new conversation (or press Ctrl+L to clear context), then re-run `/change [original $ARGUMENTS]`. I'll resume at the checkpoint. Do NOT run `make clean` — it deletes the `.runs/` directory and your saved checkpoint."
  3. STOP — do NOT proceed to Phase 2.

**POSTCONDITIONS:**
- User has explicitly approved the plan (option 1 or 2) <!-- enforced by agent behavior, not VERIFY gate -->
- Plan saved to `.runs/current-plan.md` with YAML frontmatter

**VERIFY:**
```bash
test -f .runs/current-plan.md && grep -q 'checkpoint:' .runs/current-plan.md && python3 -c "c=open('.runs/current-plan.md').read(); fm=c.split('---')[1] if c.startswith('---') and c.count('---')>=2 else ''; missing=[f for f in ['skill:','type:','scope:'] if f not in fm]; assert not missing, 'frontmatter missing: %s' % missing"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 7
```

**NEXT:**
- If user approved (option 1 / "approve"): Read [state-8-phase2-preflight.md](state-8-phase2-preflight.md) to continue.
- If user selected "approve and clear" (option 2): TERMINAL — plan saved, start a new conversation, then re-run `/change`.
