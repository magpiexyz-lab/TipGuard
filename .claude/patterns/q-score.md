# Q-Score Reference Specification

Unified Skill Quality Framework (USQF) — defines the objective function for
measuring and optimizing skill prompt quality.

---

## Formula

```
Q_skill = Gate x (1 - R)

Gate ∈ {0, 1}:
  Gate = 1  if  build passes  AND  hard_gate_failure == false
  Gate = 0  otherwise

R ∈ [0, 1]:
  R = 0.3 x R_system + 0.7 x R_human

  R_system = 1 - mean(Q_d for d in active_scope)
           → measures how much auto-remediation agents performed
           → signal for prompt quality

  R_human  = (hard_gate_failures + exhaustions) / agents_expected
           → measures how often the system failed to self-heal
           → signal for user experience
```

## Dimension Scores

### verify-type (/bootstrap, /change, /verify, /distribute)

Extracted from agent traces in STATE 7 before cleanup:

| Dimension | Formula | Source | Scope |
|-----------|---------|--------|-------|
| Q_build | `1 - (build_attempts - 1) / 2` | build-result.json | all |
| Q_security | `1 - min((C*1.0 + H*0.5 + M*0.1) / 5, 1)` | security-merge.json | full, security |
| Q_design | `min_score / 10` | design-critic trace | full, visual |
| Q_ux | `1 - min(unresolved_dead_ends / 3, 1)` | ux-journeyer trace | full, visual |
| Q_behavior | `tests_passed / max(tests_passed + tests_failed, 1)` | behavior-verifier trace | full, security |
| Q_spec | `1 if PASS else 0` | spec-reviewer trace | full, security |

Only active-scope dimensions contribute to R_system:
- `build` scope → Q_build only
- `security` scope → Q_build, Q_security, Q_behavior
- `visual` scope → Q_build, Q_design, Q_ux
- `full` scope → all six

### spec-type (/spec) — PR 2

| Dimension | Formula | Source |
|-----------|---------|--------|
| Q_yaml | `1 if exit=0, 0.5 if exit=2, 0 if exit=1` | make validate |
| Q_hypothesis | `min(pending / level_min, 1)` | spec-manifest.json |
| Q_behavior | `with_behaviors / total_pending` | spec-manifest.json |
| Q_variant | `1 if all >30% word-diff` | spec-manifest.json |
| Q_metric | `complete_metric / total` | spec-manifest.json |

### deploy-type (/deploy) — PR 2

| Dimension | Formula | Source |
|-----------|---------|--------|
| Q_health | `services_ok / services_total` | health check JSON |
| Q_provision | `checks_passed / 7` | provision-scanner JSON |

## Pipeline Q

```
if any skill's latest Gate == 0:
    Q_pipeline = 0
else:
    Q_pipeline = geometric_mean(latest Q_skill for each skill)
```

## verify-history.jsonl Schema

Each line is a JSON object. The schema is backward-compatible — consumers use
`.get()` with defaults, so new fields are invisible to old readers.

```jsonc
{
  // Original fields (always present)
  "timestamp": "2026-03-23T10:00:00Z",
  "run_id": "2026-03-23T10:00:00Z",
  "scope": "full",
  "archetype": "web-app",
  "build_attempts": 1,
  "fix_log_entries": 3,
  "hard_gate_failure": false,
  "process_violation": false,
  "overall_verdict": "pass",

  // USQF fields (added by PR 1)
  "skill": "change",               // which skill triggered this verify run
  "dimension_scores": {             // per-agent quality dimensions
    "build": 1.0,
    "security": 0.8,
    "design": 0.7,
    "ux": 1.0,
    "behavior": 0.9,
    "spec": 1.0
  },
  "gate": 1.0,                     // binary gate (0 or 1)
  "r_system": 0.083,               // auto-remediation cost
  "r_human": 0.0,                  // human intervention cost
  "q_skill": 0.975                 // final Q score
}
```

### completion-scored — Q via execution completion

Used by skills that embed `/verify` (for their own execution Q, distinct from
the embedded verify Q) or produce no measurable agent artifacts.

| Skill | Dimensions | Formula | Source |
|-------|-----------|---------|--------|
| bootstrap | Q_states, Q_gates | `completed / expected`; `gates_passed / gates_total` | bootstrap-context.json, gate-verdicts/ |
| change | Q_states, Q_plan | `completed / expected`; `checked / total checkboxes` | change-context.json, current-plan.md |
| distribute | Q_states, Q_campaign | `completed / expected`; `1 if campaign_id else 0.5` | distribute-context.json, ads.yaml |
| resolve | Q_states, Q_fix | `completed / expected`; `1.0 (reached terminal)` | resolve-context.json |
| retro | Q_sections, Q_filed | `1.0`; `1 if issue created else 0.5` | terminal state output |
| rollback | Q_rollback, Q_health | `1 if succeeded else 0`; `1 if health passed else 0` | terminal state output |
| teardown | Q_deletion, Q_verification | `1 if manifest deleted else 0`; `1.0` | deploy-manifest.json absence |
| audit | Q_coverage, Q_findings | `1.0`; `1 if findings > 0 else 0.5` | audit-context.json, audit-manifest.json |
| solve | Q_depth, Q_output | `1 if full mode else 0.5`; `1.0` | solve-context.json |

### artifact-scored — Q via output artifact quality

| Skill | Dimensions | Formula | Source |
|-------|-----------|---------|--------|
| review | Q_yield, Q_precision | `fixed / max(fixed + disputed, 1)`; `1 - max(final - baseline, 0) / max(baseline, 1)` | review-complete.json |
| iterate | Q_data, Q_verdict | `1 if sample_size > 0 else 0.5`; `1 if verdict != TOO_EARLY else 0.5` | iterate-manifest.json |

## Write Procedure

**Shared writer:** All skills use `.claude/scripts/write-q-score.py`.
Follow `.claude/patterns/skill-scoring.md` for the calling convention.

The script implements the full Write Procedure:

1. Compute the Q entry as a JSON object per the schema above
2. Check the `SKILL_HISTORY_BACKEND` environment variable:
   - `local` (default): append JSON line to `.runs/verify-history.jsonl`
   - `api`: POST JSON to `$SKILL_HISTORY_ENDPOINT` (with `Content-Type: application/json`).
     On failure (timeout, error), fall back to `local`.
   - Any other value: skip writing (tracking disabled)
3. Print the Q score to stdout: `Q-score: <value> (Gate=<g>, R=<r>)`

## Thresholds

| Threshold | Value | Action |
|-----------|-------|--------|
| Low Q | < 0.5 | Trigger auto-observe issue to template repo (PR 2) |
| Healthy Q | >= 0.7 | No action needed |
| Perfect Q | 1.0 | Gate passed, zero remediation |

## Anti-Overfit Principles

When editing skill prompts based on Q-score data:

1. **Generalize, don't overfit** — never add a rule for a single test case
2. **Keep prompts lean** — if agents do unnecessary work, remove the causing instruction
3. **Explain why** — every constraint needs a reason, not just a rule
4. **Extract repetition** — if 3+ runs show agents rebuilding the same utility, package it

## Statistical Treatment

Q is a random variable (LLM stochasticity). Use:
- **Sliding window median** (K=5) for trend analysis
- **Stratify by (skill, scope, archetype)** — never mix scopes
- **Trend**: compare median of last 3 runs to prior 3 runs
