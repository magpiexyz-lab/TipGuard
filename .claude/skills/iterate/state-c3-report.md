# STATE c3: REPORT

**PRECONDITIONS:**
- Fixes processed (STATE c2 POSTCONDITIONS met)
- `.runs/iterate-check-fixes.json` exists

**ACTIONS:**

### Output health report

Read `.runs/iterate-check-context.json`, `.runs/iterate-check-health.json`, and `.runs/iterate-check-fixes.json`. Present a summary to the user:

```
## Campaign Health Check -- [campaign_name] -- Day [campaign_age_days]

**Status:** [Healthy / Issues Fixed / Needs Attention]

| Metric | Value |
|--------|-------|
| Impressions | [N] |
| Clicks | [N] |
| CTR | [X]% |
| Avg CPC | $[X] |
| Spend | $[X] of $[total_budget] |
| Conversions | [N] |
| Tracking | [If tracking_pulse.evaluated: 24h capture [X]% (or skipped), lifetime capture [Y]%; if not evaluated: monitoring unavailable: [skip_reason] -- fix to restore the daily tracking check] |

### Stop Rule
- Paid clicks: [clicks] / [click_target]
- Spend: $[spend] / $[total_budget]
- End date: [active / ended]. If ended before clicks or cap fired, recommend extending by `(cap - spent) / daily_budget` days or stopping consciously.

### Issues Found: [N]
[For each issue:]
- **[issue_type]**: [action_taken -- auto-fixed / needs manual intervention / recommendation]
  [description of what was done or recommended]
  [If issue_type is campaign_paused: add context -- "This is expected during Phase 1 Day -2/-1 protocol" when phase == 1 AND campaign age < 48h, or "Campaign was unpaused after ad approval" when auto-fixed, or "Ads still under review -- re-run /iterate --check tomorrow" when phase == 1 AND age >= 48h AND ads not approved, or "Campaign paused by user -- resume manually if intended" when not Phase 1]
  [If issue_type is stop_clicks_target_met: "Pause the campaign if still serving and report to your Team Lead (the lead runs /iterate --cross)."]
  [If issue_type is stop_budget_cap_reached: "Pause the campaign if still serving; short clicks are an affordability signal."]
  [If issue_type is campaign_ended or stop_extend_recommended: "Extend the End date by the reported headroom, or stop consciously."]
  [If issue_type is tracking_degraded: "Re-run /ads-ready against the current deploy and fix before trusting any verdict. Do NOT pause the campaign for this."]
  [If issue_type is tracking_utm_missing: "The Google Ads Final URL is missing the utm_campaign suffix (paid traffic reaches PostHog but is untagged) -- /ads-ready cannot catch this. Set the campaign-level Final URL suffix per Phase 2 playbook §5 step 6. Spend is invisible to the verdict until fixed; pause if it persists."]
  [If issue_type is monitoring_unavailable: "Fix PostHog key/project resolution so the daily tracking check is restored."]

[If no issues:]
- No issues found. Campaign is running as expected.

### Thresholds Check
- Go signal: [thresholds.go_signal from ads.yaml]
- Current progress toward go signal: [assessment based on metrics]
- No-go signal: [thresholds.no_go_signal from ads.yaml]

### Next Steps
- Next health check: tomorrow -- run `/iterate --check` daily until a stop condition fires
- For full funnel analysis: run `/iterate` (without --check) when you have enough conversion data
- If campaign was paused: review recommendations above before resuming
- If a stop-rule recommendation is present: resolve it before the next health check
```

Determine the **Status** value:
- `Healthy` -- no issues found
- `Issues Fixed` -- issues found and all were auto-fixed
- `Needs Attention` -- issues found that require manual intervention (e.g., NO-GO signal, budget anomaly pause)

### Strategy B Skill Epilogue

Follow `.claude/patterns/skill-epilogue.md` **Strategy B** (Execution Audit).

Inputs for Strategy B:
- Context file: `.runs/iterate-check-context.json`
- Expected completed states: `["c0", "c1", "c2"]` (from skill.yaml states)
- This skill is analysis-only and makes no code changes (Chrome MCP actions on Google Ads UI are not code changes)

**Important:** When writing `observe-result.json`, use `"skill": "iterate-check"` (not `"iterate"`).

**POSTCONDITIONS:**
- Health report presented to user
- `.runs/observe-result.json` exists with `"skill": "iterate-check"`

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/observe-result.json')); assert d['skill']=='iterate-check'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-check c3
```

**NEXT:** TERMINAL -- ads health check complete.
