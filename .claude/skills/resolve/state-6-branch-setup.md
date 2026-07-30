# STATE 6: BRANCH_SETUP


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Branch naming may include 'cli' / 'service' as slug fragments (e.g., 'fix/resolve-42-missing-cli-check'). -->

**PRECONDITIONS:**
- User approved diagnosis (STATE 5d POSTCONDITIONS met)

**ACTIONS:**

Follow `.claude/patterns/branch.md` with:
- `branch_prefix`: `fix`
- `branch_name`: `fix/resolve-<N>-<slug>` where N is the primary issue number
  and slug is a 2-3 word description (e.g., `fix/resolve-42-missing-cli-check`)

If resolving multiple issues: use the lowest issue number and a general slug
(e.g., `fix/resolve-42-template-fixes`).

**POSTCONDITIONS:**
- Current branch matches `fix/resolve-*`
- Branch is not `main`

**VERIFY:**
```bash
git branch --show-current | grep -q 'fix/resolve'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 6
```

**NEXT:** Read [state-7-implement-fixes.md](state-7-implement-fixes.md) to continue.
