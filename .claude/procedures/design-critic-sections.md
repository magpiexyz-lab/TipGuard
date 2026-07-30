# Design Critic — Sections (Landing) Procedure

> Executed by the **landing-sections-critic** agent. See `.claude/agents/landing-sections-critic.md` for identity, review criteria, and output contract.
>
> Scope: Layer 1/2/3 section scoring for the LANDING page only. Image candidate inspection (Step 5.5) is OUT OF SCOPE — owned by the sibling **landing-images-critic** agent.
>
> Companion: `.claude/procedures/design-critic-images.md` (Step 5.5 image work).
>
> Shared procedure: `.claude/procedures/design-critic.md` (non-landing pages, plus the Steps 1-4 / 3.5 / 4.5 / 7-9 shared by both landing critics).

### 1. Prerequisite Check

> REF: see `.claude/procedures/design-critic.md` § 1.

### 2. Rebuild with Demo Mode

> REF: see `.claude/procedures/design-critic.md` § 2.

### 3. Start Production Server (or use provided `base_url`)

> REF: see `.claude/procedures/design-critic.md` § 3.
>
> When spawned in parallel with `landing-images-critic`, the LEAD pre-starts the server and passes `base_url`; do NOT start a second server (port collision). Use the provided `base_url` directly.

### 3.5. Classify Review Method (per page, before screenshot)

> REF: see `.claude/procedures/design-critic.md` § 3.5.

### 4. Screenshot the Landing Page

> REF: see `.claude/procedures/design-critic.md` § 4, restricted to your assigned page (`landing`).

### 4.5. Visual Regression Baseline Check

> REF: see `.claude/procedures/design-critic.md` § 4.5.

### 5. Review the Landing Screenshot — Sections Only

Use the Read tool to view the landing screenshot. Apply layers 1 / 2 / 3 from `.claude/procedures/design-critic.md` § 5 with these scope adjustments:

- **Layer 1 (Functional floor)** — apply in full, EXCLUDING the image-quality bullet ("Images render" + "Image manifest" + image-related SVG checks). Image quality is owned by `landing-images-critic`.
- **Layer 2 (Per-Section Taste Judgment)** — apply universal criteria 1-6 + Landing-page bonus (criterion 7: Conversion pull). SKIP image integration criteria 7b/7c/7d — `landing-images-critic` evaluates image fusion / color temperature / visual weight separately.
- **Layer 3 (Anti-pattern Rejection)** — apply animation monotony, layout monotony, hero passivity, default component styling, scroll inertness. SKIP style fracture, stock photo feel, AI artifacts visible, color temperature disconnect — image-specific anti-patterns are owned by `landing-images-critic`.

Any Layer 1 failure or Layer 2 score < 8 → fix immediately before continuing.

### 5.5. Image Candidate Selection — OUT OF SCOPE

This step is owned by the sibling `landing-images-critic`. Do NOT screenshot image candidates, do NOT regenerate images, do NOT touch `.runs/image-candidates.json`. If you observe an image quality issue during Layer 2, note it in your trace under `image_issues_for_landing` (a `[{slot, issue}]` array) for the lead-merge to surface to the images critic via the aggregate trace — same shape as non-landing critics' observation channel.

### 6. Fix Below-Standard Sections — Layout/Animation/Spacing Only

> REF: see `.claude/procedures/design-critic.md` § 6, restricted to non-image fixes. SKIP the Priority 1-3 image fix priority tree (lines covering "Pre-generated candidates", "Generate new candidates with page context", "Source switching fallback").
>
> Allowed fix categories: CSS classes, JSX layout structure, animation code, spacing rhythm, component theming, typography hierarchy. Image swaps, candidate selection, and AI generation are all out of scope.

### 7. Cleanup

> REF: see `.claude/procedures/design-critic.md` § 7.

### 8. Report

> REF: see `.claude/procedures/design-critic.md` § 8. Use the agent's "Output Contract" (`.claude/agents/landing-sections-critic.md`).

### 9. Compute Trace Metrics

> REF: see `.claude/procedures/design-critic.md` § 9, restricted to the section/layout fields you own (`min_score`, `sections_below_8`, `pages_reviewed`, `weakest_page`, etc.). Image-specific fields (`candidates_tried`, `new_candidates_generated`, `unresolved_images`, `image_scores`, `image_fixes`) are owned by the sibling and aggregated by `merge-landing-critic-traces.py`.
