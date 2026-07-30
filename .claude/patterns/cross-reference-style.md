# Cross-Reference Style

When authoring cross-references between template files (`.claude/stacks`,
`.claude/skills`, `.claude/agents`, `.claude/patterns`, `.claude/templates`),
use **stable anchors** — never line numbers.

Line numbers rot silently when the referenced file is edited (a comment is
added, an import shifts, a refactor moves blocks). Reviewers don't notice
the drift; downstream contributors follow the stale pointer to the wrong
content. There is no automated check for the reference at write-time, so the
class-level prevention is **don't write line numbers in cross-references**.

This file is the canonical convention doc for the
`markdown_cross_file_line_reference` rule (issue #1238) declared in
`.claude/patterns/template-coherence-rules.json`.

## The Two Acceptable Forms

### 1. Section anchor

A markdown heading is a stable anchor — it survives line shifts and
reorderings as long as the heading text doesn't change.

```
[link text](path/to/file.md#heading-anchor)
```

Example:

```
See state-3b-quality-gate.md#archetype-gate for the gate semantics.
```

The anchor is derived from the heading text (lowercase, spaces → dashes,
strip punctuation). Verify the heading exists at the time of writing.

### 2. Code-search anchor

When the target file lacks a structural anchor (e.g., a script with no
sections, or you want to point at a specific function/symbol), use a
search-for-symbol anchor:

```
path/to/file.py: search for SYMBOL_OR_PHRASE
```

Example:

```
The merge logic lives in merge-design-critic-traces.py: search for
"boundary-skip excludes source-only/unknown unresolved-forcing".
```

The phrase should be unique enough to grep for, but not so long that small
edits break it.

## What Not To Do

These forms are flagged by the
`markdown_cross_file_line_reference` rule and rejected at finalize time:

<!-- coherence-allow: line-number-cross-reference: anti-pattern documentation -->
```
merge-design-critic-traces.py L121-138        # rotting range reference
state-3b-quality-gate.md (lines 7-31)         # parenthesized line range
the same filter at lines 38-42                # same-file line range (no path)
on line 79 already uses ...                   # bare "on line N"
```
<!-- coherence-allow: line-number-cross-reference: anti-pattern documentation -->

Each form will rot the next time the referenced file is edited.

## Pragma Escape Hatch

For legitimate cases where a line-number reference is genuinely stable —
typically scaffold-instruction text describing the line numbers of an
embedded code block, or a citation of an external resource (a stable RFC
section, a stack-emitted source line) — silence the rule with a pragma:

```html
<!-- coherence-allow: line-number-cross-reference: <reason> -->
```

Place the pragma on the same line as the reference, or on the line
immediately above or below. The pragma must include a brief reason so
reviewers can audit whether the suppression remains warranted.

Example uses (all currently committed in `.claude/stacks/auth/supabase.md`):

<!-- coherence-allow: line-number-cross-reference: pragma usage example -->
```
Replace the import on line 5:
<!-- coherence-allow: line-number-cross-reference: refers to embedded code block above -->
```

## Migration Examples

In-PR migrations performed alongside this rule's introduction:

<!-- coherence-allow: line-number-cross-reference: anti-pattern column documents the form being replaced -->

| Before | After |
|---|---|
| `merge-design-critic-traces.py L121-138` | `merge-design-critic-traces.py: search for "boundary-skip excludes source-only/unknown unresolved-forcing"` |
| `state-3b-quality-gate.md L7-31` | `state-3b-quality-gate.md#archetype-gate` |
| `loadStripe fallback on line 79 already uses` | `loadStripe fallback near the top of this file already uses` |
| `the same filter at lines 38-42` | `the same filter described in the **Stage 1 boundary derivation** section above` |
<!-- coherence-allow: line-number-cross-reference: end of anti-pattern column block -->


## Pattern Maintenance

When the rule fires on a new instance:

1. Prefer migration to a stable anchor (section or search-symbol).
2. If the reference is genuinely line-stable (frontmatter slot, embedded
   code block, external citation), use the pragma with a clear reason.
3. Do not introduce new line-number references — the rule blocks them at
   day-1 severity.

When the rule false-positives (e.g., on prose like "Description line 1"
that is content rather than a reference):

1. The qualifier regex is intentionally narrow — it requires a strong
   citation signal (parenthesized form, range, or `on line` connector).
2. If a real false-positive escapes that filter, refine the regex in
   `.claude/scripts/lib/linter/runner.py:check_markdown_cross_file_line_reference`
   and add a fixture to
   `.claude/scripts/tests/test_markdown_cross_file_line_reference.py`.
