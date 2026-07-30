#!/usr/bin/env python3
"""VERIFY helper for state-11c behavior contract audit (#1387).

Asserts:
  1. For web-app archetype: .runs/behavior-implementation-audit.json exists
  2. uncovered_count == 0 (no behavior contracts left unimplemented)
  3. audit.run_id matches bootstrap-context.json.run_id (no stale-audit drift)

Service/cli archetypes skip (no pages → no contract audit needed).

Exit 0 on pass; exit 1 (with stderr diagnostic) on fail.
"""
from __future__ import annotations
import json
import os
import sys


def main() -> int:
    ctx_path = ".runs/bootstrap-context.json"
    if not os.path.isfile(ctx_path):
        print(
            f"verify-state-11c-behavior-audit: SKIP "
            f"({ctx_path} absent — not in a bootstrap run)"
        )
        return 0
    try:
        ctx = json.load(open(ctx_path))
    except Exception as e:
        print(
            f"FAIL: cannot parse {ctx_path}: {e}", file=sys.stderr
        )
        return 1

    archetype = ctx.get("archetype", "web-app")
    if archetype != "web-app":
        print(
            f"verify-state-11c-behavior-audit: SKIP (archetype={archetype})"
        )
        return 0

    audit_path = ".runs/behavior-implementation-audit.json"
    if not os.path.exists(audit_path):
        print(
            f"FAIL: {audit_path} missing — state-11c post-fan-out must run "
            f"behavior_contract_auditor.py (#1387)",
            file=sys.stderr,
        )
        return 1

    try:
        audit = json.load(open(audit_path))
    except Exception as e:
        print(
            f"FAIL: cannot parse {audit_path}: {e}", file=sys.stderr
        )
        return 1

    uncovered = audit.get("uncovered_count", 0)
    if uncovered != 0:
        print(
            f"FAIL: behavior contract uncovered_count={uncovered} (#1387)",
            file=sys.stderr,
        )
        for u in (audit.get("uncovered") or [])[:10]:
            page = u.get("page", "?")
            kind = (u.get("contract") or {}).get("kind", "?")
            reason = u.get("reason", "")
            print(f"  - page={page} kind={kind} reason={reason}", file=sys.stderr)
        return 1

    ctx_run_id = ctx.get("run_id", "")
    audit_run_id = audit.get("run_id", "")
    if audit_run_id != ctx_run_id:
        print(
            f"FAIL: behavior-implementation-audit run_id drift: "
            f"audit={audit_run_id!r} vs context={ctx_run_id!r} (#1387)",
            file=sys.stderr,
        )
        return 1

    print(
        f"state-11c behavior-implementation-audit: OK "
        f"(audited={audit.get('audited_pages', 0)} "
        f"covered={audit.get('covered_static', 0)} "
        f"runtime_signaled={len(audit.get('runtime_check_signaled', []))})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
