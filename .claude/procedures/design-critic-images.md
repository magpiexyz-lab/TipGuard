# Design Critic — Images (Landing) Procedure

> Executed by the **landing-images-critic** agent. See `.claude/agents/landing-images-critic.md` for identity, review criteria, and output contract.
>
> Scope: Step 5.5 image candidate confirmation + image-quality anti-patterns for the LANDING page only. Layer 1/2/3 section scoring is OUT OF SCOPE — owned by the sibling **landing-sections-critic** agent.
>
> Companion: `.claude/procedures/design-critic-sections.md` (Layer 1/2/3 section scoring).
>
> Shared procedure: `.claude/procedures/design-critic.md` (Steps 1-4 / 3.5 / 4.5 / 7-9 shared with the sibling).
>
> **Step 5.5 step 4 regression signal (#1076):** `candidates_tried==0` AND `unresolved_images==[]` AND sidecar `.runs/image-candidates.json` has unused candidates in landing-owned slots is the canonical hard-block signal (state-3b VERIFY, GECR rule `recovery-path-skip-pairing`). Track step numbers AS WRITTEN here — line numbers drift, step numbers do not.

### 1. Prerequisite Check

> REF: see `.claude/procedures/design-critic.md` § 1.

### 2. Rebuild with Demo Mode

> REF: see `.claude/procedures/design-critic.md` § 2.

### 3. Start Production Server (or use provided `base_url`)

> REF: see `.claude/procedures/design-critic.md` § 3.
>
> When spawned in parallel with `landing-sections-critic`, the LEAD pre-starts the server and passes `base_url`; do NOT start a second server (port collision). Use the provided `base_url` directly.

### 3.5. Classify Review Method (per page, before screenshot)

> REF: see `.claude/procedures/design-critic.md` § 3.5.

### 4. Screenshot the Landing Page

> REF: see `.claude/procedures/design-critic.md` § 4, restricted to your assigned page (`landing`). You may reuse screenshots already captured by the sibling critic if the lead pre-staged them in a shared dir; otherwise capture your own.

### 4.5. Visual Regression Baseline Check

> REF: see `.claude/procedures/design-critic.md` § 4.5.

### 5. Section Scoring — OUT OF SCOPE

Layer 1 / 2 / 3 section scoring is owned by `landing-sections-critic`. Do NOT score sections, do NOT touch `min_score` / `sections_below_8` / fixes to layout/animation/spacing/typography.

You MAY consult section-level rendering as context for image judgment (e.g., "this hero image looks pasted-on because the surrounding section uses photorealism while the image is flat illustration") but the fix for any non-image issue belongs to the sibling.

### 5.5. Candidate Selection Phase — FULL SCOPE

> REF: see `.claude/procedures/design-critic.md` § 5.5 (Candidate Image Swap Protocol, Pareto comparison, polish-floor escalation, escape-hatch `unresolved_images` emission). This is YOUR core responsibility.
>
> Apply image-quality anti-patterns from Layer 3 (these are EXCLUDED from sections-critic): style fracture, stock photo feel, AI artifacts visible, color temperature disconnect. Trigger candidate swap or regeneration when any image fails.
>
> og-photo evaluation (REF: `.claude/procedures/design-critic.md` § 5.5 og-photo subsection) is part of your scope.

### 6. Fix Below-Standard Images — Priority 1/2/3 Image Fix Tree

> REF: see `.claude/procedures/design-critic.md` § 6, restricted to image fixes:
>
> - **Priority 1** — Pre-generated candidates from `.runs/image-candidates.json` sidecar
> - **Priority 2** — Generate new candidates with page-context-informed prompts
> - **Priority 3** — Source switching fallback (AI → Unsplash or Unsplash → AI)
>
> SKIP non-image fixes (CSS classes, JSX layout, animation, spacing, typography) — those belong to the sibling.

### Pre-Trace Self-Check (mandatory)

Before writing your trace:

- [ ] Did I read `.runs/image-candidates.json`?
- [ ] For every landing-owned slot (everything except `empty-state`) where `len(candidates) > 1`, did I score every unused candidate IN PAGE CONTEXT (Candidate Image Swap Protocol) — not from disk inspection?
- [ ] Does my trace's `candidates_tried` reflect the count of unused candidates I scored? (`candidates_tried > 0` required when sidecar has unused landing-owned candidates AND `unresolved_images==[]`.)
- [ ] If a candidate could not be scored (file unreadable, dimension limit, production server error), did I emit `unresolved_images: [{slot, reason, best_score}]` for that slot? (the sanctioned escape hatch when `candidates_tried` cannot reach the unused-candidate count).

If ANY check is "no", return to Step 5.5 and complete before writing the trace. The state-3b VERIFY (#1129) AND the new GECR rule `recovery-path-skip-pairing` both hard-block on `candidates_tried==0` when the sidecar has unused landing-owned candidates AND `unresolved_images` is empty AND the trace is not self-degraded with `recovery_validated=True`.

### 7. Cleanup

> REF: see `.claude/procedures/design-critic.md` § 7.

### 8. Report

> REF: see `.claude/procedures/design-critic.md` § 8. Use the agent's "Output Contract" (`.claude/agents/landing-images-critic.md`).

### 9. Compute Trace Metrics

> REF: see `.claude/procedures/design-critic.md` § 9, restricted to the image fields you own: `candidates_tried`, `new_candidates_generated`, `unresolved_images`, `image_scores`, `image_fixes`, `image_issues_for_landing`. Section/layout fields (`min_score`, `sections_below_8`, `weakest_page`) are owned by the sibling and aggregated by `merge-landing-critic-traces.py`.
