---
# YAML Frontmatter Schema — every stack file must include this block.
# The validate-frontmatter.py script checks these keys on every PR.
#
# assumes:          list[str]  — other stack files this depends on (e.g., [framework/nextjs])
# packages:
#   runtime:        list[str]  — npm packages installed with `npm install`
#   dev:            list[str]  — npm packages installed with `npm install -D`
# files:            list[str]  — source files this stack creates (relative to repo root)
# env:
#   server:         list[str]  — server-only environment variable names
#   client:         list[str]  — client-side environment variable names (e.g., NEXT_PUBLIC_*)
# ci_placeholders:  dict       — env var name → placeholder value for CI builds
# clean:
#   files:          list[str]  — files to delete on `make clean`
#   dirs:           list[str]  — directories to delete on `make clean`
# gitignore:        list[str]  — entries to add to .gitignore
# emits_events:     list[str]  — OPTIONAL (#1447); analytics events this stack's template code
#                                fires automatically (e.g., from a hardcoded `import { trackX } from "@/lib/events"`).
#                                Seeded by /spec state-6 step 9 into experiment/EVENTS.yaml when the stack is active
#                                and `stack.analytics` is present. Default scope is `archetypes: [web-app]` unless the
#                                stack declares broader via an inline comment (e.g., `# archetypes: [service]`).
#                                Coherence rule `events-yaml-seeded-from-stack-emits-events` audits drift post-bootstrap.

assumes: []
packages:
  runtime: []
  dev: []
files: []
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# [Category]: [Technology Name]
> Used when experiment.yaml has `stack.[category]: [value]`
> Assumes: [other stack files this depends on, e.g., `framework/nextjs` — or "None"]

## Packages
```bash
npm install [runtime-packages]
npm install -D [dev-packages]
```

## Files to Create
<!-- If this stack creates no files (e.g., hosting/vercel), write "None — this stack provides deployment patterns only." so future authors know the omission is intentional. -->

### `src/lib/[filename].ts` — [Description]
```ts
// Starter code or key exports
```
- [Usage notes]

## Environment Variables
```
VARIABLE_NAME=description-or-example
```

## Patterns
- [How skills should use this technology]
- [Key conventions to follow]
- [What to import and where]

## Assumes
- [List stack files this depends on, e.g., `framework/nextjs` for Next.js-specific imports]
- [If truly generic, write "None"]

<!-- Optional sections — include when relevant: -->

## Security
- [Secrets handling]
- [Access control requirements]
- [Client vs server boundaries]

## Demo Mode
<!-- Add demo mode guards to all client factory functions so pages render
     during visual review (no real credentials at bootstrap time).

     Server-side: FIRST check for production misuse, THEN check for demo mode:
       if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
         throw new Error("DEMO_MODE is not allowed in production");
       }
       if (process.env.DEMO_MODE === "true") return createDemoClient();
     The production guard uses `VERCEL === "1"` (injected by Vercel on all
     deployments) instead of `NODE_ENV === "production"` because `next start`
     sets NODE_ENV=production locally, which would block demo mode during
     visual review and verification. For non-Vercel hosting, replace with
     the provider's deployment indicator (e.g., `RAILWAY_ENVIRONMENT_NAME`).

     Client-side: check `process.env.NEXT_PUBLIC_DEMO_MODE === "true"` and
     return a mock client. Do NOT add a NODE_ENV guard — the demo flag alone
     is sufficient. NEXT_PUBLIC_ is required because Next.js inlines
     client env vars at build time.

     For Supabase-style chainable APIs (e.g., `from()`), use a Proxy-based mock:
       const chainable = (terminal) => new Proxy(() => terminal, {
         get: (_, prop) => {
           if (prop === "then") return (resolve) => resolve(terminal);
           if (prop === "single") return () => chainable({ data: null, error: null });
           if (prop === "maybeSingle") return () => chainable({ data: null, error: null });
           return chainable(terminal);
         },
         apply: () => chainable(terminal),
       });
     The `then` trap returns a proper thenable so `await` resolves to the
     terminal value. The `single()` and `maybeSingle()` handlers both return
     `{ data: null }` instead of the default array shape — they share semantics
     in the demo case (zero-row outcome). Pages calling either method see a
     usable null result; without the explicit `maybeSingle` handler, calls fall
     through to the array terminal and break null-coalescing logic in pages.

     For auth-like namespaces with many methods (e.g., `auth`), use a Proxy
     fallback so unknown methods return a safe default instead of crashing:
       auth: new Proxy(
         { getUser: () => ..., getSession: () => ... },  // known methods with specific return shapes
         { get: (target, prop) => prop in target ? target[prop] : () => Promise.resolve({ data: {}, error: null }) }
       );
     This avoids maintaining an explicit allowlist — any new SDK method
     (e.g., signInWithOAuth) automatically gets a safe no-op response.

     For simpler clients (Stripe, Resend), a plain object mock or early
     return is sufficient.

     DEMO_MODE is never added to env frontmatter or .env.example — it is
     only set by the visual scanner (visual-review.md), never by /verify
     or production deployments. -->

## Analytics Integration
- [Which experiment/EVENTS.yaml events this stack interacts with]
- [Where to fire them]

## PR Instructions
- [Post-merge setup steps for the user]
- [Environment variables to configure]
- [External service configuration]

<!-- =========================================================================
     ## Production Observability
     (REQUIRED for stack files prescribing env-gated generated code)

     Any stack file whose `## Files to Create` blocks include source code
     gated on environment variables (e.g., API keys, secrets, configuration)
     MUST include a `## Production Observability` section specifying:

     1. The fail-loud mechanism (one or more of):
        - Build-time prebuild guard (Node script + package.json prebuild hook)
        - Runtime module-load console.error gated on hosting platform indicator
        - Health-check route signal
     2. The placeholder-replacement contract (if applicable): how the literal
        placeholder string flows from stack file → bootstrap codegen → generated
        source → fork customization → deploy.
     3. How the contract interacts with `/distribute` STATE 2 verification.
     4. A behavior matrix showing what happens for each combination of
        (source customization × env override × deployment context).

     Rationale: stack files prescribing silent fallbacks like
     `if (!KEY) return;` or `?? "PLACEHOLDER"` without compensating visibility
     create an entire class of production-failure modes that are invisible
     until users complain. See issue #1170 for the canonical incident
     (PostHog) and the `posthog-missing-key-silent-noop` Stack Knowledge
     entry in `.claude/stacks/analytics/posthog.md` for the canonical fix
     template.

     Tracking: `.claude/patterns/template-coherence-rules.json` enforces
     this convention via the `must_contain_section` rule type — any stack
     file matching the `env_gated_source` pattern is required to declare
     a `## Production Observability` heading. Skipping this section in a
     new stack file is a CI-blocking error, not a guideline. -->

<!-- =========================================================================
     ## Stack Knowledge (OPTIONAL — added by /resolve STATE 9 as it learns)

     Structured composite-identity-hashed entries sedimented by /resolve runs
     in the template repo (magpiexyz-lab/mvp-template). Downstream projects
     never write this section directly — they file `pattern-proposal`-labeled
     issues upstream instead (HC1).

     All consumers (STATE 2 triage, solve-reasoning Agent 2, STATE 5d
     adversarial challenge, STATE 7 fix approval) treat this section as
     OPTIONAL (HC3). Absent section = empty list = zero hints.

     Per-entry YAML schema:

     ```yaml
     id: <stack>-<short-slug>           # human-readable, e.g. nextjs-demo-guard
     maturity: raw | stable | canonical # raw=first sighting, canonical=hardened
     anti_pattern: false                # Phase 1 always false; Phase 2 enables
     composite_identity:
       root_cause_class: <class>        # canonicalized before hashing
       divergence_pattern: <pattern>    # canonicalized before hashing
       stack_scope: <stack-slug>        # e.g. framework/nextjs
     composite_identity_hash: <12-char-sha1>   # sha1(sort_keys(canon(ci)))[:12]
     symptom_keywords: [kw1, kw2]
     fix_template: <snippet or pointer>
     prevention_mechanism: <test|guard|validator|null>
     confidence_score: 0.5              # float in [0.0, 1.0]
     occurrence_count: 1                # int >= 1
     linked_issues: [#123]
     first_seen: YYYY-MM-DD
     last_seen: YYYY-MM-DD
     graduated_to: null                 # Phase 2: pointer if promoted

     # OPTIONAL — added M3 (PR #1397 retro). Project-agnostic bash command
     # that empirically reproduces the root cause. /resolve STATE 3 Step 0
     # runs this first to check if the issue still exists post-package-upgrade.
     # Trinary exit contract:
     #   exit 0 → bug PRESENT (proceed with reproduction)
     #   exit 1 → bug ABSENT (close issue as Stale; refresh SK entry)
     #   exit 2 → preconditions not met (skip; e.g., package not in this stack)
     #   exit other → snippet broken (treat as "unable to verify")
     # Project-agnostic requirements: NO user-specific paths (/Users/, /home/);
     # use mktemp -d for ephemeral working dirs; runnable from repo root.
     # Required when /resolve STATE 9 emits an entry whose underlying fix had
     # reproduction.method ∈ {exec, validator-fed} (the snippet IS the evidence
     # captured at STATE 3). Optional for cite/grep tier reproductions.
     verification_snippet: |
       # exit 0 = bug present (default contract)
       cd "$(mktemp -d)" && npm init -y >/dev/null && npm install <pkg> 2>/dev/null
       node -e "<minimal repro>" && exit 0 || exit 1
     ```

     One one-paragraph prose summary for humans SHOULD follow each fenced
     YAML entry. Entries are enforced by scripts/validate-stack-knowledge.py
     (schema + forbidden-heading lint + within-file hash uniqueness) and
     scripts/ci-check-stack-knowledge.py (cross-file hash uniqueness).

     Do NOT create a `## Known Issues` heading — that heading is forbidden
     by the validator. Migrate legacy Known Issues prose to Stack Knowledge
     entries via scripts/migrate-known-issues.py (two-phase, approval-gated).

     ---

     Maturity lifecycle (Phase 3 — active prevention + compression + promotion):

     | Tier       | Entry condition                                               | Readers                                   |
     |------------|---------------------------------------------------------------|-------------------------------------------|
     | raw        | First sighting; /resolve STATE 9 writes                       | /resolve (reactive)                       |
     | stable     | occurrence_count >= 5, confidence > 0.8, no oscillation 90d   | /resolve + /change + /bootstrap (active)  |
     | canonical  | stable for >= 60 days, no regression linked back              | all skills (active, constraint-strength)  |
     | graduated  | Manual PR removes entry AND adds validator/hook/rule/default  | retained as doc via `graduated_to` field  |
     | archived   | Filename *.archive.md — skill-unreadable, documentation only  | none (preserved for history only)         |

     Promotion paths (system NEVER auto-mutates maturity — always via human /resolve PR):
       - raw → stable:        .claude/scripts/stack-knowledge-audit.sh files `pattern-graduation-stable` issue
       - stable → canonical:  .claude/scripts/stack-knowledge-audit.sh files `pattern-graduation-canonical` issue
       - canonical → graduated:  human PR, CI (.github/workflows/stack-knowledge-graduation.yml) enforces
                                 that the `graduated_to:` path is modified in the same PR
       - canonical → archived:  audit files `pattern-archive-candidate` issue → maintainer renames to *.archive.md

     Reader filtering: active-prevention consumers (/change, /bootstrap) filter
     `maturity in {stable, canonical}` AND `graduated_to is None`. Entries with
     graduated_to != None are preserved for history but deprioritized — the
     structural prevention (validator/hook/rule/default) is now the source of truth.
     ========================================================================= -->

<!-- Include the Deploy Interface section for hosting and database stack files.
     deploy.md and teardown.md reference these subsections by name.
     Omit this section for non-hosting/non-database stacks (analytics, payment, etc.). -->

## Deploy Interface

<!-- For hosting stacks, include all of these subsections: -->
<!-- ### Prerequisites -->
<!-- - install_check, install_fix, auth_check, auth_fix -->
<!-- ### Config Gathering -->
<!-- - CLI command to discover team/org, experiment.yaml field name -->
<!-- ### Project Setup -->
<!-- - Create/link project, connect GitHub -->
<!-- ### Domain Setup -->
<!-- - Add custom domain command, fallback behavior -->
<!-- ### Environment Variables -->
<!-- - Primary method (API or CLI), auth token location, fallback, verify command -->
<!-- ### Volume Setup (optional — only if the hosting provider supports persistent volumes) -->
<!-- - Create volume command, mount path -->
<!-- ### Deploy -->
<!-- - Production deploy command, how to extract deployment URL -->
<!-- ### Health Check -->
<!-- - URL pattern -->
<!-- ### Auto-Fix -->
<!-- - Env var verify command, re-set method, redeploy command -->
<!-- ### Teardown -->
<!-- - Remove domain command, remove project command, dashboard URL for manual fallback -->
<!-- ### Manifest Keys -->
<!-- - Provider-specific keys for deploy-manifest.json -->
<!-- ### Compatibility -->
<!-- - incompatible_databases: [], reason: "..." -->

<!-- For database stacks, include all of these subsections: -->
<!-- ### Prerequisites -->
<!-- - install_check, auth_check (empty for embedded databases like sqlite) -->
<!-- ### Config Gathering -->
<!-- - Required parameters (org, region, etc.), experiment.yaml field names -->
<!-- ### Provisioning -->
<!-- - Project creation, readiness polling, key extraction, link + migration commands -->
<!-- ### Hosting Requirements -->
<!-- - incompatible_hosting: [], volume_config: { needed: bool, mount_path, env_vars } -->
<!-- ### Auth Config (optional — only if the database provides auth services) -->
<!-- - Management API token discovery, auth redirect URL configuration -->
<!-- ### Teardown -->
<!-- - Pre-delete safety check, delete command, dashboard URL for manual fallback -->
<!-- ### Manifest Keys -->
<!-- - Provider-specific keys for deploy-manifest.json -->
