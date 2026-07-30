# /change: Test Implementation

> Invoked by change.md Step 6 when type is Test.
> Read the full change skill at `.claude/commands/change.md` for lifecycle context.

## Prerequisites from change.md

- experiment.yaml and experiment/EVENTS.yaml have been read (Step 2)
- Change classified as Test (Step 3)
- Preconditions checked (Step 4)
- Plan approved (Phase 1)
- Specs updated (Step 5)

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: Playwright OR component/API tests | service: `app.request()` smoke tests | cli: `runCli()` command tests
>
> State-specific logic below takes precedence.

## Production Quality

Test type changes do NOT spawn implementer agents — tests observe the app, they don't change application code. Implementer agents are reserved for Feature, Fix, and Upgrade types that modify application logic.

## Implementation

- If the testing stack file's configuration file already exists (e.g., `playwright.config.ts` for Playwright, `vitest.config.ts` for Vitest — from bootstrap): do NOT recreate configuration, helper, or setup/teardown files. Only add or modify test case files. If the configuration file does NOT exist, follow the full setup procedure below.
- Do NOT modify application code — tests observe the app, they don't change it
- Install packages per the testing stack file, create config and helpers per the testing stack file templates
- Test funnel happy path only — skip error states, edge cases, and `retain_return`
- **If `stack.testing` is `playwright`:**
  - Read actual page source code for selectors — never guess
  - Call `blockAnalytics(page)` in `beforeEach` to prevent analytics pollution. The default `blockAnalytics` route pattern targets PostHog — if the analytics provider is different, adapt the route pattern using the endpoint domain from the analytics stack file.
  - For payment tests: use Stripe test card `4242424242424242`
- **If archetype is `web-app` AND `stack.testing` is NOT `playwright` (e.g., vitest):** Generate component or API-level tests using the testing stack file's templates. No `blockAnalytics`, no page selectors, no browser interactions.
- **If archetype is `service`:** Generate tests using `app.request()` per the testing stack file's service smoke test template. No `blockAnalytics`, no page selectors, no browser interactions. For frameworks without `app.request()`, test handler functions directly.
- **If archetype is `cli`:** Generate tests using `runCli()` per the testing stack file's CLI smoke test template. Test `--help` and each command's help output. No browser interactions.
- Before applying testing stack file templates: read the testing stack file's `assumes` list. For each `category/value` entry, verify that experiment.yaml `stack` has a matching `category: value` pair (e.g., `analytics/posthog` requires `stack.analytics: posthog`, not just that `analytics` is present). If ALL assumed dependencies match → use the full templates (global-setup/teardown, login helper, auth-based tests). If ANY assumed dependency is unmet → use the testing stack file's "No-Auth Fallback" section instead (no global-setup/teardown, no login helper, tests run as anonymous visitors). Document the chosen path in the PR body.
- Update `.gitignore` and CI workflow per the testing stack file. If using the No-Auth Fallback path, **replace** the existing `e2e:` job in `.github/workflows/ci.yml` with the testing stack file's No-Auth CI Job Template — the pre-baked full-auth `e2e:` job uses local Supabase which is unnecessary for no-auth tests. Add env vars to `.env.example` based on the chosen template path (full or no-auth fallback), not solely from the frontmatter.
- If `stack.payment` is present, uncomment payment-related env vars in the testing CI template when generating the CI job.
- If using the No-Auth Fallback path and `stack.database` is present, uncomment database-related env vars (e.g., `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`) in the testing CI template when generating the CI job.
