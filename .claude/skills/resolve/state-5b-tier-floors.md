# STATE 5b: TIER_FLOORS (warn-mode in M2 launch; flips to deny-mode in follow-up PR)

**PRECONDITIONS:**
- Fix design complete (STATE 5 POSTCONDITIONS met)
- `.runs/solve-trace.json` exists with `solution_design`
- `.runs/resolve-reproduction.json` exists with per-issue `reproduction.method`

**ACTIONS:**

Run the file-class tier-floor classifier. It reads:

- `.runs/solve-trace.json` — which files the fix plans to modify
- `.runs/resolve-reproduction.json` — per-issue reproduction.method (the tier the lead chose at STATE 3)
- `.claude/patterns/resolve-tier-floors.yaml` — file-class → minimum required tier mapping

For each issue, computes the highest required floor across all files the fix
touches, and cross-checks against the actual reproduction tier. Reports
violations to stderr and writes `.runs/resolve-tier-floors.json`.

```bash
python3 .claude/scripts/resolve-tier-floors.py
```

**Mode (warn-mode in M2 launch):** the script ALWAYS exits 0 in warn-mode.
Violations are logged to stderr and recorded in the artifact, but they do not
halt the /resolve run. This soak window collects 1 week of post-merge data
to confirm the YAML rules are well-tuned (false-positive rate, missing rules).

**Future flip to deny-mode:** a follow-up PR will (a) flip the registry VERIFY
to assert `violations == []`, and (b) flip the script's default mode to deny.
After the flip, any tier-floor violation will halt /resolve at this state and
require the lead to either re-reproduce the issue at the higher tier OR drop
the issue from actionable scope.

**Why this exists (issue surfaced post-PR #1397):** the lead can choose any
reproduction tier at STATE 3 (cite is the cheapest). Pre-M2, even when the fix
touches `package.json` (a runtime/version-pinned file where claims need
isolated-repl evidence), the lead could ship with `cite` or worse. Critic
round-1 was the de-facto tripwire — but it's expensive (~20min per discovered
gap) and unreliable (only catches internal inconsistencies). M2 makes the
tripwire deterministic and post-design (sees the actual blast radius).

**POSTCONDITIONS:**
- `.runs/resolve-tier-floors.json` exists with `violations[]` and `passes[]` arrays
- Warn-mode: violations are logged but never halt; deny-mode (future): violations halt
- Each violation record cites which rules matched and which files triggered them

**VERIFY:**
```bash
test -f .runs/resolve-tier-floors.json && python3 -c "import json; d=json.load(open('.runs/resolve-tier-floors.json')); assert 'violations' in d, 'violations field missing'; assert 'passes' in d, 'passes field missing'; print(f'tier-floors: mode={d.get(\"mode\")}, violations={len(d.get(\"violations\",[]))}, passes={len(d.get(\"passes\",[]))}')"  # .runs/resolve-tier-floors.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 5b
```

**NEXT:** Read [state-5d-adversarial-challenge.md](state-5d-adversarial-challenge.md) to continue.
