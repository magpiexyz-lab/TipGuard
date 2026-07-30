# STATE 7: OUTPUT

**PRECONDITIONS:**
- experiment.yaml assembled and user approved (STATE 6 POSTCONDITIONS met)

**ACTIONS:**

## Step 7: Write Files and Confirm

### 7a: Verify experiment.yaml on disk
`experiment/experiment.yaml` was progressively written during STATES 2–6 (each
state's VERIFY gate required its fields to be on disk). This step confirms the
on-disk file matches the approved spec — re-write only if the STATE 6 approval
round captured a last-minute revision that has not yet been persisted.

### 7a.0: Persist user-supplied design preferences

Read `.runs/spec-context.json.input` for design preferences (parsed from STATE 0
`--theme` / `--design-lineage` / `--aesthetic` flags). If any of `theme`,
`design_lineage`, `aesthetic_notes` are present, persist them to the
`design` block in `experiment/experiment.yaml` (create block if absent). This
closes the silent-drop gap from issue #1050.

```bash
python3 -c "
import json, os, yaml
ctx = json.load(open('.runs/spec-context.json'))
inp = ctx.get('input', {}) or {}
theme = inp.get('theme')
lineage = inp.get('design_lineage')
notes = inp.get('aesthetic_notes')
if not (theme or lineage or notes):
    exit(0)  # no preferences to persist
exp_path = 'experiment/experiment.yaml'
with open(exp_path) as f:
    exp = yaml.safe_load(f) or {}
design = exp.setdefault('design', {})
if theme: design['theme'] = theme
if lineage: design['design_lineage'] = lineage
if notes: design['aesthetic_notes'] = notes
with open(exp_path, 'w') as f:
    yaml.safe_dump(exp, f, sort_keys=False)
print(f'Persisted design preferences: {list(design.keys())}')
"
```

If input has design fields but the write fails (YAML parse error, file missing),
emit a visible warning so the user knows preferences were dropped — do not
silently proceed:
> `WARN: /spec: failed to persist design preferences (theme / design_lineage / aesthetic_notes). These will NOT propagate to /bootstrap. Edit experiment/experiment.yaml manually before running /bootstrap.`

### 7a.1: Write EVENTS.yaml
Write the approved EVENTS.yaml to `experiment/EVENTS.yaml`.
This overwrites the template example file entirely with project-specific events.

### 7b: Write spec-manifest.json
Write `.runs/spec-manifest.json` with the full research and hypothesis details:
```json
{
  "spec_version": "1.0",
  "created_at": "<ISO timestamp>",
  "level": "<N>",
  "research": {
    "market_exists": { "finding": "...", "sources": ["..."], "confidence": "...", "verdict": "..." },
    "problem_validated": { "finding": "...", "sources": ["..."], "confidence": "...", "verdict": "..." },
    "competitive_landscape": { "finding": "...", "sources": ["..."], "confidence": "...", "verdict": "..." },
    "icp_identified": { "finding": "...", "sources": ["..."], "confidence": "...", "verdict": "..." }
  },
  "hypotheses": [
    { "id": "...", "category": "...", "statement": "...", "metric": { "formula": "...", "threshold": 0.05, "operator": "gte" }, "priority_score": 80, "experiment_level": 1, "depends_on": [], "status": "..." }
  ],
  "behaviors": [
    { "id": "...", "hypothesis_id": "...", "given": "...", "when": "...", "then": "...", "tests": ["..."], "level": 1 }
  ],
  "variants": [
    { "slug": "...", "headline": "...", "headline_word_diff_vs_others": ">30%" }
  ],
  "funnel": {
    "available_from": { "reach": "L1", "demand": "L1", "activate": "L2", "monetize": "L2", "retain": "L3" },
    "decision_framework": {
      "scale": "All tested dimensions >= 1.0",
      "kill": "Any top-funnel (REACH or DEMAND) < 0.5",
      "pivot": "2+ dimensions < 0.8",
      "refine": "1+ dimensions < 1.0 but fewer than 2 below 0.8"
    }
  }
}
```

### 7c: Validate
1. Verify experiment.yaml is valid YAML:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('experiment/experiment.yaml'))"
   ```
2. Verify EVENTS.yaml is valid and has required structure:
   ```bash
   python3 scripts/validate-events.py
   ```
3. Verify spec-manifest.json is valid JSON:
   ```bash
   python3 -c "import json; json.load(open('.runs/spec-manifest.json'))"
   ```
4. Spot-check:
   - Every hypothesis has a `metric` object with numeric `threshold`, `formula`, and `operator`
   - Every behavior traces to a hypothesis ID that exists
   - Variant headlines have >30% word difference (compare each pair)

If validation fails, fix the file and re-validate (max 2 attempts).

### 7c.1: Q-score

Run `make validate` and capture the exit code to compute the spec's Q-score:

```bash
make validate 2>&1; VALIDATE_EXIT=$?
```

Compute spec Q dimensions and write via shared script (see `.claude/patterns/skill-scoring.md`):

```bash
SPEC_Q=$(VALIDATE_EXIT=$VALIDATE_EXIT python3 -c "
import json, os

manifest = json.load(open('.runs/spec-manifest.json'))
level = manifest.get('level', 2)
level_mins = {1: 2, 2: 4, 3: 5}
min_required = level_mins.get(level, 4)

hypotheses = manifest.get('hypotheses', [])
behaviors = manifest.get('behaviors', [])
pending = [h for h in hypotheses if h.get('status') == 'pending']

validate_exit = int(os.environ.get('VALIDATE_EXIT', '0'))
q_yaml = 1.0 if validate_exit == 0 else (0.5 if validate_exit == 2 else 0.0)
q_hypothesis = round(min(len(pending) / max(min_required, 1), 1), 3)

hyp_ids_with_behavior = set(b.get('hypothesis_id') for b in behaviors)
pending_ids = set(h['id'] for h in pending)
q_behavior = round(len(pending_ids & hyp_ids_with_behavior) / max(len(pending_ids), 1), 3)

# q_metric counts ONLY pending hypotheses — per Issue #1117 schema, resolved
# hypotheses carry `evidence:` (desk-research validated), not `metric:`. Dividing
# by len(hypotheses) under-counts on Level 3 specs that include resolved
# research dimensions (#1384).
q_metric = round(sum(1 for h in pending if h.get('metric', {}).get('formula') and h.get('metric', {}).get('threshold') is not None) / max(len(pending), 1), 3)

q_variant = 1.0  # validated by Step 7c spot-check; default 1.0 if no variants

dims = {'yaml': q_yaml, 'hypothesis': q_hypothesis, 'behavior': q_behavior, 'metric': q_metric, 'variant': q_variant}
gate = 1.0 if validate_exit in (0, 2) else 0.0
verdict = 'pass' if gate == 1.0 else 'fail'
print(json.dumps(dims))
print(gate)
print(verdict)
" 2>/dev/null || echo -e '{}\n1.0\npass')

DIMS_JSON=$(echo "$SPEC_Q" | head -1)
GATE=$(echo "$SPEC_Q" | sed -n '2p')
VERDICT=$(echo "$SPEC_Q" | tail -1)
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/spec-context.json')).get('run_id', ''))" 2>/dev/null || echo "")

PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'spec',
    'dims': json.loads(os.environ['DIMS_JSON_ENV'])
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill spec || true
```

### 7c.2: Observation check

If `make validate` required fixes (did not pass on first attempt in Step 7c):

1. Collect the list of validation errors that were fixed
2. Evaluate each against `.claude/patterns/observe.md` Path 2 criteria:
   - Is the root cause in a template file? (spec skill prompt, Makefile validator, etc.)
   - Not an environment issue?
   - Not a user-specific experiment.yaml issue?
3. If any qualify -> follow observe.md's Redaction, Dedup, and Issue Creation
   procedures (mandatory execution, graceful degradation on external failures)
4. Write `.runs/observe-result.json`:
   ```json
   {
     "skill": "spec",
     "timestamp": "<ISO 8601>",
     "friction_detected": true,
     "observations_filed": "<N>",
     "verdict": "filed | no-template-issues"
   }
   ```

If `make validate` passed on first attempt -> skip this step.

### 7d: Summary
Print a summary:

```
Experiment Specification Complete
---------------------------------
Level:        [N] — [level name]
Hypotheses:   [N] ([N resolved from research], [N pending])
Behaviors:    [N] (given/when/then)
Variants:     [N]
Stack:        [services: app(runtime, hosting, ...), shared: ...]
Status:       draft

Next: Run /bootstrap to scaffold the app, or edit experiment/experiment.yaml to adjust.
```

**POSTCONDITIONS:**
- `experiment/experiment.yaml` written and valid YAML
- `experiment/EVENTS.yaml` written and validated
- `.runs/spec-manifest.json` written and valid JSON
- Q-score computed and appended to `.runs/verify-history.jsonl` <!-- enforced by agent behavior, not VERIFY gate -->
- Observation check completed (if applicable)
- Summary printed to user

**VERIFY:**
```bash
python3 -c "import json,yaml; yaml.safe_load(open('experiment/experiment.yaml')); m=json.load(open('.runs/spec-manifest.json')); assert m.get('created_at'), 'created_at empty'; assert isinstance(m.get('hypotheses'), list) and len(m['hypotheses'])>0, 'no hypotheses'; assert isinstance(m.get('behaviors'), list) and len(m['behaviors'])>0, 'no behaviors'; e=yaml.safe_load(open('experiment/EVENTS.yaml')); assert isinstance(e.get('events'), dict) and len(e['events'])>0, 'no events in EVENTS.yaml'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 7
```

**NEXT:** Skill states complete.
