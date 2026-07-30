# STATE x0: DISCOVER_MVPS

PostHog-based MVP discovery. No Google Ads / Chrome MCP dependency.

**PRECONDITIONS:**
- `~/.posthog/personal-api-key` exists and has scope `query:read` and `project:read`
- Supabase auth resolvable (`supabase login` / `SUPABASE_ACCESS_TOKEN` / `~/.supabase/access-token`) — unless `require_db_ground_truth: false`
- Railway CLI installed and logged in (`railway whoami`) — unless `require_db_ground_truth: false`
- Vercel token resolvable (`vercel login` CLI auth, `$VERCEL_TOKEN`, or `~/.vercel/api-token`) — no bypass; the owner-resolution channel silently mis-attributes without it

**ACTIONS:**

### Step 0: Auth preflight (fail fast)

Every credential the run needs is checked up front, and ALL missing ones are
listed at once — a mid-run credential failure wastes the whole discovery pass,
and a silently-off Vercel channel mis-attributes owners (the 2026-07-27
tripcraft/vernis/kansei incident). Supabase/Railway soften to warnings under
`require_db_ground_truth: false`; PostHog and Vercel are always hard.

```bash
set +e
PREFLIGHT_PAYLOAD=$(python3 .claude/scripts/lib/iterate_cross_auth.py --mode cross --emit-payload)
PREFLIGHT_RC=$?
set -e
[ -n "$PREFLIGHT_PAYLOAD" ] || { echo "STOP: auth preflight crashed (no payload)" >&2; exit 1; }
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-cross-auth-preflight.json \
  --payload "$PREFLIGHT_PAYLOAD" \
  --skill iterate-cross
if [ "$PREFLIGHT_RC" -ne 0 ]; then
  echo "STOP: auth preflight failed — the checklist above lists every missing login and its fix. Log in, then re-run /iterate --cross." >&2
  exit 1
fi
```

The checklist (stderr) names each missing service with its exact login
command. The state-x0b DB gate stays in place as defense-in-depth but should
never fire on a preflighted run.

### Read PostHog credentials

```bash
POSTHOG_API_KEY=$(cat ~/.posthog/personal-api-key 2>/dev/null)
```

Key presence was already enforced by Step 0; if this read comes back empty
anyway, re-run the preflight instead of continuing.

### Discover PostHog project ID

```bash
POSTHOG_PROJECT_ID=$(curl -s "https://us.i.posthog.com/api/projects/" \
  -H "Authorization: Bearer $POSTHOG_API_KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['results'][0]['id'])")
```

If this fails (key lacks `project:read` scope, network error, etc.), report the error and STOP. If the team has multiple PostHog projects and the wrong one is auto-picked, the operator can override via `experiment/iterate-cross-config.yaml` `posthog_project_id`.

### Read operator config (with safe defaults)

Read `experiment/iterate-cross-config.yaml`. If missing, use inline defaults and emit a one-time notice:

```yaml
window_days: 90              # how far back to look
phase_filter:
  utm_campaign_like: ""      # empty = all gclid traffic; e.g. "%-search-v%" = Phase 1 Manual CPC convention
  fallback_all_gclid: true   # if utm_campaign_like has no matches for an MVP, count all gclid traffic
mvp_mappings: {}             # per-MVP overrides (signup_events, owner, deploy_domain,
                             #   phase1_relaunch_at: "YYYY-MM-DD" to re-test a failed
                             #   MVP — Phase-1 eval then ignores all data before that
                             #   date (GA/DB/PostHog windows raise to max(window,
                             #   relaunch); relaunch needs a fresh v2 campaign name).
                             #   See .claude/scripts/lib/iterate_cross_relaunch.py)
thresholds:
  visitors_floor: 100
  conv_rate_go: 0.06
  signups_go: 6              # derived visitors_floor * conv_rate_go; back-compat
# Orphan/canonical merge threshold. When an orphan host's gclid set overlaps with
# a canonical MVP's gclid set by at least this fraction (of the smaller set), the
# orphan is merged into the canonical (treated as partial-page tracking on the
# same deploy, NOT a separate broken deploy). Below this threshold, the orphan is
# kept as a separate MISSING_PROJECT_NAME row.
orphan_merge_overlap_threshold: 0.70
```

If `posthog_project_id` is set in the config, use it instead of auto-discovery.

If `phase_filter.utm_campaign_like` is set, x0 surfaces both:
- "Phase 1 candidates": projects where utm_campaign matches the pattern
- "All-gclid candidates": projects with any gclid traffic (broader view)

### Discover MVPs from PostHog

Query distinct `project_name` values with gclid traffic in the time window. `project_name` is the canonical MVP identifier (set verbatim from `experiment.yaml.name` by `/bootstrap` STATE 3 — see `.claude/scripts/lib/validate_experiment_yaml.py`). Events without `project_name` are orphaned and surfaced separately for triage.

**Paid-traffic gclid filter** — uses `.claude/scripts/lib/gclid_filter.py` `PAID_GCLID_FILTER` (length > 40 AND prefix in `Cj`/`EAI`/`CIa`). Real Google Ads gclids start with these prefixes and are 60-120 chars. Operator manual-test gclids (e.g., `analytics-verify-2026050720272` at 32 chars, `MANUAL_VERIFY_CHECK` at 19 chars) fail one or both checks. Filter ALSO reads from `properties.gclid` as fallback when `$session_entry_gclid` is empty (handles legacy deploys where PostHog SDK init lost the race to Next.js router URL cleanup — see `.claude/stacks/analytics/posthog.md` "Paid-attribution capture" section). The filter is the single source of truth in `gclid_filter.py`; all 4 query sites (state-x0 canonical + orphan, state-x1, state-x2) read from it — do NOT inline the rule.

**PostHog query tuning** — long windows (365d) exceed HogQL's max-execution-time at the library's 30s default, so every query below reads `posthog_query.max_time_seconds` from the operator config (default 120). See `experiment/iterate-cross-config.example.yaml` for the full `posthog_query:` block.

```bash
read -r WINDOW_DAYS PH_MAX_TIME <<< "$(python3 -c "
import yaml, os
cfg = {}
if os.path.exists('experiment/iterate-cross-config.yaml'):
    cfg = yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}
pq = cfg.get('posthog_query') or {}
print(cfg.get('window_days', 90), pq.get('max_time_seconds', 120))
")"

python3 - "$POSTHOG_PROJECT_ID" "$WINDOW_DAYS" "$PH_MAX_TIME" <<'PY'
import json, os, sys
sys.path.insert(0, '.claude/scripts/lib')
from gclid_filter import PAID_GCLID_FILTER
from iterate_cross_posthog_batch import paginate_discovery_query

project_id = sys.argv[1]
window_days = int(sys.argv[2])
max_time_seconds = int(sys.argv[3])
api_key = open(os.path.expanduser('~/.posthog/personal-api-key')).read().strip()
sql = (
    "SELECT properties.project_name AS mvp_key, "
    "max(properties.utm_campaign) AS sample_utm_campaign, "
    "count(DISTINCT distinct_id) AS gclid_visitors, "
    "min(timestamp) AS first_seen, max(timestamp) AS last_seen "
    f"FROM events WHERE {PAID_GCLID_FILTER} "
    "AND properties.project_name IS NOT NULL "
    "AND properties.project_name != {empty} "
    f"AND timestamp >= now() - INTERVAL {window_days} DAY "
    "GROUP BY mvp_key HAVING gclid_visitors > 0 "
    "ORDER BY gclid_visitors DESC LIMIT 200"
)
rows, metadata = paginate_discovery_query(
    sql,
    {"empty": ""},
    project_id,
    api_key,
    page_size=200,
    max_time_seconds=max_time_seconds,
)
payload = {"results": rows, "_canonical_pagination_status": metadata}
json.dump(payload, open('.runs/_iterate-cross-discover.json', 'w'))

context_path = '.runs/iterate-cross-context.json'
if os.path.exists(context_path):
    ctx = json.load(open(context_path))
    ctx['_canonical_pagination_status'] = metadata
    json.dump(ctx, open(context_path, 'w'), indent=2)
PY
```

The production path must run this query through
`.claude/scripts/lib/iterate_cross_posthog_batch.py::paginate_discovery_query`
instead of relying on the visible `LIMIT 200`. The helper issues a single
OFFSET-free query capped at `page_size * max_pages` (personal API keys reject
OFFSET; this GROUP BY aggregate is bounded by the number of MVPs), stamps
`_canonical_pagination_status` into context, and proves completeness with a
short page (raising if the cap is ever hit).

Parallel sibling query — count gclid events with NULL/empty `project_name`. These get surfaced in the operator confirmation message; they are NOT auto-keyed by URL anymore (the previous `splitByChar(domain($current_url))[1]` fallback created cross-pollution between similarly-named MVPs):

```bash
python3 - "$POSTHOG_PROJECT_ID" "$WINDOW_DAYS" "$PH_MAX_TIME" <<'PY'
import json, os, sys
sys.path.insert(0, '.claude/scripts/lib')
from gclid_filter import PAID_GCLID_FILTER
from iterate_cross_posthog_batch import paginate_discovery_query

project_id = sys.argv[1]
window_days = int(sys.argv[2])
max_time_seconds = int(sys.argv[3])
api_key = open(os.path.expanduser('~/.posthog/personal-api-key')).read().strip()
sql = (
    "SELECT splitByChar('.', domain(coalesce(properties.$current_url, '')))[1] AS host_prefix, "
    "count(DISTINCT distinct_id) AS gclid_visitors "
    f"FROM events WHERE {PAID_GCLID_FILTER} "
    "AND (properties.project_name IS NULL OR properties.project_name = {empty}) "
    f"AND timestamp >= now() - INTERVAL {window_days} DAY "
    "GROUP BY host_prefix HAVING gclid_visitors > 0 "
    "ORDER BY gclid_visitors DESC LIMIT 50"
)
rows, metadata = paginate_discovery_query(
    sql,
    {"empty": ""},
    project_id,
    api_key,
    page_size=50,
    max_time_seconds=max_time_seconds,
)
payload = {"results": rows, "_orphan_pagination_status": metadata}
json.dump(payload, open('.runs/_iterate-cross-orphan.json', 'w'))

context_path = '.runs/iterate-cross-context.json'
if os.path.exists(context_path):
    ctx = json.load(open(context_path))
    ctx['_orphan_pagination_status'] = metadata
    json.dump(ctx, open(context_path, 'w'), indent=2)
PY
```

The orphan query uses the same helper with a page size of 50 and stamps
`_orphan_pagination_status` into context. The single capped fetch returns up to
`50 * max_pages` rows; a short page proves completeness.

Parse results into MVP records. Each MVP gets:
- `name` — `mvp_key` from query (always equals `properties.project_name` — never URL-derived)
- `gclid_visitors` — visitor count in window
- `first_seen`, `last_seen` — ISO timestamps
- `sample_utm_campaign` — one example utm_campaign value (informational)
- `owner` — read from `mvp_mappings.<name>.owner` if set, else null
- `deploy_domain` — from `mvp_mappings.<name>.deploy_domain` if set, else null (informational; no longer used for query filtering)
- `phase_match` — true if `sample_utm_campaign` matches `phase_filter.utm_campaign_like` (or `phase_filter.utm_campaign_like` is empty)
- `orphan` — always `false` for entries from this discovery query (orphan entries are handled separately, see next step)
- `partial_tracking_pct` — fraction (0.0–1.0) of orphan-host visitors not covered by canonical tracking, present only when state-x0's orphan-merge step absorbed an orphan into this canonical record (high gclid overlap = same deploy with partial page tracking). state-x4 reads this to render a "⚠ partial tracking" marker on the canonical row instead of opening a separate MISSING_PROJECT_NAME row. Null when no orphan was merged into this canonical.

Add one synthetic MVP record per orphan host:
- `name` — `__orphan_<host_prefix>__` (sentinel form; double-underscore prefix avoids collision with kebab-case MVP names)
- `gclid_visitors` — from orphan query
- `orphan` — `true`
- All other fields null

These orphan records propagate the `missing_project_name` flag through x1a → verdict pipeline so the operator can see which deploys are missing tracking.

### Merge aliases (legacy duplicate-key dedup)

Before applying the phase filter, merge MVPs that the operator has declared as aliases of each other. This handles MVPs created before /bootstrap state-3 enforced kebab-case (a `split-share-neon` deploy and a `splitshare` deploy reporting under two different `project_name` values for the same product).

```bash
python3 .claude/scripts/lib/iterate_cross_classify.py merge-aliases \
  --discovery .runs/_iterate-cross-discover.json \
  --config experiment/iterate-cross-config.yaml \
  --output .runs/_iterate-cross-discover.json
```

The script reads `mvp_aliases:` from the config, sums visitor counts into the canonical record, takes min/max of timestamps, and preserves the canonical's other fields. Aliases referenced in config but absent from PostHog discovery are silently ignored (config can lag the data). Conflicting aliases (one alias key listed under two canonicals) exit non-zero. The script is idempotent.

### Detect orphan/canonical gclid overlap (merge same-deploy partial tracking)

For each (canonical MVP name, orphan host) pair with matching alphanumeric keys (after stripping hyphens — e.g., `x-predict` matches `xpredict`), query PostHog for the gclid intersection. High overlap (≥70% by default; tunable via `orphan_merge_overlap_threshold` in config) means same deploy with partial page tracking — merge orphan into canonical (don't double-count). Low overlap means genuinely independent broken deploy — keep separate as MISSING_PROJECT_NAME.

The overlap query MUST run per-MVP serially. UNION ALL of 7+ subqueries hits HogQL's max-execution-time at ~6s; one query per pair at ~500ms each is comfortably under the timeout.

On long windows (365d) individual pairs still time out, and PostHog then applies a server-side circuit breaker ("This query failed the same way 4 times in a row … It can run again in about 4 minutes") that makes immediate retries fail instantly. The library call below therefore runs cooldown-resume passes: pairs that fail a pass sleep `posthog_query.overlap_failure_sleep_seconds` before the next pair, and remaining failures are retried in up to `posthog_query.overlap_max_passes` passes separated by `posthog_query.overlap_cooldown_seconds` (≈ the breaker window). The per-pair cache in `.runs/_iterate-cross-overlap.json` resumes both across passes and across invocations — if pairs are still unresolved after the final pass, re-running state-x0 continues from the cache instead of starting over.

```bash
# Step 1: identify (canonical, orphan_host) pairs that share an alphanumeric key.
python3 - <<'PY'
import json, re, sys
sys.path.insert(0, '.claude/scripts/lib')
from iterate_cross_classify import match_key

disc = json.load(open('.runs/_iterate-cross-discover.json'))
orph = json.load(open('.runs/_iterate-cross-orphan.json'))

pairs = []
orph_by_key = {match_key(r[0]): r[0] for r in orph.get('results', []) if r}
for cr in disc.get('results', []):
    if not cr:
        continue
    canon = cr[0]
    canon_key = match_key(canon)
    if canon_key in orph_by_key:
        pairs.append((canon, orph_by_key[canon_key]))

with open('.runs/_iterate-cross-overlap-pairs.json', 'w') as f:
    json.dump(pairs, f)
print(f"overlap-pairs: {len(pairs)} canonical/orphan matches to query")
PY

# Step 2: query overlap via the shared library implementation
# (iterate_cross_posthog_batch.compute_orphan_overlap — the same code path
# state-x5 uses; per-pair caching + cooldown-resume live there).
# IMPORTANT: pass POSTHOG_PROJECT_ID and WINDOW_DAYS via sys.argv because the
# context.json (which iterate-cross-context.json) is NOT written until later in
# state-x0 (the "Merge cross-specific fields into context" step at the end).
# These two bash variables are set earlier in state-x0 and remain in scope.
python3 - "$POSTHOG_PROJECT_ID" "$WINDOW_DAYS" <<'OVERLAP_PY'
import json, os, sys
sys.path.insert(0, '.claude/scripts/lib')
try:
    import yaml
except ImportError:
    yaml = None
from iterate_cross_posthog_batch import compute_orphan_overlap

project_id = sys.argv[1]
window_days = int(sys.argv[2])
api_key = open(os.path.expanduser('~/.posthog/personal-api-key')).read().strip()
pairs = [tuple(p) for p in json.load(open('.runs/_iterate-cross-overlap-pairs.json'))]

cfg = {}
if yaml is not None and os.path.exists('experiment/iterate-cross-config.yaml'):
    cfg = yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}
pq = cfg.get('posthog_query') or {}

by_canonical = compute_orphan_overlap(
    pairs,
    project_id,
    api_key,
    window_days,
    cache_path='.runs/_iterate-cross-overlap.json',
    max_time_seconds=int(pq.get('max_time_seconds', 120)),
    cooldown_seconds=int(pq.get('overlap_cooldown_seconds', 300)),
    failure_sleep_seconds=int(pq.get('overlap_failure_sleep_seconds', 20)),
    max_passes=int(pq.get('overlap_max_passes', 3)),
)
failed = [(c, o) for c, o in pairs if (by_canonical.get(c) or {}).get('orphan_host') != o]
print(f"overlap-query: {len(by_canonical)}/{len(pairs)} pairs resolved, {len(failed)} failed")
if failed:
    print("WARN: unresolved pairs (re-run state-x0 to resume from cache): "
          + ", ".join(f"{c}/{o}" for c, o in failed), file=sys.stderr)
OVERLAP_PY

# Step 3: merge orphans whose overlap >= threshold into canonical rows.
python3 .claude/scripts/lib/iterate_cross_classify.py merge-orphan-overlap \
  --discovery .runs/_iterate-cross-discover.json \
  --orphan .runs/_iterate-cross-orphan.json \
  --overlap .runs/_iterate-cross-overlap.json \
  --config experiment/iterate-cross-config.yaml

rm -f .runs/_iterate-cross-overlap-pairs.json .runs/_iterate-cross-overlap.json
```

Result: high-overlap orphans are absorbed into canonical rows (with `partial_tracking_pct` as the 6th element documenting "fraction of orphan visitors not covered by canonical tracking"). Low-overlap orphans remain as separate MISSING_PROJECT_NAME rows.

### Apply phase filter

If `phase_filter.utm_campaign_like` is set AND `phase_filter.fallback_all_gclid` is false: keep only MVPs with `phase_match: true`.
Else: keep all discovered MVPs.

### Confirm with operator

Present the discovered MVPs:
> "Found **N** MVPs with Google Ads gclid traffic in the last {window_days} days
> (M alias pairs merged via `mvp_aliases`, K orphan hosts have gclid events but no `project_name` — see warning below):
>
> | # | MVP | Owner | Visitors | Window | utm_campaign sample |
> |---|-----|-------|----------|--------|---------------------|
> | 1 | {name} | {owner or '—'} | {visitors} | {first_seen}→{last_seen} | {sample_utm_campaign or '(no utm)'} |
> | ... |
>
> ⚠ Orphan hosts (no `project_name` — fix tracking in those deploys):
> | Host prefix | Visitors |
> |-------------|----------|
> | {host_prefix} | {visitors} |
>
> Proceed with evaluation of all N MVPs?"

Wait for confirmation. If the operator wants to exclude/add MVPs, adjust the list. Orphan rows are surfaced for visibility but they do flow through to x1a → MISSING_PROJECT_NAME verdict (operator does not need to ack each one).

### Merge cross-specific fields into context

```bash
python3 -c "
import json

def status_from(path, key, fallback):
    try:
        return json.load(open(path)).get(key) or fallback
    except Exception:
        return fallback

mvps = [
    # Populate from discovered + operator-confirmed list:
    # {'name': 'pettracker', 'owner': 'lee', 'gclid_visitors': 60,
    #  'first_seen': '2026-04-08T...', 'last_seen': '2026-05-06T...',
    #  'sample_utm_campaign': 'pettracker-search-v1',
    #  'deploy_domain': None, 'phase_match': True}
]

extra = {
    'mode': 'cross',
    'posthog_project_id': '$POSTHOG_PROJECT_ID',
    'window_days': $WINDOW_DAYS,
    'mvp_count': len(mvps),
    'mvps': mvps,
    '_canonical_pagination_status': status_from('.runs/_iterate-cross-discover.json', '_canonical_pagination_status', {'status': 'missing'}),
    '_orphan_pagination_status': status_from('.runs/_iterate-cross-orphan.json', '_orphan_pagination_status', {'status': 'missing'}),
    'completed_states': ['x0']
}
json.dump(extra, open('.runs/_iterate-cross-extra.json', 'w'))
"
bash .claude/scripts/init-context.sh iterate-cross "@.runs/_iterate-cross-extra.json"
rm -f .runs/_iterate-cross-extra.json .runs/_iterate-cross-discover.json .runs/_iterate-cross-orphan.json
```

The base fields (`skill`, `branch`, `timestamp`, `run_id`) are already set by lifecycle-init.sh.

**POSTCONDITIONS:**
- PostHog API key + project ID resolved
- MVPs discovered and operator-confirmed
- `.runs/iterate-cross-context.json` exists with `mvps` array — every MVP has `name`, `gclid_visitors`, `first_seen`, `last_seen`

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x0`.

```bash
python3 -c "import json; d=json.load(open('.runs/iterate-cross-context.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; bad=[m.get('name','?') for m in ms if not m.get('name') or 'gclid_visitors' not in m]; assert not bad, 'MVPs missing required fields: %s' % bad; assert d.get('_canonical_pagination_status',{}).get('status') == 'complete', 'canonical pagination incomplete'; assert d.get('_orphan_pagination_status',{}).get('status') == 'complete', 'orphan pagination incomplete'; import os; assert os.path.isfile('.runs/iterate-cross-auth-preflight.json'), 'auth preflight artifact missing (state-x0 Step 0 did not run)'; ap=json.load(open('.runs/iterate-cross-auth-preflight.json')); assert ap.get('mode')=='cross' and ap.get('all_required_ok') is True, 'auth preflight failed: mode=%s missing=%s' % (ap.get('mode'), ap.get('missing'))"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x0
```

**NEXT:** Read [state-x1-gather-all-data.md](state-x1-gather-all-data.md) to continue.
