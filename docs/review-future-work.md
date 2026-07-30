# /review Future Work

Improvements identified by 5-agent first-principles analysis (2026-03-08) but deferred from the world-champion PR. Each item is independent and can be implemented as a standalone PR.

## 1. ~~Dimension D: Production Path Consistency~~ — COMPLETED
**Status:** Implemented as validator checks 54-58 (not LLM dimension) — structural invariants are better caught by regex than LLM.

Checks added to `validate-semantics.py`:
- **Check 54:** Procedure files have production branch
- **Check 55:** Production sections reference TDD
- **Check 56:** Production sections reference implementer (feature/upgrade only — fix uses simpler single-task TDD)
- **Check 57:** change.md production block validates `stack.testing`
- **Check 58:** Agent tool declarations match roles (implementer has write tools, spec-reviewer is read-only)

## 2. ~~Validator Self-Tests~~ — COMPLETED
**Status:** Implemented in PR #232 (`chore/review-validator-tests`).

- `test_validate_frontmatter.py` — unit tests for all 11 frontmatter checks
- `test_validate_semantics.py` — unit tests for 20 extracted check functions + subprocess integration test
- `test_consistency_check.py` — subprocess tests for 6 consolidated consistency checks
- CI runs `pytest scripts/` before validators execute

## 3. ~~Pre-Computed Health Card~~ — REDESIGNED as Binary Health Gate
**Status:** Redesigned as binary health gate (not numeric score). Never skip LLM review — reduced loop parameters when clean.

Instead of a separate script with a 0-100 score, review.md Step 1 now computes a boolean `health_clean` check:
- All validators pass (`baseline_errors == 0`)
- No pending checks in check-inventory.md
- No TODO strings in skill or stack files

When clean: `max_iterations = 3`, `max_findings_per_dimension = 3` (light review).
When not clean: `max_iterations = 5`, `max_findings_per_dimension = 5` (full review).

The original design's "skip review entirely" option was rejected — validators can't catch cross-file contradictions that LLM review excels at.

## 4. ~~Parallel Adversaries~~ — SKIPPED
**Status:** Skipped — single adversary's cross-dimensional context is its main value. No dispute rate data exists to justify splitting.

Revisit only if `disputed_rate > 30%` is sustained across 3+ review runs, indicating the single adversary is systematically missing context within individual dimensions.

## 5. ~~File Category Auto-Discovery~~ — DEFERRED
**Status:** Deferred — 6 categories is manageable. Revisit when category count exceeds 8.

Current manual glob expansion in review.md dimensions is sufficient and more transparent than auto-discovery indirection.
