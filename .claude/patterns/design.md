# Visual Design System

## Quality Invariants

Non-negotiable rules that prevent real usability issues:

1. **Form input sizing**: All `<Input>` and `<Select>` elements must use `text-base` (16px minimum). This prevents iOS Safari from auto-zooming the viewport when a user focuses an input field (triggered at font sizes below 16px). This is a platform bug workaround, not an aesthetic choice.

2. **Use shadcn/ui components**: Use library components (`<Button>`, `<Input>`, `<Card>`, etc.) instead of raw HTML elements. This ensures accessibility baselines (ARIA attributes, keyboard handling, focus management) without manual effort.

3. **Scroll-triggered animation safety**: Never use `opacity: 0` or `visibility: hidden` as an initial state for content sections awaiting scroll reveal. If using IntersectionObserver, handle the initial callback where `isIntersecting` is already `true` for above-the-fold elements. Entrance animations use CSS transforms (translateY, scale) while keeping content visible.

4. **Reduced-motion respect**: All animations (CSS transitions and JS-driven IntersectionObserver reveals) must respect `prefers-reduced-motion`. CSS: wrap motion in `@media (prefers-reduced-motion: no-preference)`. JS: check `window.matchMedia('(prefers-reduced-motion: reduce)')` and skip animation setup when true.

## Design Decisions

Before generating pages, derive design constraints from experiment.yaml and establish
visual direction. `frontend-design` is the recommended executor for visual
decisions (see `### Recommended executor`); skills decide when and how to
invoke it.

> Skip this section if `stack.surface` resolves to `none`.
> (Inference: `stack.services[0].hosting` present → `co-located`; absent → `detached`.
> Explicit `stack.surface` in experiment.yaml overrides inference.)

### Design constraints

Three hard constraints must be derived from experiment.yaml's product domain before
any visual decisions are made. These compress ~100 open decisions to ~10:

1. **Color direction** — dark, light, or neutral; with temperature: warm or cool.
   Infer from product domain (e.g., security/dev-tools/AI → dark-cool;
   consumer/health/education → light-warm; B2B/finance → neutral-cool).
   Temperature guides background tint (cream vs blue-grey), text color warmth,
   and accent hue selection. The executor may override with justification.
2. **Design philosophy** — minimalist, rich, or playful. Infer from audience
   (developers → minimalist; consumers → rich; creative → playful).
3. **Optimization target** — conversion, documentation, or demonstration.
   Infer from archetype and funnel (web-app with waitlist → conversion;
   service with API → documentation; CLI → demonstration).

These constraints, along with experiment.yaml content, are inputs to the visual
executor.

### Quality bar

Every page must look **world-champion level** — the absolute limit of your
ability. Not adequate, not good — the best you've ever seen. Each page
should make the founder proud. This standard applies equally to all pages,
but expresses differently based on page purpose.

**Per-section rule:** Evaluate per-section. Each section scores independently.
Weakest section determines overall quality. A page cannot hide mediocre social
proof behind a great hero.

**Landing page** (marketing surface) — optimized for **persuasion**.
The benchmark is world-champion persuasion — the absolute limit of your ability:
- Custom color palette (not default shadcn/tailwind colors)
- Considered typography (display + body font, clear hierarchy)
- Meaningful animations (scroll-triggered transforms, staggered transitions — content visible before animation starts)
- Textured depth (subtle gradients, noise overlays, backdrop effects)
- Responsive layout, dark/light mode
- The goal: "I want to share this URL"

**Inner pages** (product surface) — world champion of **utility**.
The benchmark is a top-tier SaaS product (Linear, Vercel, Raycast):
- Same custom palette and typography as landing (visual coherence)
- Proper spacing rhythm (consistent padding, margins, gap)
- Information hierarchy (scannable layout, appropriate data density)
- Interaction quality (loading states, empty states, hover/focus feedback)
- Component completeness (all shadcn/ui, no raw HTML, proper form validation)
- Functional animations (skeleton loaders, micro-interactions, state transitions)
- The goal: "When users open this page, they should feel surprise — this is far better than I expected"

Both expressions share the same theme tokens. Neither is a lower bar —
they are different axes of the same professional standard.

### Quality mechanics

These 5 constraints are the minimum floor (passing does not equal good, just not
bad). The real standard is taste judgment — constraints prevent disaster, taste
drives excellence. Checkable structural constraints that give `frontend-design`
precise targets.

**Landing page (5 constraints):**
1. **Typography tension** — display heading >= 6:1 size ratio vs body text
2. **Layout diversity** — at least one section must break the centered-column pattern (asymmetric grid, full-bleed + inset alternation, overlapping elements)
3. **Depth layers** — minimum 3 z-layers visible simultaneously (background texture/gradient, content, decorative elements)
4. **Interactive hero** — hero section must contain a functioning micro-interaction, not static content
5. **Section differentiation** — each section transition must have a visual event (color temperature shift, background modulation, layout pattern change, or animation). No two adjacent sections may look structurally identical.

**Inner pages (3 constraints):**
1. **Loading choreography** — skeleton-to-content transition must stagger elements, not pop everything at once
2. **Empty state as design moment** — empty tables/lists show illustration + clear CTA, not "No data found"
3. **Hover vocabulary** — every interactive element responds to hover within 50ms (cards lift, buttons glow, links underline-animate)

**Image quality (5 constraints — applies when `public/images/` contains AI-generated assets):**
1. **Subject relevance** — image content clearly relates to product domain and section purpose (hero = aspirational, feature = concept-specific, empty state = encouraging)
2. **Style cohesion** — all generated images share a consistent visual system (same illustration approach, consistent level of abstraction, similar rendering technique). A photorealistic hero with flat-vector features is a style fracture.
3. **Color harmony** — image palette complements the page's custom color palette from globals.css (not clashing, not identical — complementary)
4. **Compositional quality** — intentional negative space, clear focal point, no cluttered or empty regions, suitable for overlaid text where applicable
5. **Production polish** — no AI artifacts (distorted text, extra fingers, floating objects, inconsistent lighting, blurred regions)

**Image anti-patterns:**
- Style fracture — hero uses photorealism while features use flat illustration (inconsistent visual system)
- Stock photo feel — images look like generic stock rather than custom-designed for this product
- AI artifact visibility — distorted text, unnatural hands, floating objects, impossible geometry
- Composition conflict — image content competes with overlaid page text for attention
- Color temperature disconnect — image color temperature clashes with page design tokens

> These mechanics are structural constraints, not technique prescriptions.
> `frontend-design` decides HOW to satisfy each one.

### CSS Technique Catalog

Vocabulary of premium techniques for the executor — tools available, not a
checklist. `frontend-design` retains creative authority over HOW to use them.
Prefer the left column over the right column in each row.

**Color & Surface:**

| Scenario | Prefer | Over |
|----------|--------|------|
| Text color | Tinted near-black: warm `#1a1a0e` / cool `#0a0a1a` | Pure black `#000000` |
| Background | Tinted near-white: warm `#f5f4ed` / cool `#f0f4f8` | Pure white `#ffffff` |
| Warm/cool choice | Follow design constraints temperature derivation | Arbitrary choice |
| Accent color usage | Primary CTA and key actions only | Decorative usage |

**Typography:**

| Scenario | Prefer | Over |
|----------|--------|------|
| Display letter-spacing (48px+) | -1.5px to -2.5px | 0px or positive values |
| Body letter-spacing | -0.1px to 0px | Large negative values |
| Heading line-height | 1.07 to 1.15 (compressed) | Uniform line-height |
| Body line-height | 1.5 to 1.6 (open) | Uniform line-height |
| Font features | `font-feature-settings: "ss01" on` when supported | Default settings |

**Depth & Shadow:**

| Scenario | Prefer | Over |
|----------|--------|------|
| Card borders | `box-shadow: 0 0 0 1px rgba(...)` (ring shadow) | `border: 1px solid #ccc` |
| Shadow color | Brand-accent-tinted `rgba(accent, 0.12-0.25)` | Neutral gray `rgba(0,0,0,0.1)` |
| Shadow layers | 2-3 layers (near blur 2-4px + far blur 16-24px) | Single layer |
| Depth texture | `backdrop-filter: blur(16px)` + SVG noise (opacity 0.03-0.05) | Flat opaque backgrounds |
| Dark mode cards | Translucent `rgba(255,255,255,0.05)` + rgba border | Flat dark gray |

**Interaction:**

| Scenario | Prefer | Over |
|----------|--------|------|
| Primary CTA shape | Pill `border-radius: 9999px` | Default radius |
| Secondary buttons | `border-radius: 6-8px` | Pill shape |
| Hover states | Opacity transition or warm color shift | Background color change |
| Scroll reveal | BlurFade (blur + translate + opacity) | Simple `opacity: 0→1` |

**Magic UI Component Selection Guide** (all 74 pre-installed, import from `@/components/ui/`):

| Category | Components | Use for |
|----------|-----------|---------|
| Text effects | aurora-text, morphing-text, line-shadow-text, text-reveal, hyper-text, animated-gradient-text, word-rotate, typing-animation, sparkles-text, spinning-text, flip-text, text-animate, animated-shiny-text | Hero headlines, section titles, animated labels |
| Background effects | warp-background, grid-pattern, dot-pattern, flickering-grid, retro-grid, animated-grid-pattern, particles, meteors, grid-beams | Hero backgrounds, section backgrounds |
| Card effects | magic-card, neon-gradient-card, border-beam, shine-border | Feature cards, pricing cards, product showcases |
| Button effects | shimmer-button, shiny-button, pulsating-button, ripple-button, rainbow-button, interactive-hover-button, animated-subscribe-button | Primary CTA, signup buttons, action buttons |
| Layout | bento-grid, marquee, orbiting-circles, dock, avatar-circles, icon-cloud | Feature grids, social proof, tech stack display |
| Reveal effects | blur-fade, box-reveal, scroll-progress, progressive-blur, text-reveal, scratch-to-reveal | Section entrance, content reveal, progress indicators |
| Delight | confetti, cool-mode, ripple | Conversion confirmation, Easter eggs |
| Product mockups | safari, iphone-15-pro, terminal, android | Product screenshots, demo displays |
| Developer | file-tree, code-comparison, script-copy-btn | Dev tool products, API docs |
| Utility | number-ticker, animated-list, lens, pointer, smooth-cursor, highlighter, arc-timeline, animated-theme-toggler, hero-video-dialog, globe, animated-circular-progress-bar, pixel-image, video-text, scroll-based-velocity, comic-text, striped-pattern, interactive-grid-pattern | Stats, lists, navigation, data viz |

### Design Anti-Patterns (Never Do)

Prohibitive rules with HIGHER priority than creative suggestions. The
`design-critic` Layer 3 check evaluates violations of these rules.

1. **Pure black text** — never use `#000000`. Use tinted near-black (warm: `#1a1a0e`, cool: `#0a0a1a`)
2. **Pure white background** — never use `#ffffff` as main background. Use tinted near-white
3. **Gray shadows** — never use neutral `rgba(0,0,0,x)` for shadows. Tint with brand accent color
4. **Single-layer shadows** — at least 2 layers (near blur 2-4px + far blur 16-24px)
5. **CSS border for cards** — use ring shadow `box-shadow: 0 0 0 1px rgba()` instead
6. **Positive letter-spacing at display** — headings 48px+ must use negative letter-spacing (-1.5 to -2.5px)
7. **3+ consecutive same layout** — no 3 adjacent sections with identical layout structure
8. **5+ brand colors** — max 3 brand colors (primary + accent + CTA). CTA color used sparingly
9. **Generic opacity fade-in** — don't use simple `opacity: 0→1`. Use BlurFade (blur + translate) or richer entrance effects
10. **Static hero** — hero section must have ≥1 dynamic element (signature animation, background effect, or interactive element)
11. **Uniform line-height** — headings and body must have different line-heights (headings compressed 1.07-1.15, body open 1.5-1.6)
12. **Background-color hover** — interactive elements should use opacity transition or color-tone shift, not abrupt background color change

### Image Source Strategy

When `image_gen_status` is available, the image source is a creative decision
made by `scaffold-init` in the visual brief's Image Direction section.
Two sources coexist — choose per image based on what builds MORE TRUST
for the specific product domain:

| Signal | Recommended source | Reason |
|--------|-------------------|--------|
| Professional services (medical, legal, financial, real estate) | Unsplash real photography | Real photos build trust. Clients need credibility |
| B2B SaaS / developer tools | AI-generated illustration | Abstract concepts suit conceptual visuals |
| Consumer products (lifestyle, health, fitness) | Mixed: hero Unsplash, features AI | Real scenarios + conceptual features |
| Creative tools / design products | AI-generated illustration | Showcases creative capability |
| Hardware / physical products | Unsplash product photography | Real product photos are more credible |

**Unsplash usage notes:**
- License: free for commercial use, attribution not required (but encouraged)
- No API key needed — direct URL access
- URL format: `https://images.unsplash.com/photo-{ID}?auto=format&fit=crop&w={width}&q=80`
- Download to `public/images/` to match existing manifest format
- Agent searches Unsplash via WebFetch for domain-relevant photos

**Multi-Candidate Selection:**

The Image Source Strategy table above is a STARTING POINT, not a commitment.
For high-impact images, both AI and Unsplash candidates are generated regardless
of domain, and the best candidate is selected.

**Two-phase candidate budget (explore then exploit):**

| Image | Explore | Sources | Exploit | Sources |
|-------|---------|---------|---------|---------|
| Hero | 3 | 2 AI + 1 Unsplash | 3 AI | Direction-refined |
| Feature ×3 | 2 each (ensemble) | 1 AI + 1 Unsplash | 1 AI each | Direction-refined |
| OG/Social | 2 | 1 AI + 1 Unsplash | 1 AI | Direction-refined |
| Logo | 3 | 3 AI (no Unsplash) | 2 AI | Direction-refined |
| Empty state | 2 | 1 AI + 1 Unsplash | 0 | Skip exploit |

**Direction extraction:** After scoring explore candidates per slot, derive a
15-20 word direction signal from the top-2 candidates. Exploit candidates
reference this signal and vary on secondary axes only (lighting, detail,
perspective, edge treatment).

**Ensemble selection for features:** feature-1 winner is the style anchor.
feature-2 and feature-3 candidates are generated style-matched to feature-1's
winning visual system. The goal is the best COMBINATION of 3, not 3 independent bests.

**Candidate storage:** All candidates live in `.runs/image-candidates/` (NOT
`public/images/`). Only winners are copied to canonical paths. Metadata is
recorded in the sidecar file `.runs/image-candidates.json`. The main manifest
(`.runs/image-manifest.json`) schema is unchanged.

**Phase tagging:** Each candidate in the sidecar includes `"phase": "explore"|"exploit"`
and each slot includes `"direction_signal"`. These fields are additive — downstream
consumers (design-critic) can safely ignore them.

**Unsplash fallback reallocation:** If WebFetch cannot extract multiple Unsplash
photo IDs from the search page, reallocate the Unsplash budget to additional
AI prompt variants. Total candidate count per slot is maintained.

When `frontend-design` is available, invoke it for all pages (with
context-appropriate creative brief). When unavailable, follow the theme
tokens and the relevant expression criteria.

### Recommended executor

The `frontend-design` skill is the recommended executor for all visual
decisions. It has full authority over visual direction — color palette,
typography, spacing, component styling, and layout composition — within the
derived constraints.

For **service/cli archetypes with a surface**: the executor creates a complete,
self-contained HTML marketing page (not a React component). CSS is inline,
fonts via Google Fonts `<link>`, animations via CSS keyframes. Same creative
authority as for web-app — unique visual identity per experiment, not a
generic template.

Skills decide when and how to invoke `frontend-design`. The `design-critic`
agent has `frontend-design` preloaded and full read-write access. When
`frontend-design` is unavailable, the creative brief and constraints provide
sufficient direction.

### Theme contract

- Record choices in the theme layer (globals.css custom properties,
  tailwind config, font setup in layout.tsx)
- All pages consume these tokens — no per-page color/font overrides
- `/change` must preserve these choices unless explicitly asked to restyle

### Visual language brief

The visual language brief (`.runs/current-visual-brief.md`) is a structured
artifact produced by the Init subagent during bootstrap. It extends the theme
contract with non-CSS decisions that affect visual coherence across pages:
animation philosophy, spacing density, component styling, visual texture, etc.

All page-generating subagents (landing, pages) read the same brief so they
produce visually coherent output without needing to see each other's work.
This enables landing and inner pages to be generated in parallel.

The brief is **ephemeral** — it is deleted after the bootstrap PR is committed.
`/change` reads the generated code (globals.css, existing components) to infer
the established visual language rather than referencing the brief.
