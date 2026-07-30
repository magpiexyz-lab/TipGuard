#!/usr/bin/env bash
# lib-verdict.sh — Backward-compat shim. Real implementations split into
# lib-verdict-consistency.sh, lib-gate-verdicts.sh, lib-hard-gate.sh
# (refactored 2026-04). Sourced via lib.sh facade. Do NOT source directly.
_HOOK_LIB_DIR="${_HOOK_LIB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
source "$_HOOK_LIB_DIR/lib-verdict-consistency.sh"
source "$_HOOK_LIB_DIR/lib-gate-verdicts.sh"
source "$_HOOK_LIB_DIR/lib-hard-gate.sh"
