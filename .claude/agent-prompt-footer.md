<!-- DIRECTIVES:batch_search,pr_changed_first,context_digest,pre_existing -->

## Efficiency Directives
1. **Batch searches**: Use Grep with glob patterns (e.g., `glob: "src/**/*.tsx"`) instead of reading files one by one.
2. **PR-changed files first**: Check files from `git diff --name-only $(git merge-base HEAD main)...HEAD` before scanning the full source tree.
3. **Context digest**: [Provided above — pages, behavior IDs, event names, golden_path steps from experiment.yaml]
4. **Pre-existing changes**: Edit-capable agents should ignore pre-existing uncommitted changes outside the PR file boundary.

## Trace Requirements
1. **First action**: Your absolute first tool call must initialize your trace: `python3 scripts/init-trace.py <agent-name>`. This registers your presence so the orchestrator can detect incomplete work if you exhaust turns.
2. **Verdict vocabulary**: Write your `verdict` field using the exact casing from `.claude/patterns/agent-trace-protocol.md` (Verdict Values table). Casing is normative.
3. **Completion trace via canonical writer (AOC v1.1)**: After all work, write your final trace through `bash .claude/scripts/write-agent-trace.sh <agent-name> --json '<payload>'`. Direct `Write`/`Edit` of `.runs/agent-traces/*.json` is blocked by hooks (`agent-trace-write-gate.sh`); direct Python `open(..., 'w')` is blocked by `agent-trace-write-guard.sh`. The writer stamps `agent`, `timestamp`, `status`, `provenance`, `partial`, `run_id`, `skill`, `spawn_sha`, and `spawn_index` from active identity + spawn-log; your payload contributes `verdict`, `result`, `checks_performed`, and any agent-specific structured fields.
4. **Parallel-spawn agents** (e.g., scaffold-pages, implementer with task-slug): pass **both** `--trace-filename '<agent>-<slug>.json'` (matches your `init-trace.py` stub) **and** `--spawn-index <N>` (your spawn_index from spawn metadata) so the writer disambiguates sibling spawn-log rows.
5. **Partial outcomes**: if you must report a degraded result, use `python3 .claude/scripts/write-degraded-trace.py <agent-name> --reason '<...>'` (also accepts `--spawn-index`). See `.claude/patterns/agent-output-contract.md` § Canonical Writer Policy for the full per-artifact writer mapping.
