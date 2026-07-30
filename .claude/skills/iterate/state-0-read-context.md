# STATE 0: READ_CONTEXT

**PRECONDITIONS:**
- Git repository exists in working directory

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, rows "Spec field", "Primary unit".
>
> [spec-field] web-app: `golden_path` | service: `endpoints` | cli: `commands`
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)
>
> State-specific logic below takes precedence.

Read and validate context files:

- Verify `experiment/experiment.yaml` exists. If not, stop and tell the user: "No experiment found. Create `experiment/experiment.yaml` from the template first, then run `/bootstrap`."
- If `package.json` does not exist, stop and tell the user: "No app found. Run `/bootstrap` first to create the app, then run `/iterate` to review its progress."
- Run `npm run build`. If it fails, stop and tell the user: "The app has build errors. Options: (1) Run `/change fix build errors` to let me repair the codebase automatically, then return to `/iterate`. (2) If `/change` has already been tried, run `/rollback` to revert to the last working deployment, then use `/change` to re-apply the fix. (3) Debug locally: inspect the build output above, fix the issue manually, commit, and re-run `/iterate`."
- Verify `experiment/EVENTS.yaml` exists. If not, stop and tell the user: "experiment/EVENTS.yaml not found. This file defines all analytics events and is required. Restore it from your template repo or re-create it following the format in the experiment/EVENTS.yaml section of the template."
- Check if `stack.analytics` is present in experiment.yaml. If not, warn: "No analytics stack configured -- skipping auto-query. You can provide funnel numbers manually in Step 2b, or add `analytics: posthog` to experiment.yaml `stack` and run `/change add analytics` for automated tracking." Skip auto-query in STATE 1 and proceed to manual input.
- Verify the app is deployed: check for `.runs/deploy-manifest.json`. If the file does not exist, read the archetype from experiment.yaml and warn with archetype-appropriate guidance:
  - **web-app**: "No deployment detected -- analytics only tracks live traffic. If you haven't deployed yet, run `/deploy` first, wait for traffic, then re-run `/iterate`. If you've deployed without using `/deploy` (manual deploy), you can proceed with manual funnel numbers in Step 2b."
  - **service**: "No deployment detected -- analytics only tracks live traffic. If you haven't deployed yet: for services with a surface page, run `/deploy` first; for pure API services (`surface: none`), deploy manually to your hosting provider (see the archetype file). Wait for traffic, then re-run `/iterate`. If you've deployed manually, proceed with manual funnel numbers in Step 2b."
  - **cli**: "No deployment detected -- analytics only tracks live traffic. For CLIs: publish via `npm publish` or GitHub Releases (see the archetype file), then collect usage data before running `/iterate`. If you've already published manually, proceed with manual funnel numbers in Step 2b."
  This is a warning, not a hard stop -- the user may have deployed/published manually or want to provide estimates.
- Read `experiment/experiment.yaml` -- understand the hypothesis:
  - What are we building? (`name`, `description`)
  - For whom? (`target_user`)
  - What does success look like? (`thesis`, hypothesis `metric` objects, `funnel` dimensions)
  - What behaviors exist? (`behaviors`)
  - What is the scope? (pages from `golden_path` for web-app, `endpoints` for service, `commands` for cli -- from archetype's `required_experiment_fields`)
- Read the archetype file at `.claude/archetypes/<type>.md` (type from experiment.yaml, default `web-app`). Events are defined in experiment/EVENTS.yaml as a flat map with `funnel_stage` tags -- filter by `requires` (match stack) and `archetypes` (match experiment type).
- Read `experiment/EVENTS.yaml` -- understand what's being tracked (this is the canonical list of all events)
- If `.runs/spec-manifest.json` exists, read it for hypothesis context (used in STATE 2 for per-hypothesis verdicts)

**POSTCONDITIONS:**
- `experiment/experiment.yaml` has been read and hypothesis understood
- `experiment/EVENTS.yaml` has been read and events identified
- Archetype file has been read
- Build passes (or stopped with error)
- `.runs/iterate-context.json` exists

**VERIFY:**
```bash
test -f .runs/iterate-context.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate 0
```

**NEXT:** Read [state-1-gather-data.md](state-1-gather-data.md) to continue.
