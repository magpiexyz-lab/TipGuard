# STATE 3: IMPLEMENT

**PRECONDITIONS:**
- Analytics validated (STATE 2 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: React FeedbackWidget component | service/cli: inline HTML feedback widget

### 3a: UTM capture on landing page

- Read the analytics stack file (`.claude/stacks/analytics/<value>.md`) to understand the tracking API
- Ensure `visit_landing` event captures `utm_source`, `utm_medium`, `utm_campaign` from URL params
- experiment/EVENTS.yaml has these as optional properties on `visit_landing` — the surface must parse them from URL params and pass them to the tracking call
- **Idempotent**: If UTM capture already exists in the landing page file (grep for `utm_source`), skip this step
- **web-app**: parse from `window.location.search` in the landing page component
- **service (co-located)**: parse from the request URL in the root route handler and embed in the HTML response's tracking script
- **cli (detached) or service (detached)**: add an inline `<script>` in `site/index.html` that parses `window.location.search` and fires the tracking call via the analytics snippet

- When experiment.yaml has `variants`, also capture `utm_content` from URL params alongside UTM params. This maps to the variant slug and enables per-variant attribution in analytics (e.g., filter `visit_landing` by `utm_content = "speed"` to see paid traffic for the speed variant).

### 3a.5: UTM capture on sitelink destination pages

Read `golden_path` from `experiment/experiment.yaml`. For each non-landing page in the golden_path that has a user-facing route:

- **web-app**: Check if the page's route file (e.g., `src/app/{page}/page.tsx`) captures UTM parameters. If not, wire UTM + click ID capture using the same pattern as step 3a (parse `utm_source`, `utm_medium`, `utm_campaign`, `utm_content` from URL params and include in the page's analytics event).
- **Idempotent**: If the page already captures `utm_source` (grep the page file), skip it.
- **Anchor sitelinks**: No action needed — anchor sitelinks land on the same landing page, which already has UTM capture from step 3a. The `utm_content` parameter distinguishes sitelink traffic.

> **Note:** This step runs before ads.yaml is generated (state 3 precedes state 4). It wires UTM capture for all golden_path pages preemptively, not just sitelink-specific ones. The sitelink pages are a subset — this ensures any page a sitelink might point to is ready for attribution tracking.

### 3b: Add click ID capture

- Read the selected channel's stack file "Click ID" section to get the parameter name (e.g., `gclid` for google-ads, `twclid` for twitter, `rdt_cid` for reddit)
- Capture the channel's click ID from URL params on landing page load alongside UTM params
- Store the value as the generic `click_id` property in the `visit_landing` analytics event (experiment/EVENTS.yaml defines `click_id` as an optional property)
- Also capture `gclid` separately for backward compatibility (it remains an optional property on `visit_landing`)
- This enables conversion attribution in the channel's ad platform
- **Idempotent**: If click ID capture already exists (grep for the channel's click ID param name), skip this step

### 3c: Feedback widget (post-activation)

Add `feedback_submitted` to experiment/EVENTS.yaml `events` map:

```yaml
  feedback_submitted:
    funnel_stage: activate
    trigger: User submits post-activation feedback widget
    properties:
      source:
        type: string
        required: false
        description: "How the user found the product (e.g., google, friend, social)"
      feedback:
        type: string
        required: false
        description: Free-text feedback from the user
      activation_action:
        type: string
        required: true
        description: What activation action preceded this (from experiment.yaml thesis)
```

**web-app**: Add a `FeedbackWidget` component at `src/components/feedback-widget.tsx`:

- Uses shadcn `Dialog`, `Button`, `Label`, `Textarea`, and `Select` components (read the UI stack file for import conventions)
- Appears after the user completes the activation action (triggered via prop callback)
- Stores "shown" flag in localStorage to show only once per user
- Fires `feedback_submitted` event via `track()` from the analytics library (see analytics stack file for the import path and `track()` usage)
- Fields: "How did you find us?" (select: Google Search, Social Media, Friend/Referral, Other), "Any feedback?" (textarea)
- Non-blocking: user can dismiss without submitting

**service (co-located)**: Add a feedback form section to the root route's HTML response. Use inline HTML form + `<script>` that fires `feedback_submitted` via the analytics snippet. Style with inline CSS — no React/shadcn dependency.

**cli (detached) or service (detached)**: Add a feedback form section to `site/index.html`. Use inline HTML form + `<script>` that fires `feedback_submitted` via the analytics snippet. Style with inline CSS.

**Idempotent**: If the feedback widget already exists (web-app: glob `src/components/*feedback*`; service/cli: grep for `feedback_submitted` in the surface file), skip this step.

### 3d: project_name fix

- Read `project_name_mismatch` from `.runs/distribute-preconditions.json`
- If `true`: read `name` from experiment.yaml, replace `PROJECT_NAME` constant in both `src/lib/analytics.ts` and `src/lib/analytics-server.ts` with the correct value
- If `false` or field is absent: skip

### 3e: Ad-readiness verification

Post-implementation checks. Read `channel` from `.runs/distribute-preconditions.json`.

**google-ads: BLOCKING. Other channels: skip.**

Checks:

**gclid capture:**
```bash
grep -r 'gclid' src/ site/ 2>/dev/null | grep -v node_modules | grep -v '.yaml' | grep -v '.md'
```
- PASS: at least one match in `.ts`/`.tsx`/`.js`/`.jsx` that reads `gclid` from URL params
- FAIL: landing page does not capture Google Click ID

**Unified funnel_stage:**
Read `experiment/EVENTS.yaml`. For every event in the `events` map, verify `funnel_stage` exists and is one of: `reach`, `demand`, `activate`, `monetize`, `retain`.
- PASS: all events have valid `funnel_stage`
- FAIL: list the event names missing `funnel_stage`

**Click ID in reach event properties:**
Read `experiment/EVENTS.yaml`. Find events where `funnel_stage` is `reach`. Verify at least one has `gclid` or `click_id` in its `properties`.
- PASS: reach event defines gclid/click_id
- FAIL: no reach event has gclid/click_id property

**UTM capture:**
```bash
grep -r 'utm_source' src/ site/ 2>/dev/null | grep -v node_modules | grep -v '.yaml' | grep -v '.md'
```
- PASS: at least one match that reads `utm_source` from URL params
- FAIL: landing page does not capture UTM parameters

**Conversion event exists:**
Read `experiment/EVENTS.yaml`. Check that at least one event has `funnel_stage: demand` or `funnel_stage: activate`.
- PASS: at least one demand/activate event exists
- FAIL (WARNING only, non-blocking): "No conversion events in EVENTS.yaml. The ad platform needs a demand or activate stage event to track conversions."

**If any of the first 4 checks fail after 3a-3d implementation:**
- This indicates a build or logic bug in the implementation
- Fix the issue and retry the failing checks (max 2 attempts)
- If still failing after retries, STOP with error: "Ad-readiness check failed after implementation and 2 fix attempts. Manual investigation required: [list failed checks]."

**If only conversion event check fails (and first 4 pass):** WARNING only, continue.

### Completion checkpoint

Write `.runs/distribute-impl-step-check.json`:
```bash
PAYLOAD=$(python3 -c "
import json, os, subprocess, sys
steps = []
utm = subprocess.run(['grep','-rq','utm_source','src/','site/'], capture_output=True)
utm_wired = utm.returncode == 0
if utm_wired:
    steps.append('3a')
click = subprocess.run(['grep','-rq','gclid','src/','site/'], capture_output=True)
click_id_wired = click.returncode == 0
if click_id_wired:
    steps.append('3b')
fb = False
if os.path.exists('experiment/EVENTS.yaml'):
    fb = 'feedback_submitted' in open('experiment/EVENTS.yaml').read()
if fb:
    steps.append('3c')
steps.append('3d')  # project_name fix (no-op if mismatch was false)
steps.append('3e')  # ad-readiness checks ran
print(f'SELF-CHECK: wrote .runs/distribute-impl-step-check.json with {len(steps)} steps', file=sys.stderr)
print(json.dumps({
    'steps_completed': steps,
    'key_outputs': {
        'utm_wired': utm_wired,
        'click_id_wired': click_id_wired,
        'feedback_widget_added': fb,
        'ad_readiness_passed': len(steps) >= 5
    }
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/distribute-impl-step-check.json \
  --payload "$PAYLOAD" \
  --skill distribute
```

This checkpoint is mandatory. Do not skip it.

**POSTCONDITIONS:**
- UTM capture wired on landing page (utm_source, utm_medium, utm_campaign parsed from URL params)
- Click ID capture wired on landing page (channel-specific click ID + gclid for backward compatibility)
- `feedback_submitted` event added to experiment/EVENTS.yaml
- Feedback widget implemented per archetype (web-app: React component, service/cli: inline HTML)
- project_name fixed if mismatch was recorded in preconditions
- Ad-readiness checks passed (google-ads: blocking; other channels: skipped)
- `.runs/distribute-impl-step-check.json` exists with at least 1 completed step

**VERIFY:**
```bash
(grep -rq 'utm_source' src/app src/components 2>/dev/null || grep -q 'utm_source' site/index.html 2>/dev/null) && python3 -c "import json; d=json.load(open('.runs/distribute-impl-step-check.json')); assert len(d.get('steps_completed',[])) > 0" && grep -q 'feedback_submitted' experiment/EVENTS.yaml
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh distribute 3
```

**NEXT:** Read [state-3a-verify-embed.md](state-3a-verify-embed.md) to continue.
