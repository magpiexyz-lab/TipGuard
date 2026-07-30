#!/usr/bin/env python3
"""Gate Evidence Cross-Reference Protocol (GECR) — generic runner.

Closes #1473 + #1470 root cause: gates that enforce structural shape of an
artifact as a proxy for the semantic property they were meant to certify.

This runner consumes declarative rules from
`.claude/patterns/gate-evidence-rules.json` (schema at
`gate-evidence-rule-schema.json`) and emits structured failures with
citations. Follow-up issues (#1468, #1456) add rules without code changes.

Architecture:
  1. load_rules(path) — reads JSON, validates against schema at load time
     via jsonschema.validate(). Malformed rules raise SystemExit(2) with
     the schema error path. (Plan Agent A Open Risk 1)
  2. resolve_evidence(rule, source) — resolves path_glob + reader to actual
     content. Readers: json | jsonl | grep_tsx | filesystem.
  3. apply_matcher(rule, evidence_rows) — applies matcher.kind to extract
     friction events / expected facts.
  4. check_expected_observation(rule, friction_events) — cross-references
     against expected_observation.artifact_path via predicate. Returns
     structured failures with citations.
  5. mode_for(rule) — reads env var named in rule.mode_env; defaults to
     "warn". Pre-cutoff via schema_version_gate.required_schema_version().

Exit code contract:
  0 — PASS (no failures, or all failures in warn mode)
  1 — BLOCK (deny mode + failures present)
  2 — Infrastructure error (schema invalid, evidence source unparseable)
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
import sys
from typing import Any

# Same path discovery used elsewhere
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

try:
    from schema_version_gate import required_schema_version  # type: ignore
except ImportError:
    def required_schema_version(rid: str) -> int:  # fallback for early loads
        return 1


RULES_PATH = ".claude/patterns/gate-evidence-rules.json"
RULES_SCHEMA_PATH = ".claude/patterns/gate-evidence-rule-schema.json"


def load_rules(path: str = RULES_PATH, schema_path: str = RULES_SCHEMA_PATH) -> list[dict]:
    """Load rules and validate against schema. Raises SystemExit(2) on malformed."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        sys.stderr.write(
            "gate_evidence_runner: ERROR — jsonschema package not installed. "
            "Install via `pip install --user --break-system-packages jsonschema` "
            "or `pip install jsonschema`.\n"
        )
        raise SystemExit(2)

    if not os.path.isfile(path):
        sys.stderr.write(f"gate_evidence_runner: ERROR — rules file not found: {path}\n")
        raise SystemExit(2)
    if not os.path.isfile(schema_path):
        sys.stderr.write(f"gate_evidence_runner: ERROR — schema file not found: {schema_path}\n")
        raise SystemExit(2)

    try:
        data = json.load(open(path))
        schema = json.load(open(schema_path))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"gate_evidence_runner: ERROR — JSON parse error: {exc}\n")
        raise SystemExit(2)

    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        sys.stderr.write(
            f"gate_evidence_runner: ERROR — rule validation failed at "
            f"path={'.'.join(str(p) for p in exc.absolute_path)}: {exc.message}\n"
        )
        raise SystemExit(2)

    return data.get("rules", [])


def mode_for(rule: dict) -> str:
    """Return 'warn' | 'deny' | 'skip' based on env + schema cutoff."""
    if rule.get("schema_cutoff"):
        rid = _active_run_id()
        required_v = required_schema_version(rid) if rid else 1
        if required_v < 2:
            return "skip"

    env_name = rule.get("mode_env", "")
    if env_name:
        val = os.environ.get(env_name, "").lower()
        if val in ("warn", "deny"):
            return val
    # Fall back to rule.severity: block → deny default; warn → warn default
    sev = rule.get("severity", "warn")
    return "deny" if sev == "block" else "warn"


def _active_run_id() -> str:
    """Discover active run_id from .runs/*-context.json (skill-agnostic)."""
    best = None
    best_ts = ""
    try:
        candidates = glob.glob(".runs/*-context.json")
    except Exception:
        return ""
    for f in candidates:
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


# ---------------------------------------------------------------------------
# Evidence readers
# ---------------------------------------------------------------------------

def _read_json(path: str) -> dict | list | None:
    if not os.path.isfile(path):
        return None
    try:
        return json.load(open(path))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    rows: list[dict] = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def _read_grep_tsx(path: str) -> str:
    """Read .tsx file contents for grep-style matching."""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def resolve_evidence(rule: dict, source: dict) -> list[dict]:
    """Resolve one evidence_source entry to a list of {path, content} rows.

    Each returned row: {path: str, content: <json|list[jsonl]|str|None>}.
    Missing files yield empty/None content but path is recorded so downstream
    can cite "expected at <path> but not present".
    """
    path_glob = source.get("path_glob", "")
    reader = source.get("reader", "")
    always_included = source.get("always_included_paths", []) or []

    # Resolve glob; for non-glob exact paths glob.glob returns [path] if it
    # exists, else []. Augment with always_included regardless.
    paths: list[str] = []
    if path_glob:
        # If path_glob doesn't contain glob chars, also include the literal
        # so missing paths can be cited.
        if any(c in path_glob for c in "*?["):
            paths.extend(glob.glob(path_glob, recursive=True))
        else:
            paths.append(path_glob)
    for p in always_included:
        if p not in paths:
            paths.append(p)

    out: list[dict] = []
    for p in paths:
        if reader == "json":
            out.append({"path": p, "content": _read_json(p)})
        elif reader == "jsonl":
            out.append({"path": p, "content": _read_jsonl(p)})
        elif reader == "grep_tsx":
            out.append({"path": p, "content": _read_grep_tsx(p)})
        elif reader == "filesystem":
            out.append({"path": p, "content": os.path.isfile(p) or os.path.isdir(p)})
        else:
            out.append({"path": p, "content": None})
    return out


# ---------------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------------

def _matcher_template_literal_navigation(rule: dict, rows: list[dict], params: dict) -> list[dict]:
    """For #1473: classify pages as static/dynamic-only/mixed/absent via
    derive_dynamic_only_pages; for each non-static page, search rows for
    template-literal `href={`/<page>/${...}`}` patterns.

    Returns a list of friction events: pages where the expected nav form
    is NOT found in any evidence row.
    """
    # Lazy import to avoid circular dependency
    try:
        from derive_pages import derive_dynamic_only_pages  # type: ignore
    except ImportError:
        sys.stderr.write("gate_evidence_runner: ERROR — cannot import derive_dynamic_only_pages\n")
        return []

    # Load experiment.yaml
    try:
        import yaml  # type: ignore
        experiment = yaml.safe_load(open("experiment/experiment.yaml"))
    except (ImportError, OSError, Exception) as exc:
        sys.stderr.write(f"gate_evidence_runner: ERROR — cannot load experiment.yaml: {exc}\n")
        return []

    classifications = derive_dynamic_only_pages(experiment)

    # Auth-excluded pages (same as BG2-WIRE check 1)
    excluded = {"landing", "login", "signup", "auth/callback", "auth/reset-password"}

    failures: list[dict] = []
    for page, classification in classifications.items():
        if page in excluded:
            continue
        if classification == "absent":
            continue  # Trivially passes; other gates enforce existence

        # Combine all evidence row contents into one searchable corpus
        corpus = "\n".join(
            row["content"] for row in rows
            if isinstance(row.get("content"), str)
        )

        # Slug-suffix awareness (round-2 Concern 487fdf73cf62): when the
        # experiment.yaml slug is hyphenated (`portfolio-detail`), the actual
        # filesystem folder + route is the static prefix (`portfolio`). The
        # matcher must search for BOTH the literal slug AND its static prefix.
        route_names: list[str] = [page]
        if "-" in page:
            prefix = page.split("-", 1)[0]
            if prefix and prefix != page:
                route_names.append(prefix)

        # Build patterns per classification
        # Use rg-compatible regex (Python re works too). Multiline-aware via
        # re.DOTALL because prettier may format `<Link href={\n  `/page/...
        # across lines.
        def _bare_slug_for(name: str) -> str:
            n = re.escape(name)
            return rf'href=(?:"/{n}(?:/|"|\?)|\{{[^}}]*"/?{n}["/]?[^}}]*\}})'

        def _template_literal_for(name: str) -> str:
            n = re.escape(name)
            return rf'href=\s*\{{\s*`/{n}/\$\{{'

        bare_slug_present = any(
            re.search(_bare_slug_for(n), corpus) is not None for n in route_names
        )
        template_literal_present = any(
            re.search(_template_literal_for(n), corpus, re.DOTALL) is not None
            for n in route_names
        )

        if classification == "static":
            # Bare-slug required (current semantic preserved)
            if not bare_slug_present:
                failures.append({
                    "page": page,
                    "classification": "static",
                    "requirement": "bare-slug href=/<page> required",
                    "found": "no bare-slug href and no template-literal nav",
                    "expected": f'href="/{page}"',
                })
        elif classification == "dynamic-only":
            # Template-literal REQUIRED — bare slug insufficient (would 404)
            if not template_literal_present:
                failures.append({
                    "page": page,
                    "classification": "dynamic-only",
                    "requirement": (
                        "page is dynamic-only — bare slug cannot resolve a "
                        "concrete URL; require template-literal navigation"
                    ),
                    "found": (
                        f'bare-slug only={bare_slug_present}, '
                        f'template-literal={template_literal_present}'
                    ),
                    "expected": f"<Link href={{`/{page}/${{id}}`}}>",
                })
        elif classification == "mixed":
            # Both required
            missing = []
            if not bare_slug_present:
                missing.append("bare-slug href")
            if not template_literal_present:
                missing.append("template-literal nav")
            if missing:
                failures.append({
                    "page": page,
                    "classification": "mixed",
                    "requirement": (
                        "page is mixed (static index AND dynamic children) — "
                        "both nav forms expected"
                    ),
                    "found": (
                        f'bare-slug={bare_slug_present}, '
                        f'template-literal={template_literal_present}'
                    ),
                    "expected": f"BOTH href=/{page} AND href={{`/{page}/${{id}}`}}",
                    "missing": missing,
                })

    return failures


def _matcher_friction_event_extraction(rule: dict, rows: list[dict], params: dict) -> list[dict]:
    """For #1470: extract friction events from agent traces (workarounds[],
    template_gap_observed[]), verify-recheck.json (failed states), and
    fix-ledger.jsonl (provenance:lead rows).

    Returns list of friction events. Cross-reference happens in
    check_expected_observation.
    """
    fields = params.get("fields", ["workarounds", "template_gap_observed", "verify_results"])
    events: list[dict] = []

    for row in rows:
        content = row.get("content")
        if content is None:
            continue
        path = row.get("path", "")

        # JSONL list of dicts (e.g., fix-ledger.jsonl)
        if isinstance(content, list) and all(isinstance(r, dict) for r in content):
            for r in content:
                # fix-ledger.jsonl provenance:lead pattern
                prov = r.get("provenance", "")
                if prov in ("lead", "lead-on-behalf") and r.get("entry_type") == "template-edit":
                    target = r.get("target_file") or r.get("file") or ""
                    if target:
                        events.append({
                            "kind": "fix-ledger-lead-edit",
                            "source_path": path,
                            "target_file": target,
                            "description": (r.get("summary") or "")[:160],
                        })

        # JSON dict (e.g., verify-recheck.json, agent traces)
        elif isinstance(content, dict):
            # verify-recheck.json: verify_results[] with passed=false rows
            if "verify_results" in fields:
                for vr in (content.get("verify_results") or []):
                    if isinstance(vr, dict) and vr.get("passed") is False:
                        events.append({
                            "kind": "verify-failure",
                            "source_path": path,
                            "state": vr.get("state") or vr.get("name") or "",
                            "description": (vr.get("error") or "")[:160],
                        })
            # Agent trace: workarounds[] + template_gap_observed[]
            for key in ("workarounds", "template_gap_observed"):
                if key not in fields:
                    continue
                entries = content.get(key) or []
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    # Skip self-resolved workarounds
                    if entry.get("root_cause_unresolved") is False:
                        continue
                    events.append({
                        "kind": f"agent-{key}",
                        "source_path": path,
                        "file": entry.get("file") or entry.get("template_path") or "",
                        "line": entry.get("line", 0),
                        "type": entry.get("type") or "",
                        "description": (entry.get("description") or entry.get("observation") or "")[:160],
                        "root_cause_unresolved": entry.get("root_cause_unresolved"),
                    })

    return events


def _matcher_recovery_skip_extraction(rule: dict, rows: list[dict], params: dict) -> list[dict]:
    """For #1468 + #1456: extract fallback-shape skip events from agent traces.

    Implements the OARC (Observation-Anchored Recovery Contract, sibling of
    EARC #1189): traces produced under exceptional / recovery / post-completion
    conditions must either carry full schema with real data OR appear as a
    candidate row in retrospective-pending-findings.json that the lead files
    or suppresses.

    Emits two friction-event kinds gated on `params.target_kinds`:

    - `recovery-path-skip` — provenance ∈ {self-degraded, recovery,
      lead-orchestrated} AND partial=true AND a non-sanctioned degraded_reason
      AND a domain-specific skipped check is detectable (landing context:
      candidates_tried==0 with unused sidecar candidates; non-landing
      has_images=true: image_issues_for_landing key missing).

    - `sparse-trace` — trace shape `{agent, status, timestamp, run_id}` without
      `verdict` (init-trace.py stub survived past skill completion) OR
      `provenance="lead-orchestrated"` AND missing AOC v1.3 required fields
      (`workarounds[]` / `template_gap_observed[]`).

    Suppression sources (params):
      - `target_kinds`: which OARC kind(s) this rule should emit
      - `suppressed_degraded_reasons`: sanctioned legitimate-skip allowlist;
        prefer importing the shared canonical list at
        `.claude/scripts/lib/sanctioned_degraded_reasons.py` rather than
        duplicating in rule JSON.

    Cross-reference happens in check_expected_observation
    (matches_friction_count predicate maps to retrospective-pending-findings.json).
    """
    target_kinds = set(params.get("target_kinds") or [])
    # Suppressed reasons can come from rule JSON params OR the shared canonical
    # list. Default = shared list. Allow rule to override only by extension
    # (intersection enforced — never strip canonical suppressions).
    try:
        from sanctioned_degraded_reasons import SANCTIONED_DEGRADED_REASONS  # type: ignore
        canonical_suppressions = set(SANCTIONED_DEGRADED_REASONS)
    except ImportError:
        canonical_suppressions = set()
    rule_suppressions = set(params.get("suppressed_degraded_reasons") or [])
    suppressed = canonical_suppressions | rule_suppressions

    # Load suppression sidecars by path so the matcher can do landing-context
    # checks without reading from disk a second time.
    sidecars: dict[str, dict | list | str | None] = {}
    for row in rows:
        path = row.get("path", "")
        if path.endswith("image-candidates.json") or path.endswith("page-image-map.json"):
            sidecars[os.path.basename(path)] = row.get("content")

    image_candidates_sidecar = sidecars.get("image-candidates.json")
    page_image_map = sidecars.get("page-image-map.json") or {}
    if not isinstance(page_image_map, dict):
        page_image_map = {}

    # When the rule targets recovery-path-skip AND image-candidates.json is
    # absent, the contract has no anchor — return [] rather than firing false
    # positives. Note: sidecar may exist but be empty dict; that still counts
    # as "no unused candidates" → no recovery-path-skip firing (caught below).
    if "recovery-path-skip" in target_kinds and image_candidates_sidecar is None:
        # Absence of sidecar means no candidate-confirmation contract for this
        # run. Allow sparse-trace kind to still emit (it doesn't depend on
        # image-candidates.json), so we don't early-return globally.
        target_kinds = target_kinds - {"recovery-path-skip"}
        if not target_kinds:
            return []

    failures: list[dict] = []
    for row in rows:
        path = row.get("path", "")
        if not path.startswith(".runs/agent-traces/"):
            continue
        trace = row.get("content")
        if not isinstance(trace, dict):
            continue
        prov = trace.get("provenance", "")
        status = trace.get("status", "")
        verdict = trace.get("verdict")
        degraded_reason = trace.get("degraded_reason", "")
        page = trace.get("page", "")
        agent_name = trace.get("agent", "")

        # ── kind=sparse-trace detection ──────────────────────────────────────
        if "sparse-trace" in target_kinds:
            # Init-stub survived: status=started + no verdict field
            if status == "started" and verdict is None:
                failures.append({
                    "kind": "sparse-trace",
                    "shape": "init-stub-survived",
                    "source_path": path,
                    "agent": agent_name,
                    "description": (
                        f"init-trace.py stub at {path} survived without a "
                        f"completing write (agent={agent_name!r})"
                    )[:200],
                })
                continue  # Don't also evaluate recovery-path-skip on the same trace
            # Lead-orchestrated missing AOC v1.3 fields
            if prov == "lead-orchestrated":
                missing_fields = [
                    f for f in ("workarounds", "template_gap_observed")
                    if f not in trace
                ]
                if missing_fields:
                    failures.append({
                        "kind": "sparse-trace",
                        "shape": "lead-orchestrated-missing-aoc-v1.3",
                        "source_path": path,
                        "agent": agent_name,
                        "missing_fields": missing_fields,
                        "description": (
                            f"lead-orchestrated trace at {path} missing "
                            f"AOC v1.3 fields: {missing_fields}"
                        )[:200],
                    })
                    continue

        # ── kind=recovery-path-skip detection ────────────────────────────────
        if "recovery-path-skip" not in target_kinds:
            continue
        if prov not in ("self-degraded", "recovery", "lead-orchestrated"):
            continue
        if not trace.get("partial"):
            continue
        if degraded_reason in suppressed:
            continue
        # Skipped-check detection: landing context or has_images=true context.
        skipped_check = None
        # Landing-owned candidate confirmation
        if page == "landing":
            # candidates_tried==0 with unused sidecar candidates → silent skip
            candidates_tried = trace.get("candidates_tried")
            if candidates_tried == 0 or candidates_tried is None:
                # Check sidecar for unused candidates in landing-owned slots
                if isinstance(image_candidates_sidecar, dict):
                    landing_slots = image_candidates_sidecar.get("landing", {}) or {}
                    unresolved = trace.get("unresolved_images") or []
                    has_unresolved_escape_hatch = bool(unresolved)
                    has_unused_candidates = any(
                        isinstance(slot, dict) and len(slot.get("candidates") or []) > 1
                        for slot in landing_slots.values()
                        if slot != "empty-state"
                    ) if isinstance(landing_slots, dict) else False
                    if has_unused_candidates and not has_unresolved_escape_hatch:
                        skipped_check = "step-5.5-image-candidate-inspection"
        # Non-landing has_images=true: image_issues_for_landing key missing
        else:
            page_entry = page_image_map.get(page) if isinstance(page_image_map, dict) else None
            has_images = (
                isinstance(page_entry, dict) and page_entry.get("has_images") is True
            )
            if has_images and "image_issues_for_landing" not in trace:
                skipped_check = "image_issues_for_landing-key-absent"

        if skipped_check is None:
            continue
        failures.append({
            "kind": "recovery-path-skip",
            "source_path": path,
            "agent": agent_name,
            "page": page,
            "degraded_reason": degraded_reason or "<absent>",
            "skipped_check": skipped_check,
            "description": (
                f"fallback-shape trace at {path} (agent={agent_name!r}, "
                f"page={page!r}, reason={degraded_reason!r}) silently skipped "
                f"{skipped_check}"
            )[:200],
        })

    return failures


def apply_matcher(rule: dict, rows: list[dict]) -> list[dict]:
    """Dispatch matcher.kind to its implementation."""
    matcher = rule.get("matcher", {})
    kind = matcher.get("kind", "")
    params = matcher.get("params", {}) or {}

    if kind == "template_literal_navigation":
        return _matcher_template_literal_navigation(rule, rows, params)
    elif kind == "friction_event_extraction":
        return _matcher_friction_event_extraction(rule, rows, params)
    elif kind == "any_of_patterns":
        # Generic substring/regex match across evidence rows
        patterns = params.get("patterns", []) or []
        failures: list[dict] = []
        for row in rows:
            content = row.get("content")
            if not isinstance(content, str):
                continue
            for pat in patterns:
                if re.search(pat, content):
                    return []  # at least one pattern matched → no failures
        # No pattern matched in any row → all rows are failures
        return [{"reason": f"none of {len(patterns)} patterns matched", "patterns": patterns}]
    elif kind == "recovery_skip_extraction":
        return _matcher_recovery_skip_extraction(rule, rows, params)
    else:
        sys.stderr.write(f"gate_evidence_runner: WARN — unknown matcher kind: {kind!r}\n")
        return []


# ---------------------------------------------------------------------------
# Expected-observation predicates
# ---------------------------------------------------------------------------

def check_expected_observation(rule: dict, friction_events: list[dict]) -> list[dict]:
    """Cross-reference friction events against the expected observation
    artifact via the rule's predicate.

    Returns final failures (each citing source + expected observation).
    """
    if not friction_events:
        return []

    expected = rule.get("expected_observation", {})
    predicate = expected.get("predicate", "")
    artifact_path = expected.get("artifact_path", "")
    params = expected.get("params", {}) or {}

    if predicate == "exists_with_citation":
        # For #1473: the friction events ARE the failures — no cross-ref
        # needed (template_literal_navigation matcher already determined
        # absence). Pass them through.
        return friction_events

    elif predicate == "array_non_empty":
        # Generic: friction_events is the failure list itself
        return friction_events

    elif predicate == "matches_friction_count":
        # For #1470: every pending candidate in the kinds this rule cares
        # about must be either FILED in retrospective-filed-findings.json
        # OR SUPPRESSED in retrospective-result.json suppressions[].
        #
        # Source of truth: .runs/retrospective-pending-findings.json
        # (written by enumerate-pending-retrospective-findings.py). We
        # cross-reference its canonical candidate_ids rather than re-deriving
        # them here — re-derivation diverged from the enumerator's per-kind
        # `_hash_key(prefix, key)` convention (some prefixes double, some
        # don't), so any local hash would silently mismatch real cids written
        # by file-retrospective-finding.py. Using the enumerator output
        # gives a single source of truth for cid identity.
        filed = _read_json(artifact_path) or {}
        filed_ids = set()
        for entry in (filed.get("filed") or []):
            cid = entry.get("candidate_id")
            if cid:
                filed_ids.add(cid)

        suppress_path = params.get("or_suppressed_in", "")
        suppress_ids = set()
        if suppress_path:
            suppress = _read_json(suppress_path) or {}
            for s in (suppress.get("suppressions") or []):
                cid = s.get("candidate_id")
                if cid:
                    suppress_ids.add(cid)

        # Default to the two kinds this rule was designed for (GECR #1470).
        # Callers can override via rule.expected_observation.params.target_kinds
        # if a new rule needs to cross-reference a different kind set.
        target_kinds = set(params.get("target_kinds") or
                           ["agent-workaround", "verify-failure"])

        pending_doc = _read_json(".runs/retrospective-pending-findings.json") or {}
        pending = [c for c in (pending_doc.get("candidates") or [])
                   if isinstance(c, dict) and c.get("kind") in target_kinds]

        if not pending:
            # No canonical pending candidates of these kinds → fall back to
            # the matcher's freshly extracted friction_events so the rule
            # still has signal when the enumerator hasn't run yet (e.g.,
            # standalone /observe invocation or pre-Step-5a context).
            # Each event is reported as a probable-pending; the lead resolves
            # by running enumerate-pending-retrospective-findings.py.
            failures: list[dict] = []
            for event in friction_events:
                failures.append({
                    **event,
                    "candidate_id": None,
                    "expected_in": artifact_path,
                    "or_suppressed_in": suppress_path,
                    "remediation": (
                        "Enumerator has not produced "
                        ".runs/retrospective-pending-findings.json yet. "
                        "Run `python3 .claude/scripts/"
                        "enumerate-pending-retrospective-findings.py` first, "
                        "then file the resulting candidate."
                    ),
                })
            return failures

        failures = []
        for cand in pending:
            cid = cand.get("candidate_id")
            if not cid:
                continue
            if cid in filed_ids or cid in suppress_ids:
                continue
            evidence = cand.get("evidence") or {}
            description = (
                evidence.get("description")
                or evidence.get("observation")
                or evidence.get("error")
                or cand.get("key", "")
            )
            source_path = ""
            sf = cand.get("source_files") or []
            if isinstance(sf, list) and sf:
                source_path = sf[0]
            failures.append({
                "candidate_id": cid,
                "kind": cand.get("kind"),
                "key": cand.get("key"),
                "source_path": source_path,
                "description": (description or "")[:200],
                "expected_in": artifact_path,
                "or_suppressed_in": suppress_path,
                "remediation": (
                    f"Either file via .claude/scripts/file-retrospective-finding.py "
                    f"--candidate-id {cid} OR add to {suppress_path} suppressions[] "
                    f"with reason from the closed enum."
                ),
            })
        return failures

    else:
        sys.stderr.write(f"gate_evidence_runner: WARN — unknown predicate: {predicate!r}\n")
        return friction_events


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_rule(rule: dict) -> tuple[str, list[dict]]:
    """Execute one rule. Returns (mode, failures)."""
    mode = mode_for(rule)
    if mode == "skip":
        return ("skip", [])

    # Resolve all evidence sources
    all_rows: list[dict] = []
    for source in (rule.get("evidence_sources") or []):
        all_rows.extend(resolve_evidence(rule, source))

    # Apply matcher
    friction_events = apply_matcher(rule, all_rows)

    # Cross-reference against expected observation
    failures = check_expected_observation(rule, friction_events)

    return (mode, failures)


def format_failure(rule: dict, failure: dict) -> str:
    """Format a single failure using the rule's failure_citation_format."""
    template = rule.get("failure_citation_format", "{event_summary} ({source_path})")
    try:
        return template.format(
            **failure,
            event_summary=failure.get("description") or failure.get("page") or "(unknown)",
            source_path=failure.get("source_path") or failure.get("expected_in") or "(unknown)",
        )
    except (KeyError, ValueError):
        return json.dumps(failure, indent=2)


__all__ = [
    "load_rules",
    "mode_for",
    "resolve_evidence",
    "apply_matcher",
    "check_expected_observation",
    "run_rule",
    "format_failure",
]
