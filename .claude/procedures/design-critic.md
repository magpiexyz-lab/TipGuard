# Design Critic Procedure


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — 'professional services' is design-domain language, not archetype branching -->

> Executed by the design-critic agent. See `.claude/agents/design-critic.md` for identity, review criteria, and output contract.

### 1. Prerequisite Check

Run `npx playwright --version`. If it fails, return:
> Skipping visual review — Playwright not installed.

### 2. Rebuild with Demo Mode

Follow the rebuild procedure from `.claude/patterns/visual-review.md` (Section 1b).

### 3. Start Production Server (or use provided base_url)

If a `base_url` was provided in the spawn prompt, skip server start and use that URL directly.
Otherwise, start your own server:

```bash
DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run start -- -p 3099 &
```

Poll the base URL (either provided or `http://localhost:3099`) until it responds (max 15 seconds, then abort).

> REF: see `.claude/patterns/demo-server-startup.md`.

### 3.5. Classify Review Method (per page, before screenshot)

> **Skip path (#1061 — empty-boundary fast-path):** When the state-3a spawn
> prompt directs you to execute the **empty-boundary fast path** (FILE_BOUNDARY
> empty AND no CLAIMED_SHARED block AND no library/component imports from
> the PR boundary), DO NOT run this Step 3.5 — there is no render to classify
> and no review work to perform on this page. Instead, directly write the
> fast-path trace via `write-degraded-trace.py` per the state-3a spawn-prompt
> "Empty-boundary fast path" bullet, then move to the next page (or return
> if this was your only page). The trace will carry
> `review_method="boundary-skip"`, `provenance="self-degraded"`,
> `degraded_reason="empty-boundary-fast-path"`, `verdict="pass"`.

For each route, before screenshotting, run the detection procedure in
`.claude/patterns/render-review-detection.md`. The pattern loads the optional
Playwright storageState (if `e2e/.auth.json` is a valid Supabase session),
navigates to the route with a post-networkidle 500 ms settle wait, classifies
the render, and returns `{review_method, review_evidence, context, page}`.

Inputs to pass:
- `requested_route`: the route you were told to review (pre-concretized
  `test_url` from `.runs/design-page-set.json` when the page has dynamic
  segments — see state-2a)
- `route_pattern`: the literal route template from `.runs/design-page-set.json`
  (e.g. `"/quote/[id]"`). Required for the DEMO_MODE fixture short-circuit
  branch (#1042).
- `demo_mode`: `true` when the dev server is running under `DEMO_MODE=true`.
  Required `true` for the DEMO_MODE fixture short-circuit branch.
- `base_url`: the provided `base_url` or `http://localhost:3099`
- `is_first_page`: `true` only for the first auth-gated route in your list
  (so `demo-mode-bypass-failed` fires exactly once when the upstream bug is
  present; `false` for every subsequent page)

Merge the returned `{review_method, review_evidence}` into this page's
`design-critic-<page_name>.json` trace.

**Branch on the classification:**

- If `review_method ∈ {"source-only", "unknown"}`:
  - **Sub-branch S1 — DEMO_MODE fixture short-circuit (#1042).**
    When `review_evidence.fallback_reason == "demo-mode-fixture-short-circuit"`
    (HTTP 404 + DEMO_MODE + dynamic-segment route — e.g. `/quote/[id]`,
    `/project/[id]`):
    - Do NOT screenshot — the page didn't render.
    - Perform a source-only structural review via Read: the page's .tsx
      source plus one-level imports into `src/components/**` / `src/lib/**`.
      Score on structural criteria only (layout, typography hierarchy,
      color-system usage, Tailwind theme tokens, responsive-grid patterns,
      accessibility markup).
    - Capture `source_review_verdict ∈ {"pass","fixed"}` and
      `source_review_score: int` as nested evidence fields.
    - Write the trace via the self-degraded helper (see
      `.claude/agents/design-critic.md` §Verdict-gate Sub-branch S1 for
      the exact invocation). DO NOT open the trace file directly —
      `agent-trace-write-guard.sh` will block. The helper populates
      `provenance="self-degraded"`, `partial=true`, `verdict="unresolved"`,
      `result=null`, `degraded_reason="demo-mode-fixture-short-circuit"`.
      State-3b Stage-1c will stamp `recovery_validated=true` pre-merge.
    - Move to the next page.
  - **Sub-branch S2 — all other source-only / unknown cases** (auth
    redirect, `demo-mode-bypass-failed`, nav failure):
    - Still take the desktop + mobile screenshots for evidence (Step 4
      viewport loop using the `page` returned by the pattern), so the
      trace has a visual record of what was actually rendered.
    - Skip Layer 1 / Layer 2 / Layer 3 reviews entirely for this page —
      the target source was never rendered, any "fix" would be blind.
    - Set `verdict = "unresolved"` and `caveat = review_evidence.fallback_reason`
      in the trace. Do NOT apply fixes. Move to the next page.

- If `review_method ∈ {"rendered-authed", "rendered-demo"}`:
  - Continue to Step 4 with the `context` and `page` from the pattern — do
    NOT create a fresh BrowserContext in Step 4, reuse the one that already
    has the optional storageState injected.

### 4. Screenshot All Pages

Read `experiment/experiment.yaml` to get the list of pages and their routes. Write a small
inline Node.js script using Playwright API to:
- Launch Chromium (headless)
- Visit each route at the base URL (provided `base_url` or `http://localhost:3099`)
- Wait for network idle
- Take a full-page screenshot at **1280x800** viewport (desktop)
- Save to `/tmp/visual-review/<page-name>.png`
- Take a second full-page screenshot at **375x812** viewport (mobile)
- Save to `/tmp/visual-review/<page-name>-mobile.png`

### 4.5. Visual Regression Baseline Check

Check if `.verify-baseline/` directory exists in the project root.

**If `.verify-baseline/` exists:**

1. Check `pixelmatch` and `pngjs` availability:
   ```bash
   node -e "require('pixelmatch'); require('pngjs')"
   ```
   If this fails → skip visual regression, report: "pixelmatch/pngjs not installed — skipping visual regression check."

2. If available, write an inline Node.js script to pixel-diff each screenshot:
   - For each page screenshot in `/tmp/visual-review/`:
     - Load the current screenshot and the corresponding baseline from `.verify-baseline/`
     - Use `pixelmatch` to compute pixel difference percentage
     - If diff exceeds **5%** → mark page as `REGRESSION-CHECK`
   - 5% threshold filters noise from dynamic content (timestamps, random demo data)

3. Pages marked `REGRESSION-CHECK` get extra scrutiny in Layer 2 — any visual regression must be intentional.

**If `.verify-baseline/` does not exist:**

Note: "First run — no baseline exists. Will save baseline after review."

### 5. Review Each Screenshot

Use the Read tool to view each screenshot. Apply three review layers.

#### Layer 1: Functional (floor check)

For every page, check:
- **Fonts loaded** — intended font, not system fallback
- **Colors applied** — not default unstyled gray
- **Layout intact** — no overlapping elements, no blank areas
- **Content renders** — real content or plausible placeholder, not error state
- **Above-the-fold quality** — polished, not broken or template-like
- **Mobile: touch targets** — interactive elements ≥ 44px
- **Mobile: text legibility** — body font size ≥ 14px
- **Mobile: no horizontal overflow** — no content wider than viewport
- **Mobile: navigation usable** — hamburger menu or equivalent on small screens
- **Images render** — if `public/images/` contains files, verify no broken image icons in screenshots. Read each image file with the Read tool to visually inspect standalone quality.
- **Image manifest** — check `.runs/image-manifest.json` for generation status and per-image quality scores from scaffold-images
- **SVG transparency** — if logo is SVG format, verify no opaque white background rectangle is present. Check both the SVG source (read the file for `<rect>` elements with white fill like `#fff`, `#FFFFFF`, or `white`) and the visual rendering (no white square visible against the page's background color). If a white background rect is found, remove it from the SVG source and verify the logo renders correctly.

Any Layer 1 failure → fix immediately before continuing to Layer 2.

#### Layer 2: Per-Section Taste Judgment

**Evaluate per-section.** Each section of each page scores independently on a
1-10 scale. The weakest section determines the page verdict. A page cannot hide
mediocre social proof behind a great hero.

**Universal criteria** (all pages, all sections):
1. Custom palette — not default shadcn/tailwind colors, matches derived direction?
2. Typography — display + body font pairing, clear size/weight hierarchy?
3. Visual depth — meaningful animations, gradients, shadows, or transitions (not bare flat)?
4. Spacing rhythm — consistent padding, margins, gaps across sections?
5. Component quality — shadcn/ui components with project theming, no raw HTML?
6. Composition — intentional layout hierarchy, polished arrangement?

**Image integration criteria** (when `public/images/` contains AI-generated assets):
7b. Image fusion — do images look "designed in" to the page, or "pasted on" from a different source?
7c. Color temperature match — do image tones harmonize with the page's CSS color palette?
7d. Visual weight — is image presence in each section appropriate (not overwhelming, not invisible)?

**Landing page bonus criterion** — each section is also judged on **persuasion**:
7. Conversion pull — does this section actively advance the visitor toward the CTA? (emotional hook, objection handling, urgency, social proof)

**Inner page bonus criterion** — each section is also judged on **utility**:
7. Task efficiency — does the layout minimize cognitive load for the user's goal? (scannable hierarchy, loading/empty states, hover/focus feedback)

**All pages same standard.** Landing = world champion of persuasion, inner
pages = world champion of utility. Neither is a lower bar.

#### Layer 3: Anti-pattern Rejection (floor check)

Any of these triggers automatic fix — each has a measurable threshold:
- **Animation monotony** — ≥3 sections use the same animation technique (e.g., all fade-in/slide-up) → diversify animation types
- **Layout monotony** — ≥3 sections share identical layout structure (e.g., all centered single-column) → introduce layout variation (grid, asymmetric, split, offset)
- **Hero passivity** — hero contains 0 interactive or dynamic elements beyond a static button (no animation, no illustration, no gradient shift, no particle/shape) → add visual dynamism
- **Default component styling** — ≥50% of Card/Button/Badge instances use unmodified shadcn defaults (no custom colors, borders, shadows, or size overrides) → apply project theme
- **Scroll inertness** — page has 0 scroll-triggered visual events across all sections (no reveals, parallax, counters, sticky transforms) → add scroll interaction to ≥2 sections
- **Style fracture** — hero image uses photorealism while feature images use flat illustration (or vice versa) → regenerate inconsistent images with unified style prompt
- **Stock photo feel** — AI-generated images look like generic stock rather than custom-designed → regenerate with more product-specific prompts
- **AI artifacts visible** — distorted text, extra fingers, floating objects in any image → regenerate with refined prompt emphasizing "clean, no artifacts"
- **Color temperature disconnect** — image color temperature visibly clashes with page design tokens → regenerate with explicit HEX color references from globals.css

> **Scope Lock**: When fixing sections, change ONLY visual output (CSS classes, JSX structure for layout, animation code). Do NOT refactor component architecture, rename variables, or change state management patterns. If a section needs architectural changes to fix visually, note it as unresolved.

### 5.5. Candidate Selection Phase

#### Candidate Image Swap Protocol

When evaluating a candidate image in page context (used by Step 5.5d, Step 6
Priorities 1/2/3, and og-photo evaluation), use a fresh production server
to avoid dev server image caching:

1. Copy candidate to `public/images/<filename>` (overwriting current)
2. Start production server: `npx next start -p 3099 &`; wait for ready (max 15s, poll `http://localhost:3099`)
3. Screenshot against `http://localhost:3099` (NOT the original `base_url` — the dev server may cache the old image)
4. Score the candidate in page context
5. Kill the production server: `kill $(lsof -ti:3099) 2>/dev/null || true`

Use the original `base_url` for all non-candidate operations (initial review,
post-fix re-screenshots). The production server serves `public/` at runtime,
so no `npm run build` is needed between candidate swaps — only a server restart.

#### Landing-page critic — full candidate evaluation (CONFIRMATION flow)

> **MANDATORY trace-write contract (fix #1129 — state-3b VERIFY enforced).**
> If `.runs/image-candidates.json` exists AND any landing-owned slot (everything
> except `empty-state`) has `len(candidates) > 1`, you MUST score every unused
> candidate in page context AND emit `candidates_tried > 0` in your trace
> (and populate `new_candidates_generated` with any Step 5.5 polish-floor
> escalation regenerations — both fields being `0` is the procedure-line-244
> regression signal).
> The state-3b VERIFY at `state-registry.json` rejects the trace when the
> sidecar has unused landing-owned candidates AND `candidates_tried==0` AND
> `unresolved_images` is empty. Skipping this confirmation pass is a procedural
> violation that will block the verify run. The only sanctioned ways to ship
> `candidates_tried==0` with unused candidates present are:
> (a) emit `unresolved_images: [{slot, reason, best_score}]` describing why
> a candidate could not be scored (e.g., file unreadable, dimension limit), or
> (b) self-degrade with `provenance="self-degraded"` AND a sanctioned reason
> (see Self-Degradation Handler in `.claude/agents/design-critic.md`).

If you are reviewing the **landing page** AND `.runs/image-candidates.json` exists, this step runs as a **confirmation** pass, not remediation (fix #1076). Always compare the currently selected candidate against every unused candidate for that slot using Pareto dominance — do NOT wait for the selected candidate to score below a threshold before trying alternates.

**Polish-scoring rule (fix #1076 Fix B — masking-as-polish prohibition):**

> Polish scoring MUST reflect the raw asset as it ships to `public/`. Render-time CSS mitigations (opacity, filter, mix-blend-mode, masks) MUST NOT be used to justify a polish score above what the raw image earns. If the raw image contains AI-gibberish text, malformed anatomy, visible seams, or inconsistent lighting, polish is capped at 7 regardless of in-context rendering. Masking does not travel to OG-share, high-DPI screenshots, or zoomed views — the raw file ships.

1. Read `.runs/image-candidates.json` — this sidecar contains pre-generated candidates from the scaffold-images agent.
2. For each image slot with `candidates.length > 1`:
   a. Identify the current winner rendered on the page (the image at `public/images/<canonical filename>`).
   b. Score the current winner IN page context using the Layer 2 image integration criteria (subject relevance, style cohesion, color harmony, composition, polish). Apply the polish-scoring rule above.
   c. **Sampling rule (#1272, round-2 Concern 8):** rank unused candidates by their out-of-context scores; evaluate at minimum `min(N-1, 6)` candidates IN page context per slot (where N = total candidates). Prefer candidates within score-delta < 1 of the current winner; pick remaining slots from highest-scoring out-of-context candidates if fewer than the floor are within delta.
   d. For each candidate selected in (c), execute the Candidate Image Swap Protocol AND the **physical evidence contract (#1272 hard-block)**:
      - Save the in-context screenshot to `.runs/screenshots/candidates/<slot>-<candidate-basename>.png` (overwriting if exists). The screenshot must be PNG format, dimensions ≥ 1280×720.
      - Save the rendered DOM alongside the screenshot to `.runs/screenshots/candidates/<slot>-<candidate-basename>.html` from the SAME Playwright session that produced the screenshot. Both writes happen inside the inline Node.js loop you already use for the Candidate Image Swap Protocol — extend it with one extra `fs.writeFileSync` call per iteration:

        ```js
        // Inside your existing per-candidate Playwright loop:
        const safeBase = candidateBasename.replace(/\.[^.]+$/, '');
        const pngPath  = `.runs/screenshots/candidates/${slot}-${safeBase}.png`;
        const htmlPath = `.runs/screenshots/candidates/${slot}-${safeBase}.html`;
        await page.goto('http://localhost:3099/' /* or page-specific route */, { waitUntil: 'networkidle' });
        await page.setViewportSize({ width: 1280, height: 800 });
        await page.screenshot({ path: pngPath, fullPage: true });
        fs.writeFileSync(htmlPath, await page.content());  // <-- DOM-binding evidence
        ```

        Required by the DOM-binding check (#1272 follow-up): the validator at state-3b VERIFY asserts at least one `<img src>` in this DOM references either the candidate basename or the canonical slot path. Defense against fabricated scores against unrelated screenshots — agents cannot produce a DOM snapshot for a page they did not render.
      - Write a sibling `<candidate-path>.provenance.json` if not already present (scaffold-images writes this at generation time per #1272 — only re-write if missing). Required fields: `model`, `prompt_hash`, `seed`, `generated_at`.
      - Populate `score_in_context: {subject, style, color, composition, polish}` on the candidate in `image-candidates.json`.
      - Populate `evaluation_notes: ["<reasoning, ≥50 chars>"]` on the candidate — at least one substantive note explaining the score in context.
   e. **Pareto comparison (fix #1076 Fix A):** for each evaluated candidate, check whether it Pareto-dominates the current winner on any axis — strictly ≥ on all five axes AND strictly > on at least one. Ties break by polish first, then total. If an unused candidate Pareto-dominates the current winner: swap. This activates whenever a strictly-better alternate exists, not only when the current winner drops below a threshold.
   f. After the Pareto pass, record the final winner. Update `.runs/image-manifest.json` with the winner's source, model, and scores.
   g. Update `.runs/image-candidates.json` sidecar: set `"selected": true` on the new winner, `"selected": false` on the old winner. Stamp `schema_version: 2` at the top of the sidecar **only if missing** — scaffold-images Step 5b is now the canonical birthplace per #1272 follow-up, so this stamp is defensive (idempotent) for legacy sidecars whose producer ran before that change. Pre-cutoff sidecars on pre-cutoff runs are grandfathered by the validator's auto-stamp-on-read logic.

   **Hard-block enforcement (#1272):** the validator at `.claude/scripts/validate-step55-evidence.py` runs at state-3b VERIFY. It asserts that for each landing-owned slot with N>1 candidates: at least min(N-1, 6) candidates have evidence screenshots at `.runs/screenshots/candidates/<slot>-*.png` with magic-byte + dimension checks, paired provenance JSON with unique (model, prompt_hash, seed) triples per slot, populated `score_in_context`, and substantive `evaluation_notes`. Skipping the evaluation work cannot satisfy this gate (round-2 critic Concern 5: polarity inverted from "trace claims" to "sidecar physical state").
3. **Polish-floor escalation (fix #1076 Fix C):** if the post-comparison winner still has polish < 9, spawn `scaffold-images` for one-off regeneration with a tightened direction signal derived from the detected defect (e.g., "only short real English labels; no synthetic body text"). Budget: 1 regeneration per slot per verify run. Score the regenerated candidate IN context. If the regenerated candidate reaches polish ≥ 9, swap; otherwise keep the best available and emit `unresolved_images: [{slot, reason, best_score}]` in the trace so downstream gates (verify-report, auto-merge) can block.

   **Slot-intent escalation skip (Issue #1077, PR3 — read-only addition):** before triggering regeneration, read `.runs/slot-intent.json`. When `design_slots_enabled == true`, for the current slot, if `slot_role != "focal"` OR `runtime_gate != null`, **skip polish-floor escalation entirely** and record `polish_floor_skipped_low_priority: true` in the slot's `image_scores` trace entry. Rationale: regenerating a slot declared `texture` / `watermark` / `conditional` to chase polish=10 wastes the regeneration budget — the user-visible contribution is already low (texture/watermark) or unreachable in DEMO_MODE (conditional + runtime_gate). polish < 9 is acceptable for non-focal slots. design-critic does NOT mutate slot-intent.json (read-only). When slot-intent is absent or flag is false, fall through to legacy escalation.

4. Populate `candidates_tried` and `new_candidates_generated` in the trace with actual counts — these being `0` across all agents is the signal that Step 5.5 did not run (the #1076 regression vector). The state-3b VERIFY (fix #1129) hard-blocks `candidates_tried==0` when the sidecar has unused candidates in landing-owned slots AND `unresolved_images` is empty AND the trace is not self-degraded with `recovery_validated`.

#### og-photo — metadata-based evaluation (landing-page critic only)

The og-photo image is a `<meta property="og:image">` tag invisible in page screenshots.
Evaluate it via metadata and direct file inspection instead of in-context screenshot scoring:

1. Read `.runs/image-manifest.json` and find the og-photo entry
2. Use the Read tool to visually inspect the og-photo file directly
3. Check: file exists, dimensions meet minimum (1200x630), format is valid (png/jpg/webp)
4. Score the image standalone on: subject relevance, brand consistency with page palette, production polish, text legibility at thumbnail size
5. If score < 8: apply the same three-priority fix tree from Step 6 (try candidates → generate new → source switch)
6. Record og-photo evaluation in trace under `image_scores`

#### Inner-page critic — empty-state image slot

If your page renders an empty-state image (check `src/app/<page>/` for references to `public/images/empty-state*`):

1. Read `.runs/image-candidates.json` (provided as READ-ONLY context) for empty-state slot candidates
2. Use the Read tool to visually inspect the current empty-state image
3. Score standalone on: subject relevance, color harmony with page palette, emotional tone
4. Do NOT modify or replace the image. Record any issues in the trace under `image_issues_for_landing`

#### Non-landing, non-empty-state pages

Skip this step entirely. Record any image issues you notice in the trace under `image_issues_for_landing`.

### 6. Fix Below-Standard Sections

For any section rated below 8/10 in Layer 2, or any Layer 1/Layer 3 failure:

1. Read the source code for the affected section
2. Fix it directly — rewrite the section if needed
3. Run `npm run build` (must pass)
4. Re-screenshot the fixed page
5. Verify improvement with the Read tool

**Image fix path — three-priority decision tree** (when root cause is the image itself, not CSS/layout):

**Non-landing critics:** Do NOT regenerate or replace images. Record the issue in the trace `image_issues_for_landing` array (e.g., `{"slot": "hero", "issue": "color temperature too warm for this page's cool palette"}`). The landing-page critic owns all image decisions.

**Landing-page critic only:**

1. Analyze what's wrong with the image in page context (color mismatch? wrong subject? AI artifacts? style inconsistency? composition competes with text?)

2. **Priority 1 — Try remaining pre-generated candidates** (if `.runs/image-candidates.json` exists and was not exhausted in Step 5.5):
   - For each untried candidate in the sidecar for this slot: use the **Candidate Image Swap Protocol** (Section 5.5) to evaluate in page context
   - If any candidate scores ≥ 8 in context → accept it. Update manifest and sidecar.

3. **Priority 2 — Generate new candidates with page context:**
   - Read `.claude/stacks/images/fal.md` for prompt templates
   - Craft 2-3 NEW prompts, each addressing the visual problem from a DIFFERENT angle. Each prompt should vary on a different axis (subject framing, composition, emotional tone, camera perspective) while fixing the identified problem. Examples:
     - Problem: "color temperature too warm" → v1: cool-toned abstract with explicit cool HEX; v2: blue-hour photography with muted palette; v3: monochrome illustration with accent color from globals.css
     - Problem: "composition competes with headline" → v1: "clean negative space, focal point lower-right"; v2: "soft bokeh background, subject small and offset"; v3: "atmospheric gradient, no strong subject"
   - Generate new candidates to `.runs/image-candidates/`:
     ```bash
     DEMO_MODE= npx tsx -e "import { generateImage } from './src/lib/image-gen'; const r = await generateImage({ type: '<type>', prompt: '<context-informed prompt>', width: <w>, height: <h>, filename: '<slot>-critic-<N>.webp', altText: '<alt>', outputDir: '.runs/image-candidates' }); console.log(JSON.stringify(r));"
     ```
   - Try each new candidate in context using the **Candidate Image Swap Protocol** (Section 5.5)
   - Update `.runs/image-candidates.json` sidecar with new entries
   - Also try Unsplash if appropriate: craft search terms informed by the visual problem (e.g., "color too warm" → search for cool-toned photos: `cool-tone-minimal-workspace`). Use a DIFFERENT search query for each Unsplash candidate — picking multiple photos from the same search produces similar results, not diverse candidates. WebFetch search → download to `.runs/image-candidates/` → try in context

4. **Priority 3 — Source switching fallback:**
   - Was AI → search Unsplash for a real photo (professional services, human subjects often better as real photography)
   - Was Unsplash → try AI generation (abstract concepts often better as AI art)
   - Compare best from each source, keep the higher scorer

5. Read the new image file to verify improvement
6. Update `.runs/image-manifest.json` with new scores, source type, and model

Continue image fixes until all image scores ≥ 8 or turn budget exhausted.

After fixing sections on a page, re-screenshot the entire page once and re-rate all fixed sections from that screenshot. If any fixed section is still < 8, continue fixing. Reserve ≥ 30 turns for re-screenshot verification and trace writing. If remaining turns < 30, stop fixing and write the trace immediately with verdict `"unresolved"`.

**Fix Tracking**: As you apply each fix, record it as `{"file": "<path>", "symptom": "<what was wrong>", "fix": "<what you changed>"}`. These entries populate the `fixes` array in the final trace JSON. The count of entries in `fixes` must equal the `fixes_applied` numeric field.

After all fixes are complete, save current screenshots as the new baseline:

```bash
mkdir -p .verify-baseline
cp /tmp/visual-review/*.png .verify-baseline/
```

> **Note:** `.verify-baseline/` should be added to `.gitignore` — baselines are machine-specific (different rendering engines, font availability). Each developer/CI environment maintains its own baseline.

### 7. Cleanup

If you started your own server (no `base_url` was provided), kill it:

```bash
kill %1 2>/dev/null || true
```

Clean up screenshots:

```bash
rm -rf /tmp/visual-review
```

### 8. Report

Collect all changes made:
- Run `git diff` to capture diffs
- Write a one-line summary for each fix

### 9. Compute Trace Metrics

Before writing the trace file, compute these metrics from your review:

- **`min_score`**: the lowest Layer 2 per-section score across **in-boundary pages only**, measured *after* fixes are applied. If no in-boundary sections were reviewed, use `0`. Out-of-boundary pages do not affect this metric.
- **`weakest_page`**: the page name that contains the section with the lowest post-fix score (in-boundary only). If tied, pick the first page alphabetically.
- **`sections_below_8`**: count of sections that scored below 8 *before* fixes were applied (in-boundary only). This captures how much work was needed.
- **`fixes_applied`**: total number of fixes applied across all pages (Layer 1 + Layer 2 + Layer 3 combined). Use `0` if no fixes were needed.
- **`unresolved_sections`**: count of in-boundary sections that remained below 8 when turn budget was exhausted. Use `0` if all sections were fixed to >= 8.
- **`min_score_all`**: the lowest Layer 2 per-section score across **all pages** (including out-of-boundary), measured after fixes. This provides full visibility into pre-existing quality debt.
- **`pre_existing_debt`**: JSON array of `{"page":"<name>","score":<N>}` objects for out-of-boundary pages with any section scoring below 8. Use `[]` if none.

These metrics are written into the trace JSON (see agent definition for the trace command).
