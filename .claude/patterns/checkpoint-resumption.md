# Checkpoint Resumption Protocol

When `.runs/current-plan.md` exists with YAML frontmatter, skills resume at the
exact checkpoint without re-deriving classification, scope, or stack.

## Protocol

1. Check if `.runs/current-plan.md` exists
2. Parse YAML frontmatter (between `---` delimiters)
3. Extract fields per the canonical schema below
4. Validate `archetype` matches current `experiment/experiment.yaml` `type` field
5. Map `checkpoint` string to the target state number (see per-skill mapping)
6. Re-read every file listed in `context_files` to reconstruct working memory
7. Jump directly to the mapped state — skip all earlier states

**Backward compatible:** No frontmatter → current behavior (start at beginning of Phase 2).

## Canonical Frontmatter Schema

| Field | Required By | Purpose |
|-------|------------|---------|
| `skill` | all | Which skill is running (`change`, `bootstrap`, `distribute`) |
| `type` | change | Change classification (Feature, Upgrade, Fix, Polish, Analytics, Test) |
| `scope` | change | Verification scope — skip re-derivation |
| `archetype` | all | Product archetype (web-app, service, cli) |
| `branch` | all | Git branch name — informational |
| `stack` | all | Map of category/value pairs — skip stack resolution |
| `checkpoint` | all | Exact resume position (maps to state) |
| `modules` | bootstrap | Ordered list of modules for unit test generation |
| `context_files` | all | Files to re-read on resume for full state reconstruction |

## Per-Skill Checkpoint Mapping

### /change

| Checkpoint | Resumes at |
|-----------|------------|
| `phase2-gate` | STATE 8 (Phase 2 preflight) |
| `phase2-step5` | STATE 9 (update specs) |
| `phase2-step6` | STATE 10 (implement) |
| `phase2-step7` | STATE 11a (verify prep) |
| `phase2-step8` | STATE 12 (commit and PR) |

### /bootstrap

| Checkpoint | Resumes at |
|-----------|------------|
| `phase2-setup` | STATE 9 (setup phase) |
| `phase2-design` | STATE 10 (design phase) |
| `phase2-scaffold` | STATE 11 (core scaffold) |
| `phase2-wire` | STATE 14 (wire phase) |
| `awaiting-verify` | STATE 19a (verify prep) |

## When to Save

Save the plan with frontmatter when the user approves (or selects "approve and clear").
The frontmatter enables resume-after-clear without re-deriving any context.
