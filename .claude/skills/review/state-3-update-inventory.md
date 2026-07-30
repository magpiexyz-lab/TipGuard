# STATE 3: UPDATE_INVENTORY

**PRECONDITIONS:**
- Review-Fix Loop exited (via State 2b zero findings, State 2e no fixes, or State 2f termination)

**ACTIONS:**

If new validator checks were implemented in State 2e:

- Add each to the appropriate table in `scripts/check-inventory.md`
- Update the total counts in the header
- Clear any matching entries from the Pending table

**POSTCONDITIONS:**
- `scripts/check-inventory.md` updated with new checks (if any were added)
- Total counts in header are accurate
- No stale Pending entries for implemented checks

**VERIFY:**
```bash
test -f scripts/check-inventory.md && python3 -c "import os; assert os.path.getsize('scripts/check-inventory.md') > 0, 'check-inventory.md is empty'"
```

> **VERIFY rationale:** STATE 3 only updates `scripts/check-inventory.md` —
> it does NOT write `.runs/review-complete.json`. STATE 4 writes that file.
> The previous VERIFY checked `review-complete.json` which fails if STATE 3
> runs immediately after STATE 2f (loop exit), since STATE 4 hasn't run yet.

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 3
```

**NEXT:** Read [state-4-final-validation.md](state-4-final-validation.md) to continue.
