# STATE 3a: VERIFY (embed)

> This state is handled by `lifecycle-next.sh` transparent embed dispatch.
> The agent does not read this file directly — `lifecycle-next.sh` returns
> verify skill state files instead. When all verify states complete,
> `lifecycle-next.sh` returns `EMBED_COMPLETE:distribute:3a` and the agent
> advances this state via `advance-state.sh`.

**PRECONDITIONS:**
- STATE 3 POSTCONDITIONS met (implementation complete, ad-readiness passed)

**ACTIONS:**

Managed by `lifecycle-next.sh` embed dispatch. See `skill.yaml` `embed` field:
```yaml
embed:
  - at: "3a"
    skill: verify
    scope: campaign
```

Skill attribution note: verify-context.json will use `"distribute"` as the
skill value (set by verify state-0 reading current-plan.md or context).

**POSTCONDITIONS:**
- verify.md completed and `.runs/verify-report.md` exists with valid frontmatter

**VERIFY:**
```bash
test -f .runs/verify-report.md && head -1 .runs/verify-report.md | grep -q '^---$'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh distribute 3a
```

**NEXT:** Read [state-3b-post-verify.md](state-3b-post-verify.md) to continue.
