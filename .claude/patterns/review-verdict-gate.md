# Review-Verdict Gate

Shared enforcement of the `review_method → verdict` mapping across all
reviewer agents. Invoked state-locally by the state that spawns each
reviewer, after the agent's trace lands.

> **Problem solved**: without this gate, each reviewer agent carries its
> own `review_method → verdict` decision in the agent's code, and a
> tampered or buggy agent can emit a "PASS" on a `source-only` review.
> This gate is the tamper-resistant choke point: agents emit whatever
> verdict they think is right, and this gate overwrites the trace with
> the policy-correct verdict (logging the correction). The
> `review_method_gate_evaluated` sentinel proves the gate ran —
> `state-registry.json` VERIFY commands assert its presence so the gate
> cannot be silently bypassed.

## Callers

| State | Agent trace(s) | Invocation point |
|---|---|---|
| `state-2-phase1-parallel.md` | `behavior-verifier.json`, `accessibility-scanner.json` | After Phase 1 agents return |
| `state-3a-design-agents.md` | `design-critic-*.json` (per-page) | **Unchanged** — state-3b's existing merge code already enforces design-critic's mapping. Not called here. |
| `state-3b-quality-gate.md` | `design-critic.json` (merged) | **Unchanged** — existing enforcement stays. Not called here. |
| `state-3c-ux-merge.md` | `ux-journeyer.json` | After ux-journeyer returns |

design-critic and accessibility-scanner's existing enforcement (`source-only`
/ `unknown` → `"unresolved"`) is preserved in state-3b for design-critic
and in accessibility-scanner's own procedure for skip-page handling. This
gate **adds** rules for the new review_methods (`prereq-unmet`) and the
new callers (ux-journeyer, behavior-verifier) without touching the
existing invariants.

## AUTH_PATHS anchor (shared with render-review-detection.md)

```javascript
// SHARED:AUTH_PATHS — canonical list. ALSO referenced by
// .claude/patterns/render-review-detection.md Section 3. Any change
// here requires a matching update in that file. The drift test at
// .claude/scripts/tests/test_auth_paths_drift.py enforces equality.
const AUTH_PATHS = new Set(["/login", "/signup", "/auth/callback", "/auth/reset-password"]);
```

Python port (used inside the gate's correction script):

```python
# SHARED:AUTH_PATHS
AUTH_PATHS = {"/login", "/signup", "/auth/callback", "/auth/reset-password"}
```

## Policy tables

Each agent declares its `(review_method, final_path_bucket) → verdict`
mapping. The gate looks up the table, compares emitted verdict to
required verdict, overwrites on mismatch, and logs a correction.

### design-critic (not enforced here — kept for reference only)

Enforcement lives in `state-3b-quality-gate.md`. Rules:

| review_method | Required verdict |
|---|---|
| `source-only` (any final path) | `"unresolved"` |
| `unknown` | `"unresolved"` |

### accessibility-scanner

Enforced via its procedure (skip-page). Rules:

| review_method | Action |
|---|---|
| `source-only` (any final path) | Skip axe-core for the page; omit from `pages_scanned` |
| `unknown` | Same as `source-only` |
| `prereq-unmet` | Not currently emitted (accessibility-scanner does not set `auth_requirement="required"`); reserved |

This gate enforces presence of a `review_method_gate_evaluated` sentinel
on accessibility-scanner.json as a tripwire.

### ux-journeyer

| review_method | `final_path` bucket | Required `per_step_status` |
|---|---|---|
| `rendered-authed` | — | `pass` |
| `rendered-demo` | — | `pass` |
| `source-only` | `∈ AUTH_PATHS` | `dead-end-auth` |
| `source-only` | `∉ AUTH_PATHS` | `dead-end` |
| `unknown` | — | `error` |
| `prereq-unmet` | — | `blocked` (also forces top-level `verdict="blocked"`) |

Implementation: gate walks `per_step_reviews[]` and ensures every entry's
per-step `status` field matches the table. Top-level `verdict="blocked"`
enforced when any step has `review_method="prereq-unmet"`. The spec
values above are LITERAL keywords — they appear byte-for-byte in
`.claude/scripts/run-review-verdict-gate.py`'s `POLICY` dict
(drift-tested by `test_review_verdict_gate_policy_drift.py`).

### behavior-verifier

| review_method | `final_path` bucket | Required `per_item_verdict` |
|---|---|---|
| `rendered-authed` | — | `PASS` |
| `rendered-demo` | — | `PASS` |
| `prereq-unmet` | — | `SKIPPED` |
| `source-only` | `∈ AUTH_PATHS` | `FAIL` |
| `source-only` | `∉ AUTH_PATHS` | `DEGRADED` |
| `unknown` | — | `FAIL` |

Semantics by row: `PASS` → proceed with given/when/then probes;
`SKIPPED` → auth required but session missing (NOT a failure);
`FAIL ∈ AUTH_PATHS` → B3 Silent Failure (expected route unreachable);
`DEGRADED ∉ AUTH_PATHS` → product-level redirect (route still reachable
at a different path); `FAIL unknown` → navigation failed. The verdict
column above lists LITERAL keywords used by the script's `POLICY` dict
(drift-tested).

Implementation: gate walks `per_behavior_reviews[]` and overwrites each
entry's per-behavior verdict. Top-level trace verdict is the
worst-cardinality across all entries (FAIL > DEGRADED > SKIPPED > PASS).

## Procedure (single executable source — runs in the state that spawned the reviewer)

> **Single source of truth**: `.claude/scripts/run-review-verdict-gate.py`
> is the canonical executable. This markdown carries the SPECIFICATION
> (policy tables above + sentinel/idempotency contracts below); the
> script carries the IMPLEMENTATION. Neither file should embed a parallel
> POLICY dict — the drift test
> `.claude/scripts/tests/test_review_verdict_gate_policy_drift.py`
> enforces this single-source rule.
>
> If you need to extend the policy:
> 1. Update the policy tables in this file's "Policy tables" section above.
> 2. Update the `POLICY` dict in `.claude/scripts/run-review-verdict-gate.py`.
> 3. Run `python3 .claude/scripts/tests/test_review_verdict_gate_policy_drift.py`
>    to verify the spec and implementation agree.

State files invoke the gate as:

```bash
python3 .claude/scripts/run-review-verdict-gate.py <trace_path> <agent_name>
```

The script:
- Reads the trace JSON
- Looks up policy via `(agent, review_method, final_path_bucket)`
  where `final_path_bucket` is `"auth"` if `final_path ∈ AUTH_PATHS`,
  else `"non-auth"`, else `"any"` for path-agnostic policies
- Walks `per_step_reviews[]`, `per_behavior_reviews[]`,
  `per_page_reviews[]` arrays (in that fixed order)
- Auto-corrects per-item verdicts/statuses on policy mismatch and logs
  to `review_method_gate_corrections[]`
- Forces top-level `verdict` when policy specifies `top_level_verdict`
  (e.g., `prereq-unmet` on any ux-journeyer step → top-level
  `verdict="blocked"`)
- Always writes the `review_method_gate_evaluated: true` sentinel
- Returns `{"corrections_applied": N}` JSON

The script is the canonical reference for the AUTH_PATHS Set
(carries the `// SHARED:AUTH_PATHS` anchor matching
`render-review-detection.md`) and for the POLICY dict.

## Sentinel field — `review_method_gate_evaluated`

After running, the gate writes `"review_method_gate_evaluated": true` on
the trace. `state-registry.json` VERIFY commands assert this sentinel is
present on every reviewer trace; a missing sentinel means the gate was
skipped and the state fails to advance.

The sentinel is the only way downstream consumers know the gate ran.
Checking for corrections alone is not sufficient — a trace with 0
corrections (all verdicts already policy-correct) should still prove
the gate ran.

## Idempotency

Calling the gate twice on the same trace is a no-op. Rationale:
- A retry loop in the state may re-run the gate after a recovery; the
  sentinel prevents double-correction (and double-logging in
  `review_method_gate_corrections`).
- If a downstream tool (e.g., retrospective) wants to re-verify, it can
  read the sentinel rather than re-run the gate.

## Failure modes

| Condition | Gate behavior |
|---|---|
| Trace file absent | Return `{"corrections_applied": 0, "skipped_reason": "trace-missing"}`. Caller should decide whether to fail the state (usually yes — missing trace means agent didn't run). |
| Trace missing `review_method` (old trace) | Forward-compat: pass through without corrections. `if rm:` guard. |
| Agent not in POLICY | No-op walk; still writes the sentinel. Useful for agents that haven't yet declared policy. |
| Multiple fan-out arrays present on one trace | All are walked in a fixed order: `per_step_reviews`, `per_behavior_reviews`, `per_page_reviews`. Top-level verdict is only forced by policy entries that explicitly set `top_level_verdict`. |
