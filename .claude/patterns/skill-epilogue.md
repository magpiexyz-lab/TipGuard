# Skill Epilogue — Unified Quality Assurance at Skill Termination

> **Calling convention (as of PR chore/unify-observation-architecture):**
> This procedure is now called by `finalize-epilogue.md` after
> `lifecycle-finalize.sh` completes — NOT by individual skill states.
> All skills use the same code path via `observation-phase.md`.
> Step 0 (state completion check) is handled by finalize.sh — skip it here.

Follow this procedure at the end of every skill. Observation scope is derived
from skill.yaml and passed to `observation-phase.md`.

## Applicability

All skills except `/optimize-prompt` (stateless utility, no state machine).

| Scope | Skills | When |
|-------|--------|------|
| **full** | `/bootstrap`, `/change`, `/distribute`, `/resolve`, `/review` | embed:verify OR critic/challenger agents + diffs |
| **code** | `/deploy`, `/spec`, `/upgrade` | Diffs exist, no critic agents |
| **process** | `/solve` | Critic agents, no diffs |
| **audit-only** | `/ads-ready`, `/audit`, `/iterate`, `/retro`, `/rollback`, `/teardown` | No agents, no diffs |

## Step 0: State completion check — HANDLED BY FINALIZE

> **Skip this step.** `lifecycle-finalize.sh` verifies state completion
> before calling this procedure. If states are incomplete, finalize warns
> and continues — the epilogue still runs (it is mandatory, not best-effort).

## Step 1: Collect evidence (artifact-based, not memory-based)

```bash
# a. Collect branch diffs — IDEMPOTENT with lifecycle-finalize.sh.
# lifecycle-finalize.sh Step 4 writes .runs/observer-diffs.txt PRE-merge using
# `git diff $MERGE_BASE...HEAD`. When skill-epilogue runs POST-merge (auto-merge
# completed), HEAD is already on main so `git merge-base main HEAD == HEAD` and
# the diff is empty — re-running the same command would clobber finalize's good
# evidence with 0 bytes. Only collect when .runs/observer-diffs.txt is absent or
# empty (fast-path skills that skipped finalize delivery, or standalone /observe).
if [ ! -s .runs/observer-diffs.txt ]; then
  if git log --oneline $(git merge-base main HEAD)..HEAD 2>/dev/null | grep -q .; then
    git diff $(git merge-base main HEAD)...HEAD > .runs/observer-diffs.txt
  else
    git diff --cached > .runs/observer-diffs.txt
    git diff >> .runs/observer-diffs.txt
  fi
fi

# b. Read fix-log (if exists)
# .runs/fix-log.md — created during skill execution when retries/failures occur

# c. Generate template file list (canonical source: .claude/template-owned-dirs.txt)
cat .claude/template-owned-dirs.txt | grep -v '^#' | grep -v '^$' | xargs -I{} find {} -type f 2>/dev/null | sort
```

## Step 2: Write epilogue context

Write `.runs/epilogue-context.json`:
```json
{
  "skill": "<skill-name>",
  "mode": "epilogue",
  "timestamp": "<ISO 8601>",
  "branch": "<current branch>"
}
```

This file signals to `skill-agent-gate.sh` that the observer is being
spawned from a skill epilogue (not from verify.md), enabling the relaxed
prerequisite path.

## Step 3: Derive scope and run observation

### Scope derivation algorithm

Read `.claude/skills/<skill>/skill.yaml` for the active skill:

```python
import yaml, os

skill_yaml = yaml.safe_load(open(f'.claude/skills/{skill}/skill.yaml'))
diffs_exist = os.path.getsize('.runs/observer-diffs.txt') > 0 if os.path.exists('.runs/observer-diffs.txt') else False

# Critic/challenger agents that trigger process observation
CRITIC_AGENTS = {'solve-critic', 'resolve-challenger', 'review-challenger'}

# Check for embed:verify — accept both dict-shape (legacy) and
# list-of-dicts shape (current). Issue #1127.
has_embed_verify = False
embed = skill_yaml.get('embed')
embed_entries = []
if isinstance(embed, dict):
    embed_entries = [embed]
elif isinstance(embed, list):
    embed_entries = [e for e in embed if isinstance(e, dict)]
if any(e.get('skill') == 'verify' for e in embed_entries):
    has_embed_verify = True

# Check for critic/challenger agents
agents = skill_yaml.get('agents', {})
has_critic = bool(CRITIC_AGENTS & set(agents.keys())) if isinstance(agents, dict) else False

# Derive scope
if has_embed_verify:
    scope = 'full'
elif has_critic and diffs_exist:
    scope = 'full'
elif has_critic:
    scope = 'process'
elif diffs_exist:
    scope = 'code'
else:
    scope = 'audit-only'
```

### Execute observation

Read `.claude/patterns/observation-phase.md` and follow its procedure with
the derived `scope` and `skill` parameters.

## Constraints

- **Mandatory execution, graceful degradation.** The epilogue must always
  execute. If a step fails, retry once. If it still fails, write
  `observe-result.json` with `"verdict": "error"` and `"error_reason"` —
  do NOT silently write `"clean"`. External service failures degrade filing
  to local logging but do not skip evaluation.
- **Max 1 observer spawn per epilogue.** Combine all evidence into a single evaluation.
- **No project-specific data in observer prompt.** Follow observe.md redaction rules.
