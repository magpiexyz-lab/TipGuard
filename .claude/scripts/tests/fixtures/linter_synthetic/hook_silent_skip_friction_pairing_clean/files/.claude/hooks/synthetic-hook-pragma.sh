#!/usr/bin/env bash
# Synthetic clean fixture: pragma annotation on directly preceding line pairs the exit.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
parse_payload
FILE_PATH=$(read_payload_field "tool_input.file_path")
# friction-skip: trivial-fast-path — no FILE_PATH means no Write/Edit target.
[[ -z "$FILE_PATH" ]] && exit 0
# friction-skip: post-validation — terminal exit after authoritative path.
exit 0
