# STATE 4: CHECK_PRECONDITIONS

**PRECONDITIONS:**
- Duplicate check resolved (STATE 3b POSTCONDITIONS met)

**ACTIONS:**

Follow checkpoint-resumption protocol per `patterns/checkpoint-resumption.md`.

- If `.runs/current-plan.md` exists and the current branch starts with `feat/bootstrap`:
  1. Read frontmatter. If frontmatter parsing fails: stop and tell the user: "Plan file has corrupted frontmatter. Delete `.runs/current-plan.md` and re-run `/bootstrap` to start fresh." Use values directly — do NOT re-resolve archetype or stack. Read context_files to restore context.
  2. Resume per /bootstrap checkpoint mapping:

     | Checkpoint | Resumes at |
     |-----------|------------|
     | `phase2-setup` | STATE 9 (setup phase) |
     | `phase2-design` | STATE 10 (design phase) |
     | `phase2-scaffold` | STATE 11 (core scaffold) |
     | `phase2-wire` | STATE 14 (wire phase) |
     | `awaiting-verify` | STATE 19a (verify prep) |

  3. If no frontmatter (old format): skip States 1-7, jump to STATE 8.
- If `package.json` exists AND `src/app/` contains page or route entry points:
  VERIFY: `find src/app -name 'page.tsx' -o -name 'route.ts' 2>/dev/null | head -1`
  If output is non-empty: stop and tell the user: "This project has already been bootstrapped. Use `/change ...` to make changes, or run `make clean` to start over."
- If `package.json` exists but the `src/` directory does NOT contain application files: warn the user: "A previous bootstrap may have partially completed. I'll continue from the beginning — packages may be reinstalled." Note: the branch name `feat/bootstrap` may already exist from the previous attempt. If so, this run will use `feat/bootstrap-2` — you can delete the old branch later with `git branch -d feat/bootstrap`. Then proceed.

- **Write preconditions artifact** (`.runs/bootstrap-preconditions.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json, shutil, os
  trace = {
      'node_available': shutil.which('node') is not None,
      'git_clean': True,  # set to False if uncommitted changes detected
      'no_existing_src': not any(
          os.path.exists(os.path.join('src/app', f))
          for f in ['page.tsx', 'route.ts']
      )
  }
  print(json.dumps(trace))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/bootstrap-preconditions.json \
    --payload "$PAYLOAD" \
    --skill bootstrap
  ```

**POSTCONDITIONS:**
- Decision made: fresh start, resume at specific state, or stop (already bootstrapped)
- If resuming: archetype, stack, and checkpoint restored from frontmatter
- `.runs/bootstrap-preconditions.json` exists with `node_available` field

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/bootstrap-preconditions.json')); assert 'node_available' in d, 'node_available missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 4
```

**NEXT:** STATE 5 (fresh) | STATE 9/10/11/14/19 (resume). Read the appropriate state file:
- Fresh start: [state-5-present-plan.md](state-5-present-plan.md)
- Resume phase2-setup: [state-9-setup-phase.md](state-9-setup-phase.md)
- Resume phase2-design: [state-10-design-phase.md](state-10-design-phase.md)
- Resume phase2-scaffold: [state-11-core-scaffold.md](state-11-core-scaffold.md)
- Resume phase2-wire: [state-14-wire-phase.md](state-14-wire-phase.md)
- Resume awaiting-verify: [state-19a-verify-prep.md](state-19a-verify-prep.md)
