#!/usr/bin/env bash
# verify-linter.sh — Detect VERIFY-postcondition drift AND cross-file contradictions.
# Thin wrapper: parses CLI flags, exports VL_* env vars, and invokes the
# Python package at .claude/scripts/lib/linter/. All logic lives in the
# package (see lib/linter/runner.py for the entry point).
#
# CLI flags (preserved verbatim from the original heredoc contract):
#   --json              Emit machine-readable JSON to stdout (no human report)
#   --cache <path>      Write findings to cache file (used by lifecycle-finalize.sh)
#   --warn-only         Always exit 0 (still print findings; for non-blocking checks)
#   --strict-aoc        AOC findings always block (regardless of --warn-only)
#   --rules <path>      Override default rules file path
#
# Exit codes:
#   0  clean (or --warn-only suppressed all findings)
#   1  findings present (per --warn-only / --strict-aoc semantics)
#   2  unknown flag (literal stderr: "ERROR: unknown flag: <X>")

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGISTRY="$REPO_ROOT/.claude/patterns/state-registry.json"
RULES="$REPO_ROOT/.claude/patterns/template-coherence-rules.json"

JSON_OUT=""
CACHE_FILE=""
WARN_ONLY=""
STRICT_AOC=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)        JSON_OUT="1"; shift ;;
    --cache)       CACHE_FILE="$2"; shift 2 ;;
    --warn-only)   WARN_ONLY="1"; shift ;;
    --strict-aoc)  STRICT_AOC="1"; shift ;;
    --rules)       RULES="$2"; shift 2 ;;
    *)             echo "ERROR: unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$REGISTRY" ]]; then
  echo "ERROR: state-registry.json not found at $REGISTRY" >&2
  exit 1
fi

export VL_JSON_OUT="$JSON_OUT"
export VL_CACHE_FILE="$CACHE_FILE"
export VL_WARN_ONLY="$WARN_ONLY"
export VL_STRICT_AOC="$STRICT_AOC"
export VL_RULES_PATH="$RULES"
export VL_REPO_ROOT="$REPO_ROOT"

exec python3 "$REPO_ROOT/.claude/scripts/lib/linter/cli.py"
