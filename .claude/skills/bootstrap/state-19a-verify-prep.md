# STATE 19a: VERIFY_PREP

**PRECONDITIONS:**
- STATE 18 POSTCONDITIONS met (all files staged, BG4 PASS, commit-message.txt written)
- Checkpoint is `awaiting-verify`

**ACTIONS:**

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

- Re-read `.runs/current-plan.md` to verify implementation matches the approved plan. Check that every item in the plan has been addressed.
- **Note**: The next state (19b) runs the full verification procedure via embedded dispatch. scope `full` automatically spawns spec-reviewer as an additional parallel agent. No extra action needed.
- **Write conflict prevention**: verify.md requires edit-capable agents (design-critic, ux-journeyer) to run serially — not in parallel. The verification procedure handles this automatically. No extra action needed.
- **Pre-embed check-off (Issue #1118)**: state-19b is dispatched via embed and its ACTIONS section is not read by the lead (`lifecycle-next.sh` returns verify state files instead). Check off the verify-embed item here, immediately before the embed dispatch:
  - Check off in `.runs/current-plan.md`: `- [x] Verify embed completed (state 19b — scope: full)`
  This pre-marks the item as expected; if the embed exits abnormally, the rest of the lifecycle (epilogue, finalize) will surface the failure separately.

**POSTCONDITIONS:**
- Implementation reviewed against approved plan
- No plan items missed

<!-- VERIFY=true: plan review is manual agent judgment, no automatable postcondition -->
**VERIFY:**
```bash
true
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 19a
```

**NEXT:** Read [state-19b-verify-embed.md](state-19b-verify-embed.md) to continue.
