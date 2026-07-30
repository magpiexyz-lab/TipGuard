# STATE 5: FOO (synthetic fixture for state_defer_verify_pairing lint — clean case)

This state file declares defer_verify_when_writer in registry AND has the
matching write-gate-artifact.sh invocation in ACTIONS. The lint rule must
NOT flag this.

**ACTIONS:**

```bash
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/test-foo.json \
  --payload '{"ok": true}' \
  --skill test
```

**STATE TRACKING:**
```bash
bash .claude/scripts/advance-state.sh test 5
```
