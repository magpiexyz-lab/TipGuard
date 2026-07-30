---
description: "Backend service with API endpoints, no browser UI"
required_stacks: [framework, hosting, testing]
optional_stacks: [database, auth, analytics, payment, email, ai, telephony, voice, notifications, project-management]
excluded_stacks: [ui]
required_experiment_fields: [endpoints]
build_command: "npm run build"
---

# Service Archetype

Backend service that handles API requests with no browser-based UI.
The primary unit of work is the **endpoint** (not the page). Use this
archetype when `type: service` is set in experiment.yaml.

## Structure

Each experiment.yaml `endpoints` entry maps to an API route:

```
src/app/api/<endpoint>/route.ts
```

There are no page folders, no landing page, no UI components, and no
`src/components/` directory. The `ui` stack category is excluded.

Surface type is inferred by bootstrap when `stack.surface` is not set (evaluated in order — first match wins):
1. If the experiment defines no `golden_path` **and** no top-level `endpoints` entry serves HTML (all `endpoints` are pure API with no user-facing surface): surface is `none`. This applies regardless of whether hosting is configured — a pure API service has no landing page.
2. If the experiment has a `golden_path` or any top-level `endpoints` entry that serves HTML: `stack.services[0].hosting` present → `co-located` (root URL serves a marketing page alongside API routes); hosting absent → `detached` (separate static marketing site).
When in doubt, set `stack.surface` explicitly in experiment.yaml to override inference.

> Both checks read the top-level `endpoints[]` list (the canonical inventory required by `required_experiment_fields`), not `behaviors[*].endpoints`. An endpoint "serves HTML" when its `purpose` describes rendering a page (e.g., "serve landing page", "render dashboard").

When surface is `co-located` (the most common default), the root URL (`/`) serves
an HTML marketing page — see `.claude/stacks/surface/co-located.md`. API endpoints
live under `/api/*`.

### SEO/AEO (surface only)
- Root route handler's inline HTML must include `<meta>` tags: title, description, `og:title`, `og:description` — derived per messaging.md Section E
- JSON-LD with `WebAPI` type in inline HTML `<head>`
- `llms.txt` served via route handler (`src/app/llms.txt/route.ts`) returning `text/plain` — content per messaging.md Section E

## Funnel

Events are defined in experiment/EVENTS.yaml with `funnel_stage` tags. Event names are project-specific — /spec generates them from behaviors and hypotheses. Filter by `requires` and `archetypes` fields based on experiment stack. Service-specific events should have `archetypes: [service]`.

When a surface is configured (default: `co-located`), the surface fires a reach-stage event — providing a complete acquisition → activation → retention funnel.

Expected funnel stages:
1. **reach** — user loads the surface page (surface event, inline snippet)
2. **activate** — user completes the core action via the API (server-side event)
3. **retain** — user makes a request after 24+ hours since last call (server-side event)

Surface events use an inline analytics snippet (see analytics stack file and surface stack file). Product events use `trackServerEvent()` from the server analytics library.

## Testing

Services use unit and API tests (e.g., Vitest, Jest), not browser-based
E2E tests (Playwright). The test runner comes from the testing stack file.

## Deploy

Deployment follows the hosting stack file. For services, browser-based
health checks don't apply — use the `/api/health` endpoint instead.

## Distribution

When a surface is configured (default: `co-located`), the root URL serves
a marketing page. `/distribute` generates ad campaigns pointing to this URL.
This gives services the same distribution capability as web-apps — paid ads,
social campaigns, and tracked referral links all point to the surface.

When surface is `none`: distribution is direct outreach, documentation links,
or API marketplace listings.

## Conventions

- When `stack.analytics` is configured, every endpoint fires analytics events per experiment/EVENTS.yaml (server-side)
- No landing page requirement — `validate-experiment.py` skips landing checks
- No UI components — the `ui` stack category is excluded
- Database access uses RLS (Row-Level Security) when auth is configured
- API routes live directly under `src/app/api/`
