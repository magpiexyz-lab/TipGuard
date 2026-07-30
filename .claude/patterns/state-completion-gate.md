# State completion gate — chain semantics contract

`.claude/hooks/state-completion-gate.sh` is a **PreToolUse** hook. It runs
*before* the Bash command executes and inspects the command string for an
`advance-state.sh <skill> <state_id>` invocation. When it finds one, it runs
the state's VERIFY command from `.claude/patterns/state-registry.json` to
confirm the state's postconditions hold.

Because the hook fires **before** any segment of the chain has run, any
mutation that the chain itself was supposed to make is **not yet visible** to
the VERIFY assertion. This is the chain-vs-sequential contract.

## Anti-pattern: chained edit + advance-state in one Bash call

```bash
# ❌ DENIED by state-completion-gate.sh
sed -i 's/checkpoint: phase2-step6/checkpoint: phase2-step7/' .runs/current-plan.md \
  && bash .claude/scripts/advance-state.sh change <state>
```

When this state's VERIFY greps for `checkpoint: phase2-step7` in
`.runs/current-plan.md`, the hook runs BEFORE the sed, the file still contains
`step6`, the grep fails, and the entire Bash invocation is DENIED with:

> State completion gate: change STATE N postconditions not met. VERIFY failed:
> grep -q 'checkpoint: phase2-step7' .runs/current-plan.md — complete this
> state's actions before marking it done.

## Canonical fix: split into two Bash invocations

```bash
# ✅ Invocation 1 — mutate first
sed -i 's/checkpoint: phase2-step6/checkpoint: phase2-step7/' .runs/current-plan.md

# ✅ Invocation 2 — advance state (VERIFY now sees the mutated marker)
bash .claude/scripts/advance-state.sh change <state>
```

The hook is intentionally non-introspective on chain ordering — it cannot
reason "the sed earlier in the chain would have set the marker by the time the
advance-state runs." Splitting the chain is the only general-purpose fix.

## Sanctioned exception: `defer_verify_when_writer` (#1339)

For state-registry entries that opt in, the hook supports a deferred-VERIFY
mode when the chain contains a sibling segment writing one of an enumerated
set of paths via `write-gate-artifact.sh`. Shape:

```json
{
  "<skill>": {
    "<state_id>": {
      "verify": "test -f .runs/foo.json && python3 -c \"...\"",
      "defer_verify_when_writer": [".runs/foo.json"]
    }
  }
}
```

When the registry declares `defer_verify_when_writer` and the Bash chain
contains `bash .../write-gate-artifact.sh --path .runs/foo.json`, the hook
**skips** the synchronous VERIFY check. The deferred VERIFY runs inside
`advance-state.sh` pre-append (after the chain executes), so the gate stays
correct.

This mechanism only matches `write-gate-artifact.sh` segments. It does NOT
generalize to arbitrary `sed`/`jq`/`python` writers. If you need to mutate
`.runs/current-plan.md` (or any path not handled by `write-gate-artifact.sh`)
and then advance state in a sibling segment, **split the chain** per the
canonical fix above.

## Reading list

- `.claude/hooks/state-completion-gate.sh` — the hook implementation. Read for
  the exact decomposition + DENY semantics.
- `.claude/patterns/state-registry.json` — registry entries; search for
  `defer_verify_when_writer` for active opt-ins.
- `.claude/patterns/state-99-epilogue.md` — the epilogue pattern referenced by
  every skill at end-of-run. Cross-links here for skill authors.
