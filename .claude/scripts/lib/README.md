# `.claude/scripts/lib/` — Reusable helpers

Python helpers + bash utilities reusable across template scripts. Keep this directory **small and load-bearing** — only add a helper here when 2+ callers will use it (per CLAUDE.md Rule 4: 3+ similar lines is better than premature abstraction; new lib entries should beat that bar with concrete reuse, not hypothetical).

## Discovery convention

When a helper is intentionally **template-level reusable** (i.e. designed to be the canonical mechanism for solving a class of problem in any future fix), document it with a `## Stack Knowledge` section below. The convention mirrors `.claude/stacks/**/*.md` `## Stack Knowledge` sections so that:

- `/solve` Phase 1 Agent 2 (Prior Art) can grep `composite_identity` and surface the entry as `fix_template` candidate
- `/resolve` diagnosis can locate prior solutions for similar issues
- Future PRs that re-invent an existing solution get caught at review

This is the runtime-discoverable side of the auto-discovery mechanism (#1285) — solving the "reusables built by one /solve are invisible to the next" problem incrementally for the helpers that are most likely to be reused.

Helpers NOT intended for reuse (one-off utilities, single-caller adapters) should NOT have a `## Stack Knowledge` section. The conservative bar: add when first concrete second caller demonstrates reuse value, not on first introduction.

---

## Stack Knowledge

### Iterate-cross Phase-1 relaunch window
```yaml
id: iterate-cross-phase1-relaunch-window
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: phase1-relaunch-pools-failed-flight-with-retest-window
  divergence_pattern: stale-denominator-drags-conversion-rate-across-a-relaunch
  stack_scope: scripts/lib/iterate_cross_relaunch
composite_identity_hash: d83d723d702b
symptom_keywords: [iterate-cross, phase1_relaunch_at, relaunch, retest, stale-denominator, window-lower-bound, greatest, campaign-start-date]
confidence_score: 0.85
occurrence_count: 1
linked_issues: []
first_seen: 2026-07-20
last_seen: 2026-07-20
graduated_to: null
prevention_mechanism: |
  iterate_cross_relaunch.py is the single source of truth for per-MVP Phase-1
  relaunch date math. parse_relaunch_at validates the ISO config value;
  posthog_lower_bound_expr / postgres_lower_bound_expr emit a
  max(rolling-window, relaunch) lower bound for HogQL and Postgres queries;
  campaign_passes_relaunch decides whether a GA campaign's Start date qualifies.
  Every consumer (state-x0a GA merge, state-x0b DB ground truth, state-x2
  PostHog signup count) calls these helpers — the date/window logic is never
  inlined at a call site, so a relaunched MVP is scored on relaunch-onward data
  consistently across all three surfaces.
fix_template: |
  To scope any windowed Phase-1 query to a relaunch date, read the MVP's
  phase1_relaunch_at (relaunch_at_for), then replace the literal
  `now() - INTERVAL <n> DAY` / `now() - INTERVAL '<n> days'` lower bound with
  posthog_lower_bound_expr / postgres_lower_bound_expr. For GA campaign
  attribution, gate each campaign on campaign_passes_relaunch(start_date,
  relaunch_at). Never compare dates or build the greatest() expression inline.
```

### Iterate-cross redacted email signup filter
```yaml
id: iterate-cross-redacted-email-signup-filter
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: db-ground-truth-counts-include-team-test-fixtures
  divergence_pattern: raw-db-signups-promote-or-suppress-verdicts-without-real-user-filter
  stack_scope: scripts/lib/iterate_cross_email_filter
composite_identity_hash: 9d41553a060b
symptom_keywords: [iterate-cross, db_signups, email_filter, pii-redaction, team-emails, test-emails, signup-fixtures, gmail-normalize, plus-alias]
confidence_score: 0.9
occurrence_count: 2
linked_issues: [1482]
first_seen: 2026-05-21
last_seen: 2026-05-21
graduated_to: null
prevention_mechanism: |
  iterate_cross_email_filter.py is the canonical deterministic filter for
  email-bearing signup rows from both Supabase and Railway. It classifies
  rows into real/team/test using operator-owned config, reserved test
  domains, team domains, Gmail normalization, and plus-alias handling.
  It returns only aggregate counts and redacted audit entries so .runs
  artifacts, team-message output, and HTML reports never persist full emails.
fix_template: |
  When a DB ground-truth integration reads signup rows, select email-bearing
  rows instead of count(*), call filter_signups(rows, config), and persist:
  db_signups_raw, db_signups_real, db_signups_team, db_signups_test,
  db_signups_filter_audit, db_signups_real_windowed, and db_first_signup_at.
  Never write raw email addresses to .runs artifacts; use redact_email().
```

### Supabase management-project ownership checks
```yaml
id: supabase-management-project-ownership-checks
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: mvp-database-project-lives-outside-team-org
  divergence_pattern: operator-cannot-validate-or-query-supabase-ground-truth-before-ads
  stack_scope: scripts/lib/iterate_cross_db
composite_identity_hash: c9a2765ab3f8
symptom_keywords: [supabase, management-api, project-ref, team-org, db-signups, ads-ready, iterate-cross]
confidence_score: 0.85
occurrence_count: 2
linked_issues: []
first_seen: 2026-05-21
last_seen: 2026-05-21
graduated_to: null
prevention_mechanism: |
  iterate_cross_db._read_token() and list_supabase_projects() are the
  canonical operator-authenticated Supabase project inventory path. Reusing
  the same token file and Management API enumeration for /ads-ready prevents
  drift between pre-ad ownership checks and /iterate --cross DB ground-truth
  collection.
fix_template: |
  When a template script needs to confirm that a Supabase project belongs to
  the operator-visible team org, parse the project ref from the MVP's
  NEXT_PUBLIC_SUPABASE_URL, call _read_token(), then call
  list_supabase_projects(token). Pass only when the project ref appears in the
  returned project list. Missing token is an operator auth failure; do not
  silently skip the ownership check.
```

### Railway Postgres ground-truth access (CLI + psql)
```yaml
id: railway-postgres-ground-truth-access
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: mvp-database-hosted-on-railway-not-supabase
  divergence_pattern: db-ground-truth-pass-skips-railway-backed-mvps
  stack_scope: scripts/lib/iterate_cross_railway_db
composite_identity_hash: 39daffc8b416
symptom_keywords: [railway, psql, database-public-url, pay-intent, db-signups, iterate-cross, phase2]
confidence_score: 0.85
occurrence_count: 2
linked_issues: []
first_seen: 2026-07-27
last_seen: 2026-07-27
graduated_to: null
prevention_mechanism: |
  iterate_cross_railway_db owns the canonical Railway access path: CLI auth
  probe (_check_railway_auth), psql availability probe (_check_psql_available),
  per-project DATABASE_PUBLIC_URL resolution inside a tempdir
  (get_database_url — never links the caller's cwd), and tab-separated SQL
  execution (_psql_query). Any pass that needs Railway-hosted Postgres ground
  truth (state-x0b signups, x5 phase2 pay-intents) must import these helpers
  instead of shelling out to railway/psql directly — duplicate subprocess
  plumbing drifts on auth failure modes and URL preference
  (DATABASE_PUBLIC_URL over the internal DATABASE_URL).
fix_template: |
  Import _check_railway_auth / _check_psql_available / get_database_url /
  _psql_query from iterate_cross_railway_db. Gate the pass on both probes
  (auth, psql) and degrade to a non-halting per-MVP reason when either fails.
  Resolve the DB URL per MVP from mvp_mappings.<name>.railway_project_id
  (+ railway_service_name, default "Postgres"); treat a missing URL as
  railway_service_missing, never as an empty dataset. Run SQL only via
  _psql_query and parse its tab-rows ("" means NULL).
```

### gate-evidence cross-reference protocol (GECR)
```yaml
id: gate-evidence-citation-protocol
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: gate-enforces-structural-shape-as-proxy-for-semantic-property
  divergence_pattern: gate-pass-signal-decoupled-from-evidence-source
  stack_scope: scripts/lib/gate_evidence_runner
composite_identity_hash: 7edfd62ca235
symptom_keywords: [gate, gate-keeper, evidence, citation, cross-reference, semantic-check, structural-proxy, synthetic-href, empty-stub, observe, BG2-WIRE, observation-pairing, nav-bar, dynamic-route, retrospective]
confidence_score: 0.85
occurrence_count: 2
linked_issues: [1473, 1470, 1468, 1456]
first_seen: 2026-05-18
last_seen: 2026-05-18
graduated_to: null
prevention_mechanism: |
  Declarative rules in .claude/patterns/gate-evidence-rules.json describe
  per-rule evidence sources, matchers, and failure citations. A generic
  runner (lib.gate_evidence_runner) loads rules through
  jsonschema.validate() against gate-evidence-rule-schema.json, resolves
  evidence sources via glob+reader (json | jsonl | grep_tsx | filesystem),
  applies matchers (template_literal_navigation | friction_event_extraction
  | recovery_skip_extraction | any_of_patterns), and emits structured
  failures with citations. Each rule honors a MODE env var (warn|deny) +
  schema_version_gate.required_schema_version() for soak-then-flip rollout
  and pre-cutoff grandfathering.

  Two seed rules ship with the foundation:
    - bg2-wire-nav-reachability (#1473): for dynamic-only pages
      (derive_dynamic_only_pages classification == "dynamic-only"),
      REPLACE bare-slug href requirement with template-literal navigation
      requirement (`<Link href={`/<page>/${...}`}>` somewhere under
      src/app/**/*.tsx or src/components/nav-bar.tsx). For "static" pages,
      preserve current bare-slug semantics. For "mixed" pages, require BOTH.
    - agent-workaround-pairing (#1470): cross-references friction events
      from .runs/agent-traces/*.json (workarounds[] +
      template_gap_observed[]) and .runs/verify-recheck.json
      (verify_results[].passed=false) against
      .runs/retrospective-filed-findings.json filed[] OR
      .runs/retrospective-result.json suppressions[] (with rationale).
      Unpaired events fail the gate with specific citation.

  Meta-coverage lint rule rule_gate_verdict_evidence_coverage
  (template-coherence-rules.json) enforces that every structural-shape
  gate-keeper check (test -f / test -d / grep -E.*href / grep -c) is
  either covered by a rule in gate-evidence-rules.json OR carries an
  explicit evidence_check_intentionally_structural annotation. Prevents
  meta-level structural-proxy regression where new gate-keeper checks
  silently revert to gameable shape-only enforcement.

  Solve-critic Vector 8 (field-citation-verification) catches the
  recurring "design cites field name without grep-verifying it exists in
  the cited source file" failure mode that produced 4/9 round-2 TYPE A
  concerns during the originating /solve --defect run.

fix_template: |
  When a gate's pass-signal is currently a structural shape check (file
  existence, key presence, literal substring match) but the gate's INTENT
  is a semantic property (route reachability, observation fidelity,
  recovery-path validity), add a new rule to
  .claude/patterns/gate-evidence-rules.json:

    {
      "id": "<gate-id>-<purpose>",
      "type": "navigation_reachability | friction_event_extraction | recovery_path_observation",
      "gate_id": "<gate-id>",
      "severity": "warn",  # flip to block after soak (1-2 real skill cycles)
      "evidence_sources": [
        {"path_glob": "<glob>", "reader": "json|jsonl|grep_tsx|filesystem",
         "always_included_paths": ["..."]}
      ],
      "matcher": {"kind": "<matcher>", "params": {...}},
      "expected_observation": {
        "artifact_path": "<runtime-artifact>",
        "predicate": "exists_with_citation | array_non_empty | matches_friction_count",
        "params": {...}
      },
      "failure_citation_format": "<jinja-style template>",
      "mode_env": "GATE_EVIDENCE_<NAME>_MODE",
      "schema_cutoff": true
    }

  The gate-keeper.md (or check-observation-artifacts.sh) numbered check
  then delegates to:
    python3 .claude/scripts/verify-gate-evidence.py --rule-id <rule-id>
  Exit 0=PASS, 1=BLOCK, 2=infrastructure-error.

  Soak strategy (#1291 convention):
    1. severity="warn" + MODE=warn for 1-2 real skill cycles
    2. Inspect .runs/ for false positives via `verify-linter.sh` output
    3. Flip severity="block" and document in follow-up PR
    4. Default MODE remains "warn"; deny-mode opt-in via env var

  Round-2 critic guards baked into the runner:
    - jsonschema.validate() at load (Plan-Agent-A Open Risk 1: malformed
      registry produces SystemExit(2) with schema path, not stack trace)
    - Slug-suffix awareness in matchers (round-2 Concern 487fdf73cf62):
      hyphenated experiment.yaml slugs (`portfolio-detail`) resolve to
      static-prefix folders (`portfolio/[slug]`); the matcher searches
      for both forms
    - rg-style multi-line matching for template literals (BG2 check 18
      pattern; round-2 Concern Plan-Agent-B-8)
    - Optional catch-all (`[[...slug]]`) classified as static (round-2
      Concern Plan-Agent-B-2 inversion: optional matches `/` so bare slug
      IS reachable)

  Usage from a Python validator or gate-keeper invocation:
    from lib.gate_evidence_runner import load_rules, run_rule, format_failure
    rules = load_rules()
    for rule in rules:
        mode, failures = run_rule(rule)
        # ... format and emit
```

### Observation-Anchored Recovery Contract (OARC)
```yaml
id: observation-anchored-recovery-contract
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: fallback-writer-produces-schema-valid-but-depth-incomplete-artifact
  divergence_pattern: structural-gate-accepts-stub-without-paired-observation
  stack_scope: scripts/lib/gate_evidence_runner-recovery_skip_extraction
composite_identity_hash: 97f0cc6a5f1a
symptom_keywords: [fallback, recovery, self-degraded, lead-orchestrated, sparse-trace, init-stub, candidates-tried-zero, step-5.5-skipped, post-completion, recovery_validated, partial-trace]
confidence_score: 0.85
occurrence_count: 7
linked_issues: [1468, 1456, 1042, 1061, 1189, 1196, 1303, 1437]
first_seen: 2026-05-18
last_seen: 2026-05-18
graduated_to: null
prevention_mechanism: |
  Sibling pattern to EARC (Evidence-Anchored Repair Channel, #1189). Any
  agent-traces/*.json writer path that produces a schema-valid artifact
  under exceptional / recovery / post-completion conditions MUST either:
    (a) write the full schema with real data, OR
    (b) appear as a candidate row in retrospective-pending-findings.json
        (paired observation) that the lead files or suppresses.

  Detection runs at observation-phase Step 5a via two GECR rules
  (.claude/patterns/gate-evidence-rules.json):

    - recovery-path-skip-pairing (#1468): traces with provenance in
      {self-degraded, recovery, lead-orchestrated} AND partial=true AND
      a non-sanctioned degraded_reason AND a detectable skipped depth-
      check (landing: candidates_tried==0 with unused sidecar candidates;
      non-landing has_images=true: image_issues_for_landing key absent).

    - sparse-trace-pairing (#1456): traces with status="started" + no
      verdict (init-stub survived), OR provenance="lead-orchestrated"
      missing AOC v1.3 required fields (workarounds[] /
      template_gap_observed[]).

  Both rules use the recovery_skip_extraction matcher in
  gate_evidence_runner.py and emit candidates via two new enumerator
  kinds (recovery-path-skip, sparse-trace) in
  enumerate-pending-retrospective-findings.py. The matches_friction_count
  predicate requires the candidate to be either filed via
  file-retrospective-finding.py OR suppressed in retrospective-result.json
  suppressions[] with a closed-enum reason.

  Sanctioned legitimate-skip degraded_reasons (empty-boundary-fast-path
  from #1061, demo-mode-fixture-short-circuit from #1042,
  redirect-source-only from #1196) are anchored to the canonical list in
  .claude/scripts/lib/sanctioned_degraded_reasons.py — adding a new
  sanctioned skip requires editing exactly one file (no drift between
  merge-design-critic-traces.py carve-out and the matcher suppression).

  Phase C cutover criteria for both rules: see
  .claude/patterns/gecr-cutover-criteria.json + verify-linter rule
  gecr-cutover-overdue (closes the #1437/#1415 meta-pattern where soak-
  mode advisory-only carve-outs were forgotten and permanently weakened
  enforcement).

fix_template: |
  When a new fallback writer path is introduced (or an existing one
  surfaces a regression), register the OARC mechanism BEFORE shipping:

    1. If the fallback shape isn't captured by recovery-path-skip or
       sparse-trace, extend the recovery_skip_extraction matcher in
       gate_evidence_runner.py with a new sub-kind (mirror existing
       handlers ~lines 440+).

    2. Add a corresponding enumerator function to
       enumerate-pending-retrospective-findings.py mirroring
       _candidates_from_sparse_traces. Register the kind in
       KIND_PRIORITY (assign next sequential rank) and append to main().

    3. Register a new GECR rule in .claude/patterns/gate-evidence-rules.json
       with type="recovery_path_observation", matcher.kind=
       "recovery_skip_extraction", and matches_friction_count predicate
       targeting the new kind via params.target_kinds.

    4. Add the rule's mode_env entry to
       .claude/patterns/gecr-cutover-criteria.json with soak_window +
       deny_flip_trigger so the meta-defense linter tracks the cutover.

    5. Cover with unit tests in test_oarc_matcher.py.

  Sanctioned-skip carve-outs:
    - Append to .claude/scripts/lib/sanctioned_degraded_reasons.py
    - Document source PR/issue in .claude/agents/design-critic.md
      Rendered-Review Contract or equivalent sanctioned-skip section

example_callers:
  - .claude/agents/landing-images-critic.md (Step 5.5 self-degrade)
  - .claude/agents/solve-critic.md (round-2 post-completion)
  - .claude/scripts/merge-landing-critic-traces.py (sparse sub-trace handling)
  - .claude/scripts/merge-design-critic-traces.py (sparse sub-trace handling)
```

### perceptual-hash + provenance binding for image evidence
```yaml
id: image-evidence-provenance-phash
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: agent-fabricates-image-evidence
  divergence_pattern: physical-artifact-required-but-pixel-only-check-bypassable
  stack_scope: scripts/lib/phash
composite_identity_hash: 39ae7c5e3170
symptom_keywords: [image, screenshot, evidence, candidate, provenance, phash, fabrication, design-critic, candidates_tried]
confidence_score: 0.85
occurrence_count: 1
linked_issues: [1276, 1272, 1261, 1252, 1255]
first_seen: 2026-05-04
last_seen: 2026-05-04
graduated_to: null
prevention_mechanism: |
  phash.check_image_magic + read_provenance + validate_provenance_triple_unique
  enforce that every candidate has an independent (model, prompt_hash, seed)
  triple sourced from the generation provider — LLMs cannot fabricate triples
  the API never produced.
fix_template: |
  When validating that an LLM agent has actually produced distinct image
  candidates (not labeled the same image as N candidates), require BOTH:
    (a) magic-byte + min-dimension check on each file (phash.check_image_magic
        + check_image_min_dimensions)
    (b) sibling <image>.provenance.json with (model, prompt_hash, seed)
        triple, joined and asserted UNIQUE per candidate set
        (phash.read_provenance + validate_provenance_triple_unique)
  Pixel-only perceptual hash is bypassable by trivial transforms (rotate,
  re-compress) — round-2 critic Concern 1. The provenance triple is the
  load-bearing check: LLMs cannot fabricate a fal API generation parameter
  that the API never produced.

  Usage:
    from lib.phash import (
        check_image_magic, read_provenance,
        validate_provenance_triple_unique, validate_phash_diversity,
    )
    errors = []
    provs = []
    for cand in slot_candidates:
        if check_image_magic(cand) is None:
            errors.append(f"{cand}: not PNG/WebP")
            continue
        try:
            provs.append(read_provenance(cand))
        except FileNotFoundError:
            errors.append(f"{cand}: missing provenance JSON sibling")
    errors.extend(validate_provenance_triple_unique(provs))
```

### schema_version bound to run_id timestamp (downward-stamp defense)
```yaml
id: schema-version-run-id-binding
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: llm-stamps-old-schema-version-to-bypass-new-validators
  divergence_pattern: agent-controls-its-own-versioning-stamp
  stack_scope: scripts/lib/schema_version_gate
composite_identity_hash: 78138f4fc66c
symptom_keywords: [schema_version, backwards_compat, migration, runid, bypass, downward_stamp, validator_skip]
confidence_score: 0.70
occurrence_count: 1
linked_issues: [1276, 1272, 1261, 1252, 1255]
first_seen: 2026-05-04
last_seen: 2026-05-04
graduated_to: null
prevention_mechanism: |
  lib.schema_version_gate.check_artifact_schema_version binds the effective
  schema version to the run_id timestamp set by init-context.sh before any
  LLM action, so an agent cannot down-stamp schema_version to bypass a newly
  added v2 gate.
fix_template: |
  When adding required fields to .runs/ artifacts, do NOT trust agent-stamped
  schema_version. Bind the EFFECTIVE schema version to the run_id timestamp
  (set by init-context.sh BEFORE any LLM action via `date -u`):

    from lib.schema_version_gate import check_artifact_schema_version
    ok, msg, ver = check_artifact_schema_version(path, run_id)
    if not ok:
        sys.exit(1)  # downward-stamp blocked
    if ver < 2:
        sys.exit(0)  # grandfathered — skip new gates
    # ... enforce v2-required fields

  Replace MIGRATION_CUTOFF_ISO placeholder with the PR-merge commit
  timestamp via post-merge sed, so the gate is INERT until merge and
  active immediately after.
```

### validator meta-test (anti-softening property tests)
```yaml
id: validator-meta-test-pattern
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: future-pr-softens-validator-to-no-op
  divergence_pattern: hard-block-validator-survives-by-meta-property-test
  stack_scope: scripts/tests
composite_identity_hash: 4c517663dd57
symptom_keywords: [validator, softening, no-op, meta-test, ci, regression, defense-in-depth, cross-state, coverage-gap, aggregate-trace]
confidence_score: 0.75
occurrence_count: 2
linked_issues: [1276, 1272, 1261, 1252, 1255, 1294]
first_seen: 2026-05-04
last_seen: 2026-05-05
graduated_to: null
prevention_mechanism: |
  .claude/scripts/tests/test_validators_meta.py drives every hard-block
  validator with synthetic invalid input and asserts non-zero exit code,
  blocking future PRs from softening `assert <cond>` to `print("WARN");
  sys.exit(0)`. Cross-state coverage sub-pattern (added per #1294) extends
  the meta-test surface to enforce that every validator wired into
  state-registry.json appears in the VALIDATORS allowlist AND every
  scaffold-* spawn site has a downstream validator-state.
fix_template: |
  When shipping a hard-block validator (any script invoked by
  state-completion-gate.sh or lifecycle-finalize.sh that exit 1 on failure),
  ALSO add a meta-test in .claude/scripts/tests/test_validators_meta.py
  that exercises the validator with synthetic INVALID inputs and asserts
  non-zero exit code. This blocks future PRs from softening
  `assert <condition>` to `print("WARN"); sys.exit(0)`.

  Pattern (model after .claude/scripts/tests/test_validate_recovery.py):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_v_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        # Populate fixtures

    def test_synthetic_invalid_input(self):
        # Write malformed fixture
        result = subprocess.run(
            ["python3", str(VALIDATOR), ...],
            cwd=self.tmp, capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)

  CI auto-discovers .claude/scripts/tests/test_*.py via .github/workflows/ci.yml
  (do NOT place under top-level tests/ — that is NOT in CI discovery).

  ---

  Cross-state coverage sub-pattern (added per #1294).

  When a validator must run at MULTIPLE state-registry entries (e.g., one
  per spawn-site downstream), declare an explicit allowlist in VALIDATORS:

    "validate-X.py": {
      "ref_files": [".claude/patterns/state-registry.json"],
      "state_registry_states": [("bootstrap", "11b"), ("bootstrap", "11c"), ...],
    }

  Then add four cooperating meta-tests:
    D-2 explicit: each (skill, state_id) in state_registry_states must have
        the validator chained in its verify command.
    D-3 auto-discovery: walk `.claude/skills/**/state-*.md` for the canonical
        spawn marker `^\s*-\s*subagent_type:\s*<agent-prefix>-[a-z-]+\s*$`
        (line-anchored, MULTILINE). For each match, assert a downstream
        allowlisted state exists. Walks ALL skills — future scaffold-*
        spawns in /change /upgrade /resolve auto-fail until wired.
    D-4 superset: allowlist must cover every present spawn site (catches
        accidental allowlist deletions).
    D-5 inverse drift: every state-registry mention of the validator must
        appear in the allowlist (catches: maintainer wires a new state
        without updating VALIDATORS dict).

  Aggregate-trace propagation (sibling pattern).

  When a state-machine merges per-agent traces into an aggregate (e.g.,
  merge-scaffold-pages-traces.py merging scaffold-pages-<slug>.json into
  scaffold-pages.json), the merger MUST propagate validator-required
  schema fields into the aggregate. Validators glob over .runs/agent-traces
  and apply uniformly to per-agent and aggregate files; without
  propagation the aggregate fails the schema check. Mirror the merger's
  stub-skip partition in the validator (`if status=='started' and not
  verdict: return []`) so rate-limited stubs (#1190) don't trigger
  spurious failures.
```

### canonical-writer policy (Issue #1299)
```yaml
id: canonical-writer-policy-pattern
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: state-file-direct-write-antipattern
  divergence_pattern: json.dump-or-Write-instead-of-canonical-writer
  stack_scope: scripts/lib/write-gate-artifact
composite_identity_hash: 25b66de2169e
symptom_keywords: [canonical-writer, gate-readable, GRAIM, write-gate-artifact, identity-stamping, skill-run_id-written_at]
confidence_score: 0.95
occurrence_count: 1
linked_issues: [1299, 1198, 1217]
first_seen: 2026-05-01
last_seen: 2026-05-06
graduated_to: null
prevention_mechanism: |
  Two-layer defense:
    (1) Lint: gate_artifact_writer_enforcement rule
        (.claude/patterns/template-coherence-rules.json) scans state files,
        agents, patterns, procedures, and helper scripts for write-syntax
        tokens (with open(...,'w'|'a'), json.dump-with-open, > path,
        tee path, cat <<EOF > path) targeting paths declared in
        .claude/patterns/gate-readable-artifacts-canonical.json. Severity=warn
        during soak; flips to block in chore/canonical-writer-migration-deny.
        Read syntax (open(...,'r'), json.load, os.path.exists, [-f path],
        backtick prose) is allowlisted at line level (R2-C1 — avoids
        ~455-instance false-positive baseline).
    (2) Hook: gate-artifact-write-gate.sh (Write/Edit matcher, MODE=deny
        since #1217) blocks Write/Edit on manifest paths. Sibling
        gate-artifact-bash-write-guard.sh (Bash matcher, ships in
        chore/canonical-writer-migration-hook-warn) catches direct
        bash redirects, python -c with open() writes, and tee/cat <<EOF
        chains targeting manifest paths.
fix_template: |
  When writing to any path in .claude/patterns/gate-readable-artifacts-canonical.json,
  invoke .claude/scripts/lib/write-gate-artifact.sh with --path and --payload.
  Caller payload MUST NOT include skill/run_id/written_at — the writer
  auto-stamps them.

  Reference (in-skill, normal flow):
    PAYLOAD=$(python3 -c "
    import json
    print(json.dumps({'key': 'value'}))
    ")
    bash .claude/scripts/lib/write-gate-artifact.sh \
      --path .runs/foo.json \
      --payload "$PAYLOAD" \
      --skill <skill>

  Reference (post-completion, AOC v1.2):
    bash .claude/scripts/lib/write-gate-artifact.sh \
      --path .runs/foo.json \
      --payload "$PAYLOAD" \
      --source-run-id "$RUN_ID" \
      --source-skill "$SKILL_KEY"

  Canonical example: .claude/skills/deploy/state-3b-provision-host.md:64-97.

  When migrating an existing direct-write site, run
  .claude/scripts/codemod-canonical-writer.py --dry-run first; the codemod
  handles S1 (with open) and S2 (json.dump-with-open) mechanically and
  emits a manual-review queue for bash-interpolated, conditional, and
  multi-write payloads.
```

### canonical page-inventory derivation from experiment.yaml
```yaml
id: derive-pages-canonical-source-of-truth
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: count-based-consumer-recomputes-page-set-from-raw-golden_path
  divergence_pattern: re-implementation-of-page-derivation-instead-of-helper-call
  stack_scope: scripts/lib/derive_pages
composite_identity_hash: 6ebebee1607f
symptom_keywords: [page, golden_path, derive, count, inventory, scope_pages, validation_pages, design-critic, page-set-drift]
confidence_score: 0.90
occurrence_count: 1
linked_issues: [1042, 1300]
first_seen: 2026-04-15
last_seen: 2026-05-08
graduated_to: null
prevention_mechanism: |
  derive_pages.derive_scope_pages / derive_validation_pages / derive_public_paths
  are the single source of truth for "what pages must exist on disk" (SET) and
  "what is the user journey" (LIST). field_role_map rule
  (template-coherence-rules.json) forbids raw `golden_path` access for
  count-based purposes — every consumer must call these helpers.
fix_template: |
  When an agent or script needs to enumerate pages (for design-critic
  spawning, page-image manifest generation, scope verification, etc.), do
  NOT recompute from the raw user-journey field in experiment.yaml. Use the
  helpers:

    from lib.derive_pages import derive_scope_pages, derive_validation_pages
    pages = derive_scope_pages(experiment_yaml_dict)  # SET — must exist on disk
    journey = derive_validation_pages(experiment_yaml_dict)  # LIST — user flow

  The helpers handle auth-derived pages, behavior-derived pages, and
  archetype-specific rules uniformly. Raw access to that field is caught by
  field_role_map at lint time.
```

### shared paid-traffic gclid filter (cross-MVP attribution single-source-of-truth)
```yaml
id: paid-traffic-gclid-filter
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: paid-traffic-gclid-filter-inline-divergence
  divergence_pattern: hand-coded-gclid-filter-instead-of-helper-call
  stack_scope: scripts/lib/gclid_filter
composite_identity_hash: bf2967dd122c
symptom_keywords: [gclid, paid-traffic, $session_entry_gclid, properties.gclid, posthog, hogql, iterate-cross, attribution, length-filter, prefix-filter]
confidence_score: 0.9
occurrence_count: 1
linked_issues: [1427]
first_seen: 2026-05-13
last_seen: 2026-05-13
graduated_to: null
prevention_mechanism: |
  gclid_filter.PAID_GCLID_FILTER is the single HogQL fragment that any
  /iterate --cross query MUST use to filter for real Google Ads paid traffic.
  It combines (a) coalesce($session_entry_gclid, properties.gclid) for
  attribution-path robustness when PostHog SDK init loses the race against
  Next.js router URL cleanup, and (b) length>40 + prefix in {Cj, EAI, CIa}
  to exclude operator manual-test gclids (e.g. analytics-verify-* 32-char
  strings that slipped past the prior length>30 rule).
fix_template: |
  When a HogQL query needs to filter for real Google Ads paid traffic, do
  NOT hand-write `properties.$session_entry_gclid IS NOT NULL AND length...`
  inline. Import the shared filter:

    # Python f-string contexts (state-x1, state-x2, etc.):
    import sys; sys.path.insert(0, '.claude/scripts/lib')
    from gclid_filter import PAID_GCLID_FILTER
    sql = f"... WHERE {PAID_GCLID_FILTER} ..."

    # Bash contexts (state-x0, state-c2):
    PAID_GCLID_FILTER=$(python3 -c "import sys; sys.path.insert(0,'.claude/scripts/lib'); from gclid_filter import PAID_GCLID_FILTER; print(PAID_GCLID_FILTER)")
    cat > /tmp/q.json <<JSON
    {"query":{"kind":"HogQLQuery","query":"... WHERE $PAID_GCLID_FILTER ..."}}
    JSON

  The Python-side validator `is_real_gclid(s)` mirrors the SQL rule for
  unit-testable checks. All 4 query sites (state-x0 canonical, state-x0
  orphan, state-x1, state-x2) already read from this helper — state-c2 has
  no PostHog queries. Any new query MUST follow the same pattern.
```

### iterate-cross PostHog query batching helper
```yaml
id: iterate-cross-posthog-query-batching-helper
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: posthog-portfolio-query-cap-or-timeout
  divergence_pattern: single-shot-discovery-or-union-query-in-state-bash
  stack_scope: scripts/lib/iterate_cross_posthog_batch
composite_identity_hash: 875494305052
symptom_keywords: [iterate-cross, posthog, hogql, pagination, limit, offset, union-all, batch-size, discovery, signup-counts]
confidence_score: 0.9
occurrence_count: 1
linked_issues: []
first_seen: 2026-05-21
last_seen: 2026-05-21
graduated_to: null
prevention_mechanism: |
  iterate_cross_posthog_batch.py is the canonical execution helper for
  /iterate --cross PostHog queries that can grow with portfolio size. Discovery
  queries must use paginate_discovery_query(), which issues a single OFFSET-free
  query capped at page_size * max_pages and proves completeness with a short
  page. (Personal API keys — the auth /iterate --cross requires — reject OFFSET;
  these GROUP BY aggregates are one-row-per-MVP/host and bounded, so a capped
  LIMIT-only fetch is both correct and complete. It raises if the cap is hit.)
  Per-MVP UNION ALL query groups must use run_union_batches() so HogQL execution
  stays under timeout limits while preserving one concatenated results payload
  for downstream state code. Per-pair overlap queries must use
  compute_orphan_overlap(), whose multi-pass cooldown-resume (cooldown_seconds /
  failure_sleep_seconds / max_passes + the per-pair cache) absorbs the PostHog
  server-side circuit breaker that long windows trip ("query failed the same
  way 4 times in a row ... can run again in about 4 minutes").
fix_template: |
  In state bash, build the SQL parts in Python, import the helper from
  .claude/scripts/lib, read the posthog_query block from the operator config
  (experiment/iterate-cross-config.example.yaml documents it), and call:

    pq = (cfg.get('posthog_query') or {})
    rows, metadata = paginate_discovery_query(sql, values, project_id, api_key,
        page_size=200, max_time_seconds=int(pq.get('max_time_seconds', 120)))
    rows, metadata = run_union_batches(parts, values, project_id, api_key,
        batch_size=int(pq.get('union_batch_size_catalog', 5)),
        max_time_seconds=int(pq.get('max_time_seconds', 120)))

  Long windows (365d) need the small batch sizes and the raised timeout —
  never write a bare batch_size=20 literal into a state file. Write raw
  artifacts as {"results": rows, "<state_status_key>": metadata} and propagate
  the metadata into the gate-readable context/data artifact through the
  standard state artifact writer.
```

### shared selector for per-page design-critic traces (epoch suffix routing)
```yaml
id: design-critic-trace-epoch-selector
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: stale-trace-shadows-current-verdict-after-recovery-respawn
  divergence_pattern: per-page-trace-aggregation-and-gate-time-acceptance-drift
  stack_scope: scripts/lib/design_critic_trace_selector
composite_identity_hash: 896ff8a3b536
symptom_keywords: [design-critic, trace, epoch, per-page, aggregation, hard-gate, sibling-acceptance, drift]
confidence_score: 0.90
occurrence_count: 1
linked_issues: [1274, 1276, 1300]
first_seen: 2026-05-04
last_seen: 2026-05-08
graduated_to: null
prevention_mechanism: |
  Both write-time aggregation (merge-design-critic-traces.py) and gate-time
  sibling acceptance (evaluate-hard-gate-predicates.py:aggregate_ok) call
  design_critic_trace_selector.select_latest_per_page_traces. The two
  consumers cannot drift on which traces represent "current" verdicts.
fix_template: |
  When implementing logic that reads per-page design-critic traces, do NOT
  glob `.runs/agent-traces/design-critic-*.json` directly:

    from lib.design_critic_trace_selector import select_latest_per_page_traces
    traces = select_latest_per_page_traces(traces_dir)
    # traces: dict[page_key -> trace_path] where epoch-suffixed wins

  Direct glob misses the recovery-respawn epoch convention: a post-fix
  re-spawn writes design-critic-<page>.<epoch>.json which shadows the
  original. Both aggregator and gate must agree on which epoch wins.
```

### canonical bash command canonicalizer (heredoc-body false-positive defense)
```yaml
id: canonical-bash-command-canonicalizer
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: hook-regex-matches-protected-token-inside-heredoc-body
  divergence_pattern: shell-grammar-aware-stripping-required-not-string-substring
  stack_scope: scripts/lib/canonicalize_bash_command
composite_identity_hash: c47fd910cde5
symptom_keywords: [hook, bash, regex, heredoc, false-positive, protected-token, write-guard, canonicalize]
confidence_score: 0.85
occurrence_count: 1
linked_issues: [1298, 1300]
first_seen: 2026-05-05
last_seen: 2026-05-08
graduated_to: null
prevention_mechanism: |
  canonicalize_bash_command.strip_heredoc_bodies preserves the introducer
  line (cat <<EOF) but removes the body so hook regex matchers operate on
  the executable surface only — not on data that happens to contain
  protected substrings (writer names, manifest paths, etc.).
fix_template: |
  When a hook needs to scan a Bash command string for protected tokens
  (e.g., write-gate-artifact.sh enforcement), do NOT grep raw $COMMAND:

    from lib.canonicalize_bash_command import canonicalize
    canonical = canonicalize(raw_bash_command)
    # canonical: heredoc bodies stripped, comments preserved
    if PROTECTED_TOKEN in canonical:
        deny(...)

  Raw substring match has a documented false-positive class (#1298): a
  heredoc body containing the writer name (e.g., the README itself) trips
  the guard. The canonicalizer fixes three separate correctness bugs vs.
  the inline strip_heredoc_bodies that previously lived in
  check-advance-state-invocation.py.
```

### CSS/className parser for emitted JSX (slot-intent drift detection)
```yaml
id: jsx-render-context-parser
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: declared-render-intent-drifts-from-observed-jsx
  divergence_pattern: shared-parser-required-by-migration-and-drift-detector
  stack_scope: scripts/lib/render_context
composite_identity_hash: 2c16d7c7be23
symptom_keywords: [slot-intent, jsx, render, css, classname, drift, migration, image-generation]
confidence_score: 0.85
occurrence_count: 1
linked_issues: [1077, 1300]
first_seen: 2026-04-20
last_seen: 2026-05-08
graduated_to: null
prevention_mechanism: |
  render_context.extract_render_from_text + find_image_usages + compute_effective_weight
  are shared by migrate-slot-intent.py (legacy backfill) and
  check-slot-intent-drift.py (state-2b drift detector). Both consumers
  parse JSX with identical heuristics — no recomputation drift.
fix_template: |
  When inferring slot intent from JSX (image rendering context, classNames,
  effective weights), call the shared parser:

    from lib.render_context import extract_render_from_text, find_image_usages
    intent = extract_render_from_text(jsx_source)
    usages = find_image_usages(jsx_source)

  The heuristics cover className-based size/aspect inference, Image
  component prop extraction, and Tailwind-utility weight computation. New
  rendering patterns belong in this helper, not in a downstream consumer.
```

### recurrence_guard typed schema parser (RMG v2)
```yaml
id: recurrence-guard-typed-schema-parser
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: free-text-recurrence-guard-bypasses-artifact-existence-check
  divergence_pattern: typed-schema-with-tolerant-mode-escape-hatch
  stack_scope: scripts/lib/recurrence_guard_parser
composite_identity_hash: 6d3e59b2bb10
symptom_keywords: [recurrence_guard, RMG, typed-schema, prevention_analysis, solve-trace, lifecycle-finalize, artifact-existence]
confidence_score: 0.95
occurrence_count: 1
linked_issues: [1278, 1300]
first_seen: 2026-04-25
last_seen: 2026-05-08
graduated_to: null
prevention_mechanism: |
  recurrence_guard_parser.parse is the single source of truth for the typed
  prevention_analysis.recurrence_guard field in solve-trace.json. The
  artifact-existence gate (verify-rmg-guard-artifact-in-diff.py) consumes
  the canonical dict shape; free-text strings fail at parse time post-cutover.
fix_template: |
  When writing or consuming a recurrence_guard, ALWAYS go through the parser:

    from lib.recurrence_guard_parser import parse, RecurrenceGuardParseError
    try:
        canonical = parse(guard_value)  # accepts dict OR light-mode bullet
    except RecurrenceGuardParseError as exc:
        sys.exit(f"recurrence_guard does not parse: {exc}")
    # canonical: {"kind", "artifact", "rationale", "unguardability_rationale"?}

  Do NOT hand-roll YAML parsing or accept free-text — the parser enforces
  rationale length (<=200 chars), kind enum, artifact-required-when-not-none,
  and unguardability_rationale-required-when-none. Tolerant mode
  (RMG_V2_TOLERANT=1) is the emergency escape hatch only.
```

### provenance-aware reader for .runs/ artifacts (#1437/#1417)
```yaml
id: runs-reader-provenance-aware-read
maturity: canonical
anti_pattern: false
composite_identity:
  root_cause_class: provenance-blind-runs-read
  divergence_pattern: glob-then-filter-without-run-id-disambiguation
  stack_scope: scripts/lib/runs_reader
composite_identity_hash: 76f283bb06ac
symptom_keywords: [runs, scope, current-run, cross-run-by-design, identity-resolution, dossier, ledger, manual-pr]
confidence_score: 0.95
occurrence_count: 2
linked_issues: [1437, 1417, 1347]
first_seen: 2026-05-14
last_seen: 2026-05-14
graduated_to: null
prevention_mechanism: |
  runs_reader.py exposes four functions that force every .runs/ read to
  declare provenance intent:
    - discover_current_run_id(branch?, project_dir?, include_completed=False, head_commit_timestamp?)
        Identity-resolution. Two paths: active-only (include_completed=False;
        newest in-flight, preserves child-preference) vs PR-gate (3-pass:
        active top-level / completed top-level with HEAD-recency / orphan
        child). 48h staleness cap.
    - read_jsonl(path, *, scope, current_run_id?, cross_run_channel?)
        scope='current-run' filters rows by run_id with HC2-graceful skip of
        legacy rows missing run_id. scope='cross-run-by-design' requires the
        channel to be pre-registered in .claude/patterns/cross-run-channels.json.
        scope=None (omitted) → TypeError; scope is keyword-only.
    - read_context_files(branch?, *, include_completed=False, project_dir?)
        Returns list[dict] sorted by timestamp desc. Use discover_current_run_id
        if you need single-Identity precedence.
    - read_git_log(files, *, since_days=60, max_per_file=5, project_dir?)
        git-history-augmented scope; per-file granularity; caps prevent
        designer-burden cliff in dossier_builder.
  The companion linter rule `provenance_aware_runs_read` flags new .runs/
  reads in production code (tests excluded) that lack runs_reader.* call or
  `# coherence-allow: provenance-blind-read` pragma.
fix_template: |
  When reading per-run state (e.g., fix-ledger filtered to current skill):

      from runs_reader import discover_current_run_id, read_jsonl
      identity = discover_current_run_id()
      if not identity:
          return  # HC5: manual gh pr create — pass through
      result = read_jsonl('.runs/fix-ledger.jsonl', scope='current-run',
                          current_run_id=identity.run_id)
      # result.rows: filtered list; result.skipped_missing_runid: HC2 count

  When reading cross-run data intentionally (trend/recurrence analysis):

      from runs_reader import read_jsonl
      result = read_jsonl('.runs/fix-ledger.jsonl', scope='cross-run-by-design',
                          cross_run_channel='fix-ledger')

  When surfacing git history because .runs/ is ephemeral:

      from runs_reader import read_git_log
      commits = read_git_log(divergence_files, max_per_file=5)
```

### Prior-Failure Dossier builder (RMG v2 Phase 1a Recall layer)
```yaml
id: prior-failure-dossier-builder
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: phase-1a-prior-failure-recall-from-fix-ledger
  divergence_pattern: in-memory-builder-with-no-disk-persistence
  stack_scope: scripts/lib/dossier_builder
composite_identity_hash: e41dcf239e5d
symptom_keywords: [dossier, prior-failure, phase-1a, RMG, fix-ledger, recurrence-candidates, anchoring-resistance]
confidence_score: 0.85
occurrence_count: 1
linked_issues: [1415, 1331, 1300]
first_seen: 2026-04-15
last_seen: 2026-05-13
graduated_to: null
prevention_mechanism: |
  dossier_builder.build_dossier reads .runs/fix-ledger.jsonl +
  .runs/recurrence-candidates.jsonl and returns a two-phase dossier
  (phase_1a withholds failure_mode/what_was_missed for designer anchoring
  resistance; phase_4b adds them for cross-check). The _meta.divergence_files
  field carries the caller's input file set forward to dossier_verify's
  no-empty-bypass check (Issue #1415).
fix_template: |
  When a skill state needs Phase 1a Prior-Failure recall (resolve.5, solve.1,
  change.3 Fix path), invoke:

    from lib.dossier_builder import build_dossier
    d = build_dossier(
        divergence_files=<caller's affected files>,
        symptom_signature=canonicalize_symptom(<problem statement>),
        project_dir='.',
    )

  Always write the returned dict to .runs/prior-failure-dossier.json via
  the canonical writer (write-gate-artifact.sh --path
  .runs/prior-failure-dossier.json) so state-registry VERIFY can assert
  presence. Empty divergence_files produces an empty dossier; that is legal
  for fresh projects but is flagged by dossier_verify when the caller
  supplied non-empty evidence — closes the empty-input bypass loophole.
```

### dossier verification (Phase 1a coverage gate; Issue #1415)
```yaml
id: dossier-verify-phase-1a-coverage-gate
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: verify-coverage-asymmetry-phase-1a-dossier
  divergence_pattern: prose-prescribes-step-but-registry-verify-does-not-enforce
  stack_scope: scripts/lib/dossier_verify
composite_identity_hash: 02c8ff2ff7b5
symptom_keywords: [dossier, prior-failure, phase-1a, RMG, verify-coverage, prose-only, registry-asymmetry, prior_failure_response]
confidence_score: 0.90
occurrence_count: 1
linked_issues: [1415]
first_seen: 2026-05-13
last_seen: 2026-05-13
graduated_to: null
prevention_mechanism: |
  dossier_verify.assert_dossier_loaded is the single source of truth for the
  Phase 1a Prior-Failure Dossier coverage gate. Called from
  verify-recurrence-guard.py (--require-dossier) and verify-change-solve.py
  (inline import) so resolve.5, solve.1, change.3 share one contract. The
  helper asserts .runs/prior-failure-dossier.json exists, prior_failure_response
  is a list, _meta.divergence_files non-empty when caller has evidence, and
  response count >= dossier phase_1a count.
fix_template: |
  When adding a state-registry.json VERIFY gate for a Phase 1a artifact (or
  any solve-reasoning sub-phase that produces a `.runs/X.json` file via lead
  prose), factor the assertion into a shared helper, NOT inline VERIFY string:

    from lib.dossier_verify import assert_dossier_loaded, DossierVerifyError
    try:
        assert_dossier_loaded(trace, problem_type=pa.get("problem_type"),
                              divergence_files_evidence=evidence)
    except DossierVerifyError as exc:
        print(f"VERIFY FAIL: {exc}", file=sys.stderr); return 1

  Then append `&& python3 -c "import json; json.load(open('.runs/X.json'))"`
  to the state-registry.json VERIFY string BEFORE the `#` comment so
  derive-graim-manifest.py auto-registers the path (AND-regex requires both
  `json.load(open(` and the literal in the same string). Always `make
  sync-verify` after editing state-registry.json. Empty-input bypass MUST be
  closed via a `_meta.divergence_files` cross-check.
```

### AOC v1.2 source-identity validator (canonical writer post-completion)
```yaml
id: source-identity-validator-aoc-v12
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: post-completion-canonical-writer-needs-explicit-source-identity
  divergence_pattern: HC13-cross-skill-forgery-defense
  stack_scope: scripts/lib/source_identity_validator
composite_identity_hash: b6c0ee7d50de
symptom_keywords: [aoc, source-identity, source-run-id, source-skill, post-completion, canonical-writer, HC13, forgery]
confidence_score: 0.90
occurrence_count: 1
linked_issues: [1217, 1198, 1300]
first_seen: 2026-05-01
last_seen: 2026-05-08
graduated_to: null
prevention_mechanism: |
  source_identity_validator.validate_source_identity enforces R1-R4 on
  --source-run-id / --source-skill flags supplied to canonical writers when
  resolve_active_identity returns empty (post-completion). R4 (HC13
  cross-skill forgery gate) blocks same-skill self-attribution.
fix_template: |
  When a canonical writer needs to write AFTER its skill's context is marked
  completed=true (e.g., from skill-epilogue.md or an external script),
  invoke source_identity_validator before stamping identity:

    from lib.source_identity_validator import validate_source_identity
    if not validate_source_identity(source_run_id, source_skill, agent=None):
        sys.exit(1)
    # ... safe to stamp run_id/skill on the artifact

  Equivalently from bash: pass --source-run-id and --source-skill to
  write-gate-artifact.sh; the validator is invoked for you. Don't bypass
  via direct json.dump — gate-artifact-write-gate.sh blocks Write/Edit
  on manifest paths anyway.
```

### symptom canonicalizer for recurrence detection (RMG v2)
```yaml
id: symptom-canonicalizer-stable-signature
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: surface-noise-fragments-symptom-grouping-across-recurrences
  divergence_pattern: canonical-form-with-line-position-and-sha-stripping
  stack_scope: scripts/lib/symptom_canonicalizer
composite_identity_hash: eb2482f1d407
symptom_keywords: [symptom, canonicalize, signature, recurrence, RMG, dossier, fix-ledger, grouping]
confidence_score: 0.85
occurrence_count: 1
linked_issues: [1278, 1300]
first_seen: 2026-04-25
last_seen: 2026-05-08
graduated_to: null
prevention_mechanism: |
  symptom_canonicalizer.canonicalize_symptom + symptom_signature_hash
  produce a stable signature for recurrence-detector grouping by stripping
  line/col positions, PR/issue numbers, ISO timestamps, absolute paths, and
  short SHAs. Paraphrased reports collide on the canonical form.
fix_template: |
  When grouping fix-ledger rows by symptom (recurrence detection, dossier
  building, prior-art lookup), canonicalize FIRST:

    from lib.symptom_canonicalizer import canonicalize_symptom, symptom_signature_hash
    sig = canonicalize_symptom(reproductions[0]["actual"])
    sig_hash = symptom_signature_hash(reproductions[0]["actual"])  # 12-char sha1

  Direct string equality misses re-paraphrased symptoms (same root cause,
  different message wording). The canonicalizer's lowercase + position-strip
  + path-strip + sha-strip rules fold variants into a single signature.
```

### PreToolUse hook silent-bypass paired enforcement (Issues #1349 + #1350)
```yaml
id: hook-silent-bypass-paired-enforcement
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: hook-defensive-exit-0-silently-bypasses-enforcement
  divergence_pattern: fail-open-without-friction-log-or-justification-trail
  stack_scope: scripts/lib/linter
composite_identity_hash: 5d4494d74598
symptom_keywords: [hook, exit-0, silent-bypass, friction-log, fail-open, defensive-skip, manifest-bypass, solve_depth, trace-validation]
confidence_score: 0.85
occurrence_count: 2
linked_issues: [1349, 1350]
first_seen: 2026-05-07
last_seen: 2026-05-07
graduated_to: null
prevention_mechanism: |
  Two coherence rules + two manifest categories:
    - hook_silent_skip_friction_pairing scans .claude/hooks/*.sh for any
      `exit 0` / `sys.exit(0)` and requires either a _write_hook_friction
      / deny / handle_validation call within 10 preceding lines OR a
      `# friction-skip: <reason>` pragma annotation.
    - hook_bypass_manifest_completeness validates that every entry in
      bypass-manifests (gate-readable-canonical-exemptions.json,
      adversarial-merge-trace-skip.json) declares category + justification.
  Hook code change: silent-skip paths now either friction-log (Constraint
  19 fail-open) OR fail-closed unless the manifest declares the skip
  (Mechanism A — adversarial-merge-gate change-challenge light-mode).
fix_template: |
  When a PreToolUse hook needs to early-exit, classify the exit:
    1. trivial-fast-path: hook's domain is structurally absent (no FILE_PATH,
       no COMMAND, no skill context). Annotate:
         # friction-skip: trivial-fast-path — <one-sentence why>
    2. post-validation: exit follows handle_validation, deny(), or an
       authoritative manifest decision. Annotate:
         # friction-skip: post-validation — <one-sentence why>
    3. silent-bypass: hook's enforcement *would* apply but is being skipped
       (mode=warn, manifest missing, unknown env-var value). Either:
         (a) _write_hook_friction "<msg>" before exit 0   # Constraint 19 fail-open
         (b) Replace with deny() gated by an exemption manifest  # Mechanism A
  Never leave bare `exit 0` — the linter rule
  hook_silent_skip_friction_pairing fails CI under --strict-aoc.
```

---

### unstamped_values / unstamped_items — safe iteration of canonical-writer artifacts
```yaml
id: unstamped-iteration-canonical-artifact
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: iterate-stamped-artifact-trips-on-identity-metadata
  divergence_pattern: raw-d-values-against-stamped-artifact
  stack_scope: scripts/lib/verify_helpers
composite_identity_hash: 3de199778a99
symptom_keywords: [canonical-writer, identity-stamps, GRAIM, d.values, d.items, iteration, verify, behavior-contract, auditor]
confidence_score: 0.90
occurrence_count: 2
linked_issues: [1379, 1381, 1387]
first_seen: 2026-05-04
last_seen: 2026-05-12
graduated_to: null
prevention_mechanism: |
  verify_helpers.unstamped_values(d) / unstamped_items(d) filter out the
  31-field STAMPED_FIELDS union (skill, run_id, written_at, agent,
  timestamp, status, provenance, etc.) stamped by the four canonical
  trace writers. Use these from VERIFY blocks AND from any consumer
  that iterates a page/page or page/contract-keyed dict written via
  write-gate-artifact.sh. Raw d.values() leaks identity strings into
  assertions ("pass_self_pass_or_fail" string treated as a check value).
fix_template: |
  When consuming a canonical-writer .runs/*.json artifact whose top-level
  shape is {<key>: <payload>, ..., <stamped-identity-fields>}:

    # Wrong (will trip on stamped identity strings):
    for v in d.values():
        ...

    # Right:
    sys.path.insert(0, '.claude/scripts/lib')
    from verify_helpers import unstamped_items, unstamped_values
    for k, v in unstamped_items(d):
        ...

  STAMPED_FIELDS is the union across all four canonical writers
  (write-gate-artifact.sh, write-agent-trace.sh, write-recovery-trace.sh,
  write-skipped-fixer-trace.sh). The coherence rule
  verify-d-values-against-stamped-artifact catches state-registry VERIFY
  drift; this same defense applies to any Python consumer.

  Callers:
    - state-registry:bootstrap.13a (unstamped_values for design-validated check)
    - .claude/scripts/lib/behavior_contract_auditor.py (#1387 unstamped_items
      for per-page contract iteration)
```

### canonical name normalizer for iterate-cross MVP identity matching (`match_key`)
```yaml
id: iterate-cross-match-key-normalizer
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: mvp-identity-string-comparison-divergence
  divergence_pattern: hand-coded-name-normalizer-instead-of-helper-call
  stack_scope: scripts/lib/iterate_cross_classify
composite_identity_hash: d5047bd0eb7e
symptom_keywords: [match_key, iterate-cross, mvp-identity, alias-merge, orphan-host, ga-bucket, kebab-case, alphanumeric-normalizer]
confidence_score: 0.9
occurrence_count: 1
linked_issues: []
first_seen: 2026-05-13
last_seen: 2026-05-13
graduated_to: null
prevention_mechanism: |
  `iterate_cross_classify.match_key(s)` is the single normalizer for comparing
  MVP identity strings across three independent surfaces:
    1. Canonical PostHog `project_name` (kebab-case: `x-predict`).
    2. Orphan-host URL subdomain (no hyphens: `xpredict.draftlabs.org` → `xpredict`).
    3. Google Ads campaign name (mixed case + suffixes: `xpredict #2`, `Lumen-Parth`).
  All three must compare equal when they refer to the same MVP. Strip
  non-alphanumeric chars and lowercase. Any consumer that hand-rolls a
  similar normalizer can drift (e.g., kebab-case stripping vs not, owner-suffix
  removal vs not), splitting one MVP into two records.
fix_template: |
  When matching an MVP identity string across surfaces:

    # Wrong — hand-rolled, likely to drift:
    norm_a = a.lower().replace("-", "").replace("_", "")
    norm_b = b.lower().replace(" ", "").replace("#", "")
    if norm_a == norm_b: ...

    # Right — reuse the canonical normalizer:
    import sys; sys.path.insert(0, '.claude/scripts/lib')
    from iterate_cross_classify import match_key
    if match_key(a) == match_key(b): ...

  Callers (production):
    - state-x0 orphan-overlap merge (`.claude/skills/iterate/state-x0-discover-mvps.md`)
    - state-x0a GA bucketing (`.claude/scripts/lib/iterate_cross_ga.py`)
```

### prose-gate effective-mode resolution with snapshot + per-gate override
```yaml
id: prose-gate-mode-shared-resolver
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: registry-field-documentation-only-not-load-bearing
  divergence_pattern: gate-runners-each-read-own-env-with-hardcoded-default
  stack_scope: scripts/lib/prose_gate_mode
composite_identity_hash: e57777802ea6
symptom_keywords: [prose-gate, fail_mode, registry, env-var, override, snapshot, in-flight, rollback, warn, deny, soak]
confidence_score: 0.85
occurrence_count: 1
linked_issues: [1449, 1431, 1433, 1444]
first_seen: 2026-05-15
last_seen: 2026-05-15
graduated_to: null
prevention_mechanism: |
  prose_gate_mode.resolve(gate_id, prior_default) centralizes effective-mode
  resolution across the 5 prose-gate enforcers/validators that have a
  warn↔deny gradient. Resolution chain (first match wins): tolerant escape
  > per-gate env > snapshot (version-checked) > registry (when v2+) >
  caller-passed prior_default. Snapshot taken at lifecycle-init time keeps
  in-flight runs safe against mid-run registry flips. prior_default
  preserves each gate's existing runtime behavior so registry edits do not
  silently regress (e.g., gate 5 caller passes "deny" preserving #1393
  phase-2 shipping decision).
fix_template: |
  When a registry/config field needs to become load-bearing AND callers
  currently each read their own env var with hardcoded defaults, AND
  in-flight processes must remain unaffected by mid-run config changes:

    1. Add a versioned snapshot field to per-run context at run-start
       (lifecycle-init.sh post-init Step 5c style). Stamp with
       `<config>_snapshot_at_version` so stale snapshots can be detected.
    2. Build a single resolution helper with explicit ordering:
         tolerant escape > per-key env > snapshot (version-gated) >
         registry (gated on schema version increment) > caller prior_default
    3. Each caller migrates to call the helper, passing its CURRENT runtime
       default as prior_default. This preserves existing behavior unless
       registry version increment + snapshot allows the registry to override.
    4. Bump registry _schema_version when the field becomes load-bearing —
       the version increment is the trigger that activates registry lookup.
    5. Add a soak summary tool (regime-aware: binary at low-sample,
       rate at medium, statistical at high) so per-flip rollback signal is
       observable per-key.

  Usage:
    # Bash caller:
    MODE=$(bash .claude/scripts/lib/prose_gate_mode.sh <gate_id> <prior_default>)

    # Python caller:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))  # or .claude/scripts/lib
    from prose_gate_mode import resolve
    mode = resolve("<gate_id>", prior_default="<warn|deny>")

  Callers (production):
    - .claude/hooks/bound-by-coverage-provider-gate.sh (gate 1)
    - .claude/scripts/lib/anomaly-audit-evidence.py (gate 4)
    - .claude/scripts/lib/user-approval-evidence-validator.py (gate 2)
    - .claude/scripts/validate-retrospective-completeness.py (gate 5, prior_default=deny)
    - .claude/scripts/check-observation-artifacts.sh (gate 5 dual-caller)
```

### atomic deviation-log appender with visible failure channel
```yaml
id: append-deviation-log-atomic-with-failures
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: best-effort-jsonl-appender-silently-loses-data
  divergence_pattern: open-append-without-fsync-and-silent-except
  stack_scope: scripts/lib/append_deviation_log
composite_identity_hash: 44739f770539
symptom_keywords: [deviation-log, jsonl, append, fsync, silent-failure, write-failures, observability, prose-gate]
confidence_score: 0.85
occurrence_count: 1
linked_issues: [1431, 1444]
first_seen: 2026-05-15
last_seen: 2026-05-15
graduated_to: null
prevention_mechanism: |
  append_deviation_log.append(payload) centralizes the deviation-log writer
  with: (a) POSIX O_APPEND atomicity for entries < PIPE_BUF (~4KB), (b)
  fsync before close (survives process crash), (c) on exception writes to
  a sibling write-failures.jsonl channel that is consumed by
  enumerate-pending-retrospective-findings.py 7th candidate source as
  HIGH-confidence findings (silent failures become observer-visible). Adds
  _meta.schema_version stamp for forward-compat.
fix_template: |
  When multiple callers append JSONL entries to a single observability log
  AND silent failures break downstream consumers (enumerator, observer):

    1. Centralize the appender into one helper. Caller-side: just call
       `append(entry_dict)`.
    2. Use POSIX `open(path, "a")` (O_APPEND atomic for writes < PIPE_BUF)
       + explicit f.flush() + os.fsync(f.fileno()) so writes survive crash.
    3. On exception: log to a sibling .write-failures.jsonl channel with
       {original_payload, exception, ts}. Best-effort writes to the failure
       channel itself; if even that fails, print to stderr.
    4. Wire the failure channel into the consumer's enumeration as HIGH-
       confidence findings — silent failures become surface-visible.
    5. Register both files in cross-run-channels.json (read-side metadata)
       per the cross_run_channel_exemption_pairing coherence rule.

  Usage:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))  # or .claude/scripts/lib
    from append_deviation_log import append
    ok = append({"gate_id": "...", "evidence": {...}})
    # Returns True on success; False routes to write-failures.jsonl.

  Callers (production):
    - .claude/scripts/lib/bound-by-coverage-provider.py
    - .claude/scripts/lib/anomaly-audit-evidence.py
    - .claude/scripts/lib/user-approval-evidence-validator.py
```

### Vercel operator-auth project and env discovery
```yaml
id: vercel-api-operator-auth-discovery
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: deployment-account-and-env-resolution-drift
  divergence_pattern: callers-hand-roll-vercel-cli-auth-project-env-lookups
  stack_scope: scripts/lib/vercel_api
composite_identity_hash: bc18155df4da
symptom_keywords: [vercel, project-link, teamId, production-env, NEXT_PUBLIC_POSTHOG_KEY, deployment-url, ads-ready]
confidence_score: 0.85
occurrence_count: 1
linked_issues: []
first_seen: 2026-05-22
last_seen: 2026-05-22
graduated_to: null
prevention_mechanism: |
  vercel_api centralizes Vercel CLI token discovery, team-scoped project
  listing, latest production deployment lookup, and tri-state production env
  reads. Callers must not collapse "confirmed absent" and "API error" into the
  same branch, and team projects must pass teamId when available from
  .vercel/project.json.
fix_template: |
  When code needs Vercel project identity, deployment URL, or production env:

    1. Read the operator token through vercel_api.read_vercel_token().
    2. Prefer .vercel/project.json projectId/orgId over name matching.
    3. Pass teamId to project/env/deployment calls when present.
    4. For env vars, branch on EnvResultFound, EnvResultAbsent, and
       EnvResultError separately. Never fall back to source or local env on
       EnvResultError.

  Callers (production):
    - .claude/scripts/lib/ads_ready_static_helpers.py
    - .claude/scripts/lib/ads_ready_smoke.py
```

### iterate-cross decision report (.docx bucketing + NO_GO reason)
```yaml
id: iterate-cross-decision-report-docx
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: report-rendering-needs-optional-heavy-dependency
  divergence_pattern: docx-bucket-and-no-go-reason-logic-shared-by-report-and-ledger
  stack_scope: scripts/lib/iterate_cross_docx
composite_identity_hash: fab6ba0e5c6b
symptom_keywords: [iterate-cross, docx, decision-report, python-docx, optional-dependency, bucket-scores, no-go-reason, verdict-report, x4, x4a]
confidence_score: 0.85
occurrence_count: 2
linked_issues: []
first_seen: 2026-06-29
last_seen: 2026-06-29
graduated_to: null
prevention_mechanism: |
  iterate_cross_docx owns the canonical partition of a scored MVP into the
  four report buckets (GO / NO_GO / INSUF / FIX TRACKING via bucket_scores,
  precedence FIX > NO_GO > GO > INSUF with a seen-guard) and the canonical
  NO_GO explanation string (no_go_reason: deleted backend > CPC unit-economics
  > low conversion > under floor). Both the .docx report (reached via
  iterate_cross_verdicts.py --emit-docx) and the decision ledger
  (iterate_cross_ledger.py, which records the same "why" per NO_GO row) import
  these helpers from here, so the report and the persisted ledger can never
  disagree on which bucket a verdict lands in or why a NO_GO was stopped.
  python-docx is isolated behind _import_docx(); the pure bucket/marker/reason
  helpers stay importable (and unit-testable) on machines without the dep, and
  emit_docx() returns (False, msg) instead of raising when it is absent so the
  pipeline degrades gracefully.
fix_template: |
  When another consumer needs the cross-MVP verdict buckets or the human-
  readable NO_GO reason, import bucket_scores / no_go_reason / mvp_cell_markers
  from iterate_cross_docx — do NOT re-derive the precedence or the reason
  branches inline (that is the drift this entry prevents). Any new optional
  rendering backend must go behind its own _import_*() guard and return a
  (bool, message) tuple, never raise, so state-x4 stays best-effort.
```

### iterate-cross per-MVP GitHub repo fetch + fuzzy-match
```yaml
id: iterate-cross-github-repo-fetch
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: per-mvp-github-repo-fetch-and-fuzzy-match
  divergence_pattern: repo-fetch-helpers-reused-across-pricing-and-ledger-enrichment
  stack_scope: scripts/lib/iterate_cross_pricing
composite_identity_hash: e5db136698d1
symptom_keywords: [iterate-cross, github, gh-api, resolve-repo, fetch-file, list-org-repos, magpiexyz-lab, fuzzy-match, x0c, x4a, pricing, ledger]
confidence_score: 0.85
occurrence_count: 2
linked_issues: []
first_seen: 2026-06-29
last_seen: 2026-06-29
graduated_to: null
prevention_mechanism: |
  iterate_cross_pricing owns the canonical path from a canonical MVP name to a
  magpiexyz-lab GitHub repo and its file contents: resolve_repo() (github_repo
  override > repo_aliases > match_key fuzzy match), list_org_repos(), and
  fetch_file() (gh api repos/{org}/{repo}/contents/{path} + base64 decode via
  the mockable _gh() transport). state-x0c (price discovery) and
  iterate_cross_ledger (x4a description enrichment) both reach repos through
  these helpers, so the two flows resolve the same repo for a given MVP and
  share one mock surface (_gh) in tests.
fix_template: |
  When a template script needs an MVP's repo or a file from it, call
  resolve_repo(name, list_org_repos(), mappings, repo_aliases) then
  fetch_file(repo, path) from iterate_cross_pricing — do NOT shell out to gh
  directly or re-implement the name→repo fuzzy match. Treat a None return
  (gh absent / repo unmatched / 404) as best-effort empty, never an error.
```

## Existing helpers (no Stack Knowledge — single-caller or in-flux)

These helpers are below the `lib_helper_stack_knowledge_required` rule's `caller_threshold: 2` (per narrow consumption_patterns excluding tests/), so they don't yet need a Stack Knowledge entry. Add an entry only when the helper crosses 2+ production callers.

- `auth_routing.py` — auth provider routing (1 caller: scaffold-wire.md)
- `check-advance-state-invocation.py` — standalone script invoked via subprocess (no Python imports)
- `check-archetype-canonical.py` — standalone script invoked via subprocess (no Python imports)
- `concern_id.py` — solve-critic concern ID generation (1 caller: solve-critic.md)
- `decompose-bash-chain.py` — standalone script invoked via subprocess (no Python imports)
- `derive_slot_intent.py` — slot intent derivation for image generation (1 caller: scaffold-init.md)
- `dossier_builder.py` — RMG v2 prior-failure dossier builder (1 caller: solve-reasoning.md)
- `iterate_cross_owner_infer.py` — owner inference from repo commit history for x4 owner-backfill proposals (1 caller: state-x4-rank-recommend.md)
- `iterate_cross_verdicts.py` — /iterate cross-skill verdict aggregation (subprocess-only)
- `observer_evidence_families.py` — observer evidence family manifest (1 caller: write-observation-evidence.py)
- `slot_intent_schema.py` — manual JSON schema validator (1 caller: scaffold-init.md)
- `stack_knowledge_audit.py` — nightly stack-knowledge issue filing (subprocess-only)
- `validate_evidence.py` — evidence-set validation (subprocess-only)
