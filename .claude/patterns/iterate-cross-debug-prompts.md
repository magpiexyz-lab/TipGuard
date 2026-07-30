# Iterate Cross — Debug Prompt Templates

These prompt templates are referenced by `state-x4-rank-recommend.md` Section C: for each NO_DATA / GA_NO_PH_TRACKING row, the lead surfaces the matching section in the conversation. Each section heading **must** be the verdict name verbatim so the lead can match by `## <VERDICT>`.

Owners copy-paste these into Claude Code from their MVP repo to diagnose the verdict.

---

## NO_DATA

The cross-MVP discovery query found this MVP via gclid traffic on a related domain, but PostHog has no events under its `project_name` (or extracted host). Two possibilities: (a) the MVP isn't deployed at the URL the campaign is pointing to, or (b) the deployed app doesn't have the PostHog snippet loading (or `project_name` global property isn't being set).

Verify in order:

1. Open the deployed production URL in a browser. Does the page load? If no — the MVP isn't deployed; redeploy.
2. In DevTools Network tab, filter for `posthog`. Does any request go out? If no — `posthog.init()` isn't running. Check `NEXT_PUBLIC_POSTHOG_KEY` is set in Vercel production env, and verify `app/layout.tsx` (or equivalent) imports + initializes PostHog.
3. In DevTools Console, run `window.posthog`. If `undefined` — same as step 2.
4. Make a test PostHog event: open Console, run `posthog.capture('test_from_console', { source: 'manual' })`. Then check the PostHog dashboard live events feed. If the event doesn't appear within 30 seconds — the API key is wrong or the project ID is wrong.
5. Verify the PostHog event has `project_name` set as a global property. If not, the cross-MVP query won't group this MVP under its expected name. Compare against `.claude/stacks/analytics/posthog.md` for the expected init pattern.
6. When you append `?gclid=test123` to the URL and reload, does the frontend capture `gclid` into the PostHog event properties for the `$pageview` event? Does `gclid` persist across the session via `$session_entry_gclid`?

   > **Test-gclid convention — use length ≤ 40 OR a prefix that is NOT in `{Cj, EAI, CIa}`.** `/iterate --cross` filters paid traffic by `length > 40 AND prefix in {Cj, EAI, CIa}` — real Google Ads gclids match both. Short sentinels like `test123` work (fail length); readable strings like `MANUAL_VERIFY_CHECK_2026_ANYTHING_LONG_OK` work (fail prefix). Real Google Ads gclids start with `Cj0KCQ`, `CjwKCAjw`, or `EAIaIQob` and are 60-120 chars (base64-url). **Do not use a test gclid that BOTH exceeds 40 chars AND starts with `Cj` / `EAI` / `CIa`** — that would bypass the filter and silently inflate cross-MVP signup/visitor counts. The filter is the single source of truth in `.claude/scripts/lib/gclid_filter.py` (`PAID_GCLID_FILTER`), enforced via state-x0/x1/x2/c2 of the iterate skill.

Report which step failed and what the root cause is. Then propose the minimum fix — don't apply it yet, I'll review first.

---

## GA_NO_PH_TRACKING

This MVP appears in Google Ads with paid clicks but PostHog has **zero presence** for it — neither canonical events (under any `project_name`) nor orphan events (gclid events with NULL `project_name` whose host matches this MVP). The operator is paying for a deploy that cannot be measured at all.

The campaign's Final URL is visible in the Google Ads UI under "Ads" → click the ad → "Final URL". Open that URL in a browser and verify in order:

1. Does the page load (200 OK) and render real content? If 404/5xx or empty — the deploy is broken; ship the fix or pause the campaign.
2. In DevTools Network tab, filter for `posthog`. Does ANY request go out within 5 seconds of page load? If no — `analytics.ts` is not imported on this route. The most common cause: the ad's Final URL points to a deep path (e.g. `/repair/adhd-couples`) but `app/layout.tsx`'s analytics import only runs from the root layout — verify the route is actually wrapped by the root layout, not bypassing via a route group.
3. In DevTools Console, run `window.posthog?.config?.project_name` (or inspect a captured event's `properties.project_name`). What does it print?
   - `undefined` → analytics.ts isn't loading. Check the import chain back from this page.
   - A string DIFFERENT from what the operator expects (e.g. PostHog has `myproduct` but `experiment.yaml` says `my-product` kebab-case) → `PROJECT_NAME` constant in `src/lib/analytics.ts` doesn't match `experiment.yaml.name`. Fix the constant. Per /bootstrap state-3 these MUST be kebab-case (`[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`).
   - The expected name → events are firing under the right project_name. Then the issue is that `/iterate --cross` discovery didn't pick up this MVP because the gclid query filter excluded its traffic. Check the test-gclid convention in the NO_DATA section above — operator manual-test gclids (length ≤ 40 OR prefix not in `Cj/EAI/CIa`) are filtered out by design.
4. Append `?gclid=test123` to the URL, reload, and check that PostHog captures the event with `properties.project_name` set. If the event arrives but `project_name` is missing, the analytics layer isn't auto-attaching it — verify `src/lib/analytics.ts` `enriched` object includes `project_name: PROJECT_NAME`.

Report which step failed and the minimum fix. Don't apply it yet — operator reviews first. Once fixed, run `/iterate --cross` again; this MVP should move from GA_NO_PH_TRACKING into a normal verdict (GO / NO_GO / INSUFFICIENT_DATA based on DB-first signup conversion).
