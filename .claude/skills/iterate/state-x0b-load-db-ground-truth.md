# STATE x0b: LOAD_DB_GROUND_TRUTH

Pulls authoritative signup counts from each MVP's primary database
(Supabase OR Railway Postgres), so x3 can cross-check PostHog's paid-signup
count against the database's actual signups and flag tracking divergence.

PostHog answers "how many paid users engaged with the page".
The database answers "how many actually completed signup".
The two should roughly agree; when they don't, that's a tracking gap worth
surfacing — not a verdict bug. stylica-ai's 33 (PH, including `activate`) →
2 (PH, `signup_complete`) → 6 (Supabase) is the canonical example: the gap
between 2 and 6 was a PostHog instrumentation delay (event added 2026-04-30
but first signup landed 2026-04-13).

Two passes run in sequence:
1. **Supabase pass** (Steps 1-2) — primary. Uses Management API to list
   projects, fuzzy-match MVP names, query signup tables.
2. **Railway pass** (Step 3) — fallback for MVPs the Supabase pass left
   unmapped. Uses `railway list --json` to enumerate Postgres-bearing
   projects, links each in a tempdir to pull DATABASE_PUBLIC_URL, queries
   via psql. Never overwrites a Supabase-sourced db_signups.

The two passes are interchangeable sources, but DB ground-truth as a whole is
**required by default** — it is the only path that filters test/team accounts
out of signup counts (via `iterate_cross_email_filter`). So if NO DB auth is
present at all, Step 0 fails fast (HALT), unless the operator opts out via
`require_db_ground_truth: false`, in which case every MVP ends with
`db_signups: null` and verdicts fall back to (unfiltered) PostHog counts.

## Why this state exists

Three classes of MVP-side tracking issues that PostHog cannot self-diagnose:

1. **Late instrumentation** — `signup_complete` track call added weeks after
   product launched. PH count looks too low; Supabase total exposes the gap.
2. **Wrong event name in `signup_events`** — operator-locked event over-counts
   (`activate` firing on image generation). PH count looks too high relative
   to actual DB rows.
3. **Broken backend signup** — PH fires events but DB never writes the user.
   PH count looks normal; Supabase has zero. Fixes a class of "we're paying
   for ads but the funnel is silently broken" bugs.

State-x3 consumes `db_signups` to emit sanity flags:
`ph_attribution_broken`, `ph_undercount`, `ph_overcount`, `late_instrumentation`,
plus the informational `db_union_multi_table` when ≥2 tables contribute.
State-x3 uses `db_signups_real` for verdict-source decisions; `db_signups`
remains the raw count for backward compatibility and operator audit. Both are
cross-table unions: all windowed email-bearing tables (public + `auth.users`
confirmed) are merged with gmail-normalized email dedupe, so the same person
in `waitlist` AND `auth.users` counts once and no table masks another.

**PRECONDITIONS:**
- STATE x0a POSTCONDITIONS met (`.runs/iterate-cross-context.json` exists with `ga_clicks` on every MVP)
- At least ONE of: a resolvable Supabase token whose live `GET /v1/projects` probe succeeds (via `SUPABASE_ACCESS_TOKEN`, `~/.supabase/access-token`, or one targeted macOS Keychain lookup) OR `railway whoami` returns logged-in (via `railway login`). **Both absent → Step 0 HALTs** (test/team signup filtering requires DB), unless `require_db_ground_truth: false` is set in `experiment/iterate-cross-config.yaml`.

**ACTIONS:**

### Step 0: Require DB auth (fail-fast), then detect Supabase availability

DB ground-truth is the ONLY path that scrubs test/team accounts from signup
counts (via `iterate_cross_email_filter`). Without it, verdicts use PostHog
signup counts that are NOT filtered for team/test — and most deploys never
capture an email in PostHog, so it cannot be patched there. So Step 0 first
**fails fast** when no DB auth exists at all (mirrors state-x0a's CSV gate),
gated by `require_db_ground_truth` (default `true`). The Supabase pass (Steps
1-2) is the primary source; the Railway pass (Step 3) is the fallback. Having at
least one auth source passes the gate; individual MVPs that genuinely have no DB
still soft-degrade to `db_signups: null`.

```bash
# --- Fail-fast: require at least one DB auth source (Supabase OR Railway) ---
REQUIRE_DB=$(python3 -c "
import os
try:
    import yaml
except ImportError:
    yaml = None
cfg = {}
p = 'experiment/iterate-cross-config.yaml'
if yaml is not None and os.path.exists(p):
    cfg = yaml.safe_load(open(p)) or {}
# Default true: fail-fast unless the operator explicitly opts out.
print('true' if cfg.get('require_db_ground_truth', True) else 'false')
")

python3 - <<'PY' > .runs/_iterate-cross-supabase-probe.json
import json, os, sys
sys.path.insert(0, '.claude/scripts/lib')
try:
    import yaml
except ImportError:
    yaml = None
from iterate_cross_db import _read_token, probe_supabase_projects

cfg = {}
p = 'experiment/iterate-cross-config.yaml'
if yaml is not None and os.path.exists(p):
    cfg = yaml.safe_load(open(p)) or {}
mappings = cfg.get('mvp_mappings') or {}
supabase_mapped = any(
    isinstance(v, dict) and bool(v.get('supabase_project_ref'))
    for v in mappings.values()
)
result = {
    'require_db_ground_truth': bool(cfg.get('require_db_ground_truth', True)),
    'supabase_mapped': supabase_mapped,
    'supabase_available': False,
    'reason': 'not probed',
}
try:
    token = _read_token()
    probe = probe_supabase_projects(token)
    result['supabase_available'] = bool(probe.get('ok'))
    result['reason'] = probe.get('reason')
    result['project_count'] = len(probe.get('projects') or [])
except SystemExit as exc:
    result['reason'] = str(exc)
except Exception as exc:
    result['reason'] = f'{type(exc).__name__}: {exc}'
print(json.dumps(result))
PY

SUPABASE_AVAILABLE=$(python3 -c "import json; d=json.load(open('.runs/_iterate-cross-supabase-probe.json')); print('true' if d.get('supabase_available') else 'false')")
SUPABASE_MAPPED=$(python3 -c "import json; d=json.load(open('.runs/_iterate-cross-supabase-probe.json')); print('true' if d.get('supabase_mapped') else 'false')")
SUPABASE_PROBE_REASON=$(python3 -c "import json; d=json.load(open('.runs/_iterate-cross-supabase-probe.json')); print(d.get('reason') or '')")

RAILWAY_AUTHED=false
if command -v railway >/dev/null 2>&1 && railway whoami 2>/dev/null | grep -q "@"; then
  RAILWAY_AUTHED=true
fi

if [ "$REQUIRE_DB" = "true" ] && [ "$SUPABASE_MAPPED" = "true" ] && [ "$SUPABASE_AVAILABLE" = false ]; then
  cat >&2 <<EOF
STOP: Supabase projects are mapped in experiment/iterate-cross-config.yaml, but the Supabase Management API probe failed.

Probe: token resolvable AND live GET /v1/projects must succeed.
Failure: ${SUPABASE_PROBE_REASON}

Fix Supabase auth/network and re-run /iterate --cross:
  - Export SUPABASE_ACCESS_TOKEN, or
  - Run supabase login, then verify: curl -H "Authorization: Bearer \$SUPABASE_ACCESS_TOKEN" https://api.supabase.com/v1/projects

Or explicitly accept PostHog/Railway-only degradation by setting:
  require_db_ground_truth: false
EOF
  exit 1
fi

if [ "$REQUIRE_DB" = "true" ] && [ "$SUPABASE_AVAILABLE" = false ] && [ "$RAILWAY_AUTHED" = false ]; then
  cat >&2 <<'EOF'
STOP: /iterate --cross requires DB ground-truth, but no DB auth is available.

Why: signup verdicts must exclude test/team accounts. That filter only runs on
the database path (Supabase/Railway). With no DB access, verdicts fall back to
PostHog signup counts that are NOT scrubbed of team/test accounts — and most
deploys do not capture an email in PostHog, so it cannot be done there either.

Fix one (or both), then re-run /iterate --cross:
  - Supabase:  supabase login
  - Railway:   ! railway login   (the `!` prefix runs the browser flow in-session)

Or accept PostHog-only verdicts (NOT recommended — signups will include
test/team accounts) by setting in experiment/iterate-cross-config.yaml:
  require_db_ground_truth: false
EOF
  exit 1
fi

# --- Detect Supabase availability (primary pass) ---
if [ "$SUPABASE_AVAILABLE" = false ]; then
  echo "WARN: Supabase Management API probe failed. Skipping Supabase pass." >&2
  echo "       Failure: $SUPABASE_PROBE_REASON" >&2
  echo "       Will still try Railway pass (Step 3) as fallback." >&2
  echo "       Export SUPABASE_ACCESS_TOKEN or run \`supabase login\` to enable the Supabase cross-check." >&2
  # Pre-stamp every MVP with the COMPLETE null-DB schema (all x0b VERIFY fields),
  # reusing the canonical iterate_cross_db._empty_ground_truth so the opt-out /
  # Supabase-absent path still satisfies postconditions. A subsequent Railway
  # pass (Step 3) refines matched MVPs; unmatched ones keep this schema.
  PAYLOAD=$(python3 -c "
import json, sys
try:
    import yaml
except ImportError:
    yaml = None
sys.path.insert(0, '.claude/scripts/lib')
from iterate_cross_db import _empty_ground_truth
ctx = json.load(open('.runs/iterate-cross-context.json'))
cfg = {}
if yaml is not None:
    try:
        cfg = yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}
    except Exception:
        cfg = {}
mappings = cfg.get('mvp_mappings') or {}
for m in ctx['mvps']:
    mapping = mappings.get(m.get('name')) or {}
    status = mapping.get('lifecycle_status') or m.get('lifecycle_status') or 'active'
    m['lifecycle_status'] = status
    if mapping.get('lifecycle_status_at'):
        m['lifecycle_status_at'] = mapping.get('lifecycle_status_at')
    if mapping.get('supabase_project_ref'):
        m['supabase_project_ref'] = mapping.get('supabase_project_ref')
    reason = 'orphan' if m.get('orphan') else ('archived_killed' if status == 'killed' else 'no_token')
    m.update(_empty_ground_truth(reason))
print(json.dumps(ctx))
")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/iterate-cross-context.json \
    --payload "$PAYLOAD" \
    --skill iterate-cross
fi
```

### Step 1: Fuzzy-match MVPs to Supabase projects + operator confirm

Skipped entirely when `SUPABASE_AVAILABLE=false`. Run the whole `if`-block:

```bash
if [ "$SUPABASE_AVAILABLE" = "true" ]; then
  python3 .claude/scripts/lib/iterate_cross_db.py merge \
    --context .runs/iterate-cross-context.json \
    --config experiment/iterate-cross-config.yaml \
    --run-dir .runs > .runs/_iterate-cross-db-step1.json
  STEP1_EXIT=$?
fi
```

The script reads context, calls Supabase Management API to list all projects
accessible to the token, fuzzy-matches each MVP name against project names by
normalized-name (strip non-alphanumerics + lowercase) using three strategies:

1. Exact match (`stylica-ai` == `stylica-ai`)
2. Project name contains MVP name (`neuralpost` vs `neuralpost-prod`)
3. MVP name contains project name (rarer)

**Exit codes:**
- `0` (merged): every MVP either has `supabase_project_ref` in config, no
  fuzzy-match candidate (logged as unmapped), or was just auto-matched and
  the queries succeeded. Proceed.
- `2` (needs_confirm): one or more MVPs got an auto-match that's about to
  be persisted to config. Print the proposed mapping to the operator and
  re-run with `--auto-confirm` once they've eyeballed it. This includes
  `match_type: rebuilt-ref` proposals — the config ref is absent from the
  live org list while an exact-name project exists under a different id
  (member deleted + recreated the project; the ShelfCurve 2026-07-24
  incident). Confirming updates the ref instead of letting the stale one
  read as a deleted backend.

```bash
if [ "$SUPABASE_AVAILABLE" = "true" ] && [ "$STEP1_EXIT" = "2" ]; then
  echo ""
  echo "═══ Proposed MVP → Supabase project mapping ═══" >&2
  python3 -c "
import json
d = json.load(open('.runs/_iterate-cross-db-step1.json'))
for m in d['needs_confirm']:
    alts = f'  [also: {len(m[\"alternatives\"])} other candidates]' if m.get('alternatives') else ''
    print(f\"  {m['mvp']:25s} → {m['project_ref']:25s}  {m['project_name']:25s}  ({m['match_type']}){alts}\")
print()
print(f'Unmapped (no Supabase project found): {d[\"unmatched\"]}')
" >&2
  echo "" >&2
  echo "Review the mapping above. If correct, re-run /iterate --cross." >&2
  echo "(The auto-match runs once per missing supabase_project_ref entry; subsequent runs read from config.)" >&2
  exit 1
fi
```

### Step 2: Persist mapping + query each project (run via merge --auto-confirm)

Re-invoke with auto-confirm to write the matched refs to config and execute
the queries:

```bash
if [ "$SUPABASE_AVAILABLE" = "true" ]; then
  python3 .claude/scripts/lib/iterate_cross_db.py merge \
    --context .runs/iterate-cross-context.json \
    --config experiment/iterate-cross-config.yaml \
    --run-dir .runs \
    --auto-confirm > .runs/_iterate-cross-db-step2.json

  python3 -c "
import json
d = json.load(open('.runs/_iterate-cross-db-step2.json'))
print(f'Supabase DB ground truth: queried={d[\"queried\"]} unmapped={d[\"unmapped\"]} errors={d[\"errors\"]}')
"
fi
```

The merge step writes per-MVP into `iterate-cross-context.json`:
- `supabase_project_ref` — the Supabase project ID
- `lifecycle_status` / `lifecycle_status_at` — copied from `mvp_mappings.<name>`; killed MVPs are archived in compute/render instead of being re-queried
- `db_signups` — int raw count in window; the cross-table union's deduped raw when the union candidate wins, else the winning residual (legacy/no-email) table's raw
- `db_signups_paid` — int count of union real emails carrying a shape-valid POPULATED `gclid`/`click_id` in ≥1 table; `0` when gclid columns exist but none validate; null when no contributing table has such a column
- `db_attribution` — `"gclid_shape"` iff `db_signups_paid > 0`, `"window"` otherwise (including present-but-dead gclid columns), null when unmapped
- `db_signups_table` — top real contributor, reporting only (e.g. `auth.users`, `public.waitlist`); counts are union-deduped across tables, not this table alone
- `db_union_tables` — tables contributing ≥1 real email to the union (`[]` on single-table/legacy/override paths)
- `db_first_signup_at` — ISO timestamp of earliest row in window (used by x3 for `late_instrumentation` flag)
- `db_breakdown` — per-table counts for transparency
- `db_unmapped_reason` — set to `"no_match"`, `"no_token"`, `"orphan"`, or `"archived_killed"` (killed policy skip — the row is NOT re-queried; this does NOT claim the backend is gone) when `db_signups` is null. `"project_deleted"` is reserved for OBSERVED deletions and is tombstone-CONFIRMED before it sticks: the SQL query endpoint 404s for both deleted and never-existed refs, so a query-path deletion signal is re-checked against `GET /v1/projects/<ref>` (`confirm_project_deleted`) — true tombstone keeps `project_deleted` (and persists the sticky `db_backend` record), a plain 404 downgrades to `"ref_invalid"` (bad/stale mapping, Railway fallback still runs, no rule-3 NO_GO), 403 → `"forbidden"`, flaky/alive → `"query_error"` (re-confirmed next run — deletion is never concluded on flaky evidence). The backend's verified knowledge state (alive / deleted_verified / never_existed / not_visible / never_located) lives in the sticky `mvp_mappings.<name>.db_backend {status, checked_at, evidence}` config record, maintained near-free by the merge (org project-list membership proves alive; refs absent from the list get a one-time `GET /v1/projects/<ref>` tombstone probe — HTTP 400 "Resource has been removed" = deleted_verified, 404 = never_existed, 403 = not_visible). Backfill/on-demand sweep: `python3 .claude/scripts/lib/iterate_cross_db.py verify-backends [--dry-run]`.

### Step 3: Railway fallback (sibling DB source)

For every MVP that the Supabase pass left as `db_signups: None` with a
retryable `db_unmapped_reason`, try Railway. The retryable set is pinned by
`RAILWAY_FALLBACK_REASONS` in `.claude/scripts/lib/iterate_cross_db.py`
(`no_match`, `no_token`, `no_email_column`, `project_deleted`, `ref_invalid`)
— a deleted or mis-mapped Supabase backend may simply mean the real DB lives
on Railway. Orphans and lifecycle-killed rows are additionally excluded
(`archived_killed` is a policy skip, never retried). This catches MVPs whose
primary DB lives on Railway-hosted Postgres instead of Supabase
(`Outcome-Oracle` pattern). The Supabase pass is preserved as authoritative —
Railway is a strict fallback and never overwrites a non-null `db_signups`.

```bash
# Same auto-confirm shape as Supabase step 2, but always one shot: Railway
# has far fewer Postgres projects than Supabase has projects, so ambiguity
# pressure is low. Bumping to a needs_confirm review path is future work.
python3 .claude/scripts/lib/iterate_cross_railway_db.py merge \
  --context .runs/iterate-cross-context.json \
  --config experiment/iterate-cross-config.yaml \
  --run-dir .runs \
  --auto-confirm > .runs/_iterate-cross-railway-step.json

python3 -c "
import json
d = json.load(open('.runs/_iterate-cross-railway-step.json'))
step = d.get('step')
if step == 'skipped_auth':
    print(f'Railway fallback skipped: {d.get(\"reason\")}')
    print('  (Run \`! railway login\` in the prompt box to enable Railway DB cross-check.)')
elif step == 'skipped_no_psql':
    print(f'Railway fallback skipped: {d.get(\"reason\")}')
    print('  (psql is the SQL client used to query Railway Postgres URLs.)')
elif step == 'no_candidates':
    print('Railway fallback: no Supabase-unmapped MVPs to retry.')
elif step == 'no_postgres_projects':
    print(f'Railway fallback: workspace has no Postgres-bearing projects ({d.get(\"unmapped\", 0)} MVPs stay unmapped).')
elif step == 'merged':
    print(f'Railway fallback: queried={d.get(\"queried\")} '
          f'still_unmapped={d.get(\"unmapped\")} errors={d.get(\"errors\")} '
          f'(of {d.get(\"total_candidates\")} candidates)')
"
```

Railway-side fields written into `iterate-cross-context.json` (additive to the
Supabase schema; do NOT overlap):

- `railway_project_id` — UUID of the Railway project (mirrors `supabase_project_ref`)
- `railway_project_name` — display name
- `railway_service_name` — which Postgres service won (e.g. `Postgres`, `Postgres-5HUP`)
- `db_source` — `"supabase"` or `"railway"` so x3/x4 can tell where the number came from
- `db_signups_table` — Railway-sourced tables are prefixed `railway:` (e.g. `railway:public.users`)
- `db_unmapped_reason` — on a Railway miss, refined to `"no_match_neither"` for the retryable reasons EXCEPT `project_deleted`, which is preserved (an observed deletion must stay visible; `archived_killed` never reaches this path)

**Railway-side preconditions:**
- `railway` CLI installed (`which railway`)
- Authenticated via `railway login` (token at `~/.railway/config.json`)
- `psql` available locally (queries use `DATABASE_PUBLIC_URL` proxy)

If any precondition fails, the step prints a notice and continues — Railway
is optional, just like Supabase token absence skips that pass.

### Step 4: Operator override hooks

When auto-discovery picks the wrong table OR you want to lock a fuzzy match
against future drift, the operator overrides in
`experiment/iterate-cross-config.yaml`:

```yaml
mvp_mappings:
  diarly:                                          # Supabase MVP
    supabase_project_ref: qiinzizrdjzlrhasddtw
    db_signup_table: public.waitlist_subscribers_only
  outcome-oracle:                                  # Railway MVP
    railway_project_id: 999fa04b-9c0b-47cd-af5e-5587c6bd9e49
    railway_service_name: Postgres                 # only needed when project has multiple PG services
    db_signup_table: public.users                  # same override field works for both sources
```

`db_signup_table` accepts `auth.<table>` (Supabase only; uses
`email_confirmed_at IS NOT NULL` filter) or `public.<table>` (uses the table's
discovered timestamp column for window filtering). Railway has no `auth.*`
schema so only `public.<table>` is valid there.

### Cleanup

```bash
rm -f .runs/_iterate-cross-supabase-probe.json .runs/_iterate-cross-db-step1.json .runs/_iterate-cross-db-step2.json .runs/_iterate-cross-railway-step.json
```

**POSTCONDITIONS:**
- Every MVP record has `db_signups`, `db_signups_raw`, `db_signups_real`, `db_signups_paid`, `db_attribution`, `db_signups_team`, `db_signups_test`, `db_signups_filter_audit`, `db_signups_real_windowed`, `lifecycle_status`
- Every MVP record has `db_unmapped_reason` when `db_signups_real` is null
  (a `RAILWAY_FALLBACK_REASONS` value if only Supabase was tried,
  `"no_match_neither"` if Railway was also tried and missed,
  `"project_deleted"` preserved through a Railway miss,
  `"no_token"` / `"orphan"` / `"archived_killed"` for the never-retried paths)
- MVPs that got auto-matched have `supabase_project_ref` OR `railway_project_id` written to config (idempotent)

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x0b`.

```bash
python3 -c "import json; d=json.load(open('.runs/iterate-cross-context.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; req=['db_signups','db_signups_raw','db_signups_real','db_signups_paid','db_attribution','db_signups_team','db_signups_test','db_signups_filter_audit','db_signups_real_windowed','db_first_signup_at','db_unmapped_reason','lifecycle_status']; bad=[m.get('name','?') for m in ms if any(k not in m for k in req)]; assert not bad, 'MVPs missing DB fields: %s' % bad; inv=[m.get('name','?') for m in ms if ((m.get('db_signups_real') is None) != (m.get('db_unmapped_reason') is not None))]; assert not inv, 'db_signups_real/db_unmapped_reason invariant failed: %s' % inv; paid_inv=[m.get('name','?') for m in ms if ((m.get('db_attribution') == 'gclid_shape') != (type(m.get('db_signups_paid')) is int and m.get('db_signups_paid') > 0))]; assert not paid_inv, 'db_attribution/db_signups_paid invariant failed: %s' % paid_inv; paid_bounds=[m.get('name','?') for m in ms if m.get('db_signups_paid') is not None and not (type(m.get('db_signups_paid')) is int and type(m.get('db_signups_real')) is int and 0 <= m.get('db_signups_paid') <= m.get('db_signups_real'))]; assert not paid_bounds, 'db_signups_paid bounds invariant failed: %s' % paid_bounds"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x0b
```

**NEXT:** Read [state-x0c-discover-pricing.md](state-x0c-discover-pricing.md) to continue.
