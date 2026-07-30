# Skill Framework v2 Architecture


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Architecture overview; describes archetype as a concept (requires_archetype attribute, etc.). -->

Reference document for the skill framework. All migration PRs read this file for context.

---

## 1. Design Axioms

1. **Declare, don't implement** — A skill declares what it is; the framework decides how to execute it.
2. **Derive, don't configure** — Behavior derivable from facts requires no manual configuration.
3. **One skill = one folder** — Adding a new skill requires zero changes to infrastructure files (hooks, gates, settings.json).

---

## 2. File Structure

```
.claude/skills/<name>/
├── skill.yaml              # Manifest (required, alongside state files)
├── orchestration.json      # Phase config (JSON, optional)
├── gates/                  # Convention-based gate scripts (optional)
│   ├── <agent-name>.sh     # Per-agent procedural gate
│   ├── commit.sh           # Commit-time procedural gate
│   └── write.sh            # Write-protection procedural gate
├── state-0-xxx.md          # State files (6-section format)
├── state-1-xxx.md
└── ...

.claude/commands/<name>.md  # Thin dispatcher (Claude Code platform requirement, ~15 lines)
```

State files live inside the skill folder.

---

## 3. skill.yaml Schema

### Core Fields (5)

| Field | Required | Type | Purpose |
|-------|----------|------|---------|
| `states` | Yes | `string[]` | Ordered state ID list. Explicit contract — prevents typo-caused silent state skips. |
| `branch` | Code-writing only | `string` | Branch pattern (e.g., `"fix/resolve-{slug}"`). Present = code-writing skill, absent = analysis skill. |
| `agents` | Optional | `map` | Agent dependency graph with declarative gate fields. See extended schema below. |
| `loop` | Optional | `string[]` | State IDs that may be re-entered. Metadata only — control flow lives in state file NEXT section. Tells the framework these states can repeat without triggering advancement errors. |
| `embed` | Optional | `array` | Embedded sub-skills. Each entry: `{at: "<state_id>", skill: "<name>", scope: "<scope>"}`. |

When `modes` is present (rare, e.g., /iterate), it replaces `states`:

```yaml
modes:
  default:
    states: ["0", "1", "2"]
  <mode-name>:
    trigger: "--<flag>"
    states: ["m0", "m1", "m2"]
```

### Agents Extended Schema

Each agent entry in the `agents` map supports:

```yaml
agents:
  <agent-name>:
    # Core scheduling
    after: ["state-id", ...]             # Spawn after these states complete
    depends_on: [agent-name, ...]        # Wait for these agents to complete
    mode: "background" | "foreground"    # Default: background
    condition: "<expression>"            # Optional: condition for spawning

    # Declarative gate fields (checked by universal hook)
    requires_archetype: "<archetype>"    # Only spawn for this archetype (e.g., "web-app")
    requires_traces: [agent-name, ...]   # These agents' traces must exist with verdict + matching run_id
    scope_condition:                     # Additional trace requirements when scope matches
      scope: "<value>"
      requires_traces: [agent-name, ...]
```

**Convention gate**: `custom_gate` is NOT a YAML field. Instead, the framework checks
`gates/<agent-name>.sh` by filesystem convention. If the file exists, it runs after
declarative checks pass. If it doesn't exist, only declarative checks apply.

### Boundary: Declarative vs Procedural

| Check type | Mechanism | Examples |
|------------|-----------|---------|
| Existence checks | Declarative (YAML) | Trace file exists, verdict non-empty, run_id matches, archetype matches |
| Quality checks | Convention gate (script) | Retry completeness, file boundary enforcement, scope-conditional aggregation |

---

## 4. Derivation Rules (12)

All derived automatically. Zero manual configuration.

| # | Behavior | Derived from | Logic |
|---|----------|-------------|-------|
| 1 | Create branch | `branch` field | Present → create; absent → skip |
| 2 | Skill type | `branch` field | Present → code-writing; absent → analysis |
| 3 | When to verify | `branch` + `embed` | Has branch + embed:verify → verify runs at embed state; no embed → verify runs standalone after last state |
| 4 | Verify scope | Default `full` | Override only via `embed` scope field |
| 5 | Observation mode | Runtime `git diff` | Diff exists → spawn observer agent; else → inline execution audit |
| 6 | Create PR | `branch` + `git diff` | Has branch + has diff → commit + PR + auto-merge |
| 7 | Epilogue strategy | Eliminated | Derived from verify embed status + git diff presence |
| 8 | Build check | Verify embed | Verify procedure includes build check internally |
| 9 | PR gate checks | Verify output | `verify-report.md` exists → full-verify checks; else → artifact-only |
| 10 | Agent spawn allowed | `agents` declarations | Check archetype + traces + scope_condition + convention gate |
| 11 | Commit allowed | Framework defaults + convention | Code-writing skills: state completion + postconditions + `gates/commit.sh` |
| 12 | Write allowed | Convention | `gates/write.sh` exists → enforce; else → allow all writes |

---

## 5. State File Format

Each state file has 6 sections:

```
PRECONDITIONS   — Entry conditions for this state
ACTIONS         — What to do (business logic — executed by LLM)
POSTCONDITIONS  — Completion description (prose)
VERIFY          — Executable verification command (bash)
STATE TRACKING  — Records state completion (advance-state.sh call)
NEXT            — Next state (informational — lifecycle-next.sh drives actual dispatch)
```

### Information Ownership (Zero Overlap)

```
skill.yaml owns (cross-state architectural info):
├── branch, states, agents, loop, embed

State files own (per-state execution info):
├── PRECONDITIONS, ACTIONS, POSTCONDITIONS
├── VERIFY, STATE TRACKING, NEXT

state-registry.json owns (VERIFY commands only):
└── Per-skill per-state VERIFY commands (authoritative source)
    Hooks read VERIFY from here, not from state files.

orchestration.json owns (phase config):
└── phases (state_range, interactive, gate, max_budget)
```

---

## 6. VERIFY Ownership

**Path A: state-registry.json continues to own VERIFY commands.**

The registry is shrunk to contain ONLY VERIFY commands:
```json
{
  "solve": {
    "0": "test -f .runs/solve-context.json",
    "1": "python3 -c \"...\"",
    "2": "...",
    "3": "..."
  },
  "bootstrap": { ... },
  ...
}
```

The former `observation_gates` and `agent_gates` sections migrate to per-skill `skill.yaml` files.
Existing toolchain preserved: `verify-linter.sh`, `sync-verify-to-state-files.sh`, CLAUDE.md Rule 13.

---

## 7. Lifecycle Engine (3 Phases, Code-Driven)

The lifecycle engine replaces LLM-memory-driven dispatch with code-driven dispatch.
Deterministic operations are code; creative work (state ACTIONS) remains LLM-driven.

### Phase 1: INIT — `lifecycle-init.sh <skill> [extra_json]`

```
Input:  skill name + optional extra JSON (e.g., mode selection, scope)
Output: .runs/<skill>-lifecycle.json + .runs/<skill>-context.json + branch (if applicable)

Steps:
1. Find and parse .claude/skills/<skill>/skill.yaml
2. If modes present + extra_json has mode field → select that mode's states
3. Write .runs/<skill>-lifecycle.json (JSON copy of skill.yaml, for hooks to read).
   NOTE: .runs/<skill>-manifest.json is reserved for each skill's domain output
   (e.g., deploy resources, iterate verdicts, audit findings) — see issue #1006.
4. If branch field present and not in worktree → create branch
5. Create canonical context (run_id, branch, timestamp) via init-context.sh

Fallback: if skill.yaml not found → warn, call init-context.sh only (v1 compat)
```

### Phase 2: EXECUTE — `lifecycle-next.sh <skill>` drives dispatch

```
Input:  skill name
Output: path to next state file, or "FINALIZE", or "NO_MANIFEST"

Steps:
1. Read .runs/<skill>-context.json → completed_states
2. Read .runs/<skill>-lifecycle.json → states list
3. Find first state_id in states not in completed_states
   - For loop states: allow re-entry (check manifest loop field)
4. Find state file: .claude/skills/<skill>/state-<id>-*.md
5. Output file path, or "FINALIZE" if all states complete

The LLM loop:
  a. Call lifecycle-next.sh → get state file path
  b. If "FINALIZE" → go to Phase 3
  c. Read state file, execute ACTIONS
  d. Call advance-state.sh <skill> <state_id> (hook enforces VERIFY)
  e. Repeat from (a)
```

### Phase 3: FINALIZE — `lifecycle-finalize.sh <skill>`

```
Input:  skill name
Output: delivery result

Steps:
1. Read context.json, verify all states in completed_states
2. If branch field present AND git diff exists:
   a. Delivery Gate:
      - Rerun all state VERIFY commands (from state-registry.json)
      - If verify-report.md exists: validate frontmatter, trace completeness
      - Scan gate-verdicts/*.json for BLOCK verdicts
      - Check observe-result.json exists
   b. If all pass: commit → push → gh pr create → auto-merge
3. If no branch or no diff: verify observe-result.json exists only
4. Output "FINALIZE_COMPLETE"

Note: Observation (Strategy A/B) is executed by the LLM in the skill's epilogue
state, NOT in lifecycle-finalize.sh. Finalize handles delivery gate + git ops only.
```

### Command File Template (post-migration)

```markdown
# /<skill>

[Skill-specific pre-flight: argument parsing, precondition checks]

## Lifecycle

1. Run `bash .claude/scripts/lifecycle-init.sh <skill> [extra_json]`
2. State execution loop:
   a. Run: `NEXT=$(bash .claude/scripts/lifecycle-next.sh <skill>)`
   b. If NEXT is "FINALIZE" → go to step 3
   c. If NEXT is "NO_MANIFEST" → STOP with error
   d. Read the state file at $NEXT and execute its ACTIONS section
   e. After ACTIONS, run the STATE TRACKING command (advance-state.sh)
   f. Return to step 2a
3. Run `bash .claude/scripts/lifecycle-finalize.sh <skill>`
```

---

## 8. Gate System (3 Gates)

Gates are skill-agnostic. They read `<skill>-lifecycle.json` and `state-registry.json`, never skill names.

### Progression Gate

**Trigger:** `advance-state.sh` call (intercepted by `state-completion-gate.sh`) or Agent spawn

- **State advancement:** Run VERIFY command from `state-registry.json` for that state.
  Block if VERIFY fails.
- **Agent spawn:** Check all of:
  - `after` states are in completed_states
  - `depends_on` agents have trace files
  - `requires_archetype` matches current archetype (from context)
  - `requires_traces` exist with verdict + matching run_id
  - `scope_condition` satisfied (if applicable)
  - Convention gate `gates/<agent>.sh` passes (if file exists)

### Quality Gate

**Trigger:** Write/Edit to `.runs/` artifacts

- JSON schema validity for agent traces and gate verdicts
- Cross-artifact consistency checks

### Delivery Gate

**Trigger:** Once, at the start of `lifecycle-finalize.sh`

1. Rerun ALL state VERIFY commands (from state-registry.json)
2. If `verify-report.md` exists: validate frontmatter, check agents_expected == agents_completed, verify each agent has trace
3. If `build-result.json` exists (no verify-report): check exit_code == 0
4. Scan `gate-verdicts/*.json` — if any verdict == BLOCK → fail
5. Check `observe-result.json` exists

All pass → framework proceeds with commit → push → PR → merge.

---

## 9. Universal Hooks (4, Static Registration)

`settings.json` has a fixed set of hook entries that **does not change when skills are added or removed.**
4 of these hooks are skill-identity-aware (listed below). The remaining ~10 hooks are
already generic (artifact-integrity-gate, verify-report-gate, phase-boundary-gate, etc.)
and are retained unchanged from v1.

| Hook | Matcher | What it reads | Purpose |
|------|---------|---------------|---------|
| `state-completion-gate.sh` | Bash (`advance-state`) | `state-registry.json` VERIFY commands | Enforce state postconditions before advancement |
| `skill-agent-gate.sh` | Agent (all) | Manifest `agents` + convention `gates/<agent>.sh` | Enforce agent spawn prerequisites |
| `skill-commit-gate.sh` | Bash (`git commit`) | Manifest `branch` + convention `gates/commit.sh` | Enforce commit-time checks for code-writing skills |
| `skill-write-gate.sh` | Write/Edit (all) | Convention `gates/write.sh` | Enforce file-write protection |

### Execution Model (all universal hooks)

```
1. Read .runs/<skill>-lifecycle.json
2. Apply declarative checks (pure data lookup, <10ms)
3. Run convention gate script if exists (≤30s timeout)
4. If no manifest found → fallback to old hook logic (v1→v2 hook migration compat; unrelated to the 2026-04 framework-path rename)
5. If no active skill → exit 0 (pass-through)
```

### Migration from v1 Hooks

| v1 Hook (replaced) | Lines | v2 Hook | Lines |
|---------------------|-------|---------|-------|
| `agent-state-gate.sh` (6 hardcoded dispatch functions) | 383 | `skill-agent-gate.sh` | ~80 |
| `change-commit-gate.sh` + `bootstrap-commit-gate.sh` | 245 | `skill-commit-gate.sh` | ~60 |
| `bootstrap-root-protection.sh` | 54 | `skill-write-gate.sh` | ~40 |

Hooks NOT replaced (already generic): `state-completion-gate.sh`, `phase-boundary-gate.sh`,
`verify-pr-gate.sh`, `observe-commit-gate.sh`, `artifact-integrity-gate.sh`,
`verify-report-gate.sh`, `patterns-saved-gate.sh`, `design-ux-merge-gate.sh`,
`security-merge-gate.sh`, `adversarial-merge-gate.sh`.

---

## 10. Convention-Based Gates

The `gates/` folder inside a skill directory uses filesystem presence as declaration:

| File | When it runs | What it handles |
|------|-------------|-----------------|
| `gates/commit.sh` | Before `git commit` on skill's branch | Skill-specific commit bypass/timing (e.g., checkpoint enforcement, merge commit bypass) |
| `gates/write.sh` | Before every Write/Edit during skill execution | File protection with phase-aware conditions (e.g., bootstrap root file protection) |
| `gates/<agent-name>.sh` | Before spawning that agent | Quality checks beyond declarative (e.g., retry completeness, file boundary enforcement) |

**File existence IS the declaration.** No YAML field needed.

Each gate script:
- Receives context via environment variables (`PROJECT_DIR`, `SKILL`, `TRACES_DIR`, `FILE_PATH`, `PAYLOAD`)
- Sources `lib.sh` for shared helpers (`deny()`, `require_trace_verdict()`, etc.)
- Exits 0 to allow, non-zero + stderr message to deny

---

## 11. Examples

### Analysis skill — /solve

```yaml
states: ["0", "1", "2", "3"]
agents:
  solve-critic:
    after: ["0"]
```

No branch → analysis-only → no PR, no verify auto-append, Strategy B epilogue.

### Standard code-writing — /resolve

```yaml
branch: "fix/resolve-{slug}"
states: ["0","1","2","3","3b","4","4b","5","5d","6","7","8","8b","9","9a","10","11"]
agents:
  resolve-challenger:
    after: ["5"]
  solve-critic:
    after: ["5"]
```

Has branch → code-writing → verify(full) auto-appended → PR auto-created.

### Large skill — /bootstrap

```yaml
branch: "feat/bootstrap-{slug}"
states: ["0","1","2","3","3a","3b","4","5","6","7","8","9",
         "10","11","11a","11b","11c","12","13","13a","13b","13c","14","15","16","17","18","19"]
agents:
  gate-keeper:
    after: ["0"]
  scaffold-externals:
    after: ["0"]
  scaffold-setup:
    after: ["8"]
    depends_on: [scaffold-init]
  scaffold-init:
    after: ["9"]
  scaffold-libs:
    after: ["11"]
    depends_on: [scaffold-setup]
  scaffold-images:
    after: ["11"]
  scaffold-pages:
    after: ["11b"]
    depends_on: [scaffold-libs]
  scaffold-landing:
    after: ["11b"]
    depends_on: [scaffold-libs]
  scaffold-wire:
    after: ["13c"]
    depends_on: [scaffold-pages, scaffold-landing]
embed:
  - at: "19"
    skill: verify
    scope: full
```

Embedded verify runs at state 19 with scope: full. Convention gates: `gates/commit.sh` (BG verdict checks), `gates/write.sh` (root file protection).

### Verify-first — /distribute

```yaml
branch: "chore/distribute"
states: ["0","1","2","3","4","5","6"]
embed:
  - at: "3"
    skill: verify
    scope: campaign
```

Embedded verify runs at state 3. Auto-appended verify detects prior execution → skips (idempotent).

### With loop — /review

```yaml
branch: "chore/review-{slug}"
states: ["0","1","2a","2b","2c","2d","2e","2f","3","4","5","6"]
loop: ["2a","2b","2c","2d","2e","2f"]
agents:
  review-challenger:
    after: ["2c"]
```

Loop states [2a-2f] may be re-entered. `lifecycle-next.sh` reads the `loop` field
and allows these states to not be in `completed_states` during re-iteration.

### With modes — /iterate

```yaml
modes:
  default:
    states: ["0","1","2","3","4","5"]
  check:
    trigger: "--check"
    states: ["c0","c1","c2","c3"]
  cross:
    trigger: "--cross"
    states: ["x0","x1","x2","x3","x4","x5"]
```

No branch → analysis-only. `lifecycle-init.sh` selects mode based on trigger argument.

### Complex agent graph — /verify

```yaml
states: ["0","1","2","3a","3b","3c","3d","4","5","7a","7b","8"]
agents:
  build-info-collector:
    after: ["1"]
    mode: "foreground"
  security-defender:
    after: ["1"]
    mode: "foreground"
    requires_traces: [build-info-collector]
  security-attacker:
    after: ["1"]
    mode: "foreground"
    requires_traces: [build-info-collector]
  behavior-verifier:
    after: ["1"]
    mode: "foreground"
    requires_traces: [build-info-collector]
  performance-reporter:
    after: ["1"]
    mode: "foreground"
    requires_traces: [build-info-collector]
  accessibility-scanner:
    after: ["1"]
    mode: "foreground"
    requires_traces: [build-info-collector]
  spec-reviewer:
    after: ["1"]
    mode: "foreground"
    requires_traces: [build-info-collector]
  design-critic:
    after: ["1"]
    requires_archetype: web-app
    requires_traces: [build-info-collector]
    scope_condition:
      scope: full
      requires_traces: [security-defender, security-attacker, behavior-verifier]
  design-consistency-checker:
    after: ["1"]
    requires_archetype: web-app
    requires_traces: [build-info-collector]
  ux-journeyer:
    after: ["1"]
    requires_archetype: web-app
    requires_traces: [design-critic, design-consistency-checker]
  quality-fixer:
    after: ["3c"]
    requires_archetype: web-app
    requires_traces: [accessibility-scanner, design-consistency-checker]
  security-fixer:
    after: ["3a"]
    requires_traces: [build-info-collector]
  observer:
    after: ["4"]
  pattern-classifier:
    after: ["6"]
```

14 agents. Convention gates: `gates/design-critic.sh` (per-page file boundary),
`gates/ux-journeyer.sh` (retry completeness), `gates/quality-fixer.sh` (quality-merge prerequisites), `gates/security-fixer.sh` (scope-conditional aggregation).

### Other skills (minimal manifests)

```yaml
# /audit
states: ["0", "1", "2", "3"]

# /observe
states: ["0", "1", "2"]

# /retro
states: ["0", "1", "2", "3", "4"]

# /rollback
states: ["0", "1", "2", "3", "4"]

# /teardown
states: ["0", "1", "2", "3", "4", "5"]
agents:
  provision-scanner:
    after: ["2"]

# /deploy
states: ["0","1","2","3a","3b","3c","4a","4b","5","6"]
agents:
  provision-scanner:
    after: ["3a"]

# /upgrade
branch: "chore/upgrade-{slug}"
states: ["0", "1", "2", "3"]

# /spec
branch: "feat/spec-{slug}"
states: ["0","1","2","3","4","5","6","7","8"]

# /change
branch: "change/{slug}"
states: ["0","1","2","3","4","5","6","7","8","9","10","11","12"]
agents:
  gate-keeper:
    after: ["0"]
  implementer:
    after: ["9"]
  visual-implementer:
    after: ["9"]
  solve-critic:
    after: ["3"]
embed:
  - at: "11"
    skill: verify
    scope: full
```

---

## 12. Adding a New Skill

```bash
mkdir -p .claude/skills/new-skill/
# 1. Write skill.yaml (states + branch/agents/loop/embed as needed)
# 2. Write state-*.md files (6-section format)
# 3. Write orchestration.json (if multi-phase pipeline needed)
# 4. Write gates/*.sh (if custom procedural gate logic needed)
# 5. Add VERIFY commands to state-registry.json (the only shared file edit)
# 6. Run make sync-verify to propagate VERIFY to state files
```

**Zero hook changes. Zero gate script changes. Zero settings.json changes.**

The only shared file edit is `state-registry.json` VERIFY commands, managed by
the existing `verify-linter.sh` + `sync-verify-to-state-files.sh` toolchain.
