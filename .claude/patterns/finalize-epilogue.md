# Finalize Epilogue (DEPRECATED — kept as compatibility shim)

> **This file is deprecated as of state-99 enforcement (fix #1043).**
>
> Skill epilogues now run as state `"99"` per skill; the canonical state
> file is `.claude/patterns/state-99-epilogue.md`, dispatched by
> `lifecycle-next.sh` via the patterns-dir fallback in `find_state_file`
> and enforced by `state-completion-gate.sh` on `advance-state.sh
> <skill> 99`.
>
> Command files no longer reference this file. It remains only so that
> old docs, stale agent prompts, or third-party tooling that hard-coded
> a read of `.claude/patterns/finalize-epilogue.md` keep working (they
> will read this shim and harmlessly do nothing).
>
> **Delete target: after the template-upgrade window expires for all
> downstream projects.** Tracked by observation follow-up to #1043.

## Migration for legacy callers

If you maintain a script or agent prompt that does `Read
.claude/patterns/finalize-epilogue.md`, replace that step with the
lifecycle-loop idiom:

```bash
# Instead of "read finalize-epilogue.md and execute", just let the loop
# dispatch state 99:
while true; do
  NEXT=$(bash .claude/scripts/lifecycle-next.sh <skill>)
  [[ "$NEXT" == "FINALIZE" ]] && break
  # ... execute $NEXT ...
done
```

`lifecycle-next.sh` returns the path to `state-99-epilogue.md` as the
last dispatch before `FINALIZE`. Its ACTIONS run
`lifecycle-finalize.sh`, the observation scope derivation, and
remediation — everything this epilogue used to list as prose.
