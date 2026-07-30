# STATE x1a: VALIDATE_DATA_INTEGRITY

Lightweight per-MVP integrity check. Tags MVPs that need LLM signup classification in STATE x2.

## Archetype Gate

This state operates on PostHog event data, which is archetype-agnostic. Every archetype (web-app, service, cli) reports through the same PostHog ingestion path; the integrity flags (`missing_project_name`, `signup_classified`, `auto_default_match`, `low_traffic`, `no_event_data`, `needs_llm_classification`) apply uniformly with no archetype-specific branching.

REF: [.claude/patterns/archetype-behavior-check.md](../../patterns/archetype-behavior-check.md) — row "primary unit"

> [primary-unit] web-app: page | service: endpoint | cli: command

**PRECONDITIONS:**
- STATE x1 POSTCONDITIONS met
- `.runs/iterate-cross-data.json` exists with `event_catalog` per MVP
- `experiment/iterate-cross-config.yaml` exists OR defaults will be used (notice already emitted by x0)

**ACTIONS:**

This state is **pure compute** — no network calls. Idempotent. Safe to re-run after editing the operator config.

### Read inputs + compute flags

Canonical implementation:

```bash
python3 .claude/scripts/lib/iterate_cross_integrity.py \
  --data .runs/iterate-cross-data.json \
  --config experiment/iterate-cross-config.yaml \
  --output .runs/iterate-cross-data-issues.json
```

The helper computes the seven flags below and is the path used by dry-run
validation. The inline form is retained here only as readable reference.

```bash
python3 - <<'PY'
import json, os, sys

try:
    import yaml
except ImportError:
    yaml = None

data = json.load(open('.runs/iterate-cross-data.json'))

config = {}
config_path = 'experiment/iterate-cross-config.yaml'
if yaml and os.path.exists(config_path):
    config = yaml.safe_load(open(config_path)) or {}

mvp_mappings = config.get('mvp_mappings') or {}
default_signup_whitelist = config.get('signup_whitelist') or [
    'signup_complete', 'waitlist_signup', 'waitlist_submit',
    'early_access_signup', 'activate', 'form_submitted'
]

issues = {'mvps': []}
for mvp in data['mvps']:
    name = mvp['name']
    catalog = mvp.get('event_catalog') or []
    catalog_events = {e['event'] for e in catalog}

    mapping = mvp_mappings.get(name) or {}
    classified_signup_events = mapping.get('signup_events') or []

    # Flag 0: missing_project_name — discovery row had NULL/empty project_name
    # (set in x0 as the `orphan: true` flag on synthetic MVP records).
    # Tracking is missing PROJECT_NAME injection — likely a bootstrap regression
    # or pre-standardization MVP. Highest verdict precedence in x3.
    missing_project_name = bool(mvp.get('orphan'))

    # Flag 1: signup_classified — operator config has signup_events for this MVP
    signup_classified = bool(classified_signup_events)

    # Flag 2: auto_default_match — catalog contains any event from the default whitelist
    auto_default_match = bool(catalog_events & set(default_signup_whitelist))

    # Flag 3: low_traffic — fewer than 5 gclid visitors (far below the default
    # 100-visitor verdict floor; informational only)
    low_traffic = mvp.get('gclid_visitors', 0) < 5

    # Flag 4: no_event_data — catalog empty (likely tracking not capturing PostHog events)
    no_event_data = len(catalog) == 0

    # Flag 5: needs_llm_classification — not classified AND no obvious default match.
    # Orphan MVPs are excluded; their verdict is fixed at MISSING_PROJECT_NAME.
    needs_llm = (
        (not signup_classified)
        and (not auto_default_match)
        and (not no_event_data)
        and (not missing_project_name)
    )

    # Flag 6: ga_clicks_without_ph_traffic — GA has paid clicks but PostHog has
    # zero presence for this MVP (set on ga_only synthetic records produced by
    # state-x0a's merge step). Strictly stricter than missing_project_name
    # (which fires when PH SEES the traffic but project_name is NULL). This
    # surfaces deploys we're paying for but cannot measure at all.
    ga_clicks_without_ph_traffic = bool(mvp.get('ga_only'))

    issues['mvps'].append({
        'name': name,
        'missing_project_name': missing_project_name,
        'signup_classified': signup_classified,
        'auto_default_match': auto_default_match,
        'low_traffic': low_traffic,
        'no_event_data': no_event_data,
        'needs_llm_classification': needs_llm,
        'ga_clicks_without_ph_traffic': ga_clicks_without_ph_traffic,
    })

print(json.dumps(issues))
PY
```

Capture the output and write via the standard helper:

```bash
PAYLOAD=$(python3 - <<'PY'
# (same script as above; print json.dumps(issues))
PY
)
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-cross-data-issues.json \
  --payload "$PAYLOAD" \
  --skill iterate-cross
```

### Summary report

Print a concise summary:

> Data integrity check: {N} MVPs validated.
> - {sc_count} signup_classified (operator config provides signup_events; skip LLM)
> - {ad_count} auto_default_match (catalog has known signup event; classify by default whitelist)
> - {llm_count} needs_llm_classification (no obvious signup event; LLM proposes in x2)
> - {lt_count} low_traffic (<5 gclid visitors; normally INSUFFICIENT_DATA unless a higher-precedence tracking error applies)
> - {ne_count} no_event_data (no events found; likely tracking not deployed)

**POSTCONDITIONS:**
- Every MVP has all seven flags computed (booleans): `missing_project_name`, `signup_classified`, `auto_default_match`, `low_traffic`, `no_event_data`, `needs_llm_classification`, `ga_clicks_without_ph_traffic`
- `.runs/iterate-cross-data-issues.json` exists with required schema

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x1a`.

```bash
python3 -c "import json; d=json.load(open('.runs/iterate-cross-data-issues.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; req=['missing_project_name','signup_classified','auto_default_match','low_traffic','no_event_data','needs_llm_classification','ga_clicks_without_ph_traffic']; bad=[m.get('name','?') for m in ms if any(k not in m for k in req)]; assert not bad, 'MVPs missing flags: %s' % bad"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x1a
```

**NEXT:** Read [state-x2-classify-signups.md](state-x2-classify-signups.md) to continue.
