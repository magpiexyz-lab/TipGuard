# Scaffold: App Shell & Pages

## Prerequisites
- Packages installed and UI setup complete (Step 1 finished)
- Stack files and archetype file on disk
- `.runs/current-plan.md` exists
- `design.md` choices recorded in globals.css and tailwind config
- `.runs/current-visual-brief.md` exists (visual language brief from init)

## Dependency note

Pages import from `src/lib/events.ts` (created by scaffold-libs in Phase B1).
scaffold-libs completes and writes its manifest before scaffold-pages launches in Phase B2.
The `src/lib/events.ts` file exists when this agent runs — import typed wrappers directly.

## Input Contract (#1387)

State-11c writes a page-keyed behavior contract to `.runs/scaffold-pages-contracts.json` before fan-out, derived from `experiment.yaml.behaviors[*].tests[*]` directive tokens of the form `[audit:<kind>=<arg>]<prose>`. Each scaffold-pages agent MUST read its own slice via direct key access (NOT via `d.values()` — the artifact is stamped with identity fields):

```bash
python3 -c "import json; print(json.dumps(json.load(open('.runs/scaffold-pages-contracts.json')).get('<page-slug>', [])))"
```

Contract entries directly drive page implementation:
- `{"kind": "api-fetch", "arg": "/api/x"}` — the page MUST contain `fetch('/api/x', ...)` whose response is consumed (NOT discarded into ignored const, NOT replaced by `.catch(() => <literal>)` synthesizing static fallback).
- `{"kind": "ai-conversation"}` — the page MUST contain at least one `fetch('/api/...')` AND use `useState`/`useReducer`/`useChat` for turn state.
- `{"kind": "event", "arg": "<event>"}` — the page MUST call `track<Event>(...)` from `src/lib/events.ts` on the appropriate trigger (verb name `event` per audit-verb-registry.json — NOT `event-emit`).
- `{"kind": "sitemap-instance", "arg": "<route>/<segment>"}` — the lead-emitted sitemap.ts MUST iterate over `<segment>` (handled in state-11c post-fan-out — NOT a per-page agent concern).
- `{"kind": "render"}` — trivially satisfied by page existence.
- `{"kind": "untagged"}` — soft warning only (backward compat for legacy experiment.yaml tests; Group A's audit-verb registry will tighten in a follow-up).

Post-fan-out, state-11c runs `behavior_contract_auditor.py` against this contract. Uncovered tagged entries BLOCK PR creation. Layer 4b runtime check (behavior-verifier B7 in `/verify`) catches AST-undetectable stubs — the load-bearing trustworthy verification.

## Self-Check Score Schema (#1387)

The agent's trace JSON file (written via `write-agent-trace.sh`) MUST emit `self_check_score` as a typed sub-object OR `self_check_score_explicit_none: true` + `self_check_score_explicit_none_reason: <enum>`.

```python
"self_check_score": {
    "visual_coherence": 9,         # int 0-10 per Utility Self-Check dimension
    "information_hierarchy": 9,
    "interaction_completeness": 9,
    "layout_purpose": 9,
    "component_quality": 9,
    "functional_animation": 9,
},
# XOR alternative (rerun-recovery or phase-a-authored only):
# "self_check_score_explicit_none": True,
# "self_check_score_explicit_none_reason": "agent-skipped-self-check"
#   | "phase-a-authored" | "rerun-recovery" | "other",
```

The score sub-object enables design-critic Stage 0 fast-path to consume the agent's self-reports as structured data (not prose). Validator: `.claude/scripts/validate-self-check-score-schema.py` (env `SELF_CHECK_SCORE_SCHEMA_MODE`, default `warn`). Warn-default mode in this PR; flips to fail after rollout per AOC v1.2 invariants.

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: app shell + SEO + pages | service: API routes only | cli: command modules only

### web-app

#### App shell (Step 3)
- Follow the framework stack file's file structure and page conventions
- **Root layout**: metadata from experiment.yaml `title`, import globals.css. Set up the display font per the UI stack file's "Theme Setup" section (chosen font via `next/font/google`, apply variable to `<html>`). The `retain_return` tracking component (RetainTracker) and NavBar are wired into layout.tsx later by scaffold-wire (Step 5c) — do not add them here.
- **404 page**: simple not-found page with link back to `/`
- **Error boundary**: user-friendly message and retry button

#### SEO baseline (Step 3b, web-app only)
- **Sitemap (`src/app/sitemap.ts`) is authored by the LEAD post-fan-out (#1387)** — NOT by this agent. State-11c post-fan-out invokes the sitemap emitter, which consumes both `derive_scope_pages(experiment)` (static slugs) and `dynamic_public_pages(experiment)` (concrete fixture-slug instances declared via `behaviors[*].dynamic_segments`). Authorship moved from Phase A so fixture data declared in experiment.yaml can be consumed after Phase B2 fan-out completes. See `.claude/skills/bootstrap/state-11c-page-scaffold.md` "Post-fan-out: sitemap.ts authorship" section.
- Generate `src/app/robots.ts` — export a default function returning `MetadataRoute.Robots` allowing all crawlers (`{ rules: { userAgent: '*', allow: '/' } }`)
- Generate `public/llms.txt` — content per messaging.md Section E (display name, meta description, behaviors list)
- Ensure layout.tsx `metadata` export uses messaging.md Section E derivation: `title` = meta title, `description` = meta description, `openGraph` = `{ title, description }`

#### Pages (Step 4)

### Page.tsx export constraint (Next.js requirement)

Next.js page route files (`src/app/<page>/page.tsx`, `src/app/<page>/[seg]/page.tsx`) allow ONLY these named exports:

- `default` (the page component)
- `generateStaticParams`, `generateMetadata`, `metadata`
- `dynamic`, `dynamicParams`, `revalidate`, `fetchCache`, `runtime`, `preferredRegion`, `maxDuration`

ANY other `export const` / `export function` / `export type` from `page.tsx` fails the build with `"<name>" is not a valid Next.js entry export value. [71002]`. This includes the JS-idiomatic pattern of exporting a fixture array for `generateStaticParams` to reuse:

```tsx
// WRONG — fails the build (export of non-route symbol)
export const SAMPLE_TOKENS = ["demo-fixture-token"] as const;
export function generateStaticParams() {
  return SAMPLE_TOKENS.map((token) => ({ token }));
}

// CORRECT (a) — declare without `export` if used only locally
const SAMPLE_TOKENS = ["demo-fixture-token"] as const;
export function generateStaticParams() {
  return SAMPLE_TOKENS.map((token) => ({ token }));
}

// CORRECT (b) — move to a colocated non-page file when it must be importable
// src/app/<page>/fixtures.ts
//   export const SAMPLE_TOKENS = ["demo-fixture-token"] as const;
// src/app/<page>/page.tsx
//   import { SAMPLE_TOKENS } from "./fixtures";
```

For each page in the canonical SET — compute via:

```bash
python3 .claude/scripts/lib/derive_pages.py scope < experiment/experiment.yaml
```

This yields `derive_scope_pages(experiment)` = union of `golden_path[*].page`,
`behaviors[*].pages`, and auth-derived pages, with `landing` excluded
(scaffold-landing owns it). For each returned page:
- If `name` is `landing` → create the root page
- Otherwise → create a page at the appropriate route
- Every page file must:
  - Follow page conventions from the framework stack file
  - If `stack.analytics` is present: import tracking functions per the analytics stack file conventions and fire the appropriate experiment/EVENTS.yaml event(s) on the correct trigger
  - Follow `.claude/patterns/design.md` quality invariants (form input sizing). Aim for a distinctive, polished look that matches the product domain.
  - For empty states (empty tables, lists, dashboards): read `.runs/image-manifest.json` and use the empty-state image at the `publicPath` listed there — do NOT hardcode the file extension (it may be `.svg` or `.webp` depending on whether AI image generation ran). Example: if manifest shows `"publicPath": "/images/empty-state.webp"`, use `<Image src="/images/empty-state.webp" alt="No items yet" width={400} height={400} />`.
    
    **Slot-intent fallback (Issue #1077):** when `.runs/slot-intent.json` exists AND `design_slots_enabled == true` AND `slots["empty-state"].slot_role == "conditional"` AND `runtime_gate != null`, the empty-state image was NOT generated (scaffold-images skipped the slot). Render a **text-only fallback** instead of `<Image>`:
    ```tsx
    {/* slot-intent: empty-state runtime_gated by role, image unreachable in DEMO_MODE */}
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <p className="text-lg font-medium text-foreground">No items yet</p>
      <p className="mt-2 text-sm text-muted-foreground">
        {/* Customize per page context — message should reflect the runtime_gate.role and product domain */}
        This view requires a different account role.
      </p>
    </div>
    ```
    Quick check before emitting empty-state imports:
    ```bash
    python3 -c "
    import json, os
    if os.path.exists('.runs/slot-intent.json'):
        d = json.load(open('.runs/slot-intent.json'))
        if d.get('design_slots_enabled'):
            es = d.get('slots', {}).get('empty-state', {})
            if es.get('slot_role') == 'conditional' and es.get('runtime_gate'):
                print('USE_TEXT_FALLBACK=true')
    "
    ```
  - If an event from the experiment/EVENTS.yaml events map has no matching page in experiment.yaml (e.g., no signup page for signup_start/signup_complete), omit that event — do not create a page just to fire it
- **Landing page**: Do NOT generate the landing page content here — it is
  created by the landing-page subagent (see `scaffold-landing.md`). If
  experiment.yaml has `variants`, create only the structural routing files here:
  - `src/lib/variants.ts` — typed `VARIANTS` array (slug, headline,
    subheadline, cta, pain_points, isDefault) and `getVariant(slug)` helper
  - Root `src/app/page.tsx` — imports and renders `LandingContent` with the
    default variant's props, **wrapped in `<Suspense fallback={null}>`**. Fires
    `visit_landing` with `variant` property.
  - `src/app/v/[variant]/page.tsx` — dynamic route, imports `LandingContent`
    **wrapped in `<Suspense fallback={null}>`**, fires `visit_landing` with
    `variant` property. `generateStaticParams()` for all variant routes.
    Returns `notFound()` for unknown slugs.

  **Suspense requirement (#1150):** `LandingContent` calls `useSearchParams()`
  to read `utm_source` for the `landing_viewed` event payload. Per
  `.claude/stacks/framework/nextjs.md` § *Suspense Requirements*, every
  Next.js 16 caller of `useSearchParams()` must be wrapped in a `<Suspense>`
  boundary above the leaf — without it the build fails with
  `useSearchParams() should be wrapped in a suspense boundary at page "/v/[variant]"`.
  Both wrapper files import `Suspense` from `react`:

  ```tsx
  // src/app/page.tsx
  import { Suspense } from "react";
  import { LandingContent } from "@/components/landing-content";
  import { getVariant } from "@/lib/variants";

  export default function Home() {
    const variant = getVariant();
    return (
      <Suspense fallback={null}>
        <LandingContent {...variant} />
      </Suspense>
    );
  }
  ```

  Mirror the same Suspense wrap inside `src/app/v/[variant]/page.tsx`.

  If no `variants`, skip entirely — the landing-page subagent creates `src/app/page.tsx`.
- **Auth pages (if listed in golden_path)**: signup/login form pages using auth provider UI templates from the auth stack file. Create only the page files (`signup/page.tsx`, `login/page.tsx`) — auth infrastructure (callback, reset-password, nav-bar) is created by scaffold-wire.
  Fire the corresponding experiment/EVENTS.yaml events at their specified triggers.
  If `stack.auth_providers` is present in experiment.yaml: add OAuth login buttons for each
  listed provider below the email/password form, using the OAuth button template and
  `handleOAuthLogin` function from the auth stack file's "OAuth buttons" section.
  Fire `trackSignupStart({ method: "<provider>" })` before the OAuth redirect.
  Update the post-auth redirect in signup and login pages to navigate to the first
  non-auth, non-landing page from experiment.yaml (e.g., `/dashboard`). If no such page
  exists, keep the redirect to `/`.
- If `stack.email` is present: wire the welcome email API call into the auth success callback. After `signup_complete` event fires, call `/api/email/welcome` with the user's email and name. Read the email stack file for the route handler template.
- **All other pages**: For each non-landing, non-auth page, apply the
  preloaded `frontend-design` guidelines (injected via skills) with:
  - The existing theme tokens (from `src/app/globals.css` and tailwind config)
  - The page's `purpose` from experiment.yaml
  - The visual language brief from `.runs/current-visual-brief.md` (palette,
    typography, animation, spacing, component style, and texture decisions)
  - Instruction: "Design a top-tier SaaS product screen (think Linear, Vercel,
    Raycast). Follow the visual language brief for palette, typography,
    animation, spacing, and component styling. Optimized for utility: clear
    information hierarchy, appropriate data density, loading states, empty
    states, micro-interactions. Not a marketing page — a professional tool
    interface."
  If `frontend-design` guidelines are not available: use your own judgment —
  consume the theme tokens, match the product's visual identity, and follow
  the inner page utility criteria from design.md.
  Each page must have heading, description matching purpose, and a clear
  next-action CTA.
  - **Forward navigation:** If this page is not the last step in `golden_path`,
    include a prominent forward CTA (button or link) that navigates to the
    next golden_path step's page route. Read `golden_path` from experiment.yaml
    to determine the next step. This prevents dead-end pages where users
    complete an action but have no path forward.

#### Feature→UI cross-reference (after page creation)

For each experiment.yaml `behavior` that has a corresponding API route:
1. Check if the behavior describes a **user-facing interaction** (chat, wizard, form, file upload, etc.) — not just a background process or data query
2. If yes, check if a page in experiment.yaml already provides the UI for this interaction
3. If no page exists: create a reusable component at `src/components/<feature>-widget.tsx` that calls the API route and provides the interactive UI
4. Ensure any landing page CTA referencing this feature opens or navigates to the component — not an unrelated page

This step only applies to the **web-app** archetype. Skip for service and cli.

> **STOP** — verify analytics per `patterns/analytics-verification.md` before finishing (skip if `stack.analytics` is absent).

> **Note:** Visual rendering review (screenshots, layout breaks, mobile responsiveness)
> is performed by the design-critic agent in `/verify` (web-app only). Scaffold agents
> are responsible for code-level quality via the Utility Self-Check above.

### service

Skip shell and pages. Create API directory structure only:
- `src/app/api/` directory with placeholder route folders for each endpoint in experiment.yaml
- Follow the framework stack file's route handler conventions

### cli

Skip shell and pages. Create CLI entry point and command modules:
- `src/index.ts` — CLI entry point with bin config
- `src/commands/` — one module per experiment.yaml command
- Follow the framework stack file's conventions

