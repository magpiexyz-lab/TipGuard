# Gate-Artifact Ordering Procedure

> Recurrence guard for the defect class behind #1142: a gate G that asserts
> the existence of an artifact A whose producer P runs at state X, where G
> runs at state Y < X. This is a manual review checklist; not currently
> CI-enforced (the coherence-rule handler form requires structured ownership
> frontmatter across stack files — phased to a follow-up when the migration
> from free-form ownership comments to YAML frontmatter is complete).

## When to Apply

Run this checklist whenever a `/change` PR modifies any of:

- `.claude/agents/gate-keeper.md` (gate spec — adds/moves/deletes a check)
- `.claude/skills/<skill>/skill.yaml` (state list, agents block — reorders states or changes `after:` placement)
- `.claude/agents/scaffold-*.md` (producer "Key Constraints" — changes write territory)
- `.claude/skills/<skill>/state-*-*-gate.md` (gate invocation — moves a gate state)
- `.claude/stacks/**/*.md` (`files:` frontmatter list — changes which stack owns which file)

## Procedure

### Step 1: Inventory artifact references in the gate

For each numbered check in the gate spec, list every artifact path it
references:
- Literal `src/...` paths in grep/test/find commands
- Glob patterns expanded at runtime (e.g., `src/app/<page>/...`)
- `.runs/...` artifacts written by other agents

### Step 2: Identify each artifact's producer

For each path, find its declared producer in this priority order:

1. **Stack-file frontmatter `files:` lists** — `.claude/stacks/<category>/<value>.md` frontmatter. Example: `database/supabase.md:9` declares `src/lib/types.ts` as a libs/supabase artifact.
2. **Agent "Key Constraints" sections** — `.claude/agents/scaffold-*.md` "exclusive write territory" or "Do NOT write to" clauses.
3. **Procedure step-level statements** — `.claude/procedures/scaffold-*.md` and `procedures/wire.md` "Create…" or "Write…" lines.
4. **State-file ACTIONS sections** — when the lead agent writes the artifact directly (rather than spawning a scaffold agent).

### Step 3: Verify producer-state ≤ gate-state

For the active skill's `skill.yaml`:

1. Read the `agents` block → map each producer agent to its `after:` value.
2. Read the `states` list → find the gate's containing state.
3. Compare positions in the linear `states` list. **Position-based comparison, NOT lexical.** State `"11a"` precedes `"11b"` precedes `"12"` precedes `"13c"` etc.
4. Apply the rule: for each artifact A referenced by gate G, A's producer must complete at or before G's state.

### Step 4: Resolve any misalignment

If the rule is violated, choose ONE of:

- **Move the gate later.** Split the gate into pre-X and post-X variants (the canonical fix — cf. `BG2` → `BG2` + `BG2-WIRE` for #1142).
- **Move the producer earlier.** Only viable if the producer's `depends_on` chain allows.
- **Move the artifact's production to an earlier producer.** Only viable if the new producer's territory legitimately includes that file.

Never silently exclude the artifact from the gate ("hardcoded exclusion") — that pattern is what BG2 line-270 originally did, and it ages badly when wire actually starts producing more artifacts the gate cares about.

### Step 5: Document the alignment

In the PR description, include a one-line attestation:

> Gate-artifact ordering reviewed: gate=`<name>`, producers=`<list>`. All producers run at or before gate state per `skill.yaml`.

If you split a gate or moved a producer, briefly note which option you chose and why.

## Cross-Links

- `.claude/patterns/audit.md` — `/audit` includes this checklist as a periodic review item.
- **Originating defect**: #1142 (BG2 asserted scaffold-wire artifacts before scaffold-wire ran).
- **Future automation**: when stack-file ownership is migrated from free-form YAML comments to structured `ownership:` frontmatter, implement a `gate_artifact_ordering` rule type in `.claude/scripts/lib/linter/runner.py` HANDLERS for CI enforcement.
