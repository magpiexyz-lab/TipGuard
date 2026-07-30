# Technical Reference

This document is for technical teammates and template maintainers. If you're running experiments, you probably don't need this — see the [README](../README.md) instead.

## Project structure

The generated file structure depends on the archetype (`type` in experiment.yaml):

**web-app** (default):
```
src/
  app/
    api/              # API route handlers (all mutations go here)
    <page-name>/      # One folder per experiment.yaml page
      page.tsx
  components/
    ui/               # UI library components (auto-generated)
  lib/
    analytics.ts      # Analytics tracking
experiment/           # experiment.yaml lives here
supabase/migrations/  # Database migrations (when stack.database: supabase)
```

**service** (`type: service`):
```
src/
  app/
    api/
      <endpoint>/     # One folder per experiment.yaml endpoint
        route.ts
  lib/
    analytics.ts      # Server-side analytics only
experiment/
```

**cli** (`type: cli`):
```
src/
  commands/
    <command-name>.ts # One file per experiment.yaml command
  index.ts           # CLI entry point
experiment/
```

### Other files (all archetypes)

```
experiment/experiment.yaml           # Your experiment definition (edit this first)
experiment/experiment.example.yaml   # Worked example for reference
experiment/EVENTS.yaml               # Analytics event dictionary
experiment/retro-template.md         # Retrospective template
CLAUDE.md                # Rules for Claude Code (don't edit unless you know what you're doing)
.claude/commands/        # Claude Code skills
.claude/patterns/        # Shared patterns referenced by skills
.claude/stacks/          # Stack implementation files (one per technology)
.claude/archetypes/      # Archetype definitions (web-app, service, cli)
.github/                 # PR template and CI workflow
Makefile                 # Utility command shortcuts — run `make` to see all
```

## Migration setup

If your project uses `stack.database: supabase`, database migrations need to reach the remote database.

### Automatic (default with Supabase Vercel Integration)

If you deployed using the Supabase Vercel Integration (recommended), **migrations are applied automatically** during every Vercel build. No additional setup needed.

The `prebuild` script connects using `POSTGRES_URL_NON_POOLING` (injected by the integration), applies new SQL files from `supabase/migrations/`, and tracks progress in a `_auto_migrations` table.

### CI auto-migration (alternative)

If you're not using the Supabase Vercel Integration, add three GitHub repository secrets (Settings > Secrets and variables > Actions):

1. **`SUPABASE_PROJECT_REF`** — Supabase Dashboard > Settings > General > Reference ID
2. **`SUPABASE_DB_PASSWORD`** — Supabase Dashboard > Settings > Database > Database password
3. **`SUPABASE_ACCESS_TOKEN`** — [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)

Once configured, the `migrate` CI job applies pending migrations on every merge to `main`.

### Manual alternative

```bash
npx supabase login              # One-time: authenticate CLI
npx supabase link --project-ref <ref>  # One-time: link to remote project
export SUPABASE_DB_PASSWORD=your-password
make migrate
```

> **Fallback:** You can always copy SQL from `supabase/migrations/` into Supabase Dashboard > SQL Editor.

## Branch protection

After your first PR is merged, protect the `main` branch:

1. Go to **Settings > Branches** in your GitHub repo
2. Click **Add branch ruleset** for `main`
3. Enable:
   - **Require a pull request before merging**
   - **Require status checks to pass** — select `validate`, `build`, `e2e`, `preview-smoke`, and `secret-scan`
4. Save

## Stack reference

Each value maps to a stack file at `.claude/stacks/<category>/<value>.md`. Skills read these files to know which packages to install and which patterns to follow.

| Category | Available values | Default |
|----------|-----------------|---------|
| framework | `nextjs`, `hono`, `commander`, `virtuals-acp` | `nextjs` |
| hosting | `vercel`, `railway` | `vercel` |
| database | `supabase`, `sqlite` | `supabase` |
| auth | `supabase` | `supabase` |
| analytics | `posthog` | `posthog` |
| ui | `shadcn` | `shadcn` |
| payment | `stripe` | *(none — opt-in)* |
| email | `resend` | *(none — opt-in)* |
| testing | `playwright`, `vitest` | `playwright` |
| ai | `anthropic` | *(none — opt-in)* |
| telephony | `twilio` | *(none — opt-in)* |
| voice | `retell-ai` | *(none — opt-in)* |
| notifications | `slack` | *(none — opt-in)* |
| project-management | `linear` | *(none — opt-in)* |
| distribution | `google-ads`, `twitter`, `reddit` | *(none — set by /distribute)* |

## Archetype reference

| | web-app | service | cli |
|---|---------|---------|-----|
| **experiment.yaml field** | `pages` | `endpoints` | `commands` |
| **Required stacks** | framework, hosting | framework, hosting | framework |
| **Excluded stacks** | *(none)* | ui | hosting, ui, auth, payment, email |
| **Deploy model** | `/deploy` (Vercel) | `/deploy` (Vercel/Railway) | `npm publish` or GitHub Releases |
| **Distribution** | `/distribute` (ad campaigns) | Direct outreach / API docs | Package registry listing |
| **Funnel** | Default web funnel | Archetype events | Archetype events |
| **Testing** | Playwright (browser) | Vitest (API) | Vitest (CLI) |

## Extending the template

### Adding a new stack option

To support a new technology (e.g., Firebase instead of Supabase):

1. Create a stack file at `.claude/stacks/<category>/<value>.md` (e.g., `.claude/stacks/database/firebase.md`)
2. Use `.claude/stacks/TEMPLATE.md` as a starting point — it documents the required and optional sections
3. Set the corresponding `stack.<category>` value in experiment.yaml to match the filename
4. Skills automatically read your new stack file — no changes to skill files needed

> Stack files may depend on other stacks. Each file declares its assumptions in an `> Assumes:` line at the top. When swapping a stack, check the `> Assumes:` lines in related files.

> Swapping a framework or database stack may also require updates to `CLAUDE.md` (rules 9-10), the `Makefile`, `.gitignore`, and `.github/workflows/ci.yml`.

### Adding a new skill

Most changes should go through the unified `/change` skill. Only add a new skill if it has a fundamentally different workflow (e.g., analysis-only like `/iterate`).

1. Create a command file at `.claude/commands/<skill-name>.md`
2. Add YAML frontmatter with required keys: `type`, `reads`, `stack_categories`, `requires_approval`, `references`, `branch_prefix`, `modifies_specs`. See existing skill files for examples.
3. For code-writing skills: add `.claude/patterns/branch.md` and `.claude/patterns/verify.md` to the `references` list
4. Update the skills table in README.md
5. Update the skill list in CLAUDE.md Rule 0

## Production debugging

One-time setup so Claude Code can diagnose production issues directly:

```bash
make setup-prod
```

This links your local repo to your Vercel project and remote Supabase database. After setup, Claude Code can run `vercel logs`, `vercel env ls`, `supabase db execute "SELECT..."`, etc.

> **Prerequisites:** `vercel login` and `npx supabase login` must be done first.

## Make commands

Run `make` to see all available commands:

| Command | What it does |
|---------|-------------|
| `make validate` | Check experiment.yaml for valid YAML, TODOs, name format, and required fields |
| `make verify-local` | Verify the app works locally (install, test, cleanup) — needs Docker |
| `make supabase-start` | Start local Supabase for testing (requires Docker) |
| `make supabase-stop` | Stop local Supabase |
| `make test-e2e` | Run E2E tests |
| `make distribute` | Validate experiment/ads.yaml |
| `make migrate` | Push pending Supabase migrations to remote database |
| `make deploy` | Deploy to Vercel (first-time setup or manual deploys) |
| `make setup-prod` | Link Vercel + Supabase for production debugging |
| `make clean` | Remove generated files (lets you re-run bootstrap) |
| `make clean-all` | Remove everything including migrations (full reset) |
