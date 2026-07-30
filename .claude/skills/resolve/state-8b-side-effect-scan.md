# STATE 8b: SIDE_EFFECT_SCAN

**PRECONDITIONS:**
- Final validation passed (STATE 8 POSTCONDITIONS met)

**ACTIONS:**

For issues closed as "cannot reproduce" in Step 3 or non-actionable
in Step 2: if any file modified in Steps 7-8 is cited in the issue,
comment: "This may have been addressed by the fix in PR #<number>
(for #<primary>). Verify and reopen if the issue persists."

For other open issues not in the current batch:
```bash
gh issue list --state open --search "-label:trace -label:architecture" --limit 10 --json number,title,body
```

> **`-label:trace -label:architecture` rationale (issue #1340 blast extension):** trace-collector issues are permanent open tickets whose bodies happen to mention common files; without filtering they spuriously land in the "Potentially Resolved" PR section. `architecture`-labelled issues are deferred to /solve and similarly should not be cross-referenced here.
If any reference files modified in this PR: note under a
"### Potentially Resolved" section in the PR body (do NOT close —
the fix was not designed for them).

- **Write side-effects artifact** (`.runs/resolve-side-effects.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  side_effects = {
      'comments_posted': [],
      'potentially_resolved': []
  }
  print(json.dumps(side_effects))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-side-effects.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

**POSTCONDITIONS:**
- Side-effect comments posted on relevant closed issues
- Open issues referencing modified files identified for PR body
- `.runs/resolve-side-effects.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/resolve-side-effects.json')); assert isinstance(d.get('comments_posted'), list), 'comments_posted not a list'; assert all(isinstance(c, (str,dict)) for c in d['comments_posted']), 'comments_posted items invalid'; assert isinstance(d.get('potentially_resolved'), list), 'potentially_resolved not a list'; assert all(isinstance(i, (str,int,dict)) for i in d['potentially_resolved']), 'potentially_resolved items invalid'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 8b
```

**NEXT:** Read [state-9-save-patterns.md](state-9-save-patterns.md) to continue.
