# Remediation Phase — Post-Epilogue Gap Detection

> **Called by `finalize-epilogue.md` Step 2.5 after observation completes.**
> Detects execution gaps and presents actionable follow-up prompts.
> Mandatory execution, graceful degradation. Failure writes empty remediation.json
> with error reason and continues — do not silently skip.

## Parameters

- **skill**: the active skill name (from `*-context.json`)

## Step 1: Read verify-recheck.json

```python
import json, os
if not os.path.isfile('.runs/verify-recheck.json'):
    json.dump({"skill": "<skill>", "gaps": [], "total_gaps": 0, "skipped": "no-recheck-data"},
              open('.runs/remediation.json', 'w'), indent=2)
    # STOP — no remediation data available
```

If absent: write empty `remediation.json` and **STOP**.

Parse `failed`, `verify_results`, `missing_states`, `delivery_status`.

## Step 2: VERIFY Failure Prompts

### Step 2a: Skip when no delivery occurred

If `delivery_status` from verify-recheck.json is `"none"`, the skill did not
produce code (analysis-only: solve, audit, iterate, retro, rollback, teardown).
Their VERIFY commands check artifact existence which is trivially satisfied by
the skill itself. VERIFY failures for these skills indicate broken
infrastructure, not actionable user gaps.

If `delivery_status == "none"`: **skip to Step 3** (agent concerns only).

If `failed == 0` AND `missing_states` is empty: **skip to Step 3**.

### Step 2b: Extract POSTCONDITIONS for failed states

For each entry in `verify_results` where `passed == false`:

1. Locate the state file: glob `.claude/skills/{skill}/state-{state_id}-*.md`; fall back
   to `.claude/patterns/state-{state_id}-*.md` for shared terminal states (e.g. state 99)
2. Extract text between `**POSTCONDITIONS:**` and the next line starting with `**`
3. Each bullet line (starting with `- `) is one postcondition

```python
import glob, re

def extract_postconditions(skill, state_id):
    pattern = f'.claude/skills/{skill}/state-{state_id}-*.md'
    files = glob.glob(pattern)
    if not files:
        # Try base skill name for mode-qualified skills (iterate-check -> iterate)
        base = skill.split('-')[0] if '-' in skill else skill
        files = glob.glob(f'.claude/skills/{base}/state-{state_id}-*.md')
    if not files:
        # Shared terminal states (e.g. state-99-epilogue.md) live under .claude/patterns/
        files = glob.glob(f'.claude/patterns/state-{state_id}-*.md')
    if not files:
        return []
    content = open(files[0]).read()
    match = re.search(r'\*\*POSTCONDITIONS:\*\*\n(.*?)(?=\n\*\*)', content, re.DOTALL)
    if not match:
        return []
    lines = match.group(1).strip().split('\n')
    return [line.lstrip('- ').strip() for line in lines if line.strip().startswith('- ')]
```

### Step 2c: Generate prompts

For each failed state, generate a follow-up prompt using 3 components:
- **State ID** for traceability
- **POSTCONDITION prose** (what should be true)
- **VERIFY error** from verify-recheck.json (what actually failed)

All prompts are **post-merge follow-ups** (delivery already happened by the
time remediation runs).

**Prompt template:**
```
/change --type Fix "State {state_id}: {postcondition_summary}. Error: {verify_error}"
```

For missing states (in `missing_states` but not in `verify_results`):
```
State {id} was not completed during execution. Review the skill flow and
determine if this state needs to be run separately.
```

## Step 3: Detect Unresolved Agent Concerns

Read agent traces from `.runs/agent-traces/` for adversarial agents.
Missing trace files are silently skipped (not gaps).

### solve-critic

Read `.runs/agent-traces/solve-critic.json`:
- The trace always reflects the **last critic round** (round 2 overwrites
  round 1). If `type_a_count > 0` in the trace, those concerns were not
  resolved during the critic loop.
- For each concern where `type == "A"`: generate a remediation gap

Prompt: `Review .runs/agent-traces/solve-critic.json — unresolved TYPE A: {description}`

### resolve-challenger

Read `.runs/agent-traces/resolve-challenger.json`:
- For each verdict where `label` is `"challenged"` or `"needs-revision"`:
  generate a gap

Prompt: `Review .runs/agent-traces/resolve-challenger.json — challenged fix: {challenge}`

### review-challenger

Read `.runs/agent-traces/review-challenger.json`:
- For each verdict where `label` is `"disputed"` or `"needs-evidence"`:
  generate a gap

Prompt: `Review .runs/agent-traces/review-challenger.json — disputed finding: {counterexample}`

## Step 4: Write remediation.json

```json
{
  "skill": "<skill-name>",
  "timestamp": "<ISO 8601>",
  "delivery_status": "<from verify-recheck.json>",
  "gaps": [
    {
      "source": "verify_failure",
      "state": "<state_id>",
      "postcondition": "<postcondition text or null>",
      "error": "<verify stderr>",
      "prompt": "<generated prompt>"
    },
    {
      "source": "missing_state",
      "state": "<state_id>",
      "prompt": "<generated prompt>"
    },
    {
      "source": "agent_concern",
      "agent": "<agent-name>",
      "description": "<concern description>",
      "prompt": "<generated prompt>"
    }
  ],
  "total_gaps": "<N>"
}
```

## Step 5: Terminal Output

If `total_gaps == 0`: **no output** (clean run, silent exit).

If `total_gaps > 0`:

```
--- Remediation Suggestions ({N} gap(s)) ---

1. [VERIFY] State {id} — {postcondition_summary}
   Error: {verify_error}
   Run: /change --type Fix "State {id}: {summary}"

2. [AGENT] {agent} — {description}
   Run: Review .runs/agent-traces/{agent}.json

These are post-delivery follow-ups. Run the suggested prompts to address gaps.
Full details: cat .runs/remediation.json
```

## Constraints

- **Best-effort.** Any failure: write `{"gaps": [], "total_gaps": 0}` and continue.
  Never block the skill.
- **Post-merge context.** All prompts assume delivery already happened.
  Do not suggest reverting or blocking delivery.
- **No observation data.** Observations are template issues fixed via `/upgrade`.
  Remediation handles execution gaps only.
- **No-delivery skills.** When `delivery_status == "none"`, skip VERIFY
  remediation. Only check agent traces.
