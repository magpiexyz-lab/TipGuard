#!/usr/bin/env python3
"""Tests for level ↔ stack validation in validate-experiment.py."""

import copy
import os
import subprocess
import tempfile

import pytest
import yaml


SCRIPT = os.path.join(os.path.dirname(__file__), "validate-experiment.py")

# Minimal valid experiment.yaml base — no level, no forbidden stack keys
BASE_YAML = {
    "name": "test-experiment",
    "owner": "test-team",
    "description": "A test experiment",
    "thesis": "If we test, then we learn, as measured by tests passing",
    "target_user": "developers testing validators",
    "distribution": "word of mouth",
    "behaviors": [{"id": "b-01", "hypothesis_id": "h-01", "given": "A user", "when": "They act", "then": "They see result", "level": 1}],
    "stack": {
        "services": [
            {
                "name": "app",
                "runtime": "nextjs",
                "hosting": "vercel",
            }
        ],
    },
    "golden_path": [
        {"step": "Visit landing page"},
        {"step": "Click CTA"},
    ],
}


def run_validator(yaml_data: dict) -> subprocess.CompletedProcess:
    """Write yaml_data to a temp dir and run validate-experiment.py."""
    with tempfile.TemporaryDirectory() as tmpdir:
        experiment_dir = os.path.join(tmpdir, "experiment")
        os.makedirs(experiment_dir)
        yaml_path = os.path.join(experiment_dir, "experiment.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_data, f)
        return subprocess.run(
            ["python3", SCRIPT],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )


def make_yaml(**overrides) -> dict:
    """Deep-copy BASE_YAML and apply overrides (supports dot notation for stack keys)."""
    data = copy.deepcopy(BASE_YAML)
    for key, val in overrides.items():
        if key.startswith("stack."):
            stack_key = key[len("stack."):]
            data["stack"][stack_key] = val
        else:
            data[key] = val
    return data


def make_hypothesis(category: str, hypothesis_id: str = "h-01") -> dict:
    return {
        "id": hypothesis_id,
        "category": category,
        "statement": f"Test {category} hypothesis",
        "metric": {
            "formula": "event_a / event_b",
            "threshold": 0.05,
            "operator": "gte",
        },
        "priority_score": 80,
        "experiment_level": 3,
        "status": "pending",
    }


# --- L1 tests ---

def test_l1_with_database_fails():
    data = make_yaml(level=1, **{"stack.database": "supabase"})
    result = run_validator(data)
    assert result.returncode == 1
    assert "level 1 cannot have stack.database" in result.stdout


def test_l1_with_auth_fails():
    data = make_yaml(level=1, **{"stack.auth": "supabase"})
    result = run_validator(data)
    assert result.returncode == 1
    assert "level 1 cannot have stack.auth" in result.stdout


def test_l1_with_payment_fails():
    data = make_yaml(level=1, **{"stack.payment": "stripe"})
    result = run_validator(data)
    assert result.returncode == 1
    assert "level 1 cannot have stack.payment" in result.stdout


def test_l1_clean_passes():
    data = make_yaml(level=1)
    result = run_validator(data)
    assert result.returncode != 1  # 0 or 2 (warnings OK)


# --- L2 tests ---

def test_l2_with_database_passes():
    data = make_yaml(level=2, **{"stack.database": "supabase"})
    result = run_validator(data)
    assert result.returncode != 1


def test_l2_with_auth_fails():
    data = make_yaml(level=2, **{"stack.auth": "supabase"})
    result = run_validator(data)
    assert result.returncode == 1
    assert "level 2 cannot have stack.auth" in result.stdout


def test_l2_with_payment_fails():
    data = make_yaml(level=2, **{"stack.payment": "stripe"})
    result = run_validator(data)
    assert result.returncode == 1
    assert "level 2 cannot have stack.payment" in result.stdout


# --- L3 tests ---

def test_l3_all_with_monetize_passes():
    data = make_yaml(
        level=3,
        **{
            "stack.database": "supabase",
            "stack.auth": "supabase",
            "stack.payment": "stripe",
        },
    )
    data["hypotheses"] = [make_hypothesis("monetize")]
    result = run_validator(data)
    assert result.returncode != 1


def test_l3_payment_without_monetize_fails():
    data = make_yaml(
        level=3,
        **{
            "stack.database": "supabase",
            "stack.auth": "supabase",
            "stack.payment": "stripe",
        },
    )
    data["hypotheses"] = [make_hypothesis("demand")]
    result = run_validator(data)
    assert result.returncode == 1
    assert "requires at least one hypothesis with category 'monetize'" in result.stdout


def test_l3_payment_with_monetize_passes():
    data = make_yaml(
        level=3,
        **{
            "stack.database": "supabase",
            "stack.auth": "supabase",
            "stack.payment": "stripe",
        },
    )
    data["hypotheses"] = [
        make_hypothesis("demand", "h-01"),
        make_hypothesis("monetize", "h-02"),
    ]
    result = run_validator(data)
    assert result.returncode != 1


# --- No level ---

def test_no_level_skips_validation():
    """When level is absent, level-stack validation is skipped entirely."""
    data = make_yaml(**{
        "stack.database": "supabase",
        "stack.auth": "supabase",
        "stack.payment": "stripe",
    })
    # No level field — should not trigger level-stack errors
    result = run_validator(data)
    assert result.returncode != 1
