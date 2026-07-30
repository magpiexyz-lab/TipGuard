# Stack Promotion Lifecycle

How external service stack files graduate to pre-built category directories.

## Lifecycle Stages

### Stage 1: Auto-generated (project repos only)

During `/bootstrap`, `scaffold-externals` detects services from experiment.yaml
behaviors. Unknown services get auto-generated stack files at
`.claude/stacks/external/<service-slug>.md`. These files are project-specific
and live only in project repos.

### Stage 2: Pre-built reference (template repo)

When `/resolve` encounters repeated observations about an external service
(threshold: 2+ observations or 1 HIGH security), `state-9a` graduates the
service to a permanent, hand-curated stack file.

**Graduation target:** `.claude/stacks/<category>/<service-slug>.md` — a
purpose-specific category directory (e.g., `telephony/`, `voice/`,
`notifications/`), NOT `stacks/external/`.

State-9a automatically:
1. Proposes a category based on the service's domain (user confirms)
2. Creates the stack file in the category directory
3. Registers the new category in all registration points (archetypes,
   validators, exclusion lists, skill commands)

### Stage 3: Discovery at bootstrap

When a project runs `/bootstrap`, `scaffold-externals` searches
`.claude/stacks/*/<service-slug>.md` before generating. If a pre-built file
exists in any category directory, it uses that file instead of generating a
new one in `external/`.

## Registration Points

When a new category is created (by state-9a or manually), it must be
registered in ALL of:

| File | Field |
|------|-------|
| `.claude/archetypes/web-app.md` | `optional_stacks` |
| `.claude/archetypes/service.md` | `optional_stacks` |
| `.claude/archetypes/cli.md` | `optional_stacks` |
| `.claude/skills/bootstrap/state-2-resolve-archetype.md` | known shared categories |
| `.claude/procedures/scaffold-externals.md` | exclusion list |
| `scripts/validate-experiment.py` | `SHARED_STACK_KEYS` |
| `scripts/validators/_utils.py` | `OPTIONAL_CATEGORIES` |
| `scripts/validators/_stack_deps.py` | `SHARED_STACK_CATEGORIES` |
| `.claude/commands/bootstrap.md` | `stack_categories` |
| `.claude/commands/change.md` | `stack_categories` |
| `.claude/commands/deploy.md` | `stack_categories` |

## Exceptions

- `images/` — internal template infrastructure, not user-declared. Do not register.
- `distribution/`, `surface/` — special-purpose directories, not stack categories.
- `external/` — reserved for project-specific auto-generated files during bootstrap.
  The template repo's `external/` should only contain `.gitkeep`.
