# STATE 0: BRANCH (synthetic fixture for branch_checkout_propagation_pairing lint)

This markdown fenced bash block has `git checkout -b` but does NOT pair
it with `update-context-branch.sh`. The lint rule must flag this — the
race window (#1328) is recreated whenever the LLM splits checkout from
propagation.

**ACTIONS:**

```bash
git checkout -b feat/test-branch
```
