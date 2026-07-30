# STATE 6: USER_APPROVAL

**PRECONDITIONS:**
- Plan presented (STATE 5 POSTCONDITIONS met)

**ACTIONS:**

**STOP.** End your response here. Say:
> Plan ready. How would you like to proceed?
> 1. **approve** — continue implementation now
> 2. **approve and clear** — save plan, then clear context for a fresh start
> 3. Or tell me what to change

<!-- prose-gate:bootstrap-state-6-user-approval -->
DO NOT proceed to STATE 7 until the user explicitly replies with approval.
If the user requests changes instead of approving, revise the plan to address their feedback and present it again (return to STATE 5). Repeat until approved.

**POSTCONDITIONS:**
- User has explicitly approved the plan (option 1 or 2)

**VERIFY:**
<!-- VERIFY=true: Human approval gate — user approval is conversational, not artifact-based.
     advance-state.sh execution is the proof of approval. -->
```bash
echo "User approval received"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 6
```

**NEXT:** Read [state-7-save-plan.md](state-7-save-plan.md) to continue.
