# STATE x0c: DISCOVER_PRICING

Discovers each over-cap MVP's **monthly price** from its GitHub repo (and the live
site as a fallback), so the CPC unit-economics gate in state-x3 can run. The gate
forces NO_GO when an over-cap MVP's implied CAC (`ga_cpc_usd * cpc_payback_multiple`)
exceeds its `monthly_price_usd`; without a price the gate is dormant.

This state only processes **over-cap MVPs** (`cpc_usd > thresholds.max_cpc`) that
aren't already priced — the only MVPs whose verdict the gate can change. Prices are
cached to `experiment/iterate-cross-config.yaml` with provenance, so each MVP is
discovered once (like signup classification in x2). Operator overrides win.

## Why this state exists

The CPC gate needs each MVP's price, but the skill has no built-in source for it.
Per-MVP repos live in the `magpiexyz-lab` GitHub org and are fuzzy-matchable from
`project_name`. The price is usually in `experiment/experiment.yaml` (thesis prose)
or `src/app/pricing/page.tsx`; some MVPs are waitlist/free (no price → gate stays
off, correctly) or expose the price only on the live site. Regex alone misreads
the spec (it also lists competitor prices, target-user income, annual/lifetime, and
tiers), so a script fetches **price-candidate snippets** and the lead LLM picks the
product's own monthly price — the same prepare → extract → persist shape as x2.

**Best-effort, never blocking.** If `gh` is unavailable, a repo doesn't match, or no
price is found, the MVP is stamped with a `price_unmapped_reason` and stays unpriced
— the gate simply doesn't fire for it (the existing `cpc_price_unmapped` advisory in
x3 surfaces it). This state has NO hard gate.

**PRECONDITIONS:**
- STATE x0b POSTCONDITIONS met (`.runs/iterate-cross-context.json` has DB fields)
- `.runs/iterate-cross-context.json` records carry `ga_cpc` / `ga_currency` (from state-x0a's CSV merge) so over-cap targets can be computed

**ACTIONS:**

### Step 0: gh availability (graceful skip)

```bash
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  GH_OK=true
else
  GH_OK=false
  echo "WARN: gh not available/authenticated — skipping repo price discovery." >&2
  echo "      MVPs stay unpriced; the CPC gate stays dormant for them (cpc_price_unmapped)." >&2
fi
```

If `GH_OK=false`, skip Steps 1–2 and run **only** Step 3 with an empty proposals
file (`echo '[]' > .runs/_iterate-cross-pricing-proposals.json`). Step 3 still
stamps every record with a `price_unmapped_reason` so the POSTCONDITIONS/VERIFY hold.

### Step 1a: resolve live hosts for over-cap targets (PostHog)

The live-site fallback needs a URL. Resolve the top `$current_url` host per over-cap
target from PostHog (over-cap MVPs all have paid traffic, so a host exists). Reuses
`select_over_cap_targets` so the over-cap definition lives in one place.

```bash
python3 - <<'PY'
import json, os, sys
sys.path.insert(0, '.claude/scripts/lib')
import yaml
from iterate_cross_pricing import select_over_cap_targets
from iterate_cross_posthog_batch import _posthog_query

ctx = json.load(open('.runs/iterate-cross-context.json'))
config = yaml.safe_load(open('experiment/iterate-cross-config.yaml')) or {}
targets = select_over_cap_targets(ctx['mvps'], config)
hosts = {}
if targets:
    project_id = ctx['posthog_project_id']
    window_days = ctx['window_days']
    api_key = open(os.path.expanduser('~/.posthog/personal-api-key')).read().strip()
    placeholders = ', '.join('{t%d}' % i for i in range(len(targets)))
    values = {f't{i}': t for i, t in enumerate(targets)}
    sql = (
        "SELECT properties.project_name AS mvp, "
        "topK(1)(domain(coalesce(properties.$current_url, '')))[1] AS host "
        f"FROM events WHERE properties.project_name IN ({placeholders}) "
        f"AND timestamp >= now() - INTERVAL {window_days} DAY "
        "GROUP BY mvp"
    )
    try:
        pq = config.get('posthog_query') or {}
        resp = _posthog_query(sql, values, project_id, api_key,
                              max_time_seconds=int(pq.get('max_time_seconds', 120)))
        for row in resp.get('results', []):
            if row and row[0] and row[1]:
                hosts[row[0]] = row[1]
    except Exception as e:
        print(f'WARN: host resolution failed: {e}', file=sys.stderr)
json.dump(hosts, open('.runs/_iterate-cross-hosts.json', 'w'))
print(f'resolved {len(hosts)} live hosts for {len(targets)} over-cap targets')
PY
```

### Step 1b: prepare the extraction bundle

```bash
python3 .claude/scripts/lib/iterate_cross_pricing.py prepare \
  --context .runs/iterate-cross-context.json \
  --config experiment/iterate-cross-config.yaml \
  --hosts .runs/_iterate-cross-hosts.json \
  --output .runs/_iterate-cross-pricing-input.json
```

This selects over-cap unpriced MVPs, resolves each to a `magpiexyz-lab` repo via
the layered chain in `iterate_cross_pricing.resolve_repo_layered` (`github_repo`
override > `repo_aliases` > exact-name key > org-wide experiment.yaml
name-index > repo-description `"<name>:"` prefix > homepage-host match — the
name-index caches to `.runs/gh-name-index.json` and refreshes only repos pushed
since the last scan), fetches price-candidate snippets from
`experiment/experiment.yaml`, `src/lib/plan.ts`, `src/lib/pricing.ts`,
`src/app/pricing/page.tsx`, and buckets each MVP into `to_extract` (has
snippets), `repo_empty_try_live` (no snippets, has a live URL), or `no_source`.

### Step 2: lead extracts the price (inline, like x2)

Read `.runs/_iterate-cross-pricing-input.json`. For **each** MVP in `to_extract`,
inspect its `snippets` and decide the product's **own lowest monthly USD price**:

- **Ignore** competitor prices ("Optmyzr is $249/mo"), target-user income ("$2–5K/mo
  creator budgets"), annual/lifetime prices, and setup fees.
- **Tiers/ranges** ($29–$49) → take the **lowest paid** monthly tier.
- **Per-account/per-seat** ("$19/mo per account") → take that unit price.
- **Annual only** → divide by 12 and round.
- **Waitlist / free / "contact us" with no number** → `monthly_price_usd: null`,
  `price_unmapped_reason: "free_or_waitlist"`.

For each MVP in `repo_empty_try_live` (and any `to_extract` MVP whose snippets are
inconclusive), **WebFetch** its `live_pricing_url` (and the site root if `/pricing`
404s) and extract the monthly price the same way. If still nothing →
`monthly_price_usd: null`, `price_unmapped_reason: "not_found"`. MVPs in `no_source`
with no repo and no URL → `null`, `"not_found"`.

Write `.runs/_iterate-cross-pricing-proposals.json` as a JSON array:

```json
[
  {"name": "pmax-sentinel", "monthly_price_usd": 19, "source": "repo:experiment.yaml",
   "confidence": "high", "rationale": "thesis: 'Get daily alerts — $19/mo'"},
  {"name": "agent-lens", "monthly_price_usd": 500, "source": "repo:experiment.yaml",
   "confidence": "high", "rationale": "thesis names $500/mo team plan"},
  {"name": "rubber-duck-api", "monthly_price_usd": null, "source": "repo:experiment.yaml",
   "confidence": "high", "price_unmapped_reason": "free_or_waitlist",
   "rationale": "payment omitted; waitlist-stage"}
]
```

`confidence` ∈ {`high`, `medium`, `low`}. Set `price_unmapped_reason` only when
`monthly_price_usd` is null.

### Step 3: persist prices + provenance, stamp context

```bash
python3 .claude/scripts/lib/iterate_cross_pricing.py persist \
  --context .runs/iterate-cross-context.json \
  --config experiment/iterate-cross-config.yaml \
  --proposals .runs/_iterate-cross-pricing-proposals.json
```

Writes `monthly_price_usd` + `price_source` + `price_classified_by: x0c-<confidence>`
+ `price_classified_at` into `mvp_mappings.<name>` (preserving `price_classified_by:
operator` locks and all other operator fields), and stamps every context record with
`monthly_price_usd` / `price_source` / `price_unmapped_reason` (found → reason null;
under cap → `not_over_cap`; over-cap with no price → `free_or_waitlist` / `not_found`).
State-x1 `iterate_cross_propagate` carries `monthly_price_usd` into the verdict
records; state-x3 `compute_cpc_flags` consumes it.

### Cleanup

```bash
rm -f .runs/_iterate-cross-hosts.json .runs/_iterate-cross-pricing-input.json .runs/_iterate-cross-pricing-proposals.json
```

**POSTCONDITIONS:**
- Every MVP record in `.runs/iterate-cross-context.json` has `monthly_price_usd`, `price_source`, `price_unmapped_reason`
- Invariant: `monthly_price_usd is None` ⟺ `price_unmapped_reason is not None`
- Over-cap MVPs with a discovered price have `monthly_price_usd` + provenance written to `mvp_mappings.<name>` in config (idempotent; operator locks preserved)

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x0c`.

```bash
python3 -c "import json; d=json.load(open('.runs/iterate-cross-context.json')); ms=d.get('mvps',[]); assert isinstance(ms, list) and len(ms)>0, 'mvps empty'; req=['monthly_price_usd','price_source','price_unmapped_reason']; bad=[m.get('name','?') for m in ms if any(k not in m for k in req)]; assert not bad, 'MVPs missing pricing fields: %s' % bad; inv=[m.get('name','?') for m in ms if (m.get('monthly_price_usd') is None) != (m.get('price_unmapped_reason') is not None)]; assert not inv, 'price/reason invariant failed: %s' % inv"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x0c
```

**NEXT:** Read [state-x1-gather-all-data.md](state-x1-gather-all-data.md) to continue.
