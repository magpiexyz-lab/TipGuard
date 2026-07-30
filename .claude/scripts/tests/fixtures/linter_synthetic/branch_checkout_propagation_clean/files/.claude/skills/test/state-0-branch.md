# STATE 0: BRANCH (synthetic fixture for branch_checkout_propagation_pairing lint — clean case)

This markdown fenced bash block bundles checkout AND propagation in the
same chain. The lint rule must NOT flag this.

**ACTIONS:**

```bash
echo "$(date +%s)" > .runs/last-branch-checkout.tsv && \
  OLD_BRANCH="$(git branch --show-current)" && \
  git checkout -b feat/test-branch && \
  bash .claude/scripts/update-context-branch.sh "$OLD_BRANCH"
```
