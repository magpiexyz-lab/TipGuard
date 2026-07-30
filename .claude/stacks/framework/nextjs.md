---
assumes: []
packages:
  runtime: [next, react, react-dom]
  dev: [typescript, "@types/react", "@types/node", "eslint@9", "@eslint/js", typescript-eslint, eslint-plugin-react-hooks, "@next/eslint-plugin-next"]
files:
  - .nvmrc
  - eslint.config.mjs
  - src/app/layout.tsx
  - src/app/page.tsx              # conditional: web-app
  - src/app/route.ts              # conditional: service with co-located surface
  - src/app/not-found.tsx         # conditional: web-app
  - src/app/error.tsx             # conditional: web-app
  - src/app/icon.tsx              # conditional: web-app
  - src/app/opengraph-image.tsx   # conditional: web-app
  - src/app/sitemap.ts            # conditional: web-app
  - src/app/robots.ts             # conditional: web-app
  - src/components/RetainTracker.tsx  # conditional: web-app
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: [.nvmrc, package.json, package-lock.json, tsconfig.json, next.config.ts, next-env.d.ts, eslint.config.mjs]
  dirs: [node_modules, .next, out]
gitignore: [.next/, out/]
emits_events: [retain_return]  # conditional: only when stack.analytics is present; framework template fires from src/components/RetainTracker.tsx
---
# Framework: Next.js (App Router)
> Used when experiment.yaml has `stack.services[].runtime: nextjs`

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.

> **Conditional files**: Files marked `# conditional` in the frontmatter `files` list are only created when the condition matches. Bootstrap skips conditional files whose archetype or surface type does not apply. The archetype file (`.claude/archetypes/<type>.md`) and the resolved surface type determine which conditionals are included.

## Packages
```bash
npm install next react react-dom
npm install -D typescript @types/react @types/node eslint@9 @eslint/js typescript-eslint eslint-plugin-react-hooks @next/eslint-plugin-next
# Pin eslint@9 — eslint-plugin-react-hooks requires flat config (eslint 9); update all 4 framework stack files when eslint 10 ships
```

## Project Setup
- `.nvmrc`: containing `20` (used by CI and local version managers)
- `package.json`: `scripts` with `dev`, `build`, `start`, `lint` (`eslint src/`); `engines: { "node": ">=20" }`. Stack-specific scripts (e.g., `prebuild` for database auto-migrate) are added by the owning scaffold-libs stage together with the target file it invokes — scaffold-setup must NOT write such script entries ahead of the helper file's creation, which would leave a fragile window where any intermediate `npm run build` fails at an unresolvable `prebuild`.
- `tsconfig.json`: enable `strict: true`, `@/` path alias mapping to `src/`, and `exclude: ["node_modules", ".next", ".runs", "scripts"]` — see the Stack Knowledge entry "tsconfig.json must exclude .runs/ AND scripts/" for the rationale
- `next.config.ts`: starts minimal. Stack files extend it conditionally with their own `nextConfig` blocks (rewrites, env injection, etc.) — additions are merged into a single object literal, not stacked configs. Notable extensions:
  - `analytics/posthog.md` adds `rewrites()` for the `/ingest/*` proxy and `skipTrailingSlashRedirect: true`.
  - `analytics/posthog.md` (and any stack relying on a deploy-environment client-side gate) requires an `env` block injecting `NEXT_PUBLIC_VERCEL_ENV: process.env.VERCEL_ENV ?? ""`. Vercel does NOT auto-prefix system env vars with `NEXT_PUBLIC_` — without this injection, client-side `process.env.NEXT_PUBLIC_VERCEL_ENV` is `undefined` and any `=== "production"` gate evaluates to false even on real production deploys. The `?? ""` keeps the value defined-but-empty when the build runs outside Vercel (local dev, bootstrap), so gates fall through to non-production code paths cleanly.

  Combined example (when both `stack.analytics: posthog` and `stack.hosting: vercel` are present):
  ```ts
  import type { NextConfig } from "next";
  const nextConfig: NextConfig = {
    env: {
      NEXT_PUBLIC_VERCEL_ENV: process.env.VERCEL_ENV ?? "",
    },
    async rewrites() {
      return [
        { source: "/ingest/decide", destination: "https://us.i.posthog.com/decide" },
        { source: "/ingest/:path*", destination: "https://us.i.posthog.com/:path*" },
      ];
    },
    skipTrailingSlashRedirect: true,
  };
  export default nextConfig;
  ```

### `eslint.config.mjs`
```js
import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import nextPlugin from "@next/eslint-plugin-next";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  { plugins: { "react-hooks": reactHooks }, rules: { ...reactHooks.configs.recommended.rules, "react-hooks/set-state-in-effect": "off" } },
  { plugins: { "@next/next": nextPlugin }, rules: nextPlugin.configs.recommended.rules },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
    },
  },
  { ignores: [".next/", "out/", "node_modules/", "src/components/ui/", "src/components/magicui/"] }
);
```
> **Underscore-prefix convention:** The `^_` ignore pattern lets you mark intentionally unused params as `_userId`, `_brandId`, etc. without tripping `no-unused-vars` — standard TS/ESLint convention. Without it, any project with an unused underscore-prefixed callback param (common in API handlers, test stubs, typed wrappers) fails `npm run lint`.

> **Known Issue — `eslint-disable` comments:** When generating `eslint-disable-next-line` comments, use the generic form (`// eslint-disable-next-line`) without a rule name. Rule-specific forms like `// eslint-disable-next-line react/no-danger` cause errors if the corresponding plugin (e.g., `eslint-plugin-react`) is not installed. Only specify rule names for rules known to be configured in the eslint config above.

## File Structure

**web-app archetype:**
```
src/
  app/              # App Router pages and API routes
    layout.tsx      # Root layout — <html>, <body>, metadata, globals.css import
    page.tsx        # Landing page (/)
    not-found.tsx   # 404 page with link back to / — MUST export a `metadata` object
    error.tsx       # Error boundary with "use client", user-friendly message, retry + home link
    icon.tsx        # Dynamic favicon -- monogram in primary color (Next.js Metadata File API)
    opengraph-image.tsx  # Dynamic OG image -- branded card (Next.js Metadata File API)
    api/            # API route handlers (all mutations go here)
      <resource>/
        route.ts    # Route handler
    <page-name>/    # One folder per experiment.yaml page
      page.tsx      # Page component
  components/       # Reusable UI components
    ui/             # UI library components (auto-generated)
  lib/              # Utilities (analytics, database clients, types, etc.)
```

**service archetype:** No page folders, no UI components, no `src/components/` directory.
```
src/
  app/              # App Router — API routes only
    layout.tsx      # Root layout (minimal — required by Next.js App Router)
    route.ts        # Root route handler (GET /) — co-located surface HTML page
    api/            # API route handlers
      <endpoint>/
        route.ts    # Endpoint handler
  lib/              # Utilities (analytics, database clients, types, etc.)
```
The root `route.ts` is created only when surface is `co-located` (the default for services). It returns a complete HTML marketing page — see `surface/co-located.md` for content guidance.

## Page Conventions
- Default to `"use client"` for all page and component files
- Exception: `layout.tsx` MUST remain a server component (required for `metadata` export). Do NOT add "use client" to layout.tsx.
- One `page.tsx` per route folder
- `layout.tsx` for root layout only
- Import analytics tracking functions in every page that fires events (see analytics stack file for exports)
- Exception: when a page needs both `generateStaticParams()` (server export) and client-side hooks (`useEffect`, analytics tracking), split into two files:
  - `page.tsx` — server component, exports `generateStaticParams`, imports and renders the client component with props
  - `<name>-client.tsx` — `"use client"`, receives props, handles interactivity and analytics
  Next.js does not allow `generateStaticParams` in `"use client"` components.

### SEO Metadata Conventions
- `layout.tsx` MUST export a `metadata` object (Next.js Metadata API) with `title`, `description`, and `openGraph` fields — derived per messaging.md Section E
- Variant pages export `generateMetadata()` to override layout defaults with variant-specific title/description
- JSON-LD structured data — archetype-specific injection:
  - **web-app** (React): use `next/script` with the JSON passed as children. This avoids the React prop that takes a `{ __html: ... }` payload (which trips security-review hooks and forces an `eslint-disable` that then fails as an unused-disable). `next/script` renders inline `<script>` safely from the children string.

    ```tsx
    import Script from "next/script";
    // ...
    <Script id="ld-app" type="application/ld+json" strategy="beforeInteractive">
      {JSON.stringify(jsonLd)}
    </Script>
    ```

  - **service / cli** (plain HTML): write `<script type="application/ld+json">...</script>` directly in the inline HTML `<head>` — no React, so the prop concern does not apply (see `procedures/scaffold-landing.md` per-archetype JSON-LD embedding).

  Schema.org type per archetype: `WebApplication` (web-app), `WebAPI` (service), `SoftwareApplication` (cli).
- `src/app/sitemap.ts`: export a default function returning `MetadataRoute.Sitemap` — URLs derived from `derive_scope_pages(experiment)` (call `python3 .claude/scripts/lib/derive_pages.py scope < experiment/experiment.yaml`); see `.claude/procedures/scaffold-pages.md` Step 3b for the contract
- `src/app/robots.ts`: export a default function returning `MetadataRoute.Robots` — allow all crawlers for MVP (`{ rules: { userAgent: '*', allow: '/' } }`)

### Paid-attribution capture (when `stack.analytics: posthog` is present)

Google Ads sends users with `?gclid=EAI...` in the URL. Next.js client-side router may call `replaceState()` during hydration to strip query params (depending on page-level code). PostHog SDK loads lazily via `import("posthog-js").then()` — if the SDK loses the race against URL cleanup, `$session_entry_gclid` is empty and the click is unattributable. Observed in production: foundrygraph 0.5% gclid capture, pingback 14%, report-pilot 24% (vs healthy stylica-ai 96%, x-predict 91%).

Mitigation: an inline `<Script>` in `<head>` captures `gclid` and `utm_*` synchronously into `sessionStorage` BEFORE any React/Next.js code runs. The `loaded` callback in `analytics.ts` reads from sessionStorage and registers as super-properties via `posthog.register()` (it also registers `project_name`/`project_owner` as session super-properties so SDK auto-events stay attributable — see analytics/posthog.md). `/iterate --cross` uses `coalesce($session_entry_gclid, properties.gclid)` to attribute via whichever capture path succeeded — see `.claude/scripts/lib/gclid_filter.py`.

Wire the Script element into `src/app/layout.tsx` (added by scaffold-wire Step 5c when `stack.analytics: posthog`). `strategy="beforeInteractive"` automatically hoists the script into the document `<head>` and guarantees execution before React hydration — placement inside the JSX tree (inside `<body>` as a sibling of `{children}`, OR inside an explicit `<head>` if the layout defines one) does not affect when it runs. The convention is to keep it as the first child of `<body>` for readability:

```tsx
import Script from "next/script";

// In src/app/layout.tsx — strategy="beforeInteractive" hoists to <head> regardless
// of JSX placement. Must be in the ROOT layout (not nested layouts or pages).
<Script id="capture-paid-attribution" strategy="beforeInteractive">
  {`
    try {
      var p = new URLSearchParams(window.location.search);
      var g = p.get('gclid');
      // Match the /iterate --cross filter at the source: only stamp gclids
      // that look real (length > 40, prefix in {Cj, EAI, CIa}). Test gclids
      // like 'analytics-verify-*' (32 chars) and 'MANUAL_VERIFY_CHECK' are
      // excluded here so they never make it into the analytics pipeline.
      if (g && g.length > 40 && /^(Cj|EAI|CIa)/.test(g)) {
        sessionStorage.setItem('__ph_gclid', g);
      }
      ['utm_source','utm_medium','utm_campaign','utm_content','utm_term'].forEach(function(k){
        var v = p.get(k);
        if (v) sessionStorage.setItem('__ph_' + k, v);
      });
    } catch (e) {
      // sessionStorage unavailable (private mode, sandboxed iframe); skip
    }
  `}
</Script>
```

Notes:
- The 40-char + prefix filter at the source means PostHog never receives operator test gclids — `properties.gclid` is always clean.
- The `loaded` callback in `analytics.ts` reads `__ph_gclid` / `__ph_utm_*` from sessionStorage and stamps every event automatically (alongside the `project_name`/`project_owner` session super-properties); no per-event code change needed.
- This script is wired into layout.tsx by `.claude/procedures/wire.md` Step 5c — only when `stack.analytics: posthog` is configured.
- Storage key prefix `__ph_` (double underscore) namespaces these private keys from any application-level sessionStorage usage and signals "do not touch — internal analytics" to readers.

## React 19 Patterns
- Use ref as a regular prop -- do NOT use `React.forwardRef`. React 19 passes ref as a standard prop.
- Use `useActionState` instead of `useFormState` (renamed in React 19).

## Suspense Requirements
- Any component using `useSearchParams()` MUST be wrapped in a `<Suspense>` boundary (Next.js 15 requirement)
- Pattern: create a client component that uses the hook, wrap it in Suspense in the parent page

## API Route Conventions
- Route handlers in `src/app/api/<resource>/route.ts`
- Validate all input with zod — always include `.max()` bounds on all string and array fields. Suggested defaults: short text fields `.max(200)`, long text fields `.max(5000)`, array fields `.max(50)`. Adjust per business logic. Without bounds, a single oversized request can exhaust memory or run up large inference costs.
- Dynamic route segment params (e.g., `[id]` in `src/app/api/projects/[id]/route.ts`) must be validated before use. Parse `params` with zod: `z.object({ id: z.uuid() }).parse(await params)`. Reject non-UUID values with 400 before they reach database queries. This prevents malformed inputs (SQL-injection-style strings, excessively long values) from reaching the database layer.
- Return `{ error: string }` with appropriate HTTP status codes on failure
- Use try/catch, return user-friendly error messages
- When catching `ZodError`, return generic `{ error: "Invalid request" }` with status 400 — never forward `error.issues` or `error.message` which expose schema structure to attackers (OWASP A4-InfoLeakage)

## CORS Policy

API routes use same-origin by default (no CORS headers needed for same-domain requests). When cross-origin access is required:

- Set `ALLOWED_ORIGIN` env var to the specific origin (e.g., `https://app.example.com`)
- Never use `Access-Control-Allow-Origin: *` on routes that require authentication
- Apply CORS headers in the route handler:
```typescript
const allowedOrigin = process.env.ALLOWED_ORIGIN;

export async function OPTIONS() {
  return new Response(null, {
    headers: {
      "Access-Control-Allow-Origin": allowedOrigin ?? "",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}
```
- For MVP experiments, same-origin is almost always sufficient — add CORS only when a separate frontend or mobile app calls the API

## Data Fetching
- Client-side: `fetch` in useEffect or SWR
- Server-side (API routes): direct database calls via server client

## Restrictions
- No Server Actions — use API routes for all mutations
- No caching configuration (`revalidate`, `cache`, etc.)
- No parallel routes or intercepting routes
- No `@apply` with custom class names in CSS -- Tailwind v4 only supports `@apply` with utility classes. Use inline utility classes or `@theme` for custom values.

### `src/app/error.tsx` — Error boundary (web-app only)

```tsx
"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
      <h2 className="text-2xl font-bold">Something went wrong</h2>
      <p className="text-muted-foreground max-w-md">
        An unexpected error occurred. You can try again or go back to the home page.
      </p>
      <div className="flex gap-2">
        <Button onClick={() => reset()}>Try again</Button>
        <Link href="/" className={buttonVariants({ variant: "outline" })}>Back to Home</Link>
      </div>
    </div>
  );
}
```

Notes:
- Always include both a retry button (`reset()`) and a navigation link — if the error is persistent, the user needs an escape route
- The `Link` import is from `next/link`; the `Button` import assumes shadcn/ui is present (when `stack.ui: shadcn`, which is the default)

## Accessibility

> This section is **unconditional** — it applies to every web-app bootstrap regardless of `stack.analytics`, `stack.auth`, or variants.

### Root layout — skip-nav link + `<main id="main-content">` for WCAG 2.4.1 (Bypass Blocks)

The root `<body>` must include a visually-hidden skip-navigation anchor before the first visible navigation block, and the `<main>` wrapper around `{children}` must carry `id="main-content"` so the anchor can target it. Keyboard users tab to the skip link first and jump past every repeated nav item.

```tsx
// In src/app/layout.tsx <body>:
// Added by scaffold-wire Step 5c when stack.auth is present:
import { NavBar } from "@/components/nav-bar";
// Added by scaffold-wire Step 5c when stack.analytics is present:
import { RetainTracker } from "@/components/RetainTracker";

<a
  href="#main-content"
  className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-background focus:text-foreground focus:rounded"
>
  Skip to main content
</a>
{/* Only when stack.auth is present — scaffold-wire Step 5c adds this: */}
<NavBar />
{/* tabIndex={-1} makes the wrapper programmatically focusable so the skip-link
    anchor moves focus here on activation. Without it, Tab from the link cycles
    back to the link (WCAG 2.4.1 Bypass Blocks fails). -1 keeps the wrapper
    out of the natural tab order; mouse clicks still focus actual descendants. */}
<main id="main-content" tabIndex={-1}>{children}</main>
{/* Only when stack.analytics is present — scaffold-wire Step 5c adds this: */}
<RetainTracker />
```

ALL THREE additions are required for WCAG 2.4.1 to pass: (1) the `<a href="#main-content">` skip link before the first nav block, (2) `id="main-content"` on the `<main>` wrapper, AND (3) `tabIndex={-1}` on the same `<main>`. Without the skip link, keyboard-only users must tab through every nav item on every page; without the matching `id`, the skip link has nowhere to jump; without `tabIndex={-1}`, the link's target is not programmatically focusable — activating the skip link does not move focus and Tab cycles back to the link.

### Multi-nav layouts — unique `aria-label` on each `<nav>`; decorative logos `alt=""`

Pages that render more than one `<nav>` (e.g., top NavBar + landing-page marketing nav, or NavBar + footer) must give each `<nav>` element a unique `aria-label`. Without labels, screen readers announce both as "navigation" with no way for the user to distinguish them.

```tsx
<nav aria-label="Primary">{/* main NavBar */}</nav>
<nav aria-label="Footer">{/* footer nav */}</nav>
```

When a logo `<img>` or `<Image>` is placed directly next to visible brand text, set `alt=""` and `aria-hidden="true"` on the image so the brand name is not announced twice.

```tsx
import Image from "next/image";
import Link from "next/link";

<Link href="/" className="flex items-center gap-2">
  {/* unoptimized: next/image rejects SVG by default — see "When loading SVG assets through next/image" below. */}
  <Image src="/images/logo.svg" alt="" aria-hidden width={32} height={32} unoptimized />
  <span>APP_NAME</span>
</Link>
```

If the logo is standalone (no adjacent brand text), keep `alt="APP_NAME"` — only decorate with `alt=""` when the text is already announced.

## retain_return Tracking

When `stack.analytics` is absent: skip this entire section — the RetainTracker component exists solely to fire analytics events.

Create a client component for retain_return tracking and render it in the root layout. **Created by scaffold-wire (Step 5c)** — not by scaffold-pages (which is barred from `src/components/`). This keeps the root layout as a server component (required for `metadata` export) while running client-side localStorage logic in a separate component.

### `src/components/RetainTracker.tsx` — Client component
```tsx
"use client";

import { useEffect } from "react";
import { trackRetainReturn } from "@/lib/events";

export function RetainTracker() {
  useEffect(() => {
    try {
      const lastVisit = localStorage.getItem("last_visit_ts");
      if (lastVisit) {
        const days = Math.floor((Date.now() - Number(lastVisit)) / 86_400_000);
        if (days >= 1) {
          trackRetainReturn({ days_since_last: days });
        }
      }
      localStorage.setItem("last_visit_ts", String(Date.now()));
    } catch {
      // localStorage unavailable — skip silently
    }
  }, []);

  return null;
}
```

In the root layout (a server component — do NOT add "use client" to layout.tsx).
These imports are added by **scaffold-wire (Step 5c)** after creating the components:
```tsx
// Added by scaffold-wire Step 5c when stack.analytics is present:
import { RetainTracker } from "@/components/RetainTracker";
// Added by scaffold-wire Step 5c when stack.auth is present:
import { NavBar } from "@/components/nav-bar";

// Inside the <body> tag — see the Accessibility section above for the full
// skip-nav link + <main id="main-content" tabIndex={-1}> pattern that applies
// unconditionally. The tabIndex={-1} is REQUIRED for WCAG 2.4.1 (skip-link
// target must be programmatically focusable).
<NavBar />           {/* Only when stack.auth is present — scaffold-wire Step 5c */}
<main id="main-content" tabIndex={-1}>{children}</main>
<RetainTracker />    {/* Only when stack.analytics is present — scaffold-wire Step 5c */}
```

## Security
- All `"use client"` components run in the browser — never import server-only secrets or database admin clients in client components
- API route handlers (`src/app/api/`) run server-side — use them for all mutations and sensitive operations
- Validate all API route inputs with zod before processing
- Return generic error messages to the client — do not leak stack traces or internal details

## Stack Knowledge

### When a form or status message uses a conditionally-mounted role=alert element

Mount the alert region **unconditionally** on first render and toggle its visibility with the Tailwind `sr-only` class (or `hidden`) — never use `{condition && <div role="alert">...}`. A conditionally-mounted live region is absent from the accessibility tree at page load, so the browser never registers it as a live region. When the element mounts after a state change, the announcement fires inconsistently — VoiceOver/Safari and NVDA/Firefox silently drop the message in many cases. axe-core flags this as WCAG 4.1.3 (Status Messages) High.

```tsx
// WRONG — live region absent on initial render; announcement silently drops on mount
{error && (
  <div role="alert">{error}</div>
)}

// CORRECT — always-mounted live region; visibility toggled via sr-only
<div
  role="alert"
  aria-live="assertive"
  aria-atomic="true"
  className={error ? "" : "sr-only"}
>
  {error ?? ""}
</div>
```

Required attributes on the always-present container:

- `role="alert"` (or `role="status"` for non-urgent updates)
- `aria-live="assertive"` (use `"polite"` for non-urgent updates)
- `aria-atomic="true"` so screen readers announce the full updated content, not just the diff

Update the **text content** of the always-mounted element to trigger the announcement — adding/removing the element from the DOM does not reliably fire one. The `sr-only` class (Tailwind's visually-hidden utility) keeps the empty state out of the visual layout while preserving the node in the accessibility tree.

Apply to: form validation errors, autosave status indicators, toast-replacement inline notices, signup/login submission feedback. Common scaffolded pages where this matters: preview/preview-view.tsx, signup/login form components, any `<form>` that surfaces async errors.

### When inline SVG `<text>` needs CSS font features (tabular numbers, ligatures, etc.)

Pass `fontFeatureSettings` via the `style` prop, NOT as a JSX attribute. React does not recognize `fontFeatureSettings` as a valid SVG element prop — it emits an "unrecognized prop" warning and the server-rendered HTML diverges from the client tree, producing a hydration mismatch. tabular-numeric alignment (`"tnum"`) is lost on the first client render.

```tsx
// WRONG — React drops the prop, hydration mismatch
<text fontFeatureSettings='"tnum"'>{value}</text>

// CORRECT — style prop carries the CSS font-feature-settings declaration
<text style={{ fontFeatureSettings: '"tnum"' }}>{value}</text>
```

Applies to any inline SVG text element that needs CSS font features: tabular numbers in dashboards / data viz, small-caps / oldstyle figures in marketing copy, contextual ligatures in display headings. The pattern generalizes to other CSS-only SVG presentation properties whose JSX prop spelling is camelCase but is not in React's SVG attribute whitelist (e.g., `paintOrder`).

### When loading SVG assets through `next/image`

`next/image` rejects SVG sources by default — the optimizer image endpoint returns HTTP 400 and the browser falls back to the broken-image glyph. Two acceptable patterns:

```tsx
import Image from "next/image";

// CORRECT (a) — keep <Image> for layout/lazy/responsive behavior, opt out of optimization for SVG
<Image src="/images/logo.svg" alt="" aria-hidden width={32} height={32} unoptimized />

// CORRECT (b) — use plain <img> for one-off SVGs that don't need next/image's responsive features
<img src="/images/logo.svg" alt="" aria-hidden width={32} height={32} />
```

Both patterns ship the SVG file as-is to the browser (no rasterization or format conversion). Choose (a) when the slot already uses `<Image>` and consistency matters (e.g., NavBar logo next to PNG/WebP siblings); choose (b) for landing-page hero illustrations and standalone SVG icons. Never write `<Image src="*.svg" />` without `unoptimized` — it produces a broken image on every page that renders the component.

The auto-scaffolded NavBar logo (created from `auth/supabase.md` template via `wire.md` Step 3) and the standalone logo example in this file's Multi-nav section both use pattern (a). `procedures/scaffold-landing.md` and `agents/scaffold-landing.md` correctly prefer pattern (b) for landing-page images.

### When using a variable-axis next/font/google font (e.g., Fraunces with `axes: ["opsz"]`)

DO NOT include an explicit `weight` array — `next/font` rejects the combination at build time with:

> Module not found: Can't resolve 'next/font/google/target.css'
> Axes can only be defined for variable fonts when the weight property is nonexistent or set to `variable`.

The two configurations are mutually exclusive. Pick ONE form:

```tsx
// CORRECT — variable font, all weights available, axis-controlled
const fontDisplay = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  axes: ["opsz"],
  display: "swap",
});

// CORRECT — static font, narrow weight set, no axis
const fontDisplay = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["400", "500", "600"],
  display: "swap",
});

// WRONG — combining axes with explicit weight array fails the build
const fontDisplay = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["400", "500", "600"],   // remove this line
  axes: ["opsz"],                   // OR remove this line, but not both together
  display: "swap",
});
```

Applies to every `next/font/google` font that has variable axes (Fraunces opsz, Inter opsz, Recursive CASL/CRSV/MONO/slnt, Roboto Flex, etc.). When picking a variable font for a display role and you want every weight available, prefer the axis form (no `weight`). When you need a narrow weight set (smaller bundle) AND don't need axis control, use the weight form (no `axes`). Never combine them. Phase A `layout.tsx` is sealed against downstream edits — getting this wrong at scaffold-init time forces a shell-side bypass of the protection gate.

### When verifying shared secrets in API routes (cron triggers, webhooks)
Use `crypto.timingSafeEqual` instead of `===` or `!==`. String equality is vulnerable to timing side-channels — an attacker can infer secret characters by measuring response-time differences.

```typescript
import { timingSafeEqual } from "crypto";

function verifySecret(provided: string, expected: string): boolean {
  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}
```

### When a page fails the checkNoHorizontalOverflow smoke test on Mobile Chrome
Add `overflow-x-hidden` to the outermost wrapper `<div>` of the page component. Wide flex rows, animated elements, and shadcn Card grids are the most common cause of horizontal overflow on mobile viewports. This is the standard first fix; if overflow persists, audit for elements with fixed pixel widths or negative margins.

**If `overflow-x-hidden` on the outer wrapper does not fix the overflow:** check for `position: absolute` decorative elements (radial glows, blobs, geometric shapes — commonly 600–900px wide) inside child containers that lack `position: relative`. The absolute element's containing block falls through to the nearest positioned ancestor, which may be the `<body>` or viewport — NOT the wrapper you added `overflow-x-hidden` to. The element therefore escapes the clipping region and keeps causing horizontal scroll.

Fix: add `relative` to the nearest ancestor wrapper of the absolute-positioned decoration so it establishes the containing block. The scope stays local:

```tsx
// WRONG — glow escapes clipping because inner div is not positioned
<div className="overflow-x-hidden">
  <div>
    <div className="absolute w-[820px] h-[820px] bg-gradient-radial ..." />
    {children}
  </div>
</div>

// CORRECT — inner div is position:relative, glow is clipped by the ancestor
<div className="overflow-x-hidden">
  <div className="relative">
    <div className="absolute w-[820px] h-[820px] bg-gradient-radial ..." />
    {children}
  </div>
</div>
```

### Place rate limiting after auth and API key checks in AI routes
In API routes that call external AI services (Anthropic, OpenAI, etc.), run authentication and API key validation *before* `rateLimit()`. If rate limiting runs first:
1. An unconfigured deployment (missing API key) returns 429 instead of the correct 503, hiding the real problem
2. Unauthenticated requests consume rate-limit budget, returning 429 instead of 401 and masking the auth failure

Correct order: `verifyAuth()` → `checkApiKey()` → `rateLimit()` → business logic.

### When handling file uploads, sanitize filenames before storage key interpolation
User-supplied filenames can contain path traversal sequences (`../`, `..\`), null bytes, or special characters that break storage key construction. Always sanitize before interpolating into a storage path:

```typescript
function sanitizeFilename(name: string): string {
  return name
    .replace(/[/\\]/g, "-")       // path separators
    .replace(/\.\./g, "")          // traversal sequences
    .replace(/[^a-zA-Z0-9._-]/g, "-") // non-safe chars
    .replace(/-+/g, "-")           // collapse consecutive hyphens
    .slice(0, 255);                // filesystem limit
}

// Usage: prepend a UUID to prevent collisions and predictable paths
const key = `uploads/${crypto.randomUUID()}/${sanitizeFilename(file.name)}`;
```

### Zod v4: use top-level string-format validators (`z.uuid()`, `z.url()`, `z.email()`)
Zod v4 promoted all string-format validators to top-level factories: `z.string().uuid()` → `z.uuid()`, `z.string().url()` → `z.url()`, `z.string().email()` → `z.email()`, `z.string().cuid()` → `z.cuid()`, `z.string().nanoid()` → `z.nanoid()`. The old `.string().<format>()` forms are deprecated (console warning) but still functional. Use the top-level forms in all new code. If a project pins Zod v3 in `package-lock.json`, the top-level forms cause compile errors — revert to `z.string().<format>()`.

### When validating user-supplied URLs with Zod, always chain `.refine()` for scheme
`z.url()` only validates that a string is a well-formed URL; it does NOT restrict the URL scheme. A field validated with bare `z.url()` accepts `javascript:alert(1)` and `data:text/html,...` values. When such a URL is stored in the database and later rendered in an anchor `href` or `window.open()` call, it executes arbitrary JavaScript (XSS). Always chain a scheme refinement:

```typescript
const safeUrl = z.url().refine(
  (v) => {
    try { const u = new URL(v); return u.protocol === "http:" || u.protocol === "https:"; }
    catch { return false; }
  },
  { message: "URL must use http or https" }
);
```

Defense-in-depth: at render time, also gate anchor `href` with a helper `isSafeHref(url)` that re-checks scheme — covers legacy rows that were persisted before the validator landed. This applies to any user-supplied URL field (portfolio links, milestone links, webhook URLs, OAuth redirect URIs). The schema-level `.refine()` is the primary guard; render-time re-check is belt-and-suspenders.

### When server-side fetching user-supplied URLs, use redirect:'manual' and re-validate each hop

Any API route that calls `fetch(user_supplied_url)` with the default `redirect: 'follow'` is vulnerable to SSRF via redirect chain. An attacker submits a valid public URL that redirects to an internal/metadata endpoint (e.g., `http://169.254.169.254/` for AWS instance metadata). Even if the initial URL is validated with `isSafePublicHttpUrl`, the redirected destination is never re-checked — the `fetch` follows the `Location` header silently.

The existing entry "When validating user-supplied URLs with Zod, always chain `.refine()` for scheme" only covers the initial URL at input time. Use `redirect: 'manual'` and explicitly re-validate each hop:

```typescript
import { isSafePublicHttpUrl } from "@/lib/url-safety";

async function safeFetch(url: string, maxHops = 3): Promise<Response> {
  let current = url;
  for (let hop = 0; hop < maxHops; hop++) {
    const res = await fetch(current, { redirect: "manual" });
    if (res.status < 300 || res.status >= 400) return res;
    const next = res.headers.get("location") ?? "";
    if (!isSafePublicHttpUrl(next)) {
      throw new Error(`Redirect to unsafe destination: ${next}`);
    }
    current = next;
  }
  throw new Error("Too many redirects");
}
```

Applies to any API route or cron handler that fetches a user-supplied URL server-side (scraping endpoints, link-preview routes, webhook payload delivery, import-from-URL features). The up-front Zod `.refine(isSafePublicHttpUrl)` at the request body level is the first gate; `redirect: 'manual'` re-validation is the second gate that covers the redirect chain.

**Signed-integer CIDR mask bug** — when implementing `isSafePublicHttpUrl`, use unsigned right-shift `>>> 0` when computing bitwise CIDR masks on high-bit IPs (e.g., `169.254.169.254` = `0xA9FEA9FE`). JavaScript's `&` operator returns a signed 32-bit integer; `169.254.169.254 & 0xFFFF0000` produces a negative value and the range check silently passes:

```typescript
// WRONG — signed comparison silently passes for high-bit IPs
if ((ip & mask) === (network & mask)) return false;

// CORRECT — coerce to unsigned before comparison
if (((ip & mask) >>> 0) === ((network & mask) >>> 0)) return false;
```

### When a nested layout uses Suspense, provide an sr-only h1 during initial paint

When a page-level layout file (e.g., `src/app/<page>/layout.tsx`) wraps its children in a `<Suspense>` boundary, the loading UI is rendered during SSR / initial paint. If that loading UI contains no `<h1>`, axe-core fires `page-has-heading-one` (WCAG 1.3.1 Info and Relationships — every page must have at least one `<h1>`). This only affects nested layouts with Suspense — the root `layout.tsx` template typically does not have this problem because its loading UI (if any) is page-agnostic.

Add an `sr-only` heading to the loading UI that describes the page:

```tsx
// src/app/product-detail/layout.tsx
import { Suspense } from "react";

function LoadingFallback() {
  return (
    <main>
      <h1 className="sr-only">Product detail</h1>
      {/* skeleton / spinner */}
    </main>
  );
}

export default function ProductDetailLayout({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<LoadingFallback />}>{children}</Suspense>;
}
```

The `sr-only` class keeps the heading out of the visual layout while satisfying the WCAG landmark requirement. The `<main>` wrapper is also required when the nested layout owns the main landmark (i.e., the root layout's `<main>` was repaired to `<div>` to avoid the `landmark-no-duplicate-main` rule — see the paired Stack Knowledge entry "When a page component wraps its content in `<main>`").

Applies to every page-level `layout.tsx` that uses `<Suspense>` to gate dynamic children. If the layout is purely passive (just `{children}` with no boundary), this rule does not apply.

### When a login page redirects based on a `next` query parameter
Validate that `next` starts with `/` AND does NOT start with `//` before redirecting. A bare `startsWith("/")` check accepts `?next=//evil.com` because protocol-relative URLs begin with `/` — the browser then resolves `//evil.com` against the current scheme and redirects the authenticated user to an external origin. This is a classic open-redirect (OWASP A1-Broken-Access-Control / A10-Server-Side-Request-Forgery surface).

```typescript
// WRONG — accepts //evil.com
if (next && next.startsWith("/")) redirect(next);

// CORRECT — rejects protocol-relative URLs
const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
redirect(safeNext);
```

When `stack.auth: supabase`, the auto-scaffolded OAuth callback handler at `src/app/auth/callback/route.ts` already implements this validation (search for `rawNext.startsWith` in the rendered file or in `.claude/stacks/auth/supabase.md`). The principle above applies when:
- hand-rolling a login redirect for a non-supabase auth provider,
- adding a custom `/login` page that bypasses the supabase callback,
- adding any post-auth or post-action redirect that consumes a `next` / `redirect_to` / `return_to` query parameter.

Per OWASP guidance, when an allowlist of redirect destinations is feasible (e.g., a small set of known internal paths), prefer that over scheme validation. The `startsWith("/") && !startsWith("//")` form is the minimum guard; an allowlist is the strongest.

### Next.js 16+: scaffold `src/proxy.ts` + `proxy()` (filename↔export-name invariant) — supersedes #1120

**Today (Next.js 16+ — the template default after `npm install next`):** scaffold `src/proxy.ts` with `export async function proxy(request: NextRequest)`. Next.js 16+ enforces a **filename↔export-name invariant**: the file MUST be named `src/proxy.ts` AND the exported function MUST be named `proxy`. Renaming only one (file but not export, or vice versa) produces an empty `.next/server/middleware-manifest.json` after `npm run build` and silent non-registration of the proxy — auth-gated routes are reachable without redirect (a security regression). This is the symptom #1120 originally reported on 16.2.4 (closed with the conclusion "proxy.ts registration is incomplete on 16"); empirical verification on 16.2.6 shows the actual root cause was the filename↔export mismatch, not a registration gap.

**Empirical verification (run on the installed Next.js version to confirm registration works):**

```bash
cd /tmp && mkdir t && cd t && npm init -y && npm install next@16 react react-dom @types/react @types/react-dom typescript
mkdir -p src/app/protected
cat > src/proxy.ts <<'EOF'
import { NextResponse, type NextRequest } from "next/server";
export async function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/protected"))
    return NextResponse.redirect(new URL("/login", request.url));
  return NextResponse.next();
}
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"] };
EOF
# (minimal src/app/{layout,page,protected/page}.tsx omitted for brevity)
npm run build
# expect output line: "ƒ Proxy (Middleware)"
# expect file: .next/server/middleware.js (compiled proxy)
# expect file: .next/server/functions-config-manifest.json with "/_middleware" entry whose matchers[0].originalSource matches src/proxy.ts config.matcher
```

If the empirical test fails on a future Next.js patch release, file a new observation against this Stack Knowledge entry — do NOT revert to `src/middleware.ts` without verifying the rename pairing first.

**Scaffold rule:** always write `src/proxy.ts` + `export async function proxy(...)` on Next.js 16+. The `config` export is unchanged.

**Migration (already-bootstrapped projects on `src/middleware.ts`):** the legacy filename continues to work on Next.js 16+ but emits a deprecation warning at build time. Migrate via `git mv src/middleware.ts src/proxy.ts` AND rename the exported function from `middleware` to `proxy` (and any test imports referencing it by name) IN THE SAME COMMIT — the invariant rejects partial renames.

**Runtime consumers** (ux-journeyer, etc.) probe `src/proxy.ts` first (today's default) and fall back to `src/middleware.ts` for projects still on the legacy filename.

### When a `[seg]` page route does an auth lookup that may redirect, emit `force-dynamic` instead of `generateStaticParams`

When a page path contains a dynamic `[seg]` AND the server loader calls an auth API that can redirect unauthenticated requests (e.g., `requireRole()`, `getCurrentUser()`, `getSession()`, or any `@/lib/supabase-auth*` import), emit `export const dynamic = 'force-dynamic'` at the top of the page. Do NOT use `dynamicParams=false + generateStaticParams()` — the build prerender executes the loader for every slug returned by `generateStaticParams`, captures the redirect-to-login response, and bakes it into the `.next/` output as a static 404. Users visiting the URL hit the hardcoded 404 (not a live auth check).

Pages with `dynamic = 'force-dynamic'` re-execute on every request, so auth state is evaluated at request time and the redirect fires normally.

```tsx
// src/app/items/[id]/page.tsx — auth-gated [seg] route
import { requireRole } from '@/lib/supabase-auth-server';
import { fetchItem } from '@/lib/items';
import { ItemView } from '@/components/ItemView';

export const dynamic = 'force-dynamic';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await requireRole('member');  // redirects to /login if unauthenticated
  const item = await fetchItem(id, user);
  return <ItemView item={item} />;
}
```

This complements the `generateStaticParams()` + client-component split documented above (the "Exception: when a page needs both `generateStaticParams()` and client-side hooks" entry): use that split pattern only when the `[seg]` route is **public**. For auth-gated `[seg]` routes, `force-dynamic` is the only correct choice.

### When a `[seg]` page route is `anonymous_allowed` with `dynamic_segments` fixtures, short-circuit `DEMO_MODE`

When a behavior has `anonymous_allowed=true` AND declares `dynamic_segments[]` fixture slugs in experiment.yaml, the page loader must support a `DEMO_MODE` short-circuit. `sitemap.ts` enumerates the fixture URLs (via `derive_dynamic_public_pages()` in `.claude/scripts/lib/derive_pages.py`), so search engines crawl those URLs — but in `DEMO_MODE` the Supabase loader returns empty (no real data seeded), and without a fixture branch the page renders "not available" for sitemap-listed slugs. Indexability breaks.

Solution: export a `SAMPLE_<SEGMENT_NAME>` constant (array of fixture objects matching the page schema) at module top, then short-circuit at the top of the loader:

```tsx
// src/app/projects/[slug]/page.tsx — public [seg] route with DEMO_MODE fixtures
import { notFound } from 'next/navigation';
import { fetchProject } from '@/lib/projects';
import { ProjectView } from '@/components/ProjectView';

export const SAMPLE_SLUG = [
  { slug: 'my-first-project', title: 'My First Project', body: '...' },
  // one entry per fixture slug declared in experiment.yaml behaviors
];

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (process.env.DEMO_MODE === 'true') {
    const fixture = SAMPLE_SLUG.find(p => p.slug === slug);
    return fixture ? <ProjectView project={fixture} /> : notFound();
  }
  const project = await fetchProject(slug);
  return project ? <ProjectView project={project} /> : notFound();
}
```

The `SAMPLE_<SEGMENT_NAME>` naming convention (uppercase segment param name) makes the fixture discoverable for `sitemap.ts` cross-checks and behavior tests. Fixture slug values MUST match `dynamic_segments[].slug` entries verbatim — otherwise sitemap URLs and page fixtures diverge.

### When configuring tsconfig.json, always exclude `.runs/` AND `scripts/` to prevent build + LSP noise (#1450 gap 4)
TypeScript's `include: ["**/*.ts", "**/*.tsx", ...]` glob picks up two classes of files that are NOT part of the application build:

1. **`.runs/`** — scratch/gitignored workspace for skill execution artifacts (JSON traces, design-critic screenshot `.js` scripts, transient merge files). Produces false-positive LSP diagnostics on files that are not part of the build.
2. **`scripts/`** — bakeoff harnesses and ad-hoc tooling (e.g., `scripts/bakeoff/*.ts` per `.claude/stacks/images/fal.md:481-485`). These often have their own nested `package.json` with dependencies that the root `node_modules` does NOT contain. Without exclusion, `tsc --noEmit` fails with `Cannot find module '@fal-ai/client'` (or similar) during `npm run build`, blocking state progression.

Both must be excluded in the bootstrap `tsconfig.json` template:

```json
{
  "compilerOptions": { ... },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules", ".next", ".runs", "scripts"]
}
```

Without `.runs` exclusion: spurious LSP errors. Without `scripts` exclusion: bootstrap-time build failure when any bakeoff or image-pipeline scaffold runs under `scripts/`. Cross-reference: `.claude/stacks/images/fal.md` already documents the bakeoff sub-case; the root tsconfig must default to excluding the whole `scripts/` tree so individual stack scaffolds don't each need to teach a tsconfig amendment.

### React 19: use `React.SyntheticEvent<HTMLFormElement>` for onSubmit handler types
`React.FormEvent<HTMLFormElement>` is deprecated in React 19 types — it emits a TypeScript deprecation warning during `npm run build`. The correct replacement is `React.SyntheticEvent<HTMLFormElement>`, which covers the same surface and does not trigger the warning. Write the handler signature as `async function onSubmit(e: React.SyntheticEvent<HTMLFormElement>) { ... }` (never `React.FormEvent<...>`).

This applies to every form handler in auth pages (signup, login, password reset), settings forms, and any custom form UI.

### When accessibility scanner reports duplicate `<nav>` landmark regions or duplicate brand announcement
See the "Multi-nav layouts" entry under `## Accessibility` above. Two `<nav>` elements on the same page require unique `aria-label` values; a logo image adjacent to visible brand text requires `alt=""` + `aria-hidden` so the brand name is not announced twice.

### When keyboard accessibility scan reports missing skip-navigation link (WCAG 2.4.1)
See the "Root layout — skip-nav link" entry under `## Accessibility` above. The layout must include a visually-hidden `<a href="#main-content">` anchor before the first visible navigation block, and `<main>` must carry BOTH `id="main-content"` AND `tabIndex={-1}`. All three are required — the anchor alone, or anchor+id without tabIndex, BOTH fail. Without tabIndex={-1}, the `<main>` wrapper is not programmatically focusable; activating the skip-link anchor does not move focus and Tab cycles back to the link (issue #1380).

### `src/app/not-found.tsx` must export a `metadata` object
The 404 page has no `<title>` without an explicit `metadata` export, which fails a11y / SEO audits. Add a static `metadata` export at the top of `src/app/not-found.tsx`:

```tsx
// src/app/not-found.tsx
import Link from "next/link";

export const metadata = { title: "Page Not Found" };

export default function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
      <h1 className="text-2xl font-bold">Page not found</h1>
      <p className="text-muted-foreground">The page you&apos;re looking for doesn&apos;t exist.</p>
      <Link href="/" className="underline">Back to home</Link>
    </div>
  );
}
```

`generateMetadata()` is NOT needed — `not-found.tsx` is a static route so the object export is sufficient.

### When a let variable is always overwritten in the try block (no-useless-assignment)
Declare the variable with a type annotation and no initial value: `let x: string;` instead of `let x = "placeholder";`. The `@typescript-eslint/no-useless-assignment` lint rule (from `tseslint.configs.recommended`) fires when the initial value is never read because every branch (try + catch) reassigns the variable before use. An initial value suggests a fallback that isn't actually used.

### When accessibility scanner reports all pages missing `<main>` landmark
Wrap `{children}` in a `<main>` element in `src/app/layout.tsx`. The root layout template emits `{children}` directly inside `<body>`, which causes every page to fail WCAG landmark checks. A `<main>` in the root layout applies the fix to all pages simultaneously.

### When npm install fails with eslint-plugin-react-hooks peer dependency error
`eslint-plugin-react-hooks` does not support eslint v10+. When `npm install` resolves the latest eslint major version and the peer dependency check fails, re-run with a pinned version: `npm install -D eslint@9`. This is a temporary compatibility workaround until `eslint-plugin-react-hooks` supports eslint v10. Other framework stacks (Hono, Commander) do not use `eslint-plugin-react-hooks` and are unaffected.

### When a custom hook returns a useRef and react-hooks/refs lint fires
A custom hook that returns a `useRef` object triggers the `react-hooks/refs` ESLint rule when consumers access properties on the returned ref during render (e.g., `hook().current`). The error is "Cannot access refs during render." Convert `useRef` to a `useState` + callback ref pattern, or restructure so the hook returns derived values instead of the raw ref object. This commonly occurs with scroll-tracking or intersection-observer hooks.

### When `react-hooks/purity` flags `Date.now()` or `Math.random()` in a Server Component helper
The `react-hooks/purity` rule fires on helper functions that use impure expressions (`Date.now()`, `Math.random()`, etc.) when those helpers are defined inside a component-scope file. Server Components render server-side once and are serialized to HTML — they are NOT bound by React's purity rules for hooks. In a Server Component file, calling `Date.now()` in a helper is valid and a false positive. Suppress with an inline comment that both disables the rule and documents the reason:

```tsx
// eslint-disable-next-line react-hooks/purity -- Server Component: purity rule does not apply
const now = Date.now();
```

**Only suppress in files that do NOT contain the `"use client"` directive.** In Client Components the rule IS applicable — `Date.now()` inside a component-scope helper can cause hydration mismatches and should be wrapped in `useEffect` or moved out of render, not suppressed.

### When a page component wraps its content in `<main>` causing `landmark-no-duplicate-main`
When `src/app/layout.tsx` already wraps `{children}` in a `<main>` element (see the paired "missing `<main>` landmark" entry above), individual page components MUST NOT add their own `<main>`. Two `<main>` elements on the same page fail the axe-core `landmark-no-duplicate-main` check (WCAG 4.1.2). Scaffold-generated `page.tsx` templates should use `<div>` as the outermost wrapper — only `layout.tsx` owns the `<main>` landmark.

This pairs with the missing-`<main>` entry to form the full rule: **exactly one `<main>` per rendered page, owned by `layout.tsx`, never duplicated by a page component.**

### When two `<section>` elements share the same `aria-labelledby` value (landmark-unique)
A `<section>` element only registers as a landmark when it carries `aria-label` or `aria-labelledby`. When two labelled sections compute to the same accessible name (e.g., a hero section and a final-CTA section both pointing `aria-labelledby` at the variant headline element), axe-core fires `landmark-unique` because screen-reader users navigating by landmark cannot distinguish them — both announce as "region: <variant headline>".

Triage rule before applying a fix: **Would a screen-reader user navigating by landmark want to jump directly to this section?** If the section provides distinct content navigable as a landmark (e.g., a hero introducing the page vs. a final CTA closing it), give each a purpose-naming `aria-label` (`aria-label="Hero"`, `aria-label="Final call to action"`) — do not share the headline label between them. If the section is incidental — semantic `<section>` used purely for visual grouping with no landmark value beyond the surrounding `<main>` and `<h1>` — demote it to `<div>`.

```tsx
// WRONG — two sections share the headline label, both announce as the same region
<section aria-labelledby="variant-headline">…</section>
<section aria-labelledby="variant-headline">…</section>

// CORRECT (path A) — each section gets a unique purpose-naming label
<section aria-label="Hero">…</section>
<section aria-label="Final call to action">…</section>

// CORRECT (path B) — the second block was incidental; demote to <div>
<section aria-labelledby="variant-headline">…</section>
<div>…</div>
```

### When using `<aside>` as a visual layout column inside `<main>` (landmark-complementary-is-top-level)
`<aside>` is reserved for content that is genuinely complementary to but separable from the main flow — related-links panels, pull-quote blocks, glossary side-panels. Using `<aside>` as a visual layout column (a sidebar rendered via CSS grid/flex, a marginalia column for `RitualStep`-style annotations) trips axe-core `landmark-complementary-is-top-level`.

Rule semantics: axe-core fires this rule when an `<aside>` is **nested** inside another landmark (e.g., inside `<main>` or another `<section>`). `aria-label` does NOT suppress the rule — only top-level placement (sibling of `<main>`, not child) or demotion to `<div>` resolves it. For layout columns inside `<main>`, demotion is the correct fix.

```tsx
// WRONG — <aside> nested inside <main> for layout purposes; axe fires regardless of aria-label
<main>
  <aside aria-label="Marginalia">{annotations}</aside>
  <div>{primaryContent}</div>
</main>

// CORRECT — <div> for layout columns; <aside> reserved for genuinely complementary content
<main>
  <div className="marginalia">{annotations}</div>
  <div>{primaryContent}</div>
</main>
```

### When accessibility scanner reports heading-order violation (general rule)
Headings must descend sequentially: `<h1>` → `<h2>` → `<h3>`. Skipping a level (e.g., `<h1>` directly to `<h3>` with no intermediate `<h2>`) fails WCAG 1.3.1 "Info and Relationships" — screen readers use heading hierarchy for document outline and skipped levels confuse navigation. The triggering pattern in scaffolded pages is usually a page title at `<h1>` with each section header jumping to `<h3>` (no `<h2>` for major sections), or reusing a component that internally renders `<h3>` on a page that already uses `<h2>`.

Visual size is controlled by CSS — use Tailwind classes to size headings independently of their semantic level, so the rank stays correct without sacrificing visual hierarchy:

```tsx
{/* h3 that looks like a large heading — semantic rank stays h3, visual size is large */}
<h3 className="text-2xl font-semibold">Section Title</h3>

{/* Or h2 styled as smaller — semantic rank stays h2 */}
<h2 className="text-lg">Subsection Title</h2>
```

Use the browser Accessibility Tree panel (Chrome DevTools → Elements → Accessibility) or `axe-core` to audit heading order before committing. The card-title special case is a common subset — see the next entry.

### When card or list-item titles skip a heading level (heading-order)
axe-core `heading-order` fires when an outline rank jumps by more than 1 (e.g., `<h1>` followed by `<h3>` with no `<h2>` between, or `<h2>` followed by `<h4>`). A common trigger: card / list-item title components default to `<h3>` regardless of page heading context, so a page with a single `<h1>` and a row of cards renders `<h1>` → `<h3>` (skipping `<h2>`).

Rule of thumb: use the minimum heading rank that maintains an unbroken hierarchy. **`<h2>`** for top-level cards on a page with a single `<h1>`. **`<h3>`** for sub-items inside an `<h2>` section. Verify the rendered rank at the usage site — card and list-item title components do not adapt to context automatically. When the title component does not let you choose the rank at the call site (e.g., shadcn `CardTitle` renders a fixed element from the scaffolded `src/components/ui/card.tsx`), see the paired entry in your UI stack file (`.claude/stacks/ui/<value>.md`) for editing the scaffolded component.

```tsx
import { Card, CardTitle } from "@/components/ui/card";

// WRONG — card titles render <h3> on a page with single <h1>; rank jumps 1→3
<h1>Portfolio</h1>
{items.map(item => (
  <Card key={item.id}>
    <CardTitle>{item.name}</CardTitle>  {/* renders <h3> */}
  </Card>
))}

// CORRECT — promote card titles to <h2> to maintain h1→h2 hierarchy
<h1>Portfolio</h1>
{items.map(item => (
  <article key={item.id}>
    <h2>{item.name}</h2>
    {item.body}
  </article>
))}
```

### When a textarea or input is flagged as missing an accessible label
Every `<textarea>`, `<input>`, and `<select>` must be associated with a label via one of:

1. `<label htmlFor="id">` + matching `id` on the field (preferred — visible label)
2. `aria-label="..."` directly on the element (use when no visible label exists)
3. `aria-labelledby="id"` referencing an existing visible heading or text node

```tsx
{/* Preferred: visible label */}
<label htmlFor="notes">Notes</label>
<textarea id="notes" />

{/* When label is not visible */}
<textarea aria-label="Search query" />
```

A `placeholder` is **not** a label substitute — placeholders disappear when the user types and are not announced on focus by all screen readers. Scaffolded result/output pages commonly render a textarea with only a placeholder; axe-core flags these as "Form element does not have an associated label" (WCAG 1.3.1, 4.1.2).

### When an interactive element contains only an icon (no visible text)
Icon-only buttons (hamburger menu, show/hide password toggle, modal close `×`, icon-only action buttons in data tables) have no accessible name — screen readers announce "button" with no context, failing WCAG 4.1.2. Every icon-only interactive must carry an `aria-label` (or `aria-labelledby` referencing visible text), and the icon itself should carry `aria-hidden="true"` so it is not announced in addition to the label.

```tsx
import { Menu, ToggleLeft } from "lucide-react";

{/* hamburger */}
<button aria-label="Open navigation menu" onClick={toggleMenu}>
  <Menu aria-hidden="true" />
</button>

{/* on/off toggle — use role="switch" + aria-checked for stateful toggles */}
<button
  role="switch"
  aria-checked={enabled}
  aria-label="Enable notifications"
  onClick={() => setEnabled(!enabled)}
>
  <ToggleLeft aria-hidden="true" />
</button>
```

The supabase auth-stack `nav-bar.tsx` template already uses `aria-label="Open menu"` for the hamburger SheetTrigger — this entry documents the underlying pattern so downstream icon buttons (settings toggles, table actions, modal close) inherit the same convention.

### When auth proxy redirects to /login during demo mode
When a Next.js project uses `src/proxy.ts` for auth-based redirects AND supports demo mode, an unauthenticated request to a protected route still redirects to `/login` even with `DEMO_MODE=true` set — blocking all demo traffic. The demo client returns a fake session object, but the proxy runs **server-side, before any client SDK is instantiated**, so the demo session is invisible to the proxy function. The only working short-circuit is an `process.env.DEMO_MODE === "true"` check at the top of the proxy function.

```ts
// src/proxy.ts
import { NextRequest, NextResponse } from "next/server";

export async function proxy(request: NextRequest) {
  // Demo mode (server env): skip auth redirect — no real session exists.
  // DEMO_MODE is the canonical server-side flag; NEXT_PUBLIC_DEMO_MODE is
  // the client-side counterpart and is not visible to the proxy (which
  // runs in the Edge / server runtime).
  if (process.env.DEMO_MODE === "true") return NextResponse.next();
  // ... existing auth logic
}
```

The shipped `auth/supabase.md` middleware template currently checks `NEXT_PUBLIC_DEMO_MODE` only — projects that need server-side `DEMO_MODE` honor (e.g., the playwright config flips `DEMO_MODE=true` when Supabase is unreachable) must add the explicit guard above. Without it, demo runs see every protected-route visit redirected to `/login`, which itself may crash if the auth client tries to read missing env vars before the demo guard runs.

### When openGraph metadata is missing images array, og:image is absent
When the `openGraph` config object in `layout.tsx` is written without an `images` property, the `og:image` meta tag is entirely absent from the rendered HTML. Social sharing previews and link unfurls show no image. Always include the `images` array in the openGraph config:

```typescript
openGraph: {
  title: "...",
  description: "...",
  images: [{ url: "/images/og-photo.png", width: 1200, height: 640 }],
},
```

### When API route accepts total + line-items breakdown, validate with .refine()
API routes that accept both a `total` field (e.g., `total_cents`) and a breakdown array (e.g., `line_items`) must validate that the sum matches. Without cross-field validation, a client can pass an arbitrary total that does not match the line items. Use Zod's `.refine()` for cross-field validation:

```typescript
const schema = z.object({
  total_cents: z.number().int().positive(),
  line_items: z.array(z.object({ amount_cents: z.number().int() })),
}).refine(
  (data) => data.total_cents === data.line_items.reduce((sum, i) => sum + i.amount_cents, 0),
  { message: "total_cents must equal sum of line_items" }
);
```

### When API routes performing expensive operations lack rate limiting
CLAUDE.md Rule 6 specifies rate limiting for auth and payment routes, but any API route performing expensive operations (AI calls, email sends, database writes from anonymous users, quote generation) is equally vulnerable to abuse. Add rate limiting to all write routes and routes that call external services, not just auth and payment.

### When a project emits schema.org `Offer` objects in JSON-LD structured data
Derive `price` values from the same constant that drives the visible pricing UI (`PLAN_PRICES` when `stack.payment: stripe` is present — see `.claude/stacks/payment/stripe.md`; otherwise whichever pricing source the project uses). **Never** hard-code price strings inside the LD+JSON block. When prices change, stale JSON-LD is invisible to visual QA but crawlers and LLM agents see the contradiction and may surface wrong prices in search results or AI summaries.

For enterprise / custom tiers that have no fixed price, use a `PriceSpecification` object with a `description` field instead of a numeric `price`:

```json
{
  "@type": "Offer",
  "name": "Enterprise",
  "priceCurrency": "USD",
  "priceSpecification": {
    "@type": "PriceSpecification",
    "description": "Custom pricing — contact sales"
  }
}
```

When a unit test / build-time assertion is easy to add, compare `JSON.parse(ldJson).offers[*].price` against `PLAN_PRICES[tier].priceUsd` to catch drift during future refactors. Skip the assertion for single-page MVPs where the Offer list is inline — the static-source derivation is the primary guard.

### When rendering non-text Unicode glyphs (∞, ×, ©, →, etc.) as visible UI values
Screen readers announce the Unicode name verbatim — NVDA/JAWS/VoiceOver say "mathematical infinity sign", "multiplication sign", "right-pointing arrow" — which fails WCAG 1.1.1 non-text content when the glyph carries semantic meaning (e.g., `∞` meaning "unlimited"). Wrap the glyph in `aria-hidden="true"` and add a `<span className="sr-only">` sibling with a descriptive word:

```tsx
<span aria-hidden="true">∞</span>
<span className="sr-only">unlimited</span>
```

The `sr-only` utility (Tailwind v4 ships this by default) clips the text visually but keeps it in the accessibility tree. Do NOT substitute `visibility: hidden` or `display: none` — those remove the text from both visual AND accessibility trees, breaking the screen-reader announcement.

Apply to quota displays (`∞` → "unlimited"), close buttons (`×` → "close dialog"), copyright footers (`©` → "copyright"), and arrow indicators (`→` → "leads to"). For purely decorative arrows between cards where no meaning is carried, `aria-hidden="true"` alone without the sr-only sibling is sufficient.

### Suppress the global NavBar on landing/marketing and auth routes
When the root layout mounts a global `<NavBar />` AND a landing/variant page has its own in-page navigation (e.g., `VariantLanding`'s `StickyNav`), both render simultaneously above the fold — producing doubled brand marks, colliding CTAs, and stacked navs. The fix is route-conditional suppression in `src/components/nav-bar.tsx`:

```tsx
"use client";
import { usePathname } from "next/navigation";

const AUTH_ROUTES = ["/login", "/signup", "/auth/"];
const MARKETING_ROUTE_PREFIXES = ["/v/"];  // variant routes

export function NavBar() {
  const pathname = usePathname();
  const isAuth = AUTH_ROUTES.some((r) => pathname === r || pathname.startsWith(r));
  const isMarketing = pathname === "/" || MARKETING_ROUTE_PREFIXES.some((p) => pathname.startsWith(p));
  if (isAuth || isMarketing) return null;
  // ... rest of NavBar
}
```

The returned `null` is evaluated on the client after hydration, so the server-rendered output may briefly include the global nav before React decides to hide it. Acceptable tradeoff for the simpler implementation; if flash-of-unstyled-content is unacceptable, move the gate to the root layout's server component using `headers()` to read the path. The alternative `body:has(#sentinel-id) .global-nav { display: none }` CSS pattern also works but is fragile — it depends on a sentinel element being present and is less obvious to future maintainers. Without this gate, every marketing/auth page ships with duplicate navigation bars (fix #1072).

### When emitting opengraph-image.tsx (next/og ImageResponse), use only Satori-supported CSS (#1450 gap 5)
Satori — the render engine inside Next.js's `next/og ImageResponse` — supports a small subset of CSS. The full restriction list is in Satori's docs; the most common mistake is `display`:

| display value | Satori support |
|---|---|
| `flex` | ✅ supported (canonical layout) |
| `block` | ✅ supported |
| `contents` | ✅ supported |
| `none` | ✅ supported |
| `-webkit-box` | ✅ supported |
| `inline-block`, `grid`, `table`, `inline-flex`, `inline` | ❌ rejected at render time |

When scaffolding `src/app/opengraph-image.tsx`, default the root element to `display: 'flex'` and use `flexDirection: 'column'` / `'row'` for layout. Inline content (text + icon side-by-side) uses a flex child with `gap` instead of `display: 'inline-block'`. The Satori error message at render time is generic ("Failed to fetch / load OG image"), so an unsupported `display` value can be hard to diagnose post-deploy — prefer the flex default at scaffold time.

### When iterating list items inside JSX, use .filter().map((_, idx) => ...) not let counter mutation (#1450 gap 7)
React 19's stricter `eslint-plugin-react-hooks` immutability rule flags any `let counter += 1` inside a `.map()` callback as a lint error (`react-hooks/...` purity violation). The OLD pattern that triggers the rule:

```tsx
// ❌ React 19 lint error — mutation inside .map callback
let counter = 0;
return turns.map((turn) => {
  if (!turn.content) return null;
  const idx = counter++;
  return <li key={idx}>{turn.content}</li>;
});
```

The canonical replacement is `.filter().map((_, idx) => ...)` so the index is derived from the filtered array's positional callback parameter, not a mutated outer variable:

```tsx
// ✅ functional purity — idx from .map's second arg
return turns
  .filter((turn) => Boolean(turn.content))
  .map((turn, idx) => <li key={idx}>{turn.content}</li>);
```

Applies broadly: any scaffold that needs a "skipped some, index the rest" iteration must use `.filter().map((_, idx) => ...)`. Examples: spec-builder turn rendering, FAQ accordion item indexing, table-row enumeration with conditional skips.

### When removing default focus outlines, always pair with focus-visible:ring-* (WCAG 2.4.7) (#1450 gap 8)
Inline `outline: 'none'` or Tailwind `focus:outline-none` WITHOUT a focus-visible fallback is a serious axe-core violation: WCAG 2.4.7 "Focus Visible" requires keyboard focus to be perceivable on every interactive element. The error class fires on FAQ accordions, custom buttons, dialog triggers, and any element where the designer wanted to "hide the default browser focus ring" without thinking about keyboard-only users.

The canonical Tailwind idiom:

```tsx
// ❌ axe-core serious violation
<button className="focus:outline-none">Open FAQ</button>

// ✅ WCAG 2.4.7 compliant — outline removed but focus-visible ring restored
<button className="focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-brand-primary">
  Open FAQ
</button>
```

`focus-visible` shows the ring only for keyboard navigation (Tab key), not for mouse clicks — so the visual design stays clean for pointer users while remaining accessible for keyboard users. Apply this pattern in every scaffold that emits a focusable element with custom styling: FAQ items, Card primitives, custom selects, accordion triggers.

```yaml
id: nextjs-open-redirect-next-param
maturity: raw
anti_pattern: false
composite_identity:
  root_cause_class: open redirect via unvalidated next query parameter
  divergence_pattern: stack-file-security-guidance-gap
  stack_scope: framework/nextjs
composite_identity_hash: 593435a0ab4a
symptom_keywords: [open-redirect, next-param, login, redirect, OWASP-A1, protocol-relative, startsWith]
fix_template: |
  Validate next.startsWith("/") AND !next.startsWith("//") before consuming
  the next query parameter in a redirect. A bare startsWith("/") accepts
  ?next=//evil.com because protocol-relative URLs begin with /. The browser
  resolves //evil.com against the current scheme and redirects to an external
  origin. Pattern:
    const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
    redirect(safeNext);
  When stack.auth: supabase, the auto-scaffolded OAuth callback at
  src/app/auth/callback/route.ts already implements this validation (see
  auth/supabase.md callback handler — search for rawNext.startsWith). The
  guard above applies when hand-rolling a login redirect for a non-supabase
  auth provider or adding any post-action redirect that consumes a next /
  redirect_to / return_to query parameter. When an allowlist of redirect
  destinations is feasible, prefer the allowlist over scheme validation.
prevention_mechanism: Stack Knowledge entry above documents the guard with code example and cross-reference to auth/supabase.md canonical implementation. Recurrence guard is documentation-quality.
confidence_score: 0.7
occurrence_count: 1
linked_issues: [1228]
first_seen: 2026-05-01
last_seen: 2026-05-01
graduated_to: null
```

## PR Instructions
- No additional framework setup needed after merging — `npm install && npm run dev` is sufficient
