# STATE 2: PHASE1_PARALLEL

**PRECONDITIONS:** STATE 1 complete (build passes, build-result.json exists).

> **Write Conflict Prevention**: Edit-capable agents (design-critic, ux-journeyer, quality-fixer, security-fixer)
> MUST run serially in Phase 2. Read-only agents run in parallel here.

**ACTIONS:**

> **Shared algorithms:** Before executing this state, ensure you have read the following sections in [verify.md](../verify.md): Dev Server Preamble, File Boundary for Edit-Capable Agents, Agent Efficiency Directives. These apply to all agent spawns in this state and STATE 3.

### Spawn Phase 1 agents

> **CRITICAL — Template enforcement (read BEFORE spawning):** Read
> `.claude/agent-prompt-footer.md` and append its full content to every
> agent spawn prompt below. The `skill-agent-gate.sh` hook checks for the
> directive marker `<!-- DIRECTIVES:batch_search,pr_changed_first,context_digest,pre_existing -->`
> at the top of the prompt and BLOCKS spawns that lack it. The spawn-prompt
> examples in this state are minimal — you MUST add the footer block to each
> one before invoking the Agent tool. See the `build-info-collector` example
> below for the inlined-footer reference.

> **EXPLICIT FOREGROUND INSTRUCTION (#1247):** Phase 1 spawning is **two-step
> sequential** because `skill-agent-gate.sh` requires `build-info-collector.json`
> to exist on disk before any of the dependent Phase 1 agents
> (security-defender, security-attacker, behavior-verifier, performance-reporter,
> accessibility-scanner, spec-reviewer) can spawn. Following the prior
> "all in one message" instruction produced 6 hook denials per /verify run.
>
> **Step A:** Spawn `build-info-collector` FIRST as a single foreground Agent
> tool call. Wait for it to return.
>
> **Step B:** Verify the trace exists before dispatching the parallel batch:
> ```bash
> test -f .runs/agent-traces/build-info-collector.json || \
>   echo "ERROR: build-info-collector trace missing — invoke verify.md Trace State Detection / recovery before continuing"
> ```
> If the trace is absent, follow the [Trace State Detection](../verify.md#trace-state-detection)
> and [Recovery Traces](../verify.md#recovery-traces) protocol before Step C.
>
> **Step C:** Spawn the remaining Phase 1 agents as parallel foreground Agent
> tool calls in a **SINGLE message** (security-defender, security-attacker,
> behavior-verifier, performance-reporter, accessibility-scanner, spec-reviewer
> — gated by the scope table in [verify.md](../verify.md)). Do NOT use
> `run_in_background: true`. The platform blocks you until ALL return.

#### build-info-collector (Step A — spawn alone, wait for trace)

Spawn the `build-info-collector` agent (`subagent_type: build-info-collector`).

**Inlined-footer example** (copy-paste reference for the directive marker
that every spawn prompt MUST carry):

```
<!-- DIRECTIVES:batch_search,pr_changed_first,context_digest,pre_existing -->

[Your spawn-prompt body here. For build-info-collector specifically:]
If build/lint errors were fixed above, pass: "Build errors were fixed
in this verification run. Collect the diff and summaries."
If no errors were fixed, pass: "No build errors were fixed."

[Append the rest of .claude/agent-prompt-footer.md content below the body.]
```

If build/lint errors were fixed above, pass: "Build errors were fixed
in this verification run. Collect the diff and summaries."

If no errors were fixed, pass: "No build errors were fixed."

#### Step C agents (spawn the following six in a SINGLE message after Step B verifies the trace)

#### security-defender (if scope is `full` or `security`)

Spawn the `security-defender` agent (`subagent_type: security-defender`). No additional context needed.

#### security-attacker (if scope is `full` or `security`)

Spawn the `security-attacker` agent (`subagent_type: security-attacker`). No additional context needed.

#### behavior-verifier (if scope is `full` or `security`)

Spawn the `behavior-verifier` agent (`subagent_type: behavior-verifier`). No additional context needed.

#### performance-reporter (if scope is `full` or `visual`, AND archetype is `web-app`)

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Performance + a11y agents".
>
> [perf-a11y] web-app: performance-reporter, accessibility-scanner | service: skip | cli: skip

Spawn the `performance-reporter` agent (`subagent_type: performance-reporter`). No additional context needed.

#### accessibility-scanner (if scope is `full` or `visual`, AND archetype is `web-app`)

Spawn the `accessibility-scanner` agent (`subagent_type: accessibility-scanner`). No additional context needed.

#### spec-reviewer (if scope is `full` or `security`)

Spawn the `spec-reviewer` agent (`subagent_type: spec-reviewer`). Pass: "Read `.claude/agents/spec-reviewer.md` and execute all checks. Read `experiment/experiment.yaml` and `.runs/current-plan.md` (if it exists) as input. Return the output contract table and verdict."

### After Phase 1 agents return

After each agent returns, use [Trace State Detection](../verify.md#trace-state-detection) to check each spawned agent's trace individually. Use [Recovery Traces](../verify.md#recovery-traces) for agents that returned output but crashed before writing their trace. Use [Exhaustion Protocol](../verify.md#exhaustion-protocol) for agents in Trace State 2.

> **Template enforcement reminder (also stated above the spawn list):** Every Agent
> spawn prompt MUST carry the directive marker block from `.claude/agent-prompt-footer.md`.
> The skill-agent-gate hook BLOCKS spawns whose prompts lack the marker.

### Invoke review-verdict-gate (after each reviewer trace lands)

Per `.claude/patterns/review-verdict-gate.md`, the lead must run the
shared `review_method → verdict` enforcement gate against every reviewer
agent trace that may carry `review_method` fields. The gate is
idempotent and writes a `review_method_gate_evaluated: true` sentinel
that downstream VERIFY commands assert.

For each Phase 1 reviewer trace (when its agent was spawned per scope),
invoke the gate:

```bash
# behavior-verifier (when scope ∈ {full, security})
if [ -f .runs/agent-traces/behavior-verifier.json ]; then
  python3 .claude/scripts/run-review-verdict-gate.py .runs/agent-traces/behavior-verifier.json behavior-verifier
fi
# accessibility-scanner (when scope ∈ {full, visual} AND archetype=web-app)
if [ -f .runs/agent-traces/accessibility-scanner.json ]; then
  python3 .claude/scripts/run-review-verdict-gate.py .runs/agent-traces/accessibility-scanner.json accessibility-scanner
fi
```

`run-review-verdict-gate.py` is the executable extraction of
`review-verdict-gate.md`'s `enforce_review_verdict` function.
Idempotency means re-invocation on a trace that already has the
sentinel is a no-op — safe to run unconditionally.

design-critic does NOT use this gate at this state — its existing
`source-only/unknown → unresolved` invariant is enforced in state-3b's
merge code (unchanged).

**POSTCONDITIONS:** All scope-required Phase 1 traces exist in `.runs/agent-traces/`.
Each reviewer trace (behavior-verifier, accessibility-scanner) that exists
carries `review_method_gate_evaluated: true` proving the gate ran.

**VERIFY:**
```bash
python3 -c "import json,os; ctx=json.load(open('.runs/verify-context.json')); scope=ctx.get('scope',''); arch=ctx.get('archetype',''); req=['build-info-collector']; req.extend(['security-defender','security-attacker','behavior-verifier','spec-reviewer'] if scope in ('full','security') else []); req.extend(['performance-reporter','accessibility-scanner'] if scope in ('full','visual') and arch=='web-app' else []); missing=[a for a in req if not os.path.exists('.runs/agent-traces/'+a+'.json')]; assert not missing, 'missing Phase 1 agent traces: %s (scope=%s, archetype=%s)' % (missing,scope,arch); needs_bv=scope in ('full','security'); needs_a11y=scope in ('full','visual') and arch=='web-app'; assert (not needs_bv) or json.load(open('.runs/agent-traces/behavior-verifier.json')).get('review_method_gate_evaluated') is True, 'review-verdict-gate did not run on behavior-verifier trace (review_method_gate_evaluated sentinel missing)'; assert (not needs_a11y) or json.load(open('.runs/agent-traces/accessibility-scanner.json')).get('review_method_gate_evaluated') is True, 'review-verdict-gate did not run on accessibility-scanner trace (review_method_gate_evaluated sentinel missing)'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 2
```

**NEXT:** Read [state-2a-page-image-map.md](state-2a-page-image-map.md) to continue.
