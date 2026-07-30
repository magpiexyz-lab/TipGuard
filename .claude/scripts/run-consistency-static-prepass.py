#!/usr/bin/env python3
"""run-consistency-static-prepass.py — Lead-side prepass for design-consistency-checker (#1257).

Replaces the per-page loop the agent used to do. The lead computes:
  * C1-C4 frequency maps (color / typography / spacing / component) via
    grep across `src/app/<page>/page.tsx`.
  * C5 structural feature vectors via Playwright + DOM extraction (lead
    invokes consistency_dom_extract.js as a subprocess).
  * Anomaly candidates: ≥80% majority threshold detection — pages that
    deviate from the dominant pattern are flagged for severity judgment.
  * Partition: page list is split into ceil(N / BATCH_SIZE) batches so
    each batch agent processes ≤ BATCH_SIZE pages with full maxTurns.

The artifact at `.runs/consistency-check-prepass.json` is the canonical
input for state-3b Stage 2 Step B's per-batch agent spawns. Each batch
agent reads the prepass + judges severity (minor / major / intentional)
of anomaly candidates that involve its assigned pages.

Architecturally this script is the lead-side substrate that lets us
remove the agent-side soft-exit primitive (#1296 → superseded by #1257
final). The agent no longer iterates; the lead pre-computes once.

Usage:
  python3 .claude/scripts/run-consistency-static-prepass.py \
    --base-url http://localhost:3000 \
    --batch-size 8

Exit codes:
  0 — prepass artifact written
  1 — design-page-set.json missing or malformed
  2 — DOM extract subprocess failed (artifact still written with
      `c5_method: "static-fallback"` for transparency)
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

# Tailwind-class regexes — match the "family-shade" tokens used by the
# original agent-side procedure (procedures/design-consistency-checker.md
# Step 2). Each match is a single class token; we count usage per page.
_COLOR_RE = re.compile(r"\b(?:bg|text|border|from|to|via|ring|fill|stroke|outline)-([a-z]+)-(?:50|100|200|300|400|500|600|700|800|900|950)\b")
_TYPO_RE = re.compile(r"\b(?:font-(?:sans|serif|mono|thin|extralight|light|normal|medium|semibold|bold|extrabold|black)|text-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl))\b")
_SPACING_RE = re.compile(r"\b(?:p|px|py|pt|pr|pb|pl|m|mx|my|mt|mr|mb|ml|gap|space-x|space-y)-([0-9]{1,2}(?:\.5)?|px)\b")
_COMPONENT_RE = re.compile(r"<([A-Z][A-Za-z0-9]+)(?:\s|/?>)")

# 80% majority threshold: a value is "majority" iff present on ≥ MAJORITY_THRESHOLD * N pages.
MAJORITY_THRESHOLD = 0.80


def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_run_id() -> str:
    for ctx_path in sorted(glob.glob(".runs/*-context.json")):
        if "epilogue" in os.path.basename(ctx_path):
            continue
        try:
            with open(ctx_path) as f:
                data = json.load(f)
        except Exception:
            continue
        rid = data.get("run_id")
        if rid:
            return rid
    return ""


def collect_page_source(page_entry: dict, project_dir: Path) -> str:
    """Concatenate all source_files content for a page entry. Empty string if none readable."""
    source_files = page_entry.get("source_files") or []
    if not source_files:
        # Fall back to default page.tsx path
        name = page_entry.get("name", "")
        if name == "landing":
            source_files = ["src/app/page.tsx"]
        else:
            source_files = [f"src/app/{name}/page.tsx"]
    parts: list[str] = []
    for rel in source_files:
        path = project_dir / rel
        try:
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(parts)


def collect_class_frequencies(pages: list[dict], regex: re.Pattern, project_dir: Path) -> dict:
    """Return {token: {pages: [page_names], count: int}} — per-page-presence map."""
    presence: dict[str, set[str]] = {}
    for p in pages:
        src = collect_page_source(p, project_dir)
        if not src:
            continue
        tokens = set()
        for match in regex.finditer(src):
            # Use the full matched token (group 0) as the key
            tokens.add(match.group(0))
        for tok in tokens:
            presence.setdefault(tok, set()).add(p["name"])
    return {tok: {"pages": sorted(p), "count": len(p)} for tok, p in presence.items()}


def detect_token_outliers(check: str, freq_map: dict, all_page_names: list[str], threshold: float = MAJORITY_THRESHOLD) -> list[dict]:
    """For each token that appears on ≥ threshold pages, flag the minority pages missing it."""
    anomalies: list[dict] = []
    total = len(all_page_names)
    if total < 3:
        return anomalies
    majority_min = math.ceil(threshold * total)
    for tok, info in freq_map.items():
        if info["count"] < majority_min:
            continue
        with_set = set(info["pages"])
        missing = [n for n in all_page_names if n not in with_set]
        if not missing:
            continue
        anomalies.append({
            "check": check,
            "type": f"missing_{tok}",
            "token": tok,
            "majority_count": info["count"],
            "total_pages": total,
            "minority_pages": missing,
            "detail": f"{tok!r} present on {info['count']}/{total} pages; missing on: {', '.join(missing)}",
            "severity_hint": "?",
        })
    return anomalies


def detect_dom_outliers(features: list[dict], threshold: float = MAJORITY_THRESHOLD) -> list[dict]:
    """For boolean DOM features (header/footer/nav/sidebar), flag pages that deviate from the majority."""
    anomalies: list[dict] = []
    valid = [f for f in features if "error" not in f]
    total = len(valid)
    if total < 3:
        return anomalies
    majority_min = math.ceil(threshold * total)
    for field in ("header_present", "footer_present", "nav_present", "sidebar_present"):
        present_pages = [f["name"] for f in valid if f.get(field) is True]
        absent_pages = [f["name"] for f in valid if f.get(field) is False]
        # Majority: present
        if len(present_pages) >= majority_min and absent_pages:
            anomalies.append({
                "check": "C5",
                "type": f"missing_{field.replace('_present','')}",
                "majority_value": True,
                "minority_pages": absent_pages,
                "majority_count": len(present_pages),
                "total_pages": total,
                "detail": f"{field} on {len(present_pages)}/{total} pages; absent on: {', '.join(absent_pages)} (verify if intentional, e.g., landing without nav)",
                "severity_hint": "?",
            })
        # Majority: absent
        elif len(absent_pages) >= majority_min and present_pages:
            anomalies.append({
                "check": "C5",
                "type": f"unexpected_{field.replace('_present','')}",
                "majority_value": False,
                "minority_pages": present_pages,
                "majority_count": len(absent_pages),
                "total_pages": total,
                "detail": f"{field} absent on {len(absent_pages)}/{total} pages; present on: {', '.join(present_pages)}",
                "severity_hint": "?",
            })
    return anomalies


def partition_pages(page_entries: list[dict], landing: dict | None, batch_size: int) -> list[dict]:
    """Deterministic partition: sorted by name + landing appended; ceil(N / batch_size) batches.

    For N <= batch_size: single batch with batch_id 'single' (legacy compat).
    For N > batch_size: batches named 'batch1', 'batch2', ..., 'batchK'.

    Even distribution: math.ceil(n/k) per batch via slice.
    """
    sorted_pages = sorted(page_entries, key=lambda p: p["name"])
    inputs = list(sorted_pages)
    if landing:
        inputs.append(landing)
    n = len(inputs)
    if n == 0:
        return []
    if n <= batch_size:
        return [{
            "batch_id": "single",
            "pages": [p["name"] for p in inputs],
        }]
    k = math.ceil(n / batch_size)
    sz = math.ceil(n / k)
    return [
        {
            "batch_id": f"batch{i+1}",
            "pages": [p["name"] for p in inputs[i*sz:(i+1)*sz]],
        }
        for i in range(k)
    ]


def invoke_dom_extract(pages: list[dict], base_url: str, project_dir: Path) -> tuple[list[dict], str]:
    """Invoke consistency_dom_extract.js. Returns (features, c5_method).

    c5_method is 'playwright' on success, 'static-fallback' on subprocess failure.
    """
    pages_json = json.dumps([
        {"name": p["name"], "test_url": p.get("test_url", "/" if p.get("name") == "landing" else f"/{p['name']}")}
        for p in pages
    ])
    output_path = project_dir / ".runs" / "consistency-check-dom-features.json"
    script = project_dir / ".claude" / "scripts" / "lib" / "consistency_dom_extract.js"
    try:
        result = subprocess.run(
            ["node", str(script),
             "--base-url", base_url,
             "--pages-json", pages_json,
             "--output", str(output_path)],
            capture_output=True, text=True, timeout=600,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as err:
        sys.stderr.write(f"run-consistency-static-prepass: dom_extract subprocess unavailable: {err}\n")
        return [], "static-fallback"
    if result.returncode != 0:
        sys.stderr.write(f"run-consistency-static-prepass: dom_extract failed (exit {result.returncode}):\n{result.stderr}\n")
        return [], "static-fallback"
    try:
        with open(output_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"run-consistency-static-prepass: dom_extract output unreadable: {err}\n")
        return [], "static-fallback"
    return data.get("features") or [], "playwright"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--skip-playwright", action="store_true",
                        help="Skip Playwright DOM extraction (test-only fallback)")
    parser.add_argument("--project-dir", default=".",
                        help="Project root (defaults to cwd)")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).resolve()

    # 1. Read design-page-set
    page_set_path = project_dir / ".runs" / "design-page-set.json"
    if not page_set_path.exists():
        sys.stderr.write(f"run-consistency-static-prepass: {page_set_path} missing\n")
        return 1
    try:
        with open(page_set_path) as f:
            page_set = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"run-consistency-static-prepass: cannot parse {page_set_path}: {err}\n")
        return 1

    pages = page_set.get("pages") or []
    landing = page_set.get("landing")
    if not pages and not landing:
        sys.stderr.write("run-consistency-static-prepass: design-page-set has no pages\n")
        return 1

    all_page_entries = list(pages)
    if landing:
        all_page_entries.append(landing)
    all_page_names = [p["name"] for p in all_page_entries]

    # 2. Partition
    partition = partition_pages(pages, landing, args.batch_size)

    # 3. C1-C4: frequency maps + outlier detection
    color_map = collect_class_frequencies(all_page_entries, _COLOR_RE, project_dir)
    typo_map = collect_class_frequencies(all_page_entries, _TYPO_RE, project_dir)
    spacing_map = collect_class_frequencies(all_page_entries, _SPACING_RE, project_dir)
    component_map = collect_class_frequencies(all_page_entries, _COMPONENT_RE, project_dir)

    anomalies: list[dict] = []
    anomalies.extend(detect_token_outliers("C1", color_map, all_page_names))
    anomalies.extend(detect_token_outliers("C2", typo_map, all_page_names))
    anomalies.extend(detect_token_outliers("C3", spacing_map, all_page_names))
    anomalies.extend(detect_token_outliers("C4", component_map, all_page_names))

    # 4. C5: invoke Node script for DOM features
    if args.skip_playwright:
        dom_features = []
        c5_method = "static-fallback"
    else:
        dom_features, c5_method = invoke_dom_extract(all_page_entries, args.base_url, project_dir)

    anomalies.extend(detect_dom_outliers(dom_features))

    # 5. Build payload
    payload = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "run_id": resolve_run_id(),
        "base_url": args.base_url,
        "batch_size": args.batch_size,
        "partition": partition,
        "all_pages": all_page_names,
        "global_frequency_maps": {
            "color_classes": color_map,
            "typography": typo_map,
            "spacing": spacing_map,
            "components": component_map,
        },
        "dom_features": dom_features,
        "c5_method": c5_method,
        "anomaly_candidates": anomalies,
    }

    # 6. Write via canonical writer
    out_path = project_dir / ".runs" / "consistency-check-prepass.json"
    writer = project_dir / ".claude" / "scripts" / "lib" / "write-gate-artifact.sh"
    try:
        result = subprocess.run(
            ["bash", str(writer),
             "--path", str(out_path.relative_to(project_dir)),
             "--payload", json.dumps(payload),
             "--skill", "verify"],
            cwd=str(project_dir),
            capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as err:
        sys.stderr.write(f"run-consistency-static-prepass: writer unavailable: {err}\n")
        return 2
    if result.returncode != 0:
        sys.stderr.write(f"run-consistency-static-prepass: write-gate-artifact failed (exit {result.returncode}):\n{result.stderr}\n")
        # Fall back to direct write so prepass is not the blocker
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)

    print(
        f"run-consistency-static-prepass: wrote {out_path.relative_to(project_dir)} "
        f"(partition={len(partition)} batch(es), {len(all_page_names)} pages, "
        f"{len(anomalies)} anomalies, c5={c5_method})"
    )
    return 2 if c5_method == "static-fallback" and not args.skip_playwright else 0


if __name__ == "__main__":
    sys.exit(main())
