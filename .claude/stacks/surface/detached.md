---
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

# Detached Surface

The acquisition surface is deployed independently to Vercel free tier —
separate from the product. Used when the product has no server hosting
(e.g., CLI tools).

## Output

`site/index.html` — a self-contained HTML page. No external CSS/JS files
needed beyond Google Fonts and the analytics provider CDN (see analytics stack file).

Include an inline SVG favicon via `<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,...">` -- a monogram of the product name initial in the primary color.

## Design

The surface is the first thing a potential user sees. It must be
**world-class** — visually equivalent to a $50K agency landing page.

`frontend-design` has full creative authority AND full creative
responsibility. The expectation is not "use nice colors." The expectation
is: custom color palette, considered typography (Google Fonts via `<link>`),
meaningful animations (CSS keyframes, scroll-triggered reveals, staggered
transitions), textured depth (subtle gradients, noise overlays, backdrop
effects), responsive layout, dark/light mode (`prefers-color-scheme`).

Not a template. Not adequate. Exceptional — a unique page that makes the
founder proud to share the URL.

> _Mirrors `.claude/patterns/design.md` Quality bar — keep in sync._

**Content inventory from experiment.yaml** (raw material — page architecture is a
creative decision by `frontend-design`, not a fixed mapping):
- `name` — product identity
- `description` — value proposition and what the product does
- `behaviors` — capabilities to showcase
- `target_user` — who the product is for
- CTA — `npm install -g <name>` command with copy button (pure CSS/minimal JS)

Can include CSS-based terminal animation showing CLI usage.

## Analytics

Same inline analytics snippet approach as co-located (see `co-located.md` for
the canonical snippet template — it uses `<%POSTHOG_KEY%>` substitution and a
runtime misconfiguration check that matches the analytics stack file's
`## Production Observability` Layer 2 contract). Inline `<script>` fires
`visit_landing` on page load with: `referrer`, `utm_source`, `utm_medium`,
`utm_campaign`, `utm_content`, `click_id`, plus global properties
(`project_name`, `project_owner`).

In `site/index.html` (cli detached surface), the substituted snippet looks
the same as in service `src/app/route.ts` — only the surrounding HTML
changes. The same console.error fires when the placeholder is still in
place at deploy time, so CLI projects also get post-deploy visibility for
analytics misconfiguration.

## Deployment

During `/deploy`, run `vercel site/ --prod` to deploy the static site to
Vercel free tier. Bind custom domain (`<name>.<domain>` from `deploy.domain`
if present). Surface URL goes into `deploy-manifest.json` as `surface_url`.

## Note

The CLI archetype excludes `hosting` in its `excluded_stacks`. This does not
apply to the surface — `hosting` exclusion means the PRODUCT has no server
hosting. The surface's Vercel deployment is managed by the surface stack,
not the hosting stack.
