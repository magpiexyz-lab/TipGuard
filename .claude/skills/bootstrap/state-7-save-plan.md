# STATE 7: SAVE_PLAN


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Reads archetype from experiment.yaml; saves to plan frontmatter for resume continuity. -->

**PRECONDITIONS:**
- User approved the plan (STATE 6 POSTCONDITIONS met)

**ACTIONS:**

Follow checkpoint-resumption protocol per `patterns/checkpoint-resumption.md`.

Write the plan to `.runs/current-plan.md` with YAML frontmatter:

```yaml
---
skill: bootstrap
archetype: [from experiment.yaml type, default web-app]
branch: feat/bootstrap
stack: { [category]: [value], ... }
checkpoint: phase2-setup
context_files:
  - experiment/experiment.yaml
  - experiment/EVENTS.yaml
  - .claude/archetypes/[archetype].md
  - [each .claude/stacks/<category>/<value>.md read in STATE 2]
---
```

Then append the plan body. The frontmatter enables resume-after-clear without re-deriving archetype or stack. If `golden_path` was derived (not already in experiment.yaml), write it back to `experiment/experiment.yaml` after approval.

**Append Process Checklist** (skip if `current-plan.md` already contains `## Process Checklist`):

```markdown
## Process Checklist
- Skill: bootstrap
- Archetype: [archetype]
- [ ] BG1 Validation Gate passed
- [ ] Duplicate check resolved
- [ ] User approved plan
- [ ] TSP-LSP check completed
- [ ] scaffold-setup completed
- [ ] scaffold-init completed
- [ ] scaffold-libs completed
- [ ] scaffold-pages completed
- [ ] scaffold-externals completed
- [ ] scaffold-landing completed (or N/A: surface=none)
- [ ] Externals user decisions collected
- [ ] BG2.5 Externals Gate passed
- [ ] Merged checkpoint validation passed
- [ ] BG2 Orchestration Gate passed
- [ ] scaffold-wire completed
- [ ] BG2-WIRE Post-Wire Gate passed
- [ ] Scan & classify (state 15)
- [ ] Unit test generation (state 16)
- [ ] ON-TOUCH persisted (state 17)
- [ ] BG4 PR Gate passed
- [ ] Verify embed completed (state 19b — scope: full)
```

Check off items already completed at this point:
- `- [x] BG1 Validation Gate passed`
- `- [x] Duplicate check resolved`
- `- [x] User approved plan`

If the user replied **"approve and clear"** or **"2"**:
  1. Save the plan with frontmatter (same as above)
  2. Tell the user: "Plan saved to `.runs/current-plan.md`. Start a new conversation (or press Ctrl+L to clear context), then re-run `/bootstrap`. I'll resume at the checkpoint. Do NOT run `make clean` — it deletes the `.runs/` directory and your saved checkpoint."
  3. STOP — do NOT proceed to STATE 8.

**POSTCONDITIONS:**
- `.runs/current-plan.md` exists with YAML frontmatter
- Plan body is appended
- `## Process Checklist` section present with all 20 checklist items (state 15/16/17/19b coverage added per #1118)
- Items completed so far are checked off

**VERIFY:**
```bash
test -f .runs/current-plan.md && grep -q 'Process Checklist' .runs/current-plan.md
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 7
```

**NEXT:** STATE 8 (approve) | TERMINAL (approve and clear). If user chose "approve", read [state-8-preflight.md](state-8-preflight.md) to continue. If user chose "approve and clear", TERMINAL — start a new conversation, then re-run `/bootstrap`.
