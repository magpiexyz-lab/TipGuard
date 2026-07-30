"""Helper utilities for state-registry VERIFY blocks.

#1379 G1 fix: write-gate-artifact.sh and the other canonical trace writers
stamp identity fields onto every artifact payload. VERIFY blocks that
iterate `d.values()` (e.g., `assert all(v in (True, 'skipped') for v in d.values())`)
incorrectly trip on the stamped string values — those are metadata, not
check values.

`unstamped_values(d)` returns the values from `d` excluding every field
stamped by ANY of the four canonical writers, so VERIFY blocks see only
the check payload.

## Stamped-field union by writer

Writer → fields stamped (identity + provenance metadata only; conditional
payload fields like 'fixes' are NOT in the union because they ARE check values).

- `.claude/scripts/lib/write-gate-artifact.sh` (line 113-115):
    {skill, run_id, written_at}

- `.claude/scripts/write-agent-trace.sh` (line 318-328 base + provenance branches):
    {agent, timestamp, status, provenance, run_id, skill, spawn_sha, spawn_index}
  + per-provenance metadata: {partial, source, coverage_provider, lead_attestation,
    source_run_id, source_skill, degraded_reason, recovery, recovery_validated,
    recovery_reason, epoch}

- `.claude/scripts/write-recovery-trace.sh` (line 336-376):
    {agent, timestamp, status, verdict, provenance, partial, lead_attestation,
     source_run_id, source_skill, checks_performed, degraded_reason, recovery,
     recovery_validated, recovery_reason, run_id, skill, spawn_sha, spawn_index}

- `.claude/scripts/write-skipped-fixer-trace.sh` (line 288-316):
    {agent, timestamp, status, verdict, result, provenance, lead_attestation,
     partial, checks_performed, upstream_evidence_path, reason,
     unresolved_critical, run_id, skill, spawn_sha, spawn_index}

The union below is the superset. When a writer adds a new identity stamp,
add it here AND update the corresponding writer's stamping block. The
recurrence guard `verify_d_values_against_stamped_artifact` (rule in
template-coherence-rules.json) flags state-registry VERIFY blocks using
raw `d.values()` against gate-stamped artifact paths — catches the next
writer addition that doesn't update this helper.

TODO(post-soak): replace hardcoded set with programmatic derivation by
parsing each writer's stamp block at import time. Deferred until drift is
observed in practice.
"""

STAMPED_FIELDS = frozenset({
    # write-gate-artifact.sh (3 fields)
    "skill", "run_id", "written_at",
    # write-agent-trace.sh base stamps (8 fields)
    "agent", "timestamp", "status", "provenance", "spawn_sha", "spawn_index",
    # NOTE: "skill" and "run_id" already in write-gate-artifact.sh row above
    # write-agent-trace.sh per-provenance stamps (selectively added by branches)
    "partial", "source", "coverage_provider", "lead_attestation",
    "source_run_id", "source_skill", "degraded_reason",
    "recovery", "recovery_validated", "recovery_reason", "epoch",
    # write-recovery-trace.sh additions (verdict + checks_performed are stamped
    # by the recovery writer as identity-of-recovery, not check values; the
    # recovery flow's check values live elsewhere)
    "verdict", "checks_performed",
    # write-skipped-fixer-trace.sh additions
    "result", "upstream_evidence_path", "reason", "unresolved_critical",
})


def unstamped_values(d):
    """Return values from `d` excluding canonical-writer identity/provenance stamps.

    Use in state-registry.json VERIFY blocks that iterate dict values to assert
    check-payload invariants. Replaces raw `d.values()` to keep stamped identity
    metadata out of the assertion surface.

    Example (state-13a bootstrap-design-validated.json VERIFY):
        before: assert all(v in (True, 'skipped') for v in d.values())
        after:  from verify_helpers import unstamped_values
                assert all(v in (True, 'skipped') for v in unstamped_values(d))
    """
    return [v for k, v in d.items() if k not in STAMPED_FIELDS]


def unstamped_items(d):
    """Same idea but returns (k, v) tuples — useful when you need the key
    in error messages."""
    return [(k, v) for k, v in d.items() if k not in STAMPED_FIELDS]
