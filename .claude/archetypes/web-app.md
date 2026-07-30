---
description: "Web application with browser-based pages, UI components, and user authentication"
required_stacks: [framework, hosting, testing]
optional_stacks: [database, auth, analytics, ui, payment, email, ai, telephony, voice, notifications, project-management]
excluded_stacks: []
required_experiment_fields: [golden_path]
build_command: "npm run build"
---

# Web App Archetype

Browser-based application with URL-routed pages, UI components, and optional
user authentication. This is the default archetype when `type` is absent from
experiment.yaml.

## Structure

Each experiment.yaml `golden_path` entry with a `page` field maps to a route folder:

```
src/app/<page-name>/page.tsx
```

Pages are React components rendered in the browser. The landing page
(`golden_path` must include an entry with `page: landing`) is the public entry point.

## Funnel

Events are defined in experiment/EVENTS.yaml with `funnel_stage` tags. Filter by `requires` and `archetypes` fields based on experiment stack.

Expected funnel stages (event names are project-specific, defined in experiment/EVENTS.yaml):
1. **reach** — user loads the landing page
2. **demand** — user begins and completes the signup flow
3. **activate** — user completes the core action for the first time
4. **retain** — user returns after initial activation

When `stack.payment` is present, monetize-stage events (with `requires: [payment]`) are also included.

## Conventions

- When `stack.analytics` is configured, every page fires analytics events per experiment/EVENTS.yaml
- Landing page is required — `validate-experiment.py` enforces this
- UI components come from the configured UI stack (e.g., shadcn/ui)
- API routes live under `src/app/api/` for mutations and server-side logic
- Database access uses RLS (Row-Level Security) when auth is configured
- layout.tsx exports `metadata` (title, description, OG tags) — derived per messaging.md Section E
- `src/app/sitemap.ts`, `src/app/robots.ts`, and `public/llms.txt` generated at bootstrap
- JSON-LD `WebApplication` schema embedded in layout.tsx
- Variant pages export per-page `generateMetadata()` with variant-specific title/description
