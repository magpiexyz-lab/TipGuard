# STATE x2: CLASSIFY_SIGNUPS

LLM-derived per-MVP signup event classification with **silent auto-accept** by default. Classifications are persisted to operator config and reused on subsequent runs.

This state does NOT prompt the operator for each MVP. The combination of (a) **code-enforced hard exclusion list** in `iterate_cross_classify.py` (cannot be bypassed by LLM error), (b) strong-prior LLM rules, (c) operator override lock via `classified_by: operator`, and (d) post-classification sanity check (suspect MVPs flagged when signups/visitors > 50%) covers the same safety surface that per-MVP confirmation would, without O(N) friction across many MVPs.

The heavy lifting (filtering, merging, sanity check, summary) runs in `.claude/scripts/lib/iterate_cross_classify.py` — unit-tested at `.claude/scripts/tests/test_iterate_cross_classify.py`. This state file is the orchestrator only.

**PRECONDITIONS:**
- STATE x1a POSTCONDITIONS met
- `.runs/iterate-cross-data.json` exists with `event_catalog` per MVP
- `.runs/iterate-cross-data-issues.json` exists with the five flags from x1a
- `.runs/iterate-cross-context.json` exists with `posthog_project_id`, `window_days`

**ACTIONS:**

### Step 1: Prepare classification buckets

```bash
python3 .claude/scripts/lib/iterate_cross_classify.py prepare \
  --data .runs/iterate-cross-data.json \
  --issues .runs/iterate-cross-data-issues.json \
  --config experiment/iterate-cross-config.yaml \
  --output .runs/_iterate-cross-classify-input.json
```

This writes three buckets:
- `to_skip`: MVPs whose operator already locked classification (`classified_by: operator`) or that already have a mapping in config — no work needed
- `to_auto`: MVPs whose catalog has events matching the operator's `signup_whitelist` — deterministically assigned (excluded events stripped automatically)
- `to_llm`: MVPs requiring LLM classification (no obvious whitelist match)

### Step 2: LLM classification (silent, inline)

Read `.runs/_iterate-cross-classify-input.json`. For each MVP in `to_llm`, inspect its `event_catalog` (top 20 events with `gclid_users` counts and `sample_stage` hint) and decide which event(s) represent **completed signup / committed conversion**.

#### Classification rules (priority order)

1. **Strong** (`confidence: 'strong'`): event names matching the canonical patterns — `signup_complete`, `signup_completed`, `register_complete`, `account_created`, `<role>_signup_complete` (e.g., `buyer_signup_complete`), `early_access_*`, `*_submitted` (when paired with form/email/waitlist semantics). Take all matches.

2. **Waitlist** (`confidence: 'strong'`): `waitlist_signup`, `waitlist_submit`, `waitlist_submitted`. Take all matches.

3. **Activation-as-signup** (`confidence: 'inferred'`): only when NO strong/waitlist match exists. Pick events whose name implies a meaningful first action consistent with the MVP's product type:
   - `api_key_create` for dev tools
   - `demo_completed` for demo-driven funnels
   - `first_check_completed`, `analysis_complete` for tool/calculator MVPs (NOT `model_recommended` — that's UI)
   - `location_connected` for connect-based MVPs
   - `<role>_registration_started` (e.g., `actor_registration_started`)
   Pick at most TWO events. Tag `confidence: 'inferred'`.

4. **Form submission** (`confidence: 'inferred'`): when catalog has `form_submitted` and no `signup_*` exists. Take it.

5. **Loose** (`confidence: 'loose'`): only as last resort, when only `signup_start` (no `_complete`) exists. Take it.

6. **Empty** (`confidence: 'empty'`): no event qualifies. Return `signup_events: []`. MVP will report INSUFFICIENT_DATA or NO_DATA in x3.

Do NOT manually filter excluded events — `iterate_cross_classify.py persist` will strip any UI/page events that slipped through. Your job is to make the best guess; the code is the safety net.

Write proposals to `.runs/_iterate-cross-classify-proposals.json` as a JSON array:

```json
[
  {"name": "diarly", "signup_events": ["signup_complete"], "confidence": "strong", "rationale": "Standard SaaS signup_complete (8 gclid users)."},
  {"name": "stylica-ai", "signup_events": ["signup_complete", "activate"], "confidence": "inferred", "rationale": "activate (32 gclid) is the real conversion signal — minimal signup_complete (2) suggests activate IS the conversion."}
]
```

### Step 3: Persist (filter + merge + write config)

```bash
python3 .claude/scripts/lib/iterate_cross_classify.py persist \
  --input .runs/_iterate-cross-classify-input.json \
  --proposals .runs/_iterate-cross-classify-proposals.json \
  --config experiment/iterate-cross-config.yaml \
  --summary .runs/_iterate-cross-classify-persist-summary.json
```

This script:
- Iterates `to_auto` + LLM proposals
- For each MVP: if existing mapping has `classified_by: operator` → **skip** (do not overwrite operator's manual choice)
- Otherwise: strip hard-excluded events from `signup_events` (using `EXCLUDED_PATTERNS`), merge into config under `mvp_mappings.<name>` with `classified_by: x2-<confidence>` and `classified_at: <ISO>`
- Preserves any existing `owner`, `deploy_domain`, `rationale` fields on the mapping
- Writes audit summary (which MVPs were preserved, which had events stripped)

### Step 4: Query signups using classified events

Build a UNION ALL query that counts gclid-filtered distinct signups per MVP using each MVP's now-persisted `signup_events`:

```bash
PAYLOAD=$(python3 - <<'PY'
import json, os, sys, yaml
sys.path.insert(0, '.claude/scripts/lib')
from gclid_filter import PAID_GCLID_FILTER  # single source of truth; see gclid_filter.py
from iterate_cross_posthog_batch import run_union_batches
from iterate_cross_relaunch import posthog_lower_bound_expr, relaunch_at_for

config = yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}
mappings = config.get('mvp_mappings') or {}

data = json.load(open('.runs/iterate-cross-data.json'))
ctx = json.load(open('.runs/iterate-cross-context.json'))
project_id = ctx['posthog_project_id']
window_days = ctx['window_days']
api_key = open(os.path.expanduser('~/.posthog/personal-api-key')).read().strip()

parts = []
values = {"empty": ""}
for i, mvp in enumerate(data['mvps']):
    # Orphan MVPs (no project_name) cannot be queried by project_name. They
    # default to 0 signups and flow through x3 as MISSING_PROJECT_NAME.
    if mvp.get('orphan'):
        continue
    mapping = mappings.get(mvp['name']) or {}
    signup_events = mapping.get('signup_events') or []
    if not signup_events:
        continue
    pj = f"pj_{i}"
    values[pj] = mvp['name']

    sg_conds = []
    for j, sg in enumerate(signup_events):
        k = f"sg_{i}_{j}"
        values[k] = sg
        sg_conds.append(f"event = {{{k}}}")
    sg_expr = "(" + " OR ".join(sg_conds) + ")"

    # Filter SOLELY by properties.project_name (canonical MVP identifier
    # enforced at /bootstrap state-3). The previous OR-LIKE branch on
    # $current_url double-counted signups across similarly-named MVPs.
    #
    # Paid-traffic filter (PAID_GCLID_FILTER) is the single source of truth
    # in .claude/scripts/lib/gclid_filter.py. Excludes operator manual-test
    # gclids (e.g. analytics-verify-* 32-char strings that slipped past the
    # old length>30 rule) by combining length>40 AND prefix in Cj/EAI/CIa,
    # AND coalesces $session_entry_gclid with properties.gclid for legacy
    # deploys where SDK init lost the race to URL cleanup.
    # Same filter applied in state-x0/state-x1/state-c2 — keep in sync.
    #
    # Per-MVP Phase-1 relaunch: when this MVP has phase1_relaunch_at set, the
    # lower time bound rises to max(window, relaunch) so the failed first
    # flight's signups are excluded from the re-test count (iterate_cross_relaunch).
    lower = posthog_lower_bound_expr(window_days, relaunch_at_for(mvp['name'], mappings))
    parts.append(
        f"SELECT {{{pj}}} AS mvp_key, "
        f"count(DISTINCT IF({sg_expr}, distinct_id, NULL)) AS signups "
        f"FROM events "
        f"WHERE {PAID_GCLID_FILTER} "
        f"AND timestamp >= {lower} "
        f"AND properties.project_name = {{{pj}}}"
    )

pq = config.get('posthog_query') or {}
rows, metadata = run_union_batches(
    parts,
    values,
    project_id,
    api_key,
    batch_size=int(pq.get('union_batch_size_signup', 10)),
    max_time_seconds=int(pq.get('max_time_seconds', 120)),
)
json.dump(
    {"results": rows, "_x2_signup_batches_status": metadata},
    open('.runs/_iterate-cross-signups-out.json', 'w'),
)
data['_x2_signup_batches_status'] = metadata
print(json.dumps(data))
PY
)
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-cross-data.json \
  --payload "$PAYLOAD" \
  --skill iterate-cross
```

The production path must build the per-MVP signup-count subqueries as `parts`
and execute them through
`.claude/scripts/lib/iterate_cross_posthog_batch.py::run_union_batches` with the
batch size from `posthog_query.union_batch_size_signup` (default 10 — these
unions are lighter than x1's catalog scan but still time out at 20 on 365-day
windows) and `posthog_query.max_time_seconds` (default 120). The concatenated
result is written to `.runs/_iterate-cross-signups-out.json` and the returned
metadata is stamped in `.runs/iterate-cross-data.json` as
`_x2_signup_batches_status`; VERIFY requires `complete: true`.

### Step 5: Finalize (update data.json + sanity check + summary)

```bash
python3 .claude/scripts/lib/iterate_cross_classify.py finalize \
  --data .runs/iterate-cross-data.json \
  --config experiment/iterate-cross-config.yaml \
  --signup-counts .runs/_iterate-cross-signups-out.json \
  --persist-summary .runs/_iterate-cross-classify-persist-summary.json
```

This script:
- Merges `signup_events` from config into `.runs/iterate-cross-data.json`
- Applies signup counts from PostHog query (`.runs/_iterate-cross-signups-out.json`)
- Writes `ph_signups_available` and `ph_signups`; empty `signup_events` is the only path to `ph_signups_available=false`
- Raises on malformed PostHog signup-count responses instead of treating missing `results` as zero signups
- Runs sanity check: any MVP with `gclid_visitors >= 10` AND `signups/gclid_visitors > 0.5` is flagged as **suspect** (a 50%+ conversion rate on cold ad traffic almost always means we picked a UI event by mistake)
- Prints classification summary + suspect warnings + inferred-classification review list to stdout
- Returns 0 (warn-only). Pass `--strict-sanity` to exit 1 on any suspect (for CI / safety-critical contexts).

### Cleanup

```bash
rm -f .runs/_iterate-cross-classify-input.json \
      .runs/_iterate-cross-classify-proposals.json \
      .runs/_iterate-cross-classify-persist-summary.json \
      .runs/_iterate-cross-signups-query.json \
      .runs/_iterate-cross-signups-out.json
```

**POSTCONDITIONS:**
- Every MVP has `signup_events` field (array, possibly empty) in `.runs/iterate-cross-data.json`
- Every MVP has `signups`, `ph_signups`, and `ph_signups_available` fields in `.runs/iterate-cross-data.json`
- Summary printed to stdout (classification counts + suspect MVPs + filter audit)
- Side effect (out-of-band, no VERIFY check): operator config file is updated with `mvp_mappings.<name>.signup_events`, `classified_by`, and `classified_at` for every newly-classified MVP. Operator overrides (`classified_by: operator`) are preserved. The data file's `signup_events` is sourced from the persisted config, so the data-file VERIFY transitively confirms the config write. <!-- enforced by agent behavior, not VERIFY gate -->

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x2`.

```bash
python3 -c "import json; d=json.load(open('.runs/iterate-cross-data.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; bad=[m['name'] for m in ms if 'signup_events' not in m or 'signups' not in m or 'ph_signups_available' not in m or 'ph_signups' not in m]; assert not bad, 'MVPs missing signup_events/signups/ph availability: %s' % bad; bad2=[m['name'] for m in ms if not isinstance(m.get('ph_signups_available'), bool) or ((m.get('ph_signups') is None) != (m.get('ph_signups_available') is False))]; assert not bad2, 'MVP ph_signups/ph_signups_available inconsistent: %s' % bad2; assert d.get('_x2_signup_batches_status',{}).get('complete') is True, 'x2 signup batching incomplete'"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x2
```

**NEXT:** Read [state-x3-compute-scores.md](state-x3-compute-scores.md) to continue.
