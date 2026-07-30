# Scoped Review Prompt

You are a template auditor reviewing this experiment template for issues
that automated validators cannot catch. Execute the workflow below — no
user input is needed until the plan mode approval step.

---

## Phase 1: Load context

Read these files:

1. `scripts/check-inventory.md` — canonical list of all automated checks
2. `CLAUDE.md`
3. `experiment/experiment.example.yaml`
4. `experiment/EVENTS.yaml`

---

## Phase 2: Parallel review

Launch 3 subagents in parallel using the Task tool (`subagent_type: "Explore"`),
one per dimension below. Construct each agent's prompt from:

- The **shared context instruction** (box below)
- The agent's **dimension section** (focus, examples, files to read)
- The **Rules** and **Finding Format** sections at the bottom of this file

> **Shared context instruction** — include verbatim in every subagent prompt:
>
> Before reviewing, read these files:
> `scripts/check-inventory.md`, `CLAUDE.md`, `experiment/experiment.example.yaml`, `experiment/EVENTS.yaml`.
> Do not report anything already covered by check-inventory.md (including Pending).

### Dimension A: Cross-File Consistency

**Focus**: Find contradictions or inconsistencies **between** files that no regex or structural check can catch. Examples:
- A skill file says "do X" but a stack file's code template does Y
- A rule in CLAUDE.md conflicts with how a skill actually operates
- A stack file assumes a convention that another stack file violates
- A prose instruction references a function/file/path that doesn't match reality

**Files to read**:
- Glob `.claude/commands/*.md` — read each skill file
- Glob `.claude/stacks/**/*.md` — read each stack file
- Glob `.claude/patterns/*.md` — read each pattern file

### Dimension B: Edge Case Robustness

**Focus**: Find configurations where skills or stack files would produce broken output. Examples:
- A skill assumes auth exists but the experiment.yaml has no `stack.auth`
- A code template hard-codes a path that changes based on stack choices
- A conditional branch in a skill handles 2 of 3 possible states
- An edge case not covered by the test fixtures

**Files to read**:
- Glob `.claude/commands/*.md` — read each skill file
- Glob `.claude/stacks/**/*.md` — read each stack file
- Glob `tests/fixtures/*.yaml` — read each test fixture

After reading: mentally simulate running `/bootstrap` and `/change` with each fixture's configuration.

### Dimension C: User Journey Completeness

**Focus**: Find dead-end states where a user gets stuck with no clear next step. Examples:
- A skill exits early but doesn't tell the user what to do next
- A build failure produces an unhelpful error message
- A workflow step assumes a previous step succeeded but doesn't verify
- A Makefile target fails silently or with an unhelpful error
- The user follows instructions but ends up in an undocumented state

**Files to read**:
- Glob `.claude/commands/*.md` — read each skill file
- Glob `.claude/stacks/**/*.md` — read each stack file
- Glob `.claude/patterns/*.md` — read each pattern file
- Read `Makefile`

After reading: trace the user journey from `make validate` → `/bootstrap` → merge → `/verify` → `/deploy` → `/change` → `/verify` → `/distribute` → `/iterate` → `/retro` → `/teardown`.

---

## Phase 3: Consolidate and plan

After all 3 agents return:

1. Collect all findings (up to 15 total: 5 per dimension)
2. Deduplicate — if two agents found the same issue, keep the more detailed version
3. Enter plan mode (call `EnterPlanMode`)
4. Write the **Planning Summary** below as the plan
5. Exit plan mode for user approval

---

## Rules

Include these in each subagent prompt:

1. **Maximum 5 findings.** Keep only the 5 most impactful.

2. **No overlap with automated checks.** `scripts/check-inventory.md` is authoritative, including the Pending and Rejected sections. If a check is pending, propose extending it instead. If a check was rejected, do not re-propose it unless the rejection reason no longer applies.

3. **Zero findings is valid.** Say "No findings for this dimension" and summarize what was checked.

4. **Self-review before presenting.** Merge proposed checks that cover the same invariant. Verify each finding against check-inventory.md one more time.

5. **Concrete fixes only.** Every fix must be implementable in a single PR.

---

## Finding Format

Include this in each subagent prompt:

```
### Finding N: <title>
- **File(s)**: ...
- **Issue**: ... (be specific — quote the conflicting text)
- **Impact**: ... (what breaks or confuses the user)
- **Fix**: ... (concrete, implementable)
- **Proposed check** (only if the finding qualifies — see Check Proposal Criteria below):
  - **Target**: validate-frontmatter.py | validate-semantics.py | consistency-check.sh
  - **Name**: imperative verb phrase (e.g., "Verify X matches Y")
  - **Category**: structural | cross-file sync | behavioral contract | reference check
  - **Similar to**: existing/pending check from check-inventory.md, or "none"
  - **Pass/fail**: one sentence describing what constitutes failure
```

---

## Check proposal criteria

A proposed check must fall into one of these categories:

| Category | What it catches | Example |
|----------|----------------|---------|
| Structural | Missing keys, malformed data, invalid syntax | "Fixture YAML missing required `assertions` key" |
| Cross-file sync | Value in file A doesn't match corresponding value in file B | "Env var in prose not declared in frontmatter" |
| Behavioral contract | Code template would produce broken output at runtime | "Non-src template uses `process.env` without loading env config" |
| Reference check | A named reference (tool, file, path) doesn't resolve | "Skill references unknown tool `FooBar`" |

**Do NOT propose checks that:**
- Regex-match natural-language prose for specific wording (e.g., "prose must contain the word 'branch' within 200 chars of a recovery message")
- Enforce cosmetic formatting with no silent-failure risk (e.g., "numbered lists must have no gaps")
- Verify that prose *explains* something (e.g., "skill must document resumption behavior") — this is the scoped LLM review's job

These are prose-phrasing checks. They belong in the LLM review, not in regex validators.
See the Rejected table in `scripts/check-inventory.md` for prior examples.

---

## Planning Summary

Use this structure for the plan written in Phase 3:

```
## Review Summary

**Dimensions reviewed**: A, B, C
**Total findings**: N (A: n, B: n, C: n)
**Files affected**: [deduplicated list]

### Findings by Dimension

#### Dimension A: Cross-File Consistency
[findings or "No findings — checked: ..."]

#### Dimension B: Edge Case Robustness
[findings or "No findings — checked: ..."]

#### Dimension C: User Journey Completeness
[findings or "No findings — checked: ..."]

### Fix Queue
| # | Dim | Finding | File(s) | Scope |
|---|-----|---------|---------|-------|

### Proposed Checks
| Name | Target validator | Extends existing? |
|------|-----------------|-------------------|

### Next steps
[prioritized actions to fix the findings]

**Always last:** Update `scripts/check-inventory.md` — add every implemented check to the appropriate validator table, update the total counts in the header, and clear implemented entries from the Pending table.
```
