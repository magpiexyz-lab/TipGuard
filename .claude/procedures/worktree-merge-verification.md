# Worktree Merge Verification

> Shared procedure for merging implementer worktree changes back to branch.
> Referenced by change-feature.md, change-fix.md, and change-upgrade.md.

## For each completed implementer worktree:

a. **Verify the agent committed:** run `git log --oneline main..<worktree-branch>` and confirm at least one commit beyond the fork point. If NO commit exists:
   - **Do NOT copy files manually or commit on behalf of the agent.**
   - Re-spawn the same implementer agent with a commit-only task: "Your prior implementation is complete but uncommitted. Stage and commit all changed files with `git add <files> && git commit -m 'Add <task-slug>'`. Then verify with `git log --oneline -1`." Budget: 1 retry.
   - If still no commit after retry, mark task as blocked in PR body.
b. **Merge:** `git merge <worktree-branch> --no-ff -m "Merge implementer: <task-slug>"`. The `--no-ff` flag ensures a merge commit in git history (required for G4).
c. **If merge conflicts:** resolve, then commit the merge resolution.
d. **Verify merge succeeded:** `git log --oneline -1` must show the merge commit.
e. **Update the trace:** set `worktree_merged: true`.

## Multi-agent consistency scan

If 2+ implementer agents were spawned: quick consistency scan -- check for naming divergence, duplicate utilities (3+ copies per Rule 4), and mixed error handling patterns across modified files. Fix under green tests. Budget: 3 minutes. After scan, write result artifact:
```bash
PAYLOAD=$(python3 -c "
import json, datetime
result = {'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'implementer_count': '<N>', 'issues_found': '<N>', 'issues_fixed': '<N>', 'status': 'pass'}
print(json.dumps(result))
")
# Procedure called from a skill context — pass the active skill via env or use --source-* if post-completion.
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/consistency-scan-result.json \
  --payload "$PAYLOAD"
```
