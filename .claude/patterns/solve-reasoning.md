# Solve Reasoning

First-principles methodology for finding optimal solutions. Two modes: light
(inline, ~30s) and full (agent-assisted, ~3 min). Callable by commands (`/solve`)
and other patterns (`/change` Phase 1, `/resolve` Step 5).

---

## Light Mode

Execute directly in the lead agent. No subagents.

### Step 1: Problem Decomposition

Answer three questions:
1. **What** — State the problem in one sentence. No jargon.
2. **Why** — What breaks, degrades, or is blocked if this isn't solved?
3. **Constraints** — What is fixed and cannot change? (time, API surface, backwards compatibility, user expectations, etc.)

### Step 2: Constraint Enumeration

List:
- **Executor**: Who/what performs the solution? (human, CI, runtime, agent, etc.)
- **Available mechanisms**: What tools, APIs, patterns, or abstractions can the executor use? Rank by strength (strongest = most direct, fewest failure modes).
- **Hard constraints**: From Step 1.3 — things that cannot change.
- **Soft constraints**: Preferences that can be traded off if necessary.

### Step 3: Solution Design

For each sub-problem identified in Step 1:
1. Pick the **strongest available mechanism** from Step 2
2. Explain why it's strongest (fewest failure modes, most direct path)
3. If the strongest mechanism has a dealbreaker constraint, fall back to the next strongest

Output: a single recommended solution as an ordered implementation checklist.

### Step 4: Self-Check

For each mechanism chosen in Step 3, ask:
- "Is there a stronger mechanism I dismissed too early?"
- "Does this mechanism introduce a new failure mode I haven't accounted for?"
- "Would a different decomposition in Step 1 unlock a stronger approach?"

If any answer is yes: revise Steps 1-3 for that sub-problem. One revision pass max.

If `problem_type = "defect"`:
4. "Does this solution address the root cause, or just the symptom?"
   If treating a symptom (suppressing errors, adding workarounds, handling edge cases
   without addressing why they exist): revise Step 3.
5. "Could this same class of problem recur? If yes, what prevents it?"
   Identify a concrete prevention mechanism (test, guard, validator, type constraint)
   or explain why prevention is not feasible.
6. "Are there other instances of this same problem beyond the reported one?"
   The solution must cover all known instances, not just the trigger case.
7. **Falsification**: "What observable signal does H predict that ¬H would NOT
   predict? Cite the actual observation supporting H over ¬H."
   The prediction and the ¬H prediction must be *structurally distinct*, not
   just "X" vs "not X". If no observable signal can be specified that
   distinguishes H from any other hypothesis, mark `strength = "untestable"`
   and downgrade H from "root cause" to "workaround" in Step 5's output.
   Emit the `falsification` block (see Falsification Schema below).

If any answer reveals a gap: revise Step 3. Same one-revision-pass-max rule.

### Step 5: Output

```
## Recommended Solution
[1-2 sentence summary]

### Implementation Steps
1. [step]
2. [step]
...

### Constraints Respected
- [constraint]: [how the solution respects it]

### Key Tradeoff
[the most significant tradeoff made, and why it's acceptable]

### Prevention Analysis (when problem_type = defect)
- **Root cause addressed**: [yes/no — explain]
- **Recurrence risk**: [none | guarded | unguarded (<why acceptable>)]
- **Recurrence guard**: when risk != none, emit one of:
  - light-mode bullet — `- kind=<test|lint|hook|invariant> | artifact=<path|null> | rationale=<≤200ch>`
  - full-mode JSON (required when kind=none) — see Full Mode "Recurrence guard" block
- **Scope**: [all instances covered | N known instances, all addressed]
- **Falsification**: emit the typed `falsification` block — see Falsification
  Schema below. Required regardless of `recurrence_guard.kind` (including
  `kind=none`). Signals that ¬H would predict instead of H — the lead must
  cite the observation that distinguishes the two.
```

---

## Full Mode

Uses 4 Opus subagents across 6 phases.

### Phase 1 — Parallel Research (3 agents)

Launch 3 agents concurrently:

**Agent 1 — Problem Space** (Explore subagent)
> Investigate the problem: what needs solving, for whom, and why.
> Search the codebase for related code, docs, and prior decisions.
> Output: problem statement, affected users/systems, severity, and scope.

**Agent 2 — Actionable Prior Art** (Explore subagent)
> Search the codebase for patterns, utilities, and infrastructure that partially
> solve this problem. For each finding: what it does + what gap remains.
>
> Search targets: demo modes, test fixtures, mocks, fallbacks, guards, gates,
> env vars, scripts, similar patterns in other files, related config, and the
> optional `## Stack Knowledge` sections across every path returned by
> `scripts/lib/stack_knowledge_parser.iter_stack_knowledge_files()` — currently
> `.claude/stacks/**/*.md` plus `.claude/scripts/lib/README.md` (the README is
> the canonical surface for reusable lib helpers like phash,
> schema_version_gate, and validator-meta-test). Treat the helper as the
> single source of truth — never hardcode the glob list locally. For each
> entry whose `composite_identity` matches the problem's derived composite
> (see `scripts/lib/stack_knowledge_parser.py`), surface its `fix_template`
> as prior art tagged with the entry's `id`, `maturity`, and
> `occurrence_count`. Missing sections are expected (HC3) — absence is not
> a finding, just skip.
>
> When invoked from /change STATE 2, the precomputed hints artifact
> `.runs/change-stack-knowledge-hints.json` lists pre-filtered stable +
> canonical entries (already filtered for `graduated_to is None`). Treat
> `maturity=canonical` as a hard constraint (must avoid); `maturity=stable`
> as strong guidance. When the artifact is absent, fall back to parsing
> stack files directly.
>
> Output: list of findings, each with: file path, what it does, gap remaining.

#### Phase 1a — Prior-Failure Dossier (RMG v2; runs only when `problem_type=defect`)

After Agent 2 returns and BEFORE the lead synthesizes Phase 2, the lead builds
a Prior-Failure Dossier. This is the **Recall** layer of RMG v2 — every defect
run reads what prior fix attempts looked like on the same files / symptoms so
the new design cannot accidentally repeat a failed approach.

Inputs (derive from caller's context):
- `divergence_files`: file set under repair (resolve: extract the file part
  from each `reproductions[*].divergence_point` — schema is the string
  `<file>:<line>` per state-3-reproduce.md; change/solve: affected files in
  scope).
- `symptom_signature`: canonicalized form of `reproductions[*].actual` (resolve)
  or `$ARGUMENTS` summary (solve/change). Canonicalization is performed by
  `.claude/scripts/lib/symptom_canonicalizer.py`.

Mechanism: invoke `dossier_builder.build_dossier(divergence_files,
symptom_signature, project_dir)` from
`.claude/scripts/lib/dossier_builder.py`. The builder reads
`.runs/fix-ledger.jsonl`, `.runs/recurrence-candidates.jsonl` (Phase B
artifact), and `git log -- <files>` and returns a two-phase dossier.

**Phase 1a — designer-visible reveal (anchoring resistance)**: only the
following fields are surfaced to the designer for Phase 4 initial design:

```
{
  "prior_run_id": str,
  "files_touched": [str, ...],
  "regression_test_present": bool,
  "occurrence_count_60d": int
}
```

`failure_mode` and `what_was_missed` are **withheld** during Phase 4. The
designer must independently diagnose the problem; the dossier just flags
that this area has prior incidents and how many.

**Phase 4b — full reveal (cross-check, RMG v2 R2-A2)**: see Phase 4b below.

When the dossier is empty, Phase 1a is a no-op. When `problem_type` is not
`defect`, the dossier is not built at all.

**Agent 3 — Hard Constraints** (Explore subagent)
> Identify immutable boundaries: API contracts, backwards compatibility
> requirements, performance budgets, security requirements, deployment
> constraints, dependencies that cannot be changed.
>
> Only list truly immutable constraints. Preferences and soft constraints
> are NOT hard constraints. Failure modes are NOT constraints (those go
> to the critic in Phase 5).
>
> Output: numbered list of hard constraints with evidence (file path, doc, or API spec).

Wait for all 3 agents to complete before proceeding.

### Phase 2 — Constraint Enumeration (lead)

Synthesize research from Phase 1 into a structured constraint space:

1. **Executor type**: Who/what performs the solution?
2. **Available mechanisms**: Tools, APIs, patterns, abstractions the executor can use. Rank each by strength (strongest = most direct, fewest failure modes). Include mechanisms discovered by Agent 2.
3. **Hard constraints**: From Agent 3. Numbered, with evidence source.
4. **Prior art**: From Agent 2. What exists, what gap remains for each.
5. **Problem scope**: From Agent 1. Boundaries of what needs solving.

### Phase 3 — Gap Resolution (autonomous)

After research, before synthesis. The lead agent identifies and self-answers
research gaps using first-principles reasoning from Phase 1 data:

1. Generate 3-5 specific questions from gaps in Phase 1 research
   (e.g., "Agent 2 found X utility but it doesn't handle Y — should we extend it or build separately?")
2. For each question, self-answer using Phase 1 evidence:
   - Review Agent 1 (problem space), Agent 2 (prior art), Agent 3 (constraints)
   - Apply first-principles reasoning: strongest mechanism, fewest failure modes
   - Tag each answer with confidence: **HIGH** (grounded in Phase 1 evidence) or **LOW** (assumption without direct evidence)
3. LOW-confidence answers are flagged for Phase 5 Critic to challenge

Incorporate self-answers into the constraint space.

### Phase 4 — Solution Design (lead)

Using the constraint space from Phase 2 and self-answered gaps from Phase 3:

1. For each sub-problem: pick the **strongest available mechanism**
2. Explain why it's strongest (fewest failure modes, most direct)
3. Mark each mechanism's strength level: **strong** (direct, few failure modes), **moderate** (indirect or some failure modes), **weak** (workaround, many failure modes)
4. If two mechanisms are close in strength: note both as Pareto alternatives

5. **Prevention check** (when `problem_type = "defect"`):
   - **Root cause**: For each mechanism — does it address root cause, or just the symptom?
   - **Recurrence**: Could this class of problem recur? If yes: identify prevention
     mechanism (test, guard, validator, type constraint) or explain why not feasible.
   - **Scope**: Are there other instances beyond the reported one? Solution must
     cover all known instances.
   - Output: `prevention_analysis` — root_cause_addressed (bool),
     recurrence_risk (none|guarded|unguarded), recurrence_guard (typed object — see
     **Recurrence-Guard Schema** below), scope (all_covered bool, instance_count int),
     falsification (typed object — see **Falsification Schema** below; required for
     all defect runs regardless of recurrence_guard.kind).

   #### Recurrence-Guard Schema (RMG v2 — required when `recurrence_risk != "none"`)

   `recurrence_guard` is a typed object parsed by
   `.claude/scripts/lib/recurrence_guard_parser.py`. Both shapes below are
   accepted; the parser canonicalizes to the dict form.

   **Full-mode shape (dict, preferred):**

   ```json
   {
     "kind": "test | lint | hook | invariant | none",
     "artifact": "<path-or-rule-id-or-null>",
     "rationale": "<≤200 chars; what this guard catches>",
     "unguardability_rationale": "<required when kind=none; ≥80 chars>"
   }
   ```

   - `kind=test|lint|hook|invariant`: `artifact` MUST point to an existing file
     path or a rule id; the lifecycle-finalize Step 4.6 gate enforces presence
     in the PR diff.
   - `kind=none`: `artifact` is null and `unguardability_rationale` MUST answer
     **(a)** why no executable check expresses the invariant, AND **(b)** which
     observation/human-review/monitoring process catches the next instance.
     Prefer `kind=lint` (pointing at a markdown coherence-rule) over `kind=none`
     for prose-only fixes.

   **Light-mode shape (single bullet — only when `kind != none`):**

   ```
   - kind=<token> | artifact=<path|null> | rationale=<≤200ch>
   ```

   The bullet grammar is enforced by the parser. Pipes (`|`) are not allowed
   inside rationale; switch to dict shape if needed. `kind=none` always
   requires the dict shape.

   Post-cutover: legacy free-text strings are rejected at parse time by
   default. The escape hatch `RMG_V2_TOLERANT=1` is preserved for
   emergencies — when set, the parser returns `kind="legacy_freetext"`
   and the lifecycle-finalize gate logs a warning instead of blocking.
   Default off: no in-tree writer emits free-text post-Phase-A.

   #### Falsification Schema (Falsification Gate — required when `problem_type = "defect"`)

   `falsification` is a typed object parsed by
   `.claude/scripts/lib/recurrence_guard_parser.parse_falsification`.
   Required for every defect run regardless of `recurrence_guard.kind`
   (including `kind="none"` prose-only fixes — the textual block forces
   a falsifiable claim even when no executable guard is possible).

   **Schema (dict, only shape accepted):**

   ```json
   {
     "prediction":          "<≥40 chars: signal H predicts to observe>",
     "opposite_prediction": "<≥40 chars: signal ¬H would predict instead>",
     "observable_signal":   "<≥40 chars: actual observation cited from evidence>",
     "strength":            "high | low | untestable"
   }
   ```

   - **`prediction`**: the observable signal H predicts. Must be specific to
     the root-cause hypothesis — generic predictions like "the fix works" or
     "the symptom disappears" fail the gate because they are derivable from
     "any fix works", not from H specifically.
   - **`opposite_prediction`**: the signal ¬H would predict instead. Must be
     *structurally distinct* from `prediction`, not just its negation. The
     parser rejects token-Jaccard ≥ 0.8 between the two (tautological
     framing). The point is to force the designer to name a different world.
   - **`observable_signal`**: the actual observation cited from the
     reproduction artifact, code trace, or existing evidence — what we
     measured that matches H over ¬H.
   - **`strength`**:
     - `high` — observable signal directly supports H over ¬H
     - `low`  — signal is consistent with H but does not exclude ¬H
     - `untestable` — no observable signal distinguishes H from ¬H; downgrade
       H from "root cause" to "workaround" in the output

   Enforcement: STATE 5 VERIFY runs `verify-recurrence-guard.py
   --require-falsification`. The flag honors `FALSIFICATION_SOAK=1` to warn
   instead of fail during the soak window. solve-critic vector 7
   (`falsification-weak`) challenges weak / circular blocks in Phase 5.

Output:
- **1 recommended solution** with ordered implementation checklist
- **0-2 Pareto alternatives** (only if genuinely competitive on different tradeoff axes — e.g., one is simpler but less extensible)

For each alternative: name the tradeoff axis where it wins.

### Phase 4b — Prior-Failure Reveal & Response (RMG v2; runs only when Phase 1a dossier is non-empty)

After the initial design from Phase 4 is emitted, the lead reveals the
remaining dossier fields (`failure_mode`, `what_was_missed`,
`prior_commit_sha`) — i.e., the prose that was withheld from Phase 4 to
prevent diagnostic anchoring (R2-A2).

The designer then MUST emit a `prior_failure_response` array, one entry per
Phase 1a dossier entry:

```json
"prior_failure_response": [
  {
    "prior_run_id": "<from dossier>",
    "failure_mode": "<from Phase 4b reveal>",
    "how_addressed": "<≤300 chars: how the new design addresses this prior failure mode>",
    "concrete_delta_step_or_guard": "<implementation step number OR guard artifact path that did NOT appear in the prior fix's commit>"
  }
]
```

**`concrete_delta_step_or_guard` is required.** It must reference either:
- A step number from the Phase 4 implementation checklist that introduces
  something new the prior commit did not contain, OR
- A `recurrence_guard.artifact` path that did not exist in the prior fix.

This makes "we addressed it by being more careful" non-passing — the
designer must point at a concrete artifact or step that demonstrably
diverges from the prior attempt. solve-critic Phase 5 verifies this in
Phase D (Layer 2).

If the dossier is empty, Phase 4b is a no-op.

#### Prior-Failure Consultation (OARC #1468/#1456 — semantic-match escalation)

Phase 1a entries where the dossier set
`designer_consultation_attestation_required: true` (semantic-match
heuristic: ≥2 content-token overlap between the canonicalized symptom
and the prior commit's subject/failure_mode AND ≥1 file overlap)
require an explicit consultation attestation in addition to (or in
place of) `prior_failure_response`. The designer MUST emit:

```json
"prior_failure_consultation": [
  {
    "prior_run_id": "<from dossier; e.g., git:abc1234 OR a ledger run_id>",
    "consulted_via": "git_show | read_pr | skipped",
    "skip_justification": "<≥40 chars; required when consulted_via=skipped>"
  }
]
```

`verify-recurrence-guard.py --require-dossier` enforces this gate.
Default during soak: warn-only (prints `VERIFY WARN: OARC ...` to
stderr, returns 0 — does not block PR merge). Phase C cutover: set
`CONSULTATION_DENY=1` to promote to hard block. See
`.claude/patterns/gecr-cutover-criteria.json` for cutover timeline.

Rationale: in template repos with empty fix-ledger the dossier
otherwise degrades to git-sentinel "advisory only" (caef8ab/#1437),
re-introducing the RMG v1 leak that R2-A2 was designed to close.
The semantic-match annotation surfaces high-signal prior commits as
REQUIRED consultation, restoring R2-A2's strength in the empty-ledger
case.

### Phase 5 — Critic Loop (1 Named agent, max 2 rounds)

Spawn the `solve-critic` Named agent (`subagent_type: solve-critic`).

The caller MUST include `--context <file>` in the agent prompt to specify the
context file for run_id correlation:
- `/resolve`: `--context .runs/resolve-context.json`
- `/change`: `--context .runs/change-context.json`
- `/solve`: `--context .runs/solve-context.json`

**Critic receives**: the recommended solution + problem statement + constraint
space + Phase 3 self-answered gaps. When `problem_type=defect`, the critic
also receives the Phase 1a + Phase 4b Prior-Failure Dossier and the
designer-emitted `prior_failure_response[]`. On round 2, the critic also
receives the round-1 concerns array (with stable `concern_id`) so the
`within-run-round1-concern-unaddressed` vector can verify each round-1
concern is addressed by a cited step.

**Critic does NOT receive**: the reasoning chain from Phases 1-4.

The critic protocol (TYPE A/B/C classification, output format) is defined in
`.claude/agents/solve-critic.md`. The agent writes its own trace to
`.runs/agent-traces/solve-critic.json` — this trace is independent of the lead
agent and cannot be modified by it.

**Convergence rules**:
- **Round 1**: If 0 TYPE A concerns → early exit (solution converged). Otherwise: fix all TYPE A concerns → round 2.
- **Round 2**: Before spawning round 2, **archive the round-1 trace** to the sidecar location `.runs/solve-critic-round1.json` via the canonical writer (the path is registered in `.claude/patterns/gate-readable-artifacts-canonical.json` and is intentionally outside `.runs/agent-traces/` so the trace-write-guard does not block it):

  ```bash
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/solve-critic-round1.json \
    --payload "$(cat .runs/agent-traces/solve-critic.json)" \
    --skill <active-skill>
  ```

  Then spawn a **new** solve-critic agent (use the Agent tool, NOT SendMessage to the round 1 agent). The round-2 spawn prompt MUST include `round_1_concerns` (the full `concerns[]` array from the archived round-1 trace, with stable `concern_id` values) under a `## Round 1 Concerns to Cross-Check` header — see `.claude/agents/solve-critic.md` "Round 2 Prompt Contract". Wait for the agent to return its result. The agent overwrites the live trace at `.runs/agent-traces/solve-critic.json` with `round: 2` and updated counts; the round-1 archive at `.runs/solve-critic-round1.json` remains as the audit-trail source for vector 5 (`within-run-round1-concern-unaddressed`). Any remaining TYPE A → package as caveats in output. Stop.

  **Post-completion handling (#1456 OARC sparse-trace fix):** when the caller's `*-context.json` is `completed:true` (round-2 re-spawn from a finished skill, e.g., `/observe` against a completed `/resolve`, OR a /solve --defect run where round 1 already advanced the caller's state), `resolve_active_identity` returns empty and `write-agent-trace.sh`'s default `self` provenance branch exits 1 (see `.claude/scripts/write-agent-trace.sh`: search for `"no active skill context on current branch"`). The agent's Trace Output Bash heredoc already detects this via `$CONTEXT_FILE.completed` and passes `--provenance lead-orchestrated --source-run-id <id> --source-skill <skill>`. The caller (orchestrator) must:

    1. Determine whether the active context is `completed:true` BEFORE spawning round 2.
    2. If yes, export `SOURCE_RUN_ID` and `SOURCE_SKILL` env vars from the context BEFORE the Agent tool invocation so `skill-agent-gate.sh` stamps the spawn-log under the source identity (the 3-gate validation from #1275 / `a0e568d` requires this).
    3. The spawn prompt SHOULD also include `is_post_completion: true` so the agent has explicit signal in addition to the env vars.

  Without this, the agent's write attempt fails silently → the init-trace.py 4-key stub survives → sparse-trace candidate emitted by GECR `sparse-trace-pairing` rule. With this, the agent writes a full lead-orchestrated trace and the gate accepts via `pass_lead_orchestrated`.

**IMPORTANT**: Each critic round MUST complete (agent returns result) before the caller proceeds to Phase 6 or advances to the next state.

**Artifact tracking:** After the critic loop completes, the caller must record:
- `critic_rounds`: number of rounds actually executed (1 or 2)
- `round_1_type_a_count`: number of TYPE A concerns from round 1
- `round_2_type_a_count`: number of TYPE A concerns from round 2 (always emit; 0 when `critic_rounds <= 1`) — registry contract: `state-registry.json` `challenge_fields.when_rounds_gt_1` requires presence when round 2 ran; emit-always-0 keeps prose consistent across resolve/change/solve callers

These fields enable postcondition verification that round 2 was executed when required
and cross-artifact consistency checks between the challenge file and the critic trace.
Store in the caller's challenge artifact:
- `/resolve`: `.runs/resolve-challenge.json`
- `/change`: `.runs/change-challenge.json`
- `/solve`: `.runs/solve-challenge.json`

Do NOT store in the shared `solve-trace.json`.
The adversarial-merge-gate.sh hook cross-references these fields against the
solve-critic trace to detect silent overrides.

### Phase 6 — Output

Present the final output:

```
## Recommended Solution
[converged solution — 2-3 sentence summary]

### Implementation Checklist
1. [step]
2. [step]
...

## Self-Answered Research Gaps
[Phase 3 gap resolution — question, self-answer, confidence level for each]

## Constraint Space
[enumeration from Phase 2 — executor, mechanisms, hard constraints]

## Alternatives
[Pareto alternatives from Phase 4, if any. For each: summary + tradeoff axis where it wins]
[If none: "No Pareto alternatives — recommended solution dominates on all axes."]

## Remaining Risks
- **TYPE B** (system constraints): [list, or "None"]
- **TYPE C** (open questions): [list, or "None"]
- **Caveats**: [unresolved TYPE A from round 2, if any, or "None"]

## Prior-Failure Response (when Phase 1a dossier is non-empty)
- One entry per dossier row. Each entry MUST cite a concrete delta step or
  guard artifact absent from the prior commit (Phase 4b contract).

## Prevention Analysis (when problem_type = defect)
- **Root cause addressed**: [yes/no — explain how the solution targets the cause]
- **Recurrence risk**: [none | guarded | unguarded]
- **Recurrence guard**: [typed object per RMG v2 schema — full-mode JSON block
  below, OR a single light-mode bullet `- kind=<token> | artifact=<path|null> |
  rationale=<≤200ch>` when kind != none]
- **Scope**: [N instances identified, all covered | single instance, no others found]
- **Falsification**: [typed object — required regardless of recurrence_guard.kind.
  JSON block below.]

### Recurrence guard (full-mode JSON; emit when kind=none or for clarity)

```json
{
  "kind": "test | lint | hook | invariant | none",
  "artifact": "<path-or-rule-id-or-null>",
  "rationale": "<≤200 chars>",
  "unguardability_rationale": "<required when kind=none; ≥80 chars covering (a) why no executable check expresses the invariant, (b) which review/observability/monitoring process catches the next instance>"
}
```

### Falsification (full-mode JSON; required when problem_type = defect)

```json
{
  "prediction": "<≥40 chars: signal H predicts to observe — specific to the root-cause hypothesis>",
  "opposite_prediction": "<≥40 chars: signal ¬H would predict instead — structurally distinct from prediction (token-Jaccard < 0.8)>",
  "observable_signal": "<≥40 chars: actual observation cited from reproduction artifact / code trace / evidence>",
  "strength": "high | low | untestable"
}
```

## Critic Convergence
- Rounds completed: [1 or 2]
- Round 1 TYPE A count: [N]
- Round 2 needed: [yes/no]
```

---

## Caller Integration

Other patterns can invoke this methodology with **adaptive depth** — light by
default, full when complexity warrants it.

### `/resolve` Step 5

- **Default**: light
- **Trigger full**: `blast_radius` confirmed >= 3 files OR `severity` = HIGH
- **Input mapping**: `divergence_point`, `blast_radius`, `reproduction`, `severity` as constraints
- **Light output mapping**: "Recommended Solution" -> `root_cause`, "Implementation Steps" -> `fix_plan`, "Constraints Respected" -> constraint review, "Key Tradeoff" -> diagnosis report, "Prevention Analysis" -> `prevention_analysis` in solve-trace.json
- **Full mode customization**:
  - Phase 1 agents: Agent 1 = divergence investigation, Agent 2 = blast radius + prior fix art, Agent 3 = fix constraints (validators, archetype universality)
  - Phase 5 Critic receives domain-specific vectors from Step 5b (configuration counterexample, blast radius gap, regression vector)
- **Prevention**: Core pattern handles root-cause, regression-prevention, and scope coverage via `problem_type = "defect"` (resolve always sets this). Post-validation retains only the domain-specific template universality requirement.
- **Post-validation**: resolve.md Step 5 applies template universality after solve-reasoning completes. If rejected: iterate once through self-check (light) or critic round 2 (full).

### `/change` Step 2b

- **Default**: light
- **Trigger full**: `preliminary_type` in [Feature, Upgrade] AND `affected_areas` >= 3
- **Input mapping**: `$ARGUMENTS` as problem, exploration results from Step 2 as constraints
- **Light output**: stored in working memory, feeds into plan "How" sections
- **Full mode customization**:
  - Phase 1 agents: Agent 1 = change problem space, Agent 2 = reuse/prior art (extends plan-exploration), Agent 3 = hard constraints (archetype, stack, behaviors)
  - Phase 5 Critic reviews plan mechanism choices (no extra domain vectors)
  - Output feeds: "How" sections, Risks & Mitigations, Approaches table
- **Prevention**: When `preliminary_type = "Fix"`, callers set `problem_type = "defect"` to activate prevention dimension. Other types do not set problem_type.

### Direct `/solve` invocation

- **Default**: full
- **Override**: `--light` flag selects light mode
- **Prevention**: Callers may set `problem_type = "defect"` via `--defect` or `--bug` flag to activate prevention. Default: not set (no prevention check).

### Caller conventions

- **Output ownership**: return output to the caller — do not present directly to the user (the caller handles presentation and next steps)
- **Phase 3 autonomy**: Phase 3 is fully autonomous — the lead agent self-answers research gaps using first-principles reasoning. No user interaction occurs in Phase 3. Callers do not need to merge Phase 3 questions into STOP gates
- **Domain-specific critics**: callers may inject additional critic vectors into Phase 5 (see `/resolve` Step 5b vectors)
- **Post-validation iteration**: callers may apply their own domain validation after solve-reasoning completes and iterate once if rejected
- **Prevention activation**: Callers set `problem_type = "defect"` to activate prevention questions. When not set, prevention dimension is skipped entirely. The pattern treats this as a pure input — it never infers problem_type on its own.
- **RMG v2 dossier activation**: When `problem_type = "defect"` is set, the
  Phase 1a dossier and Phase 4b reveal run **for all three callers** uniformly
  (R2-A6). Callers do not need bespoke wiring — solve-reasoning pulls the
  dossier from the shared artifacts (`.runs/fix-ledger.jsonl` and
  `.runs/recurrence-candidates.jsonl`). When the artifacts are empty/absent
  the dossier is empty and Phase 4b is a no-op.
- **Generic vs domain separation**: Core prevention handles root cause, recurrence, and scope coverage for all defects. Callers add domain-specific validation only (e.g., config universality, deployment constraints). Never re-implement generic prevention in a caller.
