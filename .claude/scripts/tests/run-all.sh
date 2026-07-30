#!/usr/bin/env bash
# run-all.sh — run every test in .claude/scripts/tests/ and report the aggregate.
# Fails on first failing suite so CI can surface the root cause quickly.
set -euo pipefail

cd "$(dirname "$0")/../../.."

SUITES=(
  ".claude/scripts/tests/test_trace_schema.py"
  ".claude/scripts/tests/test_resolve_active_identity.py"
  ".claude/scripts/tests/test_detect_skill_for_branch.py"
  ".claude/scripts/tests/test_command_head_match.py"
  ".claude/scripts/tests/test_write_recovery.py"
  ".claude/scripts/tests/test_forgery_surface.py"
  ".claude/scripts/tests/test_validate_recovery.py"
  ".claude/scripts/tests/test_migrate_legacy_traces.py"
  ".claude/scripts/tests/test_lifecycle_init_mode_promotion.py"
  ".claude/scripts/tests/test_delivery_branch_guard.py"
  ".claude/scripts/tests/test_lifecycle_finalize_delivery_guard.py"
  ".claude/scripts/tests/test_resolve_skill_dir.py"
  ".claude/scripts/tests/test_hard_gate_predicates.py"
  ".claude/scripts/tests/test_agent_trace_write_guard.py"
  ".claude/scripts/tests/test_trace_write_guard.py"
  ".claude/scripts/tests/test_fix_ledger_write_guard.py"
  ".claude/scripts/tests/test_phase_a_forgery_surface.py"
  ".claude/scripts/tests/test_canonicalize_bash_command.py"
  ".claude/scripts/tests/test_check_advance_state_invocation.py"
  ".claude/scripts/tests/test_transient_teardown.py"
  ".claude/scripts/tests/test_state3b_review_method_merge.py"
  ".claude/scripts/tests/test_derive_pages.py"
  ".claude/scripts/tests/test_verify_semantics.py"
  ".claude/scripts/tests/test_field_role_map_rule.py"
  ".claude/scripts/tests/test_validate_behavior_pages.py"
  ".claude/scripts/tests/test_check_project_name.py"
  ".claude/scripts/tests/test_aoc_coherence_rules.py"
  ".claude/scripts/tests/test_provenance_rules.py"
  ".claude/scripts/tests/test_write_agent_trace.py"
  ".claude/scripts/tests/test_augment_trace.py"
  ".claude/scripts/tests/test_lead_fix_path.py"
  ".claude/scripts/tests/test_recovery_run_id_override.py"
  ".claude/scripts/tests/test_resolve_reviewer.py"
  ".claude/scripts/tests/test_frontmatter_coherence.py"
  ".claude/scripts/tests/test_derive_page_images.py"
  ".claude/scripts/tests/test_render_review_demo_404.py"
  ".claude/scripts/tests/test_merge_provenance_branch.py"
  ".claude/scripts/tests/test_state_registry_7b.py"
  ".claude/scripts/tests/test_state_3b_verify_partition.py"
  ".claude/scripts/tests/test_slot_intent_schema.py"
  ".claude/scripts/tests/test_derive_slot_intent_decision_table.py"
  ".claude/scripts/tests/test_derive_og_photo_default.py"
  ".claude/scripts/tests/test_derive_runtime_gate.py"
  ".claude/scripts/tests/test_archetype_short_circuit.py"
  ".claude/scripts/tests/test_design_slots_override.py"
  ".claude/scripts/tests/test_scaffold_init_writes_slot_intent.py"
  ".claude/scripts/tests/test_auth_stack_frontmatter_schema.py"
  ".claude/scripts/tests/test_migrate_slot_intent_suggestions.py"
  ".claude/scripts/tests/test_state_11a_dynamic_ic.py"
  ".claude/scripts/tests/test_render_context.py"
  ".claude/scripts/tests/test_drift_detection_asymmetric.py"
  ".claude/scripts/tests/test_drift_boundary_skip.py"
  ".claude/scripts/tests/test_drift_null_unresolved.py"
  ".claude/scripts/tests/test_auth_routing.py"
  ".claude/scripts/tests/test_iterate_cross_verdicts.py"
  ".claude/scripts/tests/test_worktree_boundary_gate.py"
  ".claude/scripts/tests/test_bash_hook_write_operator_binding.py"
  ".claude/scripts/tests/test_markdown_cross_file_line_reference.py"
  ".claude/scripts/tests/test_recurrence_guard_parser.py"
  ".claude/scripts/tests/test_recurrence_detector.py"
  ".claude/scripts/tests/test_runs_reader.py"
  ".claude/scripts/tests/test_dossier_git_fallback.py"
  ".claude/scripts/tests/test_detect_skill_recency_window.py"
  ".claude/scripts/tests/test_check_fixlog_verdict_per_run.py"
  ".claude/scripts/tests/test_skill_commit_gate_mode_qualified.py"
  ".claude/scripts/tests/test_skill_agent_gate_mode_qualified.py"
  ".claude/scripts/tests/test_state_completion_gate_mode_qualified_provenance.py"
  ".claude/scripts/tests/test_compliance_fixlog_run_scope.py"
  ".claude/scripts/tests/test_check_observation_artifacts_fast_path.py"
  ".claude/scripts/tests/test_gecr_cutover_linter_rule.py"
  ".claude/scripts/tests/test_check_observation_artifacts_gate_evidence.py"
  ".claude/scripts/tests/test_consultation_deny_values.py"
  ".claude/scripts/tests/test_provenance_linter_rule.py"
  ".claude/scripts/tests/test_dossier_builder.py"
  ".claude/scripts/tests/test_oarc_matcher.py"
  ".claude/scripts/tests/test_landing_critic_merger.py"
  ".claude/scripts/tests/test_concern_id_stability.py"
  ".claude/scripts/tests/test_verify_rmg_guard_artifact.py"
  ".claude/scripts/tests/test_design_agents_orchestration.py"
  ".claude/scripts/tests/test_consistency_prepass.py"
  ".claude/scripts/tests/test_consistency_merger.py"
  ".claude/scripts/tests/test_consistency_attestation.py"
  ".claude/scripts/tests/test_codemod_canonical_writer_audit.py"
  ".claude/scripts/tests/test_codemod_canonical_writer.py"
  ".claude/scripts/tests/test_gate_artifact_writer_enforcement.py"
  ".claude/scripts/tests/test_gate_artifact_bash_write_guard.py"
  ".claude/scripts/tests/test_prose_gate_e2e.py"
)

FAIL=0
for s in "${SUITES[@]}"; do
  echo "━━━ $s ━━━"
  if python3 "$s"; then
    echo "PASS: $s"
  else
    echo "FAIL: $s"
    FAIL=1
    break
  fi
  echo
done

if [[ $FAIL -eq 0 ]]; then
  echo
  echo "ALL AGENT-TRACE LIFECYCLE TESTS PASSED"
else
  exit 1
fi
