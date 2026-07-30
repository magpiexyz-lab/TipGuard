# TDD Task Generation

> Invoked by change-feature.md.
> See `patterns/tdd.md` for the full TDD workflow and task granularity rules.

## Task Generation

1. **Parse behaviors** from `experiment/experiment.yaml`. Each behavior in the
   `behaviors` array maps to one implementation task.

2. **Generate 1 task per behavior** with 2-5 minute scope. Each task specifies:
   - Exact files to create or modify
   - Unit test code (RED phase assertion)
   - Expected failure message
   - Minimal implementation (GREEN phase)

3. **Include tests entries.** Copy the behavior's `tests` array entries into the
   task description. The implementer agent must generate an `it()` assertion for
   each entry.

4. **Mark task type.** Classify each task as:
   - **Visual** — targets `.tsx` page or component files
   - **Logic** — everything else (API routes, utilities, hooks)

## Dependency Analysis

Analyze the task dependency graph per `patterns/tdd.md` section Task Dependency Ordering:

- **Independent tasks** (no imports between them) → spawn agents in parallel
- **Dependent tasks** (B imports A) → sequential execution: merge A's worktree,
  verify output on the branch, then spawn B

Tell user: "N tasks, M parallel / K sequential."

## Agent Spawning

For each task, spawn the appropriate agent with `isolation: "worktree"`:

| Task type | Agent | Reference |
|-----------|-------|-----------|
| Logic | `implementer` | `agents/implementer.md` |
| Visual (.tsx) | `visual-implementer` | `agents/visual-implementer.md` |

The visual-implementer auto-loads the `frontend-design` skill and applies
design quality during the GREEN phase.

> **Worktree isolation is mandatory.** Every `Agent(...)` call for
> implementer/visual-implementer MUST include `isolation: "worktree"`.
> Omitting this is a process violation — G4 will BLOCK.

## Implementer Contract

Each implementer follows the RED-GREEN-REFACTOR cycle:
1. **RED**: Write unit test from the `tests` entries → verify it fails
2. **GREEN**: Write minimal implementation → verify test passes
3. **REFACTOR**: Clean up without changing behavior

The implementer writes a trace to `.runs/agent-traces/{agent-type}-{task-slug}.json`
with fields: `agent`, `status`, `timestamp`, `task`, `files_changed`, `tdd_cycle`,
`worktree_merged`.
