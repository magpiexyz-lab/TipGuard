# STATE x3: COMPUTE_SCORES

Pure compute: read per-MVP `signups` + `gclid_visitors` from data.json, apply the 100-visitor / 6% conversion rule, write scores.json.
When trusted DB ground truth is available, x3 writes
`metrics.signup_source` and `metrics.effective_signups` and uses the effective
count for the verdict.

**PRECONDITIONS:**
- STATE x2 POSTCONDITIONS met
- `.runs/iterate-cross-data.json` exists with `signups` and `gclid_visitors` per MVP
- `.runs/iterate-cross-data-issues.json` exists with `low_traffic`, `no_event_data` flags

**ACTIONS:**

### Compute headline verdict (precedence-ordered)

For each MVP, apply rules in order. The first matching rule sets `headline_verdict`:

| Order | Condition | Verdict | Notes |
|---|---|---|---|
| 0 | `missing_project_name == true` | `MISSING_PROJECT_NAME` | Orphan event stream (gclid events with no `project_name` property). Tracking misconfiguration — fix `src/lib/analytics.ts` PROJECT_NAME constant. Highest precedence because identity is upstream of every other signal. |
| 1 | `ga_clicks_without_ph_traffic == true` | `GA_NO_PH_TRACKING` | Strictly stricter than `MISSING_PROJECT_NAME`: GA records paid clicks but PostHog has zero presence (neither canonical events nor orphan rows). Operator is paying for a blind deploy — fix `analytics.ts` import or PROJECT_NAME mismatch. |
| 2 | `no_event_data == true` | `NO_DATA` | Discovered MVP but no PostHog events found. Likely tracking not deployed. |
| 3 | `db_unmapped_reason in ("project_deleted", "archived_killed")` | `NO_GO` | `project_deleted` = deletion OBSERVED via API (`Resource has been removed`); `archived_killed` = killed policy skip (x0b does not re-query killed rows — it says nothing about the backend, whose verified state lives in the sticky `db_backend` config record). Either way no trusted ground truth remains, so do NOT promote on the PostHog fallback — for loose `signup_start` events it inflates and would resurrect a killed MVP as a false GO. Forced NO_GO flows into the existing archived + kill-proposal path in x4. |
| 4 | `visitors < thresholds.visitors_floor` (default 100) | `INSUFFICIENT_DATA` | Below visitors floor, can't conclude. Compute `visitors_needed = max(0, visitors_floor - visitors)`. |
| 5 | `visitors >= thresholds.visitors_floor` AND `effective_signups / visitors >= thresholds.conv_rate_go` (default 0.06) | `GO` | Sufficient conversion signal. Eligible for Phase 2 promotion. |
| 6 | `visitors >= thresholds.visitors_floor` AND `effective_signups / visitors < thresholds.conv_rate_go` | `NO_GO` | Past data floor with conversion below threshold. Reject. |
| 7 (override) | CPC over cap AND `ga_cpc_usd * thresholds.cpc_payback_multiple > monthly_price_usd` AND no active `cpc_exception` | `NO_GO` | **CPC unit-economics gate** (applied AFTER rules 0–6). When the implied CAC exceeds a month's revenue at this CPC, a `GO` / `INSUFFICIENT_DATA` / `NO_GO` is forced to `NO_GO`. Does NOT override the data-integrity verdicts (rules 0–2) — tracking must be trusted before an economics call is meaningful. Needs `monthly_price_usd` (price unknown → advisory `cpc_price_unmapped` only, no override). The operator's `cpc_exception` is the "special approval" that bypasses it. See the CPC discipline section below. |

**Denominator:** `visitors` is the **Phase-1 slice of GA clicks**
(`ga_clicks - ga_clicks_phase2`, i.e. blended clicks minus campaigns matching
the `phase2.utm_campaign_like` pattern — state-x0a's `--phase-exclude` split)
when state-x0a merged Google Ads data (`mvp.ga_clicks > 0`), else PostHog
`gclid_visitors`. The phase2 funnel by design collects `pay_intent`, not
signups, so its clicks must not dilute the Phase-1 conversion rate.
**Zero-guard:** when blended `ga_clicks > 0` but every click matched the phase2
pattern, `visitors == 0` flows through rule 4 → `INSUFFICIENT_DATA` with
`visitors_needed == visitors_floor` and the score carries
`note: "all paid clicks match phase2 pattern; no Phase-1 traffic in window"`.
Precedence rules 0–3 still run first (a promoted MVP with broken tracking gets
its FIX-class verdict, not the zero-guard). The PostHog count remains in
`metrics.gclid_visitors` for diagnostics, `metrics.ga_clicks_phase1/phase2`
carry the split, and `metrics.denominator_source` indicates which source was
used (`"ga"` also covers the phase1-scoped case). `capture_rate` stays
deliberately blended on both sides (PostHog cannot phase-split untagged
phase1 flights). See `.claude/scripts/lib/iterate_cross_verdicts.py`
`compute_headline_verdict` for the implementation.

**CPC basis after the split:** the rule-7 unit-economics gate (trigger AND
implied CAC) runs on the **Phase-1 CPC** (`ga_cpc_phase1`, = blended CPC when
no split exists) so the verdict-changing signal shares the verdict
denominator's basis; the advisory `cpc_over_cap` worklist flag stays on the
**blended** CPC so an over-cap phase2 campaign never drops off the operator's
bid-discipline list.

Signup-source resolution is DB-first:
- `db_paid`: trusted DB paid gclid-shape count is used when the cross-table union has ≥1 real signup carrying a shape-valid populated gclid (`db_signups_paid > 0`)
- `db_real_zero`: trusted `db_signups_real == 0` and PostHog reports paid signups, suppressing false GO
- `db_real`: trusted DB real count is used whenever available, regardless of PostHog count — this now also covers gclid-dead tables (column present, never populated) and cross-table union counts
- `ph`: PostHog count is used only when no trusted DB count is available
- `null`: neither source is available; existing verdict precedence decides

Lifecycle/money-leak compute:
- `lifecycle_status` propagates from `mvp_mappings.<name>.lifecycle_status` (`active`, `killed`, `promoted`).
- `metrics.money_leak` is true when `db_unmapped_reason in ("project_deleted", "archived_killed")` OR `lifecycle_status == "killed"`, and `last_seen` is within the recent window (default 14 days). The Python helper compares against a deterministic reference window end: `--reference-now` when supplied, otherwise the max `last_seen` in the input data.
- `metrics.zombie_backend` is true when `lifecycle_status == "killed"` AND the sticky `db_backend.status == "alive"` (backend verifiably still exists) AND no active `backend_keep` waiver. The money-leak mirror: money_leak = paid traffic to a dead funnel; zombie_backend = live infrastructure behind a dead product. `metrics.db_backend_status` carries the raw status for rendering. Waiver: `iterate_cross_classify.py persist-backend-keep --name <mvp> --reason "..." --confirm`.

### CPC discipline (advisory flags + the verdict-changing unit-economics gate)

`compute_cpc_flags` (in `iterate_cross_verdicts.py`) appends to the same
`tracking_sanity_flags` list and adds CPC metrics (`ga_cost`, `ga_cpc`,
`ga_cpc_usd`, `ga_currency`, `effective_cpc_cap_usd`, `campaign_age_days`,
`monthly_price_usd`, `implied_cac_usd`, `cpc_payback_multiple`,
`cpc_unit_economics_fail`).

**Advisory flags** (channel-efficiency axis, orthogonal to conversion — they NEVER
change `headline_verdict`):
- **`cpc_over_cap`** (high): effective CPC > cap → the operator approval worklist.
  With Manual CPC, actual avg CPC ≤ max-CPC bid, so avg CPC over cap proves the
  bid was set over cap. Suppressed by an active `cpc_exception`.
- **`channel_starved`** (high; NO-GO candidate): in-cap but an aged campaign
  (`campaign_age_days ≥ thresholds.channel_starve_min_days`) still under
  `thresholds.channel_floor` clicks → the channel can't deliver volume at a viable
  CAC. Reliable because Phase-1 daily budgets are standardized (low clicks can't
  be blamed on under-funding). Uses `ga_clicks` directly so it fires for `ga_only`
  records too. In-cap is proven by an observed CPC ≤ cap **or by 0 clicks** (no
  CPC exists at $0 spend, and a bid can't be over cap without spending — the
  starved-est case must not be the one the flag misses); CPC unknown WITH clicks
  (Cost column absent) does not fire. Suppressed by an active `channel_waiver`.
- **`cpc_currency_unmapped`** (low): no `fx_to_usd` rate for the campaign's
  currency → CPC compared in native units (never silently passes).
- **`cpc_price_unmapped`** (low): CPC over cap but `monthly_price_usd` is unset, so
  the unit-economics gate below cannot run. Add the price to enable the gate.

**Verdict-changing flag** (the ONE CPC signal that moves a verdict — applied as the
rule-7 override in `compute_headline_verdict`, NOT inside `compute_cpc_flags`):
- **`cpc_unit_economics_fail`** (high): CPC over cap AND
  `implied_cac_usd = ga_cpc_usd * thresholds.cpc_payback_multiple` exceeds
  `monthly_price_usd` → the campaign can't pay back at this CPC → `NO_GO`. Only
  fires when a monthly price is known and no `cpc_exception` is active. The
  implied-CAC heuristic assumes ~`cpc_payback_multiple` clicks per paying customer
  and a one-month payback target.

Config: `thresholds.max_cpc` (default 2.5), `thresholds.cpc_payback_multiple`
(default 20), `thresholds.channel_floor` (50), `thresholds.channel_starve_min_days`
(21); top-level `max_cpc_basis` (`usd` → convert native CPC via `fx_to_usd` before
comparison; `native` → compare in the campaign's own currency) and `fx_to_usd`. All
seeded in `DEFAULT_CONFIG` (`load_config` only merges keys present there).

Operator data + overrides (per-MVP, in `mvp_mappings.<name>`, overlaid onto the
record by state-x1 `iterate_cross_propagate`):
- `monthly_price_usd` — the MVP's monthly price in USD; the denominator of the
  unit-economics gate. Operator-supplied (the skill has no source for per-MVP
  pricing). Absent → gate cannot run (`cpc_price_unmapped` advisory only).
- `cpc_exception {reason, max_cpc_override, expires_at}` — raises the effective cap
  and suppresses `cpc_over_cap` AND the unit-economics gate (the "special approval"
  that keeps an over-cap MVP in its conversion verdict). Written by the
  `persist-cpc-exception` subcommand of `iterate_cross_classify.py`.
- `channel_waiver {reason, expires_at}` — suppresses `channel_starved`.
An `expires_at` in the past no longer suppresses (forces re-review). Neither hides
data: actual CPC/Cost still render every run.

### INSUF futility triage (annotation only — never changes a verdict)

Every `INSUFFICIENT_DATA` row is annotated with a sequential-futility statistic
(`iterate_cross_verdicts.annotate_futility`, invoked automatically by the CLI
after verdict computation): the Beta-Binomial predictive probability that the
MVP still clears `conv_rate_go` once its click count reaches `visitors_floor`,
given the observed n clicks / k signups (Beta(1,1) prior). "Keep running until
the floor" is a purchase of information at `visitors_needed × CPC` — this
statistic prices whether the purchase can still pay off.

Fields written into `metrics`: `futility_prob` (effective-signups numerator),
`futility_prob_ph` (numerator lifted to `max(effective, ph_signups)`),
`futility_campaign_stale`, `futility_bucket`:

| Bucket | Condition | x4 consequence |
|--------|-----------|----------------|
| `too_new` | n < `thresholds.futility_min_clicks` (default 30) | none — no statistical call on tiny samples |
| `kill_candidate` | BOTH numerators give P < `thresholds.futility_kill_prob` (default 0.05) | folded into the operator-confirmed kill-proposal file |
| `verify_data` | numerators disagree materially: `ph > effective` AND `p_ph − p_eff ≥ thresholds.futility_verify_gap` (default 0.30) | "verify DB write path / signup_events first" worklist (perky/pagoo false-zero pattern — the discrepancy decides the outcome, so buying clicks before fixing data is waste) |
| `revive_candidate` | P ≥ `thresholds.futility_revive_prob` (0.5) AND campaign stale (`last_seen` older than `thresholds.futility_stale_days`, default 14d) | "cheap information the portfolio forgot to buy" worklist |
| `keep` | everything else | let it run to the floor |

The dual-numerator rule is the safety net: a DB-zero row whose PostHog count
would clear the bar is NEVER auto-proposed for kill — data quality blocks the
read, so it routes to `verify_data` instead. Thresholds are operator-tunable in
`experiment/iterate-cross-config.yaml` `thresholds:` (all four keys seeded in
`DEFAULT_CONFIG`). The headline verdict itself never changes here: a kill is an
operator decision recorded via `persist-lifecycle` in x4, symmetric with the
GO→promote confirm flow.

### Stalled campaign detection (annotation only — never changes a verdict)

Futility asks "is the observed sample already conclusive?". Stalled asks the
orthogonal question: **"is the sample even growing?"** An INSUF row whose click
flow is ~zero is a zombie — waiting has zero expected information gain while
the slot, calendar time, and operator attention keep burning. The typical
mechanism is a bid-capped shortfall: campaign enabled at the $2.50 ceiling but
losing every auction → 0 impressions → 0 clicks → $0 spend, indistinguishable
from "paused" in click-derived telemetry.

`annotate_stalled` (invoked by the CLI after `annotate_futility`) reads the
previous run's row from the decision ledger (`--ledger`, default
`experiment/mvp-decision-ledger.jsonl`) for run-over-run click deltas and
carry-forward. Missing ledger → lifetime-velocity detection only; a first-ever
run never escalates. Fields written into `metrics`: `stalled_bucket`,
`stalled_cause`, `stalled_since`, `stalled_streak`, `stalled_escalated`,
`click_delta`, `delta_days`, `stalled_eta_days`.

| Bucket | Condition | x4 consequence |
|--------|-----------|----------------|
| `stalled` | zero click growth since the previous ledger run, OR lifetime-zero clicks (provably zero growth over the whole campaign age — needs no previous row) | STALLED worklist; escalates (below) |
| `stalled_slow` | lifetime ETA to `visitors_floor` > `thresholds.stalled_eta_max_days` (default 45) | STALLED worklist only (never escalates in v1) |
| `none` | flow is healthy | nothing |

Cause split (needs the `Impr.` CSV column — see state-x0a):

| Cause | Condition | Meaning |
|-------|-----------|---------|
| `zero_serve` | lifetime impressions/day < `thresholds.stalled_impr_per_day_floor` (10) | losing auctions at the cap — **zero information about demand; never read as product NO-GO** |
| `weak_demand` | impressions ≥ `thresholds.stalled_weak_demand_min_impr` (1000) AND CTR < `thresholds.stalled_weak_demand_ctr` (0.01) | ads serve, nobody clicks — a REAL negative demand signal |
| `no_telemetry` | `ga_impressions` is null (CSV lacked the column) | re-export with `Impr.` to diagnose |

Escalation: `stalled_escalated = true` when the bucket is `stalled` on ≥ 2
consecutive runs spanning ≥ `thresholds.stalled_escalate_days` (default 14) —
x4 then folds the row into the operator-confirmed kill proposals. The first
flagged run never escalates: the operator always sees the STALLED worklist at
least one run before any fold-in. Suppressed by an active `channel_waiver`
(the same waiver that quiets `channel_starved`) or a `phase1_relaunch_at`
within `thresholds.relaunch_protection_days` (30). Age gate:
`stalled_age_days ≥ thresholds.channel_starve_min_days`, where
`stalled_age_days` = `campaign_age_days` (GA `Start date`) when present, else
days since the row's `first_seen_in_ledger` — a lower bound, so flagging is
delayed, never premature. The fallback is load-bearing: real exports often
omit `Start date` (the 2026-07-21 run had it on 0/101 records), which is why
`channel_starved` never fired in practice — stalled must not inherit that
silent failure mode. Only an MVP with neither source (first-ever sighting) is
skipped. Same-day re-runs carry the previous state verbatim
(`delta_days ≤ 0`), so the streak cannot double-increment. The headline
verdict itself never changes here.

### Use the verdict module

Verdict precedence is implemented in `.claude/scripts/lib/iterate_cross_verdicts.py` for testability:

```bash
python3 .claude/scripts/lib/iterate_cross_verdicts.py \
  --data .runs/iterate-cross-data.json \
  --issues .runs/iterate-cross-data-issues.json \
  --config experiment/iterate-cross-config.yaml \
  --ledger experiment/mvp-decision-ledger.jsonl \
  --output .runs/iterate-cross-scores.json
```

`--ledger` feeds the stalled triage's run-over-run deltas (see above). A
missing ledger file is fine — detection falls back to lifetime velocity and
never escalates on a first-ever run.

The script reads inputs, applies the precedence rules above, computes `visitors_needed` for INSUFFICIENT_DATA verdicts, and writes the results.

### Schema of `.runs/iterate-cross-scores.json`

```json
{
  "thresholds": {"signups_go": 6, "visitors_floor": 100, "conv_rate_go": 0.06},
  "window_days": 90,
  "mvps": [
    {
      "name": "diarly",
      "owner": "lego",
      "headline_verdict": "GO | NO_GO | INSUFFICIENT_DATA | NO_DATA | MISSING_PROJECT_NAME | GA_NO_PH_TRACKING",
      "visitors_needed": 0,
      "metrics": {
        "gclid_visitors": 100,
        "ga_clicks": 102,
        "ga_clicks_phase1": 102,
        "ga_clicks_phase2": 0,
        "signups": 8,
        "effective_signups": 8,
        "signup_source": "ph",
        "conv_rate": 0.08,
        "true_conv_rate": 0.0784,
        "capture_rate": 0.9804,
        "denominator_source": "ga",
        "money_leak": false,
        "ga_cpc_phase1": null,
        "futility_prob": 0.62,
        "futility_prob_ph": 0.62,
        "futility_campaign_stale": false,
        "futility_bucket": "keep",
        "ga_impressions": 4210,
        "stalled_bucket": "none",
        "stalled_cause": null,
        "stalled_since": null,
        "stalled_age_days": 23,
        "stalled_streak": 0,
        "stalled_escalated": false,
        "click_delta": 12,
        "delta_days": 2,
        "stalled_eta_days": null
      },
      "signup_events": ["signup_complete"],
      "ga_only": false,
      "ga_campaigns": ["diarly-search-v1"]
    }
  ]
}
```

`metrics.ga_clicks` is 0 only when the operator's CSV had zero data rows for
that MVP (campaign not present in the window) or no campaigns at all (header-only
CSV — legitimate zero-paid-clicks case). `denominator_source` then becomes
`"ph"` and `capture_rate` is `null`. Note that state-x0a now BLOCKS on missing
CSV — there is no scrape-or-skip fallback.

### Summary line

Print to stdout:
> Verdicts: {GO} GO · {NO_GO} NO_GO · {INSUF} INSUFFICIENT · {NO_DATA} NO_DATA

**POSTCONDITIONS:**
- Every MVP has `headline_verdict` (one of: MISSING_PROJECT_NAME, GA_NO_PH_TRACKING, NO_DATA, GO, NO_GO, INSUFFICIENT_DATA)
- INSUFFICIENT_DATA MVPs have `visitors_needed` set
- `.runs/iterate-cross-scores.json` exists with the schema above

The VERIFY assertion also accepts legacy `WEAK` artifacts for back-compat; the current x3 rule does not emit `WEAK`.

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x3`.

```bash
python3 -c "import json; d=json.load(open('.runs/iterate-cross-scores.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; allowed={'GO','WEAK','NO_GO','INSUFFICIENT_DATA','NO_DATA','MISSING_PROJECT_NAME','GA_NO_PH_TRACKING'}; sources={'db_paid','db_real_zero','db_real','ph',None}; bad=[m.get('name','?') for m in ms if m.get('headline_verdict') not in allowed]; assert not bad, 'MVPs with invalid headline_verdict: %s' % bad; bad2=[m.get('name','?') for m in ms if m.get('metrics',{}).get('signup_source') not in sources or 'effective_signups' not in m.get('metrics',{}) or 'money_leak' not in m.get('metrics',{})]; assert not bad2, 'MVPs missing/invalid signup_source metrics: %s' % bad2"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x3
```

**NEXT:** Read [state-x4-rank-recommend.md](state-x4-rank-recommend.md) to continue.
