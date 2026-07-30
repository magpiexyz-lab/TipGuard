# EARC — Evidence-Anchored Repair Channel

> Contract for incomplete-state gates and writers across the template.
> Closes the failure mode reported in #1182 and #1189.

## Problem this contract solves

Gates and writers around incomplete-state are tempted to design only two
behaviors: happy path (allow) and deny. When the actor is wrong (the lead
needs to repair a sealed file; an agent crashed mid-flight and the lead
needs to record what was done), the lead is forced to either:

- **Bypass** — write the file via shell (`python -c`, `sed -i`, `cat >`)
  to evade the Edit/Write hook surface (#1182), or
- **Misclassify** — invoke the wrong writer to satisfy a validator that
  rejects the right one (#1189: writing a `recovery` trace as a
  `self-degraded` trace, falsifying provenance/status/verdict).

Both break the audit trail that auto-merge relies on as its review surface.

## The contract

> **Any write-blocking gate or writer must offer a third path: provide
> external evidence, invoke the canonical repair writer, get a `lead-fix`
> (or evidence-anchored `recovery`) trace stamped, gate ALSO-ALLOWs.**

Two stacked halves, applied per-instance:

### Half I — Self-validation at seal

A state writer that seals a no-rewrite window MUST self-check artifact
usability (compile/build/schema) BEFORE sealing. The seal artifact thus
becomes a usability attestation, not a presence attestation.

**Reference implementation**: `state-11-core-scaffold.md` runs `npm run
build` before writing `phase-a-sentinel.json`. The sentinel records
`build_passing: true` + `commit_sha`. PR #1204.

### Half II — Evidence-anchored repair channel

A gate/writer that would deny on a binary precondition MUST offer an
evidence-anchored alternative path:

1. A **canonical repair writer** validates external evidence
   (build-result.json, git diff, manifest) via the
   `validate_evidence` library.
2. The writer performs the operation atomically.
3. The writer stamps a `lead-fix` trace via `write-agent-trace.sh
   --provenance lead-fix`.
4. The writer leaves an attestation artifact (e.g.,
   `.runs/phase-a-repair-attestations/<basename>-<ts>.json`) with
   `evidence_validated: true`.
5. The gate reads the attestation and ALSO-ALLOWs subsequent writes
   matching the attested target while the attestation is fresh.

**Reference implementation (gate-side)**: `bootstrap/gates/write.sh`
ALSO-ALLOWs Phase A writes when a fresh validated attestation matches.
PR #1205.

**Reference implementation (writer-side)**: `write-recovery-trace.sh
--fixes-json --evidence-source` writes an evidence-anchored recovery
trace. Each fix is stamped `lead_transcribed: true`; trace gains
`lead_evidence_source`. `validate-recovery.sh` validates the evidence
before stamping `recovery_validated: true`. PR #1203.

### Bash-side guard

For each gate-side EARC instance, a complementary Bash PreToolUse hook
intercepts shell-side bypass attempts (`python -c`, `sed -i`, etc.) and
points the lead to the canonical repair writer. This closes the
**means** of bypass once the **motivation** is closed by Half II.

**Reference implementation**: `bootstrap-phase-a-write-guard.sh` ports
the 4-layer evasion catalogue from `agent-trace-write-guard.sh` —
chain delimiters, fd-redirect normalization, Python literal `open()`,
Python variable indirection — plus `pathlib.Path.write_text/bytes`,
`sed -i`, `perl -i`, `cp`, `mv`, `tee`, `cat heredoc`. PR #1205.

Bash-side guards ship in `MODE=warn` (telemetry-only) and flip to
`MODE=deny` after a one-week soak window with zero false positives.
This matches the proven PR3→PR4 hardening pattern from
`agent-trace-write-gate.sh`.

## Provenance choice

| Scenario | Provenance | Trace shape |
|---|---|---|
| Lead self-applies an in-flight fix (e.g., Phase A repair) | `lead-fix` | `lead_attestation: true`, non-empty `fixes[]`, no `recovery_validated` |
| Agent crashed; lead transcribes the recovery | `recovery` (preserved) | `status: abandoned`, `verdict: unresolved`, `fixes[].lead_transcribed: true`, `lead_evidence_source` |
| Agent succeeded but write was blocked; lead transcribed payload | `lead-on-behalf` | (existing AOC v1.1) `source` + `recovery_validated` |
| Agent never spawned; lead writes consistency marker | `lead-synthesized` | (existing AOC v1.1) `coverage_provider` + `no_fixes_claimed` |

The provenance enum is closed at AOC v1.1 with these seven values:
`self`, `self-degraded`, `recovery`, `lead-merge`, `lead-on-behalf`,
`lead-synthesized`, `lead-fix`. Adding a new value requires the
synchronized 5-layer update protocol (see
`agent-output-contract.md` "Versioning rules").

## Recurrence prevention

The `earc-gate-evidence-escape` coherence linter rule (in
`.claude/patterns/template-coherence-rules.json`) iterates
`gate-inventory.json`. Every gate with `earc_subpattern in {gate-side,
writer-side}` must offer a documented evidence-escape branch — either
inline (mention `attestation`, `EARC`, or `lead_evidence_source`) or
declared in `state-registry.repair_evidence`.

Severity: WARN (slice 1, ships during soak window). Flips to BLOCK in
slice 4 after one-week soak with zero new findings.

## Inventory

`.claude/patterns/gate-inventory.json` enumerates 49 gates classified
for EARC applicability. Two are EARC candidates (the ones reported);
47 are not applicable (verdict-pass-through gates have a built-in
evidence channel — the verdict file IS the evidence; input-schema
gates have no "no legal fix" pathology — the payload itself is the
bug).

## File map

```
Half I:
  .claude/skills/bootstrap/state-11-core-scaffold.md   (seal-time self-check)

Half II — gate-side (#1182):
  .claude/scripts/write-phase-a-repair.sh              (canonical repair writer)
  .claude/skills/bootstrap/gates/write.sh              (ALSO-ALLOW on attestation)
  .claude/hooks/bootstrap-phase-a-write-guard.sh       (Bash guard, WARN mode)

Half II — writer-side (#1189):
  .claude/scripts/write-recovery-trace.sh              (--fixes-json + --evidence-source)
  .claude/scripts/validate-recovery.sh                 (evidence-anchored stamping)

Shared primitive:
  .claude/scripts/lib/validate_evidence.py             (extracted library)

Coherence enforcement:
  .claude/patterns/gate-inventory.json                 (manifest)
  .claude/patterns/template-coherence-rules.json       (rule entry)
  .claude/scripts/lib/linter/runner.py                 (HANDLER)

Provenance writer:
  .claude/scripts/write-agent-trace.sh                 (--provenance lead-fix)

Documentation:
  .claude/patterns/agent-trace-protocol.md
  .claude/patterns/agent-output-contract.md
  .claude/agents/pattern-classifier.md                 (Q0a sub-class)
```

## Soak protocol (slice 4 → eventual flip)

To flip `MODE=warn` → `MODE=deny` for `bootstrap-phase-a-write-guard.sh`:

1. **Pre-flight**: `pytest .claude/scripts/tests/test_phase_a_forgery_surface.py`
   must be green in deny mode (the test suite invokes the hook with
   `BOOTSTRAP_PHASE_A_GUARD_MODE=deny` directly — independent of the
   live mode). CI runs this on every PR.
2. **Soak**: leave `MODE=warn` in production (default in
   `bootstrap-phase-a-write-guard.sh`) for at least one week.
3. **Audit**: inspect `.runs/hook-friction.jsonl` filtered to
   `hook == "bootstrap-phase-a-write-guard"`. Every entry should be a
   real bypass attempt, not a false positive on legitimate use.
4. **Flip**: change `MODE="${BOOTSTRAP_PHASE_A_GUARD_MODE:-warn}"` to
   `MODE="${BOOTSTRAP_PHASE_A_GUARD_MODE:-deny}"`. One-line change;
   revert is also one line if regression surfaces.

The same protocol applies to flipping `earc-gate-evidence-escape` from
`severity: warn` to `severity: block` in
`template-coherence-rules.json`.
