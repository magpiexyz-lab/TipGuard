# STATE 0: INPUT_PARSE

**PRECONDITIONS:**
- Git repository exists in working directory

**ACTIONS:**

Parse `$ARGUMENTS` for:
- **Idea text**: the main argument (everything except flags)
- **Level**: always `3` (Full MVP). The `--level` flag is accepted for backwards compatibility but the value is always overridden to 3.
- **Design preferences** (optional, persisted to `experiment.yaml.design` in STATE 7):
  - `--theme <light|dark|auto>` — hard constraint on globals.css color tokens
  - `--design-lineage "<Brand1, Brand2, ...>"` — comma-separated list of reference brands (e.g., `"Linear, Vercel, Rauno Freiberg"`). Parsed into a list.
  - `--aesthetic "<freeform notes>"` — soft creative direction for `scaffold-init`

Persist parsed design fields into `.runs/spec-context.json.input` (create `input` dict if absent):
```bash
python3 -c "
import json, os
ctx_path = '.runs/spec-context.json'
ctx = json.load(open(ctx_path)) if os.path.exists(ctx_path) else {}
ctx.setdefault('input', {})
# Set only when the corresponding flag was provided — omit the key otherwise so
# STATE 7 can distinguish 'unset' from 'explicit empty'.
# theme = <parsed from --theme>
# design_lineage = <parsed list from --design-lineage, split on comma, stripped>
# aesthetic_notes = <parsed from --aesthetic>
json.dump(ctx, open(ctx_path, 'w'), indent=2)
"
```

If none of the design flags are provided, omit the `input.theme` / `input.design_lineage` / `input.aesthetic_notes` keys entirely — STATE 7 checks for presence.

Level 3 — Full MVP: auth + database + core feature + payments (if applicable). Tests the complete funnel from reach to monetization. This is the default because a full MVP takes ~2 hours to build with the template, and running ads against anything less wastes budget on incomplete funnels.

### Fallback
If `$ARGUMENTS` is empty or contains only a level flag:
- Check if `experiment/experiment.yaml` exists and has non-TODO `thesis` and `description` fields.
  If so, extract the idea text from those fields and confirm with the user:
  > Found existing thesis/description in experiment.yaml. Using this as the idea input:
  > "[extracted text]"
  > Proceed? (yes/no)
- If experiment.yaml doesn't exist or fields are still TODO: stop with:
  > **Usage:** `/spec <idea description> [--level 1|2|3]`
  >
  > Example: `/spec Freelancers waste hours on invoicing. A tool that generates invoices from time logs. --level 2`
  >
  > Provide at least a sentence describing the problem and proposed solution.

### Guards
- If the idea text (excluding flags) is fewer than 20 characters: stop with:
  > That's too brief. Describe the problem and solution in at least a sentence so I can generate meaningful hypotheses.
- If the level flag is provided with a value other than 3: log "Level overridden to 3 (Full MVP is the standard for ad-ready MVPs)" and continue with level 3.

### Input Sufficiency Check

After confirming the idea text and level, assess 3 information dimensions in the parsed input:

| Dimension | What to look for | Example (sufficient) |
|-----------|-----------------|---------------------|
| **Target user** | A describable person, not just "people" or "users" | "freelancers billing <5 clients/month" |
| **Problem** | A stated pain with some specificity | "wastes 2-3 hours/week on manual invoicing" |
| **Solution shape** | A proposed mechanism, not just a category | "single-page tool that generates invoices from time logs" |

For each dimension, classify as:
- **present** — explicitly stated in the input
- **inferable** — can be reasonably derived (mark as assumption)
- **missing** — cannot be determined

#### Decision logic

- **All 3 present/inferable** -> show assumptions inline with the Confirm (zero added latency), proceed to Step 2
- **1 missing** -> ONE follow-up message asking exactly what's missing, with `proceed` escape hatch
- **2-3 missing** -> input too vague, ask user to elaborate (no escape hatch)

#### Rules
- Maximum ONE round of follow-up — never enter a Q&A loop
- Inference-first — if you can reasonably infer, don't ask
- Show inferences — let user confirm or correct
- Merge follow-up answers with original input, then continue to Step 2 (no re-check)
- `proceed` escape hatch — user can skip and let AI infer everything

### Confirm
Display the parsed input and confirm before proceeding:
> **Idea:** [parsed idea text]
> **Level:** 3 — Full MVP
>
> Understanding:
> [present/inferable/missing status for each dimension]
>
> Proceed with this? (yes / rephrase)

Wait for user confirmation.

**POSTCONDITIONS:**
- Idea text parsed (>= 20 characters)
- Level is 3 (always)
- Input sufficiency assessed (all 3 dimensions present/inferable, or follow-up completed)
- User confirmed input
- `.runs/spec-context.json` exists

**VERIFY:**
```bash
test -f .runs/spec-context.json && python3 -c "import json,glob; d=json.load(open('.runs/spec-context.json')); ctx=None
for f in glob.glob('.runs/*-context.json'):
    if 'epilogue' in f: continue
    try: c=json.load(open(f))
    except: continue
    if c.get('completed') is True: continue
    if ctx is None or (c.get('timestamp','') > (ctx.get('timestamp','') or '')): ctx=c
active_skill=ctx.get('skill','') if ctx else ''
active_run_id=ctx.get('run_id','') if ctx else ''
assert d.get('skill') == active_skill, 'spec-context.json skill=%r does not match active_skill=%r (stale prior-skill artifact)' % (d.get('skill'), active_skill)
assert d.get('run_id') == active_run_id, 'spec-context.json run_id=%r does not match active_run_id=%r (stale artifact)' % (d.get('run_id'), active_run_id)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 0
```

**NEXT:** Read [state-1-research.md](state-1-research.md) to continue.
