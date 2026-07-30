#!/usr/bin/env python3
"""Enumerate retrospective filing CANDIDATES from runtime evidence.

Issue context: #1276 — retrospective filing failed 5 times because lead
self-judgment under turn-budget pressure skipped real findings. This
script produces a SUPERSET of fileable candidates from existing runtime
artifacts (which the LLM cannot fabricate). Lead retains semantic judgment
over each candidate but cannot silently drop them — every candidate must
either be filed (via file-retrospective-finding.py) or explicitly suppressed
in retrospective-result.json with a closed-enum reason.

Inputs (all optional; missing → no candidates from that source):
  .runs/agent-spawn-log.jsonl           — agent spawn provenance
  .runs/hook-friction-summary.json      — aggregated hook denial counts
  .runs/fix-ledger.jsonl                — fix log entries (template-edit rows)
  .runs/template-coherence-cache.json   — cross-file coherence findings
  .runs/agent-traces/*.json             — agent workarounds[] + template_gap_observed[] (#1470), recovery/sparse shapes (#1468/#1456 OARC)
  .runs/verify-recheck.json             — verify-state failures (#1470)
  .runs/lead-deviation-log.jsonl        — prose-gate deviations
  .runs/image-candidates.json + page-image-map.json — sidecars for recovery-path-skip suppression (#1468)

Output: .runs/retrospective-pending-findings.json
  {
    "run_id": "<...>",
    "schema_version": 2,
    "generated_at": "<ISO>",
    "candidates": [
      {
        "candidate_id": "<sha256[:12] hash of (kind, key)>",
        "kind": "hook-friction" | "template-edit" | "coherence-finding" | "agent-recovery"
              | "agent-workaround" | "trace-overwrite" | "verify-failure"
              | "lead-deviation" | "log-write-failure"
              | "recovery-path-skip" | "sparse-trace",
        "confidence": "high" | "medium" | "low",
        "key": "<canonical identifier — used for dedup>",
        "evidence": {<source-specific fields>},
        "source_files": ["<path>"]
      }
    ]
  }

Confidence rubric (programmatic 3-condition test approximation):
  HIGH:   hook-friction with count >= 3 AND distinct hook (proven recurring)
          OR template-edit row with kind=template-edit (lead patched template)
          OR coherence-finding category=cross_file_contradiction
          OR verify-failure (any failed verify state)
          OR recovery-path-skip / sparse-trace (OARC #1468/#1456 — fallback
             writer produced schema-valid but depth-incomplete artifact)
  MEDIUM: agent-recovery (recovery_validated=true but recovery happened)
          OR hook-friction with count 1-2 (one-off but still informative)
  LOW:    any uncategorized signal (lead must triage)

Lead reconciles in retrospective-result.json:
  - file via file-retrospective-finding.py → candidate_id appears in
    .runs/retrospective-filed-findings.json
  - suppress via "suppressions": [{candidate_id, reason: <enum>, ...}]
    in retrospective-result.json

validate-retrospective-completeness.py asserts every candidate has one
disposition.

Fail-open: missing inputs OR parse errors → empty candidate list, exit 0.
This script is a candidate generator, not a gate.
"""

from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import sys
from typing import Any


def _active_run_id() -> str:
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
        ts = d.get("timestamp") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("run_id", "")


def _hash_key(kind: str, key: str) -> str:
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()[:12]


def _candidates_from_hook_friction(rid: str) -> list[dict]:
    path = ".runs/hook-friction-summary.json"
    if not os.path.isfile(path):
        return []
    try:
        data = json.load(open(path))
    except Exception:
        return []

    if rid and data.get("run_id") != rid:
        # Summary is for a different run (or unscoped: run_id null/empty) —
        # defensive, since the aggregator already scopes; treat as empty
        # rather than incorrect. #1895: an empty/null summary run_id must NOT
        # slip past this guard — a stale unscoped summary would mint
        # high-confidence candidates from other runs' friction.
        return []

    out: list[dict] = []
    hooks = data.get("hooks") or {}
    for hook_name, info in hooks.items():
        count = int(info.get("count") or 0)
        if count <= 0:
            continue
        confidence = "high" if count >= 3 else "medium"
        key = f"hook:{hook_name}"
        out.append({
            "candidate_id": _hash_key("hook-friction", key),
            "kind": "hook-friction",
            "confidence": confidence,
            "key": key,
            "evidence": {
                "hook": hook_name,
                "count": count,
                "sample_reasons": info.get("sample_reasons") or [],
            },
            "source_files": [path],
        })
    return out


def _candidates_from_template_edits(rid: str) -> list[dict]:
    path = ".runs/fix-ledger.jsonl"
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    seen_keys: set[str] = set()
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if rid and row.get("run_id") and row.get("run_id") != rid:
                    continue
                if row.get("entry_type") != "template-edit":
                    continue
                target = row.get("target_file") or row.get("file") or ""
                if not target:
                    continue
                key = f"template-edit:{target}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append({
                    "candidate_id": _hash_key("template-edit", key),
                    "kind": "template-edit",
                    "confidence": "high",
                    "key": key,
                    "evidence": {
                        "target_file": target,
                        "summary": (row.get("summary") or "")[:200],
                    },
                    "source_files": [path],
                })
    except Exception:
        pass
    return out


def _candidates_from_coherence_findings(_rid: str) -> list[dict]:
    path = ".runs/template-coherence-cache.json"
    if not os.path.isfile(path):
        return []
    try:
        data = json.load(open(path))
    except Exception:
        return []

    out: list[dict] = []
    seen_keys: set[str] = set()
    findings = data.get("findings") or {}
    for category, items in findings.items():
        if not isinstance(items, list):
            continue
        for f in items:
            if not isinstance(f, dict):
                continue
            rule_id = f.get("rule_id") or f.get("id") or ""
            target = f.get("file") or f.get("target") or ""
            key = f"coherence:{category}:{rule_id}:{target}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            confidence = "high" if category == "cross_file_contradiction" else "medium"
            out.append({
                "candidate_id": _hash_key("coherence-finding", key),
                "kind": "coherence-finding",
                "confidence": confidence,
                "key": key,
                "evidence": {
                    "category": category,
                    "rule_id": rule_id,
                    "target": target,
                    "message": (f.get("message") or "")[:200],
                },
                "source_files": [path],
            })
    return out


def _candidates_from_agent_recoveries(rid: str) -> list[dict]:
    """Agent traces with recovery_validated=true are candidates (medium)."""
    out: list[dict] = []
    for tf in glob.glob(".runs/agent-traces/*.json"):
        try:
            data = json.load(open(tf))
        except Exception:
            continue
        if rid and data.get("run_id") and data.get("run_id") != rid:
            continue
        prov = data.get("provenance") or ""
        recovery = data.get("recovery_validated")
        if prov != "recovery" and not recovery:
            continue
        agent = data.get("agent") or os.path.basename(tf).replace(".json", "")
        key = f"recovery:{agent}"
        out.append({
            "candidate_id": _hash_key("agent-recovery", key),
            "kind": "agent-recovery",
            "confidence": "medium",
            "key": key,
            "evidence": {
                "agent": agent,
                "provenance": prov,
                "recovery_validated": recovery,
                "degraded_reason": data.get("degraded_reason"),
            },
            "source_files": [tf],
        })
    return out


def _candidates_from_trace_overwrites(rid: str) -> list[dict]:
    """5th candidate source (#1335): trace-overwrite candidates from
    detect-trace-overwrites.py.

    Runs the detector first (idempotent, fail-open), then merges its
    candidates here. The detector flags 2+ spawns of the same agent within
    a single run_id when the agent is NOT in
    .claude/patterns/sanctioned-respawn-flows.json — OR when sanctioned but
    its precondition (e.g., solve-critic round-2 requires the round-1
    sidecar to exist with round=1) is unmet.
    """
    import subprocess
    try:
        subprocess.run(
            ["python3", ".claude/scripts/detect-trace-overwrites.py"],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass
    path = ".runs/trace-overwrite-candidates.json"
    if not os.path.isfile(path):
        return []
    try:
        data = json.load(open(path))
    except Exception:
        return []
    return data.get("candidates", [])


def _candidates_from_lead_deviations(rid: str) -> list[dict]:
    """6th candidate source (#1431): lead-deviation entries from append-only
    .runs/lead-deviation-log.jsonl.

    Closes prose-gate `lead-synthesized-numerical-bounds` enumerator blindness:
    the existing 5 channels only see trace-leaving artifacts; this channel
    surfaces manual-write bypasses logged by prose-gate validators (with
    gate_layer:prose-gates-v1 attribution for E2E falsification).

    Emits one candidate per (gate_id, deviation_type, expected_artifact) key
    from entries with auto_filed=false from the current run window.
    """
    path = ".runs/lead-deviation-log.jsonl"
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if rid and row.get("run_id") and row.get("run_id") != rid:
                    continue
                if row.get("auto_filed") is True:
                    continue
                gate_id = row.get("gate_id") or ""
                dev_type = row.get("deviation_type") or ""
                ev = row.get("evidence") or {}
                key = (
                    f"deviation:{gate_id}:{dev_type}:"
                    f"{ev.get('expected_artifact', '')}"
                )
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "candidate_id": _hash_key("lead-deviation", key),
                    "kind": "lead-deviation",
                    "confidence": "high",
                    "key": key,
                    "evidence": {
                        "gate_id": gate_id,
                        "gate_layer": row.get("gate_layer") or "prose-gates-v1",
                        "deviation_type": dev_type,
                        "evidence": ev,
                    },
                    "source_files": [path],
                })
    except Exception:
        return []
    return out


def _candidates_from_log_write_failures(rid: str) -> list[dict]:
    """7th candidate source: silent appender failures from
    .runs/lead-deviation-log.write-failures.jsonl. HIGH-confidence by default
    — silent failures are always actionable (the deviation log is the single
    source of observability for prose-gate behavior; silent writes break
    everything downstream). Closes #1431 reliability gap."""
    path = ".runs/lead-deviation-log.write-failures.jsonl"
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                exc = row.get("exception", "") or ""
                # Dedupe by exception class+message prefix; same root cause
                # across runs collapses to one finding.
                key = f"log-write-failure:{exc[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "candidate_id": _hash_key("log-write-failure", key),
                    "kind": "log-write-failure",
                    "confidence": "high",
                    "key": key,
                    "evidence": {
                        "exception": exc,
                        "ts": row.get("ts"),
                        "original_payload_gate_id": (
                            row.get("original_payload", {}).get("gate_id", "")
                            if isinstance(row.get("original_payload"), dict) else ""
                        ),
                    },
                    "source_files": [path],
                })
    except Exception:
        return []
    return out


def _candidates_from_agent_workarounds(rid: str) -> list[dict]:
    """GECR #1470 — enumerate workarounds[] + template_gap_observed[] from
    every agent trace as candidates.

    Schema in agent-output-contract.md §135-173 (AOC v1.3): all 32 trace-
    writing agents emit `workarounds[]` and `template_gap_observed[]` with
    empty-array default. Non-empty entries are friction signals — the agent
    couldn't proceed without papering over a deeper issue. These have been
    inert candidate sources since #1449 because enumerate-pending was never
    extended to consume them.

    Skip entries where `root_cause_unresolved == False` (Plan-Agent-B
    Concern 7: explicit self-resolved workaround should not surface).

    Dedup key collapses paraphrasing across agents touching the same
    (file, line, type) location (Plan-Agent-B Concern 6).
    """
    out: list[dict] = []
    seen_keys: set[str] = set()
    try:
        traces = glob.glob(".runs/agent-traces/*.json")
    except Exception:
        return []

    for trace_path in traces:
        try:
            with open(trace_path) as fh:
                trace = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue

        if rid and trace.get("run_id") and trace.get("run_id") != rid:
            continue

        agent_name = trace.get("agent") or os.path.basename(trace_path)

        # workarounds[]
        workarounds = trace.get("workarounds") or []
        if isinstance(workarounds, list):
            for entry in workarounds:
                if not isinstance(entry, dict):
                    continue
                if entry.get("root_cause_unresolved") is False:
                    # Explicit self-resolved — skip
                    continue
                file = entry.get("file") or ""
                line = entry.get("line", 0)
                type_ = entry.get("type") or ""
                description = (entry.get("description") or "")[:200]
                if not file and not description:
                    continue
                key = (
                    f"agent-workarounds:{file}:{line}:{type_}:"
                    f"{description[:80].lower().strip()}"
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                # Confidence: high when explicitly flagged unresolved;
                # low when absent (defensive default — flag for triage)
                confidence = (
                    "high" if entry.get("root_cause_unresolved") is True else "low"
                )
                out.append({
                    "candidate_id": _hash_key("agent-workarounds", key),
                    "kind": "agent-workaround",
                    "confidence": confidence,
                    "key": key,
                    "evidence": {
                        "file": file,
                        "line": line,
                        "type": type_,
                        "description": description,
                        "agent": agent_name,
                        "root_cause_unresolved": entry.get("root_cause_unresolved"),
                    },
                    "source_files": [trace_path],
                })

        # template_gap_observed[]
        gaps = trace.get("template_gap_observed") or []
        if isinstance(gaps, list):
            for entry in gaps:
                if not isinstance(entry, dict):
                    continue
                template_path = entry.get("template_path") or ""
                section = entry.get("section") or ""
                observation = (entry.get("observation") or "")[:200]
                if not template_path and not observation:
                    continue
                key = (
                    f"agent-template-gap:{template_path}:{section}:"
                    f"{observation[:80].lower().strip()}"
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append({
                    "candidate_id": _hash_key("agent-template-gap", key),
                    "kind": "agent-workaround",  # share kind for downstream consumers
                    "confidence": "high",
                    "key": key,
                    "evidence": {
                        "template_path": template_path,
                        "section": section,
                        "observation": observation,
                        "suggested_remediation": (
                            entry.get("suggested_remediation") or ""
                        )[:200],
                        "agent": agent_name,
                    },
                    "source_files": [trace_path],
                })
    return out


def _candidates_from_verify_failures(rid: str) -> list[dict]:
    """GECR #1470 — enumerate verify-recheck failed states as candidates.

    Per-state granularity (Plan-Agent-B Concern 4). Dedup key uses state +
    hash(error) so a rerun-that-still-fails collapses to the same candidate
    but a transient flake (re-run passes) does not propagate.
    """
    path = ".runs/verify-recheck.json"
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    # Tolerate missing run_id; filter only when both present
    if rid and data.get("run_id") and data.get("run_id") != rid:
        return []

    verify_results = data.get("verify_results") or []
    if not isinstance(verify_results, list):
        return []

    out: list[dict] = []
    seen_keys: set[str] = set()
    for row in verify_results:
        if not isinstance(row, dict):
            continue
        if row.get("passed") is not False:
            continue
        state = str(row.get("state") or row.get("name") or "").strip()
        error = str(row.get("error") or "")
        if not state and not error:
            continue
        # Deterministic dedup: state + first 80 chars of canonicalized error
        error_norm = error[:80].strip()
        key = f"verify-failure:{state}:{error_norm}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({
            "candidate_id": _hash_key("verify-failure", key),
            "kind": "verify-failure",
            "confidence": "high",
            "key": key,
            "evidence": {
                "state": state,
                "error": error[:300],
            },
            "source_files": [path],
        })
    return out


def _candidates_from_recovery_skips(rid: str) -> list[dict]:
    """GECR #1468 — enumerate fallback-shape skip events as candidates.

    Mirrors `_candidates_from_agent_workarounds` shape. Detects agent traces
    where provenance ∈ {self-degraded, recovery, lead-orchestrated} AND
    partial=true AND a non-sanctioned degraded_reason AND a domain-specific
    skipped check is detectable (landing context: candidates_tried==0 with
    unused sidecar candidates; non-landing has_images=true:
    image_issues_for_landing key missing).

    Suppression sources:
      - `.claude/scripts/lib/sanctioned_degraded_reasons.py` canonical list
        (empty-boundary-fast-path, demo-mode-fixture-short-circuit,
        redirect-source-only).

    OARC (Observation-Anchored Recovery Contract) sibling of EARC (#1189):
    fallback traces must either carry full schema with real data OR appear
    as a candidate here that the lead files or suppresses.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    try:
        from sanctioned_degraded_reasons import SANCTIONED_DEGRADED_REASONS
    except ImportError:
        SANCTIONED_DEGRADED_REASONS = frozenset()
    image_candidates_path = ".runs/image-candidates.json"
    page_image_map_path = ".runs/page-image-map.json"
    image_candidates = None
    page_image_map: dict = {}
    if os.path.isfile(image_candidates_path):
        try:
            image_candidates = json.load(open(image_candidates_path))
        except Exception:
            image_candidates = None
    if os.path.isfile(page_image_map_path):
        try:
            page_image_map = json.load(open(page_image_map_path)) or {}
        except Exception:
            page_image_map = {}

    out: list[dict] = []
    seen_keys: set[str] = set()
    for trace_path in sorted(glob.glob(".runs/agent-traces/*.json")):
        try:
            trace = json.load(open(trace_path))
        except Exception:
            continue
        if rid and trace.get("run_id") and trace.get("run_id") != rid:
            continue
        prov = trace.get("provenance", "")
        if prov not in ("self-degraded", "recovery", "lead-orchestrated"):
            continue
        if not trace.get("partial"):
            continue
        degraded_reason = trace.get("degraded_reason", "")
        if degraded_reason in SANCTIONED_DEGRADED_REASONS:
            continue
        page = trace.get("page", "")
        agent_name = trace.get("agent", "") or os.path.basename(trace_path)
        skipped_check = None
        if page == "landing":
            candidates_tried = trace.get("candidates_tried")
            unresolved = trace.get("unresolved_images") or []
            if (candidates_tried == 0 or candidates_tried is None) and not unresolved:
                if image_candidates is None:
                    # No contract to enforce when sidecar is absent
                    continue
                landing_slots = image_candidates.get("landing", {}) or {}
                has_unused = False
                if isinstance(landing_slots, dict):
                    for slot_name, slot in landing_slots.items():
                        if slot == "empty-state":
                            continue
                        if isinstance(slot, dict) and len(slot.get("candidates") or []) > 1:
                            has_unused = True
                            break
                if has_unused:
                    skipped_check = "step-5.5-image-candidate-inspection"
        else:
            page_entry = page_image_map.get(page) if page else None
            has_images = isinstance(page_entry, dict) and page_entry.get("has_images") is True
            if has_images and "image_issues_for_landing" not in trace:
                skipped_check = "image_issues_for_landing-key-absent"
        if skipped_check is None:
            continue
        key = f"recovery-path-skip:{trace_path}:{degraded_reason}:{skipped_check}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({
            "candidate_id": _hash_key("recovery-path-skip", key),
            "kind": "recovery-path-skip",
            "confidence": "high",
            "key": key,
            "evidence": {
                "trace_path": trace_path,
                "agent": agent_name,
                "page": page,
                "degraded_reason": degraded_reason or "<absent>",
                "skipped_check": skipped_check,
            },
            "source_files": [trace_path],
        })
    return out


def _candidates_from_sparse_traces(rid: str) -> list[dict]:
    """GECR #1456 — enumerate sparse agent traces as candidates.

    Detects (a) init-trace.py 4-key stubs that survived past skill completion
    (status="started" + no verdict field), AND (b) lead-orchestrated traces
    missing AOC v1.3 fields (workarounds[] / template_gap_observed[]).

    Closes the gap from #1303 (a0e568d) AOC v1.2 agent-side rollout that
    completed documentation only for design-critic.md.
    """
    out: list[dict] = []
    seen_keys: set[str] = set()
    for trace_path in sorted(glob.glob(".runs/agent-traces/*.json")):
        try:
            trace = json.load(open(trace_path))
        except Exception:
            continue
        if rid and trace.get("run_id") and trace.get("run_id") != rid:
            continue
        status = trace.get("status", "")
        verdict = trace.get("verdict")
        prov = trace.get("provenance", "")
        agent_name = trace.get("agent", "") or os.path.basename(trace_path)
        shape = None
        missing_fields: list[str] = []
        # Shape (a): init-stub survived
        if status == "started" and verdict is None:
            shape = "init-stub-survived"
        # Shape (b): lead-orchestrated missing AOC v1.3 fields
        elif prov == "lead-orchestrated":
            for f in ("workarounds", "template_gap_observed"):
                if f not in trace:
                    missing_fields.append(f)
            if missing_fields:
                shape = "lead-orchestrated-missing-aoc-v1.3"
        if shape is None:
            continue
        key = f"sparse-trace:{trace_path}:{shape}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({
            "candidate_id": _hash_key("sparse-trace", key),
            "kind": "sparse-trace",
            "confidence": "high",
            "key": key,
            "evidence": {
                "trace_path": trace_path,
                "agent": agent_name,
                "shape": shape,
                "missing_fields": missing_fields,
            },
            "source_files": [trace_path],
        })
    return out


def main() -> int:
    rid = _active_run_id()
    candidates: list[dict] = []
    candidates.extend(_candidates_from_hook_friction(rid))
    candidates.extend(_candidates_from_template_edits(rid))
    candidates.extend(_candidates_from_coherence_findings(rid))
    candidates.extend(_candidates_from_agent_recoveries(rid))
    candidates.extend(_candidates_from_agent_workarounds(rid))  # GECR #1470
    candidates.extend(_candidates_from_trace_overwrites(rid))
    candidates.extend(_candidates_from_verify_failures(rid))  # GECR #1470
    candidates.extend(_candidates_from_lead_deviations(rid))
    candidates.extend(_candidates_from_log_write_failures(rid))
    candidates.extend(_candidates_from_recovery_skips(rid))  # GECR #1468 (OARC)
    candidates.extend(_candidates_from_sparse_traces(rid))   # GECR #1456 (OARC)

    # Stable kind priority for sort (Plan-Agent-B Concern 24 — new kinds
    # interleave deterministically with existing kinds).
    KIND_PRIORITY = {
        "hook-friction": 1,
        "template-edit": 2,
        "coherence-finding": 3,
        "agent-recovery": 4,
        "agent-workaround": 5,
        "trace-overwrite": 6,
        "verify-failure": 7,
        "lead-deviation": 8,
        "log-write-failure": 9,
        "recovery-path-skip": 10,
        "sparse-trace": 11,
    }
    # Sort: kind_priority → high → medium → low → by candidate_id (stable)
    order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: (
        KIND_PRIORITY.get(c.get("kind", ""), 99),
        order.get(c["confidence"], 9),
        c["candidate_id"],
    ))

    out = {
        "run_id": rid,
        "schema_version": 2,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "candidates": candidates,
    }
    os.makedirs(".runs", exist_ok=True)
    with open(".runs/retrospective-pending-findings.json", "w") as f:
        json.dump(out, f, indent=2)
    print(
        f"enumerate-pending-retrospective-findings: {len(candidates)} candidates "
        f"(high={sum(1 for c in candidates if c['confidence']=='high')}, "
        f"medium={sum(1 for c in candidates if c['confidence']=='medium')}, "
        f"low={sum(1 for c in candidates if c['confidence']=='low')})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
