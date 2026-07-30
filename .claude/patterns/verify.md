# Verification Procedure

> **Process fidelity > throughput.** Every step exists because its value
> shows up in edge cases, not in the happy path. When a step's output
> "seems obvious," that is precisely when you must execute it — you
> cannot confirm it is obvious without executing. Skipping a step saves
> 2 minutes; fixing the consequences costs 2 hours.

Run this procedure after making code changes and before committing.

> **Do NOT skip this procedure.** Do NOT claim the build passes without running it. Do NOT commit without a passing build. There are no exceptions.

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, rows "Visual agents", "Performance + a11y agents".
>
> [visual-agents] web-app: design-critic, ux-journeyer, consistency-checker | service: skip | cli: skip
> [perf-a11y] web-app: performance-reporter, accessibility-scanner | service: skip | cli: skip

## Scope Parameter

This procedure accepts an optional **scope** that controls which review agents run.
If no scope is specified, the default is `full`.

| Scope      | Agents spawned                                                              |
|------------|-----------------------------------------------------------------------------|
| `full`     | build-info, design-critic\*, ux-journeyer\*, quality-fixer\*, behavior-verifier, security pair, perf\*\*, a11y\*\*, spec-reviewer\*\*\* |
| `security` | build-info, behavior-verifier, security pair, spec-reviewer\*\*\*           |
| `visual`   | build-info, design-critic\*, ux-journeyer\*, quality-fixer\*, perf\*\*, a11y\*\*            |
| `build`    | build-info only                                                             |

\* = skip if archetype is NOT `web-app`
\*\* = web-app only (existing gate)
\*\*\* = requires the listed scope (full or security)

behavior-verifier runs for all archetypes (web-app, service, cli) — it has archetype-specific procedures internally.

Build & Lint Loop, E2E Tests, Auto-Observe, and Save Notable Patterns ALWAYS run regardless of scope.

> **Agent spawning is determined by scope and archetype only** — never by which files were changed in this PR. Do NOT skip agents because "no pages were modified" or "only backend changed." If the scope table says an agent runs for this scope+archetype combination, spawn it.

> **The scope table is the sole authority.** The absence of a running app, missing screenshots, or "obvious" results are NEVER valid reasons to skip a scope-required agent. Agents degrade gracefully to static analysis when runtime is unavailable — but they still run. No exceptions.

---

## JIT State Dispatch

Read each STATE's file **only when transitioning to that state**. Do NOT read ahead. Complete the VERIFY check before reading the next state. This ensures you hold only one state's instructions in working memory at a time.

| STATE | Name | File |
|-------|------|------|
| 0 | READ_CONTEXT | [state-0-read-context.md](verify/state-0-read-context.md) |
| 1 | BUILD_LINT_LOOP | [state-1-build-lint-loop.md](verify/state-1-build-lint-loop.md) |
| 2 | PHASE1_PARALLEL | [state-2-phase1-parallel.md](verify/state-2-phase1-parallel.md) |
| 2a | PAGE_IMAGE_MAP | [state-2a-page-image-map.md](verify/state-2a-page-image-map.md) |
| 3a | DESIGN_AGENTS | [state-3a-design-agents.md](verify/state-3a-design-agents.md) |
| 3b | QUALITY_GATE | [state-3b-quality-gate.md](verify/state-3b-quality-gate.md) |
| 3c | UX_MERGE | [state-3c-ux-merge.md](verify/state-3c-ux-merge.md) |
| 3d | QUALITY_FIX | [state-3d-quality-fix.md](verify/state-3d-quality-fix.md) |
| 4 | SECURITY_MERGE_FIX | [state-4-security-merge-fix.md](verify/state-4-security-merge-fix.md) |
| 5 | E2E_TESTS | [state-5-e2e-tests.md](verify/state-5-e2e-tests.md) |
| 7a | WRITE_REPORT | [state-7a-write-report.md](verify/state-7a-write-report.md) |
| 7b | COMPUTE_QSCORE | [state-7b-compute-qscore.md](verify/state-7b-compute-qscore.md) |
| 8 | SAVE_PATTERNS | [state-8-save-patterns.md](verify/state-8-save-patterns.md) |

---

## Shared Algorithms

These are referenced by multiple STATEs. They remain here so per-STATE files can reference them by section anchor.

### Dev Server Preamble (if archetype is `web-app`)

Before spawning review agents, start the dev server in demo mode so
that all visual agents have a running app to screenshot:

1. Start dev server:
   ```bash
   DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run dev &
   DEV_PID=$!
   ```
2. Wait for ready: poll `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000`
   until 200 (max 30s, 2s interval). If timeout: warn user, continue —
   agents degrade to static analysis but are NOT skipped.
3. Pass `base_url: http://localhost:3000` to all agents that accept it.
4. **CHECKPOINT — Kill dev server.** After ALL review agents (Phase 1 + Phase 2) complete AND hard gate evaluation is done: `kill $DEV_PID 2>/dev/null || true`. This is a mandatory step — do not defer to STATE 7.

> **Why DEMO_MODE.** All external clients (Supabase, Stripe, Anthropic,
> PostHog) have demo fallbacks returning safe stub data. The dev server
> runs fully functional pages without any API keys. Playwright is
> installed during Setup Phase (`npx playwright install chromium`).
>
> **There is no valid reason to skip visual agents during bootstrap.**
> DEMO_MODE + Playwright = zero external dependencies.

### File Boundary for Edit-Capable Agents

Before spawning review agents, compute the PR file boundary:

```bash
git diff --name-only $(git merge-base HEAD main)...HEAD
```

> If `git diff` returns empty (standalone on `main` or shallow clone), fall back to all source files:
> ```bash
> find src/ -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \)
> ```

Pass this list to each agent that has Edit/Write permissions (design-critic, ux-journeyer, security-fixer, quality-fixer) as a hard constraint in the agent prompt:

> "You may ONLY modify files in this list: [files]. If you find issues in files outside this list, REPORT them in your verdict but do NOT edit them."

Read-only agents (observer, build-info-collector, behavior-verifier, security-attacker, security-defender, spec-reviewer, accessibility-scanner, performance-reporter) are unaffected.

### Agent Efficiency Directives

Include these directives in every agent spawn prompt (Phase 1 and Phase 2):

1. **Batch searches**: Use Grep with glob patterns (e.g., `glob: "src/**/*.tsx"`) instead of reading files one by one.
2. **PR-changed files first**: Check files from `git diff --name-only $(git merge-base HEAD main)...HEAD` before scanning the full source tree.
3. **Context digest**: Include the context digest summary (pages, behavior IDs, event names, golden_path steps) extracted in STATE 0 so agents don't need to re-read experiment.yaml.
4. **Pre-existing changes**: Edit-capable agents (design-critic, ux-journeyer, security-fixer, quality-fixer) should ignore pre-existing uncommitted changes that are outside the PR file boundary.

> **Template enforcement:** Read `.claude/agent-prompt-footer.md` and append its full content
> to every agent spawn prompt (Phase 1 and Phase 2). The skill-agent-gate hook checks
> for the directive marker in agent prompts.

### Trace State Detection

After each agent returns, check `.runs/agent-traces/<name>.json`:

| State | Condition | Meaning |
|-------|-----------|---------|
| 1 | File does not exist | Agent never started |
| 1 | File exists but `run_id` doesn't match verify-context.json | Stale trace from prior run |
| 2 | File exists, `"status":"started"`, no `"verdict"` | Agent exhausted turns |
| 3 | File exists, has `"verdict"` | Agent completed |

Detection command:
```bash
verdict=$(python3 -c "
import json, os
f = '.runs/agent-traces/<name>.json'
ctx_f = '.runs/verify-context.json'
if not os.path.exists(f):
    print('NO_FILE')
else:
    d = json.load(open(f))
    # Check run_id freshness
    trace_run_id = d.get('run_id', '')
    if trace_run_id and os.path.exists(ctx_f):
        ctx = json.load(open(ctx_f))
        ctx_run_id = ctx.get('run_id', '')
        if ctx_run_id and trace_run_id != ctx_run_id:
            print('STALE')  # Trace from a prior run
        else:
            print(d.get('verdict', 'MISSING'))
    else:
        # No run_id in trace — backward compat, treat as current
        print(d.get('verdict', 'MISSING'))
" 2>/dev/null || echo "NO_FILE")
```
- `NO_FILE` → state 1 (agent never started)
- `STALE` → state 1 (trace from prior run — treat as if agent never started)
- `MISSING` → state 2 (agent exhausted turns — started trace only)
- Any other value → state 3 (agent completed normally)

Use this algorithm for all trace checks in per-STATE files and in the Exhaustion Protocol.

### Recovery Traces

After all Phase 1 agents return, use Trace State Detection to check each spawned agent's trace in `.runs/agent-traces/<name>.json`.

If an agent returned output but crashed before writing its trace, write a recovery trace:

```bash
echo '{"agent":"<name>","timestamp":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","verdict":"<agent-verdict>","checks_performed":<agent-checks-array>,"recovery":true}' > .runs/agent-traces/<name>.json
```

The `checks_performed` array must match the agent's specification (see each agent's Trace Output section). The `"recovery":true` flag marks this as a lead-written trace — gate-keeper will WARN on recovery traces.

Do NOT write traces for agents that were not spawned. Do NOT write traces for agents whose output you never received.

### Exhaustion Protocol

When an agent returns but its trace has `"status":"started"` and no `"verdict"` field (Trace State 2), it exhausted its turn budget before completing work. Handle by tier:

| Tier | Agents | Action | On Double Exhaustion |
|------|--------|--------|---------------------|
| 1 | design-critic, ux-journeyer, security-fixer, quality-fixer | Retry once (focused scope) | Hard gate failure, skip remaining STATEs |
| 2 | behavior-verifier, security-attacker, security-defender, design-consistency-checker | Retry once | Recovery trace with `"status":"exhausted"`, WARN, continue |
| 3 | build-info-collector, observer, performance-reporter, accessibility-scanner, spec-reviewer | No retry | Recovery trace with `"status":"exhausted"`, WARN, continue |

#### Tier 1 — Critical edit-capable agents

**Detection**: Trace State 2 after agent returns.

**Action**: Before re-spawning, execute Atomic Execution Protocol revert (see below). Agent traces are NOT reverted.

Then mark the retry in the trace:

**If trace exists (State 2):**
```bash
python3 -c "
import json
f = '.runs/agent-traces/<name>.json'
d = json.load(open(f))
d['retry_attempted'] = True
json.dump(d, open(f, 'w'))
"
```

**If trace does NOT exist (State 1 — NO_FILE or STALE):**
```bash
RUN_ID=$(python3 -c "import json;print(json.load(open('.runs/verify-context.json')).get('run_id',''))" 2>/dev/null || echo "")
echo '{"agent":"<name>","status":"exhausted","retry_attempted":true,"original_state":"NO_FILE","checks_performed":["exhaustion-recovery"],"timestamp":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","run_id":"'"$RUN_ID"'"}' > .runs/agent-traces/<name>.json
```

Re-spawn the agent with a reduced scope prompt:
- design-critic: "Focus on the lowest-scoring page only. Skip pages that already score ≥8."
- ux-journeyer: "Focus on the primary golden path only. Skip secondary journeys."
- security-fixer: "Fix only Critical severity issues. Skip High/Medium."
- quality-fixer: "Fix only critical WCAG violations. Skip consistency and moderate/minor issues."

> quality-fixer is Tier 1 because it is edit-capable, even though its input comes from Tier 3 scanners.

**On double exhaustion** (retry also produces State 2):
1. Write a recovery trace: `{"agent":"<name>","status":"exhausted","verdict":"exhausted","recovery":true,"retry_attempted":true,"checks_performed":["exhaustion-recovery"],"timestamp":"..."}`
2. Set `hard_gate_failure: true` in the verify report frontmatter
3. Skip operational STATEs 4-5 (jump to STATE 7a, then continue to STATE 8)
4. Report to user: "Agent <name> exhausted turns twice. Hard gate failure — manual review required."

#### Tier 2 — Critical read-only agents

**Detection**: Trace State 2 after agent returns.

**Action**: Re-spawn the agent once with the same prompt.

**On double exhaustion**:
1. Write a recovery trace: `{"agent":"<name>","status":"exhausted","verdict":"incomplete","recovery":true,"checks_performed":["exhaustion-recovery"],"timestamp":"..."}`
2. Continue to next STATE — this is a WARN, not a BLOCK
3. Note in verify report: "Agent <name> exhausted turns — results incomplete."

> **Historical — soft-exit completion (#1257 superseded):** PR #1296 added
> an agent-side soft-exit primitive (provenance="self-degraded",
> partial=true, degraded_reason="budget-soft-exit") that relied on the
> agent self-counting `consumed_turns`. This was removed in #1257 final
> because the self-counting substrate replicated the #844 anti-pattern
> (commit 51d660d removed the same pattern from scaffold-images as
> unreliable). The replacement is **page-batching** (state-3b Stage 2
> Step B) — each batch agent processes ≤8 pages with the full
> `maxTurns=1000` budget, eliminating the exhaustion class entirely.
> The lead's `merge-design-consistency-checker-traces.py` aggregates per-batch
> traces into a `provenance="lead-merge"` aggregate accepted by the
> existing `aggregate_ok` predicate. This paragraph remains for context
> with prior commits (PR #1296 / #1309).
>
> **Attestation telemetry (post-#1357 hardening):** the merger appends
> raw-fields records to `.runs/consistency-soak-telemetry.jsonl` on every
> multi-batch run. Closure-check helper:
> `python3 .claude/scripts/check-1257-attestation.py` (exits 0 ATTESTED /
> 1 NOT ATTESTED). State-3b VERIFY adds a partition-cardinality assertion
> (`len(csi) >= len(partition)` when multi-batch) to catch partial-spawn
> drift the existing `siblings >= csi` check cannot detect. See
> `step55-evidence-rollout.md ## #1257 Attestation Telemetry`.

#### Tier 3 — Non-critical agents

**Detection**: Trace State 2 after agent returns.

**Action**: No retry. Write a recovery trace immediately:
```bash
echo '{"agent":"<name>","status":"exhausted","verdict":"incomplete","recovery":true,"checks_performed":["exhaustion-recovery"],"timestamp":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' > .runs/agent-traces/<name>.json
```

Continue to next STATE. Note in verify report: "Agent <name> exhausted turns — skipped."

### Trace Integrity

Agent traces MUST be produced by actual Agent tool invocations. Writing trace
files directly (via Bash, Write, or any other mechanism) without spawning the
corresponding agent is a critical integrity violation.

**Mechanical enforcement**: `state-completion-gate.sh` cross-references every
trace file against `.runs/agent-spawn-log.jsonl` (written by `skill-agent-gate.sh`
on each Agent tool call). Traces without matching spawn records cause state
advancement to be blocked.

- Do NOT write to `.runs/agent-traces/` without spawning the agent
- Do NOT write to `.runs/agent-spawn-log.jsonl` — it is hook-managed
- For legitimate recovery traces (agent crashed), use:
  `bash .claude/scripts/write-recovery-trace.sh <agent-name> [skill]`

### Atomic Execution Protocol

Before each edit-capable agent spawn, snapshot the working tree:

```bash
git diff --name-only > /tmp/pre-agent-snapshot.txt
```

After an agent returns with Trace State 2 (exhausted), revert **source** changes only — preserve `.claude/` artifacts:

```bash
git diff --name-only > /tmp/post-agent-snapshot.txt
AGENT_CHANGED=$(comm -13 <(sort /tmp/pre-agent-snapshot.txt) <(sort /tmp/post-agent-snapshot.txt))
for f in $AGENT_CHANGED; do
  case "$f" in
    .claude/*) ;;  # Keep traces and artifacts
    *) git checkout -- "$f" 2>/dev/null || rm -f "$f" ;;
  esac
done
```

For per-page design-critic: only revert the **exhausted page's** files. Keep completed pages' changes.

If the agent completes normally (Trace State 3 with verdict), do NOT revert — its changes are accepted.

---

## Build & Lint Loop

See [state-1-build-lint-loop.md](verify/state-1-build-lint-loop.md) for full procedure.

## Auto-Observe

Observation is now handled in the post-finalize epilogue via
[observation-phase.md](observation-phase.md) for all skills.

## Write Verification Report

See [state-7a-write-report.md](verify/state-7a-write-report.md) and [state-7b-compute-qscore.md](verify/state-7b-compute-qscore.md) for full procedure.

## Save Notable Patterns

See [state-8-save-patterns.md](verify/state-8-save-patterns.md) for full procedure.
