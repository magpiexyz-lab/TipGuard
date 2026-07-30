# Context Initialization

Shared procedure for creating a skill's `.runs/<skill>-context.json` file during lifecycle initialization (`lifecycle-init.sh`), with extra fields merged at STATE 0 when needed.

## Base Schema (required fields)

| Field | Type | Value |
|-------|------|-------|
| `skill` | string | Physical running skill (e.g., `"solve"`, `"verify"`). **Protected** — callers cannot override via `extra_json`. |
| `branch` | string | `$(git branch --show-current)` |
| `timestamp` | string | ISO 8601 UTC: `$(date -u +%Y-%m-%dT%H:%M:%SZ)` |
| `run_id` | string | `<skill>-<timestamp>` (e.g., `"solve-2026-04-08T03:30:56Z"`) |
| `completed_states` | array | `[]` |
| `parent` | object \| null | `{skill, run_id}` of the immediate parent when embedded; `null` when top-level |
| `ancestors` | array | Full chain root→immediate-parent as `[{skill, run_id}, ...]`; `[]` when top-level |
| `attributed_to` | string | Q-score / retrospective attribution target; defaults to `skill` when top-level |
| `completed` | boolean | `false` at init; set `true` by `lifecycle-next.sh` on `EMBED_COMPLETE` or by `lifecycle-finalize.sh` at end-of-run |

All fields are consumed by infrastructure (`advance-state.sh`, `lib-state.sh`, `lib-core.sh::resolve_active_identity`, `state-completion-gate.sh`, `verify-pr-gate.sh`, `agent-gate-check.py`).

### `skill` vs `attributed_to`

Two different questions get two different fields:

| Purpose | Read field |
|---|---|
| "Which skill's state machine is running right now?" (logging, hook logic, state-registry lookup) | `skill` |
| "Which skill should Q-score / retrospective / analytics attribute this run to?" (metrics, dashboards) | `attributed_to` |

In the top-level case (no embedding) they are equal by default. Only when skill X embeds skill Y do they diverge: Y's context has `skill=Y` and `attributed_to=X`. This separation is the coherent fix for issue #941, which was rooted in a single `skill` field trying to serve both purposes simultaneously.

## Script Interface

```bash
bash .claude/scripts/init-context.sh <skill> [extra_json]
```

- `$1` — skill name (required). Exit 1 if missing.
- `$2` — extra JSON fields (optional). Merged into base via `dict.update`.
- Output: `.runs/$1-context.json`
- When `$2` is empty: pure bash heredoc (no python3 dependency).
- When `$2` has content: python3 merges base + extra.
- When `$2` starts with `@`: read extra JSON from the referenced file path (e.g., `@.runs/_extra.json`). Avoids shell quoting issues for values with special characters.
- **Guard behavior** (priority order — `has_identity` checked first to support checkpoint resumption):
  - No file exists → create (base + extra)
  - File + `run_id`, no extra → skip (already initialized, safe for resumption)
  - File + `run_id` + extra → merge extra fields into existing context (protects `branch`, `timestamp`, `run_id`)
  - File exists, no `run_id`, `completed_states` length > 1 → block (corrupt state)
  - File exists, no `run_id`, `completed_states` length ≤ 1 → overwrite (replace stub with canonical context)

## Extra Fields by Skill

| Skill | Extra fields |
|-------|-------------|
| change | `preliminary_type`, `affected_areas`, `solve_depth` (all null) |
| deploy | `deploy_mode` ("initial"), `added_services`, `removed_services`, `unchanged_services` (all []) |
| distribute | `phase` (integer: 1 or 2) |
| resolve | `issue_list` ([]) |
| upgrade | `dry_run` (false) |
| verify | `scope`, `archetype`, `quality` ("production"), `mode`, `baseline_available`. **Note**: `skill` is no longer an extra-json-overridable field — callers embedding verify must use `--embed` (lifecycle-init derives `parent`/`ancestors`/`attributed_to` from the calling skill's context automatically). |
| iterate-check | `mode` ("check"), `channel`, `campaign_name`, `campaign_id`, `campaign_age_days`, `budget_total_cents`, `budget_daily_cents`, `max_cpc_cents`, `completed_states` (["c0"]) |
| iterate-cross | `mode` ("cross"), `mvp_count`, `mvps` (array), `completed_states` (["x0"]) — uses @file mechanism |

## Relationship to advance-state.sh

`lifecycle-init.sh` **creates** the canonical context file (base schema) during Phase 1. For skills with extra fields, STATE 0 **merges** extra fields into the existing context via `init-context.sh`. `advance-state.sh` **appends** to `completed_states` after each state's postconditions pass. Together they form the lifecycle: init → merge (if extra) → advance → advance → ... → completed.
