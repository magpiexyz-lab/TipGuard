# STATE 2d: BRANCH_SETUP

**PRECONDITIONS:**
- Adversarial validation complete (STATE 2c POSTCONDITIONS met)

**ACTIONS:**

First iteration only:

Follow `.claude/patterns/branch.md` with prefix `chore` and name `chore/review-fixes`.

If branch already exists from prior iteration, continue on it.

**POSTCONDITIONS:**
- On `chore/review-fixes*` branch (or continuing on existing branch)
- Branch is not `main`

**VERIFY:**
```bash
git branch --show-current | grep -q 'chore/review-fixes'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 2d
```

**NEXT:** Read [state-2e-fix-findings.md](state-2e-fix-findings.md) to continue.
