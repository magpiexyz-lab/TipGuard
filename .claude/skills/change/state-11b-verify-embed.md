# STATE 11b: VERIFY (embed)

> This state is handled by `lifecycle-next.sh` transparent embed dispatch.
> The agent does not read this file directly — `lifecycle-next.sh` returns
> verify skill state files instead. When all verify states complete,
> `lifecycle-next.sh` returns `EMBED_COMPLETE:change:11b` and the agent
> advances this state via `advance-state.sh`.

**PRECONDITIONS:**
- STATE 11a POSTCONDITIONS met

**ACTIONS:**

Managed by `lifecycle-next.sh` embed dispatch. See `skill.yaml` `embed` field:
```yaml
embed:
  - at: "11b"
    skill: verify
    scope: full
```

**POSTCONDITIONS:**
- Verification procedure completed per scope
- Build passes
- verify-report.md exists with valid frontmatter

**VERIFY:**
```bash
head -1 .runs/verify-report.md | grep -q '^---$'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 11b
```

**NEXT:** Read [state-12-commit-and-pr.md](state-12-commit-and-pr.md) to continue.
