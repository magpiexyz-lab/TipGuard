# STATE x4: RANK_AND_RECOMMEND

Cross-MVP report using PostHog visitors, Google Ads click denominators when available, and DB-first signup counts.

**PRECONDITIONS:**
- STATE x3 POSTCONDITIONS met
- `.runs/iterate-cross-scores.json` exists with `headline_verdict` per MVP
- `.runs/iterate-cross-data.json` exists (raw metrics)

**ACTIONS:**

### Read inputs

```bash
SCORES=.runs/iterate-cross-scores.json
DATA=.runs/iterate-cross-data.json
DEBUG_PROMPTS=.claude/patterns/iterate-cross-debug-prompts.md
```

Read all three. Build a per-MVP record by joining scores + data on `name`.

### Sort MVPs by verdict precedence

Sort MVPs into this order:

0. `MISSING_PROJECT_NAME` — sort by `gclid_visitors` desc (biggest leaks first; these block all downstream analysis until tracking is fixed, so they go at the top)
1. `GA_NO_PH_TRACKING` — sort by `ga_clicks` desc (paying for blind deploys; surface the most expensive first)
2. `GO` — sort by `signups` desc, then visitors asc (most efficient first; visitors = `ga_clicks` when GA data present, else `gclid_visitors`)
3. `INSUFFICIENT_DATA` — sort by visitors desc (closest to floor first)
4. `NO_GO` — sort by visitors desc
5. `NO_DATA` — alphabetical

This keeps the most-actionable verdicts at the top. `MISSING_PROJECT_NAME` and
`GA_NO_PH_TRACKING` outrank everything else because the data underneath is
suspect — the operator must fix tracking before any product decision is trustworthy.
The rank table uses `.claude/scripts/lib/iterate_cross_verdicts.py::sort_scores_global`.
The team message uses `sort_scores_by_owner` so each owner block preserves
this verdict precedence after owner grouping.
Legacy `WEAK` scores are still sorted by the implementation for old artifacts,
but current x3 no longer emits `WEAK`.

---

### Section A — Per-MVP table

Partition scored MVPs before rendering (precedence: money_leak > archived > promoted > normal — the shared predicate is `iterate_cross_verdicts._score_is_promoted`, mirrored locally by `iterate_cross_docx.is_promoted`):
- `money_leaks`: rows where `metrics.money_leak == true`. Render these in the dedicated `🆘 MONEY_LEAK` section below, regardless of lifecycle/verdict.
- `archived`: rows where `lifecycle_status == "killed"` and `metrics.money_leak != true`. Render these in the archived section; do not re-litigate them in the normal decision table.
- `promoted`: rows where `lifecycle_status == "promoted"` AND the verdict is conversion-class (`GO`/`NO_GO`/`INSUFFICIENT_DATA`) and the row is neither leaking nor archived. Render these in the `🚀 Promoted (Phase 2)` table in Section B — NOT in the normal decision table, and exclude them from GO-promote and kill proposals. Data-integrity verdicts (`MISSING_PROJECT_NAME`/`GA_NO_PH_TRACKING`/`NO_DATA`) override this partition: a promoted MVP with broken tracking stays on the fix worklist (phase2 measurement depends on tracking too).
- `normal`: every other row. Render these in the usual verdict table.

Print the normal table to stdout. Window comes from `.runs/iterate-cross-scores.json window_days`:

```
╔════════════════════════════════════════════════════════════════════════════════════════════════╗
║  Cross-MVP Evaluation — {date}  |  {N} MVPs  |  {window_days}d window                          ║
╠════════════════════════════════════════════════════════════════════════════════════════════════╣
║ Verdict     │ MVP             │ GA-clk │ PH-vis │ PHsig │ DB-sig │ Conv%  │ Cap% │ Signup events ║
║─────────────┼─────────────────┼────────┼────────┼───────┼────────┼────────┼──────┼───────────────║
║ 🚨 MISSING  │ {host_or_name}  │  {ga}  │  {ph}  │  --   │  --    │   --   │ {c}% │ —             ║
║ 🆘 NO_PH    │ {name}          │  {ga}  │    0   │  --   │  {db}  │   --   │   0% │ — (ga_only)   ║
║ ✅ GO       │ {name}          │  {ga}  │  {ph}  │  {s}  │  {db}⚠ │ {tc}%  │ {c}% │ {events}      ║
║ ⏳ INSUF    │ {name}          │  {ga}  │  {ph}  │  {s}  │  {db}  │   --   │ {c}% │ {events}      ║
║ ❌ NO_GO    │ {name}          │  {ga}  │  {ph}  │  {s}  │  {db}⚠ │ {tc}%  │ {c}% │ {events}      ║
║ ❓ NO_DATA  │ {name}          │   --   │   --   │  --   │  {db}  │   --   │  --  │ —             ║
╚════════════════════════════════════════════════════════════════════════════════════════════════╝
```

Column legend:
- `GA-clk` — Phase-1 clicks with the phase2 split rendered inline: `metrics.ga_clicks_phase1` plus a `(+N P2)` suffix when `metrics.ga_clicks_phase2 > 0` (e.g. `113 (+258 P2)`); plain `metrics.ga_clicks` when there is no split. Shown as `--` when an MVP has zero GA clicks in the window (either the CSV omits that campaign or the operator's CSV was header-only). state-x0a blocks if no CSV is provided, so a fully empty GA-clk column should not appear in normal operation.
- `PH-vis` — `metrics.gclid_visitors` (PostHog).
- `PHsig` — `metrics.ph_signups` (PostHog paid-traffic signups).
- `DB-sig` — `metrics.db_signups_real` (filtered DB real signups in window; a cross-table email-deduped union when multiple email tables contribute — see the `db_union_multi_table` flag). `--` when the MVP isn't mapped to a trusted DB source. A `⚠` suffix means `tracking_sanity_flags` has at least one high-severity flag.
- `Source` — `metrics.signup_source` (`db_paid`, `db_real_zero`, `db_real`, `ph`, or null) and `metrics.effective_signups`, the value consumed by the verdict.
- `Conv%` — `metrics.true_conv_rate` × 100 (denominator = Phase-1 GA clicks — `ga_clicks - ga_clicks_phase2` — when GA data present, else PH visitors; matches the displayed GA-clk phase1 number so `signups == Conv% × GA-clk` holds on every row).
- `Cap%` — `metrics.capture_rate` × 100 (how much of paid traffic PostHog actually captured; deliberately blended on both sides — PostHog cannot phase-split untagged flights). Null when no GA data.

For any row whose `partial_tracking_pct` is non-null and > 0, append a warning suffix to the MVP cell (e.g., `x-predict ⚠ 14% pages w/o project_name`). This flags canonical rows that absorbed an orphan during state-x0's merge step — same-deploy partial-tracking, NOT a separate broken deploy.

For any row whose `phase1_relaunch_at` is set, append a `🔄 relaunch <date>` marker to the MVP cell. This row's `ga_clicks`/`signups`/`db_signups_real` are scoped to the relaunch-onward window (the failed first flight is excluded), but `gclid_visitors`/`capture_rate` still span the full window (state-x0 discovery is not re-scoped) — so a low `Cap%` on a relaunched row is expected and not a tracking defect. Judge these on GA/DB numbers only.

For any row whose `metrics.capture_rate` < 0.5 AND `metrics.ga_clicks` ≥ 30, append `⚠ low capture` (operator should investigate the deploy's `src/lib/analytics.ts` import path).

For any row whose `metrics.gclid_visitors > metrics.ga_clicks * 1.10`, append `⚠ PH-overcount` (likely distinct_id churn / cross-device — informational, not blocking).

For any row whose `tracking_sanity_flags[]` (from state-x0b cross-check + state-x3 CPC flags) contains a high-severity flag, append `⚠ <flag_name>` to the MVP cell AND print the flag's `message` as an indented sub-bullet below the row. The flags are:
- `ph_attribution_broken` — DB has signups, PH paid is zero → gclid attribution likely lost between landing and signup page
- `ph_overcount` — PH paid > DB total × 1.5 → signup_events config likely wrong (chose a non-signup event)
- `ph_undercount` — DB > 3 × PH paid → organic-only OR PostHog track() call missing from some signup paths
- `late_instrumentation` — PH first paid event > 7d after DB first row → track() added after product launch, early signups invisible
- `cpc_over_cap` (CPC) — effective CPC over `thresholds.max_cpc` (USD basis) → max-CPC bid set above playbook; appears in the **CPC approval worklist** below
- `cpc_unit_economics_fail` (CPC, **verdict-changing**) — over cap AND implied CAC (`metrics.implied_cac_usd` = CPC × `cpc_payback_multiple`) > `metrics.monthly_price_usd` → this is why the row is `NO_GO`. Render the reason and note it clears via an operator `cpc_exception`.
- `channel_starved` (CPC) — in-cap but aged campaign still under `thresholds.channel_floor` clicks → **Channel NO-GO candidate** below
- `cpc_currency_unmapped` (CPC, low) — no `fx_to_usd` rate for the campaign's currency → CPC compared in native units
- `cpc_price_unmapped` (CPC, low) — over cap but `monthly_price_usd` unset → the unit-economics gate could not run; add the price to `mvp_mappings.<name>` to enable it
- `db_union_multi_table` (info) — the DB count is a cross-table email union (≥2 tables contributed real signups after gmail-normalized dedupe); `db_signups_table` names the top contributor only, per-table raws are in `db_breakdown`. Informational — no `⚠` row marker.

Add two columns to the table when any row has CPC data (`metrics.ga_cpc` non-null): **CPC** (`metrics.ga_cpc_usd`, with the native `metrics.ga_cpc`/`ga_currency` in parentheses) and **Cost** (`metrics.ga_cost`). Rows under an active `cpc_exception` show `✓ CPC exception (operator): <reason>` instead of `⚠ cpc_over_cap`; rows under an active `channel_waiver` show `✓ channel waiver (operator): <reason>` instead of `⚠ channel_starved`.

For any row carrying a discovered price (`metrics.monthly_price_usd` non-null, from state-x0c), show **Price** (`$<monthly_price_usd>/mo`) and, when `metrics.cpc_unit_economics_fail` is true, the implied CAC (`metrics.implied_cac_usd`) next to it — so a NO_GO driven by the CPC gate reads as `CAC $63 > $19/mo`. The `price_source` (e.g. `repo:experiment.yaml`, `live:<url>`) renders as a sub-note for auditability.

Show the operator at the bottom: total visitors, total signups, blended conv%, count by verdict.

After the main table, render two operator-action sections derived from the CPC flags:

```
💸 CPC APPROVAL WORKLIST (CPC > cap AND still deliverable — team must apply for an exception)
| MVP | Owner | CPC (USD) | cap | Cost | Clicks | Campaigns | Action |
|-----|-------|-----------|-----|------|--------|-----------|--------|
| {name} | {owner or "—"} | {ga_cpc_usd} ({ga_cpc} {ga_currency}) | {effective_cpc_cap_usd} | {ga_cost} | {ga_clicks} | {ga_campaigns} | Lower max-CPC bid to cap, OR approve via `iterate_cross_classify.py persist-cpc-exception --name {name} --reason "..." --max-cpc-override <usd> --confirm` |
```

Row selection (operator decision 2026-07-28): render only `cpc_over_cap` rows
that are NOT provably stopped — include when `ga_ads_all_stopped is not True`
(tri-state: `false` = a campaign can still spend; `null` = export lacked the
status columns, conservatively shown. Mirrors `normalize_campaign_status`
semantics: "stopped" is proven by whitelist, "alive" is the default). Rows
whose campaigns are all verifiably stopped are historical bid-discipline
records, not action items — omit them from the table and print one
no-silent-caps note instead:
`(N over-cap rows with all campaigns verifiably stopped omitted — historical record lives in scores.json)`.
If no rows have `cpc_over_cap` on a still-deliverable campaign, print
`No deliverable campaigns over the CPC cap.` (plus the omitted-count note when
stopped over-cap rows exist).

```
🛑 CHANNEL NO-GO CANDIDATES (in-cap but can't acquire traffic at viable CAC)
| MVP | Owner | CPC (USD) | Clicks | Age (days) | Action |
|-----|-------|-----------|--------|------------|--------|
| {name} | {owner or "—"} | {ga_cpc_usd} | {ga_clicks} | {campaign_age_days} | Stop the campaign (channel NO-GO), OR keep alive via `iterate_cross_classify.py persist-channel-waiver --name {name} --reason "..." --confirm` |
```
If no rows have `channel_starved`, print `No channel NO-GO candidates.`

After the CPC sections, render the INSUF futility triage (fields written by
state-x3 `annotate_futility` — see state-x3 "INSUF futility triage" for bucket
semantics; `P(GO)` below is `metrics.futility_prob`, the probability the MVP
still clears `conv_rate_go` at the `visitors_floor`):

```
⚖️ INSUF FUTILITY TRIAGE
Kill candidates (P < futility_kill_prob on BOTH numerators — folded into the kill proposals below):
| MVP | n (clicks) | k (signups) | P(GO) | CPC | Spent | Cost to floor | Last seen |
|-----|-----------|-------------|-------|-----|-------|---------------|-----------|

Verify data first (DB says futile, PostHog disagrees — fix the write path / signup_events before buying more clicks):
| MVP | n | k_eff | k_ph | P(GO) eff | P(GO) ph | Action |
|-----|---|-------|------|-----------|----------|--------|
| {name} | {n} | {eff} | {ph} | {p_eff} | {p_ph} | Investigate DB write path (perky/pagoo false-zero pattern) before continuing spend |

Revive candidates (P ≥ futility_revive_prob but campaign stopped — cheap information going unbought):
| MVP | n | k | P(GO) | Cost to floor | Last seen | Action |
|-----|---|---|-------|---------------|-----------|--------|
| {name} | {n} | {k} | {p} | {visitors_needed × cpc} | {last_seen} | Restart the campaign or archive deliberately |
```

Omit any empty sub-table. `too_new` and `keep` rows render only in the normal
INSUF section (no extra list — they are the default "let it run" path).

After the futility triage, render the stalled-flow worklist (fields written by
state-x3 `annotate_stalled` — see state-x3 "Stalled campaign detection" for
bucket/cause semantics). These are INSUF rows whose click flow is ~zero:
waiting is not a rational action for them, so every row must resolve through
the menu below — "keep waiting" is deliberately not on it.

```
🧟 STALLED CAMPAIGNS (bid-capped shortfall — forced-resolution menu)
| MVP | Owner | Clicks (Δ) | Age | Impr/day | Cause | Stalled since | Streak | ETA to floor | Escalated |
|-----|-------|------------|-----|----------|-------|---------------|--------|--------------|-----------|
| {name} | {owner or "—"} | {ga_clicks} ({click_delta or "—"}) | {stalled_age_days}d | {ga_impressions/stalled_age_days or "no telemetry"} | {stalled_cause or "—"} | {stalled_since} | {stalled_streak} | {stalled_eta_days or "∞"}d | {"YES" if stalled_escalated else "no"} |
```

Rows: `metrics.stalled_bucket` in (`stalled`, `stalled_slow`). If empty, print
`No stalled campaigns.` and skip the menu. Cause legend: `zero_serve` = losing
auctions at the bid cap — **zero information about demand, do NOT read as a
product NO-GO**; `weak_demand` = impressions healthy but CTR ~0 — a real
negative signal; `no_telemetry` = the CSV export lacked the `Impr.` column
(ask the owner to re-export with it).

Below the table, print the three-option menu (owner homework for `zero_serve`
rows: read the keyword set's first-page bid estimates in the Ads UI before
choosing):

1. **Raise the cap** (market is priceable — first-page bid ≤ the proposed new
   ceiling, and unit economics still pass): `python3
   .claude/scripts/lib/iterate_cross_classify.py persist-cpc-exception --name
   {name} --reason "priced-out keyword market — approved raise"
   --max-cpc-override <usd> --confirm`, then raise the max-CPC bids in the Ads
   UI. Products > $50/mo follow the google-ads.md premium-price escalation.
2. **Swap keywords / channel + relaunch**: create a fresh campaign (new Start
   date), then set `mvp_mappings.{name}.phase1_relaunch_at: "YYYY-MM-DD"` in
   `experiment/iterate-cross-config.yaml` (manual config edit — there is no
   persist subcommand for relaunch). Relaunch protection then suppresses
   stalled for `relaunch_protection_days`.
3. **Kill (channel infeasible)**: do nothing — rows with `stalled_escalated`
   fold into the kill proposals below on the next confirm, recorded in the
   ledger as *channel infeasible at the CPC cap, NOT a product NO-GO*. To keep
   the row alive instead: `python3
   .claude/scripts/lib/iterate_cross_classify.py persist-channel-waiver --name
   {name} --reason "..." [--expires-at YYYY-MM-DD] --confirm` (one waiver
   suppresses both `stalled` and `channel_starved`).

---

### Section B — Money leak + archived lifecycle

Render this section above owner grouping.

`🆘 MONEY_LEAK` rows are scored MVPs whose backend is deleted/killed but still has recent paid traffic (`last_seen` within the recent window, default 14 days). This is a LAGGING signal (PostHog last_seen) and cannot say whether the campaigns can still spend; the CSV status columns can — the Action column splits on them. All-time `Cost` in the export is cumulative, not proof of current spend.

```
🆘 MONEY_LEAK
| MVP | Owner | Lifecycle | Last seen | GA-clk | PH-vis | Reason | Action |
|-----|-------|-----------|-----------|--------|--------|--------|--------|
| {name} | {owner or "—"} | {lifecycle_status} | {last_seen} | {ga} | {ph} | {db_unmapped_reason} | {action — rule below} |
```

Action column rule, keyed on the score row's `ga_ads_all_stopped` (state-x0a
status-column ingest):
- `false` → `Pause in Google Ads NOW: <campaigns from ga_campaign_status_detail where normalized == "active">` (fall back to `Ads not verifiably stopped — check Google Ads and pause` when no entry is marked active)
- `true` → `Ads stopped per CSV — tail traffic, no action`
- `null` → `Ads status unknown (export lacked status columns) — check Google Ads`

If no rows have `metrics.money_leak == true`, print `No money leaks detected in the recent window.`

The `Reason` column renders `db_unmapped_reason` verbatim. Read it honestly:
`project_deleted` = deletion OBSERVED via API; `archived_killed` = killed
policy skip — the backend was NOT re-queried and may still be alive (check
`metrics.db_backend_status`: `alive` = verified live backend →
`metrics.zombie_backend` teardown candidate; `deleted_verified` = tombstone
confirmed; `never_located` = backend was never found).

Archived rows (`lifecycle_status == "killed"` and not leaking) should be listed separately and excluded from the normal decision table:

```
Archived killed MVPs (not re-litigated)
| MVP | Owner | Last seen | Latest verdict |
|-----|-------|-----------|----------------|
| {name} | {owner or "—"} | {last_seen or "—"} | {headline_verdict} |
```

Promoted rows (Section A `promoted` partition) render in their own table — the phase-1 verdict is reference-only; the operative call is x5's pay-intent verdict:

```
🚀 Promoted (Phase 2) MVPs — no Phase 1 action
| MVP | Owner | Promoted at | Phase-1 ref verdict | Phase-2 clicks | Next |
|-----|-------|-------------|---------------------|----------------|------|
| {name} | {owner or "—"} | {lifecycle_status_at or "—"} | {headline_verdict} | {metrics.ga_clicks_phase2 or 0} | See /iterate --cross --phase2 |
```

If no rows are promoted, omit the table.

Auto-propose lifecycle kill updates for (a) rows whose latest verdict is
`NO_GO` and `db_unmapped_reason == "project_deleted"`, (b) INSUF rows in
the futility `kill_candidate` bucket (P below `thresholds.futility_kill_prob`
on BOTH the effective and the PostHog numerator — see state-x3), (c)
**plain demand NO_GOs** — past the floor with conversion below threshold —
with two exemptions, and (d) INSUF rows with `metrics.stalled_escalated`
(second consecutive stalled run, sustained ≥ `thresholds.stalled_escalate_days`
— see the STALLED worklist above; channel_waiver and relaunch protection were
already applied in x3, so no re-check here). The kill records as *channel
infeasible at the CPC cap*, not a product NO-GO:
- **Channel-problem exemption**: rows whose NO_GO came SOLELY from the CPC
  unit-economics gate (`metrics.pre_cpc_verdict != 'NO_GO'`) and have no
  active `cpc_exception` are NOT proposed — expensive clicks ≠ no demand.
  They render in the separate channel-problem list below instead.
- **Relaunch protection**: rows whose `phase1_relaunch_at` is within
  `thresholds.relaunch_protection_days` (default 30) of now are NOT proposed
  — the re-test is still breathing. (A NO_GO past that window means the
  scoped re-test itself reached the floor and failed → proposable.)

All are PROPOSALS: nothing persists until the operator confirms.

```bash
python3 - <<'PY' > .runs/_iterate-cross-lifecycle-kill-proposals.json
import json, os, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, '.claude/scripts/lib')
try:
    import yaml
except ImportError:
    yaml = None
from iterate_cross_relaunch import parse_relaunch_at

cfg = {}
if yaml is not None and os.path.exists('experiment/iterate-cross-config.yaml'):
    cfg = yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}
mappings = cfg.get('mvp_mappings') or {}
protection_days = int((cfg.get('thresholds') or {}).get('relaunch_protection_days', 30))
now = datetime.now(timezone.utc)

scores = json.load(open('.runs/iterate-cross-scores.json')).get('mvps', [])
updates = []
channel_problems = []
for s in scores:
    met = s.get('metrics') or {}
    if s.get('lifecycle_status') in ('killed', 'promoted'):
        continue
    project_deleted_no_go = (
        s.get('headline_verdict') == 'NO_GO'
        and s.get('db_unmapped_reason') == 'project_deleted'
    )
    futility_kill = (
        s.get('headline_verdict') == 'INSUFFICIENT_DATA'
        and met.get('futility_bucket') == 'kill_candidate'
    )
    stalled_kill = (
        s.get('headline_verdict') == 'INSUFFICIENT_DATA'
        and bool(met.get('stalled_escalated'))
    )
    plain_no_go = (
        s.get('headline_verdict') == 'NO_GO'
        and not project_deleted_no_go
    )
    if plain_no_go:
        # Channel-problem exemption: NO_GO solely from the CPC gate.
        if met.get('pre_cpc_verdict') not in (None, 'NO_GO') and not s.get('cpc_exception'):
            channel_problems.append(s.get('name'))
            plain_no_go = False
        else:
            # Relaunch protection: fresh re-test keeps breathing.
            relaunch_at = parse_relaunch_at(
                (mappings.get(s.get('name')) or {}).get('phase1_relaunch_at')
            )
            if relaunch_at is not None:
                if relaunch_at.tzinfo is None:
                    relaunch_at = relaunch_at.replace(tzinfo=timezone.utc)
                if now < relaunch_at + timedelta(days=protection_days):
                    plain_no_go = False
    if project_deleted_no_go or futility_kill or plain_no_go or stalled_kill:
        updates.append({'name': s.get('name'), 'lifecycle_status': 'killed'})
json.dump({'updates': updates}, open('.runs/_iterate-cross-lifecycle-kill-proposals.json', 'w'), indent=2)
print(f"lifecycle-kill-proposals: {len(updates)}")
if channel_problems:
    print("channel-problem NO_GOs (CPC gate only — NOT kill-proposed; fix bids or file cpc_exception):")
    for name in channel_problems:
        print(f"  {name}")
PY
```

Show the proposed updates to the operator. On confirmation only, persist with the dedicated lifecycle writer:

```bash
python3 .claude/scripts/lib/iterate_cross_classify.py persist-lifecycle \
  --input .runs/_iterate-cross-lifecycle-kill-proposals.json \
  --config experiment/iterate-cross-config.yaml \
  --confirm
```

Do not use `persist`; it owns signup classification and must keep writing only signup fields.

Auto-propose lifecycle **promote** updates — the symmetric twin of the kill flow.
A GO verdict is a PROPOSAL, never a decision: nothing persists until the
operator confirms. Rows already promoted/killed and money-leak rows are
excluded:

```bash
python3 - <<'PY' > /dev/null
import json
scores = json.load(open('.runs/iterate-cross-scores.json')).get('mvps', [])
updates = []
for s in scores:
    if (
        s.get('headline_verdict') == 'GO'
        and s.get('lifecycle_status') not in ('promoted', 'killed')
        and not (s.get('metrics') or {}).get('money_leak')
    ):
        updates.append({'name': s.get('name'), 'lifecycle_status': 'promoted'})
json.dump({'updates': updates}, open('.runs/_iterate-cross-lifecycle-promote-proposals.json', 'w'), indent=2)
print(f"lifecycle-promote-proposals: {len(updates)}")
PY
```

Render the promote proposals to the operator as a table (MVP, phase-1 conv,
effective signups, and the `lifecycle_status_at` that will be stamped = confirm
time). The operator may confirm all, some (edit the proposals file first), or
none. **On confirmation only**, persist with the same dedicated lifecycle
writer (same `--confirm` gate as kills; never touches signup classification
keys):

```bash
python3 .claude/scripts/lib/iterate_cross_classify.py persist-lifecycle \
  --input .runs/_iterate-cross-lifecycle-promote-proposals.json \
  --config experiment/iterate-cross-config.yaml \
  --confirm
```

Then delete both proposal files (transient artifacts):

```bash
rm -f .runs/_iterate-cross-lifecycle-kill-proposals.json \
      .runs/_iterate-cross-lifecycle-promote-proposals.json
```

Auto-propose **owner backfill** for mapping rows with no `owner` — inferred from
each MVP's repo commit history (first-commit author > majority author; operator
accounts + bots excluded; authors matched to `team_roster` via
`github`/`github_aliases`/`email`; departed members remap to the operator).
Repo resolution uses the layered chain (`resolve_repo_layered`: override >
alias > exact-name > experiment.yaml name-index > description prefix >
homepage), plus the **optional Vercel channel** (`iterate_cross_vercel`; token
at `$VERCEL_TOKEN` or `~/.vercel/api-token`, absent → channel off) for repos
living OUTSIDE the org: the Vercel project link supplies a cross-org
`owner/repo` slug, and when even that repo is unreachable the latest
production deployment's commit author becomes a direct medium-confidence
owner signal (`evidence.resolution_method: vercel-deploy-author`).
Rows first created by this run's x2 have no owner yet and are picked up here
automatically. `--scores` widens the target set to score-row MVPs with NO
mapping row at all (the ga_only class — zero PostHog events means x2 never
births their row; without this channel they are structurally unreachable by
owner inference). Confirming such a proposal creates the mapping row. All are
PROPOSALS: nothing persists until the operator confirms.

```bash
python3 .claude/scripts/lib/iterate_cross_owner_infer.py propose \
  --config experiment/iterate-cross-config.yaml \
  --scores .runs/iterate-cross-scores.json \
  --output .runs/_iterate-cross-owner-proposals.json
```

Render the proposals to the operator sorted high → medium → low confidence,
with low-confidence rows grouped last:

| MVP | Proposed owner | Confidence | Evidence (first / majority) | Runner-up |

Then two separate lists from the same file:

- **Fallback → operator** (`confidence: "fallback"` rows — reasons
  `repo_unresolved` / `repo_deleted` / `no_commits` / `no_teammate_history` /
  `fetch_error`): | MVP | Reason |
- **Needs roster mapping** (`needs_roster[]` — no author matched the roster;
  add `github_aliases`/`email` to `team_roster`, then re-run propose):
  | MVP | Unmapped authors (commits) |

The operator may confirm all, some (edit the proposals file first — delete
rows or change `owner`), or none. **On confirmation only**, persist with the
dedicated owner writer (same `--confirm` gate as lifecycle; never touches
signup or lifecycle keys; rows that already have an owner are skipped):

```bash
python3 .claude/scripts/lib/iterate_cross_classify.py persist-owner \
  --input .runs/_iterate-cross-owner-proposals.json \
  --config experiment/iterate-cross-config.yaml \
  --confirm
```

Confirmed owners take effect next run (owner flows x0 → scores.json → the x4
renderers); do not re-render this run's tables. Then delete the proposal file
(transient artifact):

```bash
rm -f .runs/_iterate-cross-owner-proposals.json
```

---

### Section C — Debug prompts + team hand-off

For each `NO_DATA` / `GA_NO_PH_TRACKING` row in the normal table, surface the
matching section of `.claude/patterns/iterate-cross-debug-prompts.md` in the
conversation so the owner can copy it into the MVP repo. Per-verdict action
wording lives in `ACTION_TEMPLATES` (`iterate_cross_verdicts.py`) — do not
restate it here.

The per-owner team message is NOT composed in this state: it renders once at
state-x4b's team-message step (after the teardown reconcile, so teardown items
are included) and is relayed verbatim in the conversation. Nothing is written
to disk — the operator forwards it to the team chat with the results-doc link
filled in.

### Section D — Decision report (.docx, best-effort)

Write `.runs/iterate-cross-phase1-decision.docx` — the team-facing decision review
(header + "what to verify" intro + verdict-summary mini-table + the ✅ GO / ❌ NO_GO /
⏳ INSUF / 🚨 FIX TRACKING tables + Methodology). The NO_GO table carries a **WHY NO_GO**
column (low conversion vs CPC over cap vs deleted backend); the GO table carries
**PAID %**.

```bash
python3 .claude/scripts/lib/iterate_cross_verdicts.py \
  --scores .runs/iterate-cross-scores.json \
  --reference-now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --emit-docx .runs/iterate-cross-phase1-decision.docx
```

This is **best-effort**: rendering needs the optional `python-docx` package. When it is
absent the command prints `python-docx not installed; skipping .docx report` and exits
0 — the pipeline continues (the scores artifact gated at x3 is the durable output, the
.docx is a convenience report). Surface the resulting `.docx` path to the operator when
it was written.

### Summary line

Print to stdout:
> Cross-MVP evaluation complete. Output: per-MVP table (above), lifecycle/owner proposals (above), decision report (`.runs/iterate-cross-phase1-decision.docx`, when python-docx is available). The team message renders at x4b.

**POSTCONDITIONS:**
- Per-MVP ranking table presented (Section A)
- `🆘 MONEY_LEAK` section and archived lifecycle section presented (Section B)
- Debug prompts surfaced for FIX-class verdicts (Section C)
- `.runs/iterate-cross-phase1-decision.docx` written when `python-docx` is available (best-effort; not gated)

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x4`.

```bash
true
```
<!-- VERIFY=true: x4 is a render-only state — scores are gated at x3, teardown obligations at x4b, and the team message prints to stdout at x4b (no durable artifact by operator decision 2026-07-27). The .docx is best-effort. -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x4
```

**NEXT:** Read [state-x4a-persist-ledger.md](state-x4a-persist-ledger.md) to continue.
