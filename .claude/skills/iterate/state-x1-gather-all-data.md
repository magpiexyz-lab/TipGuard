# STATE x1: GATHER_DATA

PostHog-only data gather. No Google Ads metrics (spend, CTR, QS, impressions).

**PRECONDITIONS:**
- MVP list confirmed (STATE x0 POSTCONDITIONS met)
- `.runs/iterate-cross-context.json` exists with `mvps` array, `posthog_project_id`, `window_days`

**ACTIONS:**

### Read context

```bash
POSTHOG_PROJECT_ID=$(python3 -c "import json; print(json.load(open('.runs/iterate-cross-context.json'))['posthog_project_id'])")
WINDOW_DAYS=$(python3 -c "import json; print(json.load(open('.runs/iterate-cross-context.json'))['window_days'])")
```

### Build per-MVP event catalog query

For each MVP, query the top events with counts. Catalog feeds STATE x2 (signup classification) and STATE x3 (signup count using mvp_mappings).

The query uses bounded batches of UNION ALL per-MVP subqueries. Build via Python to handle dynamic mvp list cleanly:

```bash
python3 - "$POSTHOG_PROJECT_ID" <<'PY'
import json, os, sys
sys.path.insert(0, '.claude/scripts/lib')
from gclid_filter import PAID_GCLID_FILTER  # single source of truth; see gclid_filter.py
from iterate_cross_posthog_batch import run_union_batches

project_id = sys.argv[1]
api_key = open(os.path.expanduser('~/.posthog/personal-api-key')).read().strip()
ctx = json.load(open('.runs/iterate-cross-context.json'))
mvps = ctx['mvps']
window_days = ctx['window_days']

parts = []
values = {"empty": ""}
for i, m in enumerate(mvps):
    # Skip orphan synthetic MVPs (no project_name → nothing to catalog by project_name).
    # They flow through x1a → MISSING_PROJECT_NAME verdict in x3 with empty catalog.
    if m.get('orphan'):
        continue
    pj = f"pj_{i}"
    values[pj] = m['name']

    # Filter SOLELY by properties.project_name. The previous OR-LIKE branch on
    # $current_url cross-polluted similarly-named MVPs (e.g. rubberduck vs
    # rubber-duck-api). project_name is now the canonical MVP identifier —
    # enforced at /bootstrap state-3 by validate_experiment_yaml.py.
    #
    # Paid-traffic filter (PAID_GCLID_FILTER) lives in .claude/scripts/lib/gclid_filter.py.
    # Same filter applied in state-x0/state-x2/state-c2 — single source of truth.
    subq = (
        f"SELECT {{{pj}}} AS mvp_key, "
        f"event AS event_name, "
        f"max(toString(properties.funnel_stage)) AS sample_stage, "
        f"count(*) AS event_count, "
        f"count(DISTINCT distinct_id) AS unique_users, "
        f"count(DISTINCT IF({PAID_GCLID_FILTER}, distinct_id, NULL)) AS gclid_users "
        f"FROM events "
        f"WHERE timestamp >= now() - INTERVAL {window_days} DAY "
        f"AND properties.project_name = {{{pj}}} "
        f"AND event NOT LIKE '$%' "
        f"GROUP BY event_name "
        f"HAVING gclid_users > 0 OR unique_users >= 5"
    )
    parts.append(subq)

pq = {}
try:
    import yaml
    import os as _os
    if _os.path.exists('experiment/iterate-cross-config.yaml'):
        pq = (yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}).get('posthog_query') or {}
except ImportError:
    pass
rows, metadata = run_union_batches(
    parts,
    values,
    project_id,
    api_key,
    batch_size=int(pq.get('union_batch_size_catalog', 5)),
    max_time_seconds=int(pq.get('max_time_seconds', 120)),
)
json.dump(
    {"results": rows, "_x1_catalog_batches_status": metadata},
    open('.runs/_iterate-cross-catalog-raw.json', 'w'),
)
PY
```

The production path must run these UNION parts through
`.claude/scripts/lib/iterate_cross_posthog_batch.py::run_union_batches` with the
batch size from `posthog_query.union_batch_size_catalog` (default 5 — the
empirical 365-day ceiling; 20 hits HogQL max-execution-time on the first batch)
and `posthog_query.max_time_seconds` (default 120), then write the concatenated
result to `.runs/_iterate-cross-catalog-raw.json`. Stamp the returned metadata
under `_x1_catalog_batches_status` in `.runs/iterate-cross-data.json`; VERIFY
requires `complete: true`.

### Aggregate per-MVP totals + event catalog

Do not inline aggregation here. Use the canonical propagation helper, which
performs the context → data bridge and carries the DB-side fields:

```bash
python3 .claude/scripts/lib/iterate_cross_propagate.py \
  --context .runs/iterate-cross-context.json \
  --config experiment/iterate-cross-config.yaml \
  --run-dir .runs \
  --output .runs/iterate-cross-data.json
```

**POSTCONDITIONS:**
- Per-MVP `gclid_visitors` and `total_events_count` recorded
- Per-MVP `event_catalog` (≤30 events) recorded with stage hints
- Per-MVP `ga_clicks`, `ga_only`, `ga_campaigns`, `partial_tracking_pct` propagated from `context.json` (set by state-x0a's CSV merge)
- Per-MVP `db_signups`, `db_signups_raw`, `db_signups_real`, `db_signups_paid`, `db_attribution`, `db_signups_team`, `db_signups_test`, `db_signups_filter_audit`, `db_signups_real_windowed`, `db_signups_table`, `db_union_tables`, `db_first_signup_at`, `db_unmapped_reason`, `db_source`, `lifecycle_status`, `lifecycle_status_at` propagated from `context.json` (set by state-x0b's Supabase + Railway passes). `db_source` discriminates between the two backends — `"supabase"`, `"railway"`, or `None` when neither matched.
- Per-MVP `supabase_project_ref` / `railway_project_id` / `railway_project_name` / `railway_service_name` propagated when applicable (for x4 to render attribution)
- `.runs/iterate-cross-data.json` exists with required schema

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x1`.

```bash
python3 -c "import json; d=json.load(open('.runs/iterate-cross-data.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; req=['name','gclid_visitors','total_events_count','event_catalog','ga_clicks','ga_clicks_phase2','db_signups','db_signups_raw','db_signups_real','db_signups_paid','db_attribution','db_signups_team','db_signups_test','db_signups_filter_audit','db_signups_real_windowed','lifecycle_status']; bad=[m.get('name','?') for m in ms if any(k not in m for k in req)]; assert not bad, 'MVPs missing required fields (incl. ga_clicks/db fields propagated from state-x0a/x0b context): %s' % bad; paid_inv=[m.get('name','?') for m in ms if ((m.get('db_attribution') == 'gclid_shape') != (type(m.get('db_signups_paid')) is int and m.get('db_signups_paid') > 0))]; assert not paid_inv, 'db_attribution/db_signups_paid invariant failed: %s' % paid_inv; paid_bounds=[m.get('name','?') for m in ms if m.get('db_signups_paid') is not None and not (type(m.get('db_signups_paid')) is int and type(m.get('db_signups_real')) is int and 0 <= m.get('db_signups_paid') <= m.get('db_signups_real'))]; assert not paid_bounds, 'db_signups_paid bounds invariant failed: %s' % paid_bounds; assert d.get('_x1_catalog_batches_status',{}).get('complete') is True, 'x1 catalog batching incomplete'"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x1
```

**NEXT:** Read [state-x1a-validate-data-integrity.md](state-x1a-validate-data-integrity.md) to continue.
