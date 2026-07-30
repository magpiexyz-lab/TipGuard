# STATE c1: CHECK_HEALTH

**PRECONDITIONS:**
- Ads context read (STATE c0 POSTCONDITIONS met)
- Chrome MCP tools available

**ACTIONS:**

### Open Google Ads

1. Use Chrome MCP to navigate to `https://ads.google.com`
2. Verify login state -- if a login prompt is shown, tell the user:
   > "Please log into Google Ads in Chrome, then re-run `/iterate --check`."
   > STOP.
3. If the account uses an MCC (Manager Account), navigate to the correct sub-account using `account_id` from ads.yaml (if present) or `campaign_id`
4. Navigate to the campaign matching `campaign_name` from the context

### Health checks

Perform the following health checks via Chrome MCP (7 standard + conditional Check 8 when sitelinks exist). For each, navigate to the relevant section and read the UI:

#### Check 1: Ad approval status
- Navigate to the campaign's **Ads** tab
- Read the **Status** column for each ad
- Healthy: all ads show "Eligible" or "Approved"
- Issue type: `disapproved` -- record which ads are disapproved and their status text

#### Check 2: Impression count
- Navigate to the campaign **Overview** or check the **Impressions** column
- Read total impressions since campaign start
- Healthy: impressions > 0
- Issue type: `zero_impressions` -- record the exact impression count (0 or very low)

#### Check 3: Campaign status
- Check the campaign **Status** (visible on the campaign list or Settings page)
- Healthy: "Active" or "Enabled"
- Issue type: `campaign_paused` -- record the actual status only when status is "Paused"
- Issue type: `campaign_ended` -- record the actual status when status is "Ended"; do not emit `campaign_paused` for an ended campaign
- Note: `campaign_paused` is informational only -- if the user paused it intentionally, skip auto-fix

#### Check 4: Search terms report
- Navigate to **Keywords > Search terms**
- Look for irrelevant search terms that are consuming budget:
  - Terms with cost > $1 AND CTR < 1%
  - Terms clearly unrelated to the experiment (e.g., "free", "download", "tutorial" for a SaaS product)
- Healthy: no obviously wasted search terms
- Issue type: `wasted_clicks` -- record the problematic search terms with their cost and CTR

#### Check 5: Budget consumption rate
- Read total spend so far and compare against expected spend for the campaign age
  - Expected daily spend = `budget.daily_budget_cents` from ads.yaml
  - Expected total spend at current age = `min(expected daily spend x campaign_age_days, budget.total_budget_cents)`
  - Actual spend from the campaign dashboard
- Healthy: actual spend is between 30% and 150% of expected spend
- Issue type: `budget_anomaly` -- record actual vs expected spend and the anomaly direction (underspend/overspend)

#### Check 6: Stop-rule status

Read `budget.click_target` (fallback 100), `budget.total_budget_cents`, `budget.daily_budget_cents`, campaign status, total clicks, and total spend.

- Healthy: clicks < click target, spend < total cap, and the campaign has not ended with budget headroom.
- Issue type: `stop_clicks_target_met` when `clicks >= click_target`; recommendation: pause the campaign and report to the Team Lead (the lead runs `/iterate --cross` for the cross-MVP verdict).
- Issue type: `stop_budget_cap_reached` when `spend_cents >= total_budget_cents`; recommendation: pause the campaign. If clicks are below target, treat it as an affordability signal and consider NO_GO.
- Issue type: `stop_extend_recommended` when campaign status is "Ended" AND clicks < target AND spend < cap; recommendation: extend the End date by `(cap - spent) / daily_budget` days, or stop consciously.
- Detection and recommendation only: do not auto-pause or auto-extend from this check. Existing protective auto-pauses in c2 stay scoped to their established issue types.

#### Check 7: Tracking pulse

Before overwriting `.runs/iterate-check-health.json`, read the existing file if present. It is eligible for the 24h-delta signal only when it has the same `campaign_id` and its `checked_at` timestamp is between 4 and 48 hours old.

Run:
```bash
python3 .claude/scripts/lib/tracking_pulse.py --campaign-name "<campaign_name from context>" --since "<campaign_created_at from context>"
```

If `campaign_created_at` is null or absent, omit `--since`; the script uses a 90-day campaign window and returns `created_at_missing: true`.

If the script exits 2, parse stdout and record issue type `monitoring_unavailable` with severity informational, no action, and the `skip_reason`. This is a visible skip, never a healthy pass.

If the script exits 0, parse stdout and evaluate. **The campaign-utm-invisible signal takes precedence** — it is a specific Final-URL diagnosis, not generic degradation, so when it applies do NOT also emit `tracking_degraded`:

- **Campaign-utm invisible → `tracking_utm_missing`:** when `ph_gclid_visitors_campaign == 0` AND `ph_gclid_visitors_project_window > 0` AND total GA clicks `>= 10`. Paid traffic IS reaching PostHog, but none of it carries this campaign's `utm_campaign` — i.e. the Google Ads Final URL is missing the `utm_campaign` suffix (a genuine app-side capture failure would instead show `ph_gclid_visitors_project_window == 0`). Record issue type `tracking_utm_missing` with recommendation: "The campaign is getting clicks and paid traffic IS reaching PostHog, but 0 visitors are tagged with `{campaign_name}`. The Google Ads Final URL is missing the `utm_campaign` suffix — this is NOT an app-side bug, and `/ads-ready` cannot catch it. Fix per the Phase 2 playbook §5 step 6: set the campaign-level Final URL suffix to `utm_source=google&utm_medium=cpc&utm_campaign={campaign_name}`. Until fixed, this campaign's spend is invisible to the Phase 2 verdict. If the signal persists on the next run while the campaign keeps spending, pause it until the Final URL is fixed."

- **Capture-rate degraded → `tracking_degraded`** (only when the campaign-utm-invisible case does NOT apply — i.e. some paid traffic IS tagged but the capture rate is low, signalling genuine app-side loss):
  - 24h delta: `ga_clicks_24h = today's UI total clicks - previous run's health-json clicks`. Skip this signal unless the previous file is eligible. Flag when `ga_clicks_24h >= 10` AND `ph_gclid_visitors_24h / ga_clicks_24h < 0.5`.
  - Campaign lifetime: flag when total GA clicks `>= 30` AND `ph_gclid_visitors_campaign / total ga_clicks < 0.5`.
  Record issue type `tracking_degraded` with recommendation: "App-side tracking appears degraded (capture rate {x}%, normal >= ~70% net of ad blockers). Re-run `/ads-ready` against the current deploy and fix before trusting any verdict. Do NOT pause the campaign for this."

Add this block to the health json:
```json
"tracking_pulse": {
  "ph_24h": 0,
  "ph_campaign": 0,
  "ph_project_window": 0,
  "ga_clicks_24h": null,
  "capture_rate_24h": null,
  "capture_rate_lifetime": null,
  "evaluated": false,
  "skip_reason": null,
  "created_at_missing": false
}
```

Threshold rationale: 0.5 leaves margin under normal ad-blocker loss (~20-30%); the click-count guards prevent small-sample noise.

#### Check 8: Sitelink approval status

**Skip condition:** Read `experiment/ads.yaml`. If `sitelinks` is missing, null, or an empty array, skip this check entirely. Log: "No sitelinks in ads.yaml -- skipping sitelink health check."

- Navigate to the campaign's **Ads & assets** → **Assets** tab (or **Extensions** tab in older UI versions)
- Filter or scroll to Sitelink type assets
- Read the **Status** column for each sitelink
- Healthy: all sitelinks show "Eligible", "Approved", or "Under review" (under review is expected for the first 24-48 hours)
- Issue type: `sitelink_disapproved` -- record which sitelinks are disapproved and their status/reason text

### Collect campaign metrics

While checking health, also record these metrics for the report:
- Total impressions
- Total clicks
- CTR (click-through rate)
- Average CPC
- Total spend
- Conversions (if shown)

### Write health report

```bash
PAYLOAD=$(python3 -c "
import json
health = {
    'campaign_name': '<name>',
    'campaign_id': '<id>',
    'checked_at': '<ISO 8601>',
    'metrics': {
        'impressions': 0,
        'clicks': 0,
        'ctr_pct': 0.0,
        'avg_cpc_cents': 0,
        'spend_cents': 0,
        'conversions': 0
    },
    'stop_rule': {
        'click_target': 100,
        'clicks': 0,
        'total_budget_cents': 25000,
        'spend_cents': 0,
        'clicks_target_met': False,
        'budget_cap_reached': False,
        'extend_recommended': False
    },
    'tracking_pulse': {
        'ph_24h': 0,
        'ph_campaign': 0,
        'ph_project_window': 0,
        'ga_clicks_24h': None,
        'capture_rate_24h': None,
        'capture_rate_lifetime': None,
        'evaluated': False,
        'skip_reason': None,
        'created_at_missing': False
    },
    'checks': [
        {'check_name': '<name>', 'status': '<healthy|issue>', 'details': '<details>', 'issue_type': None}
    ],
    'issues': [],
    'overall_status': '<healthy|issues_found>'
}
# Populate issues from checks where status == 'issue'
health['issues'] = [c for c in health['checks'] if c['status'] == 'issue']
health['overall_status'] = 'issues_found' if health['issues'] else 'healthy'
print(json.dumps(health))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-check-health.json \
  --payload "$PAYLOAD" \
  --skill iterate
```

Replace all placeholder values with actual data collected from Chrome MCP.

**POSTCONDITIONS:**
- All health checks performed via Chrome MCP and tracking pulse (7 standard + conditional sitelink check when ads.yaml has sitelinks)
- Campaign metrics collected
- `.runs/iterate-check-health.json` exists with structured results

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/iterate-check-health.json')); assert d.get('campaign_name'), 'campaign_name empty'; assert d.get('checked_at'), 'checked_at empty'; m=d.get('metrics',{}); assert 'impressions' in m and 'clicks' in m, 'metrics missing impressions or clicks'; assert isinstance(d.get('checks'), list), 'checks not a list'; assert d.get('overall_status') in ('healthy','issues_found'), 'overall_status=%s' % d.get('overall_status')"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-check c1
```

**NEXT:** Read [state-c2-auto-fix.md](state-c2-auto-fix.md) to continue.
