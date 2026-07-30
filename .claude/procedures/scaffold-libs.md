# Scaffold: Library Files

## Prerequisites
- Packages installed and UI setup complete (Step 1 finished)
- Stack files on disk for all categories in experiment.yaml `stack`
- `.runs/current-plan.md` exists

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: client + server analytics, typed event wrappers | service: server analytics only | cli: server analytics + opt-in consent guard
> Conditional points: Step 6 (analytics constant replacement, per-archetype path), Step 7 (CLI consent guard), Step 8 (typed wrappers — web-app + nextjs only)
> Shape: interleaved-per-step
>
> State-specific logic below takes precedence.

## Instructions

Create ONLY the `src/lib/` files (and the route-protection file `src/proxy.ts` when `stack.auth` is present — see Step 3 below) from each stack file's "Files to Create" section. Skip files outside these paths — pages are owned by scaffold-pages, infrastructure routes and components by scaffold-wire.

1. **Analytics library** (if `stack.analytics` is present): create from the analytics stack file.

2. **Database clients** (if `stack.database` is present): create from the database stack file.

3. **Auth files** (if `stack.auth` is present): create from the auth stack file using the correct conditional path:
   - The route-protection filename is `src/proxy.ts` on Next.js 16+ (today's template default after `npm install next`). The Next.js 16+ filename↔export-name invariant requires the file `src/proxy.ts` paired with `export async function proxy(request: NextRequest)` — renaming only one (file but not export, or vice versa) produces an empty middleware-manifest and silent non-registration of the proxy (this was the symptom #1120 originally reported on 16.2.4, since superseded by empirical 16.2.6 verification — see `.claude/stacks/framework/nextjs.md` Stack Knowledge entry "Next.js 16+: scaffold src/proxy.ts + filename↔export-name invariant"). The `config` export is identical regardless of filename. For pre-existing projects already on `src/middleware.ts`, the legacy filename continues to work on Next.js 16+ but emits a deprecation warning — migrate via `git mv src/middleware.ts src/proxy.ts` and rename the exported function in the same commit.
   - **publicPaths derivation (Issue #1126)**: After writing the route-protection file from the auth stack template, replace the hardcoded `publicPaths` array literal with the canonical set computed from experiment.yaml:
     ```bash
     PUBLIC_PATHS=$(python3 .claude/scripts/lib/derive_pages.py public_paths < experiment/experiment.yaml)
     # Substitute the placeholder array on the publicPaths const line with PUBLIC_PATHS
     ```
     The derive helper returns a JSON array of paths (e.g., `["/", "/login", "/signup", "/auth/callback", "/auth/reset-password", "/api/health", "/spec"]`) — a union of auth landing pages, `/api/health`, and behavior pages where every owning behavior has `anonymous_allowed: true` (fail-secure intersection). The static `publicPaths` array in the auth stack template is a placeholder; the substitution makes it canonical.
   - If `stack.database` matches the auth provider (e.g., both `supabase`): auth shares the database client files — create only the route-protection file (from the auth stack file's "Proxy" section)
   - If `stack.database` is absent or a different provider: create standalone auth library files from the "Standalone Client" section (e.g., `supabase-auth.ts`, `supabase-auth-server.ts`) AND the route-protection file
   - Do NOT create auth pages (signup, login), auth infrastructure (auth/callback, auth/reset-password), or components (nav-bar) — those are created by scaffold-pages and scaffold-wire respectively

4. **Auth before payment ordering**: if both `stack.auth` and `stack.payment` are present, create auth library files first — payment templates reference `user.id` which requires auth.

5. **Payment library files** (if `stack.payment` is present): create from the payment stack file's "Files to Create" section. Note: the payment stack file's checkout route template intentionally references `user.id` which is undefined until auth is integrated — this will cause a build error at the merged checkpoint that you must fix by adding the auth check (see the auth stack file's "Server-Side Auth Check" section). The webhook route template also contains a `// TODO: Update user's payment status in database` — unlike the auth check, this TODO compiles silently, so you must resolve it using the database schema planned in Phase 1.

6. **Analytics constant replacement** (if `stack.analytics` is present): replace placeholder constants in the analytics library files — replace `PROJECT_NAME = "TODO"` with the `name` from experiment.yaml and `PROJECT_OWNER = "TODO"` with the `owner` from experiment.yaml. For web-app: replace in both client (`src/lib/analytics.ts`) and server (`src/lib/analytics-server.ts`) files. For service/cli: replace in the server analytics file only (no client-side analytics). These constants auto-attach to every event — if left as TODO, experiment filtering will fail. **Do NOT replace** the `phc_TEAM_KEY` placeholder constant — its replacement is the fork-owner's responsibility (per the analytics stack file's `## Environment Variables` section); the prebuild check in Step 6.5 surfaces the misconfiguration if neither workflow (env override, source replacement) is satisfied.

  **6.5 Production Observability prebuild script** (if `stack.analytics` value has a `## Production Observability` section in its stack file — currently `posthog`; in the future also any analytics stack adopting the convention):
  - Read the analytics stack file's `## Production Observability` section to determine the prebuild script content. For PostHog, write the contents of `.claude/stacks/analytics/posthog.md`'s prescribed `scripts/check-analytics-env.mjs` to `scripts/check-analytics-env.mjs` in the project root.
  - Update `package.json`'s `scripts.prebuild` entry. **scaffold-libs owns this write** — it composes from active stacks. Compose with `&&`-chained, defensively-guarded segments (each segment uses `test ! -f X || node X` to no-op when the script is missing, so partial-bootstrap states stay safe):
    - Database+Analytics both present:
      ```json
      "prebuild": "(test ! -f scripts/auto-migrate.mjs || node scripts/auto-migrate.mjs) && (test ! -f scripts/check-analytics-env.mjs || node scripts/check-analytics-env.mjs)"
      ```
    - Analytics only:
      ```json
      "prebuild": "test ! -f scripts/check-analytics-env.mjs || node scripts/check-analytics-env.mjs"
      ```
    - Database only (existing behavior, no change):
      ```json
      "prebuild": "test ! -f scripts/auto-migrate.mjs || node scripts/auto-migrate.mjs"
      ```
  - Verify after writing: `grep -q '"prebuild"' package.json` MUST be truthy when either `stack.analytics: posthog` OR `stack.database: supabase` is present. If neither stack contributes a prebuild segment, leave `prebuild` absent (do not write an empty entry).
  - For details on the check's logic, error messages, and skip-gate behavior, see the analytics stack file's `## Production Observability > Layer 1` section. Do NOT re-document the script contents inside this procedure — keep the canonical source in the stack file.

7. **CLI analytics consent wrapper** (if `stack.analytics` is present AND archetype is `cli`): read the analytics stack file's CLI Opt-In Consent section. Add the `isAnalyticsEnabled()` guard function to `src/lib/analytics-server.ts` and wrap `trackServerEvent()` so it returns early when consent is not given. Replace `<CLI_NAME>` with the uppercase experiment name from experiment.yaml. After writing the file, verify the guard exists: grep `src/lib/analytics-server.ts` for `isAnalyticsEnabled`. If missing, stop: "CLI analytics opt-in guard `isAnalyticsEnabled()` was not added to `src/lib/analytics-server.ts`. The CLI archetype requires opt-in consent for analytics (see `.claude/archetypes/cli.md`). Add it per the analytics stack file's CLI Opt-In Consent section before proceeding."

8. **Typed event wrappers** (if `stack.analytics` is present AND framework is `nextjs` AND archetype is `web-app`): generate `src/lib/events.ts` from experiment/EVENTS.yaml following the analytics stack file's generation rules. For each event in the EVENTS.yaml `events` map (filtered by `requires` matching experiment stack and `archetypes` matching experiment type): (a) generate a typed wrapper function named `track` + PascalCase(event_name) with props typed from the event's `properties` map, (b) the wrapper body calls `track(event_name, { ...props, funnel_stage: "<funnel_stage>" })` to auto-inject the event's funnel_stage. Also generate an `EVENT_FUNNEL_MAP` constant (`Record<string, string>`) mapping each event name to its funnel_stage. Pages should import from `events.ts` instead of calling `track()` directly with string event names. For non-Next.js frameworks (Hono, Commander) or non-web-app archetypes (service, cli), skip this step — only server-side analytics apply (see analytics stack file).

9. **Write completion manifest** via the canonical AOC v1.1 writer (the writer creates `.runs/agent-traces/` and stamps `agent`, `timestamp`, `status:"completed"`, `provenance:"self"`, `partial:false`, `run_id`, `skill`, `spawn_sha`, and `spawn_index` from active identity + spawn-log):
   ```bash
   python3 - <<'PYEOF'
   import json, subprocess
   trace = {
       "verdict": "pass",
       "result": "clean",
       "checks_performed": ["libs_created", "exports_defined", "build_smoke"],
       "no_fixes_claimed": True,
       "files_created": ["<list all files created>"],
   }
   subprocess.run(
       ["bash", ".claude/scripts/write-agent-trace.sh", "scaffold-libs",
        "--json", json.dumps(trace)],
       check=True,
   )
   PYEOF
   ```
   This manifest gates Phase B2 agents via the skill-agent-gate hook.

