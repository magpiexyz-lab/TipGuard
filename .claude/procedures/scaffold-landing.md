# Scaffold: Landing Page

## Prerequisites
- Branch already created (by bootstrap Step 0)
- Step 1 complete (theme tokens in `src/app/globals.css`, visual brief at `.runs/current-visual-brief.md`)
- `.runs/current-plan.md` exists

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: full landing co-located | service: landing only if surface=co-located | cli: landing only if surface=detached
>
> State-specific logic below takes precedence.

## Instructions

Resolve the surface type: if `stack.surface` is set in experiment.yaml, use it.
Otherwise infer: `stack.services[0].hosting` present → `co-located`; absent → `detached`.
Read the surface stack file at `.claude/stacks/surface/<value>.md`.

- **surface: none**: report "surface: none — no landing page needed" and stop.

**All other cases**: generate a world-class landing page.

### 1. Design decisions

Read the visual language brief from `.runs/current-visual-brief.md`. Do NOT
re-derive constraints — the brief contains the canonical design decisions
(color direction, philosophy, optimization target, palette, typography,
animation, spacing, component style, texture, and social proof treatment). Also read the theme tokens
from `src/app/globals.css` and tailwind config (already set in Step 1).

### 2. Apply frontend-design methodology

Apply the preloaded `frontend-design` guidelines (injected via skills) with:
- The three derived constraints
- The quality bar from design.md: "Create a world-class, conversion-optimized
  landing page. The visual quality must match a $50K agency page — not
  adequate, exceptional."
- The full content of experiment.yaml (product context)
- Copy derivation rules from messaging.md Section A (headline = outcome for
  target_user, CTA = action verb + outcome)
- Content inventory from messaging.md Section B (raw material, not structure)

If `frontend-design` guidelines are not available: use your own judgment —
match the product's personality, follow design.md quality bar, and apply
messaging.md content derivation rules. Do not stop or wait.

### 3. Generate the page

Use the frontend-design output to build the landing page. Technical context
varies by archetype:

**web-app + co-located** (React component):
- Include: theme tokens (globals.css custom properties, tailwind config from
  Step 1), available shadcn/ui components, framework page conventions from
  framework stack file. Import analytics functions from `src/lib/events.ts`
  (created by scaffold-libs in Phase B1, which completes before this agent
  launches in Phase B2)
- Read `.runs/image-manifest.json` for generated images. Use the `publicPath`
  from each manifest entry — do NOT hardcode file extensions (images may be
  `.webp` or `.svg` depending on whether AI generation ran). For `.webp` files
  use `next/image` `Image` component; for `.svg` files use `<img>` tags.
  These paths are guaranteed to exist from Phase B1.
- **Slot-intent integration (Issue #1077):** also read `.runs/slot-intent.json` if it exists. When `design_slots_enabled == true`:
  - For each slot in `slot-intent.slots`, apply the declared `intended_render` (opacity / blend_mode / filter) to the image element's className/style. Example for a `slot_role=texture` hero with `intended_render={opacity: 0.08, blend_mode: "luminosity", filter: "none"}`:
    ```tsx
    <Image
      src="/images/hero.webp"
      className="opacity-[0.08] mix-blend-luminosity"
      // ...
    />
    ```
  - For slots with `production_method == "programmatic_css"`, **do not import `<Image>`** for that slot. Emit a CSS gradient `<div>` or styled component instead (e.g., a `bg-gradient-to-br from-primary/20 to-accent/10` hero background).
  - For slots with `production_method == "svg_icon"`, emit inline SVG instead of `<Image>`.
  - For slots with `production_method == "dynamic_runtime"` (e.g., og-photo when `next/og` is the producer), do not reference the static asset.
  - For slots with `slot_role == "none"`, do not render the slot at all.
  - When slot-intent is absent or `design_slots_enabled` is false, fall through to manifest-only behavior (legacy).
- If no `variants`: write `src/app/page.tsx` — a complete React landing
  page component. Must fire `visit_landing` on mount with experiment/EVENTS.yaml properties.
- If `variants`: write `src/components/landing-content.tsx` — a shared
  `LandingContent` component that accepts variant props (headline, subheadline,
  cta, pain_points). Features section is shared across variants (from experiment.yaml
  `behaviors`). The structural routing files (variants.ts, root page, dynamic
  route) are created by the pages subagent in Phase B2 — they exist
  when both agents run.

**service + co-located** (self-contained HTML):
- Include: surface stack file content (route path, analytics wiring, CSS approach)
- Write the route handler file at [path from framework stack file]
  returning a complete self-contained HTML page

**cli + detached** (self-contained HTML):
- Include: surface stack file content (file path, CSS approach)
- Write `site/index.html` as a complete self-contained HTML page

### 3b. Structured data

Generate a JSON-LD `<script type="application/ld+json">` block for the landing page:
- Schema.org type per archetype: `WebApplication` (web-app), `WebAPI` (service), `SoftwareApplication` (cli)
- Properties: `name` (display name per messaging.md Section E), `description` (meta description per Section E), `url` (from deploy manifest `canonical_url`, or `/` if not yet deployed)
- For web-app: embed in layout.tsx body. For service/cli: embed in the inline HTML `<head>`

### 3c. Rendered self-audit (MANDATORY before trace)

Before writing the trace, the agent MUST render the landing page and audit its own output. Source-only inspection cannot catch JSX-vs-string-literal entity bugs (e.g., `"don&apos;t bill"` rendering literally as `don&apos;t` instead of `don't`) or layout-level baseline-alignment defects. These are obvious in one screenshot but invisible in source.

Procedure:

1. Start (or reuse) the dev server. Take screenshots at desktop (1280×800) and mobile (390×844) viewports. For variant-bearing experiments, screenshot the default variant AND every `/v/<slug>` variant route declared in experiment.yaml.
2. Read each screenshot and look for:
   - **HTML entity literals in rendered text** — literal `&amp;`, `&apos;`, `&quot;`, `&#NN;` sequences. The JSX runtime never renders these as text; their presence indicates an entity was embedded inside a JS string literal rather than as JSX text.
   - **Baseline misalignment** in stat-card-shape components (a small caption baselined with the bottom of a large tabular numeral instead of stacked below it).
   - **Horizontal overflow at mobile viewport** — content spilling past the viewport width.
   - **Broken `aspect-video` containers**, broken image fallbacks, missing alt text on visible images.
3. Add the following fields to the trace JSON:
   - `screenshots_taken: [{ viewport: "desktop"|"mobile", variant: "<slug or 'default'>", path: "<path>" }]` — required; at minimum one entry per viewport-variant pair.
   - `rendered_self_check_findings: [...]` — required; empty array is acceptable when no issues are found, but the field must exist so downstream consumers can distinguish "audited and clean" from "silently skipped."

Without `screenshots_taken`, the canonical writer must not accept `verdict: clean`. The `Persuasion Self-Check` dimensions (custom palette, typography hierarchy, etc.) remain source-evaluable as before — this rendered audit covers a strictly different failure class (render-time bugs that source inspection cannot detect).

### 4. Wire analytics

If `stack.analytics` is present and not already included:
- For web-app: verify analytics per `patterns/analytics-verification.md`
- For service/cli: add inline snippet per surface stack file's analytics section.
  When the surface stack template uses the literal `<%POSTHOG_KEY%>` placeholder
  (see `.claude/stacks/surface/co-located.md` Inline analytics snippet block),
  substitute it with the analytics stack file's current `POSTHOG_KEY` constant
  value before writing the file. Procedure:
  1. Read `.claude/stacks/analytics/posthog.md`. Find the line matching
     `const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "<value>";`.
     Extract `<value>` (typically `phc_TEAM_KEY`, but a downstream fork may
     have replaced it with their team's real `phc_xxx` key).
  2. Replace every literal occurrence of `<%POSTHOG_KEY%>` in the rendered
     surface output (`src/app/route.ts` for service co-located, `site/index.html`
     for cli detached) with the extracted value, quoted as a string literal.
  3. Do NOT replace the `phc_TEAM_KEY` literal that appears inside the
     misconfiguration check (`if (!key || key === "phc_TEAM_KEY")`) —
     that comparison is intentional and survives the substitution because
     `<%POSTHOG_KEY%>` is the only template variable.

  This substitution makes the prebuild script (analytics stack file's
  `## Production Observability` Layer 1) able to grep `src/app/route.ts` /
  `site/index.html` for `phc_TEAM_KEY` literally, catching unconfigured forks
  at build time alongside the lib files.

> **Note:** Visual rendering review (screenshots, layout breaks, mobile responsiveness)
> is performed by the design-critic agent in `/verify` (web-app only). Scaffold agents
> are responsible for code-level quality via the Persuasion Self-Check above.

> **Note:** Build verification occurs at the merged checkpoint (STATE 13), after all
> subagents complete. Do not run `npm run build` here — other subagents may still
> be writing files that affect the build.

## Trace Output

Trace authoring follows the canonical pattern in `.claude/agents/scaffold-landing.md` § Trace Output (AOC v1.1 centralized writer).

