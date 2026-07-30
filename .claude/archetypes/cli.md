---
description: "Command-line tool distributed via package registry, no server hosting"
required_stacks: [framework, testing]
optional_stacks: [database, analytics, ai, telephony, voice, notifications, project-management]
excluded_stacks: [hosting, ui, auth, payment, email]
required_experiment_fields: [commands]
build_command: "npm run build"
---

# CLI Archetype

Command-line tool invoked by users on their local machine. The primary unit of
work is the **command** (not the page or endpoint). Use this archetype when
`type: cli` is set in experiment.yaml.

## Structure

Each experiment.yaml `commands` entry maps to a command module:

```
src/commands/<command-name>.ts
```

There are no page folders, no landing page, no UI components, no API routes,
no `src/app/` directory, and no `src/components/` directory. The `hosting`,
`ui`, `auth`, `payment`, and `email` stack categories are excluded.

## Funnel

Events are defined in experiment/EVENTS.yaml with `funnel_stage` tags. Event names are project-specific — /spec generates them from behaviors and hypotheses. Filter by `requires` and `archetypes` fields based on experiment stack. CLI-specific events should have `archetypes: [cli]`.

When a surface is configured (default: `detached`), the surface fires a reach-stage event — providing a complete acquisition → activation → retention funnel.

Expected funnel stages:
1. **reach** — user loads the detached marketing page (surface event, inline snippet)
2. **reach** — user executes a CLI command (product event, `archetypes: [cli]`)
3. **activate** — user completes the core action for the first time (server-side event)
4. **retain** — user runs the CLI again after 24+ hours since last use (server-side event)

Surface events use an inline analytics snippet (see analytics stack file and surface stack file). Product events use opt-in `trackServerEvent()` from the server analytics library. Analytics must be opt-in — check for a consent flag or environment variable before sending any telemetry. See the analytics stack file's CLI Opt-In Consent section (`.claude/stacks/analytics/<value>.md`) for the implementation pattern, environment variable names, and guard function.

## Testing

CLIs use unit tests and CLI integration tests (e.g., Vitest, Jest), not
browser-based E2E tests (Playwright). The test runner comes from the testing
stack file.

CLI integration tests spawn the compiled binary and assert on stdout/stderr
and exit codes.

## Distribution

When a surface is configured (default: `detached`), it is deployed to Vercel
and available at the custom domain. `/distribute` generates ad campaigns
pointing to this URL.

### SEO/AEO (surface only)
- `site/index.html` must include `<meta>` tags: title, description, `og:title`, `og:description` — derived per messaging.md Section E
- JSON-LD with `SoftwareApplication` type in `<head>`
- `site/llms.txt` generated alongside `site/index.html` — content per messaging.md Section E
- `surface: none` = skip all SEO artifacts

CLIs are also distributed via package registries:
- `npm publish` — primary distribution for Node.js CLIs
- GitHub Releases — binary artifacts for non-Node users
- Homebrew formula — optional, for macOS users

The `/deploy` skill deploys the surface (Vercel) but not the CLI binary —
use `npm publish` or GitHub Releases directly for the product.

After publishing, run `/iterate` to analyze usage. Gather metrics manually:
npm download counts (`npm info <pkg> --json`), GitHub release download counts,
and user feedback. Enter these into `/iterate` for funnel analysis.

## Health Check

CLIs use `<cli-name> --version` as a smoke test (not an HTTP endpoint).
A successful version output confirms the binary is installed and executable.

## Conventions

- Every command fires analytics events per experiment/EVENTS.yaml (server-side, opt-in)
- No landing page requirement — `validate-experiment.py` skips landing checks
- No UI components — the `ui` stack category is excluded
- No server hosting — the `hosting` stack category is excluded
- `package.json` must have a `bin` field pointing to the compiled entry point
- The entry point (`src/index.ts`) sets up the CLI program and registers commands
