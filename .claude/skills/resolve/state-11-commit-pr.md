# STATE 11: COMMIT_PR

**PRECONDITIONS:**
- Post-fix review complete (STATE 10 POSTCONDITIONS met)
- For Ring 3 runs (`"ring": 3` in resolve-context.json), STATEs 6-10 are skipped — proceed directly from STATE 5d

**ACTIONS:**

### Step 0 — Short-circuit on delivery-skip.flag

If `.runs/delivery-skip.flag` exists, the run was halted earlier (most likely
at STATE 3b oscillation escalation) and no PR should be opened. Skip the
normal delivery artifact generation and advance — `lifecycle-finalize.sh`
already honors the flag and will bypass commit/push/PR creation.

```bash
if [ -f .runs/delivery-skip.flag ]; then
  cat .runs/delivery-skip.flag
  # Defensive: if STATE 3b escalation did not file an issue (gh_failed path),
  # file a minimal one here so the halt is auditable on GitHub.
  PAYLOAD=$(python3 -c "
import json, os, subprocess, sys
a = json.load(open('.runs/resolve-causal-analysis.json')) if os.path.exists('.runs/resolve-causal-analysis.json') else {}
should_write = False
if a.get('halted') and not a.get('escalation_issue_url'):
    dps = a.get('divergence_points_analyzed', [])
    loc = dps[0]['divergence_point'] if dps else 'unknown'
    try:
        url = subprocess.check_output([
            'gh','issue','create',
            '--repo','magpiexyz-lab/mvp-template',
            '--label','oscillation-escalation',
            '--title', f'[escalation] /resolve halted: oscillation at {loc}',
            '--body', 'Auto-filed defensive escalation (STATE 3b dispatch did not record a URL).'
        ], text=True).strip()
        a['escalation_issue_url'] = url
        should_write = True
    except Exception as e:
        print(f'defensive escalation file failed: {e}', file=sys.stderr)
print(json.dumps({'__should_write': should_write, '__payload': a}))
")
  if [ "$(echo "$PAYLOAD" | python3 -c "import json,sys; print(json.load(sys.stdin)['__should_write'])")" = "True" ]; then
    INNER=$(echo "$PAYLOAD" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['__payload']))")
    bash .claude/scripts/lib/write-gate-artifact.sh \
      --path .runs/resolve-causal-analysis.json \
      --payload "$INNER" \
      --skill resolve
  fi
  bash .claude/scripts/advance-state.sh resolve 11
  exit 0
fi
```

Read `resolve-context.json` and check the `mode` field.

### Write delivery artifacts

**If `mode == "refine"`:**
- `commit-message.txt`: `Refine: <improvement description>\n\nFixes #N, #M`
- `pr-title.txt`: `Refine: <skill> state improvements`
- All other PR body sections (Root Cause Analysis, Blast Radius, etc.) remain the same

**If `mode` is not `"refine"`:** use the normal format below.

Write `.runs/commit-message.txt`: `Fix #N: <imperative description>`
(or `Fix #N, #M: <description>` for multiple issues).

Write `.runs/pr-title.txt`: short title (<=70 chars).

Write `.runs/pr-body.md` using `.github/PULL_REQUEST_TEMPLATE.md`:

- **Summary**: For each issue resolved:
  - Issue number and title
  - Root cause (1 sentence)
  - What changed
- **How to Test**: "Run `make validate` + all 3 validator scripts"
- **What Changed**: List every file and what changed
- **Why**: "Resolves template issues reported in #N, #M, ..." followed by one `Closes #N` per line per issue (GitHub only auto-closes the first issue when multiple are comma-separated on one line). Example:
  ```
  Closes #838
  Closes #837
  Closes #836
  ```
  Check `rejected_issues` in `resolve-context.json` — exclude those issue numbers from `Closes #N` lines (rejected issues remain open).

Include additional sections in PR body:

### Root Cause Analysis
For each issue: root cause, divergence point, and why the fix addresses it.

When a divergence point record from `.runs/resolve-causal-analysis.json.divergence_points_analyzed[i]` includes a non-empty `line_parse_note` (e.g., `"range: start of 34-55"`, `"csv: first of 180,217,261"`), surface it in parentheses alongside the divergence point so the graceful-degradation is observable at the most visible output surface:

> `divergence_point: f.md:34-55 (line_parse_note=range, analyzed at line 34)`

When the note is absent, `"integer"`, or `"no-digits"`, render the divergence point plainly. See `.claude/scripts/resolve-causal-analyzer.py::parse_line_part` for the full set of notes (resolves issue #985's visibility gap).

### Blast Radius
Files checked, confirmed matches fixed, potential matches evaluated.

### Validator Additions
New checks added (if any), with name, target script, and pass/fail criteria.
If none: "No new checks — pattern is unlikely to recur."

### Validator Evidence
| Issue | Pre-Fix Errors | Post-Fix Errors | Delta |
|-------|---------------|-----------------|-------|
| #N    | <cited errors or "none"> | <errors or "none"> | -K |

### Adversarial Review
| Issue | Label | Challenge Summary |
|-------|-------|-------------------|
| #N    | sound | Tested 3 fixture configs, no breakage |

### Cross-Issue Correlation
- Cluster 1: #A, #B — shared root cause: <pattern>. Single fix.
- Uncorrelated: #C
(Or: "Single issue — no correlation analysis")

### Potentially Resolved
(From Step 8b, or "None — no side-effect matches detected")

End with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`

**POSTCONDITIONS:**
- Delivery artifacts written: `.runs/commit-message.txt`, `.runs/pr-title.txt`, `.runs/pr-body.md`
- `Closes #N` on separate lines in `pr-body.md` — one per implemented issue, never comma-separated (excludes `rejected_issues` from `resolve-context.json`)

**VERIFY:**
```bash
python3 -c "import os,re,json,sys; skip=os.path.isfile('.runs/delivery-skip.flag'); sys.exit(0) if skip else None; [None for f in ('.runs/commit-message.txt','.runs/pr-title.txt','.runs/pr-body.md') if not os.path.isfile(f) and (_ for _ in ()).throw(AssertionError(f+' missing'))]; cm=open('.runs/commit-message.txt').read().strip(); assert re.match(r'^[A-Z][a-z]+\s', cm), 'commit-message first line not imperative mood: %r' % cm.split(chr(10))[0]; pt=open('.runs/pr-title.txt').read().strip(); assert 0 < len(pt) <= 70, 'pr-title length=%d (must be 1..70 chars)' % len(pt); pb=open('.runs/pr-body.md').read(); assert 'Generated with' in pb, 'pr-body.md missing PR template footer'; ctx=json.load(open('.runs/resolve-context.json')); rejected=set(ctx.get('rejected_issues') or []); issues=[i.get('number') for i in ctx.get('issue_list',[]) if i.get('number') not in rejected]; assert not issues or ('Closes #' in pb), 'pr-body.md missing Closes #N line for resolved issues'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 11
```

**NEXT:** TERMINAL — `lifecycle-finalize.sh` handles commit, push, PR creation, and auto-merge.

After finalize, read the `DELIVERY=` output and tell the user:
- If `DELIVERY=merged`: "Resolve PR auto-merged to main. Issues closed."
- If `DELIVERY=pr-created:<reason>`: "Resolve PR created but not auto-merged (<reason>). Merge manually."
