# STATE 5: FOO (synthetic fixture for state_defer_verify_pairing lint)

This state file declares defer_verify_when_writer in registry but does NOT
invoke write-gate-artifact.sh in its ACTIONS section. The lint rule must
flag this — without the invocation, the chain-aware gate skip would never
have a sibling writer to defer to.

**ACTIONS:**

Do something that does not produce .runs/test-foo.json.

**STATE TRACKING:**
```bash
bash .claude/scripts/advance-state.sh test 5
```
