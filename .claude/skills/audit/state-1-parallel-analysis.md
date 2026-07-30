# STATE 1: PARALLEL_ANALYSIS

**PRECONDITIONS:**
- Scope and baseline collected (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

## Step 1: Parallel analysis

Launch 3 Explore subagents in parallel (A, B, C). If scope is `full`, also
launch a 4th Explore subagent (D: Skill Architecture). Construct each agent's
prompt from:
- The **shared context instruction** below
- The agent's **dimension section**
- The **Finding Format** and **Rules**

> **Shared context instruction** — include verbatim in every subagent prompt:
>
> Before scanning, read these context files:
> `CLAUDE.md`, `.claude/settings.json`, `.claude/agent-prompt-footer.md`,
> `.claude/template-owned-dirs.txt`, `scripts/check-inventory.md`.
>
> Then read ALL files in these directories (adjust to scope if not full).
> This is the canonical template-source scope — every directory under
> `.claude/template-owned-dirs.txt` plus top-level `scripts/` and `Makefile`,
> filtered to analysis-relevant extensions:
> - Glob `.claude/commands/*.md` — every skill dispatcher
> - Glob `.claude/skills/**/state-*.md` — every skill state file (the bulk of skill behavior)
> - Glob `.claude/skills/**/skill.yaml` — every skill orchestration declaration
> - Glob `.claude/skills/**/orchestration.json` — every orchestration descriptor
> - Glob `.claude/skills/**/gates/*.sh` — every skill gate script
> - Glob `.claude/patterns/**/*.md` — every pattern file
> - Glob `.claude/patterns/*.json` — declarative configs (state-registry.json, agent-registry.json, coherence rules, convergence config)
> - Glob `.claude/procedures/*.md` — every procedure file
> - Glob `.claude/agents/*.md` — every agent definition
> - Glob `.claude/archetypes/*.md` — every archetype definition
> - Glob `.claude/templates/*.md` — canonical schemas (e.g., experiment-yaml.md)
> - Glob `.claude/stacks/**/*.md` — every stack file
> - Glob `.claude/hooks/*.sh` — every hook script
> - Glob `.claude/scripts/*.sh` — internal lifecycle/utility scripts
> - Glob `.claude/scripts/*.py` — internal validator/helper scripts
> - Glob `.claude/scripts/lib/*.py` — shared internal libraries
> - Glob `.claude/agent-memory/**/*.md` — agent memory scaffolds
> - Read `.claude/agent-prompt-footer.md` — agent prompt footer
> - Read `.claude/settings.json` — hook registry
> - Glob `scripts/*.py` — top-level validators
> - Glob `scripts/*.sh` — top-level shell utilities (consistency-check.sh, etc.)
> - Glob `scripts/*.mjs` — top-level node utilities (auto-migrate.mjs)
> - Glob `scripts/lib/*.py` — top-level shared libraries
> - Glob `scripts/validators/*.py` — top-level validator helpers
> - Read `Makefile` — entrypoint targets
>
> Excludes: `.claude/settings.local.json`, `__pycache__/`, `worktrees/`,
> `node_modules/`, `*.lock`, `*.pyc`.
>
> Do not report issues already covered by `scripts/check-inventory.md`
> (including its Pending and Rejected sections).
>
> **JIT awareness**: This template uses JIT State Dispatch — state files and
> agent prompts are intentionally self-contained. Some repetition is by design
> to avoid cross-file dependencies during context-limited execution. Do NOT
> flag self-containment repetition as duplication.
>
> **For Dimension D only**: also read `.runs/audit-skill-manifest.json` (the
> pre-computed structural manifest from State 0). Use the manifest as your
> primary data source for state-level metrics — do NOT re-read all raw state
> files. Selective reads of specific state files are allowed only to confirm
> manifest anomalies.

---

### Dimension A: Duplication

Focus: Find **textually identical or near-identical** code/prose blocks
duplicated across 3+ files that serve no architectural purpose and could be
extracted into a shared definition.

**Primary scan targets** (highest-yield duplication sources):
- Inline `python3 -c` one-liners in hook scripts (payload extraction, JSON reading, verdict checking)
- Boilerplate skeleton shared between structurally similar hooks (e.g., merge gates)
- Validator invocation lists repeated across skill files
- Artifact cleanup/deletion lists repeated within or across files
- Error handling patterns (`2>/dev/null || echo ""`, `ERRORS+=()`, deny JSON output)

**Classification** — for each candidate, determine:
- **Extractable**: No architectural reason for duplication. Could be a shared
  shell function, a referenced pattern section, or a named constant.
- **JIT-intentional**: Repeated for self-containment. Skip silently.

Only report extractable findings.

Files to read: all directories from shared context instruction, with special
attention to `.claude/hooks/*.sh` (the densest duplication source).

---

### Dimension B: Complexity

Focus: Find files whose **internal structure** has grown beyond maintainable
levels — not merely long files, but files with mixed responsibilities,
deep nesting, or interacting subsystems.

**Thresholds** (flag for analysis, not automatic finding):
- Shell scripts (.sh): >400 lines
- Markdown skill/pattern (.md): >600 lines
- Python scripts (.py): >1500 lines

**For each file exceeding a threshold, classify:**

- **Long but simple** — Linear structure: parallel case branches, sequential
  checklists, independent validation checks. Long because it covers many cases.
  **Do NOT report.** Instead, note in the "Scanned but clean" summary.

- **Long and complex** — One or more of:
  - Mixed responsibilities (validation + transformation + reporting in one file)
  - Deep nesting (4+ levels of if/elif/case)
  - Functions longer than 50 lines (.sh) or sections longer than 100 lines (.md)
  - Multiple helper functions that interact with shared mutable state
  - A file that is both a gate (deny/allow) and a validator (check N conditions)
  **Report with a split strategy.**

**Also flag regardless of file size:**
- Functions/sections with cyclomatic complexity concerns (many conditional paths)
- Files where a single change requires understanding 3+ helper functions

Files to read: all directories from shared context instruction.

---

### Dimension C: Abstractability

Focus: Find **semantically equivalent patterns** implemented inline in 3+ files
instead of referencing a shared definition. This goes beyond textual duplication
(Dimension A) — look for implementations that achieve the same goal with
different words, structure, or ordering.

**Deduplication rule**: If Dimension A already reported a finding about the
same pattern (textually identical blocks), do NOT re-report it here. Dimension C
is exclusively for **semantic** equivalence — same intent, different text.

**Primary scan targets:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.

- Protocol descriptions (e.g., fix-log writing format described differently in 13 files)
- Conditional archetype handling (`if web-app... elif service... elif cli...`)
  reimplemented per-skill instead of referencing a shared decision tree
- Gate-checking patterns (read JSON -> extract field -> compare -> error array)
  reimplemented per-hook instead of calling a shared function
- Artifact existence checks done inline instead of referencing a manifest

**For each finding, record:**
- The pattern being implemented inline (describe the intent, not the text)
- Number of files and their paths
- Where a shared definition should live
- **JIT tradeoff note**: Would extracting this break self-containment? If yes,
  note the tradeoff explicitly — the finding is still valuable but the fix
  approach should preserve JIT readability (e.g., "reference + inline fallback"
  rather than "extract entirely")

Files to read: all directories from shared context instruction.

---

### Dimension D: Skill Architecture (full scope only)

> **Scope gate**: This dimension runs ONLY when audit scope is `full`.
> If scope is not `full`, this agent is not launched.

Focus: Find **structural inefficiencies in skill design** — states that are
overcomplicated for their work, redundant operations within a single skill's
state machine, and dead paths that serve no purpose.

**Data source**: `.runs/audit-skill-manifest.json` (pre-computed in State 0).
Use the manifest as primary evidence. Read raw state files only to confirm
specific anomalies flagged by the manifest.

**Sub-dimension D1: Overcomplexity**

Flags:
- **Thin states**: A skill where >=2 states have <10 lines in ACTIONS —
  those thin states likely should merge with neighbors.
- **Step density**: Flag a state when ANY of these conditions AND 0
  intermediate artifact writes:
  - >7 `###` sub-headers in ACTIONS
  - >10 numbered steps (lines matching `^[0-9]+\.`) in ACTIONS (excluding code fences)
  - Any single `###` section exceeding 120 lines in ACTIONS
  Classify each flagged state as:
  - **PROCEDURAL** (sequential imperative steps — genuine risk)
  - **CONDITIONAL** (decision tree / branching logic — lower risk, note but deprioritize)
- **Heavy mechanism for light task**: A skill with >4 states for a task
  that produces a single output artifact (e.g., a report or JSON file).

**Dedup rule vs Dimension B**: B measures file-level complexity (function
nesting, mixed responsibilities within a single file). D1 measures
skill-level complexity (state count, state granularity, step density). If
a file is both a complex file (B) and a thin state (D1), report under D1
— the skill-level fix subsumes the file-level concern.

**Sub-dimension D2: Intra-Skill Redundancy**

Flags:
- Same bash/python operation (by textual or semantic similarity) appearing
  in 2+ states within the SAME skill. Examples: duplicate artifact cleanup
  commands, repeated context-file reads, identical validation checks.
- Same POSTCONDITION check appearing in 2+ states of the same skill.

**Dedup rule vs Dimension C**: D2 covers intra-skill redundancy ONLY
(same operation repeated across states within one skill). Cross-skill
redundancy (same pattern in different skills) belongs to Dimension C.
If a pattern spans both intra-skill and cross-skill, report under C —
the broader fix is higher impact.

**Sub-dimension D3: Dead Paths**

Flags:
- **Orphan state files**: State files on disk (`.claude/skills/<skill>/
  state-*.md`) whose ID is missing from the canonical orchestration
  source — `skill.yaml` `states:` (or, for multi-mode skills,
  `modes.<mode>.states`) — and from any inline dispatch in
  `.claude/commands/<skill>.md`. Check the manifest `orphan_state_files`
  field; cross-check `dispatch_state_ids` and `skill_yaml_state_ids`.
- **Unreachable branches**: Conditional branches in state ACTIONS where
  the condition can never be true given the skill's preconditions or
  archetype constraints (e.g., `elif cli` in a skill that only handles
  `web-app`).
- **Write-only context fields**: JSON fields written to a context file
  (e.g., `.runs/<skill>-context.json`) but never read by any subsequent
  state in that skill.

Files to read: `.runs/audit-skill-manifest.json` (primary). Selective
raw state file reads only when a manifest anomaly needs confirmation.

**Sub-dimension D4: Registry Sync Quality**

> Complement to D3 (D3 uses dispatch tables, D4 uses registry entries).

Flags:
- **(b) File-stronger-than-registry**: The VERIFY block in a state file
  checks MORE conditions than the registry entry. The registry is the
  runtime authority — a weaker registry entry means the gate allows
  states to pass without checking conditions the documentation requires.
- **(c) Semantically-different checks**: The file VERIFY and registry
  entry check DIFFERENT artifacts or conditions (not just weaker/stronger).
- **Cross-state artifact chains**: State N's POSTCONDITIONS create
  artifact X, but state N+1's registry postcondition does NOT verify X.

**Intentional skips:**
- **(a) Registry-stronger-than-file**: Intentional — registry was upgraded
  while .md files retain simpler checks for LLM readability. Do NOT report.
- **`audit` skill states**: Exclude from self-referential comparison.
- **Cosmetic differences**: `&& echo "OK" || echo "FAIL"` appended to
  file checks is human-readable feedback, not a postcondition difference.

Data source: `.claude/patterns/state-registry.json` entries vs VERIFY
blocks in `state-*.md` files. Use manifest `postcondition_items` as
secondary signal.

---

### Finding Format

Every finding from every dimension must use this format:

```
### Finding <D><N>: <title>
- **Dimension**: A (Duplication) | B (Complexity) | C (Abstractability) | D (Skill Architecture)
- **Impact**: HIGH (10+ files or >100 dup lines) | MEDIUM (4-9 files) | LOW (2-3 files)
- **Effort**: LOW (<30 min) | MEDIUM (1-2 hours) | HIGH (>2 hours)
- **Files**: <file1>, <file2>, ... (or "N files — see list below")
- **Issue**: <specific description — quote representative text>
- **Suggestion**: <concrete, implementable improvement>
```

### Rules

Include in each subagent prompt:

1. **Maximum 7 findings per dimension.** Prioritize by impact.
2. **No overlap with automated checks.** Read `scripts/check-inventory.md` — if
   a check exists or was rejected, do not report it.
3. **No overlap between dimensions.** Dimension A = textual duplication.
   Dimension C = semantic equivalence (different text, same intent). If the same
   pattern qualifies for both, report it under A only.
3b. **D2 boundary.** D2 = intra-skill redundancy only. Cross-skill patterns → C.
    D1 = skill-level complexity. File-level complexity → B.
4. **Zero findings is valid.** Say "No findings — scanned N files, all clean."
5. **Confidence filter.** Only report HIGH confidence (can quote specific lines)
   and MEDIUM confidence (likely issue, evidence points to it). Drop LOW.
6. **Self-review.** Before presenting: verify each finding is not already in
   check-inventory.md, verify no overlap with other dimensions, verify
   JIT-intentional repetition is excluded.

---

After all agents return (3 if scope is not full, 4 if scope is full), collect findings and deduplicate:
- Finding signature = `<dimension>:<primary_file>:<title>`
- If two findings from different dimensions describe the same underlying issue,
  keep the one with higher impact; drop the other with a note.

## Do NOT
- Modify any source files — this skill is analysis only
- Create branches or PRs
- Propose fixes for correctness issues — that is `/review`'s job
- Flag intentional JIT repetition as duplication
- Report "long but simple" files as complexity hotspots
- Report the same finding under both Dimension A and Dimension C
- Report D2 findings for cross-skill patterns — that is Dimension C's scope
- Report D1 findings for file-level complexity — that is Dimension B's scope

**POSTCONDITIONS:**
- 3 subagents completed (Duplication, Complexity, Abstractability), plus Dimension D (Skill Architecture) if scope is `full`
- Findings collected and deduplicated
- Each finding follows the Finding Format
- Rules enforced (max 7 per dimension, no overlap, confidence filter)

- **Write analysis artifact** (`.runs/audit-analysis.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  import os
  analysis = {
      'duplication': {'findings': [], 'count': 0},
      'complexity': {'findings': [], 'count': 0},
      'abstractability': {'findings': [], 'count': 0},
      'total_findings': 0
  }
  if os.path.exists('.runs/audit-skill-manifest.json'):
      analysis['skill_architecture'] = {'findings': [], 'count': 0}
  print(json.dumps(analysis))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/audit-analysis.json \
    --payload "$PAYLOAD" \
    --skill audit
  ```

**VERIFY:**
```bash
python3 -c "import json,os; d=json.load(open('.runs/audit-analysis.json')); assert 'duplication' in d; assert not os.path.exists('.runs/audit-skill-manifest.json') or 'skill_architecture' in d"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh audit 1
```

**NEXT:** Read [state-2-prioritize-and-output.md](state-2-prioritize-and-output.md) to continue.
