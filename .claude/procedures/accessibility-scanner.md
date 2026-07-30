# Accessibility Scanner Procedure

> Executed by the accessibility-scanner agent. See `.claude/agents/accessibility-scanner.md` for identity and output contract.

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Performance + a11y agents".
>
> [perf-a11y] web-app: performance-reporter, accessibility-scanner | service: skip | cli: skip
>
> State-specific logic below takes precedence.

Read `experiment/experiment.yaml` to determine the archetype (`type` field, default: `web-app`).

If archetype is **not** `web-app`, skip all checks and report:

> N/A — not a web-app. Accessibility scanning only applies to web-app archetype.

## Method Selection

Check prerequisites in order:

1. Run `npx playwright --version`. If it fails → use **Static Fallback** (Section B).
2. Run `node -e "require('@axe-core/playwright')"`. If it fails → use **Static Fallback** (Section B).
3. Both available → use **Runtime Analysis** (Section A).

## Section A: Runtime Analysis (axe-core + Playwright)

### A1. Start Server

```bash
DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run start -- -p 3096 &
```

Poll `http://localhost:3096` until it responds (max 15 seconds, then abort).

> REF: see `.claude/patterns/demo-server-startup.md`.

### R1. axe-core Violations

Enumerate pages to scan via the canonical SET inventory (every surface a user can reach — not just the funnel):

```bash
python3 .claude/scripts/lib/derive_pages.py scope < experiment/experiment.yaml
```

This yields `derive_scope_pages(experiment)` = union of `golden_path[*].page`, `behaviors[*].pages`, and auth-derived pages, with `landing` excluded (scaffold-landing owns it). Walk the returned pages in this deterministic order: first every page that appears in `golden_path` (in funnel sequence), then behavior-only pages sorted alphabetically. This preserves funnel-first trace readability while ensuring accessibility coverage on admin/dashboard/portfolio surfaces named in `behaviors[*].pages`.

For each page, write an inline Node.js script using Playwright +
`@axe-core/playwright`. Before running axe on a page, call the render-review
detection procedure from `.claude/patterns/render-review-detection.md` and
skip the axe scan when it returns `source-only` or `unknown` — a scan of a
`/login` redirect is not a scan of the requested page.

```javascript
const { chromium } = require('playwright');
const { AxeBuilder } = require('@axe-core/playwright');
// Inline the detection helper from render-review-detection.md Sections 1-5
// as `renderReviewDetect({ browser, requested_route, base_url, is_first_page })`.

const BASE_URL = 'http://localhost:3096';
const browser = await chromium.launch({ headless: true });

const perPageReviews = [];
const violations = [];
let firstAuthGatedSeen = false;

for (const { page: pageName, route } of goldenPathPages) {
  // Treat the first NON-public route as the diagnostic page
  const isAuthGated = !PUBLIC_PATHS.has(route);
  const is_first_page = isAuthGated && !firstAuthGatedSeen;
  if (is_first_page) firstAuthGatedSeen = true;

  const result = await renderReviewDetect({
    browser,
    requested_route: route,
    base_url: BASE_URL,
    is_first_page,
  });

  perPageReviews.push({
    page: pageName,
    review_method: result.review_method,
    review_evidence: result.review_evidence,
  });

  if (result.review_method === 'source-only' || result.review_method === 'unknown') {
    // SKIP scan — this page was never rendered; do NOT increment pages_scanned
    await result.context.close();
    continue;
  }

  const axeResults = await new AxeBuilder({ page: result.page }).analyze();
  for (const v of axeResults.violations) {
    for (const node of v.nodes) {
      violations.push({
        rule: v.id, impact: v.impact, page: route,
        element: node.html, wcag: (v.tags.find(t => /^wcag\d/.test(t)) || '').toUpperCase(),
        detail: v.description,
      });
    }
  }
  await result.context.close();
}
```

Populate the trace's `per_page_reviews` array from `perPageReviews`.
`pages_scanned` = count of entries where `review_method` ∈ {`rendered-authed`, `rendered-demo`}.

axe-core auto-detects 50+ WCAG 2.1 AA rules including: alt text, form labels, color contrast, ARIA attributes, heading hierarchy, lang attribute, and more.

### R2. Tab Order Test

For each page in the same canonical SET from R1 (derived via `derive_scope_pages()`), write a Playwright script that:

1. Focus the page body
2. Press Tab up to 50 times, recording `document.activeElement` tag, text, and bounding box after each press
3. Flag issues:
   - **Focus jumps out of visual order** — element position regresses significantly (bounding box Y decreases by >200px)
   - **Focus trapped** — same element appears 3 consecutive times
   - **Focus skips visible interactive element** — a button/link/input visible in the viewport was never focused

**Skip pages with `review_method ∈ {"source-only", "unknown"}`** from R1 —
tabbing through a `/login` redirect produces a tab report for the wrong
page. Reuse `perPageReviews` from R1 to decide which pages to tab-test.

### Cleanup

```bash
kill %1 2>/dev/null || true
```

## Section B: Static Fallback (grep-based)

> Used when Playwright or @axe-core/playwright is not installed.

Scan all `page.tsx`, `layout.tsx`, and component files under `src/`.

### A1. Images Without Alt Text (WCAG 1.1.1)

Search for `<img` and Next.js `<Image` components missing the `alt` attribute, or with `alt=""` on non-decorative images. Decorative images (`alt=""`) are acceptable only if the image is purely presentational.

**Severity:** High

### A2. Buttons Without Accessible Labels (WCAG 4.1.2)

Search for `<button` and `<Button` elements that have:
- No text content AND no `aria-label` / `aria-labelledby`
- Only an icon child with no screen reader text

Icon-only buttons must have `aria-label` or visually hidden text.

**Severity:** High

### A3. Form Inputs Without Labels (WCAG 1.3.1)

Search for `<input`, `<select`, `<textarea` elements that lack:
- An associated `<label>` (via `htmlFor` / wrapping)
- An `aria-label` or `aria-labelledby` attribute
- A `placeholder` alone does NOT count as a label

**Severity:** High

### A4. Color Contrast Heuristic (WCAG 1.4.3)

Search for inline styles and Tailwind classes that suggest low contrast:
- `text-gray-300` or lighter on white/light backgrounds
- `text-white` on light background classes (e.g., `bg-gray-100`)
- Inline `color` styles with light values (#ccc, #ddd, etc.) without dark backgrounds

This is a heuristic — flag as Medium since runtime rendering may differ.

**Severity:** Medium

### A5. Missing Heading Hierarchy (WCAG 1.3.1)

Within each page file, check heading levels. Flag if:
- A page jumps from `<h1>` to `<h3>` (skipping `<h2>`)
- A page jumps from `<h2>` to `<h4>` (skipping `<h3>`)
- Multiple `<h1>` elements exist in a single page

**Severity:** Medium

### A6. Missing Lang Attribute (WCAG 3.1.1)

Check the root `layout.tsx` file for `<html lang="...">`. The `lang` attribute must be present and non-empty. Missing `lang` is a violation.

**Severity:** High

### A7. Conditionally-Mounted Live Regions in Form-State Components (WCAG 4.1.3)

Scan files under `src/app/` and `src/components/` whose enclosing component ALSO contains form-state-machine markers (one or more of: `status === "success"`, `setStatus(`, or a type alias of the shape `Status = "idle" | "submitting" | "success" | "error"`). Within those files only, flag any `role="alert"` or `aria-live="<polite|assertive>"` element whose render is gated by a conditional or short-circuit expression:

- `{condition ? <p role="alert">...</p> : null}` (ternary gating)
- `{condition && <p aria-live="...">...</p>}` (&& gating)
- `<... role="alert">` placed inside an `if (status === "...") return (...)` branch with no equivalent fallback container in the other branch

**Scope filter rationale**: co-occurrence with form-state-machine markers narrows the heuristic to components that match the Intent Capture Contract surface (see `.claude/procedures/scaffold-externals.md` § Intent Capture Contract Rule 1). This reduces false positives from legitimate conditional flash banners, notification-list items, and server-error banners that exist outside form-to-success flows.

Fix hint in scanner output: "Mount the container unconditionally; toggle text content only. Example: `<p role='alert' aria-live='assertive' className='min-h-[1em] ...'>{status === 'error' ? msg : ''}</p>`."

**Severity:** Medium (heuristic; narrow scope filter + multiline regex means some false positives are inevitable. Runtime axe-core R1 is the authoritative confirmation when an error state is triggered during the test run. Flags but does not block `/verify`.)
