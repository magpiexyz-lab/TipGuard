# Debugging Guide

> Reference only. This guide maps debugging scenarios to existing skills and patterns.
> No new skills or states are created by this guide.

## Scenario Routing Table

| Scenario | Entry Point | What It Does |
|----------|------------|--------------|
| Build error during /bootstrap or /change | Handled automatically by BUILD_LINT_LOOP (`verify/state-1`) | 3 fix attempts with error feedback. On exhaustion: structured diagnosis with category, evidence, and suggested next step. |
| Bug found by behavior-verifier | Handled automatically in /verify (`verify/state-2`) | B1-B6 classification with diagnostic hints per category. Findings include investigation guidance. |
| User discovers bug in running app | `/change "fix: <symptom>"` | Bug triage (`systematic-debugging.md` Phases 1-2) during exploration, then targeted diagnosis and minimal fix. |
| Bug filed as GitHub issue | `/resolve #<issue>` | Full 11-state workflow: fetch, triage, reproduce, blast radius, root cause, fix design, implement, validate. |
| Production incident | Follow `incident-response.md` | Severity-based response: P0/P1 rollback first, then root cause analysis. |
| Unclear if template or project bug | Check `systematic-debugging.md` Phases 1-2 | Observe symptoms, hypothesize causes, determine attribution (template file vs. project code). |
| Prior /verify failed, now fixing | `/change "fix: <remaining errors>"` | Reads diagnostic context from `verify-context.json`. Prior attempts and error category carry forward automatically. |

## Key References

- **`systematic-debugging.md`** -- 4-phase methodology: Observe, Hypothesize, Test, Fix. Used by bug triage in `/change` Fix type.
- **`incident-response.md`** -- Production incident severity classification and response procedures.
- **`behavior-verifier.md`** -- B1-B6 failure taxonomy with diagnostic hints for runtime behavioral bugs.
- **`state-1-build-lint-loop.md`** -- BUILD_LINT_LOOP with structured diagnosis on exhaustion.

## When NOT to Use a Debugging Workflow

- **Build passes, behavior is correct, but code quality is poor** -- Use `/review` instead.
- **Need to add tests** -- Use `/change "test: ..."` instead.
- **Architecture question, not a bug** -- Use `/solve` instead.
- **Template improvement idea, not a bug** -- File a GitHub issue on the template repo.
