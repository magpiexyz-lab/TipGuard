# STATE 0: STATIC_CHECKS

**PRECONDITIONS:**
- `.runs/ads-ready-context.json` exists with `static_only`, `phase`, `phase_2`, and `deploy_url` keys injected by the dispatcher's step 3 via `init-context.sh`.
- PostHog API token is available at `~/.posthog/personal-api-key`.

**ACTIONS:**

Run Layer A static checks:

```bash
python3 .claude/scripts/lib/ads_ready_static.py \
  --context .runs/ads-ready-context.json \
  --output .runs/ads-ready-static-result.json
```

The script returns 0 even if checks fail; state completion uses VERIFY for pass/fail. The script returns non-zero only on internal or environmental errors.

**POSTCONDITIONS:**
- `.runs/ads-ready-static-result.json` exists with schema:
  ```json
  {
    "skill": "ads-ready",
    "layer": "A",
    "checks": [
      {"id": 1, "name": "...", "applicable": true, "passed": true, "details": "...", "fix": null}
    ],
    "overall_pass": true,
    "applicable_count": 0,
    "passed_count": 0,
    "failed_count": 0,
    "skipped_count": 0
  }
  ```

**VERIFY:**
```bash
test -f .runs/ads-ready-static-result.json && python3 -c "import json; d=json.load(open('.runs/ads-ready-static-result.json')); assert d.get('overall_pass') is True, 'Layer A failed: %d failure(s)' % d.get('failed_count', 0)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh ads-ready 0
```

**NEXT:** Read [state-1-live-smoke.md](state-1-live-smoke.md) to continue.
