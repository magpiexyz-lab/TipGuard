# STATE 1: EVALUATE_AND_FILE

> REF: The 3-condition test, redaction, dedup, and filing in this state follow
> the same decision framework defined in `observation-phase.md` Step 6 and
> `observe.md`. Changes to the decision framework must be reflected in both files.

**PRECONDITIONS:**
- Arguments parsed (STATE 0 POSTCONDITIONS met)
- `.runs/observe-context.json` exists with `template_file` and `symptom`

**ACTIONS:**

Read `.runs/observe-context.json` for `template_file`, `symptom`, and `narrative`.

### Step 1: Verify template file

1. Verify the file exists on disk. If not: report "File not found: <path>" and write
   filing result with `verdict: "error"`, then proceed to STATE 2.
2. Verify the file is listed in (or under a path in) `.claude/template-owned-dirs.txt`.
   If not: report "File <path> is not a
   template-owned file" and write filing result with `verdict: "no-template-issues"`,
   then proceed to STATE 2.

### Step 2: Three-condition test (observe.md Path 2)

Evaluate whether **all three** conditions are true:

**A. Template file is the root cause.** The file specified by `--file` is a template
file and the symptom described traces to incorrect guidance, logic, or code in that file.

**B. Not an environment issue.** The symptom is NOT caused by: missing CLI tools,
network failures, Node version mismatches, missing env vars, or auth failures.

**C. Not a user code issue.** The symptom is NOT caused by: business logic bugs
specific to this experiment.yaml, user code not following template guidance, or
project-specific dependency conflicts.

**Heuristic:** "Would another developer using this template with a different
experiment.yaml hit this same problem?" If yes, all conditions pass.

If any condition fails, write filing result and report to user:
```bash
PAYLOAD=$(python3 -c "
import json, datetime
print(json.dumps({
    'verdict': 'no-template-issues',
    'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'reason': '<which condition failed and why>'
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/observe-filing-result.json \
  --payload "$PAYLOAD" \
  --skill observe
```
Report: "Evaluation complete. The symptom does not qualify as a template observation:
<reason>." Then proceed directly to Q-score and STATE 2.

### Step 3: Prerequisites

```bash
TEMPLATE_REPO="magpiexyz-lab/mvp-template"
if ! git remote get-url template &>/dev/null; then
  git remote add template https://github.com/magpiexyz-lab/mvp-template.git
fi
```

- `gh auth status` -- if fails, write filing result with `verdict: "error"` and
  reason "GitHub auth not available", then proceed to STATE 2.
- `gh repo view $TEMPLATE_REPO --json name` -- if fails, write filing result with
  `verdict: "error"` and reason "Cannot access template repo", then proceed to STATE 2.

### Step 4: Redaction (observe.md rules)

Before composing the issue, strip all project-specific information:
- Replace the project name (from experiment.yaml `name` if it exists) with `<project>`
- Replace experiment.yaml content with `<redacted>`
- Replace full error stack traces with the relevant error message only
- Replace paths containing project-specific page names with generic paths
- Keep: template file name, generic symptom description

### Step 5: Dedup (observe.md rules)

```bash
TEMPLATE_REPO="magpiexyz-lab/mvp-template"
BASENAME=$(basename "<template-file>")
gh issue list --repo $TEMPLATE_REPO --label observation \
  --search "[observe] $BASENAME:" --state open --limit 20
```

If a duplicate is found (same file, same or similar root cause), comment instead of
creating a new issue:
```bash
gh issue comment <issue-number> --repo $TEMPLATE_REPO --body "<comment>"
```

The comment body includes the symptom, narrative (from `--context`) if provided, and
file version.

Write filing result with `verdict: "duplicate-commented"` and the issue URL, then
proceed to Q-score and STATE 2.

### Step 6: Issue creation (observe.md format)

Title: `[observe] <template-file-basename>: <symptom-in-imperative-form>`

Body:
```markdown
## Observation

**Template file:** `<full path>`
**Context:** /observe (manual)
**Trigger:** manual observation via /observe skill

## Symptom

<1-3 sentences, generic -- no project names. From --symptom.>

## Narrative

<Content from --context flag. Omit this section if --context was not provided.>

## Root cause

<1-3 sentences explaining why the template guidance/code is incorrect.>

## Suggested template change

<What the template file should change to prevent this in future projects.>

---
*Filed by /observe skill.*

---
template_file: <full path>
file_version: <FILE_VERSION>
```

Compute file version:
```bash
FILE_VERSION=$(git hash-object "<template-file>" 2>/dev/null || echo "unknown")
```

File the issue:
```bash
TEMPLATE_REPO="magpiexyz-lab/mvp-template"
gh issue create --repo $TEMPLATE_REPO \
  --title "<title>" \
  --label "observation" \
  --body "<body>"
```

If label "observation" doesn't exist, retry without `--label`.
If filing fails, log the error and write filing result with `verdict: "error"`.

On success, write filing result:
```bash
PAYLOAD=$(python3 -c "
import json, datetime
print(json.dumps({
    'verdict': 'filed',
    'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'issue_url': '<url>',
    'title': '<title>'
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/observe-filing-result.json \
  --payload "$PAYLOAD" \
  --skill observe
```

Report to user: "Filed template observation: <url>"

Note: This skill is EXEMPT from observe.md's max-1-per-session limit -- filing an
observation IS the user's requested task.

### Q-score

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/observe-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'observe',
    'dims': {'filing': 1.0}
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill observe || true
```

**POSTCONDITIONS:**
- `.runs/observe-filing-result.json` exists with `verdict` field
- Verdict is one of: `filed`, `no-template-issues`, `duplicate-commented`, `error`

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/observe-filing-result.json')); assert d.get('verdict') in ('filed','no-template-issues','duplicate-commented','error'), 'verdict=%s' % d.get('verdict')"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh observe 1
```

**NEXT:** Skill states complete.
