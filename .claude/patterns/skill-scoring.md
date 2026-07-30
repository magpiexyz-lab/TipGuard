# Skill Q-Score Protocol

Best-effort. Never blocks skill completion. `/verify`'s Check 19 is the only
hard gate — all other skills use `|| true` to ensure scoring failure is silent.

## Protocol

1. Read `.runs/<skill>-context.json` for `skill` and `run_id`
2. Compute skill-specific dimensions per the dimension registry in `q-score.md`
3. Pre-compute gate (skill-specific logic, passed as `--gate`)
4. Call the shared writer:

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/<skill>-context.json')).get('run_id', ''))" 2>/dev/null || echo "")

python3 .claude/scripts/write-q-score.py \
  --skill "<skill>" --scope "<scope>" --archetype "<archetype>" \
  --gate <gate> --dims '<JSON dimensions>' \
  --run-id "$RUN_ID" \
  || true
```

5. The `|| true` suffix ensures scoring failure never blocks the skill

## Constraints

- Call **BEFORE** cleanup (file deletions) in the terminal state — dimensions
  may read artifacts that cleanup deletes
- `/verify` uses `--raw` mode (dimension extraction stays inline in state-7
  because Check 19 requires the Q entry before verify-report.md is written)
- The script auto-generates `run_id` as `<skill>-<timestamp>` when `--run-id`
  is empty or omitted
