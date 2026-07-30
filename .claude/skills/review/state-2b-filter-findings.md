# STATE 2b: FILTER_FINDINGS

**PRECONDITIONS:**
- Review scan complete (STATE 2a POSTCONDITIONS met)
- Deduplicated findings collected

**ACTIONS:**

- A finding signature = `<file_path>:<finding_title>`
- Remove findings whose signatures match `seen_findings` set (oscillation guard)
- If 0 remaining findings -> **exit loop**, proceed to State 3
- Add new signatures to `seen_findings`

- **Update findings artifact** — add `filtered: true` to `.runs/review-findings.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  d = json.load(open('.runs/review-findings.json'))
  d['filtered'] = True
  print(json.dumps(d))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/review-findings.json \
    --payload "$PAYLOAD" \
    --skill review
  ```

**POSTCONDITIONS:**
- Findings filtered against `seen_findings`
- New signatures added to `seen_findings`
- If 0 remaining: loop exit triggered
- `.runs/review-findings.json` has `filtered` field

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/review-findings.json')); assert d.get('filtered') is not None, 'filtered field missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 2b
```

**NEXT:** If 0 remaining findings, read [state-3-update-inventory.md](state-3-update-inventory.md). Otherwise, read [state-2c-adversarial-validation.md](state-2c-adversarial-validation.md) to continue.
