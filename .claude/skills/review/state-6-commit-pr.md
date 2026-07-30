# STATE 6: COMMIT_PR

**PRECONDITIONS:**
- Final validation complete (STATE 4 POSTCONDITIONS met)

**ACTIONS:**

### Q-score

Compute review execution quality (see `.claude/patterns/skill-scoring.md`):

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/review-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
REVIEW_DIMS=$(python3 -c "
import json
try:
    r = json.load(open('.runs/review-complete.json'))
    fixed = r.get('findings_fixed', 0)
    disputed = r.get('findings_disputed', 0)
    q_yield = round(fixed / max(fixed + disputed, 1), 3)
    print(json.dumps({'yield': q_yield, 'completion': 1.0}))
except:
    print(json.dumps({'completion': 1.0}))
" 2>/dev/null || echo '{"completion": 1.0}')
PAYLOAD=$(REVIEW_DIMS_ENV="$REVIEW_DIMS" python3 -c "
import json, os
print(json.dumps({
    'scope': 'review',
    'dims': json.loads(os.environ['REVIEW_DIMS_ENV'])
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill review || true
```

If no branch exists (no findings across all iterations):
  Report "Review clean — no findings."
  Write `.runs/delivery-skip.flag` (content: `no-findings`).

If branch exists with changes:

### Close resolved observations

For each observation issue whose root cause was fixed in this review, close it:
```bash
gh issue close <number> --comment "Fixed in review — see upcoming PR"
```

### Write delivery artifacts

Write `.runs/commit-message.txt` — descriptive message for accumulated changes.

Write `.runs/pr-title.txt` — short title (<=70 chars).

Write `.runs/pr-body.md` using `.github/PULL_REQUEST_TEMPLATE.md`:
  - **Summary**: "Automated review-fix: N findings fixed across M iterations"
  - **How to Test**: "Run `make validate` + all 3 validator scripts"
  - **What Changed**: list every file and what changed
  - **Why**: "Template quality — fixes found by 3-dimension LLM review"
- Include in PR body: review summary, fixed findings, skipped/reverted
  findings, new checks added, remaining unfixable findings
- **Disputed findings section**: Under a `### Disputed Findings` heading,
  list all disputed findings across all iterations with adversarial rationale.
  Format as a table: Finding | Dimension | Rationale. Omit section if none.
- **Finding Fate Log section**: Under a `### Finding Fate Log` heading, include
  a table of ALL findings across all iterations:

  | Finding | Dimension | Adversarial Label | Fate | Notes |
  |---------|-----------|------------------|------|-------|

  Fate values: `fixed`, `reverted`, `disputed`, `skipped`.

- **Precision Summary section**: Under a `### Precision Summary` heading, include:
  - Per-dimension precision: (fixed) / (confirmed + needs-evidence) for A, B, C
  - Per-label accuracy: fraction of "confirmed" that were fixed and kept
  - Overall yield: total fixed / total reported across all iterations
- End with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`

**POSTCONDITIONS:**
- Delivery artifacts written (`.runs/commit-message.txt`, `.runs/pr-title.txt`, `.runs/pr-body.md`) OR `.runs/delivery-skip.flag` if no findings
- Resolved observation issues closed

**VERIFY:**
```bash
python3 -c "import json,os; rc=json.load(open('.runs/review-complete.json')); assert rc.get('timestamp'), 'review-complete timestamp empty'; assert isinstance(rc.get('findings_fixed'), int) and rc['findings_fixed']>=0, 'findings_fixed invalid'; skip=os.path.isfile('.runs/delivery-skip.flag'); assert skip or (os.path.isfile('.runs/commit-message.txt') and os.path.isfile('.runs/pr-title.txt') and os.path.isfile('.runs/pr-body.md')), 'delivery artifacts missing and no skip flag'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 6
```

**NEXT:** TERMINAL — `lifecycle-finalize.sh` handles commit, push, PR creation, and auto-merge (or skips if `delivery-skip.flag` present).

After finalize, read the `DELIVERY=` output and tell the user:
- If `DELIVERY=merged`: "Review PR auto-merged to main. N findings fixed, M observation issues closed."
- If `DELIVERY=pr-created:<reason>`: "Review PR created but not auto-merged (<reason>). Merge manually."
- If `DELIVERY=skipped`: "Review clean — no findings."
