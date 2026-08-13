---
name: trace-payload-argv-limit
description: write-agent-trace.sh --json silently truncates past ~8.1 KB on this Windows/msys bash; keep trace payloads under ~8000 chars
metadata:
  type: project
---

`bash .claude/scripts/write-agent-trace.sh <agent> --json '<payload>'` fails with
`--json is not valid JSON: Unterminated string starting at ... char ~8170`
whenever the serialized payload exceeds roughly 8.1 KB. The cutoff is in argv
delivery, not in the script: the JSON arrives truncated mid-string, so the
script's own parse is the thing that reports the error.

**Why:** this working copy runs Git Bash / msys on Windows, whose argv
conversion caps a single argument at ~8 KB. It is not a JSON-escaping bug — the
same payload round-trips fine through `json.loads` in-process. Observed on the
TipGuard bootstrap STATE 14 round on 2026-08-08, which cost five retry cycles
of progressively trimming prose before the write landed at 7951 chars.

**How to apply:** budget trace payloads to **under 8000 characters** serialized.
Practical tactics, in the order worth trying:
- `json.dumps(trace, separators=(",", ":"))` — saves ~5%.
- Put the load-bearing content first in your drafting: verdict, the required
  AOC fields (`workarounds`, `template_gap_observed`), and any per-issue
  resolution notes the coordinator asked for. Those are what downstream
  consumers read.
- Compress narrative prose, not structured fields. Long `security_notes` and
  `known_gaps` strings are the usual overflow source; `files_created` is
  contract-relevant and should survive.
- Write an interim trace early when a long round is at risk of being cut off —
  the writer overwrites atomically, so a short honest trace now beats a
  complete one that never lands.

The `--json` flag is the only input mode; there is no `--json-file`. Adding one
upstream would remove this constraint entirely and is worth proposing if this
recurs — see [[wire-phase-completion]] for the other wire-phase gotchas.
