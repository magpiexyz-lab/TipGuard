# Provenance Model

The state machine and verify pipeline track three provenance dimensions, each
at the natural source-of-truth for its consumers. **There is no unified
provenance registry.** Collocated schemas have lower cognitive load and zero
dual-source-of-truth risk; the three sites already have downstream consumers
that read them directly.

This model closes three architecture issues that all stemmed from missing
provenance: #1162 (artifact lifecycle), #1151 (verdict freshness), and #1152
(executor identity for retrospective artifacts).

---

## Dimension 1: Artifact Lifecycle (state-registry.json)

**Question answered**: "Is this artifact expected to exist when its declaring
state appears in `completed_states`?"

Each state-registry.json entry can declare optional metadata:

```json
{
  "10": {
    "verify": "<command>",
    "artifact": ".runs/current-visual-brief.md",
    "lifecycle": "transient-intra-skill"
  }
}
```

Allowed `lifecycle` values:
- `durable` (default; entries without the field are durable) — survives the run.
- `transient-cross-skill` — listed in `lifecycle-init.sh` `STALE_ARTIFACTS` /
  `DELIVERY_ARTIFACTS`; gone at next skill init.
- `transient-intra-skill` — deleted by a later state of the **same** skill
  (e.g., `bootstrap state-18-commit-and-push` deletes `current-visual-brief.md`).

### Behaviors

- **`lifecycle-next.sh` resume integrity**: when a state is in `completed_states`
  AND its `lifecycle` is `durable` AND `artifact` is missing → BLOCK with
  diagnostic referencing `reset-state.sh` recovery and the
  `RESUME_INTEGRITY_OVERRIDE=1` escape hatch.
- **`lifecycle-finalize.sh` Step 2**: skips VERIFY rerun for `lifecycle != durable`.
  Eliminates the spurious `WARN: 3 VERIFY command(s) failed` noise on every
  bootstrap (#1162 root symptom).
- **Recovery primitive `reset-state.sh`**: clears state and downstream from
  `completed_states`, deletes intra-skill transient artifacts.
- **Discovery / migration**: `migrate-state-registry-lifecycle.py` enumerates
  every `.runs/<path>` reference in registry and classifies each.

### Recurrence guard

`check_artifact_transience` (verify-linter rule type) — for each registry entry
with `lifecycle != durable`, validates that the path actually appears as a
deletion source (init-cleanup or same-skill `rm -f` / imperative `- Delete`
prose). Forces future authors to declare lifecycle correctly.

### Orthogonality with `check_artifact_lifecycle`

Pre-existing `check_artifact_lifecycle` validates `produces` / `do_not_modify`
arrays — the **flow** axis (which state writes the artifact, which forbids
modification). The new `check_artifact_transience` validates the **durability**
axis (when does the artifact disappear). The two are orthogonal; both can
coexist on the same registry entry.

---

## Dimension 2: Verdict Freshness (verify-report.md frontmatter)

**Question answered**: "After Phase-2 fixers resolved issues, which Phase-1
agents now have a passing verdict?"

The frontmatter declares two parallel maps:

```yaml
agent_verdicts:                          # raw (pre-fix)
  security-defender: fail
  accessibility-scanner: fail
agent_verdicts_after_fixes:              # post-fix derived
  security-defender: pass
  accessibility-scanner: pass
agent_verdicts_after_fixes_source:
  security-defender: security-fixer.json
  accessibility-scanner: quality-fixer.json
```

### Derivation algorithm (state-7a-write-report.md)

Phase-1 agents are **NOT re-spawned**. Post-fix verdicts come from fixer traces:

| Phase-1 agent | Post-fix source | Field |
|---|---|---|
| security-defender, security-attacker | `security-fixer.json` | `unresolved_critical == 0` |
| accessibility-scanner, design-consistency-checker | `quality-fixer.json` | `unresolved_critical == 0` |
| ux-journeyer | own trace | `unresolved_dead_ends == 0` |
| design-critic | own trace (its own fixer) | unchanged |
| behavior-verifier, performance-reporter, spec-reviewer, build-info-collector | own trace | unchanged |

Recovery-stamped traces are gated through `is_trace_valid_pass(trace)`, mirroring
the AOC v1.1 hard_gate predicates from `agent-registry.json:202-213`.

### Behaviors

- **R4 hard-gate restriction** (`check-cross-artifact-consistency.py` Check 12c):
  - `overall_verdict == pass` AND `agent_verdicts_after_fixes[X] == fail` AND
    `X ∈ HARD_GATES` → BLOCK.
  - Same condition with X NOT in HARD_GATES → informational warn only
    (count_summary agents legitimately have raw `fail` after their findings
    were resolved by a fixer).
- **HARD_GATES**: `{design-critic, ux-journeyer, security-fixer, quality-fixer,
  resolve-reviewer}` per `agent-registry.json:214-275`.

### Recurrence guard

R4 schema-coverage rule (existing `check_frontmatter_artifact_consistency`)
catches drift: writer must emit every field declared in
`verify-report-frontmatter.json`, consumers must reference only declared names.
The check fires automatically once new fields are declared in the schema, which
forces the writer-update ordering.

---

## Dimension 3: Executor Identity (retrospective-result.json + lead-only-artifacts.json)

**Question answered**: "Was this artifact written by the lead conversation, or
delegated to a spawned subagent?"

### Manifest of lead-only artifacts

`.claude/patterns/lead-only-artifacts.json` declares which artifacts may **only**
be produced by the lead. Inclusion criterion: producing the artifact requires
the lead's in-memory execution context (hook-friction events, deviation
reasoning, workarounds absorbed) that does not exist in any artifact and cannot
be reconstructed from agent traces.

Initial entries: `retrospective-result.json` (Step 5a Q1/Q2/Q3 retrospective).

### Three enforcement layers

1. **`lead-deliverable-gate.sh`** (PreToolUse Agent matcher) — denies any Agent
   invocation whose prompt mentions a manifest path. Unconditional path-match
   (no verb regex — paraphrase-bypass-proof). Currently in `MODE="warn"` soak
   window; flip to `MODE="deny"` after pre-flight audit
   (`audit-lead-deliverable-references.sh`) confirms zero false positives in
   the wild.
2. **`retrospective-content-gate.sh`** (PreToolUse Write/Edit matcher) —
   when target file is in the manifest, require declared executor field
   (e.g., `step_5a_executor: "lead"`) in content. Catches direct-Write
   bypass attempts.
3. **`compliance-audit.py check_lead_deliverable_compliance`** — post-write
   audit at observation-phase. BLOCKS on missing/wrong executor field. For
   `retrospective-result.json`, also requires `observation-evidence.json`
   sibling (split-deliverable invariant — observer collects evidence, lead
   writes interpretation).

### Recurrence guard

`check_executor_enforcement` (verify-linter rule type) — three-way mapping per
manifest entry: (a) hook coverage (manifest path is referenced by at least
one PreToolUse hook); (b) schema coverage (the artifact's `schema_source`
file declares the `executor_field` name); (c) negative-deliverable coverage
(NO `.claude/agents/*.md` lists the artifact as a deliverable, unless the
file explicitly documents the lead-only constraint via "Evidence collection
only" / "lead writes" prose).

### Recovery: `reset-state.sh`

If a state in `completed_states` references a missing durable artifact,
`bash .claude/scripts/reset-state.sh <skill> <state_id>` clears the state and
downstream entries from `completed_states`, plus deletes intra-skill transient
artifacts associated with cleared states. Does NOT delete durable artifacts
(user may want to inspect them).

For one-shot override without resetting state, use
`RESUME_INTEGRITY_OVERRIDE=1 <next-command>`.

---

## Why three sites, not one?

A unified `provenance.json` was rejected as YAGNI:

- **Cognitive load**: a fresh contributor must learn one new central registry
  AND continue reading the existing per-site files. The collocated approach
  extends each existing site by one or two fields, with no new central concept.
- **Dual source of truth**: state-registry.json's per-state structure already
  exists; verify-report.md's frontmatter already exists; retrospective-result.json's
  schema already exists. Mirroring this information into a separate registry
  creates drift risk.
- **No meta-query consumer**: the unified-registry's value would be cross-cutting
  queries like "show all artifacts produced by agent X." No consumer needs this.

Empirically the codebase already uses this collocation pattern:
`attributed_to` (context), `executor` (per-agent in retrospective-result.json),
AOC v1.1 trace fields (in agent traces). The provenance dimensions are
incremental on the pattern, not a new concept.
