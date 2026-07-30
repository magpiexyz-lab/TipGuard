# STATE 2: TRIAGE

**PRECONDITIONS:**
- Context files read (STATE 1 POSTCONDITIONS met)
- Optional: parse `## Stack Knowledge` sections across every path returned by
  `scripts/lib/stack_knowledge_parser.iter_stack_knowledge_files()` (single
  source of truth — currently `.claude/stacks/**/*.md` plus
  `.claude/scripts/lib/README.md`) using `parse_stack_knowledge`. Absent
  section = empty list; missing files = empty list (HC3 — never blocking).

**ACTIONS:**

Read `resolve-context.json` and check the `mode` field.

**If `mode == "refine"`:**
- Issues with label `refine` (trace-derived): type is fixed as "Gap", severity was already determined in STATE 0, action is "fix"
- Issues with label `observation`: classify using the standard 10-type system below
- Present the unified triage table and STOP for user approval (same as normal mode)

**If `mode` is not `"refine"`:** proceed with normal classification below.

Classify each issue into one of 10 types:

**Actionable (proceed to Phase 2):**

| Type | Description |
|------|-------------|
| Bug | Template file produces incorrect output or broken code |
| Gap | Missing handling for a valid configuration |
| Inconsistency | Two template files contradict each other |
| Regression | Previously working behavior now broken |
| Observation | Filed by observe.md — template-rooted issue from a project |

**Architectural (defer to /solve, skip Phase 2):**

| Type | Criteria |
|------|----------|
| Architectural | Issue describes changes to CLAUDE.md structure, state-registry.json, state machine flow, skill contracts, or cross-skill systemic concerns. Requires design-level analysis beyond auto-fix scope. |

**Architectural Smell Test** — evaluate for EVERY issue before assigning a type:

1. Does the root cause involve a pattern or mechanism used by more than one skill?
2. Does the suggested fix have 2+ fundamentally different design options?
3. Would fixing this in one file leave the same problem latent in other skills?
4. Does the issue touch state-registry.json, CLAUDE.md structure, or skill contracts?

If ANY answer is YES → classify as Architectural (defer to /solve).
Principle: err on the side of deferring — false Architectural classifications
are cheap (one /solve run), false Bug classifications risk incomplete fixes.

For architectural issues, post a comment and apply the `architecture` label:
```bash
gh issue comment <N> --body "**Deferred: Architectural Issue**

This observation describes a template-architecture concern that requires first-principles design analysis.

**Recommended next step:**
\`/solve \"Issue #<N>: <title>\"\`"
```

Apply the `architecture` label and remove `observation` label (if present) so future `/resolve` runs skip this issue:
```bash
# Create label if it doesn't exist (idempotent)
gh label create "architecture" --description "Architectural issue deferred to /solve" --color "d4c5f9" 2>/dev/null || true
gh issue edit <N> --add-label "architecture"
# Remove observation label so /resolve won't pick this up again
gh issue edit <N> --remove-label "observation" 2>/dev/null || true
```

If `gh issue edit` fails: embed `**Label:** architecture (create this label for filtering)` in the defer comment body as fallback.

### Cross-Batch Architectural Consolidation

Before within-batch clustering, check whether any newly classified architectural issues share a root cause with **existing** open architecture issues from previous /resolve runs.

**Step 0 — Fetch existing architecture issues:**
```bash
gh issue list --label architecture --state open --json number,title,body --limit 50
```

**Important:** The current batch's issues were just labeled `architecture` (lines above), so they will appear in this result. Exclude all issue numbers from the current batch before matching — cross-batch consolidation only matches against issues from **previous** /resolve runs.

If the result is empty after excluding current-batch issues, or the command fails: skip this entire section (graceful degradation — proceed to within-batch consolidation).

**Step 1 — Match each new architectural issue against existing pool:**

For each newly classified architectural issue in this batch, compare its root cause against each existing open architecture issue. Use the same causal-pattern matching as STATE 4b: look for shared structural root cause, not surface-level keyword overlap.

Matching criteria (any one sufficient):
- The new issue's root cause is a specific instance of the existing issue's root cause
- Both issues cite the same structural mechanism (e.g., "lifecycle engine lacks skip-to", "worktree isolation policy is uniform")
- Fixing the existing issue would resolve or subsume the new issue

Distinguish between two existing issue formats:
- **Individual issues**: title starts with `[observe]` or `[template]`. Root cause is in the body's analysis sections.
- **Consolidated issues**: title starts with `[Architecture]`. Body contains `## Consolidated Architectural Issue` header with `**Root cause**:` line and `### Symptoms` table.

If a new issue matches multiple existing issues, pick the most specific one (the existing issue whose root cause most precisely subsumes the new issue).

**Step 2 — For each match, consolidate into existing issue:**

**Case A — Existing issue is an individual (non-consolidated) issue:**

First, read the existing issue body to preserve its analysis:
```bash
EXISTING_BODY=$(gh issue view <EXISTING> --json body --jq '.body')
```

Extract the root cause, analysis, and suggested changes from `EXISTING_BODY` to incorporate into the consolidated `### Context for /solve` section below.

Convert the existing issue to consolidated format:
```bash
gh issue edit <EXISTING> \
  --title "[Architecture] <root-cause-summary-in-imperative-form>" \
  --body "$(cat <<'BODY'
## Consolidated Architectural Issue

**Root cause**: <1-2 sentence root cause hypothesis>
**Cluster size**: 2 issues

### Symptoms

| # | Title | Severity | Symptom |
|---|-------|----------|---------|
| #<EXISTING> | <existing-title> | <severity> | <one-line symptom from existing> |
| #<NEW> | <new-title> | <severity> | <one-line symptom from new> |

### Context for /solve

<Why these are the same root cause, what design options exist,
what constraints apply. Preserve relevant analysis from both
the existing issue body and the new issue body.>

### Original Issues
- #<EXISTING> (original observation — now the tracking issue)
- #<NEW> (closed — merged into this issue)

---
*Auto-consolidated by /resolve triage (cross-batch).*
BODY
)"
```

**Case B — Existing issue is already a consolidated issue:**

Read the existing body and update it:
- Increment `**Cluster size**:` by 1
- Add a row to the `### Symptoms` table for the new issue
- Add `- Closes #<NEW>` to the `### Original Issues` section
- Append relevant context from the new issue to `### Context for /solve`

```bash
gh issue edit <EXISTING> --body "<updated-body>"
```

**Step 3 — Close new issue with cross-reference:**

```bash
gh issue close <NEW> --comment "Consolidated into #<EXISTING>. Root cause: <summary>. Track resolution at #<EXISTING>."
```

**Step 4 — Remove matched issues from batch:**

Remove cross-batch matched issues from the batch's architectural issue list so within-batch clustering does not re-process them. If `gh issue edit` or `gh issue close` fails for any match: leave both issues open with their `architecture` labels (graceful degradation — /solve processes them individually).

**Step 5 — Update triage artifact for cross-batch matches:**

For each cross-batch consolidated issue, record it in the `issues` array:
- `{"number": <NEW>, "type": "architectural", "severity": "<severity>", "action": "defer", "consolidated_into": <EXISTING>}`
- Increment `cross_batch_consolidated_count` by the number of issues merged into existing architecture issues

### Within-Batch Architectural Consolidation (when 2+ unmatched architectural issues)

If only 0 or 1 architectural issue remains after cross-batch consolidation: skip this section.

If 2+ issues classified as Architectural remain unmatched after cross-batch consolidation:

**Step 1 — Root-cause clustering:** Compare the architectural issues and group those
sharing the same structural root cause. Same logic as STATE 4b: look for shared causal
patterns (e.g., "3 issues all caused by missing cross-skill guard in state-registry.json"
= 1 cluster). Unclustered issues remain as individual deferred items.

**Step 2 — Create consolidated issue per cluster** (for each cluster of 2+ related issues):

```bash
gh issue create \
  --label "architecture" \
  --title "[Architecture] <root-cause-summary-in-imperative-form>" \
  --body "$(cat <<'BODY'
## Consolidated Architectural Issue

**Root cause**: <1-2 sentence root cause hypothesis>
**Cluster size**: <N> issues

### Symptoms

| # | Title | Severity | Symptom |
|---|-------|----------|---------|
| #A | <title> | high | <one-line symptom> |
| #B | <title> | medium | <one-line symptom> |

### Context for /solve

<Why these are the same root cause, what design options exist,
what constraints apply. This section is the input for
`/solve "Issue #<this-number>: <title>"`.>

### Original Issues
- #A (closed — merged into this issue)
- #B (closed — merged into this issue)

---
*Auto-consolidated by /resolve triage.*
BODY
)"
```

If `gh issue create` fails: fall back to leaving original issues open with their
individual `architecture` labels and defer comments (graceful degradation — /solve
processes them individually).

**Step 3 — Close originals with cross-reference:**

```bash
gh issue close <A> --comment "Consolidated into #<consolidated>. Root cause: <summary>. Track resolution at #<consolidated>."
gh issue close <B> --comment "Consolidated into #<consolidated>. Root cause: <summary>. Track resolution at #<consolidated>."
```

**Step 4 — Update triage artifact:** Replace original entries with consolidated entry
in the `issues` array:
- Remove original issue entries
- Add: `{"number": <consolidated>, "type": "architectural", "severity": "<highest of cluster>", "action": "defer", "consolidated_from": [A, B]}`
- Add `consolidated_count` field to the triage object
- Unclustered architectural issues remain as-is

**Non-actionable (handle now, skip Phase 2):**

| Type | Action |
|------|--------|
| Environment | Comment: "This is an environment issue, not a template bug. [specific guidance]." Close. |
| User error | Comment: "This appears to be project-specific. [explain why]. Reopen if you believe this is a template issue." Close. |
| Duplicate | Comment: "Duplicate of #N." Close. |
| Stale | The described problem no longer exists in current code. Verify with a lightweight check: (1) `git log --oneline --since="<issue_created_date>" -- <cited_file>` — if the file was modified since the issue was filed, (2) read the cited file and confirm the specific pattern/text described in the issue is gone or fixed. Only classify as Stale when evidence is clear; ambiguous cases should proceed to Phase 2. Comment: "Verified against current main — this was fixed in [commit/PR]. [brief explanation]." Close. |
| Won't fix | Comment with rationale. Label `wontfix`. Close. |

For non-actionable issues, execute the close/comment actions now:
```bash
gh issue close <N> --comment "<comment>"
```

Present a triage table:

```
| # | Title | Type | File(s) | Severity | Action |
|---|-------|------|---------|----------|--------|
```

Severity levels: HIGH (breaks execution), MEDIUM (wrong output), LOW (cosmetic).

If all issues are non-actionable or architectural (all closed or deferred in this state): report "All issues
resolved as non-actionable or deferred — no Phase 2 diagnosis needed." If architectural issues were consolidated
(within-batch or cross-batch), report the consolidated issue number(s) and recommend `/solve "Issue #<N>: <title>"`
for each. For cross-batch consolidations, report: "Issue #NEW consolidated into existing #EXISTING (<root-cause>)."
Stop here.

### Pattern hints (advisory — zero-assumption first)

After default classification completes, for every issue classified as actionable
(Bug / Gap / Inconsistency / Regression / Observation), compute a preliminary
`composite_identity` using the same keys as STATE 9
(`root_cause_class`, `divergence_pattern`, `stack_scope`) and the same
canonicalization + 12-char sha1 hash (`scripts/lib/stack_knowledge_parser.py::compute_hash`).

For each issue, query matching entries from the Stack Knowledge index loaded in
PRECONDITIONS. A match is an entry whose `composite_identity_hash` equals the
issue's preliminary hash.

Record matches as `pattern_hints` — advisory only. They do NOT replace the
default classification, do NOT change the triage table presentation, and do NOT
skip the user-approval STOP below. They inform downstream states (5, 5d, 7).

**STOP. Present the triage table to the user and wait for approval before
proceeding to Phase 2.** The user may reclassify issues or remove them from scope.

- **Write triage artifact** (`.runs/resolve-triage.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  triage = {
      'issues': [
          {'number': 0, 'type': '<bug|gap|inconsistency|regression|observation|architectural>', 'severity': '<high|medium|low>', 'action': '<fix|close|defer>'}
          # Within-batch consolidated entries add: 'consolidated_from': [A, B]
          # Cross-batch consolidated entries add: 'consolidated_into': <existing-issue-number>
      ],
      'actionable_count': 0,
      'closed_count': 0,
      'deferred_count': 0,
      'consolidated_count': 0,  # within-batch consolidated issues created (0 if no consolidation)
      'cross_batch_consolidated_count': 0,  # issues merged into existing architecture issues
      'pattern_hints': []  # optional; [{'issue': N, 'id': '<entry-id>', 'stack_file': '<path>', 'maturity': '<m>', 'occurrence_count': <int>, 'fix_template': '<string>'}, ...]
  }
  print(json.dumps(triage))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-triage.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

**POSTCONDITIONS:**
- All issues classified with type, severity, and action
- Non-actionable issues closed with comments
- Triage table presented to user
- User has approved the triage before proceeding
- `.runs/resolve-triage.json` exists with `issues` array

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/resolve-triage.json')); assert isinstance(d.get('issues'), list) and len(d['issues'])>0, 'issues missing or empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 2
```

**NEXT:** If all issues were non-actionable or deferred (all closed/deferred above), skill is complete — TERMINAL. Otherwise, read [state-3-reproduce.md](state-3-reproduce.md) to continue.
