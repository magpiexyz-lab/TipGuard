# experiment.yaml — Canonical Schema

The single source of truth for `experiment.yaml`. Every consumer (skills,
agents, gate-keeper, lint rules) reads from this file. Field semantics here
are authoritative — disagreement between consumers is a coherence violation
detected by `verify-linter.sh` (see `.claude/patterns/template-coherence-rules.json`).

> **Why this file exists:** Issue #1024 surfaced that `golden_path` was being
> consumed with three incompatible semantics across consumers. To prevent
> recurrence, every field in `experiment.yaml` is documented here with one
> well-defined semantic. Consumers cite this file by URL fragment.

## Top-level structure

```yaml
name: <string>             # Canonical kebab-case slug — MUST match ^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$
                           # (lowercase, hyphenated, no consecutive/leading/trailing hyphens).
                           # Used verbatim as PostHog project_name. /bootstrap STOPs if non-compliant.
owner: <string>            # Team or user owning the experiment
type: web-app | service | cli   # Archetype (default: web-app)
level: 1 | 2 | 3           # Product depth (1: landing only, 2: + signup, 3: + payments)
status: draft | live | done

description: <multiline>
thesis: <one-sentence falsifiable claim>
target_user: <persona>
distribution: <multiline>

hypotheses: [...]
behaviors: [...]
golden_path: [...]         # web-app only
endpoints: [...]           # service only
commands: [...]            # cli only
variants: [...]
funnel: {...}
stack: {...}
target_geo: [...]
deploy: {...}
```

## Field reference

### `name` (required, string)

Canonical kebab-case slug matching `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`. Used
verbatim as the PostHog `project_name` super property (`src/lib/analytics.ts`
constant), in PR titles, and as the cross-MVP analysis key.

**Enforcement**: `/bootstrap` STATE 3 runs `.claude/scripts/lib/validate_experiment_yaml.py`,
which programmatically rejects non-canonical names (mixed case, spaces,
underscores, consecutive/leading/trailing hyphens) and prints a kebab-case
suggestion. The bootstrap STATE 3 VERIFY also reasserts the regex against
`experiment.yaml` directly as defense-in-depth.

Why strict: divergent name forms (e.g. `splitshare` vs `split-share-neon`)
produce different `project_name` values in PostHog, fragmenting cross-MVP
analysis. The strict format is the only way to keep MVP identity stable
across re-bootstraps, re-deploys, and team handoffs.

### `owner` (required, string)

Team or user identifier. Becomes `project_owner` in analytics events.

### `type` (optional, enum, default `web-app`)

Product archetype. Drives:
- File-structure: `src/app/<page>/page.tsx` (web-app), `src/app/api/` (service), `src/commands/` (cli)
- Required behavior fields: `pages` (web-app), `endpoints` (service), `commands` (cli)
- Gate-keeper checks (BG2)

### `behaviors` (required, list)

Each behavior is a user-observable capability tied to a hypothesis. Schema:

```yaml
- id: <string>                 # Required. Behavior identifier (b-01, b-02, ...)
  hypothesis_id: <string>      # Required. Hypothesis this behavior validates.
  given: <string>              # Required. Pre-condition.
  when: <string>               # Required. User/system action.
  then: <string>               # Required. Post-condition.
  tests: [<string>...]         # Required. Acceptance criteria. 1-5 entries (validator-enforced — see scripts/validate-experiment.py b_tests length check).
                               # #1393 r3 Item 3 — `tests[]` strings may include inline audit tags of the form
                               # `[audit:<verb>=<value>]`. Verb must appear in .claude/patterns/audit-verb-registry.json.
                               # Current verbs (post #1387):
                               #   - api-fetch=<path>          : AST asserts fetch('<path>') in page .tsx
                               #   - sitemap-instance=<route>/<segment> : sitemap.ts iterates over <segment>
                               #   - event=<event-key>         : AST asserts track<Event>(...) call
                               #   - ai-conversation           : AST asserts fetch('/api/...') + useState/useReducer
                               #   - render                    : trivial; page existence (already enforced upstream)
                               #   - seo=<free-text>           : free-text, lead review only
                               # Producer = human; consumer = lead + AST scanner via the audit_tag_verb_recognized
                               # and audit_tag_claim_matches_ast (#1387 behavior_contract_auditor.py) rules.
                               # Example:
                               #   tests:
                               #     - "User sees portfolio cards [audit:api-fetch=/api/portfolio] [audit:event=portfolio_viewed]"
                               #     - "[audit:sitemap-instance=portfolio/slug] each fixture slug appears in sitemap"
                               #     - "[audit:ai-conversation] multi-turn AI surface for spec builder"
  level: 1 | 2 | 3             # Required. Behavior level.
  actor: user | system | cron  # Optional. Default `user`.
  trigger: <string>            # Optional. Required when actor != user.
  requires_role: <string>      # Optional. Authenticated role needed to execute.
                               # Issue #1077: scaffold-init reads this to decide
                               # which slots are runtime_gated (e.g., admin-only
                               # empty-state unreachable in DEMO_MODE).
  anonymous_allowed: <bool>    # Optional, default false. When true, pages owned
                               # by this behavior are added to the auth proxy's
                               # publicPaths array (#1126). Mutually exclusive
                               # with requires_role -- a behavior cannot be
                               # both anonymous-allowed and role-gated.
                               # Multi-behavior pages: a page is public iff
                               # EVERY contributing behavior marks it
                               # anonymous_allowed=true (fail-secure
                               # intersection). Default false enforces
                               # default-deny: absence keeps a page auth-gated.
  dynamic_segments:            # Optional. #1387: declares concrete fixture slug
                               # values for dynamic-segment pages (e.g.,
                               # src/app/portfolio/[slug]/page.tsx). Required when
                               # anonymous_allowed=true AND any page in `pages`
                               # maps to a dynamic-segment file path — without
                               # this, sitemap.ts cannot enumerate the URL
                               # instances and SEO indexability is broken.
                               # Schema: { <segment-name>: [<slug>, ...] }
                               # Consumed by .claude/scripts/lib/derive_pages.py
                               # dynamic_public_pages() + state-11c post-fan-out
                               # sitemap.ts emitter.
                               # Example:
                               #   dynamic_segments:
                               #     slug: [harborline-internal-orders, northwind-tutoring-marketplace]

  # Archetype-conditional REQUIRED fields:
  pages: [<page>...]           # web-app + actor: user → REQUIRED, non-empty
  endpoints: [<endpoint>...]   # service → REQUIRED, non-empty
  commands: [<command>...]     # cli → REQUIRED, non-empty
```

#### `behavior.requires_role` (optional, string) — Issue #1077

Declares the authenticated role required to execute the behavior. Examples:
`admin`, `operator`, `supervisor`. When the auth stack's `demo_mode_role`
(declared in `.claude/stacks/auth/<value>.md` frontmatter) lacks this role,
the behavior is unreachable in DEMO_MODE — `scaffold-init` declares
runtime_gate on slots associated with the behavior's pages so:

- `scaffold-images` skips generation for unreachable conditional slots
- `scaffold-pages` renders text-only fallback (no `<Image>` import)
- `design-critic` suppresses polish-floor escalation (won't regen)
- `state-2b drift detection` short-circuits to INFO (no false BLOCK)

When this field is absent, the behavior has no role gate and slots default to
visible/focal. See `.claude/scripts/lib/derive_slot_intent.py:derive_runtime_gate`.

#### `behavior.anonymous_allowed` (optional, bool, default false) — Issue #1126

Marks pages owned by this behavior as public (no authentication required) in
the auth proxy / middleware route-protection file. When `true`, the pages are
added to the proxy's `publicPaths` array via `derive_public_paths()` at
scaffold-libs time.

**Default false** (default-deny): absence keeps pages auth-gated. This protects
against the failure mode in #1126 where a hardcoded `publicPaths` list in the
auth template drifts from `behaviors[*]` semantics. To opt a page into public
access, the behavior must declare `anonymous_allowed: true` explicitly.

**Mutually exclusive with `requires_role`**: a behavior that requires an
authenticated role cannot also be anonymous-allowed. `validate-experiment.py`
rejects experiments where both fields are present on the same behavior.

**Multi-behavior pages**: when two or more behaviors share a page, the page is
public iff EVERY owning behavior has `anonymous_allowed: true` (fail-secure
intersection at `derive_public_paths()`). One auth-required behavior anywhere
on the page keeps the entire page auth-gated.

Examples:
```yaml
- id: b-01
  given: "An anonymous visitor is on /spec"
  pages: [spec]
  anonymous_allowed: true   # /spec added to publicPaths

- id: b-02
  given: "An authenticated user is on /dashboard"
  pages: [dashboard]
  # anonymous_allowed defaults to false -- /dashboard stays auth-gated
```

Consumers:
- `.claude/scripts/lib/derive_pages.py::derive_public_paths` (canonical reader)
- `.claude/procedures/scaffold-libs.md` Step 3 (substitutes derived array into the proxy template)
- `scripts/validate-experiment.py` (enforces mutual exclusivity with `requires_role`)

#### `behavior.pages` (web-app + actor: user → REQUIRED)

The set of pages that the user interacts with during this behavior. **Every page
named here MUST be created** (gate-keeper BG2 check 3c enforces existence).

A behavior spans multiple pages when it crosses page boundaries — e.g., "user
clicks signup CTA on landing → fills form on signup page → lands on dashboard"
declares `pages: [landing, signup, dashboard]`.

**For `actor: system` or `actor: cron` behaviors**, `pages` is omitted (these
behaviors have no UI surface).

**For service archetype**, omit `pages`; use `endpoints` instead.

**For cli archetype**, omit `pages`; use `commands` instead.

#### Why `pages` is required

Before this requirement, pages were derived only from `golden_path`. Behaviors
referencing pages outside `golden_path` (e.g., `admin`, `dashboard`, `portfolio`)
got backend + RLS + tests scaffolded but their frontend pages were silently
blocked, causing 404 traps after deploy. Making `pages` required ensures every
user-facing behavior maps to a concrete frontend page that gets scaffolded.

### `golden_path` (web-app required, list)

Ordered list of user journey steps used for funnel analytics, sequence-based
consumers (nav-bar order, funnel tests, sitemap order). Each step:

```yaml
- step: <string>          # Required. Human-readable description.
  event: <event_id>       # Required. Maps to experiment/EVENTS.yaml.
  page: <page>            # Required. Page where this step occurs.
```

`golden_path` is the **funnel sequence**, not the page inventory. Pages outside
`golden_path` still exist if declared in `behavior.pages`. The canonical page
inventory is the union of `golden_path[*].page`, `behaviors[*].pages`, and
auth-derived pages.

### `endpoints` (service required, list)

Service archetype only. Each endpoint:

```yaml
- method: GET | POST | PUT | DELETE
  path: /api/<route>
  purpose: <string>
```

### `commands` (cli required, list)

CLI archetype only. Each command:

```yaml
- name: <command_name>
  args: [<arg>...]
  purpose: <string>
```

### `hypotheses` (required, list)

```yaml
- id: <string>           # h-01, h-02, ...
  category: demand | activate | monetize | retain | reach
  statement: <falsifiable claim>
  metric:                # required when status != 'resolved' (see below)
    formula: <events / events>
    threshold: <number>
    operator: gte | lte | eq
  evidence:              # required when status == 'resolved' (Issue #1117)
    source: <string>     # e.g., "TAM analysis Q1 2026", "competitor landscape scan"
    verdict: <string>    # one-line conclusion from desk research
    citation: <string>   # link, doc reference, or data source identifier
  priority_score: 0..100
  experiment_level: 1 | 2 | 3
  depends_on: [<hypothesis_id>...]
  status: pending | resolved
```

**`metric` vs `evidence` (Issue #1117):** Hypotheses validated by desk
research (market sizing, competitor scans, ICP interviews) carry
`status: resolved` and have no analytics-event formula. Forcing them to
declare a `metric.formula` produces invented placeholder events
(`research_market_exists / one`) that never fire and mislead grep-based
consumers. The schema accepts EITHER `metric` (for testable hypotheses
that fire events) OR `evidence` (for desk-resolved hypotheses):

| status | required field | optional field |
|--------|----------------|----------------|
| pending | `metric` | `evidence` |
| resolved | `evidence` | `metric` (legacy) |

`validate-experiment.py` enforces this XOR at validation time.

**Status `resolved`:** Use for research dimensions validated before product
build (market, problem, competition, ICP). /spec state-2 emits these with
status: resolved by default.

### `variants` (required, list)

A/B messaging variants. Each:

```yaml
- slug: <string>                # Variant identifier (used in /v/<slug> route)
  headline: <string>
  subheadline: <string>
  cta: <string>
  promise: <string>
  proof: <string>
  urgency: <string>
  pain_points: [<string>...]

  # Pricing fields — REQUIRED when level == 3 AND a monetize hypothesis exists
  # (Issue #1117). Optional otherwise. /spec emits these per
  # state-5-variants.md instructions when both conditions hold.
  pricing_amount: <number>      # Numeric price in the project's primary currency
  pricing_model: <string>       # subscription | one-time | usage-based | freemium
```

**`pricing_amount` / `pricing_model` (conditional, Issue #1117):** When the
experiment is Level 3 AND `hypotheses[*].category` includes `monetize`, every
variant MUST carry both pricing fields. /spec state-5-variants emits them; the
canonical schema acknowledges them so they don't land as orphan fields.
`validate-experiment.py` enforces presence under these conditions.

### `stack` (required, dict)

```yaml
stack:
  services:
    - name: <string>
      runtime: nextjs | express | hono
      hosting: vercel | fly | aws-lambda
      ui: shadcn | none
      testing: playwright | vitest
  database: supabase | postgres | none
  auth: supabase | none
  auth_providers: [<provider>...]
  analytics: posthog | none
  payment: stripe | none
  surface: co-located | detached | none   # service/cli only — landing page strategy
```

### `funnel` (required, dict)

```yaml
funnel:
  available_from:
    reach: L1 | L2 | L3
    demand: L1 | L2 | L3
    activate: L2 | L3
    monetize: L2 | L3
    retain: L3
  decision_framework:
    scale: <condition>
    kill: <condition>
    pivot: <condition>
    refine: <condition>
```

### `target_geo` (required, list)

ISO country codes for ad targeting. Used by `/distribute`.

### `deploy` (optional, dict)

Populated by `/deploy`:

```yaml
deploy:
  url: <https url>
  repo: <github org/repo>
  domain: <custom domain>
```

### `design` (optional, dict)

User-supplied visual direction persisted by `/spec` from input flags (`--theme`, `--design-lineage`, `--aesthetic`) and honoured by `scaffold-init` during `/bootstrap`. When a field is set here, it is a **hard constraint** — `scaffold-init` must respect it rather than judging aesthetic direction from `target_user` + `description` alone. Unset fields fall back to agent judgment. Issue #1050.

```yaml
design:
  theme: light | dark | auto      # default auto = scaffold-init decides
  design_lineage: [string]        # e.g., [Linear, Vercel, Rauno Freiberg]
  aesthetic_notes: string         # freeform creative direction, appended to visual brief

  # Issue #1077: feature flag for slot-intent contract consumers.
  # Default: true. When true, scaffold-images / scaffold-landing / scaffold-
  # pages / design-critic / state-2b drift detector read slot-intent.json
  # and route per-slot (skip dynamic_runtime og-photo, apply intended_render,
  # text-fallback for conditional+runtime_gate, drift detection enforces
  # declared-vs-emitted). Set to false ONLY to opt out for legacy
  # compatibility (existing projects that haven't migrated their visual
  # brief). New projects should leave this true.
  slots_enabled: true

  # Issue #1077: per-slot intent contract (optional user override).
  # Declared by scaffold-init at state-10 from product context; user-supplied
  # overrides take precedence verbatim. Read by scaffold-images / scaffold-
  # landing / scaffold-pages / design-critic for budget + render decisions.
  slots:
    <slot-name>:                  # hero | feature-1 | feature-2 | feature-3 | logo | og-photo | empty-state | <custom>
      slot_role: focal | texture | watermark | conditional | none
      production_method: ai_generated | programmatic_css | svg_icon | dynamic_runtime | none
      intended_render:
        opacity: <0.0-1.0>
        blend_mode: <CSS mix-blend-mode value>
        filter: <CSS filter value>
      candidate_budget: high | medium | low
      runtime_gate:               # null OR object
        role: <required role>
        reason: <human description>
        evidence: <citation>
```

- `theme: dark` or `theme: light` overrides `globals.css` color tokens regardless of product domain reasoning.
- `design_lineage` is a mandatory reference set for the visual brief (e.g., agent consults those brands' known aesthetics).
- `aesthetic_notes` is a soft override to the agent's own aesthetic reasoning — e.g., "editorial with engineering precision, not minimalist".
- `slots.<slot>.<key>` (Issue #1077): user override for a slot's declared intent. Each recognized key replaces the derived value verbatim; absent keys fall through to derivation. Use sparingly — defaults are tuned to the design lineage. Schema: see `.claude/scripts/lib/slot_intent_schema.py` (5 oneOf rejection rules R1-R5 caught at scaffold-init write time).

All four fields are optional. When the block is entirely absent, no behavior change.

## Page Inventory Derivation

The canonical page set is computed by `derive_scope_pages()` in
`.claude/scripts/lib/derive_pages.py`:

```
pages = (golden_path[*].page where present)
      ∪ (behaviors[*].pages where archetype is web-app)
      ∪ (auth-derived: login, signup if stack.auth is set)
      \ {None, empty, "landing"}   # landing is owned by scaffold-landing, not scaffold-pages
```

Consumers that need this set MUST call `derive_scope_pages()` (not raw `golden_path`):

- `.claude/skills/bootstrap/state-11c-page-scaffold.md` — spawn list
- `.claude/agents/gate-keeper.md` BG2 check 3b — page count cap
- `.claude/agents/gate-keeper.md` BG2 check 3c — behavior page existence
- `.claude/procedures/scaffold-pages.md` — sitemap generation
- `.claude/stacks/auth/supabase.md` — public path declaration

Consumers that need ordered funnel steps (nav order, funnel tests) call
`derive_funnel_steps()` instead — these access `golden_path` ordering directly.

## Archetype Matrix

| Field | web-app | service | cli |
|---|---|---|---|
| `golden_path` | required | omit | omit |
| `endpoints` | omit | required | omit |
| `commands` | omit | omit | required |
| `behavior.pages` | required (actor: user) | omit | omit |
| `behavior.endpoints` | omit | required | omit |
| `behavior.commands` | omit | omit | required |
| `stack.surface` | n/a | optional (landing strategy) | optional (landing strategy) |

## Migration

Existing experiments (created before `behavior.pages` became required) are
backfilled by `.claude/scripts/migrate-experiment-yaml.py`, which `/upgrade`
invokes as sub-step 1c. The migration helper:

- Skips non-web-app archetypes (`migration_status: not-applicable`)
- Suggests pages from heuristic scan of `behavior.given/when/then` text
- Constrains candidates to pages that already exist as `src/app/<name>/page.tsx`
- Tags suggestions `REQUIRES_USER_REVIEW`; never auto-applies
- Logs to `.runs/upgrade-migration-applied.json`
