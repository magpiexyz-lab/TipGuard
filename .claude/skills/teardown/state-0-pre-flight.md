# STATE 0: PRE_FLIGHT

**PRECONDITIONS:**
- Git repository exists in working directory

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

1. Read `experiment/experiment.yaml` — extract `name`, `type`, and `stack.surface` for validation.
   Read the archetype file at `.claude/archetypes/<type>.md` (default `web-app`).
   If archetype is `cli` and surface is `none` (only from explicit `stack.surface: none` —
   CLI defaults to `detached` since `hosting` is in `excluded_stacks`):
   - If `.runs/deploy-manifest.json` does not exist or has no `surface_url` (or
     `surface_url` is null): stop: "No cloud resources to tear down. CLI tools with no
     surface are distributed via `npm publish` — no `/deploy` infrastructure was created."
   - If the manifest exists and has a non-null `surface_url`: warn: "experiment.yaml says
     `surface: none` but the deploy manifest shows surface infrastructure exists. Proceeding
     with teardown of deployed resources."
2. Read `.runs/deploy-manifest.json`. If missing, stop: "No deploy manifest found.
   Run `/deploy` first, or delete resources manually via each provider's dashboard.
   If you deployed manually without `/deploy`, create `.runs/deploy-manifest.json`
   with the full manifest schema including optional service keys (`posthog`, `stripe`,
   etc.) matching your experiment.yaml `stack` — see `/deploy` STATE 5 for the
   complete schema."
3. If `hosting` is in the manifest: read `hosting.provider` and load the hosting stack file at
   `.claude/stacks/hosting/<provider>.md`.
   If `database` is in the manifest: read `database.provider` and load the database stack file at
   `.claude/stacks/database/<provider>.md`.
4. Check CLI installation and auth — read each stack file's `## Deploy Interface > Prerequisites`
   and run the checks (only for services present in the manifest):
   - If `hosting` in manifest: run hosting stack file's `install_check` + `auth_check`
   - If `database` in manifest: run database stack file's `install_check` + `auth_check` (skip if no Prerequisites section)
   - If `posthog` in manifest: check `~/.posthog/personal-api-key` exists
   - If `stripe` in manifest: `which stripe` + `stripe whoami` (soft — webhook
     deletion is nice-to-have)

**POSTCONDITIONS:**
- `.runs/deploy-manifest.json` exists and has been read
- experiment.yaml read and validated
- Archetype file read and surface type resolved
- Stack files loaded for services present in manifest
- CLI prerequisites checked
- `.runs/teardown-context.json` exists

**VERIFY:**
```bash
test -f .runs/teardown-context.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh teardown 0
```

**NEXT:** Read [state-1-user-confirmation.md](state-1-user-confirmation.md) to continue.
