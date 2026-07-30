# STATE c0: READ_ADS_CONTEXT


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Reads archetype as part of /iterate --cross context; downstream states branch on it. -->

**PRECONDITIONS:**
- Git repository exists in working directory

**ACTIONS:**

### Validate ads configuration

1. Verify `experiment/ads.yaml` exists. If not, STOP:
   > "No ads config found. Run `/distribute` first to generate `experiment/ads.yaml`, then run `/iterate --check`."

2. Read `experiment/ads.yaml`. Extract:
   - `channel` (e.g., `google-ads`)
   - `campaign_name`
   - `landing_url`
   - `campaign_id` (if present)
   - `phase` (if present — 1 or 2; written by `/distribute` Step 7 for Phase 1, by the Phase 2 Playbook §5 prompt for Phase 2)
   - `campaign_created_at` (if present — YYYY-MM-DD)
   - `dayzero_probe_passed_at` (if present — YYYY-MM-DD; Phase 2 day-0 relay probe PASS date)
   - `budget.total_budget_cents`, `budget.daily_budget_cents`, `budget.duration_days`, `budget.click_target`
   - `guardrails.max_cpc_cents`
   - `thresholds` (all fields)

3. If `channel` is not `google-ads`, STOP:
   > "The `--check` mode currently supports Google Ads only. Your ads.yaml uses channel `{channel}`. Manual health checks are needed for this channel."

4. If `campaign_id` is absent from ads.yaml, STOP:
   > "No `campaign_id` in ads.yaml -- campaign not yet created. Complete `/distribute` STATE 9 to create the campaign, then run `/iterate --check`."

5. If `phase` from ads.yaml is `2` AND `dayzero_probe_passed_at` is absent, STOP:
   > "Phase 2 requires a recorded day-0 probe. Run the relay probe per the Phase 2 Playbook §5 step 10 (walk the deployed funnel with the probe URL; verify `pay_intent` lands in PostHog AND the Supabase table), then record the PASS date in `experiment/ads.yaml` as `dayzero_probe_passed_at: "YYYY-MM-DD"` via the §5 step 11 prompt, and re-run `/iterate --check`."

6. Read `experiment/experiment.yaml`. Extract `name` and `type` (archetype, default `web-app`).

### Resolve phase and campaign age (ads.yaml is the primary source)

Resolve `phase` (priority order — ads.yaml wins because `.runs/distribute-context.json` is a transient Phase-1 artifact that goes stale the moment the Phase 2 campaign replaces the Phase 1 one in ads.yaml):
1. `phase` from ads.yaml (step 2 above), if present
2. Else `phase` from `.runs/distribute-context.json`, if that file exists
3. Else `null`

Calculate `campaign_age_days` (same priority):
1. If ads.yaml has `campaign_created_at`, compute days elapsed from that date to today
2. Else if `.runs/distribute-context.json` exists, use its `timestamp` field
3. Otherwise, ask the user: "When did you launch the campaign? (provide date or number of days ago)"

### Verify Chrome MCP availability

Use ToolSearch to check for Chrome MCP tools:
```
ToolSearch: query="claude-in-chrome", max_results=5
```

If no `mcp__claude-in-chrome__*` tools are returned, STOP and show the setup guide:

1. Read `.claude/patterns/chrome-mcp-setup-guide.md`
2. Present the full guide to the user
3. End with: "After completing the setup, re-run `/iterate --check`."

### Merge ads-specific fields into context

```bash
bash .claude/scripts/init-context.sh iterate-check "{\"mode\":\"check\",\"channel\":\"<channel from ads.yaml>\",\"campaign_name\":\"<campaign_name>\",\"campaign_id\":\"<campaign_id>\",\"campaign_created_at\":<campaign_created_at JSON string or null>,\"campaign_age_days\":<N>,\"phase\":<resolved phase: ads.yaml first, then distribute-context.json, else null>,\"budget_total_cents\":<N>,\"budget_daily_cents\":<N>,\"max_cpc_cents\":<N>,\"completed_states\":[\"c0\"]}"
```

Replace all `<placeholder>` values with actual data read from ads.yaml and experiment.yaml. Use a valid JSON string for `campaign_created_at` when present (for example `"2026-06-11"`), otherwise `null`. The base fields (`skill`, `branch`, `timestamp`, `run_id`) are already set by lifecycle-init.sh. The `completed_states:["c0"]` override replaces the default `[0]` to use iterate-check's string state IDs.

**POSTCONDITIONS:**
- `experiment/ads.yaml` read, channel is `google-ads`, `campaign_id` exists
- If ads.yaml `phase` is 2: `dayzero_probe_passed_at` present (day-0 probe recorded)
- Campaign age computed
- Chrome MCP tools verified available via ToolSearch
- `.runs/iterate-check-context.json` exists

**VERIFY:**
```bash
test -f .runs/iterate-check-context.json && python3 -c "import json,glob; d=json.load(open('.runs/iterate-check-context.json')); ctx=None
for f in glob.glob('.runs/*-context.json'):
    if 'epilogue' in f: continue
    try: c=json.load(open(f))
    except: continue
    if c.get('completed') is True: continue
    if ctx is None or (c.get('timestamp','') > (ctx.get('timestamp','') or '')): ctx=c
active_skill=ctx.get('skill','') if ctx else ''
active_run_id=ctx.get('run_id','') if ctx else ''
assert d.get('skill') == active_skill, 'iterate-check-context.json skill=%r does not match active_skill=%r (stale prior-skill artifact)' % (d.get('skill'), active_skill)
assert d.get('run_id') == active_run_id, 'iterate-check-context.json run_id=%r does not match active_run_id=%r (stale artifact)' % (d.get('run_id'), active_run_id)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-check c0
```

**NEXT:** Read [state-c1-check-health.md](state-c1-check-health.md) to continue.
