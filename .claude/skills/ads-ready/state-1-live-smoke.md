# STATE 1: LIVE_SMOKE

**PRECONDITIONS:**
- STATE 0 is complete and Layer A passed.
- `.runs/ads-ready-context.json` exists with `static_only`, `phase`, `phase_2`, and `deploy_url` keys.
- When `static_only` is true, this state still runs and writes a skipped Layer B result artifact.

**ACTIONS:**

Run Layer B live smoke checks:

```bash
python3 .claude/scripts/lib/ads_ready_smoke.py \
  --context .runs/ads-ready-context.json \
  --static-result .runs/ads-ready-static-result.json \
  --output .runs/ads-ready-smoke-result.json
```

**POSTCONDITIONS:**
- `.runs/ads-ready-smoke-result.json` exists with the same result schema as `.runs/ads-ready-static-result.json`.
- Static-only runs write `.runs/ads-ready-smoke-result.json` with `skipped: true`.

**VERIFY:**
```bash
test -f .runs/ads-ready-smoke-result.json && python3 -c "import json; d=json.load(open('.runs/ads-ready-smoke-result.json')); assert d.get('overall_pass') is True or d.get('skipped') is True, 'Layer B failed: %d failure(s)' % d.get('failed_count', 0)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh ads-ready 1
```

**NEXT:** Read [.claude/patterns/state-99-epilogue.md](../../patterns/state-99-epilogue.md) to continue.
