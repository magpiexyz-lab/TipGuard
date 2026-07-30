# Plan Exploration Procedure

> Called by change.md Step 2 after reading context files, before Phase 1 planning.
> For /bootstrap: skip this procedure (no existing codebase to explore).

## When to Run

Run for ALL /change types. The depth of exploration varies by type:

| Change Type | Exploration Depth | Sections to Run |
|-------------|-------------------|-----------------|
| Feature     | Full              | All 5 steps     |
| Upgrade     | Full              | All 5 steps     |
| Fix         | Targeted          | Steps 0, 1, 5   |
| Polish      | Minimal           | Step 1 only     |
| Analytics   | Minimal           | Step 1 only     |
| Test        | Minimal           | Step 1 only     |

Since change type is formally classified in Step 3 (after exploration), do a **preliminary classification** based on $ARGUMENTS keywords:
- adds/creates/new/build → Feature depth
- replaces/upgrades/real/integrate → Upgrade depth
- fixes/broken/bug/error → Fix depth
- polish/improve/copy/visual → Polish depth
- analytics/tracking/events → Analytics depth
- test/spec/e2e → Test depth

If Step 3 later overrides this classification, the exploration results remain valid (Feature depth ⊇ Fix depth ⊇ Minimal depth).

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: scan src/app/ pages + src/components/ | service: scan src/app/api/ routes | cli: scan src/commands/
> Conditional points: Step 1 (Affected Area Scan), Step 2 (Route/Command Conflict), Step 4 (Reusable Components)
> Shape: interleaved-per-step

## Exploration Steps

### Step 0: Bug Triage (Fix type only)

> Only runs when preliminary classification is **Fix**. Applies `systematic-debugging.md` Phases 1-2
> to collect symptoms and generate hypotheses before exploring the codebase.

**Phase 1 — Observe** (from `systematic-debugging.md`):
1. Read the full error message, stack trace, and relevant logs available from `$ARGUMENTS`
2. Identify the exact input or action that triggers the failure (if described)
3. Note the expected behavior vs. actual behavior
4. List every observable fact — affected files, error patterns, environment clues
5. If `.runs/verify-context.json` has a `diagnostic` key from a prior failed build, include that context

**Phase 2 — Hypothesize**:
1. List up to 3 possible root causes, ranked by probability
2. Each hypothesis must be testable
3. Prefer hypotheses that explain ALL observed symptoms

Record findings as:
```
Triage:
  Symptoms: [list from Phase 1]
  Hypotheses:
    H1 (most likely): [description] — Confirm: [what to check] — Rule out: [what would disprove]
    H2: [description] — Confirm: [...] — Rule out: [...]
  Recommended investigation: [which files/areas to check first]
```

This output feeds the Fix plan template's "Root Cause Chain" section.

### Step 1: Affected Area Scan

Identify files that will be created or modified based on $ARGUMENTS:

- **web-app**: Scan `src/app/` for page folders and `src/components/` for shared components relevant to the change
- **service**: Scan `src/app/api/` for route handlers and `src/lib/` for shared utilities
- **cli**: Scan `src/commands/` for command modules and `src/lib/` for shared utilities

For each identified file:
- Read its contents
- Note its imports and exports
- Identify which other files import from it (reverse dependency)

Record findings as: "Affected files: [list]. Imports: [list]. Dependents: [list]."

### Step 2: Route/Command Conflict Check

Check if proposed new routes/commands already exist:

- **web-app**: Glob `src/app/*/page.tsx` and `src/app/*/page.ts` — list existing routes
- **service**: Glob `src/app/api/*/route.ts` and `src/app/api/*/route.tsx` — list existing endpoints
- **cli**: Glob `src/commands/*.ts` — list existing commands

Compare with what $ARGUMENTS implies will be created. Record: "Existing routes: [list]. Proposed new: [list]. Conflicts: [list or none]."

### Step 3: Schema State (if stack.database present)

Skip if `stack.database` is absent in experiment.yaml.

- Glob for migration files (e.g., `supabase/migrations/*.sql` or `migrations/*.sql`)
- Read the latest migration file (highest number)
- List existing tables and their key columns
- Note existing RLS policies

Record: "Existing tables: [list with columns]. Latest migration: [number]. RLS: [summary]."

### Step 4: Reusable Components/Patterns

Search for existing code that could serve the new feature:

- **web-app**: Scan `src/components/` for components with names or purposes matching the change. Also scan `src/lib/` for utility functions.
- **service**: Scan `src/lib/` for utility functions relevant to the change
- **cli**: Scan `src/lib/` for shared utilities

Record: "Reusable candidates: [list with file paths], or none found."

### Step 5: Naming Conventions + Planning Patterns

Sample 2-3 existing files in the area being modified. Note:
- Variable naming (camelCase vs snake_case)
- File naming convention
- Export patterns (named vs default)
- Error handling approach (throw vs return)
- Async patterns (async/await vs .then)

If auto memory has a "Planning Patterns" section, read it and note any patterns relevant to this change. Record: "Conventions: [summary]. Planning patterns: [relevant items or none]."

## Output

Store all exploration results in working memory (not a file). These results are consumed by:
1. Phase 1 plan templates — populate "How" sections with codebase-aware details
2. `.claude/procedures/plan-validation.md` — feed conflict checks

## Time Budget

Total exploration: aim for under 30 seconds. If any individual grep or read takes unusually long, skip it and note "not explored" in working memory. The plan can proceed without full exploration — this is best-effort enhancement, never a blocker.
