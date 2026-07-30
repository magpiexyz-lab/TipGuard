# STATE 0: PRE_FLIGHT

**PRECONDITIONS:**
- Git repository exists in working directory
- `$ARGUMENTS` is available (user's change description)

**ACTIONS:**

- If `$ARGUMENTS` is empty or unclear: stop and ask the user to describe what they want to change.
- If `$ARGUMENTS` contains `#<number>` or is just a number: read the GitHub issue via `gh issue view <number>` and use its content as the change description. If `gh issue view` fails (issue not found, permission denied, or network error), tell the user: "Could not read issue #<number>. Describe the change directly, or check `gh auth status` and retry."
- Verify `package.json` exists. If not, stop and tell the user: "No app found. Run `/bootstrap` first, or if you already have a bootstrap PR open, merge it before running `/change`."
- Verify `experiment/EVENTS.yaml` exists. If not, stop and tell the user: "experiment/EVENTS.yaml not found. This file defines all analytics events and is required. Restore it from your template repo or re-create it following the format in the experiment/EVENTS.yaml section of the template."
- Run `npm run build` to confirm the project compiles before making changes (unless `$ARGUMENTS` describes a fix). If the build fails and the change is not a build fix: stop and tell the user: "The app has build errors that need to be fixed first. Run `/change fix build errors` to address them."
- **G1 Pre-flight Gate**: Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute G1 Pre-flight Gate. Verify: package.json exists, experiment/EVENTS.yaml exists, build passes (unless fix type), $ARGUMENTS is non-empty." If gate-keeper returns BLOCK, stop and report blocking items to user.

Merge skill-specific fields into context:
```bash
bash .claude/scripts/init-context.sh change '{"preliminary_type":null,"affected_areas":null,"solve_depth":null}'
```

**POSTCONDITIONS:**
- `$ARGUMENTS` is non-empty and clear
- `package.json` exists
- `experiment/EVENTS.yaml` exists
- Build passes (unless change is a fix)
- G1 Pre-flight Gate passed
- `.runs/change-context.json` exists

**VERIFY:**
```bash
test -f .runs/change-context.json && test -f package.json && test -f experiment/EVENTS.yaml
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 0
```

**NEXT:** Read [state-1-branch-setup.md](state-1-branch-setup.md) to continue.
