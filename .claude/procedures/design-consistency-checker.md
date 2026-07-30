# Design Consistency Checker Procedure

> Read-only cross-page visual consistency verification.
> Invoked by `.claude/agents/design-consistency-checker.md`.
> Page-batched architecture (#1257): each batch agent receives ≤8 pages
> + a lead-side prepass artifact and judges severity of pre-detected
> anomalies. The lead does all deterministic work (grep, screenshot,
> majority-statistics) once before spawning batch agents.

## Step 0: Read Spawn Inputs

From the spawn prompt, extract:

- `prepass_artifact`: path to `.runs/consistency-check-prepass.json`
- `batch_id`: `"single"` or `"batch{N}"`
- `assigned_pages`: list of page names you are responsible for
- `base_url`: dev server URL (informational; you do not navigate)
- `run_id`: from `verify-context.json`

Read the prepass artifact:

```bash
PREPASS_PATH="<prepass_artifact from spawn prompt>"
PREPASS_JSON=$(cat "$PREPASS_PATH")
```

The prepass payload contains:
- `partition`: list of `{batch_id, pages}` entries (informational; verify your `batch_id` matches)
- `global_frequency_maps`: C1-C4 grep frequency maps across ALL pages
- `dom_features`: C5 structural feature vectors per page (header/footer/nav/sidebar presence, content_width, h1_count). May be empty if `c5_method=="static-fallback"` (Playwright unavailable).
- `anomaly_candidates`: array of pre-detected outlier entries — pages that deviate from the ≥80% majority on any check
- `c5_method`: `"playwright"` or `"static-fallback"`

## Step 1: Filter Anomaly Candidates to Your Batch

From `prepass.anomaly_candidates`, select entries that involve any of your `assigned_pages`. An entry "involves" a page when:
- `entry.page` is in your assigned set, OR
- `entry.minority_pages` contains a page in your assigned set, OR
- `entry.pages` (if present) intersects your assigned set

These are pre-detected anomalies the lead found via deterministic statistical
analysis (≥80% majority threshold). Your job is **only severity judgment**.

If no candidates involve your assigned pages, your verdict is `pass` with `inconsistent_count=0` — write the trace and exit.

## Step 2: Severity Judgment (LLM)

For each filtered anomaly, decide severity:

- **major**: brand/structural inconsistency that breaks user expectation. Examples:
  - Different brand color family (e.g., `bg-slate` majority vs `bg-blue` outlier) on otherwise-same-tier pages
  - Missing footer/nav on a page where it should clearly be present (peer pages all have it; no design intent justifies absence)
  - Different heading hierarchy (h1 vs h2 for same role)
- **minor**: stylistic drift unlikely to confuse users. Examples:
  - Spacing token differs (`p-4` vs `p-6`) on similar sections
  - Text size shifts within typography scale
- **intentional** (skip — do NOT include in trace): the variance is design intent, not inconsistency. Examples:
  - Landing page intentionally has no nav bar (the issue body's example: "landing has NO nav bar (intentional per nav-bar.tsx logic)")
  - Empty state pages have different layout
  - Marketing landing has different content width than dashboard pages

Use the `prepass.detail` field + your domain knowledge of the pages and the project's design intent.

When uncertain between minor and major, default to **minor**.
When uncertain between minor and intentional, default to **minor** (better to over-report than under-report; design-critic catches single-page issues).

## Step 3: Build Inconsistencies List

Compose the `inconsistencies` array — one entry per non-skipped severity-classified anomaly:

```json
{
  "check": "C1" | "C2" | "C3" | "C4" | "C5",
  "severity": "major" | "minor",
  "pages": ["<minority_page1>", "<minority_page2>", ...],
  "detail": "<from prepass.detail; may be edited for clarity>"
}
```

Compute scalar fields:
- `inconsistent_count = len(inconsistencies)`
- `verdict = "fail" if inconsistent_count > 0 else "pass"` (verdict invariant)
- `pages_reviewed = <your assigned_pages list>` (the pages YOU are responsible for; merger sums these across batches)
- `pages_reviewed_count = len(assigned_pages)`
- `severity` = max severity across `inconsistencies` (`"none"` when empty, otherwise `"minor"` or `"major"`; rank: none < minor < major)

## Step 4: Write Trace

Use the `TRACE_FILENAME` you computed in your agent definition's First Action — `design-consistency-checker.json` for `batch_id="single"` or `design-consistency-checker-<batch_id>.json` otherwise.

Invoke the canonical writer with `--trace-filename` so the file lands at the right path for the merger to pick up:

```bash
bash .claude/scripts/write-agent-trace.sh design-consistency-checker \
  --trace-filename "$TRACE_FILENAME" \
  --json "$(jq -n \
      --argjson incs "$INCONSISTENCIES_JSON" \
      --argjson pages "$ASSIGNED_PAGES_JSON" \
      --arg verdict "$VERDICT" \
      --arg severity "$SEVERITY" \
      '{
        verdict: $verdict,
        result: "count_summary",
        status: "completed",
        checks_performed: ["C1_color","C2_typography","C3_spacing","C4_component","C5_layout"],
        inconsistencies: $incs,
        inconsistent_count: ($incs | length),
        pages_reviewed: $pages,
        pages_reviewed_count: ($pages | length),
        severity: $severity,
        coverage_provider: "'"$PREPASS_PATH"'"
      }')"
```

The writer stamps `agent`, `timestamp`, `provenance:"self"`, `run_id`, `skill`, `spawn_sha`, and `spawn_index` from active identity + spawn-log (AOC v1.1).

## What you DON'T do (Page-batched architecture)

- Do NOT screenshot pages — the lead pre-rendered all pages via Playwright in the prepass
- Do NOT grep page source files — the lead computed `global_frequency_maps` in the prepass
- Do NOT track turn budgets / boundary checks — page-batching gives you guaranteed budget for ≤8 pages within `maxTurns=1000`
- Do NOT cross-batch-compare — the lead's `anomaly_candidates` already span all pages; you only judge severity for candidates involving YOUR assigned pages
- Do NOT merge per-batch traces — the lead invokes `merge-design-consistency-checker-traces.py` after all batch agents complete

## Failure modes

- **Prepass artifact missing/malformed**: write a recovery trace via `bash .claude/scripts/write-recovery-trace.sh design-consistency-checker --reason "prepass-missing"` and exit. The merger / hard-gate will surface this through the validated_fallback predicate path.
- **Ambiguous severity**: default to `minor` (over-report bias). Add a brief justification in the `detail` field.
- **Empty `assigned_pages`**: emit a trace with `verdict="pass"`, `inconsistent_count=0`, `pages_reviewed=[]`. The merger will still aggregate.
- **`c5_method == "static-fallback"`**: the prepass's DOM-feature anomaly_candidates may be empty. Judge severity only on the C1-C4 grep-based candidates that are present.
