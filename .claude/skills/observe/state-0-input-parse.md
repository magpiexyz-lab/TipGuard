# STATE 0: INPUT_PARSE

**PRECONDITIONS:**
- User has invoked `/observe` with arguments

**ACTIONS:**

Parse the arguments from `$ARGUMENTS`:

### Required arguments

- `--file <template-file-path>` -- the template file suspected of having an issue
- `--symptom "<description>"` -- one-line description of the problem

### Optional arguments

- `--context "<narrative>"` -- human context that automation cannot capture (e.g., "I tried three different approaches before finding this workaround")

If `--file` or `--symptom` is missing, fail fast with usage message:
```
Usage: /observe --file <template-file-path> --symptom "<description>" [--context "<narrative>"]

Example: /observe --file .claude/patterns/verify.md --symptom "STATE 3 retry loop exits after 1 attempt instead of 3"
```

No worktree is needed (analysis-only, no branch).

Clean stale skill artifacts:
```bash
rm -f .runs/observe-filing-result.json
```

Store parsed arguments in the context file:
```bash
PAYLOAD=$(python3 -c "
import json
d = json.load(open('.runs/observe-context.json'))
d['template_file'] = '<parsed --file value>'
d['symptom'] = '<parsed --symptom value>'
d['narrative'] = '<parsed --context value or null>'
print(json.dumps(d))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/observe-context.json \
  --payload "$PAYLOAD" \
  --skill observe
```

**POSTCONDITIONS:**
- `--file` and `--symptom` arguments parsed successfully
- `.runs/observe-context.json` exists with `template_file`, `symptom`, and `narrative` fields

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/observe-context.json')); assert d.get('template_file'), 'template_file missing'; assert d.get('symptom'), 'symptom missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh observe 0
```

**NEXT:** Read [state-1-evaluate-and-file.md](state-1-evaluate-and-file.md) to continue.
