# STATE 1: USER_CONFIRMATION

**PRECONDITIONS:**
- Pre-flight checks passed (STATE 0 POSTCONDITIONS met)
- Deploy manifest read and parsed

**ACTIONS:**

### Ads reminder (print-only — no gate)

Before the summary, check for ad campaigns tied to this MVP:

```bash
if [ -f experiment/ads.yaml ]; then
  python3 - <<'PY'
try:
    import yaml
    ads = yaml.safe_load(open('experiment/ads.yaml')) or {}
except Exception:
    ads = {}
ids = []
def walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == 'campaign_id' and v:
                ids.append(str(v))
            else:
                walk(v)
    elif isinstance(node, list):
        for item in node:
            walk(item)
walk(ads)
if ids:
    print("⚠ REMINDER: this MVP has Google Ads campaign(s) recorded in experiment/ads.yaml:")
    for cid in ids:
        print(f"   campaign_id: {cid}")
    print("   Ask the Team Lead to PAUSE them in the Google Ads UI before/with this teardown —")
    print("   the /iterate --cross teardown reconcile will keep the obligation OPEN (ADS:unknown)")
    print("   until the operator records the pause via confirm-ads.")
PY
fi
```

This is deliberately a reminder, NOT a hard gate — MVP owners usually lack
Google Ads access, and a gate here would either block cleanup or invite false
declarations. The authoritative ads check lives in the operator repo's
`/iterate --cross` state-x4b (keyed `confirm-ads` confirmation).

### Present a summary:

```
## Teardown Plan

**Project:** <name>

**Resources to delete (in reverse order of creation):**
1. [If posthog] PostHog dashboard: #<dashboard_id>
2. [If stripe] Stripe webhook endpoint: <url>
3. [If hosting.domain] Custom domain: <domain>
4. [If hosting] Hosting project (<provider>): <project> — unlinks integrations
5. [If surface_url and no hosting] Surface project: <surface_url> — standalone surface deployment
6. [If database] Database project (<provider>): <ref/id> — permanent data loss
7. [If external_services] External services (manual): <list>

This action is irreversible. All data in the database will be permanently deleted.

To confirm, type the project name: **<name>**
```

**STOP.** Do not proceed until the user types the exact project name.

**POSTCONDITIONS:**
- User has typed the exact project name to confirm teardown

- **Record confirmation** in `teardown-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/teardown-context.json'))
  ctx['confirmed'] = True
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/teardown-context.json \
    --payload "$PAYLOAD" \
    --skill teardown
  ```

**VERIFY:**
```bash
python3 -c "import json; assert json.load(open('.runs/teardown-context.json')).get('confirmed') == True, 'confirmed not set'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh teardown 1
```

**NEXT:** Read [state-2-destroy-resources.md](state-2-destroy-resources.md) to continue.
