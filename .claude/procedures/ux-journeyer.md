<!-- coherence-allow: raw-golden_path (sequence-step) scope=["### 2. Read Context", "### 3. Read or Derive Golden Path", "### 5. Navigate the Golden Path", "### 10. Compute Trace Metrics"] — ux-journeyer walks golden_path steps in funnel order and computes coverage_pct as percentage of sequential steps completed. LIST semantics, not SET. -->

# UX Journeyer Procedure


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — 'click-driven' substring matches 'cli' regex; UX testing patterns are archetype-agnostic -->

> Executed by the ux-journeyer agent. See `.claude/agents/ux-journeyer.md` for identity and output contract.

### 1. Prerequisite Check

Run `npx playwright --version`. If it fails, return:
> Skipping UX journey review — Playwright not installed.

### 2. Read Context

- Read `experiment/experiment.yaml` — golden_path, behaviors, thesis, target_user
- Read `experiment/EVENTS.yaml` — events map (these define the expected journey steps)
- Read `.runs/current-plan.md` if it exists — check for an explicit Golden Path field

### 3. Read or Derive Golden Path

If experiment.yaml has a `golden_path` field: use it directly. Record the steps as the expected journey.

If experiment.yaml has no `golden_path` field: derive from behaviors + experiment/EVENTS.yaml `events` map:
Landing -> [signup if auth] -> [core page] -> [activation].

If `.runs/current-plan.md` exists and has a Golden Path section that differs from experiment.yaml,
prefer experiment.yaml (it's the persistent source of truth).

Record the expected path as an ordered list of steps with expected routes.

### 4. Rebuild & Start Server

Follow the rebuild procedure from `.claude/patterns/visual-review.md`
(Section 1b). Start the server on port **3098** (different from design-critic's
3099):

```bash
DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run start -- -p 3098 &
```

Poll `http://localhost:3098` until it responds (max 15 seconds, then abort).

> REF: see `.claude/patterns/demo-server-startup.md`.

### 5. Navigate the Golden Path

Write an inline Playwright script that:

1. Launches Chromium (headless)
2. Determines journey-level `auth_requirement` based on first step's route. To classify a route as "auth-gated" or "public", read the Next.js route-protection file once at journey start to extract the matcher patterns (Next.js convention). Probe `src/proxy.ts` first (Next.js 16+ default per the filename↔export-name invariant documented at `.claude/stacks/framework/nextjs.md` Stack Knowledge); fall back to `src/middleware.ts` for projects bootstrapped before the proxy.ts canonicalization (the legacy filename still works on 16+ but emits a deprecation warning). Use whichever exists — treat both as the same concept. Routes matched by this file that redirect unauthed traffic are auth-gated; routes outside the matcher are public. Fall back to the canonical `AUTH_PATHS` set (`/login`, `/signup`, `/auth/callback`, `/auth/reset-password`) — these are always auth-related, but ARE public landing surfaces, NOT auth-gated:
   - First step's route is in the project's public surface (`/`, `/pricing`, `/about`, anything outside the middleware matcher) → `"anonymous"` (do NOT inject storageState — anonymous journeys must run on a fresh context to avoid session leakage from prior `e2e/.auth.json`)
   - First step's route IS matched by proxy/middleware as auth-gated (e.g., `/dashboard`, `/settings`) → `"required"`
   - Cannot determine (neither file exists, ambiguous) → `"optional"` (preserves pre-PR-3 behavior — fall back to demo-mode tolerance)
3. Calls `setupAuthContext(browser, {auth_requirement})` (per `.claude/patterns/render-review-detection.md` Section 6.1) to create the BrowserContext.
4. **If `setupAuthContext` returns `reviewMethodEarly === "prereq-unmet"`**:
   - Write trace with `verdict="blocked"`, `caveat="prereq-unmet:<fallback_reason>"`, empty `per_step_reviews`. Exit. The journey cannot start.
5. Starts at first step's route (use `page.goto` ONCE for the entry point; subsequent navigation is click-driven).
6. Per-step loop:
   - **Compute `is_first_page` via the `firstAuthGatedSeen` pattern** (NOT `i === 0`).
     `step.destination_route` is auth-gated if (a) it appears in the middleware matcher set built in Step 2 above, OR (b) absent that file, the route is not in the project's public surface. The flag fires `demo-mode-bypass-failed` exactly once per journey:
     ```javascript
     // Initialized BEFORE the per-step loop:
     let firstAuthGatedSeen = false;
     // Inside the loop, per step:
     const isAuthGated = middlewareAuthRoutes.has(step.destination_route);
     const is_first_page = isAuthGated && !firstAuthGatedSeen;
     if (isAuthGated) firstAuthGatedSeen = true;
     ```
     This preserves the hard-constraint #7 semantic. Anonymous journeys never fire `demo-mode-bypass-failed` — `render-review-detection.md` Section 3 additionally suppresses that diagnostic when `auth_requirement="anonymous"`, so even if step 0 is mistakenly classified as auth-gated the diagnostic stays silent.
   - Find the primary CTA on current page.
   - Click the CTA (Playwright **native click — NOT `page.goto`**). The detection contract demands click-driven navigation so dynamically-rewritten hrefs (e.g., JS-driven A/B redirects) get observed correctly.
   - Wait for `networkidle` + 500ms (same settle window as `render-review-detection.md` Section 2).
   - Call `classifyCurrentPage(context, page, {requested_route: step.source_route, expected_destination: step.destination_route, is_first_page})` (per Section 6.3 — does NOT call `page.goto`, classifies the already-navigated page).
   - Receive `{review_method, review_evidence}` from Section 3 classification.
   - Record the per-step result with: `step_index`, `source_route`, `expected_destination` (= step.destination_route), `review_method`, `review_evidence`, plus the status derived from the Render Review Policy Table in `.claude/agents/ux-journeyer.md`:
     - `rendered-authed` / `rendered-demo` (final == expected) → `pass`
     - `source-only` with `final_url ∈ AUTH_PATHS` → `dead-end-auth`
     - `source-only` with `final_url ∉ AUTH_PATHS` → `dead-end`
     - `unknown` → `error`
   - Append the result to the `per_step_reviews` array for the trace.
7. Stops when reaching the value moment OR after 10 steps (whichever first).
8. Always close the BrowserContext at the end (the same context is reused across all steps for session continuity).

Save the trace as a structured array for the report. The `per_step_reviews` array goes directly into the trace file (see `.claude/agents/ux-journeyer.md` Trace Output).

> **Why click and not `page.goto`?** `page.goto` would navigate to the static `href`, missing JavaScript-driven rewrites, conditional redirects, or programmatic navigation. ux-journeyer's job is to verify the user's actual click leads where it should — that's only observable via real click + post-click classification. `classifyCurrentPage` exists precisely to support this caller pattern (it does the URL comparison without re-navigating).

### 6. Check Flow Quality

For each page visited during the golden path navigation, check:

- **Single clear forward CTA** — no ambiguous dual-CTA competing for attention
- **Empty states have guidance + CTA** — not bare "No data found" messages
- **Error states have recovery path** — not dead-end error pages
- **Post-auth redirect lands correctly** — user continues the journey, not dumped on a generic page
- **Navigation shows current location** — active state on nav items

Record each check result per page.

### 7. Count & Judge

- Count total clicks from landing to value moment
- Target: **3 clicks or fewer** (unless the golden path specifies a different target)
- List all dead ends, missing transitions, and unclear CTAs found

### 8. Fix Issues

For issues found in steps 5-7:

- Fix redirect paths that send users to the wrong page
- Add empty-state CTAs where missing
- Fix navigation active states
- Clarify ambiguous dual-CTA sections (make one primary, one secondary)
- Run `npm run build` after fixes (must pass)

> **Syntax safety**: After each edit, visually verify JSX tag matching before running build. Common failure: inserting a new element without updating closing tags. If build fails with JSX syntax errors, revert your last edit and try a simpler fix.
>
> **Fix budget**: Fix at most 2 dead ends. If more remain, record them as `unresolved_dead_ends` in the trace and set verdict to `"partial"`.

### 8b. Re-navigate After Fixes

After fixing issues, re-navigate the golden path once to confirm fixes work:

1. Re-use the running server (still on port 3098)
2. Write a Playwright script that re-traces the golden path from `/` to value moment
3. For each previously-failed step, verify it now passes
4. For each dead end that was fixed, verify forward navigation is possible
5. Update the golden path trace with post-fix results

If remaining turns < 8, skip re-navigation and write the trace immediately with current metrics.

### 9. Cleanup

```bash
kill %1 2>/dev/null || true
```

Remove any temp files created during navigation.

### 10. Compute Trace Metrics

Before writing the trace file, compute these metrics from your journey:

- **`clicks_to_value`**: total clicks from the landing page to the value moment (the step where the user first experiences core product value). If the value moment was never reached, use the total clicks navigated.
- **`dead_ends`**: number of pages where no forward navigation was possible (no CTA, broken link, or error page). Intentional fake-door pages count as dead ends in the trace — the lead distinguishes fake-doors from real failures.
- **`golden_path_steps`**: total number of golden path steps navigated (including failed steps). This is the denominator for coverage.
- **`coverage_pct`**: percentage of golden_path steps from experiment.yaml that were successfully completed, as an integer 0-100. Formula: `(successful_steps / total_golden_path_steps) * 100`, rounded down.
- **`fixes_applied`**: total number of fixes applied (redirect fixes, empty-state CTAs added, navigation fixes, etc.). Use `0` if no fixes were needed.
- **`unresolved_dead_ends`**: count of real (non-fake-door) dead ends that remained after fixes. Intentional fake-door pages are excluded — only real navigation failures count. Use `0` if all dead ends were fixed or all are intentional.

These metrics are written into the trace JSON (see agent definition for the trace command).
