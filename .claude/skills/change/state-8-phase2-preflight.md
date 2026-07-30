# STATE 8: PHASE2_PREFLIGHT

**PRECONDITIONS:**
- User approved the plan (STATE 7 POSTCONDITIONS met)
- `.runs/current-plan.md` exists with YAML frontmatter

**ACTIONS:**

Follow checkpoint-resumption protocol per `patterns/checkpoint-resumption.md`.

> This step creates a data dependency: writing the checklist requires reading
> the procedure files. Runs once per plan — idempotent.

Before proceeding to Step 5, execute the process gate:

1. **Read the procedure file for the classified type:**
   | Type | File to Read |
   |------|-------------|
   | Feature | `.claude/procedures/change-feature.md` |
   | Upgrade | `.claude/procedures/change-upgrade.md` |
   | Fix | `.claude/procedures/change-fix.md` |
   | Test | `.claude/procedures/change-test.md` |
   | Polish | (none — constraints are inline in Step 6) |
   | Analytics | (none — constraints are inline in Step 6) |

2. Also read `.claude/patterns/tdd.md`.

3. **Always read** `.claude/patterns/verify.md` — extract the scope table and agent list for the verification scope from Step 3.

4. **Append a `## Process Checklist` section** to `.runs/current-plan.md`:

   ```markdown
   ## Process Checklist
   - Implementation mode: TDD
   - Procedure file: [filename | inline (Polish/Analytics)]
   - Verification scope: [scope]
   - [ ] Spawn agents: [enumerate each agent from verify.md scope table for this scope+archetype]
   - [ ] Auto-Observe (after fix cycles — verify.md § Auto-Observe)
   - [ ] Write .runs/verify-report.md (verify.md § Write Verification Report)
   - [ ] Save planning patterns to auto memory (change.md Step 8)
   - Type-specific constraints:
     - [3-5 key rules extracted from the procedure file]
   ```

   Add to the constraints list:
   - Feature/Upgrade: `- Implementer agents required — do NOT implement directly`
   - Feature/Upgrade: `- TDD cycle: RED (failing test) before GREEN (implementation)`
   - Fix: `- Regression test must FAIL on current code before writing fix`

5. **Update checkpoint** in `.runs/current-plan.md` frontmatter to `phase2-step5`.

> **Skip condition:** If `.runs/current-plan.md` already contains `## Process Checklist`, skip to Step 5.

- **G3 Spec Gate**: Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute G3 Spec Gate for type [classification]. Verify: current-plan.md has `## Process Checklist`, checkpoint is at phase2-step5 or later. For Feature that adds NEW behaviors (behavior IDs not previously in experiment.yaml): experiment.yaml behaviors updated. For Feature that refines EXISTING behavior implementations without adding new behaviors: current-plan.md notes which existing behaviors are being refined (experiment.yaml update not required). For Upgrade: .env.example updated if needed. For Production quality: stack.testing present." If gate-keeper returns BLOCK, fix blocking items.

**POSTCONDITIONS:**
- Procedure file read (if applicable for type) <!-- enforced by agent behavior, not VERIFY gate -->
- `verify.md` read — scope table and agent list extracted <!-- enforced by agent behavior, not VERIFY gate -->
- `## Process Checklist` appended to `.runs/current-plan.md`
- Checkpoint updated to `phase2-step5`
- G3 Spec Gate passed <!-- enforced by agent behavior, not VERIFY gate -->

**VERIFY:**
```bash
grep -q 'Process Checklist' .runs/current-plan.md && grep -q 'checkpoint: phase2-step5' .runs/current-plan.md
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 8
```

**NEXT:** Read [state-9-update-specs.md](state-9-update-specs.md) to continue.
