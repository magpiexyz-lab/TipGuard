# STATE x5: PAY_INTENT_VERDICT

Self-contained Phase 2 cross-MVP verdict. This state does not run or reuse
state-x0/x0a/x0b/x1/x1a/x2/x3/x4. It owns
`.runs/iterate-cross-phase2-context.json` and writes its own Phase 2 artifacts.

**PRECONDITIONS:**
- `~/.posthog/personal-api-key` exists and has scope `query:read` and `project:read`
- Supabase auth resolvable and Railway CLI logged in (Step 0 preflight; softened to warnings by `require_db_ground_truth: false`)
- `.runs/iterate-cross-ga-clicks.csv` exists, is fresh, and was exported from Google Ads
- Phase 2 campaign names / `utm_campaign` values contain the configured Phase 2 token

<!-- Diagnostic invariants inherited from phase-1 (self-contained does NOT mean
     diagnostics-free — dropping one of these is a regression, see #1829):
     orphan-overlap merge (Step 3b, phase-1 sibling: state-x0), plus the
     phase2-only foreign-campaign (Step 5.6), wiring-liveness and
     price-timeline flags (Steps 4/5.5 data -> verdicts),
     phase2-scoped ads-stopped awareness (Step 5 merge status columns ->
     Step 7 phase2_ads_all_stopped flag/action; phase-1 sibling: the
     money-leak 3-way deliverability wording), and ledger-free stalled
     triage (Step 7 annotate_stalled with prev_ledger=None; phase-1
     sibling: state-x3 — streak/escalation deliberately omitted, no
     phase2 ledger exists). -->

**ACTIONS:**

### Step 0: Auth preflight (fail fast)

Same one-shot gate as state-x0 Step 0, with the phase2 required set (PostHog +
Supabase + Railway; x5 never uses the Vercel channel). All missing logins are
listed at once before any data work. Supabase/Railway soften to warnings under
`require_db_ground_truth: false`; the full Supabase resolution chain (env var,
token file, macOS Keychain, live probe) is checked — not just file presence.

```bash
set +e
PREFLIGHT_PAYLOAD=$(python3 .claude/scripts/lib/iterate_cross_auth.py --mode cross-phase2 --emit-payload)
PREFLIGHT_RC=$?
set -e
[ -n "$PREFLIGHT_PAYLOAD" ] || { echo "STOP: auth preflight crashed (no payload)" >&2; exit 1; }
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-cross-auth-preflight.json \
  --payload "$PREFLIGHT_PAYLOAD" \
  --skill iterate-cross-phase2
if [ "$PREFLIGHT_RC" -ne 0 ]; then
  echo "STOP: auth preflight failed — the checklist above lists every missing login and its fix. Log in, then re-run /iterate --cross --phase2." >&2
  exit 1
fi
```

### Step 1: Resolve Phase 2 config and fail closed

Resolve `phase2.utm_campaign_like` from `experiment/iterate-cross-config.yaml`.
The default is `%phase2%`. An explicitly empty value is a STOP, and
`fallback_all_gclid` is forced false for this mode.

```bash
python3 - <<'PY'
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    yaml = None

cfg_path = "experiment/iterate-cross-config.yaml"
cfg = {}
if yaml is not None and os.path.exists(cfg_path):
    cfg = yaml.safe_load(open(cfg_path)) or {}

phase2 = cfg.get("phase2") or {}
phase_filter = phase2.get("utm_campaign_like", "%phase2%")
if phase_filter is None or not str(phase_filter).strip():
    sys.exit(
        "STOP: /iterate --cross --phase2 requires phase2.utm_campaign_like. "
        "Set it to a non-empty LIKE pattern such as %phase2%."
    )
phase_filter = str(phase_filter).strip()

api_key_path = os.path.expanduser("~/.posthog/personal-api-key")
if not os.path.exists(api_key_path):
    sys.exit(
        "STOP: PostHog personal API key not found at ~/.posthog/personal-api-key. "
        "Create one with query:read and project:read, then re-run /iterate --cross --phase2."
    )
api_key = open(api_key_path).read().strip()

project_id = cfg.get("posthog_project_id")
if not project_id:
    r = subprocess.run(
        [
            "curl",
            "-s",
            "https://us.i.posthog.com/api/projects/",
            "-H",
            f"Authorization: Bearer {api_key}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("STOP: Could not discover PostHog project ID. Check API key scope/project access.")
    try:
        project_id = json.loads(r.stdout)["results"][0]["id"]
    except Exception as exc:
        sys.exit(f"STOP: Could not parse PostHog projects response: {exc}")

ctx_path = ".runs/iterate-cross-phase2-context.json"
ctx = json.load(open(ctx_path)) if os.path.exists(ctx_path) else {
    "skill": "iterate-cross-phase2",
    "completed_states": [],
}
ctx.pop("phase2_db_merge", None)
ctx.update({
    "mode": "cross-phase2",
    "phase": 2,
    "window_days": int(cfg.get("window_days", 90)),
    "posthog_project_id": str(project_id),
    "phase2_utm_campaign_like": phase_filter,
    "phase2_run_token": datetime.now(timezone.utc).isoformat(),
    "fallback_all_gclid": False,
    "mvps": ctx.get("mvps", []),
})
json.dump(ctx, open(ctx_path, "w"), indent=2)
PY
```

### Step 2: Restate the blocking GA CSV gate

The CSV is the sole paid-click source. It must exist, be no more than 24 hours
old, and have a valid header. Validation uses the same Phase 2 campaign filter
as the numerator. A valid CSV with zero matching Phase 2 rows is accepted as a
phase-scoped zero-click input.

```bash
CSV=.runs/iterate-cross-ga-clicks.csv
MAX_AGE_HOURS=24
PHASE2_UTM_CAMPAIGN_LIKE=$(python3 -c "import json; print(json.load(open('.runs/iterate-cross-phase2-context.json'))['phase2_utm_campaign_like'])")
WINDOW_DAYS=$(python3 -c "import json; print(json.load(open('.runs/iterate-cross-phase2-context.json')).get('window_days', 90))")

print_export_instructions() {
  cat >&2 <<EOF

How to export (~30 seconds):

  1. Open the MCC parent campaigns view in Google Ads
  2. Set the date range to last ${WINDOW_DAYS} days
  3. Make sure the columns include at minimum: Campaign, Clicks
     (stalled-cause diagnosis: + Impr. — without it a stalled phase-2
      campaign reads "no telemetry"; use the plain Impr. count column)
     (stalled age gate: + Start date — phase2 has no ledger fallback, so
      without it stalled detection stays silent)
     (deliverability: + Campaign status, Status, Status reasons — without
      them a paused phase-2 campaign reads "keep collecting" forever)
  4. Click Download icon -> CSV
  5. Save the file as: .runs/iterate-cross-ga-clicks.csv
  6. Re-run /iterate --cross --phase2

The skill cannot produce trustworthy Phase 2 verdicts without fresh paid-click data.
EOF
}

if [ ! -f "$CSV" ]; then
  echo "STOP: /iterate --cross --phase2 requires a Google Ads click CSV." >&2
  print_export_instructions
  exit 1
fi

AGE_HOURS=$(python3 -c "import os, time; print(int((time.time() - os.path.getmtime('$CSV')) / 3600))")
if [ "$AGE_HOURS" -gt "$MAX_AGE_HOURS" ]; then
  echo "STOP: GA CSV is ${AGE_HOURS}h old (max ${MAX_AGE_HOURS}h)." >&2
  echo "File: $CSV" >&2
  print_export_instructions
  exit 1
fi

python3 .claude/scripts/lib/iterate_cross_ga.py validate-csv \
  --ga-csv "$CSV" \
  --context .runs/iterate-cross-phase2-context.json \
  --phase-filter "$PHASE2_UTM_CAMPAIGN_LIKE" || exit 1
```

### Step 3: Discover Phase 2 MVPs and orphan tracking

Run a lean discovery query for paid-gclid traffic whose
`properties.utm_campaign` matches the Phase 2 filter. Also run a minimal
phase-scoped orphan query for events where `project_name` is NULL/empty; those
synthetic orphan rows are the source of `missing_project_name`.

```bash
python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, ".claude/scripts/lib")
from gclid_filter import PAID_GCLID_FILTER
from iterate_cross_posthog_batch import paginate_discovery_query

ctx_path = ".runs/iterate-cross-phase2-context.json"
ctx = json.load(open(ctx_path))
project_id = ctx["posthog_project_id"]
window_days = int(ctx.get("window_days", 90))
phase_filter = ctx["phase2_utm_campaign_like"]
api_key = open(os.path.expanduser("~/.posthog/personal-api-key")).read().strip()
values = {"empty": "", "phase_campaign": phase_filter}

phase_clause = (
    "AND properties.utm_campaign IS NOT NULL "
    "AND toString(properties.utm_campaign) LIKE {phase_campaign} "
)

sql = (
    "SELECT properties.project_name AS mvp_key, "
    "max(toString(properties.utm_campaign)) AS sample_utm_campaign, "
    "count(DISTINCT distinct_id) AS gclid_visitors_phase2, "
    "count() AS phase2_events, "
    "min(timestamp) AS first_seen, max(timestamp) AS last_seen "
    f"FROM events WHERE {PAID_GCLID_FILTER} "
    f"{phase_clause}"
    "AND properties.project_name IS NOT NULL "
    "AND properties.project_name != {empty} "
    f"AND timestamp >= now() - INTERVAL {window_days} DAY "
    "GROUP BY mvp_key HAVING gclid_visitors_phase2 > 0 "
    "ORDER BY gclid_visitors_phase2 DESC LIMIT 200"
)
# paginate_discovery_query calls in x5 intentionally stay at the library's
# default max_time_seconds=30: these are phase-scoped aggregates (utm_campaign
# LIKE-filtered), far smaller than x0's whole-portfolio 365-day scans, and have
# never been implicated in the long-window timeouts. Raise via the
# max_time_seconds kwarg only if they start failing.
rows, metadata = paginate_discovery_query(sql, values, project_id, api_key, page_size=200)
json.dump(
    {"results": rows, "_phase2_canonical_pagination_status": metadata},
    open(".runs/_iterate-cross-phase2-discover.json", "w"),
    indent=2,
)

orphan_sql = (
    "SELECT splitByChar('.', domain(coalesce(properties.$current_url, '')))[1] AS host_prefix, "
    "max(toString(properties.utm_campaign)) AS sample_utm_campaign, "
    "count(DISTINCT distinct_id) AS gclid_visitors_phase2, "
    "count() AS phase2_events, "
    "min(timestamp) AS first_seen, max(timestamp) AS last_seen "
    f"FROM events WHERE {PAID_GCLID_FILTER} "
    f"{phase_clause}"
    "AND (properties.project_name IS NULL OR properties.project_name = {empty}) "
    f"AND timestamp >= now() - INTERVAL {window_days} DAY "
    "GROUP BY host_prefix HAVING gclid_visitors_phase2 > 0 "
    "ORDER BY gclid_visitors_phase2 DESC LIMIT 50"
)
orphan_rows, orphan_metadata = paginate_discovery_query(
    orphan_sql,
    values,
    project_id,
    api_key,
    page_size=50,
)
json.dump(
    {"results": orphan_rows, "_phase2_orphan_pagination_status": orphan_metadata},
    open(".runs/_iterate-cross-phase2-orphan.json", "w"),
    indent=2,
)

cfg = {}
try:
    import yaml
    if os.path.exists("experiment/iterate-cross-config.yaml"):
        cfg = yaml.safe_load(open("experiment/iterate-cross-config.yaml")) or {}
except ImportError:
    pass
mappings = cfg.get("mvp_mappings") or {}

mvps = []
for row in rows:
    name = row[0]
    mapping = mappings.get(name) or {}
    visitors = int(row[2] or 0)
    mvps.append({
        "name": name,
        "owner": mapping.get("owner"),
        "deploy_domain": mapping.get("deploy_domain"),
        "sample_utm_campaign": row[1],
        "gclid_visitors": visitors,
        "gclid_visitors_phase2": visitors,
        "phase2_events": int(row[3] or 0),
        "first_seen": row[4],
        "last_seen": row[5],
        "phase_match": True,
        "orphan": False,
        "partial_tracking_pct": None,
        "ga_clicks": 0,
        "ga_conv": 0.0,
        "ga_campaigns": [],
        "pay_intents": 0,
    })

for row in orphan_rows:
    host = row[0] or "unknown"
    visitors = int(row[2] or 0)
    mvps.append({
        "name": f"__orphan_{host}__",
        "owner": None,
        "deploy_domain": None,
        "sample_utm_campaign": row[1],
        "gclid_visitors": visitors,
        "gclid_visitors_phase2": visitors,
        "phase2_events": int(row[3] or 0),
        "first_seen": row[4],
        "last_seen": row[5],
        "phase_match": True,
        "orphan": True,
        "partial_tracking_pct": None,
        "ga_clicks": 0,
        "ga_conv": 0.0,
        "ga_campaigns": [],
        "pay_intents": 0,
    })

ctx["mvps"] = mvps
ctx["_phase2_canonical_pagination_status"] = metadata
ctx["_phase2_orphan_pagination_status"] = orphan_metadata
json.dump(ctx, open(ctx_path, "w"), indent=2)
PY
```

### Step 3b: Merge orphan overlap (same-deploy partial tracking)

Phase-scoped port of the state-x0 orphan merge (#1829): for each
`(canonical, __orphan_<host>__)` pair sharing a `match_key`, query the paid
gclid intersection and absorb high-overlap orphans (≥ the
`orphan_merge_overlap_threshold` config value, default 0.70) into their
canonical row with `partial_tracking_pct`, instead of rendering a misleading
standalone MISSING_PROJECT_NAME verdict. MUST run before Step 4/5/5.5: the GA
merge would otherwise route paid clicks onto an orphan row that later
disappears, and the DB triage set must equal the ctx set (registry VERIFY).

```bash
python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, ".claude/scripts/lib")
from iterate_cross_classify import apply_orphan_merge_to_mvps, build_orphan_pairs
from iterate_cross_posthog_batch import compute_orphan_overlap

ctx_path = ".runs/iterate-cross-phase2-context.json"
ctx = json.load(open(ctx_path))
api_key = open(os.path.expanduser("~/.posthog/personal-api-key")).read().strip()

cfg = {}
try:
    import yaml
    if os.path.exists("experiment/iterate-cross-config.yaml"):
        cfg = yaml.safe_load(open("experiment/iterate-cross-config.yaml")) or {}
except ImportError:
    pass
threshold = float(cfg.get("orphan_merge_overlap_threshold", 0.70))

pairs = build_orphan_pairs(ctx.get("mvps", []))
phase_clause = (
    "AND properties.utm_campaign IS NOT NULL "
    "AND toString(properties.utm_campaign) LIKE {phase_campaign} "
)
overlap = {}
if pairs:
    pq = cfg.get("posthog_query") or {}
    overlap = compute_orphan_overlap(
        pairs,
        ctx["posthog_project_id"],
        api_key,
        int(ctx.get("window_days", 90)),
        phase_clause=phase_clause,
        phase_values={"phase_campaign": ctx["phase2_utm_campaign_like"]},
        cache_path=".runs/_iterate-cross-phase2-orphan-overlap.json",
        max_time_seconds=int(pq.get("max_time_seconds", 120)),
        cooldown_seconds=int(pq.get("overlap_cooldown_seconds", 300)),
        failure_sleep_seconds=int(pq.get("overlap_failure_sleep_seconds", 20)),
        max_passes=int(pq.get("overlap_max_passes", 3)),
    )
ctx["mvps"], audit = apply_orphan_merge_to_mvps(
    ctx.get("mvps", []),
    overlap,
    threshold=threshold,
)
for entry in audit:
    if entry.get("action") == "merged":
        entry["attribution_gap_note"] = (
            "High gclid overlap = same deploy; the unattributed events are "
            "typically SDK auto-events missing the project_name session "
            "super-property (template defect #1828)."
        )
json.dump(
    {"pairs": pairs, "threshold": threshold, "audit": audit},
    open(".runs/_iterate-cross-phase2-orphan-merge.json", "w"),
    indent=2,
)
json.dump(ctx, open(ctx_path, "w"), indent=2)
merged_n = sum(1 for a in audit if a.get("action") == "merged")
print(f"orphan-merge: {len(pairs)} pair(s), {merged_n} merged, {len(ctx['mvps'])} MVP rows remain")
PY

rm -f .runs/_iterate-cross-phase2-orphan-overlap.json
```

### Step 4: Gather phase-scoped pay_intent numerator

Count distinct paid-gclid users firing `pay_intent`, filtered by the same
`properties.utm_campaign LIKE phase2.utm_campaign_like` value used in discovery
and GA merge.

```bash
python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, ".claude/scripts/lib")
from gclid_filter import PAID_GCLID_FILTER
from iterate_cross_posthog_batch import paginate_discovery_query

ctx_path = ".runs/iterate-cross-phase2-context.json"
ctx = json.load(open(ctx_path))
project_id = ctx["posthog_project_id"]
window_days = int(ctx.get("window_days", 90))
phase_filter = ctx["phase2_utm_campaign_like"]
api_key = open(os.path.expanduser("~/.posthog/personal-api-key")).read().strip()
values = {"empty": "", "phase_campaign": phase_filter, "pay_intent": "pay_intent"}

sql = (
    "SELECT properties.project_name AS mvp_key, "
    "count(DISTINCT distinct_id) AS pay_intents, "
    "min(timestamp) AS first_pay_intent_at, max(timestamp) AS last_pay_intent_at, "
    "max(toString(properties.price_cents)) AS pay_intent_price_cents, "
    "count(DISTINCT toString(properties.price_cents)) AS pay_intent_price_variants "
    "FROM events WHERE event = {pay_intent} "
    f"AND {PAID_GCLID_FILTER} "
    "AND properties.utm_campaign IS NOT NULL "
    "AND toString(properties.utm_campaign) LIKE {phase_campaign} "
    "AND properties.project_name IS NOT NULL "
    "AND properties.project_name != {empty} "
    f"AND timestamp >= now() - INTERVAL {window_days} DAY "
    "GROUP BY mvp_key ORDER BY pay_intents DESC LIMIT 200"
)
rows, metadata = paginate_discovery_query(sql, values, project_id, api_key, page_size=200)
json.dump(
    {"results": rows, "_phase2_pay_intent_pagination_status": metadata},
    open(".runs/_iterate-cross-phase2-pay-intents.json", "w"),
    indent=2,
)

by_name = {m["name"]: m for m in ctx.get("mvps", [])}
for row in rows:
    name = row[0]
    target = by_name.get(name)
    if target is None:
        target = {
            "name": name,
            "owner": None,
            "deploy_domain": None,
            "sample_utm_campaign": None,
            "gclid_visitors": 0,
            "gclid_visitors_phase2": 0,
            "phase2_events": 0,
            "first_seen": None,
            "last_seen": None,
            "phase_match": True,
            "orphan": False,
            "partial_tracking_pct": None,
            "ga_clicks": 0,
            "ga_conv": 0.0,
            "ga_campaigns": [],
            "pay_intent_price_cents": 0,
            "pay_intent_price_variants": 0,
        }
        ctx.setdefault("mvps", []).append(target)
        by_name[name] = target
    target["pay_intents"] = int(row[1] or 0)
    target["first_pay_intent_at"] = row[2]
    target["last_pay_intent_at"] = row[3]
    # No pay-intent row leaves price at 0. max(toString(...)) is lexicographic;
    # one fake-door price per MVP is the invariant, and variants >1 are flagged.
    target["pay_intent_price_cents"] = float(row[4] or 0)
    target["pay_intent_price_variants"] = int(row[5] or 0)

# Price-variant timeline (price_change_mid_phase flag input). Separate query
# on purpose: adding GROUP BY price to the numerator above would corrupt its
# count(DISTINCT distinct_id) — one user can intent at two prices.
variant_sql = (
    "SELECT properties.project_name AS mvp_key, "
    "toString(properties.price_cents) AS price, "
    "count(DISTINCT distinct_id) AS pay_intents, "
    "min(timestamp) AS first_at, max(timestamp) AS last_at "
    "FROM events WHERE event = {pay_intent} "
    f"AND {PAID_GCLID_FILTER} "
    "AND properties.utm_campaign IS NOT NULL "
    "AND toString(properties.utm_campaign) LIKE {phase_campaign} "
    "AND properties.project_name IS NOT NULL "
    "AND properties.project_name != {empty} "
    f"AND timestamp >= now() - INTERVAL {window_days} DAY "
    "GROUP BY mvp_key, price ORDER BY mvp_key, first_at LIMIT 200"
)
variant_rows, _ = paginate_discovery_query(variant_sql, values, project_id, api_key, page_size=200)
for row in variant_rows:
    target = by_name.get(row[0])
    if target is None:
        continue
    target.setdefault("pay_intent_price_variant_rows", []).append({
        "price_cents": row[1],
        "pay_intents": int(row[2] or 0),
        "first_at": row[3],
        "last_at": row[4],
    })

# PH-side wiring liveness (pay_intent_wiring_unproven flag input): last
# pay_intent EVER per MVP — deliberately NO gclid and NO phase filter, so a
# dev test or a fresh dayzero-probe proves the wiring. Fixed 365d lookback.
liveness_sql = (
    "SELECT properties.project_name AS mvp_key, max(timestamp) AS last_any "
    "FROM events WHERE event = {pay_intent} "
    "AND properties.project_name IS NOT NULL "
    "AND properties.project_name != {empty} "
    "AND timestamp >= now() - INTERVAL 365 DAY "
    "GROUP BY mvp_key LIMIT 200"
)
liveness_rows, _ = paginate_discovery_query(liveness_sql, values, project_id, api_key, page_size=200)
for row in liveness_rows:
    target = by_name.get(row[0])
    if target is not None:
        target["ph_last_pay_intent_any_at"] = row[1]

ctx["_phase2_pay_intent_pagination_status"] = metadata
json.dump(ctx, open(ctx_path, "w"), indent=2)
PY
```

### Step 5: Merge the phase-filtered GA denominator

Merge Google Ads clicks with the same resolved Phase 2 filter. The verdict uses
`ga_clicks` only as denominator; PostHog `gclid_visitors_phase2` is diagnostic.

```bash
PHASE2_UTM_CAMPAIGN_LIKE=$(python3 -c "import json; print(json.load(open('.runs/iterate-cross-phase2-context.json'))['phase2_utm_campaign_like'])")

python3 .claude/scripts/lib/iterate_cross_ga.py merge \
  --ga-csv .runs/iterate-cross-ga-clicks.csv \
  --context .runs/iterate-cross-phase2-context.json \
  --config experiment/iterate-cross-config.yaml \
  --unmatched-out .runs/_iterate-cross-phase2-ga-unmatched.json \
  --phase-filter "$PHASE2_UTM_CAMPAIGN_LIKE"

python3 - <<'PY'
import json

ctx_path = ".runs/iterate-cross-phase2-context.json"
ctx = json.load(open(ctx_path))
for m in ctx.get("mvps", []):
    m.setdefault("gclid_visitors_phase2", m.get("gclid_visitors", 0) or 0)
    m.setdefault("phase2_events", 0)
    m.setdefault("pay_intents", 0)
    m.setdefault("phase_match", True)
    m.setdefault("orphan", False)
json.dump(ctx, open(ctx_path, "w"), indent=2)
PY
```

### Step 5.5: Merge DB pay-intent ground truth

Merge DB `public.pay_intent` counts using the same `window_days` and
`phase2_utm_campaign_like` already resolved into the context. Supabase
(Management API) is the primary backend; Railway Postgres (psql) is a strict
per-MVP fallback for MVPs with `mvp_mappings.<name>.railway_project_id`
(locked by x0b or set by the operator — x5 never fuzzy-matches). This step
runs after the GA merge because Step 5 can add `ga_only` MVP rows.

```bash
python3 .claude/scripts/lib/iterate_cross_phase2_db.py merge \
  --context .runs/iterate-cross-phase2-context.json \
  --config experiment/iterate-cross-config.yaml \
  --triage-out .runs/_iterate-cross-phase2-db-unmatched.json
```

### Step 5.6: Detect foreign-campaign traffic (cross-MVP ad misconfig)

MVP X receiving paid events tagged with MVP Y's `utm_campaign` means campaign
Y's ad Final URL or a sitelink points at X's site — Y's budget buys clicks
that can never convert, invisible to every per-MVP check. Resolve each
observed `(project_name, utm_campaign)` pair through the same campaign→MVP
mapping the GA merge uses (incl. `ga_campaign_aliases`), exempt
`cross_campaign_whitelist` entries, and stamp two-sided
`foreign_campaign_traffic` flags via the `extra_sanity_flags` channel
(single writer: this step, wholesale assignment — never append).

```bash
python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, ".claude/scripts/lib")
from gclid_filter import PAID_GCLID_FILTER
from iterate_cross_ga import _load_aliases, compute_foreign_campaign_flags
from iterate_cross_posthog_batch import paginate_discovery_query
from iterate_cross_verdicts import load_config

ctx_path = ".runs/iterate-cross-phase2-context.json"
ctx = json.load(open(ctx_path))
project_id = ctx["posthog_project_id"]
window_days = int(ctx.get("window_days", 90))
api_key = open(os.path.expanduser("~/.posthog/personal-api-key")).read().strip()
values = {"empty": "", "phase_campaign": ctx["phase2_utm_campaign_like"]}

sql = (
    "SELECT properties.project_name AS mvp_key, "
    "toString(properties.utm_campaign) AS utm, "
    "count(DISTINCT distinct_id) AS visitors "
    f"FROM events WHERE {PAID_GCLID_FILTER} "
    "AND properties.utm_campaign IS NOT NULL "
    "AND toString(properties.utm_campaign) LIKE {phase_campaign} "
    "AND properties.project_name IS NOT NULL "
    "AND properties.project_name != {empty} "
    f"AND timestamp >= now() - INTERVAL {window_days} DAY "
    "GROUP BY mvp_key, utm ORDER BY visitors DESC LIMIT 200"
)
rows, _ = paginate_discovery_query(sql, values, project_id, api_key, page_size=200)

config = load_config("experiment/iterate-cross-config.yaml")
aliases = _load_aliases("experiment/iterate-cross-config.yaml")
flags_by_name, audit = compute_foreign_campaign_flags(
    rows,
    ctx.get("mvps", []),
    aliases=aliases,
    whitelist=config.get("cross_campaign_whitelist") or [],
)
for m in ctx.get("mvps", []):
    m["extra_sanity_flags"] = flags_by_name.get(m.get("name"), [])

json.dump(
    {"rows": rows, "audit": audit},
    open(".runs/_iterate-cross-phase2-foreign-campaigns.json", "w"),
    indent=2,
)
json.dump(ctx, open(ctx_path, "w"), indent=2)
flagged = sum(1 for a in audit if a.get("action") == "flagged")
print(f"foreign-campaigns: {len(rows)} (mvp, utm) pairs, {flagged} cross-MVP flag(s)")
PY
```

### Step 6: Build phase-scoped integrity issues

Build the three issue flags locally because x5 skips x1a:
`missing_project_name`, `ga_clicks_without_ph_traffic`, and `no_event_data`.

```bash
ISSUES_PAYLOAD=$(python3 - <<'PY'
import json

ctx = json.load(open(".runs/iterate-cross-phase2-context.json"))
issues = []
for m in ctx.get("mvps", []):
    name = m.get("name")
    ga_clicks = int(m.get("ga_clicks", 0) or 0)
    phase_visitors = int(m.get("gclid_visitors_phase2", m.get("gclid_visitors", 0)) or 0)
    phase_events = int(m.get("phase2_events", 0) or 0)
    issues.append({
        "name": name,
        "missing_project_name": bool(m.get("orphan")),
        "ga_clicks_without_ph_traffic": ga_clicks > 0 and phase_visitors == 0,
        "no_event_data": phase_events == 0 and phase_visitors == 0,
    })
print(json.dumps({"mvps": issues}))
PY
)

bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-cross-phase2-issues.json \
  --payload "$ISSUES_PAYLOAD" \
  --skill iterate-cross-phase2
```

### Step 7: Compute pay-intent verdict and emit Phase 2 report

Use `compute_pay_intent_verdict(mvp, issues, thresholds, reference_now=ref)`
and write Phase 2 artifacts only. After building scores, run the ledger-free
stalled triage (`annotate_stalled` with `prev_ledger=None`): phase2 has no
decision ledger, so run-over-run deltas, streak carry, and escalation stay
inert (`stalled_streak` never exceeds 1, `stalled_escalated` is always False,
no kill-proposal fold-in — those semantics need ledger streak carry, see
state-x3, which also holds the cause legend). Lifetime-zero detection, the
ETA-based `stalled_slow` bucket, and the zero_serve / weak_demand /
no_telemetry cause triage all work without a ledger.

```bash
SCORES_PAYLOAD=$(python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, ".claude/scripts/lib")
from iterate_cross_verdicts import (
    VERDICT_GA_NO_PH_TRACKING,
    VERDICT_GO,
    VERDICT_INSUFFICIENT,
    VERDICT_MISSING_PROJECT_NAME,
    VERDICT_NO_DATA,
    VERDICT_NO_GO,
    annotate_stalled,
    compute_pay_intent_verdict,
    load_config,
    pay_intent_action_line,
    pay_intent_ads_stopped_action,
    pay_intent_go_rank_key,
    pay_intent_revenue_cell,
    pay_intent_score_key,
    reference_now_from_records,
)

ctx = json.load(open(".runs/iterate-cross-phase2-context.json"))
issues_data = json.load(open(".runs/iterate-cross-phase2-issues.json"))
issues_by_name = {m["name"]: m for m in issues_data.get("mvps", [])}
config = load_config("experiment/iterate-cross-config.yaml")
thresholds = config["thresholds"]

# Deterministic reference time, mirroring phase-1: max last_seen across rows;
# ga_scraped_at (CSV mtime, stamped by the Step 5 merge) covers ga_only-only
# fleets whose rows carry no last_seen. Never wall-clock.
ref = reference_now_from_records(ctx.get("mvps", [])) or ctx.get("ga_scraped_at")
floor2 = thresholds.get("pay_intent_visitors_floor", thresholds["visitors_floor"])

scores = [
    compute_pay_intent_verdict(
        m, issues_by_name.get(m.get("name"), {}), thresholds, reference_now=ref
    )
    for m in ctx.get("mvps", [])
]

# Ledger-free stalled triage (see the Step 7 prose for the deliberate
# streak/escalation omission). visitors_floor override: the phase2 sample
# gate and ETA target are clicks against pay_intent_visitors_floor.
annotate_stalled(scores, {**thresholds, "visitors_floor": floor2}, None, reference_now=ref)

scores = sorted(scores, key=pay_intent_score_key)
payload = {
    "phase": 2,
    "phase2_utm_campaign_like": ctx["phase2_utm_campaign_like"],
    "thresholds": thresholds,
    "window_days": ctx.get("window_days", 90),
    "mvps": scores,
}

theta = thresholds.get("pay_intent_rate_go", 0.02)
floor = thresholds.get("pay_intent_visitors_floor", thresholds["visitors_floor"])
report = [
    "# Phase 2 Pay-Intent Verdict",
    "",
    f"- Filter: `{ctx['phase2_utm_campaign_like']}`",
    f"- Window: {ctx.get('window_days', 90)} days",
    f"- Click floor: {floor}",
    f"- Pay-intent GO threshold: {theta:.2%}",
    "",
    "| MVP | Verdict | Source | GA clicks | Pay intents | Pay-intent rate | Rev/click | Action |",
    "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
]
if not scores:
    report.append("| No Phase 2 candidates matched the configured filter. | - | - | 0 | 0 | 0.00% | $0.00 | Check campaign naming and CSV export. |")
else:
    for s in scores:
        metrics = s["metrics"]
        flags = s.get("tracking_sanity_flags") or []
        high_flag = next((f for f in flags if f.get("severity") == "high"), None)
        source_label = "db" if str(metrics.get("pay_intent_source", "ph")).startswith("db_") else "ph"
        source_cell = source_label + (" ⚠" if high_flag else "")
        flag_suffix = f" ⚠ {high_flag['flag']}" if high_flag else ""
        db_note = ""
        if source_label == "db":
            db_note = (
                f" · DB={metrics.get('pay_intents_db')} "
                f"(PH={metrics.get('pay_intents_posthog')}, "
                f"unattributed={metrics.get('pay_intents_unattributed')})"
            )
        # Stopped-ads override first: "keep collecting" / "debug tracking" are
        # wrong when the phase2 denominator can no longer grow.
        action = pay_intent_ads_stopped_action(s) or pay_intent_action_line(
            s["headline_verdict"],
            s.get("name") or "(unknown)",
            metrics["pay_intents"],
            s["visitors_needed"],
            floor,
            theta,
        )
        rev_cell = pay_intent_revenue_cell(metrics)
        report.append(
            f"| {s.get('name') or '(unknown)'} | {s['headline_verdict']} | {source_cell} | "
            f"{metrics['ga_clicks']} | {metrics['pay_intents']} | "
            f"{metrics['pay_intent_rate']:.2%} | {rev_cell} | {action} |"
        )

go_ranked = [
    s for s in scores
    if s.get("headline_verdict") == VERDICT_GO
]
go_ranked = sorted(
    go_ranked,
    key=pay_intent_go_rank_key,
)
report.extend(["", "## GO Ranking", ""])
if go_ranked:
    for idx, s in enumerate(go_ranked[:10], 1):
        metrics = s["metrics"]
        rev_cell = pay_intent_revenue_cell(metrics)
        report.append(
            f"{idx}. {s.get('name')} - {rev_cell}/click "
            f"(rate {metrics['pay_intent_rate']:.2%}, "
            f"{metrics['pay_intents']}/{metrics['ga_clicks']})"
        )
else:
    report.append("No Phase 2 GO verdicts yet.")

diag_lines = []
for s in scores:
    pct = s.get("partial_tracking_pct")
    if pct is not None:
        diag_lines.append(
            f"- {s.get('name')}: [info] partial_tracking — merged same-deploy orphan traffic; "
            f"{pct:.1%} of its unattributed visitors were not covered by canonical tracking "
            "(auto-event attribution gap, see #1828)"
        )
    for f in (s.get("tracking_sanity_flags") or []):
        diag_lines.append(
            f"- {s.get('name')}: [{f.get('severity')}] {f.get('flag')} — {f.get('message')}"
        )
    met = s.get("metrics") or {}
    if met.get("stalled_bucket") in ("stalled", "stalled_slow"):
        eta = met.get("stalled_eta_days")
        stopped_note = (
            " (campaign stopped — stall explained by pause)"
            if s.get("phase2_ads_all_stopped") is True
            else ""
        )
        diag_lines.append(
            f"- {s.get('name')}: [stalled] {met['stalled_bucket']} "
            f"cause={met.get('stalled_cause') or '—'} age={met.get('stalled_age_days')}d "
            f"eta={eta if eta is not None else '∞'}d{stopped_note}"
        )
report.extend(["", "## Tracking diagnostics", ""])
report.extend(diag_lines if diag_lines else ["No tracking anomalies flagged."])

open(".runs/iterate-cross-phase2-report.md", "w").write("\n".join(report) + "\n")
print(json.dumps(payload))
PY
)

bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-cross-phase2-scores.json \
  --payload "$SCORES_PAYLOAD" \
  --skill iterate-cross-phase2

echo "Wrote .runs/iterate-cross-phase2-scores.json"

python3 .claude/scripts/lib/iterate_cross_verdicts.py \
  --scores .runs/iterate-cross-phase2-scores.json \
  --config experiment/iterate-cross-config.yaml \
  --phase 2 --emit-team-message
```

Relay the team-message stdout verbatim in the conversation (header + one block
of pay-intent action items per member; nothing is written to disk). The
operator replaces the results-doc placeholder before forwarding.

**POSTCONDITIONS:**
- `.runs/iterate-cross-phase2-context.json` has `phase: 2`, non-empty `phase2_utm_campaign_like`, and `fallback_all_gclid: false`
- `.runs/iterate-cross-phase2-issues.json` exists with phase-scoped issue flags
- `.runs/iterate-cross-phase2-scores.json` exists with pay-intent verdict metrics
- `.runs/iterate-cross-phase2-report.md` is non-empty; the team message printed to stdout
- `.runs/_iterate-cross-phase2-ga-unmatched.json` exists for operator triage
- The Step 3b orphan-merge audit and Step 5.6 foreign-campaigns audit
  intermediates were written for operator review (same diagnostic class as the
  Step 3 discover/orphan files, intentionally not VERIFY-gated; paths are
  documented in their steps above)

**VERIFY:** see `state-registry.json` entry for `iterate-cross-phase2.x5`.

```bash
python3 -c "import json, os; ctx=json.load(open('.runs/iterate-cross-phase2-context.json')); assert ctx.get('phase') == 2, 'phase must be 2'; filt=ctx.get('phase2_utm_campaign_like'); assert isinstance(filt, str) and filt.strip(), 'phase2_utm_campaign_like empty'; assert ctx.get('fallback_all_gclid') is False, 'fallback_all_gclid must be false for phase2'; assert os.path.isfile('.runs/_iterate-cross-phase2-ga-unmatched.json'), 'phase2 GA unmatched triage file missing'; json.load(open('.runs/_iterate-cross-phase2-ga-unmatched.json')); db_triage_path='.runs/_iterate-cross-phase2-db-unmatched.json'; assert os.path.isfile(db_triage_path), 'phase2 DB unmatched triage file missing'; db_triage=json.load(open(db_triage_path)); issues=json.load(open('.runs/iterate-cross-phase2-issues.json')); assert isinstance(issues.get('mvps'), list), 'issues mvps not list'; scores=json.load(open('.runs/iterate-cross-phase2-scores.json')); ms=scores.get('mvps', []); assert isinstance(ms, list), 'scores mvps not list'; allowed={'GO','NO_GO','INSUFFICIENT_DATA','NO_DATA','MISSING_PROJECT_NAME','GA_NO_PH_TRACKING'}; bad=[m.get('name','?') for m in ms if m.get('headline_verdict') not in allowed]; assert not bad, 'invalid pay-intent verdicts: %s' % bad; metric_keys=('ga_clicks','pay_intents','pay_intent_rate','revenue_intent_per_click','denominator_source','pay_intent_source','pay_intents_db','pay_intents_posthog','campaign_age_days','ga_impressions'); missing=[m.get('name','?') for m in ms if any(k not in m.get('metrics', {}) for k in metric_keys)]; assert not missing, 'MVPs missing phase2 metrics: %s' % missing; denom=[m.get('name','?') for m in ms if m.get('metrics', {}).get('denominator_source') != 'ga']; assert not denom, 'phase2 denominator must be ga for all MVPs: %s' % denom; status_missing=[m.get('name','?') for m in ms if 'phase2_ads_all_stopped' not in m]; assert not status_missing, 'phase2 rows missing ads-status field: %s' % status_missing; stalled_bad=[m.get('name','?') for m in ms if m.get('headline_verdict')=='INSUFFICIENT_DATA' and m.get('metrics',{}).get('stalled_bucket') not in ('none','stalled','stalled_slow')]; assert not stalled_bad, 'phase2 INSUF rows missing stalled triage: %s' % stalled_bad; run_token=ctx.get('phase2_run_token'); marker=ctx.get('phase2_db_merge') or {}; assert run_token and marker.get('run_token') == run_token, 'phase2 db merge run_token mismatch'; assert db_triage.get('run_token') == run_token, 'phase2 db triage run_token mismatch'; triage_mvps=db_triage.get('mvps'); assert isinstance(triage_mvps, list), 'phase2 db triage mvps not list'; ctx_names={m.get('name') for m in ctx.get('mvps', [])}; triage_names={m.get('name') for m in triage_mvps}; assert triage_names == ctx_names, 'phase2 db triage mvp set mismatch'; db_bad=[m.get('name','?') for m in ctx.get('mvps', []) if (m.get('db_pay_intents_paid') is None) != (m.get('db_pay_intents_unmapped_reason') is not None)]; assert not db_bad, 'phase2 db paid/reason invariant failed: %s' % db_bad; assert os.path.isfile('.runs/iterate-cross-phase2-report.md') and os.path.getsize('.runs/iterate-cross-phase2-report.md') > 0, 'phase2 report missing/empty'; assert os.path.isfile('.runs/iterate-cross-auth-preflight.json'), 'auth preflight artifact missing (state-x5 Step 0 did not run)'; ap=json.load(open('.runs/iterate-cross-auth-preflight.json')); assert ap.get('mode')=='cross-phase2' and ap.get('all_required_ok') is True, 'auth preflight failed: mode=%s missing=%s' % (ap.get('mode'), ap.get('missing'))"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross-phase2 x5
```

**NEXT:** Read [.claude/patterns/state-99-epilogue.md](../../patterns/state-99-epilogue.md) to continue.
