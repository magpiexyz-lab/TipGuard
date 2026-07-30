#!/usr/bin/env python3
"""Validate lead-synthesized trace numerical claims against coverage_provider bounds.

Consumed by `.claude/hooks/bound-by-coverage-provider-gate.sh` (PreToolUse:Bash
matcher on `write-agent-trace.sh --provenance lead-synthesized`).

Algorithm:
  1. Load prose-gates.json, find gate `lead-synthesized-numerical-bounds`.
  2. Resolve per-agent bound_semantics; fall back to `_default` defense-in-depth.
  3. Match waiver by (skill, state_id, agent, coverage_provider).
  4. Read coverage_provider artifact; compute bounded universes.
  5. Evaluate constraints; collect violations.
  6. On violation: append to .runs/lead-deviation-log.jsonl with
     deviation_type=artifact-fabrication and gate_layer=prose-gates-v1;
     emit reason to stderr; exit 1.

Defense-in-depth: when `_default` semantics apply (agent not in registry),
require all numerical fields == 0 AND no_fixes_claimed == true. Catches
unknown future agents.

Usage:
    python3 bound-by-coverage-provider.py --command "<normalized-bash-cmd>"
    python3 bound-by-coverage-provider.py --trace-payload @path/to/trace.json
    python3 bound-by-coverage-provider.py --trace-payload '{"agent":"...",...}'
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shlex
import sys
from typing import Any

PROSE_GATES_PATH = ".claude/patterns/prose-gates.json"
DEVIATION_LOG_PATH = ".runs/lead-deviation-log.jsonl"
GATE_ID = "lead-synthesized-numerical-bounds"
# Gate verify-state-3a-stage0-design-critic: when coverage_provider proves
# Stage 0 fast-path, the lead-synthesized trace MUST carry auto_trigger_evidence
# matching either a sha:<40hex> marker (auto-trigger fired) or
# marker:legitimate-bypass:<>=40 chars> (explicit lead override).
AUTO_TRIGGER_EVIDENCE_RE = re.compile(
    r"^(sha:[0-9a-f]{40}|marker:legitimate-bypass:.{40,})$"
)


def _load_registry(path: str) -> dict:
    return json.load(open(path))


def _find_gate(registry: dict, gate_id: str) -> dict | None:
    for g in registry.get("gates", []):
        if g.get("gate_id") == gate_id:
            return g
    return None


def _active_run_id() -> str:
    """Detect active skill run_id from .runs/*-context.json (latest, not completed)."""
    import glob
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if "epilogue" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp", "") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("run_id", "")


def _active_skill_state() -> tuple[str, str]:
    """Return (skill, state_id) for the active run."""
    import glob
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if "epilogue" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp", "") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    if not best:
        return "", ""
    skill = best.get("skill", "")
    completed = best.get("completed_states", []) or []
    state_id = str(completed[-1]) if completed else ""
    return skill, state_id


def _log_deviation(payload: dict) -> None:
    """Append a single line to .runs/lead-deviation-log.jsonl via shared
    atomic appender. On exception → write-failures.jsonl (observer-visible).
    Closes #1431 reliability gap."""
    sys.path.insert(0, os.path.dirname(__file__))
    from append_deviation_log import append
    append(payload)


def _extract_trace_from_command(command: str) -> dict | None:
    """Extract the --json payload from a write-agent-trace.sh bash invocation.

    Handles both `--json '<json>'` and `--json "$(...)"`. Returns parsed dict,
    or None if no parseable payload found.
    """
    if not command:
        return None
    # Try shlex split to get the --json argument value
    try:
        tokens = shlex.split(command, posix=True)
    except Exception:
        return None
    for i, tok in enumerate(tokens):
        if tok == "--json" and i + 1 < len(tokens):
            val = tokens[i + 1]
            try:
                return json.loads(val)
            except Exception:
                continue
        if tok.startswith("--json="):
            val = tok[len("--json="):]
            try:
                return json.loads(val)
            except Exception:
                continue
    return None


def _extract_coverage_provider_arg(command: str) -> str:
    """Extract --coverage-provider arg from the bash command (sibling to --json)."""
    if not command:
        return ""
    try:
        tokens = shlex.split(command, posix=True)
    except Exception:
        return ""
    for i, tok in enumerate(tokens):
        if tok == "--coverage-provider" and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok.startswith("--coverage-provider="):
            return tok[len("--coverage-provider="):]
    return ""


def _extract_agent_arg(command: str) -> str:
    """Extract the agent name (first positional arg to write-agent-trace.sh)."""
    if not command:
        return ""
    try:
        tokens = shlex.split(command, posix=True)
    except Exception:
        return ""
    # Find the script invocation, return the next non-flag positional
    for i, tok in enumerate(tokens):
        if tok.endswith("write-agent-trace.sh"):
            for next_tok in tokens[i + 1:]:
                if not next_tok.startswith("-"):
                    return next_tok
            break
    return ""


def _waiver_matches(waivers: list[dict], skill: str, state_id: str,
                    agent: str, coverage_provider: str) -> bool:
    for w in waivers or []:
        if w.get("skill") not in (skill, "*"):
            continue
        if w.get("state_id") not in (state_id, "*"):
            continue
        agents = w.get("agents") or []
        if agents and agent not in agents:
            continue
        cp = w.get("coverage_provider")
        if cp and cp != coverage_provider:
            continue
        return True
    return False


def _check_default_bounds(trace: dict) -> list[str]:
    """Defense-in-depth: all numerical fields == 0 AND no_fixes_claimed:true."""
    violations: list[str] = []
    no_fixes = trace.get("no_fixes_claimed")
    if no_fixes is not True:
        violations.append("_default rule: no_fixes_claimed must be true")
    # Scan top-level numerical fields
    for k, v in trace.items():
        if k in ("verdict", "result", "agent", "provenance", "coverage_provider",
                 "no_fixes_claimed", "checks_performed", "fixes", "timestamp",
                 "run_id", "skill", "spawn_index", "head_sha", "spawn_sha",
                 "written_at"):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if v != 0:
                violations.append(f"_default rule: field {k!r}={v} must be 0")
    return violations


def _read_coverage_provider(path: str) -> dict | None:
    try:
        return json.load(open(path))
    except Exception:
        return None


def _check_auto_trigger_evidence(trace: dict, fast_path: bool) -> list[str]:
    """Gate verify-state-3a-stage0-design-critic: when Stage 0 fast-path fired,
    the lead-synthesized trace MUST carry auto_trigger_evidence matching
    sha:<40hex> OR marker:legitimate-bypass:<>=40 chars>. Outside Stage 0
    fast-path, the field is optional (regular lead-synthesized writes don't
    need it).
    """
    if not fast_path:
        return []
    ate = trace.get("auto_trigger_evidence")
    if not ate:
        return [
            "auto_trigger_evidence missing — Stage 0 fast-path requires "
            "sha:<40hex> OR marker:legitimate-bypass:<>=40 chars> "
            "(prose-gate verify-state-3a-stage0-design-critic)"
        ]
    if not AUTO_TRIGGER_EVIDENCE_RE.match(str(ate)):
        return [
            f"auto_trigger_evidence={ate!r} does not match pattern "
            r"^(sha:[0-9a-f]{40}|marker:legitimate-bypass:.{40,})$"
        ]
    return []


def _check_design_critic(trace: dict, cp: dict | None) -> list[str]:
    """Bound design-critic lead-synthesized numerical claims.

    When coverage_provider proves all-pages-fast-path (PR_RELEVANT=0), all
    numerical fields collapse to a single legitimate state: pages_reviewed ==
    pages == len(page_set), min_score >= 10, sections_below_8 == 0,
    unresolved_sections == 0, unresolved_shared == 0, fixes_applied == 0.
    Also enforces auto_trigger_evidence pattern (gate
    verify-state-3a-stage0-design-critic).
    """
    if cp is None:
        return ["coverage_provider artifact unreadable or missing"]
    page_set = cp.get("page_set") or []
    page_count = len(page_set)
    pr_relevant = cp.get("pr_relevant", cp.get("PR_RELEVANT"))
    all_pages_fast_path = (pr_relevant in (0, "0", False) or
                           cp.get("all_pages_fast_path") is True)

    v: list[str] = []
    pages = trace.get("pages")
    pages_reviewed = trace.get("pages_reviewed")
    min_score = trace.get("min_score")
    sections_below_8 = trace.get("sections_below_8", 0)
    unresolved_sections = trace.get("unresolved_sections", 0)
    unresolved_shared = trace.get("unresolved_shared", 0)
    fixes_applied = trace.get("fixes_applied", 0)

    if pages is not None and pages > page_count:
        v.append(f"pages={pages} > coverage_provider.page_set length {page_count}")
    if pages_reviewed is not None and pages_reviewed > page_count:
        v.append(f"pages_reviewed={pages_reviewed} > coverage_provider.page_set length {page_count}")
    if all_pages_fast_path:
        if min_score is not None and min_score < 10:
            v.append(f"min_score={min_score} < 10 (all-pages-fast-path requires >=10)")
        if sections_below_8 != 0:
            v.append(f"sections_below_8={sections_below_8} != 0 (all-pages-fast-path)")
        if unresolved_sections != 0:
            v.append(f"unresolved_sections={unresolved_sections} != 0 (all-pages-fast-path)")
        if unresolved_shared != 0:
            v.append(f"unresolved_shared={unresolved_shared} != 0 (all-pages-fast-path)")
        if fixes_applied != 0:
            v.append(f"fixes_applied={fixes_applied} != 0 (all-pages-fast-path; no per-page agent ran)")
    # Gate verify-state-3a-stage0-design-critic
    v.extend(_check_auto_trigger_evidence(trace, all_pages_fast_path))
    return v


def _check_design_consistency_checker(trace: dict, cp: dict | None) -> list[str]:
    """Bound design-consistency-checker.inconsistent_count. Same Stage 0
    auto_trigger_evidence requirement as design-critic when fast-path fires.
    """
    if cp is None:
        return ["coverage_provider artifact unreadable or missing"]
    inconsistent_count = trace.get("inconsistent_count", 0)
    pr_relevant = cp.get("pr_relevant", cp.get("PR_RELEVANT"))
    all_pages_fast_path = (pr_relevant in (0, "0", False) or
                           cp.get("all_pages_fast_path") is True)
    v: list[str] = []
    if all_pages_fast_path and inconsistent_count != 0:
        v.append(f"inconsistent_count={inconsistent_count} != 0 (all-pages-fast-path)")
    # Gate verify-state-3a-stage0-design-critic (same field requirement)
    v.extend(_check_auto_trigger_evidence(trace, all_pages_fast_path))
    return v


PER_AGENT_CHECKERS = {
    "design-critic": _check_design_critic,
    "design-consistency-checker": _check_design_consistency_checker,
}


def evaluate(trace: dict, coverage_provider: str, skill: str, state_id: str,
             registry_path: str = PROSE_GATES_PATH) -> tuple[bool, list[str]]:
    """Return (passed, violations) for a single lead-synthesized trace."""
    if not os.path.isfile(registry_path):
        return True, []  # Fail-open if registry missing (e.g., fresh checkout)
    registry = _load_registry(registry_path)
    gate = _find_gate(registry, GATE_ID)
    if not gate:
        return True, []

    agent = trace.get("agent", "")
    coverage_provider = coverage_provider or trace.get("coverage_provider", "")

    if _waiver_matches(gate.get("waivers") or [], skill, state_id, agent,
                       coverage_provider):
        # Waiver matches → still apply per-agent semantics (waiver is not blanket allow).
        pass

    bound_sem = gate.get("bound_semantics") or {}
    cp_data = None
    if coverage_provider:
        cp_data = _read_coverage_provider(coverage_provider)

    if agent in bound_sem and agent in PER_AGENT_CHECKERS:
        violations = PER_AGENT_CHECKERS[agent](trace, cp_data)
    else:
        # Unknown agent → defense-in-depth.
        violations = _check_default_bounds(trace)

    return (len(violations) == 0, violations)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--command", help="Normalized bash command containing write-agent-trace.sh invocation")
    ap.add_argument("--trace-payload", help="JSON string OR @path/to/file for the trace payload")
    ap.add_argument("--registry", default=PROSE_GATES_PATH)
    args = ap.parse_args()

    trace: dict | None = None
    coverage_provider = ""

    if args.command:
        trace = _extract_trace_from_command(args.command)
        coverage_provider = _extract_coverage_provider_arg(args.command)
        if not trace:
            # The hook may invoke this even when --json is not yet visible
            # (e.g., heredoc preamble); fail-open.
            return 0
        agent_arg = _extract_agent_arg(args.command)
        if agent_arg and not trace.get("agent"):
            trace["agent"] = agent_arg
    elif args.trace_payload:
        raw = args.trace_payload
        if raw.startswith("@"):
            raw = open(raw[1:]).read()
        trace = json.loads(raw)
    else:
        print("Either --command or --trace-payload required", file=sys.stderr)
        return 2

    if not trace:
        return 0  # Nothing to validate

    # Only enforce when provenance is lead-synthesized.
    if trace.get("provenance") not in ("lead-synthesized", None):
        return 0
    # If provenance is missing AND we're called from the bash hook, the command
    # matcher already filtered for --provenance lead-synthesized, so treat
    # missing provenance as implied lead-synthesized.

    skill, state_id = _active_skill_state()

    passed, violations = evaluate(trace, coverage_provider, skill, state_id,
                                  args.registry)
    if passed:
        return 0

    # Log to deviation log.
    log_entry = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": _active_run_id(),
        "skill": skill,
        "state_id": state_id,
        "gate_id": GATE_ID,
        "gate_layer": "prose-gates-v1",
        "deviation_type": "artifact-fabrication",
        "evidence": {
            "agent": trace.get("agent", ""),
            "coverage_provider": coverage_provider,
            "violated_fields": violations,
        },
        "auto_filed": False,
    }
    _log_deviation(log_entry)

    print(json.dumps({"violated_fields": violations,
                      "reason": "; ".join(violations)}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
