# STATE 19b: VERIFY (embed)

> This state is handled by `lifecycle-next.sh` transparent embed dispatch.
> The agent does not read this file directly — `lifecycle-next.sh` returns
> verify skill state files instead. When all verify states complete,
> `lifecycle-next.sh` returns `EMBED_COMPLETE:bootstrap:19b` and the agent
> advances this state via `advance-state.sh`.

**PRECONDITIONS:**
- STATE 19a POSTCONDITIONS met

**ACTIONS:**

Managed by `lifecycle-next.sh` embed dispatch. See `skill.yaml` `embed` field:
```yaml
embed:
  - at: "19b"
    skill: verify
    scope: full
```

**POSTCONDITIONS:**
- Verification procedure completed with scope: full
- Build passes
- verify-report.md exists with valid frontmatter
- PR delivery artifacts written by verify/state-8 bootstrap-verify mode (pr-title.txt, pr-body.md)

**VERIFY:**
```bash
head -1 .runs/verify-report.md | grep -q '^---$'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 19b
```

**NEXT:** TERMINAL — `lifecycle-finalize.sh` handles commit, push, PR creation, and auto-merge.
