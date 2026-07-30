# STATE 1: BRANCH_SETUP

**PRECONDITIONS:**
- Pre-flight passed (STATE 0 POSTCONDITIONS met)
- On `main` branch (or resuming on existing `change/*` branch)

**ACTIONS:**

Follow the branch setup procedure in `.claude/patterns/branch.md`. Use branch prefix `change` and slugify `$ARGUMENTS` for the branch name.

**POSTCONDITIONS:**
- Current branch starts with `change/`
- Branch is not `main`

**VERIFY:**
```bash
git branch --show-current | grep -q 'change/'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 1
```

**NEXT:** Read [state-2-read-context.md](state-2-read-context.md) to continue.
