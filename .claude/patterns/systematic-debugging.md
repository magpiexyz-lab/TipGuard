# Systematic Debugging Procedure

Follow this procedure when diagnosing and fixing bugs. It enforces root cause
analysis over guesswork.

> **Scope:** This pattern applies to all projects regardless of `quality` setting.
> Use it whenever a bug is unclear, a fix attempt fails, or you catch yourself
> changing code without understanding why.

## Phase 1: Observe

Collect all symptoms before forming any hypothesis.

1. Read the full error message, stack trace, and relevant logs
2. Identify the exact input or action that triggers the failure
3. Note the expected behavior vs. actual behavior
4. List every observable fact — timestamps, affected files, environment state
5. Do NOT guess the cause yet

The goal is a complete symptom list. Premature hypotheses bias the investigation
toward confirming the first guess rather than finding the real cause.

## Phase 2: Hypothesize

Generate candidate root causes from the observations.

1. List up to 3 possible root causes, ranked by probability
2. Each hypothesis must be testable — there must be a way to confirm or rule it out
3. Prefer hypotheses that explain ALL observed symptoms, not just some
4. State what evidence would confirm each hypothesis and what would rule it out

Format:
```
H1 (most likely): <description>
  Confirm: <what you would observe if true>
  Rule out: <what you would observe if false>

H2: <description>
  Confirm: ...
  Rule out: ...
```

## Phase 3: Test

Test each hypothesis starting with the highest probability.

For each hypothesis:

1. Design a minimal experiment that distinguishes "confirmed" from "ruled out"
2. Run the experiment
3. Record the result factually
4. If confirmed — proceed to Phase 4 (Fix)
5. If ruled out — move to the next hypothesis

If all hypotheses are ruled out, return to Phase 1 with the new evidence
collected during testing. The failed experiments narrow the search space.

Minimal experiments include: adding a log statement, inspecting a variable,
running with a different input, commenting out a suspect block, checking
a database row, or reading a config value.

## Phase 4: Fix

Apply a minimal fix to the confirmed root cause.

1. Change only what is necessary to address the root cause — not symptoms
2. Verify the original symptoms are resolved (re-run the failing scenario)
3. Verify no new failures are introduced (run the existing test suite)
4. If the fix does not resolve the original symptoms, the hypothesis was wrong
   or incomplete — return to Phase 2 with the new evidence

A correct fix addresses the root cause. If you find yourself patching
multiple symptoms, reconsider whether you identified the actual root cause.

## Anti-Patterns

Avoid these common debugging mistakes:

- **Shotgun debugging** — Changing random things and re-running to see if the
  problem goes away. This wastes time and may introduce new bugs.
- **Fixing symptoms instead of root cause** — Adding null checks, try/catch
  blocks, or default values that mask the real problem. The bug will resurface
  in a different form.
- **Skipping the Observe phase** — Jumping straight to "I think the problem
  is X" without reading the error message or collecting facts. First guesses
  are often wrong.
- **Not verifying the fix** — Confirming the specific failure is gone but not
  checking whether the fix breaks other things. Always run the test suite after
  a fix.
- **Changing multiple things at once** — Making several changes before testing
  makes it impossible to know which change fixed the problem (or which one
  broke something else).
