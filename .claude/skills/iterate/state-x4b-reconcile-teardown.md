# STATE x4b: RECONCILE_TEARDOWN

Weekly teardown-obligation reconcile: for every killed MVP in config, gather
three INDEPENDENT evidence lines (DB / hosting / ads), apply the single
close-out rule, stamp the durable ledger, and surface due/overdue obligations
in the report + team message. Never deletes anything — destructive actions
stay with the humans running /teardown in each MVP repo.

## Why this state exists

NO-GO/killed MVPs routinely never get torn down (live audit 2026-07-21: 6 of
48 killed backends still alive). Three prior break points: plain NO_GOs never
entered kill proposals (fixed in x4), `lifecycle_status: killed` was a label
with no follow-up, and verdicts live in this operator repo while /teardown
runs in MVP repos. This state closes the loop with evidence-based tracking:
an obligation stays `due` (reminders escalate per run) until real probes say
the infra is gone — the synthesized `db_unmapped_reason` is NEVER accepted as
close-out evidence (circular: x0b stamps it from lifecycle status).

**PRECONDITIONS:**
- STATE x4a POSTCONDITIONS met (`experiment/mvp-decision-ledger.jsonl` upserted — x4b stamps teardown fields onto those rows)
- `.runs/iterate-cross-scores.json` exists (money-leak flags + ga_campaigns + `ga_campaign_status_detail`/`ga_ads_all_stopped` for the ads line)
- `experiment/iterate-cross-config.yaml` has `db_backend` records for killed rows (state-x0b / `verify-backends` maintain them)
- `.runs/_iterate-cross-ga-unmatched.json` exists (x0a writes it every run; optional input — when absent or old-format, `csv_paused` auto-evidence is disabled and the ads line falls back to `confirm-ads`; evidence freshness = the last x0a run, which is ≤24h-gated)

**ACTIONS:**

### Step 1: Reconcile

```bash
python3 .claude/scripts/lib/iterate_cross_teardown.py reconcile \
  --config experiment/iterate-cross-config.yaml \
  --scores .runs/iterate-cross-scores.json \
  --ledger experiment/mvp-decision-ledger.jsonl \
  --output .runs/iterate-cross-teardown-obligations.json \
  --unmatched .runs/_iterate-cross-ga-unmatched.json
```

Per killed non-orphan config row, the reconcile computes:
- **DB line** — from the sticky `db_backend` record (state-x0b/`verify-backends`):
  `alive` → LIVE · `deleted_verified`/`never_existed` → GONE · `never_located`
  → N/A (nothing to tear down) · `not_visible` → UNVERIFIABLE (personal org —
  stays due with note) · absent → UNKNOWN (run `verify-backends`).
- **Hosting line** — zero-credential HTTP probe of `https://<name>.draftlabs.org`
  (names containing dots probe as-is). 404/DNS-failure/timeout = surface-gone
  (**weak edge evidence** — custom domains probe wrong by design); 200/3xx/5xx
  = live. Vercel API verification is a deliberate TODO (project IDs not in config).
- **Ads line** — operator keyed confirmation (sticky in the ledger, see Step 3)
  OR **`csv_paused`** (every campaign verifiably stopped per the GA CSV status
  columns AND no unattributable unmatched campaign is still live — the
  run-level gate from `--unmatched`) OR auto-satisfied (`none_in_window`) when
  the run's scores show no GA campaigns for the MVP and none of its
  pre-relaunch-dropped campaigns is still deliverable.
- **Close-out rule** (implemented ONLY in `iterate_cross_teardown.closeout`):
  `waived` ⇔ active `backend_keep`; `verified` ⇔ DB ∈ {GONE, N/A} AND hosting
  = surface-gone AND ads ∈ {confirmed_paused, csv_paused, none_in_window};
  else `due`. A `csv_paused` close reopens honestly: if a campaign is
  re-enabled, the next run's evidence recomputes and the row goes back to
  `due` (reminders resume; `teardown_verified_at` stays set-once).

### Step 2: Ledger stamping (automatic, inside reconcile)

`stamp_teardown_fields` writes onto ledger rows WITHOUT unfreezing
(`archived_at`/`current`/history/sticky fields untouched; `upsert_row` starts
from `dict(existing)` so these fields survive later x4a upserts):
- `teardown_state: due|verified|waived`
- `teardown_first_due_at` (set once) · `teardown_reminder_count` (+1 per due run)
- `teardown_verified_at` (set once on close) · `teardown_evidence {db, hosting, ads}`

### Step 3: Operator ads confirmation (fallback only, between runs)

With the status columns in the export, "ads stopped" is normally auto-verified
as `csv_paused` — manual confirmation is the FALLBACK, needed only when the
export lacks the status columns, an unattributable unmatched campaign is still
live (gate blocked), or a non-English UI export defeats the status whitelist.
When a row shows `ADS:unknown`, the operator pauses the campaigns in Google
Ads UI, then records it (keyed confirmation, persisted sticky in the ledger):

```bash
python3 .claude/scripts/lib/iterate_cross_teardown.py confirm-ads \
  --name <mvp> --confirm
```

### Step 4: Report

The reconcile prints the priority-ordered sections (📣 STILL_SERVING — killed
MVPs whose campaigns are still deliverable per the CSV, **including waived
rows** (backend_keep waives the backend, not the ads), with per-campaign pause
instructions — the only rows needing a human in Google Ads right now · 🔥
MONEY_LEAK — killed with recent paid traffic in window · 🚨 OVERDUE — due ≥
`thresholds.teardown_overdue_days` (default 14) since kill · ⏳ DUE · ✅
VERIFIED · 🤝 WAIVED). Present these sections to the operator verbatim.

### Step 5: Team message (conversational hand-off)

Render the copy-paste team message — the header plus one block of action items
per member (obligations included, so it runs here rather than at x4):

```bash
python3 .claude/scripts/lib/iterate_cross_verdicts.py \
  --scores .runs/iterate-cross-scores.json \
  --obligations .runs/iterate-cross-teardown-obligations.json \
  --emit-team-message
```

Relay the stdout verbatim in the conversation — nothing is written to disk.
The operator replaces the `<google-doc-link>` placeholder with the run's
results doc before forwarding to the team chat. Members with no action items
are omitted by design; orphan MISSING_PROJECT_NAME rows and archived/promoted
reference rows stay in the report only.

Known limitations (pre-existing exposure, unchanged by the csv evidence): a
killed `ga_only` MVP whose score-row name differs from its config mapping key
gets no ads auto-evidence (scores lookup misses → `none_in_window`), and a
0-click campaign that fails to bucket to any MVP is skipped before the
unmatched file entirely — both remain covered only by the operator's own
Google Ads review.

**POSTCONDITIONS:**
- `.runs/iterate-cross-teardown-obligations.json` exists with one obligation per killed non-orphan config row, each carrying `teardown_state` ∈ {due, verified, waived} and the three evidence lines
- Ledger rows for those MVPs carry `teardown_state` + `teardown_evidence` (frozen rows NOT unfrozen)
- Team message printed to stdout (header + per-member action items, teardown rows folded in)

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x4b`.

```bash
python3 -c "import json, yaml; ob=json.load(open('.runs/iterate-cross-teardown-obligations.json')); rows=ob.get('obligations',[]); assert isinstance(rows, list), 'obligations missing'; allowed={'due','verified','waived'}; bad=[r.get('mvp','?') for r in rows if r.get('teardown_state') not in allowed or not r.get('db') or not r.get('hosting') or not r.get('ads')]; assert not bad, 'malformed obligations: %s' % bad; cfg=yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}; killed={n for n,m in (cfg.get('mvp_mappings') or {}).items() if isinstance(m, dict) and m.get('lifecycle_status')=='killed' and not n.startswith('__orphan')}; got={r.get('mvp') for r in rows}; assert killed <= got, 'killed rows missing obligations: %s' % sorted(killed-got); led={}; [led.__setitem__(r.get('mvp'), r) for r in (json.loads(l) for l in open('experiment/mvp-decision-ledger.jsonl') if l.strip())]; missing=[m for m in got if m in led and 'teardown_state' not in led[m]]; assert not missing, 'ledger rows missing teardown_state: %s' % missing"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x4b
```

**NEXT:** Skill states complete.
