# Step 5.5 Evidence Validator — Rollout Runbook

Single source of truth for the `validate-step55-evidence.py` warn → deny
rollout. Created as the post-#1272 follow-up companion to:

- `.claude/scripts/validate-step55-evidence.py` (the validator itself)
- `.claude/patterns/template-coherence-rules.json` rule
  `validator-env-prefix-required-step55-evidence` (severity=warn during soak;
  flips to severity=block in the deny-mode commit)
- `.runs/step55-soak-telemetry.jsonl` (telemetry written by the validator
  on every invocation)

## Status

| Phase | Default `STEP55_EVIDENCE_MODE` | state-registry.json prefix | Coherence rule for prefix |
|-------|--------------------------------|----------------------------|-----------------------------|
| **Now (warn-mode soak)** | `"warn"` | (absent) | (rule entry not yet added; infra ready) |
| **After soak passes** | `"deny"` | `STEP55_EVIDENCE_MODE=deny` | rule entry added at severity=block |

The flip is a **single follow-up PR** — see "Deny-mode flip checklist" below.

The coherence-rule schema + handler that supports the env-prefix sub-check
already shipped in this PR (`.claude/scripts/lib/linter/runner.py`
`check_validator_integration_required`). Adding the rule entry that
references `validate-step55-evidence.py` with
`required_env_prefix=STEP55_EVIDENCE_MODE=deny` is a one-block JSON
addition in the deny-mode flip PR.

## Soak Criterion (machine-checkable)

The deny-mode flip is sanctioned only when this query returns exit 0:

```bash
python3 -c "
import json, sys
try:
    entries = [json.loads(l) for l in open('.runs/step55-soak-telemetry.jsonl') if l.strip()]
except FileNotFoundError:
    print('no telemetry yet — soak window not started', file=sys.stderr)
    sys.exit(1)
recent = entries[-10:]
if len(recent) < 10:
    print(f'only {len(recent)} runs in telemetry; need 10', file=sys.stderr)
    sys.exit(1)
clean = [e for e in recent
         if e.get('verdict') != 'fail'
         and e.get('violation_count', 0) == 0
         and e.get('mode') == 'warn']
if len(clean) < 10:
    failures = [e for e in recent if e not in clean]
    print(f'soak NOT clean: {len(clean)}/10 runs are clean', file=sys.stderr)
    print(f'recent failures: {json.dumps(failures, indent=2)}', file=sys.stderr)
    sys.exit(1)
print('soak passed: 10/10 recent runs are clean warn-mode')
sys.exit(0)
"
```

Exit 0 → deny-mode flip is sanctioned. Exit 1 → extend soak window; do NOT flip.

**Threshold rationale**: 10 consecutive clean warn-mode runs.
- Mirrors `bootstrap-phase-a-write-guard.sh`'s multi-slice soak precedent
  (slice 3 warn → slice 4 deny after empirical evidence).
- Large enough to span landing + full + visual scope variants per current
  team usage of `/verify`.
- Small enough to clear in roughly one sprint of normal development.

## Telemetry Schema

Each `validate-step55-evidence.py` invocation appends one JSON-line record
to `.runs/step55-soak-telemetry.jsonl`:

```json
{
  "timestamp": "<ISO 8601>",
  "run_id": "<verify-...|change-...|bootstrap-...>",
  "mode": "warn | deny",
  "verdict": "skip | pass | fail",
  "skip_reason": "no_sidecar | pre_cutoff_grandfather | sidecar_v1 | no_slots",
  "slot_count": 0,
  "violation_count": 0,
  "violation_categories": [
    "missing_screenshot", "dim_below_min", "missing_provenance",
    "duplicate_provenance", "missing_evaluation_notes", "dom_unbound",
    "sampling_floor_unmet", "malformed_sidecar", "missing_schema_version"
  ]
}
```

`skip_reason`, `slot_count`, `violation_count`, `violation_categories` are
all optional — present only when meaningful for the verdict.

The writer is best-effort: any `OSError` is swallowed (telemetry must never
break the validator). Records are skipped silently when no `run_id` is
available (manual CLI invocation outside a skill context).

## Rollback Procedure

The validator reads `STEP55_EVIDENCE_MODE` on every invocation (no caching),
so rollback takes effect on the next state-3b VERIFY without lifecycle
restart. Three documented locations to set:

1. **Developer terminal** (immediate, scoped to current shell):
   ```bash
   export STEP55_EVIDENCE_MODE=warn
   ```
   Then re-run the failing `/verify` invocation.

2. **CI workflow** (team-wide rollback):
   ```yaml
   # .github/workflows/ci.yml
   env:
     STEP55_EVIDENCE_MODE: warn
   ```

3. **Hotfix in lifecycle-finalize.sh** (template-wide rollback before a
   CI deploy):
   Prefix the validator invocation in `state-registry.json`'s `3b` verify
   command with `STEP55_EVIDENCE_MODE=warn`. This overrides whatever the
   validator's compiled-in default is.

After rollback: investigate the violations in
`.runs/step55-soak-telemetry.jsonl` (most recent records have
`violation_categories[]`), fix the producer-side issue (usually a
scaffold-images change that broke the sidecar shape, or a design-critic
change that broke the candidate-evidence contract), then re-run the soak.

## Deny-mode Flip Checklist (single follow-up PR)

When the soak query returns exit 0, the follow-up PR makes ONE atomic
commit with all four changes — splitting risks the gate firing on stale
state-registry.json before the validator default is flipped, or vice versa.

1. **`.claude/scripts/validate-step55-evidence.py` line 84**:
   ```python
   return os.environ.get("STEP55_EVIDENCE_MODE", "warn").lower()
   ```
   change `"warn"` → `"deny"`.

2. **`.claude/patterns/state-registry.json` `verify.3b.verify`**:
   prefix `STEP55_EVIDENCE_MODE=deny ` to the
   `python3 .claude/scripts/validate-step55-evidence.py` invocation.

3. **`.claude/patterns/template-coherence-rules.json`**:
   add a NEW rule entry (the schema + handler already ship in
   commit `7d16faa` of the post-#1272 PR) — exercises the env-prefix
   sub-check infra:
   ```json
   {
     "id": "validator-env-prefix-required-step55-evidence",
     "type": "validator_integration_required",
     "severity": "block",
     "validators": [{
       "path": ".claude/scripts/validate-step55-evidence.py",
       "required_env_prefix": "STEP55_EVIDENCE_MODE=deny"
     }],
     "integration_points": [{
       "path": ".claude/patterns/state-registry.json",
       "executable_keys": ["verify"],
       "state_value_executable": true
     }],
     "description": "post-#1272 deny-mode flip drift detection — once the prefix is established, accidental removal would re-create the warn-mode bypass that the soak gate paid down."
   }
   ```

4. **`.claude/scripts/tests/fixtures/linter_baseline/baseline_*.json`**:
   should still all be at zero `cross_file_contradiction` because
   step 2 added the prefix that step 3's rule requires. Regenerate
   to confirm.

PR title should use `Closes #1272` syntax. #1257 is addressed by the
page-batched architecture (PR #1357 — fix/1257-page-batching). The
soft-exit primitive that commit `a20e55a` introduced was removed in
that fix as a #844-class anti-pattern; #1257 now closes on production
attestation (first observed `provenance=lead-merge` aggregate trace
from a real /verify run on a >8-page web-app), not on test ship.

## #1257 Attestation Telemetry

The page-batched merger (`merge-design-consistency-checker-traces.py`)
emits one raw-fields telemetry record to
`.runs/consistency-soak-telemetry.jsonl` on every multi-batch run
(`partition_size > 1`). Single-batch runs are skipped — single-batch
projects do not exercise the architecture under attestation. Telemetry
emission is best-effort: any `OSError` is swallowed so writer failure
cannot break the merger.

### Record schema

```json
{
  "timestamp": "<ISO 8601>",
  "run_id": "<verify-... | change-... | bootstrap-...>",
  "provenance": "lead-merge",
  "partition_size": <int>,
  "contributing_spawn_indexes_count": <int>,
  "contributing_spawn_indexes": [<int>, ...],
  "pages_reviewed_total": <int>,
  "verdict": "pass | fail",
  "status": "completed"
}
```

The record stores **raw fields only — no precomputed `attesting` flag**.
The closure criterion is applied at READ time by
`check-1257-attestation.py` so future criterion changes (e.g., raising
the page threshold) do not strand existing records (R2 critic concern
`8cf178ea45ab`).

### Closure-check helper

```bash
python3 .claude/scripts/check-1257-attestation.py
# exit 0 + stdout "ATTESTED: <record>"  — at least one record satisfies the criterion
# exit 1 + stderr "NOT ATTESTED: ..."   — telemetry exists but no record attests
# exit 1 + stderr "no telemetry yet"    — telemetry file absent or empty
```

Argparse `--telemetry-path <path>` overrides the default
`.runs/consistency-soak-telemetry.jsonl`.

### Closure criterion

```
provenance == "lead-merge"
AND contributing_spawn_indexes_count >= 2
AND contributing_spawn_indexes_count >= partition_size   # full batch coverage
AND pages_reviewed_total >= 12
AND status == "completed"
```

The original PR #1357 body documented the 3-tuple (lead-merge / csi>=2 /
pages>=12 / status=completed). The 4th clause `csi_count >= partition_size`
was added by post-merge first-principles audit of PR #1412 because the
3-tuple alone admitted a partial-spawn false-positive:

- State-3b VERIFY catches partial-spawn at pipeline-time
  (`assert len(csi) >= len(partition)`).
- The merger writes telemetry BEFORE state-3b VERIFY runs.
- A partial-spawn run thus leaves an `status="completed"` record on disk
  (merger hardcodes status because the merger itself completed).
- Without the 4th clause, the helper could later read this stranded record
  and falsely declare `ATTESTED`.

The 4th clause closes the asymmetric-defense gap by mirroring state-3b
VERIFY's gate-time check at READ-time. Symmetry between gate-time and
audit-time predicates is a strong first-principles design signal.

### Manual closure (NOT auto-close)

Operator runs `gh issue close 1257` after the helper returns `ATTESTED`.
Auto-close from a runtime path is intentionally not implemented:
(a) any compromised `/verify` run could otherwise close architectural
issues; (b) `gh` CLI auth in template scripts adds blast radius;
(c) `step55-evidence-rollout` precedent keeps closure decisions manual.

### Iteration over stamped artifacts

`.runs/consistency-soak-telemetry.jsonl` is a `.jsonl` file, explicitly
excluded from GRAIM canonical classification by
`derive-graim-manifest.py:52` `RE_RUNS_JSON` negative lookahead
`(?![a-zA-Z0-9])`. No registration is possible or required.

The companion JSON artifact `.runs/consistency-check-prepass.json`
(read by the new state-3b VERIFY assertion and by the merger) IS
canonical and goes through `write-gate-artifact.sh`, which stamps
3 fields (`skill`, `run_id`, `written_at`). The VERIFY assertion and
merger both use **explicit key access** (`prepass.get('partition')`)
to avoid iterating over the stamp fields. For future iterators that
must traverse the prepass payload, use
`.claude/scripts/lib/verify_helpers.py:unstamped_values()` to filter
the stamp fields out (Group A coherence guidance).

## Producer Contract (scaffold-images Step 5b)

After the schema-version birthplace move (`.claude/procedures/scaffold-images.md`
Step 5b), every new sidecar MUST include `"schema_version": 2` as the
first key:

```json
{
  "schema_version": 2,
  "generated_at": "<ISO 8601>",
  ...
}
```

Pre-cutoff sidecars (no `schema_version` field) on pre-cutoff runs are
grandfathered (validator SKIPs). Post-cutoff runs encountering an unstamped
sidecar BLOCK in deny mode (producer-side drift). See
`.claude/scripts/validate-step55-evidence.py:main()` for the decision matrix.

## Migration for Legacy Projects

**Symptom**: a project that ran `/bootstrap` between the cutoff
(`2026-05-04T05:25:30Z`) and PR #1309 merge (`2026-05-06`) has a
post-cutoff `run_id` BUT a sidecar without `schema_version`. This is
because `scaffold-images` started stamping `schema_version: 2` only after
PR #1309. On warn mode (today) the validator emits a "missing
schema_version" violation in telemetry — soak query treats this as
non-clean, **soak never passes** until the legacy sidecar is migrated.
On deny mode (after flip) the validator BLOCKs.

**Fix**: run the migration script once per affected project, then re-run
`/verify`:

```bash
python3 .claude/scripts/migrate-image-candidates-v2.py
# → "stamped v2" on first run; "already v2" on subsequent runs (idempotent)
```

The script:
- adds `"schema_version": 2` as the first key in `.runs/image-candidates.json`
- preserves all other fields verbatim
- atomic write (temp + rename) so a SIGINT mid-write cannot corrupt the file
- returns exit 0 even when sidecar is absent (safe to wire into pre-flight)
- exit 1 only on malformed JSON

**When to run**: any time the soak query reports that the latest entry
in `.runs/step55-soak-telemetry.jsonl` has
`violation_categories: ["missing_schema_version"]`. Once 10 clean
warn-mode runs accumulate after the migration, the deny-mode flip is
sanctioned.

**Detection (CI helper)**: the deny-mode flip PR may wire this script
into `.claude/skills/verify/state-2a-*.md` or `lifecycle-finalize.sh` as a
one-shot pre-flight migration so future legacy bootstraps auto-resolve
without operator action. This is intentionally NOT done in this PR — the
script is opt-in, operator-driven, to keep the blast radius minimal during
the soak window.
