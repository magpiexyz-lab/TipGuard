---
name: trace-writing-windows-blockers
description: Three template bugs that block write-agent-trace.sh on this Windows project; the workarounds that get a trace written
metadata:
  type: project
---

`.claude/scripts/write-agent-trace.sh` fails on this machine (win32 / Git Bash)
for three independent reasons. All three were hit and worked around during the
bootstrap SETUP phase on 2026-08-06. None are fixed in the template — verify
before assuming they still apply.

1. **`os.rename` is not atomic-overwrite on Windows** (~line 453). Raises
   `FileExistsError WinError 183` whenever the destination exists. Because the
   protocol is "`init-trace.py` writes a `status=started` stub, then the writer
   overwrites it", the destination *always* exists — so on Windows every
   trace write fails after init-trace has run.
   *Workaround:* `rm -f .runs/agent-traces/<agent>.json` before calling the writer.
   *Real fix:* `os.replace` instead of `os.rename`.

2. **48h staleness cap in `resolve_active_identity`** (`.claude/hooks/lib-state.sh`).
   Measured against the context's immutable `timestamp` (run start, embedded in
   `run_id`), not `written_at` (last activity). Any interactive multi-day skill
   run ages out and the writer then errors with "no active skill context on
   current branch". Bumping `timestamp` is NOT safe — `run_id` derives from it.
   *Workaround:* pass `--provenance lead-orchestrated --source-run-id <run_id>
   --source-skill <skill>`, reading `run_id` from `.runs/<skill>-context.json`.
   Side effect: the trace is stamped `provenance=lead-orchestrated` and
   `partial=true`, and `spawn_index` may not match the real spawn number.

3. **`--json` argv truncates near 8KB** under Git Bash. Symptom: "ERROR: --json
   is not valid JSON: Unterminated string starting at ... char 7951". AOC v1.3
   asks for `template_recommendations` + `workarounds` + `template_gap_observed`
   prose in one payload, which reaches 8KB easily.
   *Workaround:* condense the prose below ~7000 chars (print `len(json.dumps(trace))`
   first). There is no `--json-file` option.

**Why:** these are template-level defects, not project code — so they will recur
for every trace-writing agent in this repo until `/upgrade` pulls a fix.

**How to apply:** when any agent reports it cannot write its trace, go straight
to this list rather than re-diagnosing. All three are filed as
`template_gap_observed` entries in the scaffold-setup trace.

See also [[bootstrap-setup-state]].
