# STATE 2a: REVIEW_SCAN

**PRECONDITIONS:**
- Baseline validators ran (STATE 1 POSTCONDITIONS met)
- `iteration`, `seen_findings`, and `yield_history` initialized

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> all archetypes: systematic archetype coverage check (every conditional must handle web-app, service, cli or document the exclusion)

Launch 3 Explore subagents in parallel, one per dimension below. Construct each
agent's prompt from:

- The **shared context instruction** (box below)
- The agent's **dimension section** (focus, examples, files to read)
- The **Finding Format**, **Check Proposal Criteria**, and **Rules** sections

> **Shared context instruction** — include verbatim in every subagent prompt:
>
> Before reviewing, read these files:
> Glob `.claude/archetypes/*.md`, `scripts/check-inventory.md`, `CLAUDE.md`, `experiment/experiment.example.yaml`, `experiment/EVENTS.yaml`.
> Read `.claude/settings.json`, `.claude/agent-prompt-footer.md`.
> Do not report anything already covered by check-inventory.md (including Pending).

**Dimension A: Cross-File Consistency**

Focus: Find contradictions or inconsistencies **between** files that no regex or structural check can catch. Examples:
- A skill file says "do X" but a stack file's code template does Y
- A rule in CLAUDE.md conflicts with how a skill actually operates
- A stack file assumes a convention that another stack file violates
- A prose instruction references a function/file/path that doesn't match reality
- A hook script grep/match pattern doesn't match the actual string in the file it references
- A hook registers in settings.json but the .sh file doesn't exist (or vice versa)
- A hook checks for an artifact name that differs from what the verify state file creates

Files to read (canonical template-source scope — see `.claude/template-owned-dirs.txt`):
- Glob `.claude/commands/*.md` — read each skill dispatcher
- Glob `.claude/skills/**/state-*.md` — read each state file (look for contradictions between a state's VERIFY and ACTIONS, between a state's CHECKPOINT and an upstream state's VERIFY, and between POSTCONDITIONS promises and ACTIONS write steps)
- Glob `.claude/skills/**/skill.yaml` — orchestration declarations (states list, branch prefix, agents)
- Glob `.claude/skills/**/orchestration.json` — orchestration descriptors
- Glob `.claude/skills/**/gates/*.sh` — skill gate scripts
- Glob `.claude/stacks/**/*.md` — read each stack file
- Glob `.claude/patterns/**/*.md` — read each pattern file
- Glob `.claude/patterns/*.json` — declarative configs (state-registry.json, agent-registry.json, coherence rules, convergence config)
- Glob `.claude/procedures/*.md` — read each procedure file
- Glob `.claude/agents/*.md` — read each agent definition
- Glob `.claude/archetypes/*.md` — archetype definitions
- Glob `.claude/templates/*.md` — canonical schemas (e.g., experiment-yaml.md)
- Glob `.claude/hooks/*.sh` — read each hook script
- Glob `.claude/scripts/*.sh` — internal lifecycle/utility scripts
- Glob `.claude/scripts/*.py` — internal validator/helper scripts
- Glob `.claude/scripts/lib/*.py` — shared internal libraries
- Glob `.claude/agent-memory/**/*.md` — agent memory scaffolds
- Read `.claude/agent-prompt-footer.md` — agent prompt footer
- Read `.claude/settings.json` — hook registry
- Glob `scripts/*.py` — top-level validators
- Glob `scripts/*.sh` — top-level shell utilities
- Glob `scripts/*.mjs` — top-level node utilities
- Glob `scripts/lib/*.py` — top-level shared libraries
- Glob `scripts/validators/*.py` — top-level validator helpers
- Read `Makefile` — entrypoint targets

After reading: for each potential finding, identify which archetype and stack
configuration triggers the contradiction. Record the config alongside the finding.

**Dimension B: Edge Case Robustness**

Focus: Find configurations where skills or stack files would produce broken output. Examples:
- A skill assumes auth exists but the experiment.yaml has no `stack.auth`
- A code template hard-codes a path that changes based on stack choices
- A conditional branch in a skill handles 2 of 3 possible states
- A skill's conditional branching handles 2 of 3 archetypes (e.g., web-app and service but not cli)
- An edge case not covered by the test fixtures
- A hook's case statement handles some agent types but has a silent fallback for new agents
- A hook uses an undeclared bash variable or has a fail-open exit code on parse errors

Files to read:
- Glob `.claude/commands/*.md` — read each skill dispatcher
- Glob `.claude/skills/**/state-*.md` — read every skill's state files (archetype branches and silent fallbacks live here, not in dispatchers)
- Glob `.claude/skills/**/gates/*.sh` — skill gate scripts (silent-pass / fail-open risk)
- Glob `.claude/stacks/**/*.md` — read each stack file
- Glob `.claude/archetypes/*.md` — archetype definitions (gate the archetype-coverage check below)
- Glob `tests/fixtures/*.yaml` — read each test fixture (note: this directory is currently absent on disk; fixture phantom is a separate template observation — leave reference unchanged here so it surfaces if/when fixtures land)
- Glob `.claude/procedures/*.md` — read each procedure file
- Glob `.claude/agents/*.md` — read each agent definition
- Glob `.claude/hooks/*.sh` — read each hook script
- Glob `.claude/scripts/*.sh` — internal lifecycle scripts (case statements, undeclared vars, fail-open exit codes)
- Glob `.claude/scripts/*.py` — internal helper scripts
- Glob `scripts/*.py` — top-level validators

After reading: for each potential finding, identify the test fixture(s) whose
`experiment.stack` configuration matches the edge case (e.g., a finding about missing
`stack.auth` -> use fixtures that lack auth). Record the fixture name(s) alongside
the finding. If no fixture covers the edge case, note "no fixture coverage" —
this itself may be a finding worth reporting.

**Systematic archetype coverage check** (after heuristic scanning):

1. List all archetypes from `.claude/archetypes/*.md`
2. For each skill that contains archetype-conditional language
   (e.g., "If archetype is", "If the archetype is", "web-app", "service", "cli"):
   a. Read the dispatcher at `.claude/commands/<skill>.md` AND every state
      file at `.claude/skills/<skill>/state-*.md` — the conditional logic
      lives in state files (the dispatcher is a thin router).
   b. Identify all archetype-specific branches across the dispatcher and states
   c. For each archetype, verify either: a dedicated branch exists, OR
      the default/fallback branch explicitly covers it
   d. If an archetype has no branch and no explicit default coverage:
      report as a finding ("skill X has no handling for archetype Y")
3. Focus on the 3 most heavily conditionalized skills first:
   bootstrap, deploy, change — i.e.,
   `.claude/commands/{bootstrap,deploy,change}.md` plus
   `.claude/skills/{bootstrap,deploy,change}/state-*.md`.
4. This check supplements (not replaces) the heuristic scan above.
   Heuristic findings about archetype gaps take priority if they overlap.

**Dimension C: User Journey Completeness**

Focus: Find dead-end states where a user gets stuck with no clear next step. Examples:
- A skill exits early but doesn't tell the user what to do next
- A build failure produces an unhelpful error message
- A workflow step assumes a previous step succeeded but doesn't verify
- A Makefile target fails silently or with an unhelpful error
- The user follows instructions but ends up in an undocumented state
- A hook blocks an operation but the error message doesn't tell the user what prerequisite is missing or how to fix it

Files to read:
- Glob `.claude/commands/*.md` — read each skill dispatcher
- Glob `.claude/skills/**/state-*.md` — read each state file (most user-facing instructions and dead-end candidates live here)
- Glob `.claude/stacks/**/*.md` — read each stack file
- Glob `.claude/patterns/**/*.md` — read each pattern file
- Glob `.claude/procedures/*.md` — read each procedure file
- Glob `.claude/agents/*.md` — read each agent definition
- Glob `.claude/archetypes/*.md` — archetype definitions
- Glob `.claude/hooks/*.sh` — read each hook script (block + helpful-error pairing)
- Glob `.claude/scripts/*.sh` — internal lifecycle scripts (silent fail or unhelpful error)
- Glob `.claude/scripts/*.py` — internal helper scripts
- Read `Makefile`

After reading: trace the user journey for each archetype:
- web-app: (`/spec`) -> `make validate` -> `/bootstrap` -> merge -> `/verify` -> `/deploy` -> `/change` -> `/verify` -> `/distribute` -> `/iterate` -> `/retro` -> `/teardown`
- service: (`/spec`) -> `make validate` -> `/bootstrap` -> merge -> `/verify` -> `/deploy` -> `/change` -> `/verify` -> `/distribute` (if surface != none) -> `/iterate` -> `/retro` -> `/teardown`
- cli: (`/spec`) -> `make validate` -> `/bootstrap` -> merge -> `/verify` -> `/deploy` (surface only) -> `npm publish` -> `/change` -> `/verify` -> `/distribute` (if surface != none) -> `/iterate` -> `/retro`

Production quality is always active: `/change` uses TDD + implementer agents, `/verify` spawns spec-reviewer.

For each finding, record the archetype and fixture(s) whose config matches the
dead-end scenario. If no fixture covers it, note "no fixture coverage."

**Finding Format**

Each subagent must use this format for findings:

```
### Finding N: <title>
- **Severity**: HIGH (breaks execution) | MEDIUM (wrong output, confusing) | LOW (cosmetic, minor inconsistency)
- **File(s)**: ...
- **Issue**: ... (be specific — quote the conflicting text)
- **Impact**: ... (what breaks or confuses the user)
- **Fix**: ... (concrete, implementable)
- **Proposed check** (only if the finding qualifies — see Check Proposal Criteria):
  - **Target**: validate-frontmatter.py | validate-semantics.py | consistency-check.sh
  - **Name**: imperative verb phrase (e.g., "Verify X matches Y")
  - **Category**: structural | cross-file sync | behavioral contract | reference check
  - **Similar to**: existing/pending check from check-inventory.md, or "none"
  - **Pass/fail**: one sentence describing what constitutes failure
```

**Check Proposal Criteria**

A proposed check must fall into one of these categories:

| Category | What it catches | Example |
|----------|----------------|---------|
| Structural | Missing keys, malformed data, invalid syntax | "Fixture YAML missing required `assertions` key" |
| Cross-file sync | Value in file A doesn't match corresponding value in file B | "Env var in prose not declared in frontmatter" |
| Behavioral contract | Code template would produce broken output at runtime | "Non-src template uses `process.env` without loading env config" |
| Reference check | A named reference (tool, file, path) doesn't resolve | "Skill references unknown tool `FooBar`" |

Do NOT propose checks that:
- Regex-match natural-language prose for specific wording (e.g., "prose must contain the word 'branch' within 200 chars of a recovery message")
- Enforce cosmetic formatting with no silent-failure risk (e.g., "numbered lists must have no gaps")
- Verify that prose *explains* something (e.g., "skill must document resumption behavior") — this is the scoped LLM review's job

**Rules**

Include these in each subagent prompt:

1. **Maximum findings for this dimension** (see per-dimension budget from Step 0).
2. **No overlap with automated checks.** `scripts/check-inventory.md` is authoritative, including the Pending and Rejected sections. If a check is pending, propose extending it instead. If a check was rejected, do not re-propose it unless the rejection reason no longer applies.
3. **Zero findings is valid.** Say "No findings for this dimension" and summarize what was checked.
4. **Self-review before presenting.** Merge proposed checks that cover the same invariant. Verify each finding against check-inventory.md one more time.
5. **Concrete fixes only.** Every fix must be implementable in a single PR.
6. **Self-filter by confidence.** For each candidate finding, estimate confidence: HIGH (can quote contradicting lines with file:line), MEDIUM (likely issue but needs adversarial check), LOW (suspicious pattern only). Include HIGH and MEDIUM findings. Drop LOW findings.

After all 3 return: collect up to 15 findings, deduplicate.

- **Write findings artifact** (`.runs/review-findings.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  findings = {
      'findings': [],  # list of {title, severity, dimension, files}
      'total_count': 0
  }
  print(json.dumps(findings))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/review-findings.json \
    --payload "$PAYLOAD" \
    --skill review
  ```

**POSTCONDITIONS:**
- 3 dimension subagents have returned
- Findings collected (up to 15), deduplicated
- `.runs/review-findings.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/review-findings.json')); fs=d.get('findings',[]); assert isinstance(fs, list), 'findings not a list'; tc=d.get('total_count'); assert isinstance(tc, int) and tc>=0, 'total_count invalid'; assert tc==len(fs), 'total_count=%d but len(findings)=%d' % (tc, len(fs)); [f.get('severity') in ('HIGH','MEDIUM','LOW') or (_ for _ in ()).throw(AssertionError('finding %s has bad severity: %s' % (f.get('title','?'), f.get('severity')))) for f in fs]"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 2a
```

**NEXT:** Read [state-2b-filter-findings.md](state-2b-filter-findings.md) to continue.
