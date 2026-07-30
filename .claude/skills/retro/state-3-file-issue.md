# STATE 3: FILE_ISSUE

**PRECONDITIONS:**
- Retro document generated and shown to user (STATE 2 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

### File as GitHub Issue

> REF: The issue filing pattern (auth check, repo resolution, label fallback, error handling)
> follows `.claude/patterns/observe.md` "Issue Creation" section. Retro uses label `"retro"`
> and a different title format, but the gh CLI workflow is the same.

1. Verify GitHub authentication: run `gh auth status`. If it fails, stop: "GitHub CLI is not authenticated. Run `gh auth login` to authenticate, then re-run `/retro`. Or say 'skip' to print the retro to the terminal instead."
2. Determine the target repo: use the current repo via `gh repo view --json nameWithOwner --jq '.nameWithOwner'`. If `gh` is not available or the command fails, ask the user: "Where should I file this retro? Enter a repo in `owner/repo` format, or say 'skip' to print it to the terminal instead."
3. If the user says "skip", print the retro to the terminal and stop.

File the issue:
```
gh issue create \
  --title "Retro: <experiment-name> -- <outcome>" \
  --label "retro" \
  --body "<structured retro content>"
```

If label `"retro"` doesn't exist, retry without `--label`. If `gh issue create` fails for another reason, show the error and suggest `gh auth status` or manual filing. Show the issue URL on success.

### Q-score

Compute retro quality (see `.claude/patterns/skill-scoring.md`):

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/retro-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'retro',
    'dims': {'sections': 1.0, 'completion': 1.0}
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill retro || true
```

### Next steps

After filing the retro, guide the user:
- If the archetype is `web-app` or `service` and cloud infrastructure was deployed: "If you're done with this experiment, run `/teardown` to remove cloud resources (Vercel, Supabase, etc.)."
- If the archetype is `cli` and `surface` is `none` (or no surface was deployed): "CLI tools with no surface have no cloud infrastructure to tear down. If you want to unpublish the npm package, run `npm unpublish <name>` (within 72 hours of publish) or deprecate it with `npm deprecate <name> \"Experiment concluded\"`."
- If the archetype is `cli` and `surface` is `detached` (default for CLI): "Your marketing surface is deployed to cloud infrastructure. Run `/teardown` to remove it. For the npm package, run `npm unpublish <name>` (within 72 hours of publish) or deprecate it with `npm deprecate <name> \"Experiment concluded\"`."
- For all archetypes: "Your source code, experiment.yaml, and experiment history are preserved on the main branch."

**POSTCONDITIONS:**
- GitHub issue filed (or user chose to skip)
- Issue URL shown to user (if filed)
- Next steps guidance provided

**VERIFY:**
```bash
python3 -c "import json; ctx=json.load(open('.runs/retro-context.json')); assert ctx.get('issue_filed') or ctx.get('issue_skipped'), 'retro issue not filed and not skipped'"
```

> **Note:** The ACTIONS must set `issue_filed: true` (with `issue_url`) or `issue_skipped: true` in `retro-context.json` before the VERIFY runs.

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh retro 3
```

**NEXT:** Skill states complete.
