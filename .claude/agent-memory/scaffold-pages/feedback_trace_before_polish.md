---
name: feedback-trace-before-polish
description: Write the terminal agent trace as soon as the assigned page compiles, before any polish pass
metadata:
  type: feedback
---

Create each assigned page in its simplest complete form, write the terminal
trace for it immediately, and only then go back and polish. Rewrite the trace
afterwards to match the polished state.

**Why:** the coordinator gave this instruction after two mid-task network
outages left `.runs/agent-traces/scaffold-pages-*.json` sitting as `started`
stubs. A stub trace reads to the orchestrator as an incomplete agent and blocks
the fan-out gate, even when the page on disk is fine. Trace files are cheap to
rewrite; a lost turn is not.

**How to apply:** when assigned multiple pages, finish page 1 → trace 1 →
page 2 → trace 2 → then polish both and rewrite both traces. Never batch all
traces to the end of the turn. See [[project-build-lock-contention]] for what to
put in `checks_performed` when the build gate cannot be run.
