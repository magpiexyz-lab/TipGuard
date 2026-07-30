# STATE 2: PRIORITIZE_AND_OUTPUT

**PRECONDITIONS:**
- Parallel analysis complete with deduplicated findings (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

### Priority matrix

| | Low Effort | Medium Effort | High Effort |
|---|---|---|---|
| **High Impact** | P1 | P2 | P3 |
| **Medium Impact** | P2 | P3 | P4 |
| **Low Impact** | P3 | P4 | — |

### Delta computation

If `prior_findings` is non-empty (from Step 0):
- **New**: findings not in prior audit (by title similarity)
- **Resolved**: prior findings not in current audit
- **Persistent**: findings in both

### Report

Print the report:

```
Template Structural Audit
-------------------------
Scope: <full | hooks | commands | ...>
Files scanned: <N> .md, <N> .sh, <N> .py    Total lines: <N>
Validator baseline: <PASSED | N errors>
Prior audit: <date> (<N> findings) | none

## Duplication (<N> findings)
| # | Pattern | Occurrences | Files | Effort | Priority |
|---|---------|-------------|-------|--------|----------|
| 1 | ...     | ...         | ...   | ...    | P1       |

## Complexity Hotspots (<N> findings)
| # | File | Lines | Issue | Suggestion | Priority |
|---|------|-------|-------|------------|----------|
| 1 | ...  | ...   | ...   | ...        | P2       |

## Abstraction Opportunities (<N> findings)
| # | Pattern | Inline Count | Shared Definition | Priority |
|---|---------|--------------|-------------------|----------|
| 1 | ...     | ...          | ...               | P1       |

## Skill Architecture (<N> findings)
> If scope is not `full`, omit this section entirely.
| # | Skill | Sub-dim | Issue | Suggestion | Priority |
|---|-------|---------|-------|------------|----------|
| 1 | ...   | D1/D2/D3/D4| ...  | ...        | P2       |

## Delta (vs prior audit)
- New: <N> findings
- Resolved: <N> findings
- Persistent: <N> findings
(Or: "First audit — no prior baseline")

## Top 5 Recommendations (by priority)
1. [P1] <one-line summary + suggested next step>
2. [P1] <one-line summary + suggested next step>
3. [P2] <one-line summary + suggested next step>
4. [P2] <one-line summary + suggested next step>
5. [P3] <one-line summary + suggested next step>
```

### Manifest (if --save)

If `save_manifest` is true, write `.runs/audit-manifest.json`:
```json
{
  "timestamp": "<ISO 8601>",
  "scope": "<full|hooks|commands|...>",
  "files_scanned": {"md": "<N>", "sh": "<N>", "py": "<N>"},
  "total_lines": "<N>",
  "total_findings": "<N>",
  "findings": [
    {
      "id": "<D><N>",
      "dimension": "duplication|complexity|abstractability|skill_architecture",
      "title": "<title>",
      "impact": "HIGH|MEDIUM|LOW",
      "effort": "LOW|MEDIUM|HIGH",
      "priority": "P1|P2|P3|P4",
      "files": ["<path>"],
      "issue": "<description>",
      "suggestion": "<fix>"
    }
  ],
  "delta": {
    "new": "<N>",
    "resolved": "<N>",
    "persistent": "<N>"
  }
}
```

### Q-score

Compute audit quality (see `.claude/patterns/skill-scoring.md`):

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/audit-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
AUDIT_DIMS=$(python3 -c "
import json, os
q_findings = 0.5
if os.path.exists('.runs/audit-manifest.json'):
    m = json.load(open('.runs/audit-manifest.json'))
    q_findings = 1.0 if int(m.get('total_findings', 0)) > 0 else 0.5
print(json.dumps({'coverage': 1.0, 'findings': q_findings}))
" 2>/dev/null || echo '{"coverage": 1.0, "findings": 0.5}')
PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'audit',
    'dims': json.loads(os.environ['AUDIT_DIMS_ENV'])
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill audit || true
```

### Actionable Prompts

For each of the Top 5 recommendations above, generate a self-contained prompt block
that the user can copy-paste into a new Claude Code session. Each prompt must work
independently — include all necessary context because the target session has no
knowledge of this audit.

**Classification rule:**
- **`/solve`** — Use when the finding is architectural, cross-cutting (affects 3+ files),
  or requires first-principles tradeoff analysis. Typical for: Dimension C (abstractability)
  findings, Dimension D (skill architecture) findings, and any finding where the fix approach
  is non-obvious.
- **`plan mode`** — Use when the finding is localized, mechanical, and the fix path is clear.
  Typical for: Dimension A (textual duplication) findings, Dimension B (complexity reduction)
  findings where the suggestion is specific (e.g., "split file X at function Y").

**Format for each prompt block:**

~~~
#### Prompt N: [Finding ID] — [One-line summary]
**Approach**: `/solve` | `plan mode`
**Why this approach**: [One sentence explaining the classification]

Copy-paste into a new Claude Code session:

[Approach instruction — either "Use /solve to analyze:" or "Use plan mode for this task. Create a branch `fix/<topic>` and open a PR when done."]

## Problem

[Describe the finding in full: what is wrong, which dimension it falls under, why it matters]

## Affected Files

[List every file path from the audit finding — these are critical for the target session to locate the issue]

## Constraints

- [List relevant constraints: what cannot change, what rules apply]
- This is a template-level change — follow CLAUDE.md Rule 1 (PR-first workflow)
- Follow CLAUDE.md Rule 13 if modifying state files (state registry must sync)

## Expected Outcome

[What success looks like — e.g., "Duplicated block appears in 1 file instead of 5" or "File X is under 400 lines"]

## Verification

[How to verify the fix — e.g., "Run: grep -c 'pattern' file1 file2" or "Run: wc -l file"]
~~~

**Important rules for prompt generation:**
- Each prompt is independent — do NOT create dependency ordering between prompts
- If a finding logically depends on another (e.g., "extract shared code" must happen before
  "use shared code"), note it in the Problem section as: "Note: Consider addressing [Finding ID]
  first, as it creates the shared code this finding would use."
- Include exact file paths from the audit findings — never use placeholder paths
- For `/solve` prompts: frame as an analysis question, not an implementation instruction
- For `plan mode` prompts: include branch name suggestion and explicit PR instruction
- The prompts must respect CLAUDE.md rules: Rule 1 (PR-first), Rule 13 (state registry sync
  for skill changes), Rule 4 (minimalism)

## STOP

After printing the report and actionable prompts, **STOP**. Do not implement any changes.
The user decides which prompts to run — copy-paste any prompt into a new Claude Code session.

**POSTCONDITIONS:**
- Findings prioritized using the priority matrix
- Delta computed against prior audit (if any)
- Report printed to user
- Manifest written (if `--save` flag was set)

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/audit-analysis.json')); assert 'duplication' in d and 'complexity' in d and 'abstractability' in d, 'missing dimensions'; assert isinstance(d.get('total_findings'), int) and d['total_findings']>=0, 'total_findings invalid'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh audit 2
```

**NEXT:** Skill states complete.
