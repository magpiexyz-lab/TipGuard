"""Tests for validate-semantics.py check functions."""

import datetime
import json
import os
import subprocess
import sys

import pytest
import yaml

# Add scripts dir to path for imports
sys.path.insert(0, os.path.dirname(__file__))

# Import check functions from the refactored validator
import importlib.util
spec = importlib.util.spec_from_file_location(
    "validate_semantics",
    os.path.join(os.path.dirname(__file__), "validate-semantics.py"),
)
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


# ---------------------------------------------------------------------------
# Check 1: Import Completeness in TSX Templates
# ---------------------------------------------------------------------------


class TestCheck1ImportCompleteness:
    def test_passes_with_matching_imports(self):
        content = """---
assumes: []
packages: {}
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

```tsx
import { Button } from "@/components/ui/button"

export function Page() {
  return <Button>Click</Button>
}
```
"""
        errors = vs.check_1_import_completeness({"test.md": content})
        assert errors == []

    def test_fails_with_missing_import(self):
        content = """---
assumes: []
---

```tsx
export function Page() {
  return <Button>Click</Button>
}
```
"""
        errors = vs.check_1_import_completeness({"test.md": content})
        assert len(errors) == 1
        assert "Button" in errors[0]

    def test_passes_with_local_definition(self):
        content = """---
assumes: []
---

```tsx
function MyComponent() {
  return <div>test</div>
}

export function Page() {
  return <MyComponent />
}
```
"""
        errors = vs.check_1_import_completeness({"test.md": content})
        assert errors == []

    def test_passes_with_builtin_component(self):
        content = """---
assumes: []
---

```tsx
export function Page() {
  return <Suspense fallback={null}><div /></Suspense>
}
```
"""
        errors = vs.check_1_import_completeness({"test.md": content})
        assert errors == []

    def test_passes_with_aliased_import(self):
        content = """---
assumes: []
---

```tsx
import { Card as MyCard } from "@/components"

export function Page() {
  return <MyCard />
}
```
"""
        errors = vs.check_1_import_completeness({"test.md": content})
        assert errors == []


# ---------------------------------------------------------------------------
# Check 5: Conditional Dependency References
# ---------------------------------------------------------------------------


class TestCheck5ConditionalDependencyRefs:
    def test_passes_with_guard(self):
        content = """---
type: code-writing
reads: []
stack_categories: []
requires_approval: false
references: []
branch_prefix: feat
modifies_specs: false
---

If `stack.database` is present, read settings from the database stack file.
"""
        errors = vs.check_5_conditional_dependency_refs({"skill.md": content})
        assert errors == []

    def test_fails_without_guard(self):
        content = """---
type: code-writing
reads: []
stack_categories: []
requires_approval: false
references: []
branch_prefix: feat
modifies_specs: false
---

Read settings from the database stack file.
"""
        errors = vs.check_5_conditional_dependency_refs({"skill.md": content})
        assert len(errors) == 1
        assert "database" in errors[0]

    def test_skips_non_optional_categories(self):
        content = """---
type: code-writing
---

Read settings from the framework stack file.
"""
        errors = vs.check_5_conditional_dependency_refs({"skill.md": content})
        assert errors == []


# ---------------------------------------------------------------------------
# Check 11: Hardcoded Provider Names Match Assumes
# ---------------------------------------------------------------------------


class TestCheck11HardcodedProviderNames:
    def test_passes_when_provider_in_assumes(self):
        content = """---
assumes:
  - payment/stripe
packages: {}
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

```ts
import Stripe from 'stripe'
```
"""
        errors = vs.check_11_hardcoded_provider_names({
            ".claude/stacks/testing/vitest.md": content
        })
        assert errors == []

    def test_fails_when_provider_not_in_assumes(self):
        content = """---
assumes: []
packages: {}
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

```ts
import Stripe from 'stripe'
```
"""
        errors = vs.check_11_hardcoded_provider_names({
            ".claude/stacks/testing/vitest.md": content
        })
        assert len(errors) == 1
        assert "stripe" in errors[0]

    def test_skips_own_stack_file(self):
        content = """---
assumes: []
packages: {}
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

```ts
import Stripe from 'stripe'
```
"""
        errors = vs.check_11_hardcoded_provider_names({
            ".claude/stacks/payment/stripe.md": content
        })
        assert errors == []

    def test_fails_when_next_env_without_framework_assumes(self):
        content = """---
assumes: [database/supabase]
packages: {}
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

```ts
import { loadEnvConfig } from "@next/env";
```
"""
        errors = vs.check_11_hardcoded_provider_names({
            ".claude/stacks/testing/playwright.md": content
        })
        assert len(errors) == 1
        assert "@next/" in errors[0]

    def test_passes_when_next_env_with_framework_assumes(self):
        content = """---
assumes: [framework/nextjs, database/supabase]
packages: {}
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

```ts
import { loadEnvConfig } from "@next/env";
```
"""
        errors = vs.check_11_hardcoded_provider_names({
            ".claude/stacks/testing/playwright.md": content
        })
        assert errors == []


# ---------------------------------------------------------------------------
# Check 16: Change Payment-Auth Dependency
# ---------------------------------------------------------------------------


class TestCheck16ChangePaymentAuth:
    def test_passes_with_auth_check(self):
        content = "When adding payment to the stack, verify payment requires auth to be present."
        errors = vs.check_16_change_payment_auth(content, "change.md")
        assert errors == []

    def test_fails_without_auth_check(self):
        content = "When adding payment to the stack, install Stripe."
        errors = vs.check_16_change_payment_auth(content, "change.md")
        assert len(errors) == 1
        assert "auth-presence" in errors[0]

    def test_passes_when_no_payment_ref(self):
        content = "This skill adds new features."
        errors = vs.check_16_change_payment_auth(content, "change.md")
        assert errors == []


# ---------------------------------------------------------------------------
# Check 17: Env Vars Prose-Frontmatter Sync
# ---------------------------------------------------------------------------


class TestCheck17EnvVarsSync:
    def test_passes_when_synced(self):
        content = """---
assumes: []
packages: {}
files: []
env:
  server:
    - STRIPE_SECRET_KEY
  client: []
ci_placeholders: {}
clean: {}
gitignore: []
---

## Environment Variables

Set `STRIPE_SECRET_KEY` in your .env file.
"""
        errors = vs.check_17_env_vars_prose_frontmatter_sync({"test.md": content})
        assert errors == []

    def test_fails_when_var_not_in_frontmatter(self):
        content = """---
assumes: []
packages: {}
files: []
env:
  server: []
  client: []
ci_placeholders: {}
clean: {}
gitignore: []
---

## Environment Variables

Set `STRIPE_SECRET_KEY` in your .env file.
"""
        errors = vs.check_17_env_vars_prose_frontmatter_sync({"test.md": content})
        assert len(errors) == 1
        assert "STRIPE_SECRET_KEY" in errors[0]


# ---------------------------------------------------------------------------
# Check 18: Change Payment-Database Dependency
# ---------------------------------------------------------------------------


class TestCheck18ChangePaymentDatabase:
    def test_passes_with_database_check(self):
        content = """
#### Feature constraints

When adding payment stack, verify that stack.database is also present.
"""
        errors = vs.check_18_change_payment_database(content, "change.md")
        assert errors == []

    def test_passes_with_database_check_in_preconditions(self):
        content = """
#### Feature constraints
Follow the procedure.

## Step 4: Check type-specific preconditions
- If payment: verify stack.database is also present.
"""
        errors = vs.check_18_change_payment_database(content, "change.md")
        assert errors == []

    def test_fails_without_database_check(self):
        content = """
#### Feature constraints

Install the payment stack.
"""
        errors = vs.check_18_change_payment_database(content, "change.md")
        assert len(errors) == 1
        assert "database" in errors[0]


# ---------------------------------------------------------------------------
# Check 21: Packages Prose-Frontmatter Sync
# ---------------------------------------------------------------------------


class TestCheck21PackagesSync:
    def test_passes_when_synced(self):
        content = """---
assumes: []
packages:
  runtime:
    - stripe
  dev: []
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

## Packages

```bash
npm install stripe
```
"""
        errors = vs.check_21_packages_prose_frontmatter_sync({"test.md": content})
        assert errors == []

    def test_fails_when_package_not_in_frontmatter(self):
        content = """---
assumes: []
packages:
  runtime: []
  dev: []
files: []
env: {}
ci_placeholders: {}
clean: {}
gitignore: []
---

## Packages

```bash
npm install stripe
```
"""
        errors = vs.check_21_packages_prose_frontmatter_sync({"test.md": content})
        assert len(errors) == 1
        assert "stripe" in errors[0]


# ---------------------------------------------------------------------------
# Check 33: Phantom Event Names
# ---------------------------------------------------------------------------


class TestCheck33PhantomEventNames:
    def test_passes_when_event_defined(self):
        content = """---
type: code-writing
reads: []
stack_categories: []
requires_approval: false
references: []
branch_prefix: feat
modifies_specs: false
---

Fire the `visit_landing` event when the page loads.
"""
        defined = {"visit_landing", "signup_start"}
        errors = vs.check_33_phantom_event_names(
            {"skill.md": content}, defined, set(), set()
        )
        assert errors == []

    def test_fails_when_event_not_defined(self):
        content = """---
type: code-writing
---

Fire the `nonexistent_event` event when done.
"""
        errors = vs.check_33_phantom_event_names(
            {"skill.md": content}, set(), set(), set()
        )
        assert len(errors) == 1
        assert "nonexistent_event" in errors[0]

    def test_skips_known_non_event_tokens(self):
        content = """---
type: code-writing
---

The `payment` event category in the analytics stack.
"""
        errors = vs.check_33_phantom_event_names(
            {"skill.md": content}, set(), set(), set()
        )
        assert errors == []


# ---------------------------------------------------------------------------
# Check 38: Ads.yaml Schema Validation
# ---------------------------------------------------------------------------


def _valid_google_ads(total_budget_cents=10000):
    return {
        "channel": "google-ads",
        "campaign_name": "test-campaign",
        "project_name": "test",
        "landing_url": "https://example.com",
        "budget": {"total_budget_cents": total_budget_cents},
        "targeting": {"location": "US"},
        "conversions": {"goal": "signup"},
        "guardrails": {"max_cpc_cents": 100},
        "thresholds": {
            "expected_activations": 10,
            "go_signal": "CPA < $5",
            "no_go_signal": "CPA > $20",
        },
        "keywords": {
            "exact": ["a", "b", "c"],
            "phrase": ["d", "e"],
            "broad": ["f"],
            "negative": ["g", "h"],
        },
        "ads": [
            {"headlines": ["h1", "h2", "h3", "h4", "h5"], "descriptions": ["d1", "d2"]},
            {"headlines": ["h1", "h2", "h3", "h4", "h5"], "descriptions": ["d1", "d2"]},
        ],
    }


def _google_ads_with(total_budget_cents=10000, budget_extra=None, guardrails_max_cpc=100):
    ads = _valid_google_ads(total_budget_cents)
    if budget_extra is not None:
        ads["budget"].update(budget_extra)
    ads["guardrails"]["max_cpc_cents"] = guardrails_max_cpc
    return ads


def _valid_twitter_ads(total_budget_cents=5000, budget_extra=None):
    budget = {"total_budget_cents": total_budget_cents}
    if budget_extra is not None:
        budget.update(budget_extra)
    return {
        "channel": "twitter",
        "campaign_name": "test",
        "project_name": "test",
        "landing_url": "https://example.com",
        "budget": budget,
        "targeting": {},
        "conversions": {},
        "guardrails": {},
        "thresholds": {
            "expected_activations": 5,
            "go_signal": "good",
            "no_go_signal": "bad",
        },
        "tweets": [
            {"text": "Tweet 1"},
            {"text": "Tweet 2"},
        ],
    }


def _phase2_google_ads(**overrides):
    ads = _valid_google_ads()
    ads["campaign_name"] = "test-search-phase2-v1"
    ads["phase"] = 2
    ads["dayzero_probe_passed_at"] = "2026-07-29"
    ads.update(overrides)
    return ads


class TestCheck38AdsYamlSchema:
    def test_passes_with_valid_google_ads(self):
        errors = vs.check_38_ads_yaml_schema(_valid_google_ads(), "ads.yaml")
        assert errors == []

    def test_passes_phase1_budget_cap(self):
        errors = vs.check_38_ads_yaml_schema(_valid_google_ads(25000), "ads.yaml")
        assert errors == []

    def test_passes_phase2_budget_cap(self):
        errors = vs.check_38_ads_yaml_schema(_valid_google_ads(75000), "ads.yaml")
        assert errors == []

    def test_fails_missing_required_key(self):
        ads = {"channel": "google-ads", "campaign_name": "test"}
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert any("missing required key" in e for e in errors)

    def test_fails_budget_too_high(self):
        errors = vs.check_38_ads_yaml_schema(_valid_google_ads(80000), "ads.yaml")
        assert any("exceeds max 75000" in e for e in errors)

    def test_fails_above_bound_without_override(self):
        errors = vs.check_38_ads_yaml_schema(_valid_google_ads(76000), "ads.yaml")
        assert any("exceeds max 75000" in e and "Team Lead" in e for e in errors)

    def test_fails_raised_ceiling_without_override(self):
        ads = _google_ads_with(
            50000,
            budget_extra={"click_target": 100},
            guardrails_max_cpc=500,
        )
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert any(
            "budget.cap_override_approved_by" in e
            and "Team Lead" in e
            and "> $50/mo" in e
            for e in errors
        )

    def test_passes_coherent_raise_with_override(self):
        phase2_ads = _google_ads_with(
            150000,
            budget_extra={"click_target": 300, "cap_override_approved_by": "Taylor"},
            guardrails_max_cpc=500,
        )
        assert vs.check_38_ads_yaml_schema(phase2_ads, "ads.yaml") == []

        phase1_ads = _google_ads_with(
            50000,
            budget_extra={"click_target": 100, "cap_override_approved_by": "Taylor"},
            guardrails_max_cpc=500,
        )
        assert vs.check_38_ads_yaml_schema(phase1_ads, "ads.yaml") == []

    def test_fails_incoherent_bundle_with_override(self):
        ads = _google_ads_with(
            120000,
            budget_extra={"click_target": 300, "cap_override_approved_by": "Taylor"},
            guardrails_max_cpc=500,
        )
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert any("bundle identity" in e for e in errors)

    def test_fails_above_absolute_max_with_override(self):
        ads = _google_ads_with(
            210000,
            budget_extra={"click_target": 300, "cap_override_approved_by": "Taylor"},
            guardrails_max_cpc=700,
        )
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert any("absolute max 200000" in e for e in errors)

    def test_fails_invalid_override_type(self):
        for invalid_override in (True, ""):
            ads = _google_ads_with(
                150000,
                budget_extra={"cap_override_approved_by": invalid_override},
            )
            errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
            assert any("cap_override_approved_by" in e and "who approved the raise" in e for e in errors)
            assert any("exceeds max 75000" in e for e in errors)

    def test_fails_malformed_total_type(self):
        for malformed_total in ("150000", True):
            errors = vs.check_38_ads_yaml_schema(_valid_google_ads(malformed_total), "ads.yaml")
            assert any("budget.total_budget_cents must be an integer cents value" in e for e in errors)

    def test_override_rejected_on_other_channels(self):
        over_bound = _valid_twitter_ads(
            150000,
            budget_extra={"cap_override_approved_by": "Taylor"},
        )
        errors = vs.check_38_ads_yaml_schema(over_bound, "ads.yaml")
        assert any("only supported for google-ads" in e for e in errors)
        assert any("exceeds max 75000" in e for e in errors)

        under_bound = _valid_twitter_ads(
            50000,
            budget_extra={"cap_override_approved_by": "Taylor"},
        )
        errors = vs.check_38_ads_yaml_schema(under_bound, "ads.yaml")
        assert errors == [
            "[38] ads.yaml: budget.cap_override_approved_by is only supported for google-ads"
        ]

    def test_fails_override_without_valid_click_target(self):
        for budget_extra in (
            {"cap_override_approved_by": "Taylor"},
            {"click_target": 150, "cap_override_approved_by": "Taylor"},
            {"click_target": True, "cap_override_approved_by": "Taylor"},
        ):
            ads = _google_ads_with(
                150000,
                budget_extra=budget_extra,
                guardrails_max_cpc=500,
            )
            errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
            assert any("cap override requires budget.click_target" in e for e in errors)

    def test_fails_bool_max_cpc(self):
        plain_ads = _google_ads_with(guardrails_max_cpc=True)
        errors = vs.check_38_ads_yaml_schema(plain_ads, "ads.yaml")
        assert any("guardrails.max_cpc_cents must be an integer > 0" in e for e in errors)

        override_ads = _google_ads_with(
            150000,
            budget_extra={"click_target": 300, "cap_override_approved_by": "Taylor"},
            guardrails_max_cpc=True,
        )
        errors = vs.check_38_ads_yaml_schema(override_ads, "ads.yaml")
        assert any("guardrails.max_cpc_cents must be an integer > 0" in e for e in errors)

    def test_passes_twitter_channel(self):
        ads = {
            "channel": "twitter",
            "campaign_name": "test",
            "project_name": "test",
            "landing_url": "https://example.com",
            "budget": {"total_budget_cents": 5000},
            "targeting": {},
            "conversions": {},
            "guardrails": {},
            "thresholds": {
                "expected_activations": 5,
                "go_signal": "good",
                "no_go_signal": "bad",
            },
            "tweets": [
                {"text": "Tweet 1"},
                {"text": "Tweet 2"},
            ],
        }
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert errors == []

    def test_fails_twitter_too_long(self):
        ads = {
            "channel": "twitter",
            "campaign_name": "test",
            "project_name": "test",
            "landing_url": "https://example.com",
            "budget": {"total_budget_cents": 5000},
            "targeting": {},
            "conversions": {},
            "guardrails": {},
            "thresholds": {
                "expected_activations": 5,
                "go_signal": "good",
                "no_go_signal": "bad",
            },
            "tweets": [
                {"text": "x" * 281},
                {"text": "ok"},
            ],
        }
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert any("exceeds 280 chars" in e for e in errors)

    # --- phase / dayzero_probe_passed_at (Phase 2 gate) ---

    def test_phase_absent_no_new_requirements(self):
        errors = vs.check_38_ads_yaml_schema(_valid_google_ads(), "ads.yaml")
        assert not any("phase" in e or "dayzero" in e for e in errors)

    def test_fails_phase_invalid_value(self):
        for bad in (3, 0, "2", True):
            ads = _valid_google_ads()
            ads["phase"] = bad
            errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
            assert any("phase must be 1 or 2" in e for e in errors), f"phase={bad!r}"

    def test_passes_phase1_no_probe_required(self):
        ads = _valid_google_ads()
        ads["phase"] = 1
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert errors == []

    def test_fails_phase2_without_probe_field(self):
        ads = _phase2_google_ads()
        del ads["dayzero_probe_passed_at"]
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert any(
            "dayzero_probe_passed_at" in e and "§5 step 10" in e for e in errors
        )

    def test_passes_phase2_with_valid_probe(self):
        errors = vs.check_38_ads_yaml_schema(_phase2_google_ads(), "ads.yaml")
        assert errors == []

    def test_passes_phase2_probe_as_yaml_date(self):
        # Unquoted YYYY-MM-DD in YAML loads as datetime.date, not str.
        ads = _phase2_google_ads(dayzero_probe_passed_at=datetime.date(2026, 7, 29))
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert errors == []

    def test_fails_phase2_invalid_probe_value(self):
        for bad in ("07/29/2026", 20260729, True, ""):
            ads = _phase2_google_ads(dayzero_probe_passed_at=bad)
            errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
            assert any("must be a YYYY-MM-DD" in e for e in errors), f"probe={bad!r}"

    def test_fails_phase2_campaign_name_missing_token(self):
        ads = _phase2_google_ads(campaign_name="test-campaign")
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert any("'phase2' token" in e for e in errors)

    def test_phase2_requirements_google_ads_only(self):
        ads = _valid_twitter_ads()
        ads["phase"] = 2
        errors = vs.check_38_ads_yaml_schema(ads, "ads.yaml")
        assert not any("dayzero" in e or "phase2' token" in e for e in errors)


# ---------------------------------------------------------------------------
# Check 39: Ads Campaign Name Matches idea Name
# ---------------------------------------------------------------------------


class TestCheck39AdsCampaignName:
    def test_passes_when_matching(self):
        errors = vs.check_39_ads_campaign_name(
            {"campaign_name": "test-app-v1"},
            {"name": "test-app"},
            "ads.yaml",
        )
        assert errors == []

    def test_fails_when_not_matching(self):
        errors = vs.check_39_ads_campaign_name(
            {"campaign_name": "wrong-name"},
            {"name": "test-app"},
            "ads.yaml",
        )
        assert len(errors) == 1
        assert "does not start with" in errors[0]


# ---------------------------------------------------------------------------
# check_ads_for_distribute: `make distribute` composition (38 + 39)
# ---------------------------------------------------------------------------


class TestCheckAdsForDistribute:
    def _write_experiment(self, tmp_path, content):
        path = tmp_path / "experiment.yaml"
        path.write_text(content)
        return str(path)

    def test_composes_38_and_39(self, tmp_path):
        exp = self._write_experiment(tmp_path, "name: other-app\n")
        errors = vs.check_ads_for_distribute(_valid_google_ads(), "ads.yaml", exp)
        assert any(e.startswith("[39]") for e in errors)
        ads = _valid_google_ads()
        del ads["keywords"]
        errors = vs.check_ads_for_distribute(ads, "ads.yaml", exp)
        assert any(e.startswith("[38]") for e in errors)
        assert any(e.startswith("[39]") for e in errors)

    def test_prefix_pass(self, tmp_path):
        exp = self._write_experiment(tmp_path, "name: test\n")
        errors = vs.check_ads_for_distribute(_valid_google_ads(), "ads.yaml", exp)
        assert errors == []

    def test_experiment_yaml_missing_graceful(self, tmp_path):
        missing = str(tmp_path / "nonexistent.yaml")
        errors = vs.check_ads_for_distribute(_valid_google_ads(), "ads.yaml", missing)
        assert errors == []
        assert not any(e.startswith("[39]") for e in errors)

    def test_experiment_yaml_malformed_graceful(self, tmp_path):
        exp = self._write_experiment(tmp_path, "{{{:\n  - broken")
        errors = vs.check_ads_for_distribute(_valid_google_ads(), "ads.yaml", exp)
        assert not any(e.startswith("[39]") for e in errors)


# ---------------------------------------------------------------------------
# Check 46: Iterate Verdict
# ---------------------------------------------------------------------------


class TestCheck46IterateVerdict:
    def test_passes_with_all_elements(self):
        content = "## Verdict\nIssue a GO or NO-GO verdict based on pace.\n"
        errors = vs.check_46_iterate_verdict(content)
        assert errors == []

    def test_fails_missing_verdict(self):
        content = "## Analysis\nLook at the data.\n"
        errors = vs.check_46_iterate_verdict(content)
        assert any("verdict" in e for e in errors)

    def test_fails_missing_go_nogo(self):
        content = "## Verdict\nDecide whether to continue based on pace.\n"
        errors = vs.check_46_iterate_verdict(content)
        assert any("GO/NO-GO" in e for e in errors)

    def test_fails_missing_pace(self):
        content = "## Verdict\nIssue a GO or NO-GO decision.\n"
        errors = vs.check_46_iterate_verdict(content)
        assert any("pace" in e for e in errors)


# ---------------------------------------------------------------------------
# Check 53: Supabase Delete Flag
# ---------------------------------------------------------------------------


class TestCheck53SupabaseDeleteFlag:
    def test_passes_with_project_ref(self):
        content = """
```bash
supabase projects delete --project-ref $REF
```
"""
        errors = vs.check_53_supabase_delete_flag({"test.md": content})
        assert errors == []

    def test_fails_without_project_ref(self):
        content = """
```bash
supabase projects delete $REF
```
"""
        errors = vs.check_53_supabase_delete_flag({"test.md": content})
        assert len(errors) == 1
        assert "--project-ref" in errors[0]

    def test_skips_files_without_supabase_delete(self):
        content = """
```bash
echo "hello"
```
"""
        errors = vs.check_53_supabase_delete_flag({"test.md": content})
        assert errors == []


# ---------------------------------------------------------------------------
# Check 54: Procedure Production Branch
# ---------------------------------------------------------------------------


class TestCheck54ProcedureProductionBranch:
    def test_passes_with_tdd_and_on_touch_references(self):
        files = {
            "change-feature.md": "1. ON-TOUCH check\n2. Generate TDD tasks per patterns/tdd.md.",
            "change-upgrade.md": "1. ON-TOUCH check\n2. Generate TDD tasks per patterns/tdd.md.",
            "change-fix.md": "1. ON-TOUCH check\n2. Regression test per patterns/tdd.md.",
        }
        errors = vs.check_54_procedure_production_branch(files)
        assert errors == []

    def test_fails_without_production_branch(self):
        files = {
            "change-feature.md": "## Steps\nBuild the feature.",
        }
        errors = vs.check_54_procedure_production_branch(files)
        assert len(errors) == 1
        assert "change-feature.md" in errors[0]

    def test_skips_non_target_procedures(self):
        files = {
            "change-other.md": "No production branch here.",
        }
        errors = vs.check_54_procedure_production_branch(files)
        assert errors == []


# ---------------------------------------------------------------------------
# Check 55: Production References TDD
# ---------------------------------------------------------------------------


class TestCheck55ProductionReferencesTdd:
    def test_passes_with_tdd_reference(self):
        files = {
            "change-feature.md": "When quality: production, follow patterns/tdd.md.",
        }
        errors = vs.check_55_production_references_tdd(files)
        assert errors == []

    def test_fails_without_tdd_reference(self):
        files = {
            "change-feature.md": "When quality: production, write some tests.",
        }
        errors = vs.check_55_production_references_tdd(files)
        assert len(errors) == 1
        assert "tdd.md" in errors[0]

    def test_fails_without_tdd_reference_unconditionally(self):
        files = {
            "change-feature.md": "Build the feature normally.",
        }
        errors = vs.check_55_production_references_tdd(files)
        assert len(errors) == 1
        assert "tdd.md" in errors[0]


# ---------------------------------------------------------------------------
# Check 56: Production References Implementer
# ---------------------------------------------------------------------------


class TestCheck56ProductionReferencesImplementer:
    def test_passes_with_implementer_reference(self):
        files = {
            "change-feature.md": "When quality: production, use agents/implementer.md.",
        }
        errors = vs.check_56_production_references_implementer(files)
        assert errors == []

    def test_passes_with_implementer_agent_text(self):
        files = {
            "change-upgrade.md": "When quality: production, spawn implementer agents.",
        }
        errors = vs.check_56_production_references_implementer(files)
        assert errors == []

    def test_fails_without_implementer_reference(self):
        files = {
            "change-feature.md": "When quality: production, build things.",
        }
        errors = vs.check_56_production_references_implementer(files)
        assert len(errors) == 1
        assert "implementer" in errors[0]

    def test_skips_fix_procedure(self):
        files = {
            "change-fix.md": "When quality: production, write regression test.",
        }
        errors = vs.check_56_production_references_implementer(files)
        assert errors == []


# ---------------------------------------------------------------------------
# Check 57: Change Production Precondition
# ---------------------------------------------------------------------------


class TestCheck57ChangeProductionPrecondition:
    def test_passes_with_testing_validation(self):
        content = "If quality: production is set, verify stack.testing is present."
        errors = vs.check_57_change_production_precondition(content)
        assert errors == []

    def test_fails_without_testing_validation(self):
        content = "If quality: production is set, spawn implementer agents."
        errors = vs.check_57_change_production_precondition(content)
        assert len(errors) == 1
        assert "stack.testing" in errors[0]

    def test_fails_without_stack_testing_unconditionally(self):
        content = "Build the feature normally."
        errors = vs.check_57_change_production_precondition(content)
        assert len(errors) == 1
        assert "stack.testing" in errors[0]


# ---------------------------------------------------------------------------
# Check 58: Agent Tool Consistency
# ---------------------------------------------------------------------------


class TestCheck58AgentToolConsistency:
    def test_passes_with_correct_tools(self):
        implementer = "---\ntools:\n  - Read\n  - Edit\n  - Write\n  - Bash\n  - Glob\n  - Grep\ndisallowedTools: []\n---\nContent."
        reviewer = "---\ntools:\n  - Read\n  - Glob\n  - Grep\ndisallowedTools:\n  - Edit\n  - Write\n  - NotebookEdit\n---\nContent."
        files = {
            "implementer.md": implementer,
            "spec-reviewer.md": reviewer,
        }
        errors = vs.check_58_agent_tool_consistency(files)
        assert errors == []

    def test_fails_implementer_missing_tool(self):
        content = "---\ntools:\n  - Read\n  - Glob\ndisallowedTools: []\n---\nContent."
        errors = vs.check_58_agent_tool_consistency({"implementer.md": content})
        assert len(errors) >= 1
        assert any("Edit" in e or "Write" in e or "Bash" in e for e in errors)

    def test_fails_reviewer_has_write_tool(self):
        content = "---\ntools:\n  - Read\n  - Edit\n  - Glob\ndisallowedTools: []\n---\nContent."
        errors = vs.check_58_agent_tool_consistency({"spec-reviewer.md": content})
        assert len(errors) >= 1
        assert any("spec-reviewer" in e for e in errors)

    def test_skips_unknown_agents(self):
        content = "---\ntools:\n  - Read\ndisallowedTools: []\n---\nContent."
        errors = vs.check_58_agent_tool_consistency({"other-agent.md": content})
        assert errors == []


class TestCheck59FrameworkArchetypeCompatibility:
    def test_passes_when_both_files_have_validation(self):
        bootstrap = "web-app archetype requires nextjs. cli archetype requires commander."
        change = "web-app archetype requires nextjs. cli archetype requires commander."
        errors = vs.check_59_framework_archetype_compatibility(bootstrap, change)
        assert errors == []

    def test_fails_when_bootstrap_missing_validation(self):
        bootstrap = "some other content"
        change = "web-app archetype requires nextjs. cli archetype requires commander."
        errors = vs.check_59_framework_archetype_compatibility(bootstrap, change)
        assert len(errors) >= 1
        assert any("bootstrap.md" in e for e in errors)

    def test_fails_when_change_missing_validation(self):
        bootstrap = "web-app archetype requires nextjs. cli archetype requires commander."
        change = "some other content"
        errors = vs.check_59_framework_archetype_compatibility(bootstrap, change)
        assert len(errors) >= 1
        assert any("change.md" in e for e in errors)


# ---------------------------------------------------------------------------
# Check 60: Settings.json hook paths
# ---------------------------------------------------------------------------


class TestCheck60SettingsHookPaths:
    def test_passes_with_valid_hook_paths(self, tmp_path):
        """All hook paths resolve to existing files."""
        hooks_dir = tmp_path / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "test-gate.sh").write_text("#!/bin/bash\nexit 0\n")
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f'"{tmp_path}/.claude/hooks/test-gate.sh"',
                            }
                        ],
                    }
                ]
            }
        }
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text(json.dumps(settings))
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            errors = vs.check_60_settings_hook_paths()
        finally:
            os.chdir(old_cwd)
        assert errors == []

    def test_fails_with_missing_hook_file(self, tmp_path):
        """Hook path points to nonexistent file."""
        (tmp_path / ".claude").mkdir(parents=True)
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": '".claude/hooks/nonexistent.sh"',
                            }
                        ],
                    }
                ]
            }
        }
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings))
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            errors = vs.check_60_settings_hook_paths()
        finally:
            os.chdir(old_cwd)
        assert len(errors) == 1
        assert "does not resolve" in errors[0]

    def test_skips_when_settings_missing(self, tmp_path):
        """No settings.json → no errors."""
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            errors = vs.check_60_settings_hook_paths()
        finally:
            os.chdir(old_cwd)
        assert errors == []


# ---------------------------------------------------------------------------
# Check 61: Footer directive sync
# ---------------------------------------------------------------------------


class TestCheck61FooterDirectiveSync:
    def test_passes_when_directive_matches(self, tmp_path):
        """Footer marker matches hook grep pattern."""
        claude_dir = tmp_path / ".claude"
        hooks_dir = claude_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        (claude_dir / "agent-prompt-footer.md").write_text(
            "<!-- DIRECTIVES:a,b,c -->\n\n## Efficiency\n"
        )
        (hooks_dir / "skill-agent-gate.sh").write_text(
            '#!/bin/bash\nif ! echo "$PROMPT" | grep -q "DIRECTIVES:a,b,c"; then\nexit 1\nfi\n'
        )
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            errors = vs.check_61_footer_directive_sync()
        finally:
            os.chdir(old_cwd)
        assert errors == []

    def test_fails_when_directive_mismatches(self, tmp_path):
        """Footer has different directive list than hook grep."""
        claude_dir = tmp_path / ".claude"
        hooks_dir = claude_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        (claude_dir / "agent-prompt-footer.md").write_text(
            "<!-- DIRECTIVES:x,y,z -->\n"
        )
        (hooks_dir / "skill-agent-gate.sh").write_text(
            '#!/bin/bash\ngrep -q "DIRECTIVES:a,b,c"\n'
        )
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            errors = vs.check_61_footer_directive_sync()
        finally:
            os.chdir(old_cwd)
        assert len(errors) == 1
        assert "does not match" in errors[0]

    def test_skips_when_footer_missing(self, tmp_path):
        """No footer file → no errors."""
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            errors = vs.check_61_footer_directive_sync()
        finally:
            os.chdir(old_cwd)
        assert errors == []


# ---------------------------------------------------------------------------
# Check 63: Canonical Dependency Reference
# ---------------------------------------------------------------------------


class TestCheck63CanonicalDependencyRef:
    _marker = "stack-dependency-validation.md"
    _ref = f"Validate per patterns/{_marker} matrix."

    def _agents(self, with_ref=True):
        return {".claude/agents/gate-keeper.md": self._ref if with_ref else "no ref"}

    def _procs(self, with_ref=True):
        return {".claude/procedures/change-feature.md": self._ref if with_ref else "no ref"}

    def test_passes_when_all_files_have_reference(self):
        errors = vs.check_63_canonical_dependency_ref(
            self._ref, self._ref, self._procs(), self._agents())
        assert errors == []

    def test_fails_when_bootstrap_missing_reference(self):
        errors = vs.check_63_canonical_dependency_ref(
            "no ref", self._ref, self._procs(), self._agents())
        assert len(errors) == 1
        assert "bootstrap.md" in errors[0]

    def test_fails_when_change_missing_reference(self):
        errors = vs.check_63_canonical_dependency_ref(
            self._ref, "no ref", self._procs(), self._agents())
        assert len(errors) == 1
        assert "change.md" in errors[0]

    def test_fails_when_procedure_missing_reference(self):
        errors = vs.check_63_canonical_dependency_ref(
            self._ref, self._ref, self._procs(with_ref=False), self._agents())
        assert len(errors) == 1
        assert "change-feature.md" in errors[0]

    def test_fails_when_procedure_file_absent(self):
        errors = vs.check_63_canonical_dependency_ref(
            self._ref, self._ref, {}, self._agents())
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_fails_when_gate_keeper_missing_reference(self):
        errors = vs.check_63_canonical_dependency_ref(
            self._ref, self._ref, self._procs(), self._agents(with_ref=False))
        assert len(errors) == 1
        assert "gate-keeper.md" in errors[0]

    def test_fails_when_gate_keeper_file_absent(self):
        errors = vs.check_63_canonical_dependency_ref(
            self._ref, self._ref, self._procs(), {})
        assert len(errors) == 1
        assert "gate-keeper.md" in errors[0]
        assert "not found" in errors[0]

    def test_fails_when_all_missing(self):
        errors = vs.check_63_canonical_dependency_ref(
            "no ref", "no ref", self._procs(with_ref=False), self._agents(with_ref=False))
        assert len(errors) == 4


# ---------------------------------------------------------------------------
# Check 65: Playwright-archetype compatibility
# ---------------------------------------------------------------------------


class TestCheck65PlaywrightArchetypeCompatibility:
    def test_passes_when_both_files_have_validation(self):
        bootstrap = "playwright is not compatible with service/cli archetypes"
        change = "if archetype is service or cli and stack.testing is playwright, stop"
        errors = vs.check_65_playwright_archetype_compatibility(bootstrap, change)
        assert errors == []

    def test_fails_when_bootstrap_missing_validation(self):
        bootstrap = "some other content about testing"
        change = "playwright is not compatible with service/cli archetypes"
        errors = vs.check_65_playwright_archetype_compatibility(bootstrap, change)
        assert len(errors) == 1
        assert "bootstrap.md" in errors[0]

    def test_fails_when_change_missing_validation(self):
        bootstrap = "playwright incompatible with service/cli"
        change = "some other content about testing"
        errors = vs.check_65_playwright_archetype_compatibility(bootstrap, change)
        assert len(errors) == 1
        assert "change.md" in errors[0]

    def test_passes_with_alternate_phrasing(self):
        bootstrap = "testing: playwright and archetype is service or cli"
        change = "Playwright incompatible with service and cli archetypes"
        errors = vs.check_65_playwright_archetype_compatibility(bootstrap, change)
        assert errors == []


# ---------------------------------------------------------------------------
# Subprocess integration test — runs the full validator
# ---------------------------------------------------------------------------


class TestValidateSemanticsSubprocess:
    def test_runs_without_crash(self):
        """Verify the validator script runs to completion on the real template."""
        result = subprocess.run(
            ["python3", "scripts/validate-semantics.py"],
            capture_output=True,
            text=True,
        )
        # May have pre-existing errors, but should not crash
        assert result.returncode in (0, 1)
        assert "error" not in result.stderr.lower() or "FAIL:" in result.stderr
