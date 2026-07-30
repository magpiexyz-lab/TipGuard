# `lib/linter` — verify-linter Python package

The Python implementation of `.claude/scripts/verify-linter.sh`. Lifted out
of the bash heredoc by PR2; rule-key validation added by PR3; documented and
test-covered here in PR4.

## Module layout

| File | Responsibility |
|------|----------------|
| `cli.py` | 6-line bootstrap shim. Resolves `sys.path` so the package is importable, then `sys.exit(runner.main())`. Keeps the relative-import-in-`__main__` trap out of the rest of the package. |
| `runner.py` | Single-file entry: `def main() -> int`. Contains all 26 functions (5 subsystems) verbatim from the original heredoc, the `HANDLERS` registry, schema validation, dispatch, and report formatting. **Pre-PR2:** lived as a 1500-line shell heredoc inside `verify-linter.sh`. |
| `__init__.py` | Empty (package marker). |
| `cross_file/__init__.py` | Empty stub reserved for a future split (one file per cross-file rule type). Not used today; everything lives in `runner.py`. |

## How the bash wrapper invokes the package

```bash
.claude/scripts/verify-linter.sh
  ↓ parses --json/--cache/--warn-only/--strict-aoc/--rules
  ↓ exports VL_JSON_OUT, VL_CACHE_FILE, VL_WARN_ONLY, VL_STRICT_AOC,
  ↓         VL_RULES_PATH, VL_REPO_ROOT
  ↓ exec python3 .claude/scripts/lib/linter/cli.py
                      ↓ sys.path.insert(SCRIPTS_DIR)
                      ↓ from lib.linter.runner import main
                      ↓ sys.exit(main())
```

Bash retains argument parsing to preserve the `ERROR: unknown flag: <X>`
literal stderr + exit code 2 contract. Python reads only `VL_*` env vars.

## The HANDLERS registry

`runner.py` defines (inside `main()`):

```python
HANDLERS = {
    "field_role_map":                   (handler, required={"field","canonical_function"}, optional={"consumers"},                              is_strict_aoc=False),
    "discover_consumers":               (handler, required={"field","against_rule","consumption_patterns"}, optional={"path_excludes"},          is_strict_aoc=False),
    "artifact_lifecycle":               (handler, required={"skill"},                  optional=set(),                                          is_strict_aoc=False),
    "verdict_vocab_consistency":        (handler, required=set(),                      optional={"registry_path","agent_files_glob","predicate_file"}, is_strict_aoc=True),
    "ledger_ownership":                 (handler, required={"allowed_writers","gated_paths"}, optional=set(),                                   is_strict_aoc=True),
    "consumer_coverage":                (handler, required={"canonical_source","consumers"},  optional=set(),                                   is_strict_aoc=True),
    "frontmatter_artifact_consistency": (handler, required={"schema_path","writer"},   optional={"consumers"},                                  is_strict_aoc=True),
    "internal_href_validity":           (handler, required=set(),                      optional={"scaffold_glob","route_owner_hints"},          is_strict_aoc=False),
}
META_KEYS = {"id", "type", "severity", "description", "_transitional_note", "_comment"}
```

At rule load every rule is validated:

1. **Type in HANDLERS** — typo'd type → `SystemExit("unknown rule type 'X' in rule id=Y; valid: ...")` exit 1.
2. **No unknown keys** (after subtracting META_KEYS) → exit 1 with the offending field + valid set named.
3. **All required present** → exit 1 with the missing required listed.
4. **Each handler() call wrapped in `try/except`** → a buggy handler emits `[id] handler crashed: <type>: <msg>` finding instead of killing the linter.

**Required/optional sets are derived from each handler's actual `rule.get(...)` call sites.** If you add a field to a handler, you MUST update the corresponding entry in `HANDLERS` — otherwise rules using that field hit "unknown field".

### Schema errors override `--warn-only`

A typo'd rule key is an **infrastructure error** (template author mistake), not
a coherence violation (real-world drift). It must surface immediately.
`--warn-only` does NOT mask schema errors. This is a deliberate contract
addition versus the original heredoc, which silently no-op'd typo'd types.

## The AOC tag invariant

`_is_aoc_finding()` partitions findings for `--strict-aoc` exit-code
semantics by substring-matching `(rule_type/severity)` in the message. Two
classes of handler exist:

- **`is_strict_aoc=True` (4 types)**: `verdict_vocab_consistency`,
  `ledger_ownership`, `consumer_coverage`, `frontmatter_artifact_consistency`.
  All use `_emit_finding(rule, msg)` which inserts the `(rtype/sev)` tag.
- **`is_strict_aoc=False` (4 types)**: `field_role_map`, `discover_consumers`,
  `artifact_lifecycle`, `internal_href_validity`. The first three append
  bare `out.append(...)` strings without the tag — they are intentionally
  NOT in the strict-AOC partition. `internal_href_validity` uses
  `_emit_finding` and emits the tag, but its `is_strict_aoc=False` keeps it
  out of the strict-AOC exit-code partition (it is a warn-level rule).

This asymmetry is **load-bearing**: changing it shifts findings between exit
code categories. The `test_aoc_tag_invariant` test in
`.claude/scripts/tests/test_linter_parity.py` locks the contract that
strict-AOC handlers always produce tagged findings.

## Adding a new cross-file rule type

1. Implement `def check_my_rule(rule)` inside `runner.py` next to the existing handlers. It returns `list[str]` of findings. Use `_emit_finding(rule, msg)` if and only if you want the `(rtype/sev)` tag (mandatory for `is_strict_aoc=True`).
2. Add an entry to `HANDLERS` with required + optional field sets matching every `rule.get(...)` call site in your handler.
3. Add an entry to `.claude/patterns/coherence-rule-schema.json` `oneOf` array (mirrors HANDLERS for documentation).
4. Either add a fixture under `.claude/scripts/tests/fixtures/linter_synthetic/<your_rule_name>/` with `rules.json` + `files/` and a corresponding test method in `test_linter_parity.py`, OR add a dedicated test file under `.claude/scripts/tests/test_<your_rule_name>.py` that drives the same scenarios via subprocess (mirrors `test_linter_validation.py` and `test_lib_helper_stack_knowledge_required.py`). Either is acceptable — the fixture form is more uniform with existing parity tests; the dedicated test form is more readable for rule-specific edge cases (substring collisions, pragma escape hatches, multi-pattern consumption).
5. If your rule is `is_strict_aoc=True`: ensure your finding messages all go through `_emit_finding` (the tag invariant test will fail otherwise).

### Currently registered rule types (10 cross-file checks + per-state checks)

| Rule type | Severity tier | Notes |
|-----------|---------------|-------|
| `field_role_map` | warn | canonical accessor enforcement |
| `discover_consumers` | warn | grep + consumer-list drift |
| `verdict_vocab_consistency` | strict-AOC | agent verdict canonical names |
| `ledger_ownership` | strict-AOC | fix-ledger writer allowlist |
| `consumer_coverage` | strict-AOC | fix-count consumers reference ledger |
| `validator_integration_required` | strict-AOC | hard-block validator wiring (#1295/#1307: with `minimum_integration_count` cardinality threshold) |
| `validator_inventory_completeness` | strict-AOC | every validate-*.py covered |
| `lib_helper_stack_knowledge_required` | strict-AOC | per-helper Stack Knowledge entry (#1300: enumerate lib/*.py public functions, count callers via narrow consumption_patterns, exact stack_scope match in lib/README.md, Python-native `# coherence-allow: not-reusable: <reason>` pragma escape hatch) |
| `state_defer_verify_pairing` | strict-AOC | #1339 deferred-VERIFY ↔ writer pairing |
| `branch_checkout_propagation_pairing` | strict-AOC | #1328 git checkout-b ↔ context-update pairing |
| (others) | warn / info | see HANDLERS table for full list |

## Decision log

- **Why a bash shim survives instead of a pure Python entry:** preserves the
  literal `ERROR: unknown flag: <X>` stderr and exit-2 contract that
  `lifecycle-finalize.sh` and CI workflows rely on. argparse's default error
  output is different.
- **Why `sys.path.insert` instead of `python3 -m linter`:** `.claude/scripts/lib/`
  has zero precedent for the `python3 -m` invocation pattern, and zero
  `PYTHONPATH` env var usage. `sys.path.insert(SCRIPTS_DIR)` matches the
  convention used by `derive_pages.py` and `stack_knowledge_audit.py`.
- **Why schema errors `SystemExit` instead of becoming findings:** typo'd
  rule keys are infrastructure errors, not coherence violations. The
  signal-to-noise ratio is wrong if they merge into the findings stream.

## Testing

| Test file | What it covers |
|-----------|----------------|
| `test_linter_parity.py` | Real-repo baseline matching, 3 synthetic fixtures (field_role_map, consumer_coverage, clean), AOC tag invariant. |
| `test_linter_validation.py` | The 5 schema-validation paths in PR3: unknown type, unknown type under `--warn-only`, unknown field, missing required, META_KEYS accepted. |
| `test_subsys_c_drift.py` | Subsystem C: X1 forward early-exit, X2 baseline parity, declared_drift fires/silent (6 cases). |
| `test_aoc_coherence_rules.py` | Existing AOC v1 R1/R2/R3 behavioral tests. |
| `test_field_role_map_rule.py` | Existing `field_role_map` behavioral tests. |
| `test_frontmatter_coherence.py` | Existing `frontmatter_artifact_consistency` (R4) behavioral tests. |

Run all: `bash .claude/scripts/tests/run-all.sh`.
