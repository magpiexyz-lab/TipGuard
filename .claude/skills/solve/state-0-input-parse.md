# STATE 0: INPUT_PARSE

**PRECONDITIONS:**
- User has invoked `/solve` with arguments

**ACTIONS:**

Read the problem statement from the user's arguments: `$ARGUMENTS`

If `$ARGUMENTS` is empty, ask the user to describe the problem.

### Depth Selection

- Default: `full` (4 Opus agents, ~3 min)
- If user includes `--light` or `--quick` in arguments: use `light` mode (~30s, 0 agents)
- If user includes `--full` in arguments: use `full` mode

### Problem Type Detection

If user includes `--defect` or `--bug` in arguments, or the problem statement
clearly describes a defect/failure: set `problem_type = "defect"` in `solve-context.json`.
This activates the prevention dimension in solve-reasoning (root cause + recurrence +
scope checks). Otherwise: do not set `problem_type` (prevention skipped).

**POSTCONDITIONS:**
- Problem statement captured (from arguments or user input)
- Depth mode selected (`full` or `light`)
- `.runs/solve-context.json` exists

**VERIFY:**
```bash
test -f .runs/solve-context.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh solve 0
```

**NEXT:** Read [state-1-execute.md](state-1-execute.md) to continue.
