# STATE c2: AUTO_FIX

**PRECONDITIONS:**
- Health check complete (STATE c1 POSTCONDITIONS met)
- `.runs/iterate-check-health.json` exists

**ACTIONS:**

### Check for issues

Read `.runs/iterate-check-health.json`. If `issues` array is empty:
> "Campaign healthy -- no issues detected. Skipping auto-fix."

Write an empty fixes file and proceed to STATE c3:
```bash
PAYLOAD=$(python3 -c "
import json
fixes = {'campaign_name': '<name>', 'fixed_at': '<ISO 8601>', 'issues_found': 0, 'fixes_applied': 0, 'fixes_recommended': 0, 'details': []}
print(json.dumps(fixes))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-check-fixes.json \
  --payload "$PAYLOAD" \
  --skill iterate
```

### Process issues by type

Read `campaign_age_days` from `.runs/iterate-check-context.json`. For each issue, apply the fix:

---

#### Issue: `zero_impressions`

**If campaign age < 48 hours:**
- Navigate to campaign **Keywords** tab via Chrome MCP
- Check each keyword's **Max CPC** vs the **Top of page bid (high range)** estimate shown by Google
- Read `guardrails.max_cpc_cents` from `experiment/ads.yaml`
- If Max CPC is below the suggested high range, increase it to `min(top-of-page high range, guardrails.max_cpc_cents)`
- If the ceiling binds, record that the suggested high range exceeded the affordability ceiling and the bid was capped
- Via Chrome MCP: click the keyword's bid, update the value, save
- Record: "Raised max CPC on {N} keywords toward suggested high range, capped at guardrails.max_cpc_cents where needed"

**If campaign age >= 48 hours and < 72 hours:**
- Switch all Phrase Match keywords to Broad Match:
  - Navigate to Keywords tab, edit match type for each keyword
- Add 20 additional negative keywords relevant to the experiment's domain:
  - Read `experiment/experiment.yaml` for context (what the product does, who it's for)
  - Generate 20 domain-specific negative keywords that filter out irrelevant intent (informational queries, competitor names, unrelated verticals)
  - Add them at the campaign level via Chrome MCP: Keywords > Negative keywords > Add
- Record: "Switched {N} keywords to Broad Match, added 20 negative keywords"

**If campaign age >= 72 hours:**
- Mark the campaign as **NO-GO**: the experiment hypothesis is not attracting search interest
- Pause the campaign via Chrome MCP: Campaign Settings > Status > Paused
- Notify the user:
  > "Campaign has 0 impressions after 72+ hours. This is a NO-GO signal -- the target keywords have no search volume or bids are not competitive. Campaign has been paused. Consider: (1) Run `/iterate` for a full funnel analysis and KILL/PIVOT decision. (2) Run `/retro` to document learnings."
- Record: "NO-GO: paused campaign after 72h with 0 impressions"

---

#### Issue: `disapproved`

1. Navigate to the campaign's **Ads** tab via Chrome MCP
2. Click on the disapproved ad to view the policy violation details
3. Read the disapproval reason (e.g., "Misleading claim", "Trademark violation", "Destination mismatch")
4. AI-rewrite the ad copy to comply with the policy:
   - Keep the same RSA structure (5+ headlines, 2+ descriptions)
   - Address the specific policy violation
   - Maintain the experiment's value proposition from ads.yaml
   - Follow headline length limits (3-30 chars) and description limits (up to 90 chars)
5. Create a new ad with the rewritten copy via Chrome MCP:
   - Navigate to Ads > click "+" to create new ad
   - Fill in the rewritten headlines and descriptions
   - Save the new ad
6. Notify the user:
   > "Ad was disapproved for [{reason}]. Created a replacement ad with compliant copy. Please check ad approval status in 24-48h. Original ad left in place for reference -- you can remove it manually after the new one is approved."
7. Record: "Ad disapproved for {reason}. Created replacement ad. Review in 24-48h."

---

#### Issue: `sitelink_disapproved`

1. Navigate to the campaign's **Ads & assets** → **Assets** tab via Chrome MCP
2. Click on the disapproved sitelink to view the disapproval reason
3. Read the disapproval reason (e.g., "Destination not working", "Misleading content", "Policy violation")
4. AI-rewrite the sitelink to comply:
   - If destination URL is broken: check if the page exists at the `final_url`. If not, replace with an anchor sitelink on the landing page (fallback to a working destination)
   - If copy violates policy: rewrite `link_text`/descriptions following messaging.md Section F rules while addressing the specific violation
   - Preserve UTM parameters in the new `final_url`
   - Respect character limits: link_text ≤ 25, descriptions ≤ 35
5. Create a replacement sitelink via Chrome MCP:
   - Click "+" → "Sitelink" in the Assets tab
   - Enter the rewritten link_text, description_1, description_2, final_url
   - Save
6. Leave the original disapproved sitelink in place for reference (user can remove manually)
7. Notify the user:
   > "Sitelink '{link_text}' was disapproved for [{reason}]. Created a replacement sitelink with compliant copy. Review approval status in 24-48h."
8. Record: "Sitelink disapproved for {reason}. Created replacement. Original left for reference."

---

#### Issue: `wasted_clicks`

1. Read the problematic search terms from the health check (terms with cost > $1 AND CTR < 1%)
2. Present the list to the user:
   > "Found {N} irrelevant search terms consuming budget:"
   > | Search Term | Cost | Clicks | CTR |
   > |------------|------|--------|-----|
   > | {term} | ${cost} | {clicks} | {ctr}% |
3. Add all identified terms as **negative keywords** at the campaign level:
   - Via Chrome MCP: Keywords > Negative keywords > click "+" > add all terms
   - Use Exact Match for the negative keywords (bracket syntax)
4. Record: "Added {N} negative keywords: [{term1}], [{term2}], ..."

---

#### Issue: `campaign_paused`

Read `phase` from `.runs/iterate-check-context.json`. If `phase` is `1`, follow the Phase 1 protocol below. If `phase` is `2`, `null`, or absent, follow the "NOT Phase 1" branch.

Before any Phase 1 unpause, read the actual status from the health issue. Continue only when the actual status is exactly **Paused**. If the status is **Ended** or any other non-paused status, do NOT unpause; record: "Campaign status is {status}; skipping campaign_paused auto-fix. Ended campaigns require the campaign_ended / stop_extend_recommended path."

**If Phase 1 protocol (phase == 1):**

Check ad approval status first:
1. Navigate to campaign **Ads** tab via Chrome MCP
2. Check if ALL ads have status "Approved" (not "Under review", "Disapproved", etc.)

**If all ads approved AND campaign age >= 48 hours:**
- Unpause the campaign via Chrome MCP: Campaign Settings > Status > Enabled
- Notify the user:
  > "All ads approved. Campaign unpaused and now active. Monitor daily with `/iterate --check` until a stop condition fires."
- Record: "Campaign unpaused -- all ads approved after {age} hours"

**If some ads still disapproved or in review:**
- Do NOT unpause
- Notify the user:
  > "Campaign still paused -- {N} ad(s) are still {status}. Re-run `/iterate --check` tomorrow. Most ads are approved within 24-48 hours. If still disapproved after 48 hours, review and adjust ad copy in Google Ads, or contact platform support."
- Record: "Campaign remains paused -- {N} ads not yet approved"

**If campaign age < 48 hours:**
- This is expected during Phase 1 Day -2/Day -1 protocol
- Record: "Campaign paused (Phase 1 protocol, age {age}h < 48h) -- no action needed"

**If NOT Phase 1 (user-initiated pause or unknown):**
- Do NOT auto-unpause — the user may have paused intentionally
- Record: "Campaign paused (not Phase 1 protocol) -- skipping auto-fix. Resume manually in Google Ads if intended."

---

#### Issue: `stop_clicks_target_met`

No Chrome MCP UI action. Record `action_taken: "recommended"` with: "Paid clicks reached `budget.click_target`; pause the campaign if it is still serving, then report to your Team Lead — the lead runs `/iterate --cross` for the cross-MVP verdict." Never pause, unpause, or edit the End date from this handler.

---

#### Issue: `stop_budget_cap_reached`

No Chrome MCP UI action. Record `action_taken: "recommended"` with: "Spend reached `budget.total_budget_cents`; pause the campaign if it is still serving. If clicks are below `budget.click_target`, treat this as an affordability signal and consider NO_GO." Never pause, unpause, or edit the End date from this handler.

---

#### Issues: `campaign_ended` / `stop_extend_recommended`

No Chrome MCP UI action. Record `action_taken: "recommended"` with: "Campaign End date was reached before clicks or cap fired; extend the End date by `(cap - spent) / daily_budget` days, or stop consciously." Never pause, unpause, or edit the End date from this handler.

---

#### Issue: `tracking_degraded`

No Chrome MCP UI action. Record `action_taken: "recommended"` with: "App-side tracking appears degraded. Re-run `/ads-ready` against the current deploy and fix before trusting any verdict. If the degraded signal persists after `/ads-ready` passes, report it to your Team Lead. Do NOT pause the campaign for this." Never pause, unpause, edit bids, edit budgets, or edit the End date from this handler.

---

#### Issue: `tracking_utm_missing`

No Chrome MCP UI action. Record `action_taken: "recommended"` with: "The campaign is spending and paid traffic is reaching PostHog, but none is tagged with this campaign's `utm_campaign` — the Google Ads Final URL is missing the `utm_campaign` suffix (NOT an app-side bug; `/ads-ready` cannot catch it). Fix per the Phase 2 playbook §5 step 6: set the campaign-level Final URL suffix to `utm_source=google&utm_medium=cpc&utm_campaign=<campaign_name>`. Until fixed, this campaign's spend is invisible to the Phase 2 verdict. If this persists on the next `/iterate --check` while spend continues, pause the campaign until the Final URL is fixed." Never pause, unpause, edit bids, edit budgets, or edit the End date from this handler (pausing is the operator's call).

---

#### Issue: `monitoring_unavailable`

No Chrome MCP UI action. Record `action_taken: "recommended"` with: "The daily tracking monitor could not run. Fix the PostHog personal API key or project resolution so `/iterate --check` can restore the tracking pulse." Never pause, unpause, edit bids, edit budgets, or edit the End date from this handler.

---

#### Issue: `budget_anomaly`

**If campaign age <= 2 days AND spend > 50% of total budget:**
- This is a critical overspend -- the campaign will exhaust budget before the experiment window ends
- Pause the campaign via Chrome MCP: Campaign Settings > Status > Paused
- Notify the user:
  > "Budget anomaly: {spend_pct}% of total budget consumed in {age} days. Campaign paused to prevent premature budget exhaustion. Recommended: (1) Check if max CPC is too high relative to keyword competition. (2) Review search terms for broad/irrelevant traffic driving up costs. (3) Resume campaign with adjusted bids after review."
- Record: "Paused campaign -- {spend_pct}% budget consumed in {age} days"

**If underspend (actual spend < 30% of expected):**
- This is informational -- underspend usually means low impression volume
- If `zero_impressions` is also flagged, that issue handler covers the fix
- If impressions exist but spend is low, it may indicate low bid competitiveness
- Record: "Underspend detected -- {spend_pct}% of expected. Check bid competitiveness."

---

### Write fixes artifact

```bash
PAYLOAD=$(python3 -c "
import json
fixes = {
    'campaign_name': '<name>',
    'fixed_at': '<ISO 8601>',
    'issues_found': <N>,
    'fixes_applied': <N>,
    'fixes_recommended': <N>,
    'details': [
        {
            'issue_type': '<type>',
            'diagnosis': '<what was found>',
            'action_taken': '<applied|recommended|skipped>',
            'description': '<what was done or recommended>'
        }
    ]
}
print(json.dumps(fixes))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-check-fixes.json \
  --payload "$PAYLOAD" \
  --skill iterate
```

Replace all placeholder values with actual data from the fix actions performed.

**POSTCONDITIONS:**
- Each issue from health report processed (fixed or recommendation provided)
- `.runs/iterate-check-fixes.json` exists
- User informed of all findings and actions taken

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/iterate-check-fixes.json')); assert d.get('campaign_name'), 'campaign_name empty'; assert d.get('fixed_at'), 'fixed_at empty'; assert isinstance(d.get('issues_found'), int), 'issues_found not int'; assert isinstance(d.get('fixes_applied'), int), 'fixes_applied not int'; assert isinstance(d.get('details'), list), 'details not a list'; assert d['fixes_applied'] <= d['issues_found'], 'fixes_applied > issues_found'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-check c2
```

**NEXT:** Read [state-c3-report.md](state-c3-report.md) to continue.
