# Stack Dependency Validation

Canonical dependency matrix for experiment.yaml stack validation.
Referenced by bootstrap (state-3) and change (state-5) precondition checks.

## Dependency Matrix

| Stack | Requires | Error guidance |
|-------|----------|---------------|
| payment | auth + database | "Payment requires authentication to identify the paying user / a database to record transaction state." |
| email | auth + database | "Email requires authentication to know who to send to / a database to track activation status." |
| auth_providers | auth | "OAuth providers require an auth system." |

## Compatibility Constraints

| Constraint | Rule |
|-----------|------|
| testing: playwright | Incompatible with service/cli archetypes — use vitest instead |
| framework: nextjs | Required for web-app archetype |
| framework: commander | Required for cli archetype |
| framework: (any) | Allowed for service archetype |
| (always) | Requires stack.testing present |

## Error Message Templates

Use these canonical error messages when a dependency is unmet. Replace `<provider>` with
the missing provider suggestion (e.g., `supabase`).

| Stack | Missing | Error message |
|-------|---------|--------------|
| payment | auth | "Payment requires authentication to identify the paying user. Add `auth: <provider>` (or another auth provider) to your experiment.yaml `stack` section." |
| payment | database | "Payment requires a database to record transaction state. Add `database: <provider>` (or another database provider) to your experiment.yaml `stack` section." |
| email | auth | "Email requires authentication to know who to send emails to. Add `auth: <provider>` (or another auth provider) to your experiment.yaml `stack` section." |
| email | database | "Email requires a database to track user activation status. Add `database: <provider>` (or another database provider) to your experiment.yaml `stack` section." |
| auth_providers | auth | "OAuth providers require an auth system. Add `auth: supabase` to your experiment.yaml `stack` section." |
| testing: playwright | service/cli archetype | "Playwright requires a browser and is not compatible with the `<archetype>` archetype. Use `testing: vitest` instead." |

For `/change` context, append branch cleanup per `.claude/patterns/branch-cleanup-error-template.md` (Variant A, recovery: 'make the required changes, then re-run `/change`').

## Assumes-List Validation

Stack files may declare an `assumes` list in frontmatter (e.g., `assumes: [framework/nextjs]`).
Each `category/value` pair must match experiment.yaml stack exactly — category presence alone is insufficient.
Example: `database/supabase` requires `stack.database: supabase`, not just any database provider.

When an assumption is unmet, stop with a message listing the specific unmet dependencies and current stack values.
