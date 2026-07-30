"""Shared mode resolver for prose-gates infrastructure.

Closes #1449 / #1431 / #1433 root cause: PR-#1444 made `fail_mode` field
documentation-only (each gate-runner read its own env var with hard-coded
"warn" default). This helper makes the registry load-bearing INDIRECTLY via
a per-run snapshot taken at lifecycle-init time, while preserving each
gate's prior runtime default for legacy/in-flight contexts.

Resolution order (first match wins):
  1. PROSE_GATES_TOLERANT=1 env  → "warn" (universal escape)
  2. PROSE_GATE_<GATE_ID_UPPER_UNDERSCORED>_MODE env (per-gate override)
  3. .runs/<active-skill>-context.json.prose_gates_modes_snapshot[gate_id]
     (only when snapshot dict present AND
     snapshot_taken_at_version >= current registry _schema_version)
  4. prior_default (caller-passed; preserves each gate's existing default)

Note on registry: the registry's fail_mode field is consumed ONLY by
lifecycle-init.sh Step 5c when WRITING the snapshot. The helper does NOT
read registry.fail_mode directly — that would break in-flight safety for
runs whose context predates PR 1 (no snapshot field). Such runs fall
through to prior_default, preserving the runtime default each caller
passed historically (e.g., gate 5 callers pass "deny" preserving #1393
phase-2; gate 1 callers pass "warn" preserving Phase A).

Public API:

    resolve(gate_id: str, prior_default: str = "warn") -> str
        Returns "warn" or "deny". Raises ProseGateError if gate not in
        registry, or if registry has no fail_mode for this gate (binary gates
        like skill-yaml-mode should not invoke this helper).

CLI usage (called by prose_gate_mode.sh wrapper for bash callers):

    python3 prose_gate_mode.py <gate_id> [<prior_default>]
"""

from __future__ import annotations

import glob
import json
import os
import sys

__all__ = ["resolve", "ProseGateError"]

REGISTRY_PATH = ".claude/patterns/prose-gates.json"


class ProseGateError(Exception):
    """Raised for gate misconfiguration (unknown gate, missing fail_mode)."""


def _normalize_gate_id_to_env(gate_id: str) -> str:
    """`lead-synthesized-numerical-bounds` → `LEAD_SYNTHESIZED_NUMERICAL_BOUNDS`."""
    return gate_id.replace("-", "_").upper()


def _read_registry(path: str = REGISTRY_PATH) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        return json.load(open(path))
    except Exception:
        return None


def _registry_gate(reg: dict, gate_id: str) -> dict | None:
    for g in reg.get("gates", []) or []:
        if g.get("gate_id") == gate_id:
            return g
    return None


def _active_skill_context_path() -> str | None:
    """Return the path to the active (non-completed, latest-timestamp)
    skill context file, or None if none found."""
    best_path = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if f.endswith("/epilogue-context.json"):
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp", "") or ""
        if ts >= best_ts:
            best_path = f
            best_ts = ts
    return best_path


def _read_active_context() -> dict | None:
    p = _active_skill_context_path()
    if not p:
        return None
    try:
        return json.load(open(p))
    except Exception:
        return None


def _snapshot_value(ctx: dict | None, gate_id: str, current_version: int) -> str | None:
    """Return snapshotted fail_mode for gate_id when snapshot is present
    AND not stale (snapshot version >= current registry version).

    Stale snapshots (taken under older registry version) fall through to
    prior_default — this is the legacy in-flight safety path.
    """
    if not ctx:
        return None
    snap = ctx.get("prose_gates_modes_snapshot")
    if not isinstance(snap, dict):
        return None
    snap_version = ctx.get("prose_gates_modes_snapshot_at_version")
    if not isinstance(snap_version, int):
        return None
    if snap_version < current_version:
        return None
    val = snap.get(gate_id)
    if val in ("warn", "deny"):
        return val
    return None


def resolve(gate_id: str, prior_default: str = "warn") -> str:
    """Resolve effective fail_mode for the named gate. See module docstring."""
    if prior_default not in ("warn", "deny"):
        raise ProseGateError(
            f"prior_default must be 'warn' or 'deny', got {prior_default!r}"
        )

    # Step 1: universal tolerant escape.
    if os.environ.get("PROSE_GATES_TOLERANT", "0") == "1":
        return "warn"

    # Step 2: per-gate env var override.
    env_name = f"PROSE_GATE_{_normalize_gate_id_to_env(gate_id)}_MODE"
    env_val = os.environ.get(env_name, "").lower()
    if env_val in ("warn", "deny"):
        return env_val

    # Read registry once for steps 3 + 4.
    reg = _read_registry()
    current_version = (reg or {}).get("_schema_version", 0) if reg else 0

    # Verify gate exists in registry. Unknown gate is a configuration error.
    if reg is not None:
        gate = _registry_gate(reg, gate_id)
        if gate is None:
            raise ProseGateError(
                f"gate {gate_id!r} not found in {REGISTRY_PATH}"
            )
        # Binary gates (no fail_mode) should never reach the helper.
        if "fail_mode" not in gate and current_version >= 2:
            raise ProseGateError(
                f"gate {gate_id!r} has no fail_mode field — "
                f"caller should not invoke helper for binary gates "
                f"(enforcement_kind={gate.get('enforcement_kind')!r})"
            )

    # Step 3: snapshot from active skill context (registry-driven via
    # lifecycle-init.sh Step 5c). Skipped when snapshot is stale (older
    # registry version) or absent entirely — both paths preserve in-flight
    # safety by falling to prior_default.
    ctx = _read_active_context()
    snap_val = _snapshot_value(ctx, gate_id, current_version)
    if snap_val is not None:
        return snap_val

    # Step 4: caller-passed prior default. The helper deliberately does NOT
    # consult registry.fail_mode directly here — registry is only the
    # SOURCE for snapshots written by lifecycle-init.sh. Reading it here
    # would override prior_default for legacy contexts that have no
    # snapshot, breaking in-flight safety (round-1 critic Concern 3).
    return prior_default


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: prose_gate_mode.py <gate_id> [<prior_default>]",
            file=sys.stderr,
        )
        return 2
    gate_id = sys.argv[1]
    prior_default = sys.argv[2] if len(sys.argv) > 2 else "warn"
    try:
        print(resolve(gate_id, prior_default))
        return 0
    except ProseGateError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
