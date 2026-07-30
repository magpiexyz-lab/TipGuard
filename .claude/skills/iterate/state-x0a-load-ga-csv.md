# STATE x0a: LOAD_GA_CSV

Operator-supplied CSV is the sole source of paid-click data. No browser scrape,
no silent-skip. If the CSV is missing, stale (>24h old), or malformed, this
state HALTS with explicit instructions and `/iterate --cross` cannot proceed.

## Why this state exists

PostHog `gclid_visitors` undercounts paid traffic by 20–65% (SDK ad-blocker, DNT,
fast-bounce before lazy-imported analytics fires) and is entirely blind to
deploys whose `src/lib/analytics.ts` isn't imported on the landed route —
those deploys cost spend but emit zero events.

Google Ads "Clicks" is the ground truth for "how many real paid visitors
landed." The operator exports a CSV; the skill folds it into the verdict
pipeline. State-x3 prefers `ga_clicks` over PostHog `gclid_visitors` as the
denominator when both are present.

A prior Chrome MCP browser scrape was removed because it was brittle to Google
Ads UI changes (column-position drift, render timing, anti-automation
fallback page) and failed silently — producing zero or junk `ga_clicks` values
that masqueraded as real data. CSV export is the only supported source.

**PRECONDITIONS:**
- STATE x0 POSTCONDITIONS met (`.runs/iterate-cross-context.json` exists with `mvps`)

**ACTIONS:**

### Step 0: Blocking CSV gate

Check `.runs/iterate-cross-ga-clicks.csv`: file must exist, be ≤24h old, and
have a valid header. If any check fails, HALT with the export instructions
below. State does not advance until the operator provides a fresh, valid CSV
and re-runs `/iterate --cross`.

The 24h freshness gate prevents silent reuse of stale paid-click data across
sessions (`.runs/` is gitignored and never auto-cleaned, so a CSV from days
ago would otherwise flow through unnoticed and produce verdicts that don't
match current ad spend).

```bash
CSV=.runs/iterate-cross-ga-clicks.csv
MAX_AGE_HOURS=24
WINDOW_DAYS=$(python3 -c "import json; print(json.load(open('.runs/iterate-cross-context.json')).get('window_days', 90))")

print_export_instructions() {
  cat >&2 <<EOF

How to export (~30 seconds):

  1. Open the MCC parent campaigns view (one of your saved Google Ads URLs):
     https://ads.google.com/aw/campaigns?ocid=<MCC>&authuser=2
  2. Set the date range to last ${WINDOW_DAYS} days
     (matches window_days in experiment/iterate-cross-config.yaml)
  3. Make sure the columns include at minimum: Campaign, Clicks
     (recommended: + Account, Conversions)
     (Impr. is needed for stalled-cause diagnosis -- without it, stalled
      campaigns read "no telemetry"; use the plain Impr. count column,
      not Impr. (Top) % / Impr. (Abs. Top) %)
     (for CPC discipline: + Cost, Currency code, Start date — see note below)
     (deliverability: + Campaign status, Status, Status reasons -- without
      them x4b cannot auto-verify "ads stopped" (csv_paused) and every
      killed MVP needs a manual confirm-ads)
  4. Click Download icon -> CSV
  5. Save the file as: .runs/iterate-cross-ga-clicks.csv (overwrite if present)
  6. Re-run /iterate --cross

The skill cannot produce trustworthy verdicts without fresh paid-click data.
PostHog visitor counts undercount paid traffic by 20-65% and are blind to
deploys with broken event tracking. CSV path makes verdicts reflect real
ad spend.
EOF
}

if [ ! -f "$CSV" ]; then
  echo "STOP: /iterate --cross requires a Google Ads click CSV." >&2
  print_export_instructions
  exit 1
fi

AGE_HOURS=$(python3 -c "import os, time; print(int((time.time() - os.path.getmtime('$CSV')) / 3600))")
if [ "$AGE_HOURS" -gt "$MAX_AGE_HOURS" ]; then
  echo "STOP: GA CSV is ${AGE_HOURS}h old (max ${MAX_AGE_HOURS}h)." >&2
  echo "File: $CSV" >&2
  echo "Stale paid-click data produces unreliable verdicts -- re-export from Google Ads." >&2
  print_export_instructions
  exit 1
fi

python3 .claude/scripts/lib/iterate_cross_ga.py validate-csv \
  --ga-csv "$CSV" \
  --context .runs/iterate-cross-context.json || exit 1
```

Column requirements (preamble-aware header detection; exact header matches win
before substring matches so `Campaign status` cannot shadow `Campaign`):
- **Required:** `Campaign`, `Clicks`
- **Optional but recommended:** `Account`, `Conversions` (or `Conv.`)
- **Stalled-cause diagnosis (strongly recommended):** `Impr.` — without it,
  stalled campaigns render `no_telemetry` instead of `zero_serve`/`weak_demand`
- **CPC discipline (optional):** `Cost`, `Currency code`, `Start date`
- **Deliverability (strongly recommended):** `Campaign status`, `Status`,
  `Status reasons` — see the deliverability note below

The parser is column-order agnostic (header-indexed), strips UTF-8 BOM, skips
summary footer rows (starting with `Total`), and strips thousands separators
(`1,082` → 1082). A header-only CSV is accepted with a soft warning (legitimate
case: the date window captured zero paid clicks).

**CPC-discipline columns (optional, additive — old exports keep working):**
- `Cost` → per-MVP `ga_cpc = ga_cost / ga_clicks`. Drives the `cpc_over_cap`
  flag (the operator approval worklist) in state-x3/x4. **When `Cost` is absent,
  `ga_cpc` is null and the CPC flags simply do not compute** (graceful — never a
  false signal).
- `Currency code` → CPC is normalized to USD via `fx_to_usd` before comparison
  against `thresholds.max_cpc` (operator chose USD basis; see state-x3). Missing
  rate → compared in native units + a low-severity `cpc_currency_unmapped` note.
- `Start date` → per-MVP `campaign_first_date` (earliest across the MVP's
  campaigns). Drives the `channel_starved` NO-GO candidate (aged in-cap campaign
  still under `channel_floor` clicks) and the stalled triage's age gate. Without
  it, neither can fire (no GA-side campaign age; PostHog timestamps are
  intentionally NOT used).
- `Impr.` → per-MVP `ga_impressions` (blended sum across the MVP's campaigns;
  null when the column is absent). Drives the stalled-cause split in state-x3
  (`zero_serve` = losing auctions, vs `weak_demand` = serving but no clicks).
  Only the plain count column works — percentage variants (`Impr. (Top) %`,
  `Impr. (Abs. Top) %`) are rates, and the parser ignores them.

**Deliverability columns (optional, additive — old exports keep working):**
- `Campaign status` (on/off switch: Enabled/Paused/Removed), `Status` (serving
  state: Eligible, Eligible (Limited)/(Learning), Ended, Paused, Removed, …)
  and `Status reasons` → per-MVP `ga_campaign_status_detail` (per-campaign
  statuses + normalized `stopped|active|unknown`) and `ga_ads_all_stopped`
  (true ⇔ every campaign verifiably stopped). Headers are matched EXACT-only,
  so `Status` can never substring-bind to `Campaign status` (the #1482
  surface). `normalize_campaign_status` (iterate_cross_ga.py — single source
  of truth, reuse it for #1878) judges "stopped" by whitelist: switch Paused/
  Removed or serving Ended/Paused/Removed. **Enabled+Ended does NOT deliver**
  — serving state matters, not just the switch. Anything unrecognized
  (localized UI values, empty cells) counts as alive: the failure direction is
  an extra reminder, never a silent close-out.
- Consumers: x4b's `csv_paused` ads evidence (auto-closes the "confirm ads
  paused" line for killed MVPs) + the STILL_SERVING worklist, and the
  money-leak action wording split ("still deliverable — pause NOW" vs
  "already stopped — tail traffic"). **When the columns are absent,
  `ga_ads_all_stopped` is null and x4b falls back to manual `confirm-ads`**
  (graceful, mirrors the Cost degradation above). Unmatched campaigns carry
  `status_normalized` into `_iterate-cross-ga-unmatched.json`; any
  unattributable campaign not verifiably stopped blocks `csv_paused`
  fleet-wide (conservative — an unbucketable live ad could belong to anyone).

### Step 1: Merge

Resolve the phase2 campaign pattern from operator config first — the SAME
`phase2.utm_campaign_like` key x5 include-scopes with. x0a passes it as an
EXCLUDE so Phase 1 and Phase 2 partition the paid clicks instead of
double-counting the phase2 slice in both denominators:

```bash
PHASE2_LIKE=$(python3 -c "
import os
try:
    import yaml
except ImportError:
    yaml = None
cfg = {}
p = 'experiment/iterate-cross-config.yaml'
if yaml is not None and os.path.exists(p):
    cfg = yaml.safe_load(open(p)) or {}
phase2 = cfg.get('phase2') or {}
print(phase2.get('utm_campaign_like') or '%phase2%')
")

python3 .claude/scripts/lib/iterate_cross_ga.py merge \
  --ga-csv "$CSV" \
  --context .runs/iterate-cross-context.json \
  --config experiment/iterate-cross-config.yaml \
  --unmatched-out .runs/_iterate-cross-ga-unmatched.json \
  --phase-exclude "$PHASE2_LIKE"
```

The merge:
- Buckets each campaign to an MVP via substring match on stripped campaign name
  (xpredict → x-predict, brigent-search-v2 → brigent), honoring operator
  `ga_campaign_aliases` for names that don't substring-match (StaylicaAi-Lew
  → stylica-ai, PubCheck → verify).
- **Phase-2 split** (`--phase-exclude`): campaigns matching the pattern still
  count in the blended `ga_clicks`/`ga_cost` (capture_rate and the
  `cpc_over_cap` worklist keep the full paid picture) but ALSO accumulate into
  `ga_clicks_phase2` / `ga_cost_phase2` / `ga_campaigns_phase2`, and the merge
  prints one `phase-exclude: <mvp> excluded <N> clicks ...` summary line per
  affected MVP. state-x3 uses `ga_clicks - ga_clicks_phase2` as the Phase-1
  conversion denominator. Operator escape hatch for a Phase-1 campaign whose
  name contains the phase2 token: `phase2.exclude_exempt_campaigns` (exact
  names, default empty). An empty pattern excludes nothing (never inverts).
  The applied pattern is stamped into context as `ga_phase_exclude_applied`
  (asserted by VERIFY so the flag can't silently drop off this command).
- **Deliverability**: every MVP gets `ga_campaign_status_detail` (collected
  BEFORE the pre-relaunch drop — a dropped old flight can still spend) and
  tri-state `ga_ads_all_stopped`; unmatched entries carry `status_normalized`.
  The merge prints an `ads-status: N active / M stopped / K unknown;
  unmatched_active=X` summary line.
- Auto-creates `ga_only: true` MVP records for campaigns with no PostHog
  presence (state-x1a's `ga_clicks_without_ph_traffic` flag picks these up;
  state-x3 emits `GA_NO_PH_TRACKING` verdict for them). The record's `owner`
  is inherited from `mvp_mappings.<name>.owner` when present — same rule as
  state-x0 canonical records — so a mapped ga_only MVP never renders as
  unassigned in the team message.
- Folds into orphan rows when the GA campaign name match_keys to an orphan
  host (e.g., `Hospitica-search-v2` → `__orphan_hospitica__`).
- Writes unmatched campaigns to `.runs/_iterate-cross-ga-unmatched.json`
  (placeholder names like `Campaign #1` land here — operator triages).
- Sets `ga_clicks=0` on every existing MVP record even when CSV is header-only,
  so the x0a VERIFY postcondition holds.
- **Phase-1 relaunch** (`mvp_mappings.<name>.phase1_relaunch_at`): the merge
  reads each MVP's relaunch date from config (via `_load_relaunch_map`, no CLI
  flag needed) and DROPS any campaign bucketed to that MVP whose **Start date**
  sorts before the cut — so a failed first flight's clicks/cost no longer
  pollute the re-test denominator. Dropped campaigns print a
  `relaunch: dropped pre-relaunch campaign ...` line and land in the unmatched
  file with `reason=pre-relaunch`. **Relaunch therefore requires a NEW campaign
  name** (e.g. `mooncub-search-v2`) whose Start date is on/after the relaunch
  date; a campaign with a missing/blank Start date under an active relaunch is
  conservatively dropped (never silently re-counted). The date math lives in
  `.claude/scripts/lib/iterate_cross_relaunch.py` (single source of truth; also
  used by state-x0b DB and state-x2 signup scoping).
- Idempotent: re-running with the same CSV overwrites `ga_clicks` cleanly.

### Step 2: Review unmatched (operator triage hint)

If `.runs/_iterate-cross-ga-unmatched.json` is non-empty, the merge step has
already printed `WARN: unmatched GA campaign '<name>' (<N> clicks, reason=...)`
to stderr. For each unmatched campaign whose `reason` is `unmatched`, the
operator typically adds an entry to `ga_campaign_aliases` in
`experiment/iterate-cross-config.yaml` and re-runs `/iterate --cross`.
Campaigns with `reason=placeholder` (literal `Campaign #1` etc.) require the
operator to rename them in Google Ads first.

**POSTCONDITIONS:**
- Every MVP record in `.runs/iterate-cross-context.json` has `ga_clicks` field (≥0)
- New `ga_only: true` MVPs appended for GA campaigns lacking a PH match
- `.runs/_iterate-cross-ga-unmatched.json` exists (may be empty array)

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x0a`.

```bash
python3 -c "import json, os; d=json.load(open('.runs/iterate-cross-context.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; bad=[m.get('name','?') for m in ms if 'ga_clicks' not in m]; assert not bad, 'MVPs missing ga_clicks (CSV merge sets ga_clicks=0 on every MVP even for header-only zero-click CSV): %s' % bad; assert os.path.isfile('.runs/_iterate-cross-ga-unmatched.json'), 'unmatched triage file missing (x0a postcondition)'; assert (d.get('ga_phase_exclude_applied') or '').strip(), 'ga_phase_exclude_applied missing/empty (state-x0a merge must pass --phase-exclude with the phase2.utm_campaign_like pattern)'"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x0a
```

**NEXT:** Read [state-x1-gather-all-data.md](state-x1-gather-all-data.md) to continue.
