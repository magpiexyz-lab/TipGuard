#!/usr/bin/env bash
# lib.sh — shared functions for Claude Code hooks.
# Source from hooks: source "$(dirname "$0")/lib.sh"
# Call parse_payload first — it reads stdin into PAYLOAD.
# Do NOT register this file in settings.json — it is sourced, not invoked.
#
# Facade: sources domain modules. lib-core.sh MUST be first
# (other modules call read_json_field, deny, get_branch from core).

_HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$_HOOK_LIB_DIR/lib-core.sh"
source "$_HOOK_LIB_DIR/lib-state.sh"
source "$_HOOK_LIB_DIR/lib-verdict.sh"
source "$_HOOK_LIB_DIR/lib-artifacts.sh"
source "$_HOOK_LIB_DIR/lib-merge.sh"
