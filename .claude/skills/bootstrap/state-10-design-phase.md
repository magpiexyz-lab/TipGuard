# STATE 10: DESIGN_PHASE

**PRECONDITIONS:**
- Setup done (STATE 9 POSTCONDITIONS met)
- `package.json` and `node_modules/` exist
- Surface type resolved

**ACTIONS:**

Spawn a subagent via Agent with:
- subagent_type: scaffold-init
- prompt: Tell the subagent to:
  1. Read `.claude/procedures/scaffold-init.md` and execute all steps
  2. Read context files: `experiment/experiment.yaml`, `.runs/current-plan.md`,
     `.claude/patterns/design.md`, `.claude/archetypes/<type>.md`,
     `.claude/stacks/surface/<value>.md` (resolved from experiment.yaml or inferred)
  3. Follow CLAUDE.md Rules 3, 4, 7

The subagent returns its completion report directly as the result.
Wait for design to complete before proceeding.

Update checkpoint in `.runs/current-plan.md` frontmatter to `phase2-scaffold`.

Check off in `.runs/current-plan.md`: `- [x] scaffold-init completed`

Verify scaffold-init trace: `test -f .runs/agent-traces/scaffold-init.json && python3 -c "import json;d=json.load(open('.runs/agent-traces/scaffold-init.json'));assert d.get('status')=='completed';print('scaffold-init trace: OK')"`. If trace missing: log "WARN: scaffold-init did not write trace -- continuing with file-based verification".

**POSTCONDITIONS:**
- `.runs/current-visual-brief.md` exists
- Theme tokens written (e.g., `src/app/globals.css` has `--primary`)
- Checkpoint updated to `phase2-scaffold`

**VERIFY:**
```bash
test -f .runs/current-visual-brief.md && grep -q 'theme\|palette\|font\|color' .runs/current-visual-brief.md
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 10
```

**NEXT:** Read [state-11-core-scaffold.md](state-11-core-scaffold.md) to continue.
