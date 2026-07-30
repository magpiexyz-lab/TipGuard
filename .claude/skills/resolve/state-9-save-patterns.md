# STATE 9: SAVE_PATTERNS

**PRECONDITIONS:**
- Side-effect scan complete (STATE 8b POSTCONDITIONS met)

**ACTIONS:**

Sediment composite patterns so future /resolve runs don't re-derive what this
run already learned. Entries travel one of two paths depending on whether this
repo is `magpiexyz-lab/mvp-template` or a downstream fork (HC1).

### Step 1 — Assemble composite trace per resolved issue

Read all of the following artifacts produced earlier in the run:

- `.runs/resolve-triage.json` — issue type, severity, action
- `.runs/resolve-reproduction.json` — `divergence_point`, `expected`, `actual`
- `.runs/resolve-clusters.json` — cluster `root_cause` per issue
- `.runs/solve-trace.json` — `problem_decomposition`, `prevention_analysis`,
  `solution_design`, `self_check`
- `.runs/agent-traces/resolve-challenger.json` — challenge verdicts
- `.runs/agent-traces/solve-critic.json` (full mode only) — TYPE A/B/C concerns
- `.runs/resolve-validation.json` — regression-check proof
- `.runs/resolve-review.json` — review counts

For each resolved issue (skip issues in `ctx.rejected_issues`), derive a
`composite_identity`:

- `root_cause_class` — keyword-canonicalized distillation of
  `solve-trace.problem_decomposition` ("missing archetype guard",
  "demo mode leak in production", "rate limit bypass", etc.). One short phrase.
- `divergence_pattern` — structural shape of `resolve-reproduction.divergence_point`
  ("env-var-check-missing", "condition-branch-absent", "validator-gap"). One phrase.
- `stack_scope` — primary stack slug inferred from `ctx.blast_radius` paths via
  the mapping `.claude/stacks/<category>/<value>.md`. Pick the stack with the
  most blast-radius hits; ties broken by first-appearance.

### Step 2 — Hash + within-run dedup

Compute the 12-char hash for each composite via
`scripts/lib/stack_knowledge_parser.py::compute_hash`. Group resolved issues by
hash. One entry per unique hash with `occurrence_count = <group size>` and
`linked_issues = [#N, …]`.

### Step 3 — Repository detection

```bash
REPO=$(gh api /repos/:owner/:repo --jq .full_name 2>/dev/null || echo "")
```

If `gh` returns non-zero: set `gh_failed=true`, leave `REPO=""`. Do NOT raise —
the VERIFY shim still passes via the legacy `patterns-saved.json` path.

### Step 4 — Upstream dedup query (per unique hash)

```bash
gh api "/search/issues?q=%5Bpattern-proposal:<HASH>%5D+in:title+repo:magpiexyz-lab/mvp-template" \
  --jq '.total_count' 2>/dev/null
```

On `gh` error: set `gh_failed=true`, record the entry in `pending_proposals`,
move on to the next entry.

### Step 5 — Dispatch

For each unique-hash entry (skip when `gh_failed=true` — already in
`pending_proposals`):

- **Upstream issue already exists** (`total_count >= 1`): comment
  `"Occurrence +1 from /resolve run <run_id>. Linked issue: #<N>."` on that
  issue. Record the URL in `proposals_filed`.
- **`REPO == "magpiexyz-lab/mvp-template"`** (template repo, no existing upstream):
  append the entry's fenced YAML to the `## Stack Knowledge` section of
  `.claude/stacks/<stack_scope>.md`. Create the section at end-of-file if
  absent. Each entry's composite_identity_hash MUST match a fresh
  `compute_hash(composite_identity)` — the PR validator rejects drift.
  **verification_snippet (M3 — required when reproduction.method ∈ {exec, validator-fed}):**
  read the linked issue's reproduction record from `.runs/resolve-reproduction.json`.
  When the `reproduction` tier is `exec` or `validator-fed`, the `evidence` field
  contains the actual reproduction command. Promote it into the SK entry's
  `verification_snippet` field, wrapping in the trinary exit contract:
  ```yaml
  verification_snippet: |
    # exit 0 = bug present (root cause reproducible today)
    # exit 1 = bug absent (root cause has been independently fixed; refresh entry)
    # exit 2 = preconditions not met (skip; package not in this stack)
    <the literal command from reproduction.evidence, adapted for project-agnostic
     execution from any repo root — replace any user-specific paths with
     mktemp -d, replace literal /tmp/X with $(mktemp -d), etc.>
  ```
  For `cite` and `grep` tier reproductions, leave `verification_snippet` field
  unset (those tiers have no executable artifact). See `.claude/stacks/TEMPLATE.md`
  schema for the full contract + example. The snippet enables future /resolve
  runs to short-circuit when the underlying bug has been resolved by a package
  upgrade — see `state-3-reproduce.md` Step 0 for the consumer side.
- **Downstream** (`REPO != "magpiexyz-lab/mvp-template"`, no existing upstream):
  file a new upstream issue:
  ```bash
  gh issue create --repo magpiexyz-lab/mvp-template \
    --label pattern-proposal \
    --title "[pattern-proposal:<HASH>] <one-line summary>" \
    --body "<fenced YAML entry + evidence block citing local issue + run_id>"
  ```
  Record the returned URL in `proposals_filed`.

On any `gh` failure during Step 5: record the entry in `pending_proposals`,
set `gh_failed=true`, print a warning, continue.

### Step 6 — Continue project auto-memory (legacy accelerator)

Also save a 1–2 line pattern summary to the project's auto memory under the
"Resolution Patterns" heading, unchanged from the prior behavior. This is a
local accelerator for the current project only.

Skip Steps 1–5 (leave `learnings=[]`, set `skipped_reason`) when all resolved
issues are trivial (typo fixes, single-character changes, etc.) unlikely to
recur.

### Step 6b — Emit anti-pattern entries (issue-body marker)

For each issue being saved, read the original issue body (fetched earlier in
the run and available via `gh issue view <N> --json body`). If it contains
the literal marker `<!-- anti-pattern: true -->`, the emitted Stack Knowledge
entry MUST set:

- `anti_pattern: true`
- `maturity: canonical` (anti-patterns are never `raw` — they encode a
  known-bad direction)
- `fix_template` describes what NOT to do at this location (the schema reuses
  the field; semantics shift on `anti_pattern`)
- `prevention_mechanism` is required and non-empty (validator, guard, test)

This is the only automated path to creating anti-pattern entries. /resolve
never self-classifies a fix as an anti-pattern.

### Step 7 — Write new artifact `.runs/resolve-learnings.json`

```bash
PAYLOAD=$(python3 -c "
import json
out = {
    'learnings': [ ... ],           # one entry per unique composite_identity_hash
    'target_stacks': [ ... ],       # stack slugs matched (e.g. framework/nextjs)
    'proposals_filed': [ ... ],     # upstream issue URLs (or [])
    'halt_events': [],              # reserved. STATE 9 never populates this in the
                                    # normal flow because a STATE 3b escalate routes
                                    # through skip_states and bypasses STATE 9
                                    # entirely; STATE 3b override does not constitute
                                    # a halt. The field is kept so the schema can
                                    # accept future halt-event emitters without a
                                    # VERIFY migration.
    'gh_failed': False,
    'pending_proposals': [],        # entries skipped due to gh failure
    'skipped_reason': ''            # set only when Steps 1-5 are skipped
}
print(json.dumps(out))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/resolve-learnings.json \
  --payload "$PAYLOAD" \
  --skill resolve
```

The `resolve-learnings-gate.sh` hook enforces the schema invariants on write.

### Step 8 — Continue writing legacy `.runs/patterns-saved.json` (shim)

For one release cycle, keep writing the legacy artifact so in-flight /resolve
runs pre-dating this PR don't break. The VERIFY accepts either artifact.

```bash
PAYLOAD=$(python3 -c "
import json
legacy = {
    'patterns_saved': [],  # parallel descriptions kept for memory-style fallback
    'skipped_reason': ''
}
print(json.dumps(legacy))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/patterns-saved.json \
  --payload "$PAYLOAD" \
  --skill resolve
```

### Step 9 — Append convergence history

After the learnings artifact is written, append one line to
`.runs/convergence-history.jsonl` (create if absent) summarizing this run.
This log is consumed only by `.claude/scripts/convergence-report.py` — no
skill state reads it during execution.

```bash
python3 -c "
import json, os, datetime
ctx = json.load(open('.runs/resolve-context.json'))
causal_path = '.runs/resolve-causal-analysis.json'
causal = json.load(open(causal_path)) if os.path.exists(causal_path) else {}
dps = causal.get('divergence_points_analyzed', []) or []
osc_sum = sum(int(dp.get('oscillation_count') or 0) for dp in dps)
patterns = [dp['anti_pattern_match']['id'] for dp in dps if dp.get('anti_pattern_match')]
files_touched = sorted({dp.get('divergence_point','').split(':',1)[0] for dp in dps if dp.get('divergence_point')})
entry = {
    'run_id': ctx.get('run_id',''),
    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'divergence_points_analyzed': len(dps),
    'oscillation_count_sum': osc_sum,
    'halted': bool(causal.get('halted')),
    'files_touched': files_touched,
    'patterns_matched': patterns,
}
with open('.runs/convergence-history.jsonl', 'a') as f:
    f.write(json.dumps(entry) + '\n')
"
```

**POSTCONDITIONS:**
- `.runs/resolve-learnings.json` exists with required schema fields
- `.runs/patterns-saved.json` exists (shim — legacy schema)
- In the template repo: matched `.claude/stacks/<slug>.md` files have new/updated
  `## Stack Knowledge` entries (or section skipped due to `gh_failed`)
- In a downstream repo: `proposals_filed` lists upstream pattern-proposal issue
  URLs (or `pending_proposals` records what was skipped)
- Resolution-pattern summary saved to auto memory (legacy accelerator)

**VERIFY:**
```bash
python3 -c "import json, os; r='.runs/resolve-learnings.json'; l='.runs/patterns-saved.json'; assert os.path.exists(r) or os.path.exists(l), 'no learnings artifact'; d=json.load(open(r if os.path.exists(r) else l)); new_schema=isinstance(d.get('learnings'), list); legacy_schema=isinstance(d.get('patterns_saved'), list); assert new_schema or legacy_schema; assert (not new_schema) or ('proposals_filed' in d and 'halt_events' in d)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 9
```

**NEXT:** Read [state-9a-graduate-external.md](state-9a-graduate-external.md) to continue.
